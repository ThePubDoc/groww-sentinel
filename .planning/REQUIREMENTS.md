# Requirements: Groww Sentinel

**Defined:** 2026-07-09
**Core Value:** Every trading morning I get a short, trustworthy Telegram digest flagging which holdings need attention — so I never miss a stop, trim, or averaging opportunity.

## v1 Requirements

Requirements for initial release. Each maps to roadmap phases.

### Data Access

- [x] **DATA-01**: Authenticate to Groww TradeAPI headlessly using API key + TOTP generated at runtime from a stored seed (pyotp)
- [x] **DATA-02**: Fetch holdings (trading symbol, quantity, average cost) via `growwapi`
- [x] **DATA-03**: Fetch previous-close price for all held symbols from a free public quote source (yfinance/Yahoo `<symbol>.NS`, one batched call). *Amended Phase 1: Groww's live-data endpoints (`get_ltp`/`get_ohlc`/`get_quote`/historical) are all a paid tier — verified 403 on each; a pre-market digest only needs previous close. Unpriced symbols → NO PRICE flag, never fatal.*
- [ ] **DATA-04**: Validate all 4 required secrets are present at startup; fail loud naming the missing one
- [x] **DATA-05**: Never persist the Groww access token to state.json — regenerate it each run (token expires daily)

### Rules Engine

- [x] **RULES-01**: `rules.py` exposes a pure function `(holdings, config, state, today) -> (flags, new_state)` with no I/O
- [x] **RULES-02**: Every held stock resolves to exactly one action flag from a uniform P&L ladder (no tagging) — BOOK 50%, BOOK 25%, AVERAGE, STOP, TRIM, TRAIL WATCH, HOLD (or NO PRICE). Ladder vs avg cost: gain >50% BOOK 50% · >25% BOOK 25% · −10 to −25% AVERAGE · worse than −25% STOP · else HOLD; plus TRIM >10% weight, TRAIL WATCH >20% below a real peak.
- [x] **RULES-03**: All rule thresholds are defined as named constants in one place for tuning
- [x] **RULES-04**: ~~`config.yaml` core/tactical tagging + UNTAGGED~~ — **SUPERSEDED (Phase 1)**: replaced by the uniform P&L ladder in RULES-02. No config file, no tagging, no UNTAGGED — every holding gets a verdict from its P&L.
- [x] **RULES-05**: AVG CANDIDATE always carries the 3-gate manual-check reminder (flag and reminder are one coupled unit)
- [x] **RULES-06**: Verify whether `growwapi` `average_price` is corporate-action adjusted; if not, emit a warning rather than a false STOP/BOOK flag on distorted avg cost

### State Model

- [x] **STATE-01**: Track per-symbol peak price keyed to the current holding period
- [x] **STATE-02**: Rebuild `new_state` from current holdings each run, using prior state as a read-only lookup
- [x] **STATE-03**: Prune state for symbols no longer held; reset a symbol's peak on exit and re-seed on rebuy
- [x] **STATE-04**: Store daily portfolio + per-symbol snapshots keyed by date; a same-day rerun overwrites (idempotent); history bounded to recent entries
- [x] **STATE-05**: On first run (no state.json), seed peaks and snapshots from current LTP

### P&L Reporting

- [x] **PNL-01**: Report overall unrealized portfolio P&L vs cost
- [x] **PNL-02**: Report day P&L as snapshot delta vs the prior run's stored portfolio value
- [x] **PNL-03**: Report an N-day portfolio direction/trend from stored snapshots
- [x] **PNL-04**: Include an intraday day-change % when the LTP source exposes previous close
- [x] **PNL-05**: Friday's digest appends a weekly summary block (best/worst movers, week value change, flags-fired count)

### Notification

- [ ] **NOTIFY-01**: Format and send the daily digest to Telegram via the Bot API
- [ ] **NOTIFY-02**: List only non-HOLD stocks, grouped into action vs opportunity
- [ ] **NOTIFY-03**: Send a one-line "all quiet" heartbeat when nothing is flagged (proof the job ran)
- [x] **NOTIFY-04**: On auth/fetch failure, send a Telegram warning with the reason and exit non-zero — never silently skip a day
- [x] **NOTIFY-05**: Independent dead-man's-switch so that message absence (cron miss / crash) is detectable, not mistaken for "all quiet"

### Runtime & CI

- [x] **RUN-01**: Run on GitHub Actions cron targeting ~08:30 IST on weekdays, using a non-top-of-hour minute
- [x] **RUN-02**: Skip NSE trading holidays (static holidays list for v1)
- [x] **RUN-03**: Commit the updated state.json back to the repo after the run (`contents: write`), as a workflow step after the Python process exits
- [x] **RUN-04**: `concurrency` guard preventing overlapping or duplicate runs
- [x] **RUN-05**: `workflow_dispatch` manual trigger for on-demand runs and first-run verification

### Testing

- [x] **TEST-01**: Unit tests for `rules.py` covering every flag path and the boundary value of each threshold (AAA structure)
- [x] **TEST-02**: Mocked-I/O tests for `broker.py` and `notify.py` — no live API calls in tests

## v2 Requirements

Deferred to future release. Tracked but not in current roadmap.

### Reporting

- **PNL-06**: Dampen a flag that stays open for many consecutive days (reduce repeat-alert fatigue)

### Runtime

- **RUN-06**: Upgrade holiday source to `pandas_market_calendars` (XNSE) after validating its output against NSE's published list

### Notification

- **NOTIFY-06**: Add WhatsApp as a second channel (notify layer kept swappable)

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| Order placement / trading | Advisory only; all actions reviewed and executed manually — safety + intent |
| Web dashboard / database / charts | Telegram message is the whole UI — YAGNI |
| Auto-fundamentals (earnings, debt, sector) | The 3-gate check stays manual — can't be automated safely |
| Trade history / tax / charges | Owned by the separate `groww-dashboard` project — Sentinel is forward-looking only |
| Scraping / unofficial APIs | Official Groww TradeAPI only — sanctioned + stable |
| Real-time / intraday streaming | Once-daily pre-market digest is the product — no always-on process |

## Traceability

Which phases cover which requirements. Populated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| DATA-01 | Phase 1 | Complete |
| DATA-02 | Phase 1 | Complete |
| DATA-03 | Phase 1 | Complete |
| DATA-04 | Phase 1 | Pending |
| DATA-05 | Phase 1 | Complete |
| RULES-01 | Phase 1 | Complete |
| RULES-02 | Phase 1 | Complete |
| RULES-03 | Phase 1 | Complete |
| RULES-04 | Phase 1 | Complete |
| RULES-05 | Phase 1 | Complete |
| STATE-05 | Phase 1 | Complete |
| NOTIFY-01 | Phase 1 | Pending |
| NOTIFY-02 | Phase 1 | Pending |
| NOTIFY-03 | Phase 1 | Pending |
| TEST-01 | Phase 1 | Complete |
| TEST-02 | Phase 1 | Complete |
| STATE-01 | Phase 2 | Complete |
| STATE-02 | Phase 2 | Complete |
| STATE-03 | Phase 2 | Complete |
| STATE-04 | Phase 2 | Complete |
| PNL-01 | Phase 2 | Complete |
| PNL-02 | Phase 2 | Complete |
| PNL-03 | Phase 2 | Complete |
| PNL-04 | Phase 2 | Complete |
| PNL-05 | Phase 2 | Complete |
| RULES-06 | Phase 2 | Complete |
| RUN-01 | Phase 3 | Complete |
| RUN-02 | Phase 3 | Complete |
| RUN-03 | Phase 3 | Complete |
| RUN-04 | Phase 3 | Complete |
| RUN-05 | Phase 3 | Complete |
| NOTIFY-04 | Phase 3 | Complete |
| NOTIFY-05 | Phase 3 | Complete |

**Coverage:**

- v1 requirements: 33 total (the doc previously noted "27"; the enumerated list is 33 — all mapped, none dropped)
- Mapped to phases: 33
- Unmapped: 0 ✓

---
*Requirements defined: 2026-07-09*
*Last updated: 2026-07-09 after roadmap creation (traceability populated)*
