# Contributing to Sovereign Lead Engine

Thanks for your interest in contributing. This project is part of the **BotTomLine** weekly code series — the goal is to keep the code clean, readable, and useful for B2B teams of any size.

---

## How to contribute

1. Fork the repo and create a branch: `git checkout -b feature/your-feature`
2. Make your changes
3. Run a quick test: `python sovereign_lead_engine_v3.4.py sample_urls.txt`
4. Open a pull request with a clear description of what changed and why

---

## What we welcome

- Bug fixes (with a clear explanation of the bug)
- New export targets (Notion, Google Sheets, HubSpot, Salesforce)
- Additional AI backends (OpenAI, Anthropic, Groq, local models via LM Studio)
- `robots.txt` compliance layer
- Progress bar support (`tqdm`)
- Windows-specific improvements

## What to keep in mind

- Keep functions small and single-purpose — one function, one job
- No new hard dependencies without strong justification
- Add a `# BUG FIX` or `# IMPROVEMENT` comment when fixing something non-obvious
- `asyncio.to_thread()` for any blocking I/O inside the async pipeline

---

## Reporting bugs

Open an issue with:
- Python version and OS
- The command you ran
- The error message or unexpected output
- A sample URL that reproduces the issue (if applicable)

---

## Questions

Drop a comment on the [YouTube video](https://youtube.com/@BotTomLine) or open a GitHub Discussion.
