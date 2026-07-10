---
phase: 02-durable-state-portfolio-telemetry
plan: 03
subsystem: portfolio-telemetry
tags: [pure-helpers, yfinance-fast_info, digest-header, day-change, trend]

requires:
  - phase: 02-durable-state-portfolio-telemetry
    provides: "state.py snapshots dict shape (write_snapshot, date-keyed, pre-write LOADED read) from 02-02"

provides:
  - "state.day_change(snapshots, today) -> float|None -- prior-day baseline, D-12 off-by-one safe"
  - "state.n_day_trend(snapshots, today, n=5) -> {days, baseline}|None -- actual window length, never hardcoded 5d"
  - "prices.get_intraday(symbols) -> {sym: {prev_close, last_price}} via yfinance fast_info"
  - "notify.format_digest header telemetry line: P&L / Day / Nd trend / Intraday, each omitted cleanly when None"
  - "sentinel._telemetry(snapshots, today, total_value, merged) -- wires day-change/trend/intraday from LOADED snapshots into the portfolio dict"

affects: [02-04-weekly-summary]

tech-stack:
  added: []
  patterns:
    - "Pure snapshot-math helpers in state.py (day_change, n_day_trend) -- zero disk access, same discipline as write_snapshot"
    - "Value-weighted portfolio intraday %% computed in sentinel.py from per-symbol prev_close/last_price, best-effort wrapped so a yfinance hiccup degrades to None rather than breaking the run"
    - "Telemetry fields threaded through the portfolio dict as optional keys (day_change_pct, trend, intraday_pct) -- notify.py renders each only when not None"

key-files:
  created: []
  modified:
    - state.py
    - prices.py
    - notify.py
    - sentinel.py
    - tests/test_state.py
    - tests/test_prices.py
    - tests/test_notify.py
    - tests/test_sentinel.py

key-decisions:
  - "day_change/n_day_trend both filter `date < today.isoformat()` explicitly (D-12) -- never sorted(keys)[-2], which would grab today's own earlier value on the 2nd+ hourly run of a day; a dedicated regression test covers exactly this case"
  - "get_intraday is additive and untouched get_prev_close -- PNL-01/02/03 continue reading the batched yf.download path; PNL-04 uses the separate, purpose-built fast_info per-Ticker path since it exposes distinct prev_close/last_price attributes get_prev_close doesn't"
  - "sentinel._telemetry wraps the intraday fetch in its own try/except so a yfinance hiccup only drops intraday_pct to None, never aborts the whole digest -- day_change/trend (pure, no I/O) can't fail the same way"
  - "Fixed test_main_wires_real_state_load_evaluate_save to mock prices.get_intraday -- the new wiring in sentinel.main() would otherwise have made a live yfinance network call from that test (caught via a yfinance deprecation warning appearing in test output before the fix)"

patterns-established:
  - "Header telemetry line construction (notify._telemetry_line) isolates the P&L/Day/Trend/Intraday formatting from format_digest's grouping logic -- future telemetry additions (e.g. weekly block, 02-04) extend this helper or add a sibling, not format_digest itself"

requirements-completed: [PNL-01, PNL-02, PNL-03, PNL-04]

coverage:
  - id: D1
    description: "day_change returns the strictly-prior-day total_value, None on first run, and correctly returns yesterday's value even when today's own key already exists in snapshots (2nd+ hourly run of a day)"
    requirement: "PNL-02"
    verification:
      - kind: unit
        ref: "tests/test_state.py#test_day_change_picks_strictly_before_today_entry"
        status: pass
      - kind: unit
        ref: "tests/test_state.py#test_day_change_returns_none_with_only_todays_key"
        status: pass
      - kind: unit
        ref: "tests/test_state.py#test_day_change_still_returns_yesterday_when_today_already_in_snapshots"
        status: pass
    human_judgment: false
  - id: D2
    description: "n_day_trend reports the actual available window length (not a hardcoded 5d) for 0/2/7-day prior histories, capped at n"
    requirement: "PNL-03"
    verification:
      - kind: unit
        ref: "tests/test_state.py#test_n_day_trend_none_with_no_prior_day"
        status: pass
      - kind: unit
        ref: "tests/test_state.py#test_n_day_trend_reports_actual_window_length_under_n"
        status: pass
      - kind: unit
        ref: "tests/test_state.py#test_n_day_trend_caps_window_at_n_over_longer_history"
        status: pass
    human_judgment: false
  - id: D3
    description: "get_intraday returns prev_close/last_price per symbol via fast_info, degrades to None values on failure, and makes no live network call for an empty symbol list"
    requirement: "PNL-04"
    verification:
      - kind: unit
        ref: "tests/test_prices.py#test_get_intraday_returns_prev_close_and_last_price"
        status: pass
      - kind: unit
        ref: "tests/test_prices.py#test_get_intraday_maps_failing_symbol_to_none_values"
        status: pass
      - kind: unit
        ref: "tests/test_prices.py#test_get_intraday_empty_symbols_returns_empty_without_calling_yfinance"
        status: pass
    human_judgment: false
  - id: D4
    description: "Digest header renders P&L always, and Day/Nd-trend/Intraday only when present, with the trend label reflecting the true window length"
    requirement: "PNL-01, PNL-02, PNL-03, PNL-04"
    verification:
      - kind: unit
        ref: "tests/test_notify.py#test_header_shows_day_change_trend_and_intraday_when_present"
        status: pass
      - kind: unit
        ref: "tests/test_notify.py#test_header_omits_day_change_when_none"
        status: pass
      - kind: unit
        ref: "tests/test_notify.py#test_header_omits_trend_when_none"
        status: pass
      - kind: unit
        ref: "tests/test_notify.py#test_header_omits_intraday_when_none"
        status: pass
      - kind: unit
        ref: "tests/test_notify.py#test_header_trend_label_reflects_actual_window_length"
        status: pass
    human_judgment: false
  - id: D5
    description: "sentinel._telemetry computes day-change/trend from the loaded (pre-write) snapshots and a value-weighted intraday %% from prices.get_intraday, best-effort so an intraday fetch failure never breaks the digest"
    requirement: "PNL-02, PNL-03, PNL-04"
    verification:
      - kind: unit
        ref: "tests/test_sentinel.py#test_telemetry_computes_day_change_and_trend_from_loaded_snapshots"
        status: pass
      - kind: unit
        ref: "tests/test_sentinel.py#test_telemetry_omits_day_change_and_trend_on_first_run"
        status: pass
      - kind: unit
        ref: "tests/test_sentinel.py#test_telemetry_computes_value_weighted_intraday_pct"
        status: pass
      - kind: unit
        ref: "tests/test_sentinel.py#test_telemetry_intraday_none_when_source_lacks_prev_close"
        status: pass
      - kind: unit
        ref: "tests/test_sentinel.py#test_telemetry_never_raises_on_intraday_fetch_failure"
        status: pass
    human_judgment: false

duration: 6min
completed: 2026-07-10
status: complete
---

# Phase 2 Plan 3: Portfolio Telemetry (P&L, Day Change, Trend, Intraday) Summary

**Digest header now carries overall P&L, day change vs the prior day's stored snapshot, an N-day trend with an honest window label, and a value-weighted intraday %% -- all computed from pure state-math helpers plus a new yfinance fast_info price path, each omitted cleanly (never 0% or a crash) when its data isn't available.**

## Performance

- **Duration:** 6 min
- **Started:** 2026-07-10T07:02:00Z
- **Completed:** 2026-07-10T07:08:05Z
- **Tasks:** 3
- **Files modified:** 8 (state.py, prices.py, notify.py, sentinel.py, tests/test_state.py, tests/test_prices.py, tests/test_notify.py, tests/test_sentinel.py)

## Accomplishments

- `state.day_change(snapshots, today)` and `state.n_day_trend(snapshots, today, n=5)`: two pure helpers added alongside `write_snapshot`, sharing a private `_prior_dates` filter (`date < today.isoformat()`) that is the D-12 off-by-one fix -- never `sorted(keys)[-2]`, which would silently diff today against itself on the second-or-later hourly run of a day. A dedicated regression test (`test_day_change_still_returns_yesterday_when_today_already_in_snapshots`) locks this in.
- `n_day_trend` returns `{"days": len(window), "baseline": ...}` using whatever prior-day window actually exists (0/2/5/7-day cases all tested) so the digest never claims a "5d" trend from two days of real history.
- `prices.get_intraday(symbols)`: new additive helper using `yfinance.Ticker(...).fast_info.previous_close`/`.last_price` (the purpose-built lightweight path per 02-RESEARCH, not the slower `.info` dict). Per-symbol failures degrade to `{prev_close: None, last_price: None}`; empty input makes zero `Ticker` calls. `get_prev_close` is completely untouched -- PNL-01/02/03 keep using the existing batched `yf.download` path.
- `notify._telemetry_line`: renders `P&L +17.1% · Day +1.2% · 5d ↗ +3.4% · Intraday +0.6%` style output, appending Day/trend/intraday only when their portfolio dict keys are not `None`. `format_digest`'s header now delegates telemetry formatting to this helper instead of inlining P&L directly.
- `sentinel._telemetry(snapshots, today, total_value, merged)`: computes `day_change_pct` and `trend` from `state.day_change`/`state.n_day_trend` against the **loaded** `state["snapshots"]` (called before `write_snapshot` overwrites today's key -- verified by grep: `_telemetry(...)` at sentinel.py:139 runs before `write_snapshot(...)` at line 149), and a value-weighted portfolio `intraday_pct` from `prices.get_intraday` over symbols exposing both `prev_close` and `last_price`. The intraday fetch is wrapped in its own `try/except` so a yfinance hiccup can only drop `intraday_pct` to `None`, never break the run.

## Task Commits

Each task committed atomically:

1. **Task 1: state.py -- day_change + n_day_trend pure helpers (PNL-02, PNL-03)**
   - `113b428` feat(02-03): state.py day_change + n_day_trend pure helpers (PNL-02, PNL-03)
2. **Task 2: prices.py -- intraday %% via fast_info (PNL-04)**
   - `166f744` feat(02-03): prices.py get_intraday via fast_info (PNL-04)
3. **Task 3: notify.py header telemetry + sentinel.py wiring (PNL-01..04)**
   - `abaa72c` feat(02-03): notify.py header telemetry + sentinel.py wiring (PNL-01..04)

**Plan metadata:** committed together with this SUMMARY (see final commit below)

## Files Created/Modified

- `state.py` -- added `day_change`, `n_day_trend`, private `_prior_dates` helper; `write_snapshot` untouched
- `tests/test_state.py` -- +6 tests: strictly-before-today pick, None on today-only, D-12 regression (today's key present, still returns yesterday), trend None/under-window/capped-window cases
- `prices.py` -- added `get_intraday(symbols)`; `get_prev_close` untouched
- `tests/test_prices.py` -- +3 tests: priced symbol returns both numbers (mocked `fast_info`), failing symbol degrades to None values, empty list makes no `Ticker` call
- `notify.py` -- extracted `_telemetry_line` helper; `format_digest`'s header now renders P&L + optional Day/trend/Intraday
- `tests/test_notify.py` -- `portfolio()` helper extended with optional `day_change_pct`/`trend`/`intraday_pct` (default `None`); +5 tests: all-present render, each-None omission (x3), trend label reflects real window length
- `sentinel.py` -- added `_telemetry`; `main()` calls it against the loaded `state["snapshots"]` before `write_snapshot`, merges result into the `portfolio` dict passed to `format_digest`
- `tests/test_sentinel.py` -- +5 `_telemetry` unit tests (day-change/trend from loaded snapshots, first-run omission, value-weighted intraday calc, missing-prev-close omission, fetch-failure never raises); fixed the existing `test_main_wires_real_state_load_evaluate_save` to mock `prices.get_intraday` (see Deviations)

## Decisions Made

- `day_change`/`n_day_trend` share a private `_prior_dates(snapshots, today)` filter rather than duplicating the `sorted(d for d in snapshots if d < today.isoformat())` expression -- DRY, and it's the one place the D-12 off-by-one fix lives.
- `get_intraday` is a fully separate helper from `get_prev_close`, not a parameter added to it -- the two use different yfinance code paths (`fast_info` per-Ticker vs. batched `yf.download`) and different purposes (PNL-04 intraday vs. PNL-01/02/03 previous-close-as-current-price), so keeping them independent avoids conflating two different freshness contracts.
- Portfolio intraday %% is value-weighted (`Σ(qty·last) − Σ(qty·prev_close)) / Σ(qty·prev_close)`) over only the symbols where both numbers are available, rather than an unweighted average of per-symbol %% changes -- matches how the rest of the digest already weights P&L by position size.
- `sentinel._telemetry` takes `merged` (not raw holdings) so it can reuse the same `qty`/`ltp`-shaped records already built in `main()`, keeping the intraday weighting consistent with `_portfolio_summary`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Existing sentinel wiring test made a live yfinance network call after this plan's wiring change**
- **Found during:** Task 3, full-suite run after wiring `_telemetry` into `sentinel.main()`
- **Issue:** `tests/test_sentinel.py::test_main_wires_real_state_load_evaluate_save` monkeypatches `prices.get_prev_close` but, before this fix, did not mock the newly-added `prices.get_intraday` call inside `_telemetry`. Running the full suite surfaced a yfinance internal `DeprecationWarning` in the test output -- proof the test was silently reaching out to the real network (a TEST-02 violation introduced by this plan's own wiring, not a pre-existing bug).
- **Fix:** Added `monkeypatch.setattr(sentinel.prices, "get_intraday", lambda symbols: {})` to that test.
- **Files modified:** `tests/test_sentinel.py`
- **Commit:** `abaa72c` (folded into the Task 3 commit since it was discovered and fixed within that task's verification step)

## Issues Encountered

None beyond the deviation above. `.venv` (already provisioned) has `pytest==8.4.2`; ran via `source .venv/bin/activate`.

## User Setup Required

None -- no new dependency, no new secret. `get_intraday` reuses the already-pinned `yfinance` package.

## Next Phase Readiness

- Full suite green: **98 tests pass** (`python -m pytest -q`), up from 79 before this plan (19 new: 6 state.py + 3 prices.py + 5 notify.py + 5 sentinel.py telemetry tests), zero live network calls confirmed (no yfinance warnings in the final run).
- `rules.py` remains untouched and pure this plan (grep/diff confirms no changes to that file across all three task commits).
- Digest header now visually matches the D-07 example format, confirmed with a manual smoke render: `💰 ₹32.15L · 📈 P&L +17.1% · Day +1.2% · 5d ↗ +3.4% · Intraday +0.6%`.
- Phase 2's remaining plan (02-04, weekly summary / Friday block, PNL-05) can reuse `state["snapshots"]` and the same loaded-before-write ordering established here and in 02-02.

---
*Phase: 02-durable-state-portfolio-telemetry*
*Completed: 2026-07-10*

## Self-Check: PASSED
All modified files found on disk; all 3 task commit hashes found in git log.
