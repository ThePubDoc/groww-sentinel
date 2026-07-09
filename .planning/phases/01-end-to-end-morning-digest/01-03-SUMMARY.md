# Plan 01-03 Summary — notify.py + sentinel.py orchestrator

**Status:** Complete (walking-skeleton human-verify PASSED — real Telegram digest confirmed on device 2026-07-09)
**Requirements:** DATA-04, NOTIFY-01, NOTIFY-02, NOTIFY-03, RULES-04, RULES-05, DATA-05, TEST-02

## What was built

- **notify.py** — pure `format_digest(flags, portfolio)` + thin `send(token, chat_id, text)`. Plain-text Telegram (no `parse_mode`, sidesteps Markdown escaping), 4096 truncation, `raise_for_status`. Groups 🔴 ACTION / 🟢 OPPORTUNITY / ⚠️ UNTAGGED / NO PRICE; non-HOLD only; "all quiet" heartbeat.
- **sentinel.py** — orchestrator: startup secret validation (hard-fail exit 2 naming the missing secret, DATA-04), config load (`yaml.safe_load`), IST `today` injection, fetch → rules → notify wiring, `--dry-run` short-circuits the send, secret redaction in error paths, best-effort failure notify. Token never written to disk (DATA-05).
- **config.yaml** — flat `symbol → core|tactical` map (RULES-04, D-10).
- **.gitignore** — `.venv/`, `__pycache__/`, `*.pyc`, `.pytest_cache/`, `.env`.
- **tests/test_notify.py + tests/test_sentinel.py** — mocked `requests.post` / boundary; no live calls (TEST-02).

## Deviations (verified live during the human-verify checkpoint)

1. **Price source pivot (major).** Groww's price endpoints (`get_ltp`/`get_ohlc`/`get_quote`/historical) are ALL a paid Live Data tier — verified 403 on each with a valid, authenticated client. The free API returns cost basis but no price. Since Sentinel runs pre-market it only needs previous close, so added **prices.py** (yfinance, `<symbol>.NS`, one batched call; unpriced → None → NO PRICE flag) and rewired sentinel to it; removed the dead paid `broker.get_ltp`. Groww account stays on the official API (auth + holdings). Amends the "official-only" constraint (read-only public quotes) — documented in PROJECT.md Key Decisions + REQUIREMENTS DATA-03. Committed `0e03650`.
2. **Holdings response shape** (from 01-02, reconfirmed): `get_holdings_for_user()` wraps the list under a `"holdings"` key.
3. **Telegram chat_id setup gotcha** (config, not code): initial `TELEGRAM_CHAT_ID` pointed at the bot itself → `Forbidden: the bot can't send messages to the bot`. Correct value is the user's private chat id (from `getUpdates`). Resolved in local `.env`; documented in `.env.example`.

## Verification evidence

- Full suite: **46 passed**, zero live HTTP/API calls.
- Live dry-run: real Groww auth → 34 holdings → yfinance prev close (33/34 priced; CAPINVIT → NO PRICE) → rules → formatted digest to stdout. Exit 0.
- Live send: `python -m sentinel` exit 0; digest received on device, correct grouping/format, plain text, AVG line carried the 3-gate reminder.
- Secret validation: run with no secrets → exit 2 naming all four (DATA-04).
- Token persistence: grep-clean in broker.py / sentinel.py (DATA-05).

## Known / expected (not bugs)

- Below-peak flags (TRAIL WATCH, STOP-below-peak) rarely fire in Phase 1 — no durable state.json yet, peak re-seeds each run (Phase 2 fixes this).
- Symbol→Yahoo mapping is naive `<symbol>.NS`; InvITs/REITs like CAPINVIT may lack a `.NS` ticker → NO PRICE. Acceptable; revisit if coverage matters.
- Most holdings show UNTAGGED until the user populates config.yaml — working as designed.
