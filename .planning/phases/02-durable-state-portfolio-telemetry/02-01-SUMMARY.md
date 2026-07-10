---
phase: 02-durable-state-portfolio-telemetry
plan: 01
subsystem: rules-engine
tags: [pure-functions, rules-engine, telegram-digest, corp-action-detection]

requires:
  - phase: 01-mvp-digest
    provides: pure rules.evaluate(holdings, state, today) ladder, notify.format_digest

provides:
  - "_detect_corp_action(prior_qty, prior_avg, qty, avg_cost) -> bool pure helper (RULES-06)"
  - "CORP_ACTION flag that overrides STOP/BOOK/AVERAGE when a bonus/split is detected"
  - "peak rescale on corp-action (peak *= prior_qty/qty) so TRAIL WATCH stays meaningful"
  - "new_state[symbol] extended to {peak, qty, avg_cost} -- the D-03 peaks schema baseline"
  - "notify.py CORP ACTION rendering (ACTION group, warning emoji, pct suppressed)"

affects: [02-02-durable-state-persistence, state.py]

tech-stack:
  added: []
  patterns:
    - "Two-condition corp-action detector: qty jump AND capital-flat, never qty growth alone"
    - "Peak rescale before max(peak, ltp) so pre-action peaks stay comparable post-action"
    - "Rebuild-not-merge new_state loop already satisfied prune/re-seed -- only add tests"

key-files:
  created: []
  modified:
    - rules.py
    - notify.py
    - tests/test_rules.py
    - tests/test_notify.py

key-decisions:
  - "CORP_ACTION flag string is \"CORP ACTION\" (space, matching NO_PRICE/BOOK 50% spacing style) per plan direction, not the hyphenated \"CORP-ACTION\" spelling used in 02-CONTEXT.md prose"
  - "QTY_JUMP_PCT=0.05 and COST_FLAT_TOLERANCE=0.05 placed as named constants next to the other RULES-03 thresholds"
  - "Corp-action override only replaces STOP/BOOK/AVERAGE; TRIM and TRAIL WATCH still evaluate and take precedence over CORP_ACTION when they fire"

patterns-established:
  - "Pure detector functions take injected prior state, never read global/mutable state -- keeps rules.py side-effect-free"

requirements-completed: [RULES-06, STATE-01, STATE-02, STATE-03]

coverage:
  - id: D1
    description: "_detect_corp_action distinguishes a bonus/split (qty jump + capital flat) from a genuine AVERAGE-down buy (qty jump + capital moves)"
    requirement: "RULES-06"
    verification:
      - kind: unit
        ref: "tests/test_rules.py#test_detect_corp_action_true_on_bonus_shape"
        status: pass
      - kind: unit
        ref: "tests/test_rules.py#test_detect_corp_action_false_on_real_average_buy"
        status: pass
      - kind: unit
        ref: "tests/test_rules.py#test_detect_corp_action_false_when_no_prior_qty"
        status: pass
      - kind: unit
        ref: "tests/test_rules.py#test_detect_corp_action_false_when_qty_growth_at_or_below_threshold"
        status: pass
    human_judgment: false
  - id: D2
    description: "evaluate() overrides STOP/BOOK/AVERAGE with CORP_ACTION (pct=None) on corp-action detection, while TRIM and TRAIL WATCH still resolve normally"
    requirement: "RULES-06"
    verification:
      - kind: unit
        ref: "tests/test_rules.py#test_corp_action_overrides_would_be_average_flag_and_hides_pct"
        status: pass
      - kind: unit
        ref: "tests/test_rules.py#test_corp_action_overweight_still_trims"
        status: pass
      - kind: unit
        ref: "tests/test_rules.py#test_corp_action_still_trail_watches_far_below_peak"
        status: pass
    human_judgment: false
  - id: D3
    description: "Peak is rescaled by prior_qty/qty on corp-action so a post-bonus price is not read as a phantom drawdown"
    requirement: "STATE-01"
    verification:
      - kind: unit
        ref: "tests/test_rules.py#test_corp_action_rescales_peak_avoiding_phantom_trail_watch"
        status: pass
    human_judgment: false
  - id: D4
    description: "new_state[symbol] carries {peak, qty, avg_cost}; a sold symbol is pruned; a rebought symbol re-seeds its peak"
    requirement: "STATE-02"
    verification:
      - kind: unit
        ref: "tests/test_rules.py#test_new_state_carries_qty_and_avg_cost_forward"
        status: pass
      - kind: unit
        ref: "tests/test_rules.py#test_symbol_dropped_from_holdings_is_pruned_from_new_state"
        status: pass
      - kind: unit
        ref: "tests/test_rules.py#test_rebought_symbol_reseeds_peak_from_max_ltp_avgcost"
        status: pass
    human_judgment: false
  - id: D5
    description: "notify.py renders CORP ACTION in the ACTION group with a warning emoji/verb and no percentage shown"
    requirement: "STATE-03"
    verification:
      - kind: unit
        ref: "tests/test_notify.py#test_corp_action_renders_in_action_group_with_no_pct"
        status: pass
    human_judgment: false

duration: 16min
completed: 2026-07-10
status: complete
---

# Phase 2 Plan 1: Corp-Action Detection + Peak Rescale Summary

**Pure two-condition corp-action detector (qty jump AND capital-flat) overrides STOP/BOOK/AVERAGE with a CORP ACTION flag, rescales the stored peak so a bonus/split can't fire a phantom TRAIL WATCH, and extends `new_state` to carry qty/avg_cost as next run's detection baseline.**

## Performance

- **Duration:** 16 min
- **Started:** 2026-07-10T12:04:27+05:30
- **Completed:** 2026-07-10T12:19:25+05:30
- **Tasks:** 3
- **Files modified:** 4 (rules.py, notify.py, tests/test_rules.py, tests/test_notify.py)

## Accomplishments
- `_detect_corp_action(prior_qty, prior_avg, qty, avg_cost)` pure helper: qty grew >5% AND invested capital changed <5% -> corp action; qty growth alone (a genuine large AVERAGE buy) never trips it
- `evaluate()` overrides STOP/BOOK/AVERAGE with `CORP_ACTION` (pct=None, shares=0) on detection, while TRIM (over-weight) and TRAIL WATCH (peak-based) still resolve normally and take precedence
- Stored peak rescaled `peak *= prior_qty/qty` on corp-action detection before the `max(peak, ltp)` step, so a post-bonus price isn't misread as a >20% drawdown
- `new_state[symbol]` extended from `{peak}` to `{peak, qty, avg_cost}` -- the exact baseline `_detect_corp_action` needs next run and the shape `state.py` will persist in 02-02
- Prune (sold symbol dropped from `new_state`) and re-seed (rebuy gets a fresh peak) proven correct by new tests against the existing rebuild-not-merge loop -- no new code needed for those
- `notify.py`: CORP ACTION added to `_ACTION_FLAGS` (never silently dropped), warning emoji + verb explaining the P&L flag is intentionally withheld, pct suppressed like the existing NO PRICE branch

## Task Commits

Each task was committed atomically (TDD RED -> GREEN):

1. **Task 1: rules.py -- corp-action detection + CORP ACTION flag**
   - `c196900` test(02-01): add failing corp-action detection tests
   - `8f69502` feat(02-01): detect corp-action and override P&L flags (RULES-06)
2. **Task 2: rules.py -- peak rescale + qty/avg_cost carry-forward + prune**
   - `d31d5cd` test(02-01): add failing peak-rescale and state carry-forward tests
   - `fec57d1` feat(02-01): rescale peak on corp-action + carry qty/avg_cost forward
3. **Task 3: notify.py -- render the CORP ACTION line**
   - `a0158bc` feat(02-01): render CORP ACTION line in digest (RULES-06)

**Plan metadata:** committed together with this SUMMARY (see final commit below)

_Note: Task 3 was `type="auto"` (not tdd="true") per plan frontmatter, so a single commit; RED was still verified manually before implementing (test run confirmed failure), matching the spirit of TDD without an extra commit the plan didn't ask for._

## Files Created/Modified
- `rules.py` -- `CORP_ACTION` flag, `QTY_JUMP_PCT`/`COST_FLAT_TOLERANCE` constants, `_detect_corp_action()`, corp-action override branch in `evaluate()`, peak rescale, extended `new_state` shape
- `notify.py` -- `CORP ACTION` added to `_ACTION_FLAGS`, `_EMOJI`, `_VERB`; `_context()` suppresses pct for it
- `tests/test_rules.py` -- 13 new tests: detector unit tests, evaluate-level override/precedence tests, peak-rescale test, carry-forward/prune/re-seed tests
- `tests/test_notify.py` -- 1 new test: CORP ACTION renders with no pct

## Decisions Made
- Used the plan's explicit direction for the flag string spelling: `"CORP ACTION"` (space, matching `NO_PRICE`/`"BOOK 50%"` spacing convention already in `rules.py`), not the `CORP-ACTION` hyphenated form that appears in 02-CONTEXT.md's prose -- the plan's `<action>` block for Task 1 is unambiguous on this and it's what `notify.py`'s grouping lookup must match exactly.
- Corp-action override precedence: TRIM and TRAIL WATCH are checked *before* falling through to `CORP_ACTION` (matching D-09's "only STOP/BOOK/AVERAGE are replaced" instruction) -- verified by dedicated tests for both.
- Warning glyph for CORP ACTION chosen as `⚠️` (Claude's discretion per D-09/02-CONTEXT, no constraint on the specific emoji).

## Deviations from Plan

None - plan executed exactly as written. All behavior-block scenarios and acceptance criteria were implemented as specified; no Rule 1-4 auto-fixes were needed.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required. This plan is pure logic + tests; no I/O, no new dependencies (stdlib-only, matching 02-RESEARCH's Package Legitimacy Audit).

## Next Phase Readiness

- `rules.py` remains fully pure (verified: no `os.`/`json.`/`requests`/`datetime.now`/`date.today` in the file) and returns the exact `{peak, qty, avg_cost}` shape that 02-02's `state.py` needs to persist under `state["peaks"]`.
- Full suite green: 67 tests pass (`python -m pytest -q`), up from 55 before this plan -- no Phase 1 regressions.
- Sentinel still passes `{}` as state (no live persistence yet) -- 02-02 wires `state.load()`/`state.save()` so this corp-action logic actually fires end-to-end across runs.

---
*Phase: 02-durable-state-portfolio-telemetry*
*Completed: 2026-07-10*

## Self-Check: PASSED
All created/modified files found on disk; all 5 task commit hashes found in git log.
