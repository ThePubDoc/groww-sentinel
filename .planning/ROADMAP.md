# Roadmap: Groww Sentinel

## Overview

Groww Sentinel grows from a manually-triggered walking skeleton into a self-running,
failure-safe morning advisor. Phase 1 ships the whole value loop end-to-end — auth,
fetch holdings + live prices, evaluate the pure rules engine, and send a real Telegram
flag digest — so the tool is usable from day one. Phase 2 gives that digest a memory:
durable price peaks, a correct peak lifecycle, and portfolio telemetry (P&L, trend, Friday
weekly summary). Phase 3 takes the human out of the loop — GitHub Actions cron, holiday
skipping, automatic state persistence — and hardens it so a failure or missed run is loud,
never mistaken for "all quiet".

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [ ] **Phase 1: End-to-End Morning Digest** - Manually-triggered run fetches real holdings + prices, applies the rules engine, and sends a real Telegram flag digest
- [ ] **Phase 2: Durable State & Portfolio Telemetry** - Peaks and portfolio value persist across runs; digest carries P&L, N-day trend, and Friday weekly summary
- [ ] **Phase 3: Autonomous & Failure-Safe Runtime** - Runs itself every weekday on GitHub Actions, skips holidays, persists state, and makes failures/missed runs detectable

## Phase Details

### Phase 1: End-to-End Morning Digest
**Goal**: A manually-triggered run authenticates to Groww, fetches real holdings + live prices, evaluates the pure rules engine, and sends a real per-stock flag digest to Telegram.
**Mode:** mvp
**Depends on**: Nothing (first phase)
**Requirements**: DATA-01, DATA-02, DATA-03, DATA-04, DATA-05, RULES-01, RULES-02, RULES-03, RULES-04, RULES-05, STATE-05, NOTIFY-01, NOTIFY-02, NOTIFY-03, TEST-01, TEST-02
**Success Criteria** (what must be TRUE):
  1. Running the tool sends a real Telegram message listing current non-HOLD holdings with their flag (AVG CANDIDATE / TRIM / BOOK 50% / STOP HIT / TRAIL WATCH / UNTAGGED), grouped action vs opportunity — or a single "all quiet" line when nothing fires.
  2. Every held stock resolves to exactly one flag; a symbol missing from `config.yaml` shows UNTAGGED, never a guessed bucket.
  3. Every AVG CANDIDATE line carries the 3-gate manual-check reminder.
  4. A run started with any of the 4 secrets missing stops immediately and names the missing one, and the Groww access token is never written to disk.
  5. `rules.py` is a pure no-I/O function with passing unit tests covering every flag path and each threshold boundary; `broker.py` and `notify.py` have mocked-I/O tests that make no live calls.
**Plans**: 3 plans

Plans:
- [ ] 01-01-PLAN.md — Pure `rules.py` + full boundary tests: ordered-resolver `evaluate(holdings, config, state, today)`, 7 flags, named threshold constants (D-01), AVG 3-tier + weight gate, UNTAGGED, first-run peak seed (STATE-05, TEST-01, RULES-01..05) + pinned `requirements.txt`
- [ ] 01-02-PLAN.md — `broker.py`: headless TOTP auth (pyotp, no token persistence), `get_holdings`, single batched `get_ltp`; mocked-boundary tests, no live calls (DATA-01/02/03/05, TEST-02)
- [ ] 01-03-PLAN.md — `notify.py` (grouped non-HOLD digest + all-quiet + AVG reminder, plain-text send) + `sentinel.py` orchestrator (secret validation, `--dry-run`, IST today, state={}) + `config.yaml`/`.gitignore`; walking-skeleton end-to-end human-verify (DATA-04, NOTIFY-01/02/03, TEST-02)

### Phase 2: Durable State & Portfolio Telemetry
**Goal**: The digest remembers price peaks and portfolio value across runs and reports overall P&L, day change, an N-day trend, and a Friday weekly summary — with corporate-action-distorted cost flagged rather than mis-flagged.
**Mode:** mvp
**Depends on**: Phase 1
**Requirements**: STATE-01, STATE-02, STATE-03, STATE-04, PNL-01, PNL-02, PNL-03, PNL-04, PNL-05, RULES-06
**Success Criteria** (what must be TRUE):
  1. Across consecutive runs each symbol's peak persists and drives TRAIL WATCH / STOP HIT; selling a stock resets its peak and rebuying re-seeds it, so a permanently-down stock stops generating stale-peak noise.
  2. The digest reports overall unrealized P&L vs cost, the day's change vs the prior run's stored portfolio value, and an N-day portfolio direction; an intraday % appears when the price source exposes previous close.
  3. Friday's digest appends a weekly summary block (best/worst movers, week value change, flags-fired count).
  4. Re-running on the same day overwrites that day's snapshot without corrupting history (idempotent), state is rebuilt from current holdings each run, and stored snapshots stay bounded to recent entries.
  5. When a holding's average cost looks corporate-action-distorted, the digest emits a warning instead of a false STOP HIT / BOOK 50% flag.
**Plans**: 2 plans

Plans:
- [ ] 02-01: `state.py` — rebuild-not-merge state (STATE-02), per-holding-period peak with reset-on-exit / re-seed-on-rebuy (STATE-01, STATE-03), date-keyed bounded snapshots with idempotent same-day overwrite (STATE-04), corporate-action `average_price` verification + warning path (RULES-06)
- [ ] 02-02: P&L reporting — overall unrealized (PNL-01), day delta vs prior snapshot (PNL-02), N-day trend (PNL-03), intraday % when prev close exposed (PNL-04), Friday weekly summary block (PNL-05)

### Phase 3: Autonomous & Failure-Safe Runtime
**Goal**: The digest runs itself every weekday morning on GitHub Actions, skips NSE holidays, persists state automatically, and makes any failure or missed run loud and detectable rather than a false "all quiet".
**Mode:** mvp
**Depends on**: Phase 2
**Requirements**: RUN-01, RUN-02, RUN-03, RUN-04, RUN-05, NOTIFY-04, NOTIFY-05
**Success Criteria** (what must be TRUE):
  1. Without any manual action a digest arrives every weekday around 08:30 IST, and no run fires on NSE trading holidays.
  2. Updated `state.json` is committed back to the repo after each run, and overlapping/duplicate runs are prevented.
  3. The workflow can be triggered on demand via `workflow_dispatch` for first-run verification and ad-hoc runs.
  4. On an auth or fetch failure a Telegram warning naming the reason is sent and the run exits non-zero — a day is never silently skipped.
  5. An independent dead-man's-switch makes a missed cron or crash detectable, so message absence is never mistaken for "all quiet".
**Plans**: 2 plans

Plans:
- [ ] 03-01: `.github/workflows/sentinel.yml` — cron ~08:30 IST weekdays on a non-top-of-hour minute (RUN-01), static NSE holiday skip (RUN-02), `contents: write` state-commit step after the Python process exits with org-policy check + PAT fallback (RUN-03), `concurrency` guard (RUN-04), `workflow_dispatch` trigger (RUN-05)
- [ ] 03-02: Failure safety — auth/fetch-failure Telegram notify + non-zero exit (NOTIFY-04), independent dead-man's-switch that does not depend on the sentinel job (NOTIFY-05)

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. End-to-End Morning Digest | 0/3 | Not started | - |
| 2. Durable State & Portfolio Telemetry | 0/2 | Not started | - |
| 3. Autonomous & Failure-Safe Runtime | 0/2 | Not started | - |
