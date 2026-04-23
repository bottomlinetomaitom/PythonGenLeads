# Security Policy

## Supported Versions

Only the latest minor release receives security fixes.

| Version | Supported          |
| ------- | ------------------ |
| 3.5.x   | :white_check_mark: |
| < 3.5   | :x:                |

## Reporting a Vulnerability

**Please do not open a public GitHub issue for security problems.**

Report vulnerabilities privately via GitHub's
[Private Vulnerability Reporting](https://github.com/bottomlinetomaitom/PythonGenLeads/security/advisories/new)
feature, or by direct message to [@BotTomLineOps on YouTube](https://youtube.com/@BotTomLineOps).

Please include:

- A clear description of the issue and its impact
- Steps to reproduce (PoC code if possible)
- Affected version(s)
- Any suggested mitigation

### What to expect

- **Acknowledgement** within 72 hours
- **Triage and severity assessment** within 7 days
- **Fix or mitigation plan** within 30 days for high/critical issues
- Public disclosure coordinated with the reporter, after a fix is released

## Scope

In scope:

- The `sovereign_lead_engine.py` module
- The packaging and CI configuration in this repository

Out of scope:

- Vulnerabilities in upstream dependencies (report to those projects directly,
  but we welcome a heads-up so we can pin/patch)
- Misuse of the tool against websites without authorization — this is not
  a vulnerability, it is a violation of the project's ethical-use clause

## Hardening reminders for users

- Always run with the default `robots.txt` compliance enabled
- Never feed untrusted URLs without the SSRF guard active
- Treat the `leads.db` file as containing personal data (GDPR / CCPA apply)
