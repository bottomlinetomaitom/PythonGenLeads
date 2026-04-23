# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [3.5.0] - 2024-04

### Added
- 🤝 `robots.txt` compliance with per-origin caching (toggle with `--no-robots`)
- 🔒 SSRF guard blocks private / loopback / link-local / multicast / metadata IPs
- 🧠 Separate AI semaphore (`--ai-workers`) prevents Ollama from saturating CPU/GPU
- ♻️ Resume support — URLs already in the DB are skipped automatically
- 🆕 CLI flags: `--db-path`, `--ai-workers`, `--no-robots`, `--dry-run`, `--version`
- 🧪 Pytest test suite (21 tests) covering URL, email, JSON, heuristics, SSRF, DB
- 🤖 GitHub Actions CI: ruff lint + pytest on Python 3.9–3.12
- 📦 `pyproject.toml` with `pip install -e .` and `sovereign-lead-engine` console script
- 📝 `CHANGELOG.md`, `SECURITY.md`, `CODE_OF_CONDUCT.md`, issue & PR templates
- 🐳 `Dockerfile` + `docker-compose.yml` (with optional Ollama service)
- 🔧 `Makefile` shortcuts (`make test`, `make lint`, `make run`)
- 🪝 `.pre-commit-config.yaml` (ruff + hygiene hooks)
- 🤝 Dependabot configuration

### Changed
- 📧 Email extraction now happens **before** stripping `nav`/`footer` (contacts often live there)
- 📊 JSON export emits `emails` as a proper array instead of a CSV-joined string
- 🧮 Heuristic scoring is now density-normalized (not biased by page length)
- 🧹 Replaced `__import__("time")` with proper `import time`
- 🧹 `setup_logging()` now clears existing handlers (no duplicates on re-init)
- 🛑 Graceful `KeyboardInterrupt` handling with partial-save guarantee
- 📁 Repo layout: real `.gitignore` and `LICENSE` files (not `.txt`); single canonical script name

### Fixed
- 🐛 Removed `YOUR_USERNAME` placeholder URLs from code and docs
- 🐛 README install commands now match the actual file name

## [3.4.0] - prior

### Fixed
- `_try_ollama()` was blocking the entire async event loop — now runs in `asyncio.to_thread()` so all workers stay concurrent
- Ollama timeout used `signal.SIGALRM` (Unix-only, not thread-safe) — replaced with `asyncio.wait_for()` for cross-platform timeout
- `analyze_lead()` was synchronous but called inside an async pipeline — converted to `async def` with proper `await`

### Added
- Exponential backoff on fetch retries (1s → 1.5s → 2.25s)
- `--log-level` CLI flag
- `OLLAMA_MODEL` env var
- Improved run summary with elapsed time and cost
- `pipeline.log` file written alongside terminal output

## [3.3.0] - prior

### Added
- Dual email extraction (text + `mailto:` links)
- Ollama timeout protection
- Balanced-brace JSON parser — handles nested objects

## [3.2.0] - prior

### Added
- Thread-safe DB with `threading.Lock`
- Context manager for `LeadDB`
- URL deduplication, `--min-score` filter

## [3.1.0] - prior

### Added
- Async migration (`aiohttp`)
- Ollama integration + keyword fallback
- CSV/JSON export

[3.5.0]: https://github.com/bottomlinetomaitom/PythonGenLeads/releases/tag/v3.5.0
