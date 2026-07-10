# Groww Sentinel

**A daily, deterministic advisor over your Groww equity holdings — delivered to Telegram, run entirely on free GitHub Actions cron. No server, no trading, no black box.**

Every trading morning it fetches your holdings and previous-close prices, runs a pure rules engine over your positions, and sends a short Telegram digest flagging what needs attention today: stops, trims, profit-booking, averaging opportunities, and a portfolio P&L trend. Friday's digest adds a weekly recap. It **surfaces candidates and reminds you to run your own judgment gates — it never places a trade and never makes the final call.**

> [!WARNING]
> **Not investment advice.** The bundled rules encode one person's strategy as a worked example. Fork it, change the thresholds, or rip them out. Every action is reviewed and executed manually by you.

---

## Why it exists

The Groww free TradeAPI gives you holdings and cost basis but no live price feed (that's a paid tier). Sentinel runs pre-market, so it only needs the **previous close** — freely available from Yahoo Finance. That one insight makes a genuinely free, unattended portfolio monitor possible:

- **Zero infrastructure** — GitHub Actions cron is the whole runtime. No VPS, no always-on process, no bill.
- **Deterministic core** — the decision engine (`rules.py`) is a pure function: no network, no clock, no I/O. Fully unit-tested, trivially auditable, no surprises.
- **Private by construction** — secrets are GitHub encrypted secrets; run-to-run state lives in the Actions cache (never a commit), so your portfolio never touches git. The repo is safe to keep public.

## Example digest

```
📊 Groww Sentinel · 09 Jul
💰 ₹8.42L · 📈 P&L +12.3% · Day +0.8% · 5d ↗ +2.1%


🔴 ACTION

🛑 EXAMPLECO  -27%  ·  cut it — sell all 40 sh (~₹32,140)
✂️ HEAVYSTK  14% of book  ·  trim — sell 12 sh (~₹18,900)
📉 PEAKEDCO  -22% from peak  ·  tighten stop / consider exit

🟢 OPPORTUNITY

💰 WINNERCO  +58%  ·  book half — sell 25 sh (~₹41,000)
➕ DIPCO  -12%  ·  average — buy 15 sh (~₹9,750)
   ↳ 3-gate: results still good? fall market-wide (not company bad news)? would I buy fresh today?

😴 HOLDING (4)
STEADYA +3%, STEADYB -1%, STEADYC +7%, STEADYD +2%
```

## The decision ladder

Each holding maps to **exactly one** flag. Precedence is strict, first match wins (`STOP > TRIM > BOOK > TRAIL WATCH > AVERAGE > HOLD`), and every threshold is a strict `>` — a value sitting exactly on a threshold does not trip it. All thresholds live as named constants at the top of [`rules.py`](rules.py) — one place to tune.

| Flag | Fires when | Default | Action |
|------|-----------|---------|--------|
| 🛑 `STOP` | loss deeper than | −25% | cut the whole position |
| ✂️ `TRIM` | single-position weight above | 10% of book | trim back to the weight gate |
| 💰 `BOOK 50%` | gain above | +50% | book half |
| 💵 `BOOK 25%` | gain above | +25% | book a quarter |
| 📉 `TRAIL WATCH` | fallen from a real peak by more than | 20% | tighten stop / consider exit |
| ➕ `AVERAGE` | dip below cost more than | 10% | average down (with a 3-gate reminder) |
| 😴 `HOLD` | none of the above | — | steady, listed as proof it was checked |
| ⚠️ `CORP ACTION` | qty jumped with flat capital (bonus/split) | — | ignore distorted P&L this run |
| ❔ `NO PRICE` | price feed missing for the symbol | — | flagged, not silently dropped |

Two design notes worth knowing:

- **`TRIM` outranks `AVERAGE`** — an over-weight loser is trimmed, never averaged into. The "don't add to a heavy position" guard is free.
- **`TRAIL WATCH` only fires on a genuine drawdown** — the tracked peak must be strictly above average cost (the stock was in profit, then fell off that high). A plain loser never triggers it. Durable peaks persist across runs via state, so this signal sharpens over time.

An optional **news-sentiment layer** ([`sentiment.py`](sentiment.py), Google Gemini free tier) can only *block* a risky add — it turns an `AVERAGE` into 🚫 `AVOID` on bad news. It never invents a buy and never changes a sell. No API key → the layer is skipped, not failed.

## How it works

```
GitHub Actions cron (3×/weekday, IST)
        │
        ├─ broker.py    → Groww TradeAPI (TOTP auth) → holdings + cost basis
        ├─ prices.py    → Yahoo Finance → previous close
        ├─ rules.py     → PURE engine → one flag + trade size per holding
        ├─ sentiment.py → (optional) Gemini → block risky adds on bad news
        ├─ notify.py    → format digest → Telegram sendMessage
        └─ state.py     → peaks / snapshots / sentiment → Actions cache
```

| Module | Responsibility | Pure? |
|--------|---------------|:-----:|
| [`rules.py`](rules.py) | Decision engine — holdings → flags + trade sizes | ✅ |
| [`notify.py`](notify.py) | `format_digest` (pure) + thin Telegram `send` | partial |
| [`state.py`](state.py) | Durable peaks, daily snapshots, P&L trend math | partial |
| [`broker.py`](broker.py) | Groww SDK boundary — returns plain dicts only | ❌ |
| [`prices.py`](prices.py) | Previous-close fetch via yfinance | ❌ |
| [`sentiment.py`](sentiment.py) | Optional Gemini news-sentiment gate | ❌ |
| [`holidays.py`](holidays.py) | Static NSE trading-holiday calendar | ✅ |
| [`sentinel.py`](sentinel.py) | Orchestrator — wires the pipeline, one run to exit | ❌ |

The I/O boundaries are deliberately thin so the pure core stays testable without mocking a broker. 130 tests cover it.

## Quick start

1. **Use this repo as a template** (or fork it) into your own account/org.

2. **Add the secrets** under **Settings → Secrets and variables → Actions → New repository secret**:

   | Secret | Required | Where to get it |
   |--------|:--------:|-----------------|
   | `GROWW_API_KEY` | ✅ | Groww dashboard → TradeAPI → TOTP-flow credentials |
   | `GROWW_TOTP_SEED` | ✅ | Groww dashboard → TradeAPI → TOTP seed |
   | `TELEGRAM_TOKEN` | ✅ | Telegram [@BotFather](https://t.me/BotFather) → `/newbot` |
   | `TELEGRAM_CHAT_ID` | ✅ | Message your bot, then `getUpdates` → `chat.id` (or [@userinfobot](https://t.me/userinfobot)) |
   | `GEMINI_API_KEY` | optional | [aistudio.google.com](https://aistudio.google.com) — enables the sentiment layer |
   | `HEALTHCHECK_URL` | recommended | [healthchecks.io](https://healthchecks.io) ping URL — dead-man's-switch (below) |

   > The Groww **TOTP auth flow** is the only unattended-friendly option — the API-key+secret flow needs daily manual re-approval on Groww's dashboard, which defeats a cron.

3. **Enable Actions** on the repo (the schedule is defined in [`.github/workflows/sentinel.yml`](.github/workflows/sentinel.yml): pre-open / midday / close, weekdays IST).

4. **First run by hand** — **Actions → Groww Sentinel → Run workflow** (`workflow_dispatch`). Confirm a Telegram digest arrives (or a "market closed" / "no holdings" no-op, depending on the day) and — if configured — your healthcheck goes green. State seeds itself into the Actions cache on this first run; peaks and P&L trend fill in over the following days.

That's it. No commit ever carries your holdings — state persists in the Actions cache, which is private even on a public repo.

## Dead-man's-switch (recommended)

A cron that silently stops firing looks identical to "all quiet, no flags." [healthchecks.io](https://healthchecks.io) is a free external monitor that catches the gap: Sentinel pings `HEALTHCHECK_URL` on every clean exit (digest sent, market-closed no-op, no-holdings no-op) and on **none** of the failure paths — so a missed ping always means a real miss.

Set the check to **Cron schedule mode** (not Simple period/grace — a weekdays-only job leaves a ~65-hour Fri→Mon gap that Simple mode false-alarms on every weekend). Use the three run times (`30 3 * * 1-5`, `0 7 * * 1-5`, `0 10 * * 1-5`, UTC) with a grace window a little wider than the largest gap between runs (~3.5h) to absorb Actions' best-effort scheduling delay.

## Local development

```bash
git clone https://github.com/ThePubDoc/groww-sentinel.git
cd groww-sentinel
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

pytest                      # 130 tests, pure core needs no secrets
python -m sentinel --dry-run   # prints the digest instead of sending it (still needs live creds in env)
```

The rules engine and digest formatter are pure functions — the bulk of the suite runs with zero credentials and zero network.

## Configuration & maintenance

- **Tune the strategy** — every threshold and sizing fraction is a named constant at the top of [`rules.py`](rules.py). Change them, or replace `evaluate()` entirely with your own logic; the rest of the pipeline doesn't care what flags come out.
- **NSE holiday calendar** — [`holidays.py`](holidays.py) is a hand-maintained static set seeded through 2026–2027 (no heavyweight calendar dependency). A run past the last seeded year still executes but sends a loud warning rather than assuming the market is open. Add each new year when NSE publishes its circular.

## Tech stack

Python 3.11+ · [`growwapi`](https://pypi.org/project/growwapi/) · [`pyotp`](https://pypi.org/project/pyotp/) · [`yfinance`](https://pypi.org/project/yfinance/) · [`google-genai`](https://pypi.org/project/google-genai/) (optional) · [`requests`](https://pypi.org/project/requests/) · `pytest`. No web framework, no database, no bot framework — a one-shot script that fires and exits.

## Contributing

Issues and PRs welcome. Keep the pure core pure (no I/O in `rules.py`), keep modules focused, and add tests for behavior changes — `pytest` must stay green.

## License

[MIT](LICENSE) © Aayush Agrawal
