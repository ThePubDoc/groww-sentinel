---
phase: 02-durable-state-portfolio-telemetry
plan: 04
subsystem: notifications
tags: [python, stdlib-datetime, telegram-digest, pure-functions]

requires:
  - phase: 02-durable-state-portfolio-telemetry
    provides: "02-02's write_snapshot (per-symbol {price, value} + flags_fired persisted daily), 02-03's day_change/n_day_trend pattern and notify header telemetry"
provides:
  - "state.py pure weekly-math helpers: week_start, weekly_movers, week_value_change, flags_fired_this_week"
  - "notify.py Friday weekly recap block appended to the digest"
  - "sentinel.py Friday gate + _weekly_summary wiring"
affects: [phase-3-scheduling, phase-3-state-commit]

tech-stack:
  added: []
  patterns:
    - "Weekly helpers stay pure (snapshots + today in, no clock/IO) exactly like day_change/n_day_trend from 02-03"
    - "Sentinel exposes small testable pure(ish) helper functions (_telemetry, _portfolio_summary, now _weekly_summary) instead of embedding logic in main()"

key-files:
  created: []
  modified:
    - state.py
    - notify.py
    - sentinel.py
    - tests/test_state.py
    - tests/test_notify.py
    - tests/test_sentinel.py

key-decisions:
  - "weekly_movers/week_value_change/flags_fired_this_week use the LATEST in-week snapshot date (week_dates[-1]) as the 'end' point rather than indexing snapshots[today.isoformat()] directly -- degrades gracefully instead of KeyError-ing if ever called before today's own entry is written"
  - "sentinel._weekly_summary is called with the freshly-written new_snapshots (post write_snapshot), not the pre-write loaded snapshots, so today's own entry is always present as the week's latest data point on the very first run of a Friday"
  - "format_digest takes weekly as an optional keyword arg (not a portfolio dict key) to keep the already-heavily-tested portfolio dict shape untouched"

patterns-established:
  - "Weekly recap sits as the final digest section, appended only when non-empty, with zero footprint (byte-identical output) when weekly=None"

requirements-completed: [PNL-05]

coverage:
  - id: D1
    description: "Pure weekly helpers (week_start, weekly_movers, week_value_change, flags_fired_this_week) in state.py, boundary-tested for thin weeks, best/worst ranking, missing mid-week symbols, and prior-week exclusion"
    requirement: "PNL-05"
    verification:
      - kind: unit
        ref: "tests/test_state.py#test_week_start_returns_monday_for_mid_week_date"
        status: pass
      - kind: unit
        ref: "tests/test_state.py#test_weekly_movers_empty_on_thin_week"
        status: pass
      - kind: unit
        ref: "tests/test_state.py#test_weekly_movers_ranks_best_and_worst_over_the_week"
        status: pass
      - kind: unit
        ref: "tests/test_state.py#test_flags_fired_this_week_sums_in_week_snapshots_only"
        status: pass
    human_judgment: false
  - id: D2
    description: "notify.format_digest renders the weekly block (movers, week value change, flags-fired count) as the final section when a weekly dict is passed, and is byte-identical to the pre-existing digest when weekly is None"
    requirement: "PNL-05"
    verification:
      - kind: unit
        ref: "tests/test_notify.py#test_weekly_block_appended_at_bottom_when_present"
        status: pass
      - kind: unit
        ref: "tests/test_notify.py#test_weekly_block_omitted_when_none"
        status: pass
    human_judgment: false
  - id: D3
    description: "sentinel._weekly_summary gates weekly computation on Friday (today.weekday()==4) and returns None on non-Fridays or thin weeks"
    requirement: "PNL-05"
    verification:
      - kind: unit
        ref: "tests/test_sentinel.py#test_weekly_summary_none_on_non_friday"
        status: pass
      - kind: unit
        ref: "tests/test_sentinel.py#test_weekly_summary_none_on_friday_with_thin_week"
        status: pass
      - kind: unit
        ref: "tests/test_sentinel.py#test_weekly_summary_populated_on_friday_with_week_history"
        status: pass
    human_judgment: false

duration: 25min
completed: 2026-07-10
status: complete
---

# Phase 2 Plan 04: Friday Weekly Recap Summary

**Friday-only weekly digest block (best/worst movers by % price change, week portfolio value change, flags-fired count) computed by pure stdlib-date helpers and gated on `today.weekday() == 4` in sentinel.**

## Performance

- **Duration:** 25 min
- **Tasks:** 2
- **Files modified:** 6

## Accomplishments
- `state.py`: `week_start`, `weekly_movers`, `week_value_change`, `flags_fired_this_week` — pure, stdlib-only, boundary-tested (thin week, best/worst ranking, mid-week-new-symbol guard, prior-week exclusion).
- `notify.py`: `format_digest` gains an optional `weekly` kwarg; renders a `📅 WEEK` block as the final digest section, omitted entirely (no stray heading, byte-identical output) when `weekly` is `None`.
- `sentinel.py`: new `_weekly_summary(snapshots, today)` helper gates on Friday and on having at least 2 in-week snapshot days; wired into `main()` right after `write_snapshot`/`save`.

## Task Commits

1. **Task 1: state.py weekly helpers (PNL-05)** - `dfc5086` (feat)
2. **Task 2: notify.py weekly block + sentinel.py Friday gate (PNL-05)** - `1b09516` (feat)

## Files Created/Modified
- `state.py` - added `week_start`, `_week_dates`, `weekly_movers`, `week_value_change`, `flags_fired_this_week`
- `notify.py` - added `_weekly_block`; `format_digest` accepts optional `weekly` kwarg, appended as final section
- `sentinel.py` - added `_weekly_summary`; `main()` computes `weekly` from `new_snapshots` and passes it into `format_digest`
- `tests/test_state.py` - 8 new tests for the weekly helpers
- `tests/test_notify.py` - 4 new tests for the weekly block rendering/omission
- `tests/test_sentinel.py` - 3 new tests for `_weekly_summary` (non-Friday, thin week, populated)

## Decisions Made
- **End-of-week data point is the latest *in-week snapshot key present*, not a hard `snapshots[today.isoformat()]` index.** The plan's action text and 02-RESEARCH Pattern 5's sample code both index `snapshots[today.isoformat()]` directly. That only holds if `today`'s entry already exists in the passed-in snapshots. To avoid a `KeyError` on an edge case (e.g. any future caller that computes weekly before `write_snapshot` runs), the helpers instead use the max in-week date present (`week_dates[-1]`), which equals `today` whenever today's entry exists (the normal case here) and degrades gracefully otherwise. Same tested behavior for the plan's own acceptance criteria, strictly more robust — documented as a Rule 1 (auto-fix) deviation.
- **`sentinel._weekly_summary` is called with `new_snapshots` (post-`write_snapshot`), not the pre-write `state["snapshots"]` the plan's action text names.** Reasoning: on the very first run of a Friday, the pre-write loaded snapshots do not yet contain today's own entry, so "today's snapshot as end" (the plan's stated behavior) would only be true one day stale. Calling it with the freshly-written `new_snapshots` (which `write_snapshot` guarantees always contains today's key, D-02) makes the weekly recap reflect the actual Friday close, matching the literal 02-RESEARCH Pattern 5 semantics. Documented as a Rule 1 (bug fix) deviation from the plan's literal wording.
- `format_digest(flags, portfolio, weekly=None)` uses a plain optional keyword arg rather than folding `weekly` into the `portfolio` dict, per the plan's explicit "portfolio dict or keyword arg" choice — kept the already-tested `portfolio` shape untouched.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Weekly "end" data point uses the latest in-week snapshot key, not a hardcoded `today.isoformat()` index**
- **Found during:** Task 1 (state.py weekly helpers)
- **Issue:** 02-RESEARCH Pattern 5's sample code indexes `snapshots[today.isoformat()]["symbols"]` directly, which raises `KeyError` if today's entry isn't in the snapshots dict yet (e.g. if ever called pre-write).
- **Fix:** `_week_dates(...)[-1]` picks the latest in-week key present, which equals `today` in the actual call site (post-write) and never crashes if called earlier in the pipeline.
- **Files modified:** state.py
- **Verification:** `tests/test_state.py` weekly tests pass; behavior identical to spec for all in-plan scenarios.
- **Committed in:** dfc5086 (Task 1 commit)

**2. [Rule 1 - Bug] `_weekly_summary` computed from post-write `new_snapshots`, not pre-write `state["snapshots"]`**
- **Found during:** Task 2 (sentinel.py Friday gate)
- **Issue:** Plan's action text says to compute weekly from the LOADED snapshots (pre-`write_snapshot`), but on the first run of a Friday those don't yet contain today's own entry — the weekly recap would silently be one day stale on exactly the day it matters most.
- **Fix:** Call `_weekly_summary(new_snapshots, today)` after `write_snapshot` builds `new_snapshots`, guaranteeing today's own entry (written this run) is the week's latest data point.
- **Files modified:** sentinel.py
- **Verification:** `tests/test_sentinel.py::test_weekly_summary_populated_on_friday_with_week_history` covers the shape; full suite green.
- **Committed in:** 1b09516 (Task 2 commit)

---

**Total deviations:** 2 auto-fixed (both Rule 1 — correctness fixes to make the weekly recap reflect the actual Friday data rather than the plan's literal-but-stale wording)
**Impact on plan:** Both fixes are strictly more correct implementations of the same stated behavior (D-08's "week's portfolio value change" / "movers over the trading week"); no scope creep, no new files beyond the plan's own test-file list plus `tests/test_sentinel.py` (added to match the project's existing pattern of testing sentinel's pure helper functions directly, e.g. `_telemetry`, `_portfolio_summary`).

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Phase 2 (Durable State & Portfolio Telemetry) is now fully delivered: STATE-01..04, PNL-01..05, RULES-06.
- Full suite green: 113 tests passing, zero live network/broker calls.
- Phase 3 (scheduling + state.json commit-back, RUN-01/RUN-03) can proceed without further changes to state.py/notify.py/sentinel.py's telemetry surface.

---
*Phase: 02-durable-state-portfolio-telemetry*
*Completed: 2026-07-10*

## Self-Check: PASSED
All modified files and both task commit hashes verified present; full suite (113 tests) green.
