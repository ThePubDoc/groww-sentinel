# Roadmap: Groww Sentinel

## Shipped Milestones

- **v1.0 — Groww Sentinel** (shipped 2026-07-10) — autonomous 3×/weekday Telegram advisor over live Groww holdings: unified P&L action ladder with share quantities, durable state (peaks, P&L trend, Friday weekly), optional news-sentiment, GitHub Actions cron + holiday skip + fail-loud + dead-man's-switch. 3 phases, 10 plans, 130 tests, verified live. → [`milestones/v1.0-ROADMAP.md`](milestones/v1.0-ROADMAP.md) · [`milestones/v1.0-REQUIREMENTS.md`](milestones/v1.0-REQUIREMENTS.md)

## Backlog (next milestone candidates)

- **PNL-06** — dampen a flag that stays open for many consecutive days (repeat-alert fatigue)
- **RUN-06** — upgrade holiday source to `pandas_market_calendars` (XNSE) after validating vs NSE's list
- **NOTIFY-06** — add WhatsApp as a second channel (notify layer already swappable)
- Sturdier free news source than yfinance (Google News RSS) for more reliable sentiment
- Maintenance: bump GitHub Actions (`@v5`→`@v7`, Node 20→24); add NSE 2027 holidays when published

---
*Next milestone: run `/gsd-new-milestone` to define scope, requirements, and phases.*
