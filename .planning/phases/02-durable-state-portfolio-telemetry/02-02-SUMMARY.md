---
phase: 02-durable-state-portfolio-telemetry
plan: 02
subsystem: state-persistence
tags: [atomic-write, json, sentiment-cache, pure-helpers, stdlib-only]

requires:
  - phase: 02-durable-state-portfolio-telemetry
    provides: "rules.evaluate new_state = {peak, qty, avg_cost} shape (02-01); corp-action detection consumes prior state"

provides:
  - "state.py -- load(path)/save(state, path) atomic temp-file+os.replace write, corrupt/missing-file fallback to empty shape"
  - "state.write_snapshot(snapshots, today, total_value, per_symbol, flags_fired, keep=10) -- pure, date-keyed overwrite, bounded prune"
  - "sentiment.adjust(flags, api_key, cache, today) -> (flags, new_cache) same-day cache, ~1 model call/day"
  - "sentinel.py real end-to-end wiring: state.load -> rules.evaluate(peaks) -> sentiment.adjust(cache) -> write_snapshot -> state.save"

affects: [02-03-portfolio-telemetry-pnl, 02-04-weekly-summary]

tech-stack:
  added: []
  patterns:
    - "Pure I/O shell (state.py) vs pure core (rules.py) split maintained -- write_snapshot has zero disk access, fully unit-testable"
    - "Atomic write: tempfile.mkstemp in target's own directory + os.replace, unlink+reraise on failure -- no new dependency"
    - "Same-day cache keyed by ISO date string; miss/stale triggers exactly one batched re-score, hit/error both carry the prior entry forward unchanged"

key-files:
  created:
    - state.py
    - tests/test_state.py
  modified:
    - sentiment.py
    - sentinel.py
    - tests/test_sentiment.py
    - tests/test_sentinel.py

key-decisions:
  - "sentiment.adjust's error-path carries the PRIOR cache entry forward unchanged for symbols whose score_batch call failed, rather than dropping them -- matches the plan's 'cache unchanged for the failed symbols' behavior spec exactly"
  - "new_cache is built from only {same-day reused} ∪ {carried-forward on error} ∪ {freshly scored}, then pruned to symbols present in the current flags list (D-05) -- a symbol's cache entry naturally ages out once it's no longer an AVERAGE candidate or no longer held, no separate prune step needed"
  - "sentinel.py imports state.py as `state_mod` (not `state`) to avoid shadowing the per-run loaded-state local variable, matching 02-RESEARCH's wiring example exactly"
  - "snapshot write uses the LOADED (pre-write) state[\"snapshots\"] dict for both write_snapshot's overwrite and any future day-change lookup, per 02-RESEARCH Pattern 3 -- avoids the off-by-one where a same-day rerun would diff against itself"

patterns-established:
  - "Impure shell modules (state.py, sentiment.py) always take an explicit path/cache/today argument rather than reading a global -- keeps every I/O boundary testable via tmp_path/mocks, no monkeypatching of module-level constants needed"

requirements-completed: [STATE-01, STATE-02, STATE-03, STATE-04]

coverage:
  - id: D1
    description: "state.py load()/save() atomic round-trip; missing or corrupt state.json falls back to the empty {peaks, snapshots, sentiment} shape instead of crashing"
    requirement: "STATE-04"
    verification:
      - kind: unit
        ref: "tests/test_state.py#test_load_missing_file_returns_empty_shape"
        status: pass
      - kind: unit
        ref: "tests/test_state.py#test_load_corrupt_json_returns_empty_shape"
        status: pass
      - kind: unit
        ref: "tests/test_state.py#test_save_then_load_round_trips"
        status: pass
      - kind: unit
        ref: "tests/test_state.py#test_save_is_atomic_leaves_no_temp_file"
        status: pass
    human_judgment: false
  - id: D2
    description: "write_snapshot is a pure, non-mutating helper: same-day key overwrites (idempotent rerun), history bounded to the most recent `keep` dated entries"
    requirement: "STATE-04"
    verification:
      - kind: unit
        ref: "tests/test_state.py#test_write_snapshot_overwrites_same_day_key"
        status: pass
      - kind: unit
        ref: "tests/test_state.py#test_write_snapshot_does_not_mutate_input"
        status: pass
      - kind: unit
        ref: "tests/test_state.py#test_write_snapshot_prunes_to_keep_n"
        status: pass
    human_judgment: false
  - id: D3
    description: "sentiment.adjust caches AVERAGE scores per calendar day: same-day hit skips fetch/score entirely (still downgrades on cached bearish); stale/miss triggers exactly one batched re-score; a scorer error carries the prior cache entry forward unchanged"
    requirement: "STATE-04"
    verification:
      - kind: unit
        ref: "tests/test_sentiment.py#test_same_day_cache_hit_skips_fetch_and_score_batch"
        status: pass
      - kind: unit
        ref: "tests/test_sentiment.py#test_stale_next_day_cache_entry_triggers_rescore"
        status: pass
      - kind: unit
        ref: "tests/test_sentiment.py#test_scorer_error_keeps_prior_cache_entry_for_failed_symbol"
        status: pass
      - kind: unit
        ref: "tests/test_sentiment.py#test_new_cache_pruned_to_symbols_in_current_flags"
        status: pass
    human_judgment: false
  - id: D4
    description: "sentinel.py wires real state end-to-end: rules.evaluate receives the LOADED peaks (not {}); state.save persists {peaks, snapshots, sentiment} with flags_fired in the snapshot -- so peaks now genuinely persist across runs"
    requirement: "STATE-01"
    verification:
      - kind: unit
        ref: "tests/test_sentinel.py#test_main_wires_real_state_load_evaluate_save"
        status: pass
    human_judgment: false

duration: 4min
completed: 2026-07-10
status: complete
---

# Phase 2 Plan 2: Durable State Persistence + Sentiment Cache Summary

**Atomic-write state.json (temp-file + os.replace) now round-trips peaks/snapshots/sentiment across runs, sentinel.py wires it end-to-end through rules.evaluate and sentiment.adjust, and sentiment gained a same-day cache so hourly reruns cost ~1 Gemini call/day instead of one per run.**

## Performance

- **Duration:** 4 min
- **Started:** 2026-07-10T12:25:54+05:30
- **Completed:** 2026-07-10T12:29:25+05:30
- **Tasks:** 3
- **Files modified:** 6 (state.py, sentiment.py, sentinel.py, tests/test_state.py, tests/test_sentiment.py, tests/test_sentinel.py)

## Accomplishments
- New `state.py`: `load(path="state.json")` guards `FileNotFoundError` AND `json.JSONDecodeError`, falling back to `{"peaks": {}, "snapshots": {}, "sentiment": {}}` (V5 defense-in-depth); `save()` writes via `tempfile.mkstemp` in the target's own directory + `os.replace` (T-02-02, atomic on the ubuntu-latest runner) -- a crash mid-write can never leave a partial file
- `write_snapshot(snapshots, today, total_value, per_symbol, flags_fired, keep=10)` is a pure, non-mutating helper: date-keyed dict write (overwrite, not append) makes a same-day rerun idempotent (STATE-04/D-02); `sorted(...)[-keep:]` bounds history to ~10 entries (D-05)
- `sentiment.adjust` signature changed to `(flags, api_key, cache, today) -> (flags, new_cache)`; an AVERAGE candidate already scored today reuses its cached label/reason without a fetch or model call (D-10), collapsing N hourly reruns to ~1 model call/day; a scorer error carries the prior cache entry forward unchanged (never breaks the run); `new_cache` is pruned to symbols still present in the current flags list (D-05)
- `sentinel.py`'s `main()` no longer passes `state={}` to `rules.evaluate` -- it loads real state near the top, passes `state["peaks"]` through, threads `state["sentiment"]`/`today` into `sentiment.adjust`, builds per-symbol `{price, value}` + `flags_fired` (flags not in `{HOLD, NO PRICE}`), writes the snapshot against the LOADED (pre-write) snapshots dict, and saves `{peaks, snapshots, sentiment}` atomically before formatting the digest
- Peaks are now genuinely durable end-to-end: 02-01's corp-action detection, peak rescale, and TRAIL WATCH mechanics -- previously inert against `state={}` -- now fire for real across runs

## Task Commits

Each task was committed atomically (TDD RED -> GREEN for tasks 1-2; task 3 is `type="auto"`, single commit):

1. **Task 1: state.py -- atomic load/save + snapshot write/prune (STATE-04)**
   - `1648870` test(02-02): add failing tests for state.py atomic load/save + snapshot prune (STATE-04)
   - `32e8f21` feat(02-02): state.py atomic load/save + snapshot write/prune (STATE-04)
2. **Task 2: sentiment.py -- same-day cache (D-10)**
   - `54bbb99` test(02-02): add failing tests for sentiment same-day cache (D-10)
   - `c8853e8` feat(02-02): sentiment.py same-day cache, adjust returns (flags, new_cache) (D-10)
3. **Task 3: sentinel.py -- wire real state end-to-end**
   - `4ea9ac6` feat(02-02): wire real state.json through sentinel.py (STATE-01..04)

**Plan metadata:** committed together with this SUMMARY (see final commit below)

## Files Created/Modified
- `state.py` -- new module: `load`, `save` (atomic write), `write_snapshot` (pure, date-keyed overwrite + prune)
- `tests/test_state.py` -- new: 7 tests covering missing/corrupt-file fallback, round-trip, atomicity (no leftover temp file), same-day overwrite, non-mutation, prune-to-keep-N
- `sentiment.py` -- `adjust()` signature extended to `(flags, api_key, cache, today) -> (flags, new_cache)`; same-day cache hit/miss/stale branching; error carries prior cache forward
- `tests/test_sentiment.py` -- 11 tests total (8 existing updated for the tuple return + 3 new: same-day hit, stale rescore, error carry-forward, prune)
- `sentinel.py` -- `main()` loads/saves real state; `rules.evaluate` receives `state["peaks"]`; `sentiment.adjust` receives `state["sentiment"]`/`today`; snapshot built and saved before the digest send
- `tests/test_sentinel.py` -- added `test_main_wires_real_state_load_evaluate_save`, fully mocking broker/prices/state I/O to prove the wiring without live calls

## Decisions Made
- On a `score_batch` failure, the prior cache entry for the affected symbol(s) is explicitly carried forward into `new_cache` rather than silently dropped -- keeps yesterday's (or an older) cached label available on the next attempt instead of losing it to a transient API error.
- `new_cache` construction is deliberately narrow: only same-day-reused + error-carried + freshly-scored entries are considered, then pruned to symbols in the current `flags` list. A symbol's old cache entry for a day it wasn't an AVERAGE candidate simply doesn't survive into `new_cache` -- acceptable since D-10's cache only exists to gate the AVERAGE-specific model call.
- Imported `state.py` as `state_mod` in `sentinel.py` (not `state`) to avoid shadowing the per-run loaded-state local variable named `state`, matching 02-RESEARCH's wiring example.

## Deviations from Plan

None - plan executed exactly as written. All behavior-block scenarios and acceptance criteria for all three tasks were implemented as specified; no Rule 1-4 auto-fixes were needed.

## Issues Encountered

None. `.venv` (already provisioned) has `pytest==8.4.2` installed; `python -m pytest` was invoked via `source .venv/bin/activate` since the bare `python`/`python3` binaries on this machine don't have pytest installed globally.

## User Setup Required

None - no external service configuration required. state.py is stdlib-only (json/os/tempfile); no new dependency, no new secret.

## Next Phase Readiness

- `state.json` now round-trips real data at the repo root (a local file only -- per 02-CONTEXT.md, committing it back to the repo is Phase 3/RUN-03, intentionally not done here).
- Full suite green: **79 tests pass** (`python -m pytest -q`), up from 67 before this plan -- 12 new tests (7 state.py + 4 sentiment cache + 1 sentinel wiring; net delta reflects some renumbering of existing sentiment tests for the new signature).
- `state["snapshots"]` (loaded, pre-write) is now available in `sentinel.py`'s `main()` exactly where 02-03's day-change/trend lookups need to read it -- per 02-RESEARCH Pattern 3, that lookup must happen before `write_snapshot` overwrites today's key.
- `rules.py` remains untouched and fully pure this plan (grep confirms no `os.`/`json.`/`open(`/clock calls added) -- all persistence lives in `state.py` + `sentinel.py` as designed.

---
*Phase: 02-durable-state-portfolio-telemetry*
*Completed: 2026-07-10*

## Self-Check: PASSED
All created/modified files found on disk; all 5 task commit hashes found in git log.
