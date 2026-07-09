---
phase: 01-end-to-end-morning-digest
plan: 02
subsystem: broker-io-boundary
tags: [python, growwapi, pyotp, mocked-io, pytest]

# Dependency graph
requires: []
provides:
  - "broker.py: get_client(api_key, totp_seed) -> GrowwAPI, get_holdings(client) -> list[dict], get_ltp(client, symbols) -> dict[str, float|None]"
  - "Verified live response shape for get_holdings_for_user() -- wraps list under a \"holdings\" key"
  - "tests/test_broker.py: 4-test mocked-boundary suite, zero live calls"
affects: [01-03]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "I/O boundary returns plain dicts only -- never SDK objects (mirrors rules.py's pure-core discipline)"
    - "Token generated fresh every call, never persisted (DATA-05)"
    - "Single batched get_ltp call per run, defensive missing-key -> None"

key-files:
  created: [broker.py, tests/test_broker.py]
  modified: []

key-decisions:
  - "Verified get_holdings_for_user() live response shape against groww.in/trade-api/docs/python-sdk/portfolio: payload wraps the list under a \"holdings\" key, not a bare list as RESEARCH.md's simplified Pattern 2 / test recipe assumed -- broker.py and tests/test_broker.py both implement the verified real shape (Rule 1 bug-prevention, caught before it could break against the live API)"
  - "get_ltp implemented exactly per RESEARCH.md Pattern 3 -- live docs confirm the flat {\"NSE_SYMBOL\": price} response shape with no wrapping key, no correction needed there"
  - "get_holdings/get_ltp take an already-authenticated client as a parameter and never construct GrowwAPI internally, so their tests use a plain MagicMock client with no need to patch broker.GrowwAPI -- only get_client's test patches the class, since that's the only function that touches it"

requirements-completed: [DATA-01, DATA-02, DATA-03, DATA-05, TEST-02]

coverage:
  - id: D1
    description: "get_client authenticates via a runtime-generated TOTP and returns a live client without writing the access token anywhere"
    requirement: "DATA-01, DATA-05"
    verification:
      - kind: unit
        ref: "tests/test_broker.py#test_get_client_authenticates_via_runtime_totp_without_persisting_token"
        status: pass
      - kind: static
        ref: "grep for open(/json.dump/.write( in broker.py -- zero matches"
        status: pass
    human_judgment: false
  - id: D2
    description: "get_holdings returns minimal plain dicts, dropping all other SDK fields"
    requirement: "DATA-02"
    verification:
      - kind: unit
        ref: "tests/test_broker.py#test_get_holdings_extracts_minimal_plain_dicts"
        status: pass
    human_judgment: false
  - id: D3
    description: "get_ltp issues exactly one batched call and maps missing keys to None"
    requirement: "DATA-03"
    verification:
      - kind: unit
        ref: "tests/test_broker.py#test_get_ltp_batches_all_symbols_in_one_call, #test_get_ltp_missing_symbol_maps_to_none"
        status: pass
    human_judgment: false
  - id: D4
    description: "All broker.py tests mock the growwapi boundary, zero live network calls"
    requirement: "TEST-02"
    verification:
      - kind: unit
        ref: "python -m pytest tests/test_broker.py -q -> 4 passed"
        status: pass
    human_judgment: false

duration: 25min
completed: 2026-07-09
status: complete
---

# Phase 1 Plan 2: Broker I/O Boundary Summary

**`broker.py` authenticates to Groww via a runtime pyotp TOTP + `GrowwAPI.get_access_token` (token never persisted), fetches holdings and one batched LTP call, and returns only plain dicts — covered by a 4-test mocked-boundary suite with zero live network calls.**

## Performance

- **Duration:** ~25 min
- **Completed:** 2026-07-09
- **Tasks:** 2 (implement broker.py, mocked tests)
- **Files modified:** 2 (broker.py, tests/test_broker.py)

## Accomplishments
- `broker.py` (59 lines) — `get_client`, `get_holdings`, `get_ltp`. Auth generates a fresh TOTP code via `pyotp.TOTP(seed).now()` and exchanges it via `GrowwAPI.get_access_token(api_key=, totp=)`; the returned token is a local variable only, passed straight into `GrowwAPI(token)`, never written to disk.
- `get_holdings` extracts `{trading_symbol, quantity, average_price}` per holding from the live API's actual `{"holdings": [...]}`-wrapped response, dropping `isin`, `pledge_quantity`, and seven other SDK-internal fields.
- `get_ltp` builds one NSE_-prefixed tuple and issues exactly one `client.get_ltp(segment=client.SEGMENT_CASH, exchange_trading_symbols=...)` call per run; any symbol absent from the response maps to `None` rather than raising.
- `tests/test_broker.py` — 4 AAA-structured tests, all mocked at the SDK boundary (`broker.GrowwAPI` patched for the auth path; plain `MagicMock` clients for `get_holdings`/`get_ltp` since those functions never construct `GrowwAPI` themselves). Zero live network calls.
- Full suite green: `python -m pytest tests/test_broker.py -q` → 4 passed; whole-repo suite (`python -m pytest -q`) → 26 passed (no regressions to `tests/test_rules.py`).

## Task Commits

1. **Task 1: Implement broker.py — TOTP auth, holdings, batched LTP (no token persistence)** - `597c515` (feat)
2. **Task 2: Mocked-I/O tests for broker.py — no live calls (TEST-02)** - `dffc33a` (test)

**Plan metadata:** (this commit, follows)

## Files Created/Modified
- `broker.py` — I/O boundary: `get_client`, `get_holdings`, `get_ltp`, all returning plain dicts, no persistence
- `tests/test_broker.py` — mocked-boundary suite, realistic fixtures, no live calls

## Decisions Made
- Live-verified `get_holdings_for_user()`'s actual response shape against `groww.in/trade-api/docs/python-sdk/portfolio` before implementing: it wraps the holdings list under a `"holdings"` key. RESEARCH.md's Pattern 2 and its pytest recipe both assumed a bare list — implemented and tested against the verified real shape instead (see Deviations below).
- Live-verified `get_ltp`'s response shape against `groww.in/trade-api/docs/python-sdk/live-data`: confirmed flat `{"NSE_SYMBOL": price}`, exactly as RESEARCH.md Pattern 3 stated — no correction needed there.
- `get_holdings`/`get_ltp` tests use a plain `MagicMock` client (no `@patch("broker.GrowwAPI")`) since those two functions receive an already-authenticated client as a parameter and never touch the `GrowwAPI` class directly — only `get_client`'s test needs the class patched.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Corrected `get_holdings_for_user()` response shape against the live API**
- **Found during:** Task 1 (implementation), before writing any code
- **Issue:** RESEARCH.md's Pattern 2 code example and its Code Examples pytest recipe both treat `client.get_holdings_for_user()`'s return value as a bare list of holding dicts (`mock_instance.get_holdings_for_user.return_value = FAKE_HOLDINGS`). Live-fetching `groww.in/trade-api/docs/python-sdk/portfolio` (curl, this session) shows the actual JSON response wraps the list under a top-level `"holdings"` key: `{"holdings": [{...}, ...]}`. Implementing against RESEARCH's simplified shape would have shipped code that raises or silently returns `[]` against the real live API (a `dict` has no per-holding fields to iterate directly).
- **Fix:** `broker.get_holdings()` reads `response.get("holdings", [])` before extracting the three minimal fields. `tests/test_broker.py`'s fixture (`FAKE_HOLDINGS_RESPONSE`) mirrors the verified wrapped shape, including the full set of extra SDK fields (`isin`, `pledge_quantity`, etc.) from the live docs' own example response, to prove extraction actually drops them (Pitfall 3 discipline).
- **Files modified:** broker.py, tests/test_broker.py
- **Verification:** `python -m pytest tests/test_broker.py -q` → 4 passed; live docs page fetched and grepped to confirm `"holdings": [` wrapping before writing the fix.
- **Committed in:** 597c515 (broker.py), dffc33a (tests)

---

**Total deviations:** 1 auto-fixed (1 bug — a real-API shape correction caught via live-doc verification before it could ship broken)
**Impact on plan:** No scope creep. The plan's `<behavior>` spec for `get_holdings` ("return ONLY {trading_symbol, quantity, average_price} per holding") is satisfied exactly; only the internal unwrapping step needed correcting against verified live behavior, and this is now the authoritative reference for future growwapi holdings-shape questions in this project.

## Issues Encountered
None beyond the deviation above.

## User Setup Required
None — no external service configuration required in this plan. Real credentials (`GROWW_API_KEY`, `GROWW_TOTP_SEED`) are still not exercised (all tests mocked); live end-to-end auth happens at the 01-03 human-verify checkpoint.

## Next Phase Readiness
- `broker.py` is complete, tested against a verified real response shape, and ready for `sentinel.py` (01-03) to wire: `get_client` → `get_holdings` → `get_ltp` → merge into `rules.py`'s expected `{symbol, qty, avg_cost, ltp}` shape (that merge step belongs to `sentinel.py`, not `broker.py`, per the architecture map).
- The verified `get_holdings_for_user()` `"holdings"`-wrapping fact should be treated as authoritative going forward (it corrects RESEARCH.md for any future reader).
- Real-API confirmation of these signatures (with actual secrets) happens at 01-03's end-to-end human-verify checkpoint, per this plan's `<verification>` section.

---
*Phase: 01-end-to-end-morning-digest*
*Completed: 2026-07-09*

## Self-Check: PASSED

- FOUND: broker.py
- FOUND: tests/test_broker.py
- FOUND: 597c515 (feat commit)
- FOUND: dffc33a (test commit)
