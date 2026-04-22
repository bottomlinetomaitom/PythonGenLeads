# Sovereign Lead Engine

[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Async](https://img.shields.io/badge/async-aiohttp-orange.svg)](https://docs.aiohttp.org/)
[![AI](https://img.shields.io/badge/AI-Ollama%20Ready-purple.svg)](https://ollama.com/)
[![BotTomLine](https://img.shields.io/badge/by-BotTomLine-1D9E75.svg)](https://youtube.com/@BotTomLine)

**Free, local, async B2B lead generation engine built in Python.**
Scrape websites, score leads with a local AI model, extract emails, and export to CSV or JSON — all from your terminal, with zero subscriptions and zero API costs.

> Built by [Tom Line](https://youtube.com/@BotTomLine) — B2B Automation Architect.
> Part of the **BotTomLine** weekly code series: production Python systems for B2B teams, always free.
> 📺 [Watch the full breakdown video →](https://youtube.com/@BotTomLine)

---

## Why this exists

| SaaS stack | Cost |
|---|---|
| Apollo.io | $99/mo |
| Clay | $149/mo |
| Hunter.io | $49/mo |
| Phantombuster | $69/mo |
| **Total** | **$366/mo** |
| **Sovereign Lead Engine** | **$0/mo** |

No vendor lock-in. No rate limits. No data leaving your machine. You own the code.

---

## Features

| | |
|---|---|
| ⚡ Async pipeline | 5 concurrent requests via `aiohttp` + `asyncio.Semaphore` |
| 🤖 Local AI scoring | Ollama + Llama 3 — runs on your machine, zero cost |
| 🔁 Smart fallback | Keyword heuristics when Ollama isn't installed |
| 📧 Dual email extraction | Visible text + `mailto:` links with false-positive filter |
| 🛡️ Anti-detection | Rotating User-Agents, exponential backoff, smart status handling |
| 💾 Thread-safe SQLite | WAL mode, `threading.Lock`, indexed by domain and score |
| 📊 Flexible export | CSV and JSON with one flag |
| 🖥️ Full CLI | `--workers`, `--export`, `--min-score`, `--log-level` |

---

## Changelog

### v3.4 (current)
- 🐛 **Bug fix**: `_try_ollama()` was blocking the entire async event loop — now runs in `asyncio.to_thread()` so all 5 workers stay concurrent
- 🐛 **Bug fix**: Ollama timeout used `signal.SIGALRM` — Unix-only and not thread-safe under concurrency. Replaced with `asyncio.wait_for()` for cross-platform timeout
- 🐛 **Bug fix**: `analyze_lead()` was synchronous but called inside an async pipeline — converted to `async def` with proper `await`
- ✨ Exponential backoff on fetch retries (1s → 1.5s → 2.25s)
- ✨ `--log-level` CLI flag (DEBUG / INFO / WARNING / ERROR)
- ✨ `OLLAMA_MODEL` env var — swap models without editing code
- ✨ Improved run summary with elapsed time and cost
- ✨ `pipeline.log` file written alongside terminal output

### v3.3
- 🔧 Dual email extraction (text + `mailto:` links)
- ⏱️ Ollama timeout protection
- 🧩 Balanced-brace JSON parser — handles nested objects

### v3.2
- 🔒 Thread-safe DB with `threading.Lock`
- 📋 Context manager for `LeadDB`
- 🧹 URL deduplication, `--min-score` filter

### v3.1
- ⚡ Async migration (`aiohttp`)
- 🤖 Ollama integration + keyword fallback
- 📊 CSV/JSON export

---

## Installation

```bash
git clone https://github.com/YOUR_USERNAME/sovereign-lead-engine.git
cd sovereign-lead-engine
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### Enable AI scoring (optional)

```bash
# Install Ollama: https://ollama.com
curl -fsSL https://ollama.com/install.sh | sh
ollama pull llama3
```

Without Ollama the engine uses keyword heuristics automatically — no setup required.

---

## Quick start

```bash
# 1. Create your URL list
echo "https://stripe.com"   > urls.txt
echo "https://hubspot.com" >> urls.txt
echo "https://notion.so"   >> urls.txt

# 2. Run
python sovereign_lead_engine_v3.4.py urls.txt

# 3. Export results
python sovereign_lead_engine_v3.4.py urls.txt --export both --output my_leads
```

---

## CLI reference

```
usage: sovereign_lead_engine_v3.4.py [-h] [--workers N] [--export {csv,json,both}]
                                      [--output NAME] [--min-score N]
                                      [--log-level {DEBUG,INFO,WARNING,ERROR}]
                                      input

positional arguments:
  input           File with URLs (one per line, # = comment)

options:
  --workers N     Max concurrent requests (default: 5)
  --export FORMAT csv | json | both
  --output NAME   Export filename without extension (default: leads_export)
  --min-score N   Only display/export leads with score >= N
  --log-level LVL Logging verbosity (default: INFO)
```

### Examples

```bash
# High-concurrency scan
python sovereign_lead_engine_v3.4.py urls.txt --workers 10

# Only strong leads, CSV only
python sovereign_lead_engine_v3.4.py urls.txt --min-score 7 --export csv

# Full export, quiet output
python sovereign_lead_engine_v3.4.py urls.txt --export both --log-level WARNING

# Use a different Ollama model
OLLAMA_MODEL=mistral python sovereign_lead_engine_v3.4.py urls.txt
```

---

## Architecture

```
urls.txt
   │
   ▼
┌─────────────────────────────────────────────┐
│  asyncio.gather()  ·  Semaphore(workers)    │
│                                             │
│  fetch()           aiohttp async            │
│   ├─ 200 OK      → continue                 │
│   ├─ 429         → exponential backoff      │
│   ├─ 403/404/410 → skip (no retry)          │
│   └─ 5xx         → retry × 3               │
│                                             │
│  extract_text()    BeautifulSoup            │
│   └─ main / article / body priority        │
│                                             │
│  analyze_lead()    async                    │
│   ├─ _try_ollama() asyncio.to_thread()      │  ← non-blocking
│   │   └─ asyncio.wait_for() timeout        │  ← cross-platform
│   └─ _heuristic_analysis() fallback        │
│                                             │
│  extract_emails()  text + mailto: links    │
│                                             │
│  LeadDB.save()     threading.Lock + WAL    │
└─────────────────────────────────────────────┘
   │
   ▼
leads.db  →  leads_export.csv / leads_export.json
```

---

## Extending the engine

The code is deliberately modular. Each function does one thing and can be replaced independently.

**Swap the AI model**
```bash
OLLAMA_MODEL=mistral python sovereign_lead_engine_v3.4.py urls.txt
OLLAMA_MODEL=phi3     python sovereign_lead_engine_v3.4.py urls.txt
```

**Load URLs from a CSV column**
```python
import pandas as pd
urls = pd.read_csv("companies.csv")["website"].dropna().tolist()
with open("urls.txt", "w") as f:
    f.write("\n".join(urls))
```

**Plug results into your CRM**
```python
import pandas as pd
df = pd.read_csv("leads_export.csv")
# filter, enrich, push to HubSpot / Salesforce / Notion
```

**Run on a schedule**
```bash
# cron: every Monday at 8am
0 8 * * 1 cd /path/to/engine && python sovereign_lead_engine_v3.4.py urls.txt --export both
```

---

## Project structure

```
sovereign-lead-engine/
├── sovereign_lead_engine_v3.4.py   # Main engine
├── requirements.txt                # Dependencies
├── sample_urls.txt                 # Example URL list
├── README.md
├── CONTRIBUTING.md
├── LICENSE                         # MIT
└── .gitignore
```

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). PRs welcome — especially for:
- New export formats (Notion, Google Sheets, HubSpot API)
- Additional AI backends (OpenAI, Anthropic, Groq)
- `robots.txt` compliance layer
- Progress bar (`tqdm`)

---

## Disclaimer

This tool is for **ethical lead generation on publicly accessible websites**. Always:
- Respect `robots.txt` directives
- Comply with GDPR, CCPA, and applicable data laws
- Obtain consent before contacting extracted emails
- Do not use for spamming or unauthorized data collection

---

## License

[MIT](LICENSE) — free for personal and commercial use.

---

<p align="center">
  Built by <a href="https://youtube.com/@BotTomLine">Tom Line</a> · BotTomLine<br>
  Free B2B Python code, every week.<br>
  <a href="https://youtube.com/@BotTomLine">Subscribe →</a>
</p>
