[README.md](https://github.com/user-attachments/files/27020194/README.md)
# Sovereign Lead Engine

[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![CI](https://github.com/bottomlinetomaitom/PythonGenLeads/actions/workflows/ci.yml/badge.svg)](https://github.com/bottomlinetomaitom/PythonGenLeads/actions/workflows/ci.yml)
[![Async](https://img.shields.io/badge/async-aiohttp-orange.svg)](https://docs.aiohttp.org/)
[![AI](https://img.shields.io/badge/AI-Ollama%20Ready-purple.svg)](https://ollama.com/)
[![BotTomLine](https://img.shields.io/badge/by-BotTomLine-1D9E75.svg)](https://youtube.com/@BotTomLineOps)

**Free, local, async B2B lead generation engine built in Python.**
Scrape websites, score leads with a local AI model, extract emails, and export to CSV or JSON — all from your terminal, with zero subscriptions and zero API costs.

> Built by [Tom Line](https://youtube.com/@BotTomLineOps) — B2B Automation Architect.
> Part of the **BotTomLine** weekly code series: production Python systems for B2B teams, always free.
> 📺 [Watch the full breakdown video →](https://youtube.com/@BotTomLineOps)

---

## Features

| | |
|---|---|
| ⚡ Async pipeline | Configurable concurrency via `aiohttp` + `asyncio.Semaphore` |
| 🤖 Local AI scoring | Ollama + Llama 3 — runs on your machine, zero cost |
| 🔁 Smart fallback | Density-normalized keyword heuristics when Ollama isn't installed |
| 📧 Dual email extraction | Visible text + footer + `mailto:` links with false-positive filter |
| 🛡️ Anti-detection | Rotating User-Agents, exponential backoff, smart status handling |
| 🤝 robots.txt compliant | Honors `robots.txt` per origin (disable with `--no-robots`) |
| 🔒 SSRF protection | Blocks private/loopback/link-local/metadata IPs |
| 💾 Thread-safe SQLite | WAL mode, `threading.Lock`, indexed by domain, score, url |
| ♻️ Resume-safe | Skips URLs already in the DB |
| 📊 Flexible export | CSV and JSON with one flag (emails as proper array in JSON) |
| 🖥️ Full CLI | `--workers`, `--ai-workers`, `--export`, `--min-score`, `--db-path`, `--dry-run`, `--no-robots`, `--log-level` |

---

## Installation

```bash
git clone https://github.com/bottomlinetomaitom/PythonGenLeads.git
cd PythonGenLeads
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -e .                # uses pyproject.toml
# or, dev extras (tests + linters):
pip install -e ".[dev]"
```

### Enable AI scoring (optional)

```bash
# Install Ollama: https://ollama.com
curl -fsSL https://ollama.com/install.sh | sh
ollama pull llama3
```

Without Ollama the engine uses density-based keyword heuristics automatically — no setup required.

---

## Quick start

```bash
# 1. Create your URL list
cat > urls.txt <<EOF
https://stripe.com
https://hubspot.com
https://notion.so
EOF

# 2. Run
sovereign-lead-engine urls.txt

# 3. Export
sovereign-lead-engine urls.txt --export both --output my_leads
```

---

## CLI reference

```
usage: sovereign-lead-engine [-h] [--workers N] [--ai-workers N]
                             [--export {csv,json,both}] [--output NAME]
                             [--db-path PATH] [--min-score N] [--no-robots]
                             [--dry-run] [--log-level {DEBUG,INFO,WARNING,ERROR}]
                             [--version]
                             input
```

### Examples

```bash
# High-concurrency scan (HTTP only — AI capped at 2)
sovereign-lead-engine urls.txt --workers 20 --ai-workers 2

# Only strong leads, CSV only
sovereign-lead-engine urls.txt --min-score 7 --export csv

# Validate input without scraping
sovereign-lead-engine urls.txt --dry-run

# Use a different Ollama model
OLLAMA_MODEL=mistral sovereign-lead-engine urls.txt
```

---

## What changed in v3.5

- 🤝 **robots.txt** compliance (per-origin cache)
- 🔒 **SSRF guard** blocks private / loopback / link-local / metadata IPs
- 🧠 Separate **AI semaphore** prevents Ollama from saturating CPU/GPU
- ♻️ **Resume-safe**: URLs already in DB are skipped
- 📧 Emails now extracted **before** stripping `nav`/`footer`
- 📊 JSON export emits `emails` as proper array (not CSV string)
- 🆕 `--db-path`, `--ai-workers`, `--no-robots`, `--dry-run`, `--version`
- 🧪 Test suite + GitHub Actions CI (lint + pytest on Python 3.9–3.12)
- 📦 `pyproject.toml` with `pip install -e .` and console script entry point
- 🐛 Repo housekeeping: real `.gitignore` & `LICENSE`, single canonical script name

---

## Architecture

```
urls.txt
   │
   ▼
┌───────────────────────────────────────────────┐
│  asyncio.gather()  ·  Semaphore(workers)      │
│                                               │
│  is_safe_url()    SSRF block-list             │
│  already_processed()  resume support          │
│  is_allowed_by_robots()  per-origin cache     │
│                                               │
│  fetch()          aiohttp async + retries     │
│  extract_text_and_emails()  BeautifulSoup     │
│                                               │
│  analyze_lead()   async                       │
│   ├─ _try_ollama()  Semaphore(ai_workers)     │
│   │  └─ asyncio.wait_for() timeout           │
│   └─ _heuristic_analysis()  density-based    │
│                                               │
│  LeadDB.save()    threading.Lock + WAL        │
└───────────────────────────────────────────────┘
   │
   ▼
leads.db  →  leads_export.csv / leads_export.json
```

---

## Project structure

```
PythonGenLeads/
├── sovereign_lead_engine.py        # Main engine
├── tests/                          # Pytest suite
├── pyproject.toml                  # Build & deps
├── requirements.txt                # Pinned for pip users
├── sample_urls.txt                 # Example URL list
├── .github/workflows/ci.yml        # Lint + test
├── .gitignore
├── LICENSE                         # MIT
├── CONTRIBUTING.md
└── README.md
```

---

## Disclaimer

This tool is for **ethical lead generation on publicly accessible websites**. Always:
- Respect `robots.txt` directives (enabled by default)
- Comply with GDPR, CCPA, and applicable data laws
- Obtain consent before contacting extracted emails
- Do not use for spamming or unauthorized data collection

The price comparison in earlier versions of this README compared against tools like Apollo/Clay that also provide enrichment and people-data, which this engine does not. Use the right tool for your job.

---

## License

[MIT](LICENSE) — free for personal and commercial use.

---

<p align="center">
  Built by <a href="https://youtube.com/@BotTomLineOps">Tom Line</a> · BotTomLine<br>
  Free B2B Python code, every week.<br>
  <a href="https://youtube.com/@BotTomLineOps">Subscribe →</a>
</p>
