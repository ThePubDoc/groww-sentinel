---
phase: 03-autonomous-failure-safe-runtime
plan: 01
subsystem: infra
tags: [python, healthchecks-io, dead-mans-switch, nse-holidays, sentinel]

requires:
  - phase: 02-portfolio-telemetry-sentiment
    provides: sentinel.main() entrypoint with secrets validation, state load/save, best-effort notify, exception-path fail-loud
provides:
  - "holidays.py: static NSE 2026 trading-holiday calendar + is_trading_holiday(today)"
  - "notify.healthcheck_ping(url): best-effort dead-man's-switch heartbeat"
  - "sentinel._market_closed(today) + main() holiday/weekend early-exit and healthcheck ping wiring"
affects: [03-02-github-actions-workflow]

tech-stack:
  added: []
  patterns:
    - "Pure stdlib data module for the NSE holiday calendar (no pandas_market_calendars dependency, per D-03)"
    - "Bare best-effort try/except: pass for outbound monitoring pings, mirroring the existing _best_effort_notify pattern"
    - "Injectable `today` parameter for all date-dependent logic, keeping it clock-free and unit-testable"

key-files:
  created:
    - holidays.py
    - tests/test_holidays.py
  modified:
    - notify.py
    - sentinel.py
    - tests/test_notify.py
    - tests/test_sentinel.py

key-decisions:
  - "holidays.py is a pure-stdlib data module (frozen 15-date 2026 set) rather than pandas_market_calendars, per locked decision D-03"
  - "Past-LAST_SEEDED_YEAR warns loudly (stderr + best-effort Telegram) but does NOT early-exit on its own -- only weekend/holiday triggers the closed-day exit"
  - "healthcheck_ping fires on all four clean-exit paths (holiday/weekend, no-holdings, dry-run, real send) and on NONE of the error paths (missing-secret return 2, exception return 1)"

patterns-established:
  - "Dead-man's-switch heartbeat as a best-effort side effect placed at every clean-exit return, never inside the except handler"

requirements-completed: [RUN-02, NOTIFY-05]

coverage:
  - id: D1
    description: "holidays.py: static 15-date NSE 2026 holiday set + is_trading_holiday(today) with fail-loud past-year warning"
    requirement: "RUN-02"
    verification:
      - kind: unit
        ref: "tests/test_holidays.py"
        status: pass
    human_judgment: false
  - id: D2
    description: "notify.healthcheck_ping(url): best-effort GET heartbeat, no-ops on missing URL, swallows request failures"
    requirement: "NOTIFY-05"
    verification:
      - kind: unit
        ref: "tests/test_notify.py::test_healthcheck_ping_is_noop_when_url_is_none, test_healthcheck_ping_issues_get_with_timeout, test_healthcheck_ping_swallows_request_exception"
        status: pass
    human_judgment: false
  - id: D3
    description: "sentinel._market_closed(today) + main() early-exits(0) on weekend/holiday before any broker call, still pings healthcheck; ping fires on no-holdings/dry-run/real-send clean exits and never on the exception path; past-seeded-year warning surfaces without early-exiting"
    requirement: "RUN-02, NOTIFY-05"
    verification:
      - kind: unit
        ref: "tests/test_sentinel.py::test_market_closed_true_for_seeded_2026_holiday, test_market_closed_true_for_saturday, test_market_closed_false_for_ordinary_weekday, test_main_closed_day_returns_0_without_broker_call_and_pings_healthcheck, test_main_pings_healthcheck_on_successful_dry_run, test_main_pings_healthcheck_on_no_holdings_exit, test_main_does_not_ping_healthcheck_on_exception_path, test_main_past_seeded_year_warns_but_still_proceeds"
        status: pass
    human_judgment: false

duration: 25min
completed: 2026-07-10
status: complete
---

# Phase 3 Plan 1: Holiday Calendar + Dead-Man's-Switch Heartbeat Summary

**Static NSE-2026 holiday skip (`holidays.py`) plus a healthchecks.io heartbeat wired into every clean exit of `sentinel.main()`, never the error path — so a holiday, a missed cron, and a real crash are each distinguishable.**

## Performance

- **Duration:** 25 min
- **Started:** 2026-07-10T08:58:00Z
- **Completed:** 2026-07-10T09:03:25Z
- **Tasks:** 2
- **Files modified:** 6 (2 created, 4 modified)

## Accomplishments
- `holidays.py`: 15 seeded NSE 2026 trading holidays + `is_trading_holiday(today)`, fail-loud warning once `today.year > LAST_SEEDED_YEAR` instead of silently assuming the market is open
- `notify.healthcheck_ping(url)`: best-effort GET to a healthchecks.io URL; no-ops when unset, swallows any request exception
- `sentinel._market_closed(today)` + `main()` wiring: weekend/holiday now exits cleanly (return 0) before any broker auth or network call, still pings the heartbeat; the heartbeat also fires on the no-holdings and dry-run/real-send clean exits, and on none of the error returns
- Full suite green: 130 tests pass (113 prior + 17 new), zero live network/broker calls

## Task Commits

Each task was committed atomically:

1. **Task 1: holidays.py static NSE 2026 holiday set + is_trading_holiday** - `c33aaf1` (feat)
2. **Task 2: healthcheck heartbeat + sentinel holiday/weekend early-exit wiring** - `80572c8` (feat)

**Plan metadata:** (this commit)

_Note: both tasks followed RED (confirmed failing tests against the not-yet-existing behavior) before GREEN implementation, in a single feat commit per task rather than separate test/feat commits -- consistent with this repo's existing commit granularity (see prior-phase SUMMARYs)._

## Files Created/Modified
- `holidays.py` - Static NSE 2026 holiday set, `LAST_SEEDED_YEAR`, `is_trading_holiday(today)`
- `tests/test_holidays.py` - Holiday/non-holiday/past-year-warning/weekend-exclusion cases
- `notify.py` - Added `healthcheck_ping(url)` best-effort heartbeat helper
- `tests/test_notify.py` - No-op/success/exception-swallowed cases for `healthcheck_ping`
- `sentinel.py` - Added `_market_closed(today)`; wired holiday/weekend early-exit + heartbeat calls into `main()`'s four clean-exit paths
- `tests/test_sentinel.py` - `_market_closed` cases + `main()` wiring cases (closed-day, no-holdings, dry-run, exception-path, past-seeded-year-warn), using a frozen `today` via a `datetime` subclass monkeypatch

## Decisions Made
- Reused the existing `_best_effort_notify`/`try-except-pass` idiom for the heartbeat rather than introducing new error-handling machinery
- `_market_closed(today)` centralizes the weekend-OR-holiday check so `main()` calls it once rather than re-deriving the OR condition inline
- Test-froze `today` via a `datetime` subclass monkeypatched onto `sentinel.datetime`, rather than depending on the real wall-clock date, so the new tests are stable regardless of what day they're run on

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required in this plan (healthchecks.io account/URL creation belongs to 03-02's workflow wiring and 03-03's deploy verification, per the phase's own task split).

## Next Phase Readiness

- `holidays.py` and `notify.healthcheck_ping` are ready for 03-02's GitHub Actions workflow to inject `HEALTHCHECK_URL` as a secret and invoke `python -m sentinel`
- `sentinel.main()`'s exit codes (0 clean/closed, 1 error, 2 missing-secret) are unchanged from Phase 2 -- 03-02's workflow step can rely on the existing "no `|| true`" contract to propagate failures
- No blockers for 03-02 or 03-03

---
*Phase: 03-autonomous-failure-safe-runtime*
*Completed: 2026-07-10*

## Self-Check: PASSED

All created files and both task commits verified present on disk / in git log.
