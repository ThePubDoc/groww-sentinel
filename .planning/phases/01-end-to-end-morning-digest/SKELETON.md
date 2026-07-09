# Walking Skeleton — Groww Sentinel

**Phase:** 1
**Generated:** 2026-07-09

## Capability Proven End-to-End

Running `python -m sentinel --dry-run` (and, once confirmed, `python -m sentinel`)
authenticates to Groww with a runtime TOTP, fetches the real holdings + one batched
LTP call, runs them through the pure `rules.py` engine, formats a grouped per-stock
flag digest, and — with `--dry-run` removed — delivers that digest as a real Telegram
message. This is the whole product loop end-to-end: **auth → fetch → rules → notify.**

## Architectural Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Language / runtime | Python 3.11+ (SDK supports 3.9–3.13) | Only language with an official `growwapi` SDK; matches GitHub Actions `setup-python`. |
| Broker access | `growwapi==1.5.0` via TOTP flow (`pyotp==2.10.0`) | Sole sanctioned access path; TOTP token has no expiry so it is the only headless-viable auth. |
| Notification | Raw `requests.post` to Telegram `sendMessage`, plain text (no `parse_mode`) | One fire-and-forget message/run; plain text removes the entire Markdown/HTML escaping failure class. |
| Config | `config.yaml`, flat `symbol → core\|tactical` map, parsed with `yaml.safe_load` (`PyYAML==6.0.3`) | Thresholds stay global constants in `rules.py`; no per-symbol overrides in v1 (D-10). |
| Core logic | Pure-core / imperative-shell: `rules.evaluate(holdings, config, state, today)` has zero I/O | Money path must be deterministic and unit-testable with hand-built fixtures, no mocks. |
| State | Phase 1 state is always `{}` (no durable `state.json` yet) | Durable peaks/snapshots are Phase 2 (STATE-01..04); Phase 1 does first-run peak seed in-memory only (STATE-05). |
| Directory layout | Flat repo root — `sentinel.py`, `broker.py`, `rules.py`, `notify.py`, `config.yaml`, `tests/` | ~4 files of substance; a `src/` package adds import ceremony for zero benefit at this size. |
| Testing | `pytest==8.4.2`; pure unit tests for `rules.py`, mocked-I/O for `broker.py`/`notify.py` | No live API calls in tests (TEST-01, TEST-02). |
| Secrets | 4 env vars: `GROWW_API_KEY`, `GROWW_TOTP_SEED`, `TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID` | Validated present at startup, fail loud naming the missing one (DATA-04); Groww token never written to disk (DATA-05). |
| Run interface | `python -m sentinel` sends; `python -m sentinel --dry-run` prints to stdout and skips the send | Test rules/format without pinging the phone (D-09). |

## Stack Touched in Phase 1

- [x] Project scaffold — `requirements.txt` (pinned), flat module layout, `pytest`
- [x] External read boundary — real Groww auth + `get_holdings_for_user` + one batched `get_ltp`
- [x] Pure decision core — `rules.evaluate` returns exactly one flag per stock
- [x] External write boundary — real Telegram `sendMessage`
- [x] Full-stack local run — `python -m sentinel --dry-run` exercises auth→fetch→rules→format; removing the flag sends for real

## Out of Scope (Deferred to Later Slices)

Explicit — this list prevents future phases from re-litigating Phase 1's minimalism:

- Durable `state.json` (peaks/snapshots persisted across runs), reset-on-exit / re-seed-on-rebuy — Phase 2 (STATE-01..04).
- Day P&L delta, N-day trend, Friday weekly summary — Phase 2 (PNL-01..05).
- Corporate-action `average_price` warning — Phase 2 (RULES-06).
- GitHub Actions cron, NSE holiday skip, state commit-back, concurrency guard, `workflow_dispatch` — Phase 3 (RUN-01..05).
- Auth/fetch-failure Telegram alert as a CI requirement + dead-man's-switch — Phase 3 (NOTIFY-04/05). (Phase 1 already exits non-zero and best-effort notifies on fetch failure, but the unattended-runtime guarantees are Phase 3.)
- Per-symbol threshold overrides in `config.yaml` (D-10 deferred).

## Subsequent Slice Plan

Each later phase adds one vertical slice on top of this skeleton without changing its architectural decisions:

- **Phase 2:** Durable state & portfolio telemetry — `state.py` (rebuild-not-merge, dated bounded snapshots) + P&L/trend/weekly reporting.
- **Phase 3:** Autonomous & failure-safe runtime — `.github/workflows/sentinel.yml` cron + holiday skip + state commit-back + failure notify + dead-man's-switch.
