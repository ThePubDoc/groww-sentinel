# Phase 3: Autonomous & Failure-Safe Runtime - Discussion Log

> **Audit trail only.** Decisions live in CONTEXT.md.

**Date:** 2026-07-09
**Phase:** 3-Autonomous & Failure-Safe Runtime
**Areas discussed:** Cron schedule, NSE holiday skip, state commit-back + org token, Dead-man's-switch

---

## Cron schedule (RUN-01/05)
| Question | Choice |
|----------|--------|
| Frequency | ✓ Lean 3×/weekday (pre-open ~09:00, midday ~12:30, close ~15:30 IST) — revises Phase-2 hourly |
| (mechanics) | UTC cron ~03:30/07:00/10:00, weekdays 1-5, non-top-of-hour minute; workflow_dispatch enabled |

## NSE holiday skip (RUN-02)
| Question | Choice |
|----------|--------|
| Source | ✓ Static holidays.py (seeded 2026–2027; warn past last year) — over pandas_market_calendars |

## State commit-back + org token (RUN-03)
| Question | Choice |
|----------|--------|
| Mechanism | ✓ git-auto-commit-action@v5 + permissions:contents:write default token; PAT (STATE_PAT) fallback if org restricts; verify at first workflow_dispatch |

## Dead-man's-switch (NOTIFY-05)
| Question | Choice |
|----------|--------|
| Approach | ✓ healthchecks.io free external monitor — ping success URL; catches missed cron AND crash-before-send |

## Claude's Discretion
- Exact cron minutes, concurrency group name, healthchecks grace window, holiday-skip in Python (testable) vs YAML guard, workflow filename.

## Deferred
- Full hourly cadence (dropped for 3×/day)
- pandas_market_calendars (static list preferred)
- sturdier news source than yfinance
