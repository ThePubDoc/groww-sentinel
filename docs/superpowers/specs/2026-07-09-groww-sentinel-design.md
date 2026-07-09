# Groww Sentinel — Design Spec

**Date:** 2026-07-09
**Status:** Approved design, pre-implementation

## Purpose

A daily automated advisor over my Groww equity holdings. Each morning it fetches
holdings, applies my profit-booking + averaging strategy as deterministic rules,
and pings me on Telegram with per-stock flags (average / trim / book / stop / hold).

It does **not** trade, and it does **not** give the final decision — it surfaces
candidates and reminds me to run manual judgment gates.

> **Not investment advice.** Rules encode a personal strategy. All actions are
> reviewed and executed manually.

## Non-goals (deliberately skipped — YAGNI)

- No web dashboard, no database, no charts. Telegram message is the whole UI.
- No auto-fundamentals (earnings, debt, sector). The 3-gate check stays manual.
- No trade history / tax / charges reconstruction — that is what the separate
  `groww-dashboard` project is for. Sentinel is forward-looking alerts only.
- No order placement.

## Data access

Official **Groww TradeAPI** via the `growwapi` Python SDK. Sanctioned, stable,
free. No scraping, no credential handling beyond the official key + TOTP.

- **Holdings:** `groww.get_holdings_for_user()` →
  `{trading_symbol, quantity, average_price, ...}`. Gives qty + avg cost.
- **Live price (LTP):** holdings response has **no** LTP. Fetch per symbol from
  the live-data endpoint each run.
- **Auth:** API key + TOTP. Store the TOTP *seed*; generate the code at runtime
  with `pyotp` so it works headless.

## Architecture

Single small Python job. Three files of substance:

| File | Owner | Purpose |
|------|-------|---------|
| `config.yaml` | user | Tags each holding `core` or `tactical`. Untagged → flagged. |
| `state.json` | app | Tracked peak price per symbol (for trailing stops). Committed back each run. |
| `sentinel.py` | app | Orchestrates: fetch → rules → notify → persist. ~150 lines. |

Suggested module split (keep files focused, <200 lines):

- `broker.py` — Groww auth + fetch holdings + fetch LTPs. Returns plain dicts.
- `rules.py` — pure function: `(holdings, config, state) -> (flags, new_state)`.
  No I/O. Fully unit-testable.
- `notify.py` — format + send Telegram message.
- `sentinel.py` — wires the above, handles top-level errors.

### Data flow

```
cron (GitHub Actions, ~08:30 IST daily)
  -> pyotp: TOTP from seed
  -> broker: Groww login -> holdings {symbol, qty, avg_cost}
  -> broker: LTP per symbol
  -> load config.yaml (core/tactical tags) + state.json (peaks)
  -> rules.evaluate(...) -> per-stock flags + updated peaks
  -> notify: build + send Telegram digest
  -> commit updated state.json back to repo
```

## Rules engine

Per stock compute: `pnl_pct` vs avg cost, `pct_below_peak`, `weight_pct` of
portfolio. Peak = `max(stored_peak, today_ltp)`; seeded to first-seen LTP.

| Flag | Bucket | Condition |
|------|--------|-----------|
| 🟢 AVG CANDIDATE | core | down 10 / 20 / 30% from avg cost, weight < 10% |
| ⚪ TRAIL WATCH | core | > 20% below tracked peak |
| 🟡 TRIM | any | weight > 10% of portfolio |
| 🟢 BOOK 50% | tactical | up > 25% from avg cost |
| 🔴 STOP HIT | tactical | down > 12% from avg cost, OR > 15% below peak |
| — HOLD | any | nothing triggered |
| ⚠️ UNTAGGED | any | symbol missing from config.yaml |

Thresholds live as named constants at top of `rules.py` — one place to tune.

### Manual gate (not automated)

`AVG CANDIDATE` is a *candidate only*. The Telegram message reminds me to run the
3-gate check before adding: (1) results still good? (2) fall is market/sector-wide,
not company-specific bad news? (3) would I buy fresh today? Any "no" → skip.

## Telegram message shape

```
📊 Groww Sentinel — 09 Jul
Value ₹X.XX L | Day P&L +1.2%

🔴 ACTION
 • RELIANCE: STOP HIT (-13% vs avg) → review exit
 • TCS: TRIM, weight 11% → sell toward 7%

🟢 OPPORTUNITY
 • INFY: AVG CANDIDATE (-10%) → run 3-gate check first

⚠️ UNTAGGED: ZOMATO → set core/tactical in config.yaml
```

Only non-HOLD stocks are listed, to keep it short. If everything is HOLD, send a
one-line "all quiet" so I know the job ran.

## Runtime & secrets

- **GitHub Actions cron**, ~08:30 IST (`0 3 * * 1-5` UTC, weekdays).
- Secrets as GitHub encrypted secrets: `GROWW_API_KEY`, `GROWW_TOTP_SEED`,
  `TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID`. Never committed.
- **Scope caveat:** the `ThePubDoc` gh token lacks `workflow` scope, so pushing
  `.github/workflows/*.yml` may fail from that account. Resolve at implementation
  time (add scope, or push the workflow file via the `aayush-sib` account).

## Error handling

- Groww auth/fetch failure → send Telegram "⚠️ fetch failed: <reason>", exit
  non-zero. Never silently skip a day.
- Symbol missing from `config.yaml` → emit `UNTAGGED` flag, do not guess a bucket.
- Missing LTP for a symbol → skip that symbol's peak/flag calc, note it in message.
- Market holiday / empty holdings → send "market closed / no holdings", exit clean.
- `state.json` absent (first run) → seed peaks from current LTPs.

## Testing

- `rules.py` is pure → unit tests with hand-built holdings/config/state fixtures,
  one assertion per flag path (AAA structure). This is the money path — must have
  a runnable check.
- `broker.py` / `notify.py` → thin I/O; mock the SDK + Telegram HTTP in a light
  integration test. No live API calls in tests.

## Open items for implementation

- Confirm exact `growwapi` live-data method name + rate limits.
- Confirm `average_price` is post-corporate-action adjusted (bonus/split); if not,
  note the limitation.
