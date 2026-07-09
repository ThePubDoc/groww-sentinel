---
phase: 01-end-to-end-morning-digest
plan: 01
subsystem: rules-engine
tags: [python, pytest, pure-function, decision-engine]

# Dependency graph
requires: []
provides:
  - "rules.py: pure evaluate(holdings, config, state, today) -> (flags, new_state)"
  - "Named threshold constants (AVG tiers, TRIM weight, BOOK gain, STOP drop/below-peak, TRAIL below-peak)"
  - "Ordered precedence resolver: UNTAGGED > STOP HIT > TRIM > BOOK 50% > TRAIL WATCH > AVG CANDIDATE (deepest tier) > HOLD"
  - "requirements.txt pinned dependency set for the whole phase"
  - "tests/test_rules.py: 22-test boundary/precedence/UNTAGGED/reminder suite"
affects: [01-02, 01-03]

# Tech tracking
tech-stack:
  added: [growwapi==1.5.0, pyotp==2.10.0, requests==2.32.3, PyYAML==6.0.3, pytest==8.4.2]
  patterns:
    - "Pure-core/imperative-shell split: rules.py has zero I/O, today/state injected by caller"
    - "Single ordered precedence chain (not independent ifs) for exactly-one-flag resolution"
    - "Strict > at every threshold boundary, uniformly"

key-files:
  created: [requirements.txt, rules.py, tests/test_rules.py, .gitignore]
  modified: []

key-decisions:
  - "D-01/D-02/D-03/D-04/D-13/D-14 implemented as literally specified in 01-CONTEXT.md"
  - "ltp=None short-circuits to an explicit NO PRICE flag before entering the precedence chain (data-quality gate, not a business rule)"
  - "Two AVG tier-2/tier-3 boundary tests use a non-empty state peak (set equal to current ltp) to isolate the AVG tier math from TRAIL WATCH, whose >20%-below-peak threshold is numerically identical to drop-from-avg-cost once Phase 1's peak seed collapses to avg_cost (state={} always) -- rules.py logic unchanged, only the two test fixtures needed this to exercise the resolver's actual tier computation"

patterns-established:
  - "Fixture helper holding()/padded() in tests/test_rules.py keeps target weight <10% by default so price-action boundary tests aren't accidentally short-circuited by TRIM"

requirements-completed: [RULES-01, RULES-02, RULES-03, RULES-04, RULES-05, STATE-05, TEST-01]

coverage:
  - id: D1
    description: "rules.evaluate() returns exactly one flag per held stock, pure, no I/O"
    requirement: "RULES-01"
    verification:
      - kind: unit
        ref: "tests/test_rules.py#test_returns_exactly_one_entry_per_holding"
        status: pass
    human_judgment: false
  - id: D2
    description: "Strict > boundary behavior at every threshold (STOP HIT, TRIM, BOOK 50%, TRAIL WATCH, AVG tiers 1-3)"
    requirement: "RULES-03"
    verification:
      - kind: unit
        ref: "tests/test_rules.py (10 boundary-pair tests: stop_hit, trim, book_50, trail_watch, avg_candidate x3 tiers)"
        status: pass
    human_judgment: false
  - id: D3
    description: "Ordered precedence chain resolves multi-qualifying stocks to the single expected flag"
    requirement: "RULES-02"
    verification:
      - kind: unit
        ref: "tests/test_rules.py#test_precedence_stop_hit_wins_over_trim, #test_precedence_trim_wins_over_book_50"
        status: pass
    human_judgment: false
  - id: D4
    description: "AVG weight<10% gate suppresses AVG CANDIDATE at every tier including the deepest"
    requirement: "RULES-05"
    verification:
      - kind: unit
        ref: "tests/test_rules.py#test_avg_weight_gate_suppresses_avg_at_every_tier_including_deepest"
        status: pass
    human_judgment: false
  - id: D5
    description: "UNTAGGED fallback for missing/bad config tag, never hard-fails"
    requirement: "RULES-04"
    verification:
      - kind: unit
        ref: "tests/test_rules.py#test_untagged_when_symbol_missing_from_config, #test_untagged_when_symbol_has_bad_tag"
        status: pass
    human_judgment: false
  - id: D6
    description: "Missing LTP (None) yields explicit NO PRICE result, never silent HOLD"
    verification:
      - kind: unit
        ref: "tests/test_rules.py#test_missing_ltp_yields_explicit_no_price_result"
        status: pass
    human_judgment: false

duration: 20min
completed: 2026-07-09
status: complete
---

# Phase 1 Plan 1: Pure Rules Engine Summary

**Pure `rules.py` decision core with a single ordered precedence resolver (UNTAGGED > STOP HIT > TRIM > BOOK 50% > TRAIL WATCH > AVG CANDIDATE > HOLD), named threshold constants, first-run peak seed, and a 22-test boundary/precedence suite — all green.**

## Performance

- **Duration:** ~20 min
- **Completed:** 2026-07-09T14:49:03Z
- **Tasks:** 2 (RED test suite, GREEN implementation)
- **Files modified:** 4 (requirements.txt, rules.py, tests/test_rules.py, .gitignore)

## Accomplishments
- `requirements.txt` pins the phase's full dependency set exactly (growwapi 1.5.0, pyotp 2.10.0, requests 2.32.3, PyYAML 6.0.3, pytest 8.4.2); installs cleanly.
- `tests/test_rules.py` — 22 AAA-structured tests: strict-`>` boundary pairs for STOP HIT/TRIM/BOOK 50%/TRAIL WATCH/AVG tiers 1-3, two multi-qualifying precedence assertions, UNTAGGED (missing + bad tag), AVG-reminder-coupling, first-run peak seed, missing-LTP handling, and an exactly-one-flag-per-holding check.
- `rules.py` (146 lines) — pure `evaluate(holdings, config, state, today) -> (flags, new_state)`, named constants at module top, one ordered resolver (`_resolve`), zero clock/env/network/file access.
- Full suite green: `python -m pytest tests/test_rules.py -q` → 22 passed.

## Task Commits

1. **Task 1: Pin dependencies and write the failing rules boundary test suite (RED)** - `dfd7171` (test)
2. **Task 2: Implement pure rules.py to green (GREEN + REFACTOR)** - `e246cc6` (feat)

**Plan metadata:** (this commit, follows)

## Files Created/Modified
- `requirements.txt` - Pinned 5-package dependency set for the whole phase
- `tests/test_rules.py` - 22-test AAA boundary/precedence/UNTAGGED/reminder suite, `holding()`/`padded()` fixture helpers
- `rules.py` - Pure decision core: constants, `_bucket`, `_resolve` (ordered chain), `_message`, `evaluate`
- `.gitignore` - Excludes `.venv/`, `__pycache__/`, `.pytest_cache/`, `.env` (not in original files_modified list; added because a Python venv/test run otherwise leaves untracked cruft — Rule 3, blocking hygiene, no functional impact)

## Decisions Made
- Implemented D-01/D-02/D-03/D-04/D-13/D-14 exactly as locked in 01-CONTEXT.md — named constants, weight denominator = total equity value, 3-tier AVG with all-tiers weight gate, ordered precedence chain, strict `>` everywhere.
- `ltp=None` is checked before the precedence chain (data-quality short-circuit to `NO PRICE`), not folded into the bucket-based resolver — keeps the resolver's business logic uncontaminated by data-availability concerns.
- Chose `pct_below_peak == drop-from-avg-cost` in Phase 1 (state={} always) rather than trying to fake a synthetic peak inside `evaluate()` itself — this is the documented, intentional Pitfall 1 consequence; `state` remains a genuine read-only lookup so Phase 2 can seed real peaks without touching `rules.py`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] AVG tier 2/3 boundary tests needed an isolating state peak**
- **Found during:** Task 2 (implementation + first green run)
- **Issue:** The initial tier-2/tier-3 test fixtures (per Task 1's literal spec: plain avg_cost-drop-only holdings with `state={}`) failed — not because `rules.py` was wrong, but because Phase 1's peak-seed formula (`peak = max(ltp, avg_cost)`, since `state` is always `{}`) makes `pct_below_peak` numerically identical to `drop` whenever price is down. TRAIL WATCH's `>20%` threshold and AVG tier 2's `>20%` threshold are the same locked number (D-01), so for a core stock down >20% with `state={}`, the higher-precedence TRAIL WATCH (D-13) always wins and AVG tier 2/3 is structurally unreachable via a plain down-from-avg-cost fixture — a sharper, edge-case instance of the already-documented Pitfall 1 (same-run peak seed inertness).
- **Fix:** The two tier-2/tier-3 tests now supply a non-empty `state` with a pre-existing peak equal to the fixture's own `ltp` (e.g. `state={"ITC": {"peak": 799.9}}`), which zeroes `pct_below_peak` without touching the independently-computed `drop` used for AVG tiering. This exercises `rules.py`'s actual tier-computation contract (forward-compatible with Phase 2, where real persisted peaks will diverge from avg_cost) without changing any implementation logic. A code comment documents why in both tests.
- **Files modified:** tests/test_rules.py
- **Verification:** `python -m pytest tests/test_rules.py -q` → 22 passed
- **Committed in:** e246cc6 (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 bug in test design, not implementation)
**Impact on plan:** No scope creep; `rules.py` implements the locked decisions exactly as specified. The fix only affected how two specific boundary conditions are exercised in tests, and is documented for Phase 2 (STATE-01..04) since it's the first concrete evidence of the Pitfall 1 interaction the research flagged.

## Issues Encountered
None beyond the deviation above.

## User Setup Required
None - no external service configuration required. `broker.py`/`notify.py` (Groww/Telegram secrets) are later plans in this phase.

## Next Phase Readiness
- `rules.py` is complete, pure, fully boundary-tested, and ready to be consumed by `sentinel.py` once `broker.py`/`notify.py` exist (plans 01-02/01-03 of this phase).
- `requirements.txt` is locked for the whole phase — later plans should not add packages beyond this pinned set without a plan-level justification.
- Flag-precedence and AVG-boundary-operator assumptions (RESEARCH.md A1/A2) are now locked in code via passing tests — no open questions remain for `rules.py`'s contract.

---
*Phase: 01-end-to-end-morning-digest*
*Completed: 2026-07-09*

## Self-Check: PASSED

- FOUND: requirements.txt
- FOUND: rules.py
- FOUND: tests/test_rules.py
- FOUND: dfd7171 (test commit)
- FOUND: e246cc6 (feat commit)
