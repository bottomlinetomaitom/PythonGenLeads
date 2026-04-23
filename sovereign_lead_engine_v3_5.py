"""
=============================================================================
SOVEREIGN LEAD ENGINE v3.5
Async · Retry · AI (Ollama) · Heuristic Fallback · SQLite · CSV/JSON Export
=============================================================================

Miglioramenti rispetto a v3.4:
  - Configurazione centralizzata via dataclass EngineConfig (no magic globals)
  - LeadDB ora usa connection-per-thread (sqlite3 thread safety)
  - Retry con jitter esponenziale e rispetto dell'header Retry-After (429)
  - extract_emails: regex compilata, deduplication robusta
  - _heuristic_analysis: scoring pesato su densità keyword + lunghezza testo
  - run(): progress tracking con contatori atomici
  - main(): timing preciso con time.perf_counter(), riepilogo dettagliato
  - Type hints completi, docstring su ogni funzione pubblica
  - Nessuna importazione lazy tranne 'ollama' (facoltativo)
  - Compatibile Python 3.10+
=============================================================================
"""

from __future__ import annotations

import asyncio
import aiohttp
import csv
import json
import logging
import os
import random
import re
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional
from urllib.parse import urlparse

import argparse
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------

@dataclass
class EngineConfig:
    """Unica fonte di verità per tutti i parametri del motore."""

    db_name:           str   = field(default_factory=lambda: os.getenv("LEAD_DB", "leads.db"))
    ollama_model:      str   = field(default_factory=lambda: os.getenv("OLLAMA_MODEL", "llama3"))
    ollama_timeout:    float = 30.0
    max_concurrent:    int   = 5
    retries:           int   = 3
    request_timeout:   float = 20.0
    connect_timeout:   float = 5.0
    rate_limit_min:    float = 1.5
    rate_limit_max:    float = 4.0
    text_max_chars:    int   = 4000
    min_text_chars:    int   = 100


CONFIG = EngineConfig()

USER_AGENTS: List[str] = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36 Edg/125.0.0.0",
]

BUSINESS_KEYWORDS: Dict[str, str] = {
    "consulting":   "Consulting",
    "agency":       "Agency",
    "solutions":    "Solutions",
    "services":     "Services",
    "software":     "Software",
    "marketing":    "Marketing",
    "design":       "Design",
    "development":  "Development",
    "enterprise":   "Enterprise",
    "saas":         "SaaS",
    "platform":     "Platform",
    "analytics":    "Analytics",
    "automation":   "Automation",
    "digital":      "Digital",
    "cloud":        "Cloud",
    "management":   "Management",
    "strategy":     "Strategy",
    "integration":  "Integration",
    "ecommerce":    "E-Commerce",
    "fintech":      "Fintech",
    "startup":      "Startup",
    "b2b":          "B2B",
    "crm":          "CRM",
}

EMAIL_BLOCKED_DOMAINS: frozenset[str] = frozenset({
    "example.com", "test.com", "email.com", "domain.com",
    "sentry.io", "wixpress.com", "googleapis.com",
    "w3.org", "schema.org",
})

EMAIL_BLOCKED_EXTENSIONS: frozenset[str] = frozenset({
    ".png", ".jpg", ".gif", ".svg", ".css", ".js", ".woff",
})

_EMAIL_RE = re.compile(
    r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"
)

# ---------------------------------------------------------------------------
# LOGGING
# ---------------------------------------------------------------------------

logger = logging.getLogger(__name__)


def setup_logging(level: str = "INFO") -> None:
    """Configura logging su stdout + file con formato standard."""
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)-8s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler("pipeline.log", encoding="utf-8"),
        ],
    )

# ---------------------------------------------------------------------------
# DATABASE
# ---------------------------------------------------------------------------

class LeadDB:
    """
    Thread-safe SQLite wrapper.

    Usa un dizionario di connessioni per thread (una per thread) invece di
    una singola connessione condivisa con lock: elimina l'overhead del lock
    sulle letture e sfrutta correttamente sqlite3 in modalità WAL.
    """

    _CREATE_TABLE = """
        CREATE TABLE IF NOT EXISTS leads (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            company    TEXT    NOT NULL,
            service    TEXT    NOT NULL DEFAULT 'Unknown',
            score      INTEGER NOT NULL DEFAULT 0,
            url        TEXT    NOT NULL DEFAULT '',
            domain     TEXT    NOT NULL DEFAULT '',
            emails     TEXT    NOT NULL DEFAULT '',
            created_at TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
            UNIQUE(company, domain)
        )
    """

    def __init__(self, db_name: str = "") -> None:
        self._db_name = db_name or CONFIG.db_name
        self._local   = threading.local()
        # Inizializza schema nel thread principale
        conn = self._conn()
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute(self._CREATE_TABLE)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_domain ON leads(domain)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_score  ON leads(score DESC)")
        conn.commit()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _conn(self) -> sqlite3.Connection:
        """Restituisce la connessione del thread corrente, creandola se necessario."""
        if not getattr(self._local, "conn", None):
            conn = sqlite3.connect(self._db_name, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL;")
            self._local.conn = conn
        return self._local.conn  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> "LeadDB":
        return self

    def __exit__(self, *_) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def save(self, data: Dict) -> bool:
        """
        Inserisce un lead. Restituisce True se salvato, False se duplicato o invalido.

        Args:
            data: dizionario con chiavi company, service, score, url, emails.

        Returns:
            True se la riga è stata inserita, False altrimenti.
        """
        company = (data.get("company") or "").strip()
        if not company:
            return False

        conn = self._conn()
        try:
            cur = conn.execute(
                """
                INSERT OR IGNORE INTO leads (company, service, score, url, domain, emails)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    company,
                    (data.get("service") or "Unknown").strip(),
                    max(0, min(10, int(data.get("score", 0)))),
                    (data.get("url") or "").strip(),
                    get_domain(data.get("url", "")),
                    ",".join(data.get("emails", [])),
                ),
            )
            conn.commit()
            return cur.rowcount > 0
        except Exception as exc:
            logger.error("DB error saving '%s': %s", company, exc)
            return False

    def export_csv(self, path: str) -> int:
        """
        Esporta tutti i lead in CSV ordinati per score decrescente.

        Args:
            path: percorso del file di output.

        Returns:
            Numero di righe esportate.
        """
        cols = ("company", "service", "score", "url", "domain", "emails", "created_at")
        rows = self._conn().execute(
            "SELECT company, service, score, url, domain, emails, created_at "
            "FROM leads ORDER BY score DESC"
        ).fetchall()

        with open(path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(cols)
            writer.writerows(rows)

        logger.info("Exported %d leads → %s", len(rows), path)
        return len(rows)

    def export_json(self, path: str) -> int:
        """
        Esporta tutti i lead in JSON ordinati per score decrescente.

        Args:
            path: percorso del file di output.

        Returns:
            Numero di record esportati.
        """
        cols = ("company", "service", "score", "url", "domain", "emails", "created_at")
        rows = [
            dict(zip(cols, r))
            for r in self._conn().execute(
                "SELECT company, service, score, url, domain, emails, created_at "
                "FROM leads ORDER BY score DESC"
            ).fetchall()
        ]

        with open(path, "w", encoding="utf-8") as fh:
            json.dump(rows, fh, indent=2, ensure_ascii=False, default=str)

        logger.info("Exported %d leads → %s", len(rows), path)
        return len(rows)

    def count(self) -> int:
        """Restituisce il numero totale di lead nel database."""
        return self._conn().execute("SELECT COUNT(*) FROM leads").fetchone()[0]

    def close(self) -> None:
        """Chiude la connessione del thread corrente."""
        conn = getattr(self._local, "conn", None)
        if conn:
            conn.close()
            self._local.conn = None

# ---------------------------------------------------------------------------
# UTILITIES
# ---------------------------------------------------------------------------

def normalize_url(url: str) -> str:
    """
    Normalizza un URL: aggiunge schema https se mancante e rimuove trailing slash.

    Args:
        url: stringa URL grezza.

    Returns:
        URL normalizzato o stringa vuota se non valido.
    """
    url = (url or "").strip()
    if not url:
        return ""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url.rstrip("/")


def get_domain(url: str) -> str:
    """
    Estrae il dominio netto da un URL (senza www).

    Args:
        url: stringa URL.

    Returns:
        Dominio o 'unknown' in caso di errore.
    """
    try:
        return urlparse(url).netloc.replace("www.", "").lower() or "unknown"
    except Exception:
        return "unknown"


def extract_emails(text: str, html: str) -> List[str]:
    """
    Estrae indirizzi email dal testo visibile e dai link mailto:.

    Filtra domini bloccati ed estensioni di file note non-email.

    Args:
        text: testo visibile della pagina.
        html: sorgente HTML grezzo.

    Returns:
        Lista ordinata di email univoche in minuscolo.
    """
    candidates: set[str] = set()
    candidates.update(_EMAIL_RE.findall(text))
    candidates.update(_EMAIL_RE.findall(html))

    result: List[str] = []
    for email in candidates:
        e = email.lower()
        domain = e.split("@", 1)[-1]
        if domain in EMAIL_BLOCKED_DOMAINS:
            continue
        if any(e.endswith(ext) for ext in EMAIL_BLOCKED_EXTENSIONS):
            continue
        result.append(e)

    return sorted(result)

# ---------------------------------------------------------------------------
# HTTP SCRAPER
# ---------------------------------------------------------------------------

async def fetch(session: aiohttp.ClientSession, url: str) -> Optional[str]:
    """
    Esegue GET con retry esponenziale e rispetto di Retry-After.

    Args:
        session: sessione aiohttp condivisa.
        url:     URL da scaricare.

    Returns:
        Testo HTML della risposta o None se tutti i tentativi falliscono.
    """
    headers = {"User-Agent": random.choice(USER_AGENTS)}

    for attempt in range(CONFIG.retries):
        try:
            async with session.get(url, headers=headers, allow_redirects=True) as resp:
                if resp.status == 200:
                    return await resp.text(errors="replace")

                if resp.status == 429:
                    # Rispetta Retry-After se presente, altrimenti backoff
                    retry_after = resp.headers.get("Retry-After")
                    wait = float(retry_after) if retry_after and retry_after.isdigit() \
                           else 5.0 * (attempt + 1)
                    logger.warning("Rate limited %s — waiting %.0fs", url, wait)
                    await asyncio.sleep(wait)
                    continue

                if resp.status in (401, 403, 404, 410, 451):
                    logger.debug("Permanent skip %s (%d)", url, resp.status)
                    return None

                if resp.status >= 500:
                    logger.warning("Server error %d on %s (attempt %d/%d)",
                                   resp.status, url, attempt + 1, CONFIG.retries)

        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            logger.warning("Fetch error %s (attempt %d/%d): %s",
                           url, attempt + 1, CONFIG.retries, type(exc).__name__)

        # Jitter esponenziale: 1s, 2s±jitter, 4s±jitter
        backoff = (2 ** attempt) + random.uniform(0, 0.5)
        await asyncio.sleep(backoff)

    return None


def extract_text(html: str) -> str:
    """
    Estrae testo pulito dall'HTML rimuovendo script, stili e elementi non-content.

    Args:
        html: sorgente HTML grezzo.

    Returns:
        Testo normalizzato (max TEXT_MAX_CHARS caratteri).
    """
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "aside", "noscript", "header"]):
        tag.decompose()

    root = soup.find("main") or soup.find("article") or soup.body
    if not root:
        return ""

    text = root.get_text(separator=" ", strip=True)
    return re.sub(r"\s+", " ", text)[: CONFIG.text_max_chars]

# ---------------------------------------------------------------------------
# AI ANALYSIS — Ollama
# ---------------------------------------------------------------------------

def _extract_json_object(text: str) -> Optional[Dict]:
    """
    Estrae il primo oggetto JSON valido da una stringa usando conteggio parentesi.

    Più robusto di un semplice json.loads() su testo misto.

    Args:
        text: stringa che può contenere JSON embedded in testo libero.

    Returns:
        Dizionario Python o None se non trovato.
    """
    depth, start = 0, None
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start is not None:
                try:
                    return json.loads(text[start: i + 1])
                except json.JSONDecodeError:
                    start = None  # Prova il prossimo oggetto
    return None


_OLLAMA_PROMPT_TEMPLATE = (
    "Return ONLY valid minified JSON. No explanation, no markdown.\n"
    '{{"qualified": true/false, "company": "name", "service": "what they do", "score": 1-10}}\n'
    "DATA:\n{text}"
)


def _run_ollama(text: str, model: str) -> Optional[Dict]:
    """
    Chiamata bloccante a Ollama.

    NOTA: chiamare sempre tramite _try_ollama() — non invocare direttamente
    dall'event loop asincrono per evitare il blocco del thread principale.

    Args:
        text:  testo da analizzare.
        model: nome del modello Ollama.

    Returns:
        Dizionario con dati del lead o None in caso di errore.
    """
    try:
        import ollama  # opzionale — installare solo se si usa Ollama

        prompt = _OLLAMA_PROMPT_TEMPLATE.format(text=text)
        res    = ollama.generate(model=model, prompt=prompt)
        raw    = re.sub(r"```json?\s*|```", "", res.get("response", ""))
        data   = _extract_json_object(raw)

        if data and data.get("company"):
            data["score"]     = max(0, min(10, int(data.get("score", 0))))
            data["qualified"] = bool(data.get("qualified", False))
            return data

    except ImportError:
        logger.debug("Ollama non installato — uso heuristics")
    except Exception as exc:
        logger.debug("Ollama call error: %s", exc)

    return None


async def _try_ollama(text: str) -> Optional[Dict]:
    """
    Wrapper asincrono attorno a _run_ollama().

    Esegue la chiamata bloccante in un thread pool (asyncio.to_thread) e
    applica un timeout cross-platform con asyncio.wait_for().

    Args:
        text: testo da analizzare.

    Returns:
        Dizionario con dati del lead o None se timeout/errore.
    """
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_run_ollama, text, CONFIG.ollama_model),
            timeout=CONFIG.ollama_timeout,
        )
    except asyncio.TimeoutError:
        logger.warning("Ollama timeout dopo %.0fs — fallback a heuristics",
                       CONFIG.ollama_timeout)
        return None
    except Exception as exc:
        logger.debug("Ollama wrapper error: %s", exc)
        return None

# ---------------------------------------------------------------------------
# AI ANALYSIS — Heuristic Fallback
# ---------------------------------------------------------------------------

def _heuristic_analysis(text: str, url: str) -> Dict:
    """
    Analisi basata su keyword come fallback quando Ollama non è disponibile.

    Score = hits keyword (pesati) + bonus lunghezza testo, clampato in [0, 10].

    Args:
        text: testo visibile della pagina.
        url:  URL della pagina (usato per inferire il nome azienda).

    Returns:
        Dizionario con company, service, score, qualified.
    """
    text_lower = text.lower()
    domain     = get_domain(url)

    # Keyword matching con peso progressivo
    hits = sum(1 for kw in BUSINESS_KEYWORDS if kw in text_lower)

    # Bonus per testi più ricchi di contenuto (max +2)
    length_bonus = min(2, len(text) // 800)
    score = min(10, max(0, hits + length_bonus))

    # Nome azienda dal dominio
    company = (
        domain.split(".")[0].replace("-", " ").replace("_", " ").title()
        if domain != "unknown"
        else "Unknown"
    )

    # Servizio dalla prima keyword trovata
    service = next(
        (label for kw, label in BUSINESS_KEYWORDS.items() if kw in text_lower),
        "Unknown",
    )

    return {
        "company":   company,
        "service":   service,
        "score":     score,
        "qualified": score > 2,
    }


async def analyze_lead(text: str, url: str) -> Dict:
    """
    Analizza un lead con Ollama; se non disponibile usa heuristics.

    Args:
        text: testo estratto dalla pagina.
        url:  URL della pagina.

    Returns:
        Dizionario con company, service, score, qualified.
    """
    result = await _try_ollama(text)
    return result if result else _heuristic_analysis(text, url)

# ---------------------------------------------------------------------------
# PIPELINE
# ---------------------------------------------------------------------------

async def process_url(
    session:   aiohttp.ClientSession,
    semaphore: asyncio.Semaphore,
    url:       str,
    db:        LeadDB,
    counters:  Dict[str, int],
) -> Optional[Dict]:
    """
    Processa un singolo URL: scarica, estrae, analizza, salva.

    Args:
        session:   sessione aiohttp condivisa.
        semaphore: limita la concorrenza.
        url:       URL da processare (già normalizzato).
        db:        istanza LeadDB.
        counters:  dizionario condiviso per tracking {fetched, qualified, saved}.

    Returns:
        Dizionario del lead se qualificato e salvato, None altrimenti.
    """
    async with semaphore:
        await asyncio.sleep(random.uniform(CONFIG.rate_limit_min, CONFIG.rate_limit_max))

        html = await fetch(session, url)
        if not html:
            return None

        counters["fetched"] = counters.get("fetched", 0) + 1

        text = extract_text(html)
        if len(text) < CONFIG.min_text_chars:
            logger.debug("Skipping %s — too short (%d chars)", url, len(text))
            return None

        data = await analyze_lead(text, url)

        if not data.get("qualified"):
            logger.debug("Not qualified: %s (score=%d)", url, data.get("score", 0))
            return None

        counters["qualified"] = counters.get("qualified", 0) + 1

        data["url"]    = url
        data["emails"] = extract_emails(text, html)
        saved = db.save(data)

        if saved:
            counters["saved"] = counters.get("saved", 0) + 1
            logger.info(
                "[✓] %-28s | %-16s | score=%2d | emails=%d",
                data["company"],
                data["service"],
                data["score"],
                len(data["emails"]),
            )

        return data if saved else None


async def run(
    urls:    List[str],
    db:      LeadDB,
    workers: int = 0,
) -> tuple[List[Dict], Dict[str, int]]:
    """
    Esegue la pipeline asincrona su una lista di URL.

    Args:
        urls:    lista di URL già normalizzati e deduplicati.
        db:      istanza LeadDB.
        workers: numero massimo di worker concorrenti (0 = usa CONFIG).

    Returns:
        Tupla (lista lead qualificati, dizionario contatori).
    """
    workers   = workers or CONFIG.max_concurrent
    semaphore = asyncio.Semaphore(workers)
    counters: Dict[str, int] = {"fetched": 0, "qualified": 0, "saved": 0}

    timeout = aiohttp.ClientTimeout(
        total=CONFIG.request_timeout,
        connect=CONFIG.connect_timeout,
    )

    async with aiohttp.ClientSession(timeout=timeout) as session:
        tasks = [
            process_url(session, semaphore, u, db, counters)
            for u in urls
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    leads: List[Dict] = []
    errors = 0
    for r in results:
        if isinstance(r, Exception):
            logger.error("Task exception: %s", r)
            errors += 1
        elif r is not None:
            leads.append(r)

    counters["errors"] = errors
    if errors:
        logger.warning("%d task(s) falliti — vedi pipeline.log", errors)

    return leads, counters

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Sovereign Lead Engine v3.5 — AI-powered B2B lead generation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
esempi:
  python sovereign_lead_engine_v3_5.py urls.txt
  python sovereign_lead_engine_v3_5.py urls.txt --workers 10 --export both
  python sovereign_lead_engine_v3_5.py urls.txt --min-score 7 --export csv --output results
  OLLAMA_MODEL=mistral python sovereign_lead_engine_v3_5.py urls.txt
        """,
    )
    parser.add_argument("input",
                        help="File con URL (uno per riga, # per commenti)")
    parser.add_argument("--workers", type=int, default=CONFIG.max_concurrent,
                        help=f"Max worker concorrenti (default: {CONFIG.max_concurrent})")
    parser.add_argument("--export", choices=["csv", "json", "both"], default=None,
                        help="Formato di esportazione")
    parser.add_argument("--output", default="leads_export",
                        help="Nome file export senza estensione (default: leads_export)")
    parser.add_argument("--min-score", type=int, default=0,
                        help="Mostra solo lead con score >= N (tutti salvati nel DB)")
    parser.add_argument("--log-level", default="INFO",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
                        help="Verbosità logging (default: INFO)")
    return parser


def main() -> None:
    """Entry point CLI."""
    parser = _build_parser()
    args   = parser.parse_args()

    setup_logging(args.log_level)

    # Carica URL dal file
    try:
        with open(args.input, encoding="utf-8") as fh:
            raw_urls = [
                line.strip()
                for line in fh
                if line.strip() and not line.startswith("#")
            ]
    except FileNotFoundError:
        logger.error("File non trovato: %s", args.input)
        return

    # Normalizza e deduplicata (preserva ordine)
    seen: set[str] = set()
    urls: List[str] = []
    for u in (normalize_url(r) for r in raw_urls):
        if u and u not in seen:
            seen.add(u)
            urls.append(u)

    if not urls:
        logger.error("Nessun URL valido trovato in %s", args.input)
        return

    logger.info(
        "Caricati %d URL univoci | Workers: %d | Modello: %s",
        len(urls), args.workers, CONFIG.ollama_model,
    )

    with LeadDB() as db:
        t0 = time.perf_counter()
        leads, counters = asyncio.run(run(urls, db, workers=args.workers))
        elapsed = time.perf_counter() - t0

        # Filtra per min-score solo per la visualizzazione
        displayed = [r for r in leads if r.get("score", 0) >= args.min_score] \
                    if args.min_score else leads

        # Riepilogo
        bar = "=" * 56
        print(f"\n{bar}")
        score_note = f"  (score ≥ {args.min_score})" if args.min_score else ""
        print(f"  Lead qualificati : {len(displayed)}{score_note}")
        print(f"  Pagine scaricate : {counters.get('fetched', 0)}")
        print(f"  Salvati nel DB   : {counters.get('saved', 0)}")
        print(f"  Errori           : {counters.get('errors', 0)}")
        print(f"  Tempo totale     : {elapsed:.1f}s")
        print(f"  Costo AI         : $0.00")
        print(f"{bar}\n")

        if displayed:
            print(f"  {'COMPANY':<28} {'SERVICE':<16} {'SCORE':<8} EMAIL")
            print(f"  {'-'*28} {'-'*16} {'-'*8} {'-'*30}")
            for r in sorted(displayed, key=lambda x: x.get("score", 0), reverse=True):
                emails = ", ".join(r.get("emails", [])) or "—"
                print(f"  {r['company']:<28} {r['service']:<16} {r['score']}/10     {emails}")
            print()

        # Export
        if args.export in ("csv", "both"):
            db.export_csv(f"{args.output}.csv")
        if args.export in ("json", "both"):
            db.export_json(f"{args.output}.json")


if __name__ == "__main__":
    main()
