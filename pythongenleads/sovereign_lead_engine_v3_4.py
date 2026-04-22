# =========================
# SOVEREIGN LEAD ENGINE v3.4 (PRODUCTION)
# Async + Retry + AI + Export + CLI
# github.com/YOUR_USERNAME/sovereign-lead-engine
# =========================

import asyncio
import aiohttp
import sqlite3
import threading
import logging
import random
import json
import re
import os
import csv
import argparse
from bs4 import BeautifulSoup
from urllib.parse import urlparse
from typing import List, Dict, Optional
from datetime import datetime

# =========================
# CONFIG
# =========================

DB_NAME          = os.getenv("LEAD_DB", "leads.db")
TIMEOUT          = aiohttp.ClientTimeout(total=20, connect=5)
MAX_CONCURRENT   = 5
RATE_LIMIT_DELAY = (1.5, 4.0)
TEXT_MAX_CHARS   = 4000
RETRIES          = 3
OLLAMA_TIMEOUT   = 30   # seconds — cross-platform, uses asyncio.wait_for
OLLAMA_MODEL     = os.getenv("OLLAMA_MODEL", "llama3")

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36 Edg/125.0.0.0",
]

BUSINESS_KEYWORDS = [
    "consulting", "agency", "solutions", "services", "software", "marketing",
    "design", "development", "enterprise", "saas", "platform", "analytics",
    "automation", "digital", "cloud", "management", "strategy", "partner",
    "integration", "ecommerce", "fintech", "startup", "b2b", "crm",
]

EMAIL_BLOCKED_DOMAINS = {
    "example.com", "test.com", "email.com", "domain.com", "sentry.io",
    "wixpress.com", "googleapis.com", "w3.org", "schema.org",
}

EMAIL_BLOCKED_EXTENSIONS = {".png", ".jpg", ".gif", ".svg", ".css", ".js", ".woff"}

# =========================
# LOGGING
# =========================

logger = logging.getLogger(__name__)


def setup_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler("pipeline.log", encoding="utf-8"),
        ],
    )

# =========================
# DATABASE
# =========================

class LeadDB:
    """Thread-safe SQLite wrapper with WAL mode and context manager support."""

    def __init__(self, db_name: str = DB_NAME):
        self.conn = sqlite3.connect(db_name, check_same_thread=False)
        self._lock = threading.Lock()
        self.conn.execute("PRAGMA journal_mode=WAL;")
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS leads (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                company    TEXT,
                service    TEXT,
                score      INTEGER,
                url        TEXT,
                domain     TEXT,
                emails     TEXT    DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(company, domain)
            )
        """)
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_domain ON leads(domain)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_score  ON leads(score DESC)")
        self.conn.commit()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False

    def save(self, data: Dict) -> bool:
        """Insert a lead. Returns True on success, False if skipped/duplicate."""
        company = (data.get("company") or "").strip()
        if not company:
            return False
        with self._lock:
            try:
                cur = self.conn.execute(
                    """INSERT OR IGNORE INTO leads
                       (company, service, score, url, domain, emails)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        company,
                        (data.get("service") or "Unknown").strip(),
                        max(0, min(10, int(data.get("score", 0)))),
                        (data.get("url") or "").strip(),
                        get_domain(data.get("url", "")),
                        ",".join(data.get("emails", [])),
                    ),
                )
                self.conn.commit()
                return cur.rowcount > 0
            except Exception as e:
                logger.error(f"DB error saving '{company}': {e}")
                return False

    def export_csv(self, path: str) -> int:
        with self._lock:
            cur = self.conn.execute(
                "SELECT company, service, score, url, domain, emails, created_at "
                "FROM leads ORDER BY score DESC"
            )
            rows = cur.fetchall()
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["company", "service", "score", "url", "domain", "emails", "created_at"])
            w.writerows(rows)
        logger.info(f"Exported {len(rows)} leads → {path}")
        return len(rows)

    def export_json(self, path: str) -> int:
        cols = ["company", "service", "score", "url", "domain", "emails", "created_at"]
        with self._lock:
            cur = self.conn.execute(
                "SELECT company, service, score, url, domain, emails, created_at "
                "FROM leads ORDER BY score DESC"
            )
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        with open(path, "w", encoding="utf-8") as f:
            json.dump(rows, f, indent=2, ensure_ascii=False)
        logger.info(f"Exported {len(rows)} leads → {path}")
        return len(rows)

    def count(self) -> int:
        with self._lock:
            return self.conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0]

    def close(self):
        self.conn.close()

# =========================
# UTILS
# =========================

def normalize_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url.rstrip("/")


def get_domain(url: str) -> str:
    try:
        return urlparse(url).netloc.replace("www.", "") or "unknown"
    except Exception:
        return "unknown"


def extract_emails(text: str, html: str) -> List[str]:
    """Extract emails from visible text AND mailto: links."""
    pattern = r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"
    found: set = set()

    found.update(re.findall(pattern, text))
    found.update(re.findall(r'mailto:(' + pattern + ')', html))

    result = []
    for e in found:
        e_low = e.lower()
        if any(e_low.endswith(f"@{b}") for b in EMAIL_BLOCKED_DOMAINS):
            continue
        if any(ext in e_low for ext in EMAIL_BLOCKED_EXTENSIONS):
            continue
        result.append(e_low)

    return sorted(set(result))

# =========================
# SCRAPER
# =========================

async def fetch(session: aiohttp.ClientSession, url: str) -> Optional[str]:
    headers = {"User-Agent": random.choice(USER_AGENTS)}
    for attempt in range(RETRIES):
        try:
            async with session.get(url, headers=headers, allow_redirects=True) as resp:
                if resp.status == 200:
                    return await resp.text(errors="replace")
                if resp.status == 429:
                    wait = 5 * (attempt + 1)
                    logger.warning(f"Rate limited on {url} — waiting {wait}s")
                    await asyncio.sleep(wait)
                    continue
                if resp.status in (403, 404, 410, 451):
                    logger.debug(f"Permanent skip {url} ({resp.status})")
                    return None
                if resp.status >= 500:
                    logger.warning(f"Server error {resp.status} on {url} (attempt {attempt+1})")
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            logger.warning(f"Fetch error {url} (attempt {attempt+1}): {type(e).__name__}")
        await asyncio.sleep(1.5 ** attempt)   # exponential backoff: 1s, 1.5s, 2.25s
    return None


def extract_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "aside", "noscript"]):
        tag.decompose()
    main = soup.find("main") or soup.find("article") or soup.body
    if not main:
        return ""
    text = main.get_text(separator=" ", strip=True)
    return re.sub(r"\s+", " ", text)[:TEXT_MAX_CHARS]

# =========================
# AI ANALYSIS
# =========================

def _extract_json_object(text: str) -> Optional[Dict]:
    """Balanced-brace JSON extractor — handles nested objects correctly."""
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
                    return json.loads(text[start : i + 1])
                except json.JSONDecodeError:
                    start = None
    return None


def _run_ollama(text: str) -> Optional[Dict]:
    """
    Blocking Ollama call — always run via asyncio.to_thread() from async context.
    BUG FIX v3.4: v3.3 used signal.SIGALRM which is (a) Unix-only and
    (b) not thread-safe when multiple workers run concurrently. We now rely
    on asyncio.wait_for() in the caller for cross-platform timeout.
    """
    prompt = (
        "Return ONLY valid minified JSON. No explanation.\n"
        '{"qualified": true/false, "company": "name", "service": "what they do", "score": 1-10}\n'
        f"DATA:\n{text}"
    )
    try:
        import ollama  # lazy import — graceful if not installed
        res = ollama.generate(model=OLLAMA_MODEL, prompt=prompt)
        raw = res.get("response", "")
        raw = re.sub(r"```json?\s*|```", "", raw)
        data = _extract_json_object(raw)
        if data and data.get("company"):
            data["score"]     = max(0, min(10, int(data.get("score", 0))))
            data["qualified"] = bool(data.get("qualified", False))
            return data
    except ImportError:
        pass
    except Exception as e:
        logger.debug(f"Ollama call error: {e}")
    return None


async def _try_ollama(text: str) -> Optional[Dict]:
    """
    Async wrapper around the blocking _run_ollama().
    BUG FIX v3.4: v3.3 called ollama.generate() directly from synchronous
    code that was called inside an async pipeline — this blocked the entire
    event loop while the model ran, stalling ALL concurrent workers.
    We now run it in a thread pool and apply asyncio.wait_for() for a
    cross-platform, thread-safe timeout.
    """
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_run_ollama, text),
            timeout=OLLAMA_TIMEOUT,
        )
    except asyncio.TimeoutError:
        logger.warning(f"Ollama timed out after {OLLAMA_TIMEOUT}s — falling back to heuristics")
        return None
    except Exception as e:
        logger.debug(f"Ollama wrapper error: {e}")
        return None


def _heuristic_analysis(text: str, url: str) -> Dict:
    """Keyword-based fallback — works without any LLM installed."""
    text_lower = text.lower()
    domain     = get_domain(url)
    hits       = sum(1 for kw in BUSINESS_KEYWORDS if kw in text_lower)
    score      = min(10, max(0, hits + len(text) // 600))

    company = (
        domain.split(".")[0].replace("-", " ").title()
        if domain != "unknown"
        else "Unknown"
    )

    service_map = {
        "marketing": "Marketing",   "design": "Design",
        "consulting": "Consulting", "development": "Development",
        "software": "Software",     "saas": "SaaS",
        "ecommerce": "E-Commerce",  "analytics": "Analytics",
        "agency": "Agency",         "automation": "Automation",
        "fintech": "Fintech",       "cloud": "Cloud",
    }
    service = next(
        (label for kw, label in service_map.items() if kw in text_lower),
        "Unknown",
    )

    return {"company": company, "service": service, "score": score, "qualified": score > 2}


async def analyze_lead(text: str, url: str) -> Dict:
    """Try Ollama first (async, non-blocking), fall back to heuristics."""
    result = await _try_ollama(text)
    return result if result else _heuristic_analysis(text, url)

# =========================
# PIPELINE
# =========================

async def process_url(
    session:   aiohttp.ClientSession,
    semaphore: asyncio.Semaphore,
    url:       str,
    db:        LeadDB,
) -> Optional[Dict]:
    async with semaphore:
        await asyncio.sleep(random.uniform(*RATE_LIMIT_DELAY))

        html = await fetch(session, url)
        if not html:
            return None

        text = extract_text(html)
        if len(text) < 100:
            logger.debug(f"Skipping {url} — page too short ({len(text)} chars)")
            return None

        # BUG FIX v3.4: analyze_lead is now async — must be awaited
        data = await analyze_lead(text, url)
        if not data.get("qualified"):
            logger.debug(f"Not qualified: {url} (score={data.get('score', 0)})")
            return None

        data["url"]    = url
        data["emails"] = extract_emails(text, html)
        db.save(data)
        logger.info(
            f"[✓] {data['company']} | {data['service']} "
            f"| score={data['score']} | emails={len(data['emails'])}"
        )
        return data


async def run(urls: List[str], db: LeadDB, workers: int = MAX_CONCURRENT) -> List[Dict]:
    semaphore = asyncio.Semaphore(workers)
    async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
        tasks = [
            process_url(session, semaphore, normalize_url(u), db)
            for u in urls
            if normalize_url(u)
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    leads = []
    errors = 0
    for r in results:
        if isinstance(r, Exception):
            logger.error(f"Task error: {r}")
            errors += 1
        elif r is not None:
            leads.append(r)

    if errors:
        logger.warning(f"{errors} task(s) failed — check pipeline.log for details")

    return leads

# =========================
# CLI
# =========================

def main():
    parser = argparse.ArgumentParser(
        description="Sovereign Lead Engine v3.4 — AI-powered B2B lead generation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  python sovereign_lead_engine_v3.4.py urls.txt
  python sovereign_lead_engine_v3.4.py urls.txt --workers 10 --export both
  python sovereign_lead_engine_v3.4.py urls.txt --min-score 7 --export csv --output results
  OLLAMA_MODEL=mistral python sovereign_lead_engine_v3.4.py urls.txt
        """,
    )
    parser.add_argument("input",         help="File with URLs (one per line, # for comments)")
    parser.add_argument("--workers",     type=int, default=MAX_CONCURRENT,
                        help=f"Max concurrent requests (default: {MAX_CONCURRENT})")
    parser.add_argument("--export",      choices=["csv", "json", "both"], default=None,
                        help="Export format")
    parser.add_argument("--output",      default="leads_export",
                        help="Export filename without extension (default: leads_export)")
    parser.add_argument("--min-score",   type=int, default=0,
                        help="Only display/export leads with score >= N (all are saved to DB)")
    parser.add_argument("--log-level",   default="INFO",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
                        help="Logging verbosity (default: INFO)")
    args = parser.parse_args()

    setup_logging(args.log_level)

    try:
        with open(args.input, encoding="utf-8") as f:
            urls = [u.strip() for u in f if u.strip() and not u.startswith("#")]
    except FileNotFoundError:
        logger.error(f"Input file not found: {args.input}")
        return

    urls = list(dict.fromkeys(urls))   # deduplicate, preserve order
    if not urls:
        logger.error("No valid URLs found in input file.")
        return

    logger.info(f"Loaded {len(urls)} unique URLs | Workers: {args.workers} | Model: {OLLAMA_MODEL}")

    with LeadDB() as db:
        start = __import__("time").time()
        results = asyncio.run(run(urls, db, workers=args.workers))
        elapsed = __import__("time").time() - start

        displayed = [r for r in results if r.get("score", 0) >= args.min_score] if args.min_score else results

        print(f"\n{'='*52}")
        score_note = f" (score ≥ {args.min_score})" if args.min_score else ""
        print(f"  {len(displayed)} qualified leads{score_note}  |  {elapsed:.0f}s  |  $0.00")
        print(f"{'='*52}\n")

        for r in displayed:
            emails = ", ".join(r.get("emails", [])) or "—"
            print(f"  {r['company']:<28} {r['service']:<16} {r['score']}/10  {emails}")

        print()

        if args.export in ("csv", "both"):
            db.export_csv(f"{args.output}.csv")
        if args.export in ("json", "both"):
            db.export_json(f"{args.output}.json")


if __name__ == "__main__":
    main()
