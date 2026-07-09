# Groww Sentinel

## What This Is

A daily automated advisor over my personal Groww equity holdings. Each weekday
morning it fetches holdings + live prices, applies my profit-booking + averaging
strategy as deterministic rules, and pings me on Telegram with per-stock flags
(average / trim / book / stop / hold) plus a portfolio P&L trend. Friday's digest
also carries a weekly summary. It surfaces candidates and reminds me to run manual
judgment gates — it does **not** trade and does **not** make the final decision.

> **Not investment advice.** Rules encode a personal strategy. All actions are
> reviewed and executed manually.

## Core Value

Every trading morning I get a short, trustworthy Telegram digest that flags which
of my holdings need attention today — so I never miss a stop, trim, or averaging
opportunity, and I never have to open the app to check.

## Requirements

### Validated

(None yet — ship to validate)

### Active

- [ ] Fetch holdings (symbol, qty, avg cost) from official Groww TradeAPI
- [ ] Fetch live price (LTP) per held symbol
- [ ] Headless auth via API key + TOTP seed (pyotp)
- [ ] Deterministic rules engine producing per-stock flags (pure function)
- [ ] Track per-symbol peak price + daily portfolio snapshots in state.json
- [ ] Reset a symbol's peak when it leaves holdings (sold); re-seed on rebuy
- [ ] Day P&L trend: snapshot delta vs prior run + N-day direction; intraday % if broker exposes prev close
- [ ] Weekly summary appended to Friday's digest (best/worst movers, week value change, flags-fired count)
- [ ] Format + send Telegram digest (non-HOLD stocks only; "all quiet" if none)
- [ ] Commit updated state.json back to repo each run
- [ ] Run on GitHub Actions cron ~08:30 IST, weekdays, skipping NSE holidays via a holiday calendar
- [ ] Validate all 4 required secrets present at startup; fail loud naming the missing one
- [ ] Robust error handling — never silently skip a day (notify on fetch failure, exit non-zero)
- [ ] Unit tests for the pure rules engine (money path); mocked I/O tests for broker/notify

### Out of Scope

- Order placement / trading — advisory only, all actions manual — safety + intent
- Web dashboard / database / charts — Telegram message is the whole UI — YAGNI
- Auto-fundamentals (earnings, debt, sector) — the 3-gate check stays manual — judgment can't be automated safely
- Trade history / tax / charges reconstruction — that's the separate `groww-dashboard` project — Sentinel is forward-looking only
- Scraping / unofficial APIs — official Groww TradeAPI only — sanctioned + stable
- WhatsApp / email channels — Telegram only for v1; notify layer kept swappable — WhatsApp template-approval fights a dynamic daily digest

## Context

- **Data access:** Official Groww TradeAPI via the `growwapi` Python SDK. Free, stable, sanctioned. Holdings via `get_holdings_for_user()` (gives qty + avg cost, **no** LTP). LTP fetched per symbol from the live-data endpoint each run.
- **Auth:** API key + TOTP. Store the TOTP *seed*; generate the code at runtime with `pyotp` so it works headless in CI.
- **Strategy encoded:** profit-booking + averaging. Flags: AVG CANDIDATE (core), TRAIL WATCH (core), TRIM (any), BOOK 50% (tactical), STOP HIT (tactical), HOLD, UNTAGGED. Thresholds live as named constants in one place for tuning.
- **Manual gate:** AVG CANDIDATE is a *candidate only*. Digest reminds me to run the 3-gate check (results still good? fall market/sector-wide not company-bad-news? would I buy fresh today?) before adding. Any "no" → skip.
- **Config:** `config.yaml` tags each holding `core` or `tactical`. Untagged symbol → UNTAGGED flag, never guess a bucket.
- **Prior design:** Full approved design spec at `docs/superpowers/specs/2026-07-09-groww-sentinel-design.md`.
- **Sibling project:** `groww-dashboard` owns historical/tax/charges. Keep boundaries clean.

## Constraints

- **Tech stack**: Python + `growwapi` SDK + `pyotp` — official, headless-friendly, free.
- **Runtime**: GitHub Actions cron only — no always-on server; ~08:30 IST weekdays.
- **Security**: Secrets (`GROWW_API_KEY`, `GROWW_TOTP_SEED`, `TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID`) as GitHub encrypted secrets — never committed.
- **State persistence**: state.json committed back to repo → workflow token needs `contents: write`; under the `ThePubDoc` org this may be restricted (same family as the `workflow`-scope caveat). Resolve at impl time.
- **File size**: keep modules focused (<200 lines each): broker / rules / notify / sentinel split.
- **Correctness**: rules engine must be a pure, fully unit-testable function — no I/O.

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Telegram as the only channel (v1) | Zero-friction free-form daily push; WhatsApp needs approved templates that fight a dynamic digest | — Pending |
| GitHub Actions cron for runtime | No server to run; free; secrets built-in | — Pending |
| state.json holds per-symbol daily snapshots keyed by date | Powers P&L trend + weekly movers; date-keying makes double-runs idempotent | — Pending |
| Reset peak on exit, re-seed on rebuy | Avoids perpetual TRAIL WATCH noise on permanently-down stocks | — Pending |
| P&L trend = snapshot + intraday | Snapshot works pre-market; add true intraday % only if LTP endpoint exposes prev close | — Pending |
| Weekly summary = Friday appended block | One message, one job, no extra cron | — Pending |
| Verify corporate-action adjustment at impl, don't pre-build | Confirm if growwapi pre-adjusts avg_price; only add handling/warning if it doesn't | — Pending |
| Maintain NSE holiday calendar | Pre-market runs on holidays give stale/confusing prices; skip cleanly | — Pending |
| Validate secrets at startup | Fail loud naming the missing secret vs cryptic mid-run crash | — Pending |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-07-09 after initialization*
