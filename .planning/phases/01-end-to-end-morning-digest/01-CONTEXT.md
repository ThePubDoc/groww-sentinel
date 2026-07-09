# Phase 1: End-to-End Morning Digest - Context

**Gathered:** 2026-07-09
**Status:** Ready for planning

<domain>
## Phase Boundary

A manually-invoked Python run that authenticates to Groww (API key + runtime TOTP),
fetches real holdings + batched live prices, evaluates the pure `rules.py` engine,
and sends a real per-stock flag digest to Telegram. Manual trigger only — cron,
state persistence, and P&L trend/weekly are later phases.

Delivers requirements: DATA-01..05, RULES-01..05, STATE-05, NOTIFY-01..03, TEST-01, TEST-02.

</domain>

<decisions>
## Implementation Decisions

### Threshold values (RULES-03)
- **D-01:** Lock the spec's threshold numbers as the v1 named constants (single place in `rules.py`), tunable later:
  - AVG CANDIDATE: down 10 / 20 / 30% from average cost
  - TRIM: weight > 10% of portfolio
  - BOOK 50%: up > 25% from average cost (tactical)
  - STOP HIT: down > 12% from average cost, OR > 15% below tracked peak (tactical)
  - TRAIL WATCH: > 20% below tracked peak (core)
- **D-02:** TRIM weight denominator = **total equity holdings value** (sum of qty×LTP across held symbols). No cash / other assets — Sentinel only sees holdings.

### AVG CANDIDATE tiering (RULES-02)
- **D-03:** 3-tier escalation, not single-fire. Fires at each of -10/-20/-30% from avg cost; the message shows which tranche (e.g. `AVG CANDIDATE tier 2 (-21%)`). Deeper fall = stronger add signal.
- **D-04:** The `weight < 10%` gate applies to **all** tiers — if a core holding is already ≥10% of portfolio, suppress AVG even at -30% (averaging would over-concentrate; consistent with TRIM).

### Digest format (NOTIFY-01..03)
- **D-05:** Each flagged line shows **symbol + flag + % + short action hint**, e.g. `RELIANCE: STOP HIT (-13% vs avg) → review exit`.
- **D-06:** Header line included in Phase 1: **total value + overall unrealized P&L%** (both computable now from holdings + LTP). Day P&L / N-day trend / weekly are Phase 2.
- **D-07:** Group flagged lines into **🔴 ACTION** (STOP HIT, TRIM, TRAIL WATCH) → **🟢 OPPORTUNITY** (AVG CANDIDATE, BOOK 50%) → **⚠️ UNTAGGED** at the bottom.
- **D-08:** Only non-HOLD stocks are listed; when nothing fires, send a single "all quiet" line (proof the run happened).

### Run interface & config (DATA-04, RULES-04)
- **D-09:** Default invocation sends to Telegram; a **`--dry-run`** flag prints the formatted digest to stdout instead (test rules/format without pinging the phone).
- **D-10:** `config.yaml` is a **flat `symbol → core|tactical` map**. Thresholds stay global constants in `rules.py` — no per-symbol threshold overrides in v1.
- **D-11:** A symbol tagged anything other than `core`/`tactical` (typo) or missing from config → **UNTAGGED** flag surfaced in the digest. Never guess a bucket; never hard-fail the whole run over one bad tag.
- **D-12:** Secrets validation (DATA-04) still hard-fails at startup naming the missing secret — that is a *missing-secret* abort, distinct from D-11's *bad-tag* tolerance. Groww access token never written to disk (DATA-05).

### Claude's Discretion
- Exact wording of the "all quiet" line and the AVG 3-gate reminder text.
- Telegram message formatting details (Markdown vs HTML parse mode, emoji specifics) — pick what renders cleanly.
- Module/function naming within the locked 4-file split (`broker.py`, `rules.py`, `notify.py`, `sentinel.py`).
- Value-header number formatting (₹ lakhs vs plain).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Design & requirements
- `docs/superpowers/specs/2026-07-09-groww-sentinel-design.md` — approved design spec: exact rules table, message shape, module split, error-handling policy
- `.planning/PROJECT.md` — project scope, constraints, key decisions
- `.planning/REQUIREMENTS.md` — v1 REQ-IDs (this phase covers the 16 listed under `<domain>`)

### Research (implementation-critical)
- `.planning/research/STACK.md` — growwapi 1.5.0 methods: `get_holdings_for_user()`, `get_ltp(segment, exchange_trading_symbols)` (≤50 symbols/call), TOTP auth via `GrowwAPI.get_access_token(totp=...)`, rate limits (10/s, 300/min), Telegram via raw `requests.post` sendMessage
- `.planning/research/ARCHITECTURE.md` — pure-core/imperative-shell split; `rules.py` takes `today` as a param (deterministic); first-run peak seed
- `.planning/research/PITFALLS.md` — corporate-action false-flag risk (Phase 2), token-never-cached, Telegram send failure handling, boundary-test discipline
- `.planning/research/FEATURES.md` — flag-set validation, non-HOLD + heartbeat as the trust mechanism, AVG-flag/reminder coupling

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- None — greenfield. No source code exists yet; only the design spec and planning docs.

### Established Patterns
- 4-module split is prescribed (spec + ARCHITECTURE.md): `broker.py` (I/O), `rules.py` (pure), `notify.py` (I/O), `sentinel.py` (orchestrator). Keep each <200 lines.
- `rules.py` MUST be pure: signature `evaluate(holdings, config, state, today) -> (flags, new_state)`, no I/O, `today` injected for determinism/testability.

### Integration Points
- `sentinel.py` wires broker → rules → notify and owns top-level error handling.
- `--dry-run` short-circuits the notify send (prints instead), so the same code path is exercised minus the HTTP call.

</code_context>

<specifics>
## Specific Ideas

- Message shape follows the spec's example digest (`📊 Groww Sentinel — 09 Jul` header, ACTION/OPPORTUNITY/UNTAGGED sections).
- AVG CANDIDATE lines must always carry the 3-gate manual-check reminder (results good? / fall market-wide not company-bad-news? / would I buy fresh today?) — flag and reminder are one coupled unit (RULES-05).

</specifics>

<deferred>
## Deferred Ideas

- Per-symbol threshold overrides in `config.yaml` — considered in D-10, deferred; global constants suffice for v1.
- Day P&L / N-day trend / weekly summary header content — Phase 2 (PNL-*).
- Peak reset-on-exit / re-seed-on-rebuy, dated snapshots — Phase 2 (STATE-01..04). Phase 1 only does first-run peak seed (STATE-05) in-memory; durable state is Phase 2.
- Corporate-action stale-avg_price warning — Phase 2 (RULES-06); verify growwapi adjustment behavior then.

</deferred>

---

*Phase: 1-End-to-End Morning Digest*
*Context gathered: 2026-07-09*
