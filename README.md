# Groww Sentinel

A daily automated advisor over my personal Groww equity holdings. Each weekday
morning it fetches holdings + live prices, applies my profit-booking + averaging
strategy as deterministic rules, and pings me on Telegram with per-stock flags
(average / trim / book / stop / hold) plus a portfolio P&L trend. Friday's digest
also carries a weekly summary. It surfaces candidates and reminds me to run manual
judgment gates — it does **not** trade and does **not** make the final decision.

> **Not investment advice.** Rules encode a personal strategy. All actions are
> reviewed and executed manually.

Runs unattended on GitHub Actions — `.github/workflows/sentinel.yml` fires
three times per weekday (pre-open / midday / close, IST) plus on-demand via
`workflow_dispatch`. This file is the one-time deploy runbook.

## Secrets

All secrets are GitHub encrypted repo secrets (**Settings → Secrets and
variables → Actions → New repository secret**), injected into the run via
`env:` and never committed or echoed to logs.

| Secret | Required? | Source |
|--------|-----------|--------|
| `GROWW_API_KEY` | Required | Groww dashboard → TradeAPI → TOTP-flow credentials |
| `GROWW_TOTP_SEED` | Required | Groww dashboard → TradeAPI → TOTP seed |
| `TELEGRAM_TOKEN` | Required | Telegram `@BotFather` → `/newbot` |
| `TELEGRAM_CHAT_ID` | Required | Message the bot, then `getUpdates` → `chat.id` (or `@userinfobot`) |
| `GEMINI_API_KEY` | Optional | aistudio.google.com — enables the news-sentiment layer; sentiment is skipped (not failed) if unset |
| `HEALTHCHECK_URL` | Optional but recommended | healthchecks.io → your check → ping URL — powers the dead-man's-switch below |
| `STATE_PAT` | Optional, fallback only | See "Org-token fallback" below — only needed if the default token can't commit `state.json` |

## Dead-man's-switch (healthchecks.io)

A cron that silently stops firing looks identical to "all quiet, no flags" —
healthchecks.io is an external monitor that catches that gap.

1. Create a free check at [healthchecks.io](https://healthchecks.io).
2. Switch the check's schedule to **Cron schedule mode** — **not** the default
   Simple period/grace mode. A weekdays-only job creates a ~65-hour Friday
   → Monday gap that a Simple period/grace check will flag as "down" every
   single weekend.
3. Enter a cron schedule matching the three weekday run times (`30 3 * * 1-5`,
   `0 7 * * 1-5`, `0 10 * * 1-5`, timezone UTC), with a grace window a little
   wider than the largest gap between two consecutive runs (~3.5h between the
   midday and close runs) so GitHub Actions' best-effort scheduling delay
   doesn't false-alarm.
4. Copy the check's ping URL into the `HEALTHCHECK_URL` repo secret.

Sentinel pings this URL on every clean exit path (digest sent, market-closed
no-op, no-holdings no-op) and on none of the failure paths — so a missed ping
always means a real miss, never a quiet holiday.

## First run / verification

Before trusting the cron unattended, trigger the workflow once by hand:

1. **Actions** tab → **Groww Sentinel** → **Run workflow** (`workflow_dispatch`).
2. Confirm all three of the following:
   - A Telegram digest arrives (or a "market closed" / "no holdings" no-op,
     depending on the day).
   - A new commit to `state.json` appears in the repo, authored by the
     workflow.
   - The healthchecks.io check goes green.

### Org-token fallback

If step 2 (Telegram/no-op) succeeds but no new `state.json` commit appears,
the repo's org policy is blocking the default `GITHUB_TOKEN`'s `contents: write`
permission. Fix:

1. Create a **fine-grained personal access token** scoped to this repo only,
   with the `contents: write` permission and nothing broader.
2. Store it as the repo secret `STATE_PAT`.
3. In `.github/workflows/sentinel.yml`, uncomment the fallback and add
   `token: ${{ secrets.STATE_PAT }}` to the `actions/checkout` step.
4. Re-run `workflow_dispatch` and confirm the `state.json` commit now appears.

## Maintenance note

The NSE trading-holiday list in `holidays.py` is hand-maintained and seeded
through 2026–2027. Recommended one-time task: cross-check the 2026 dates
against NSE's own official holiday circular. When NSE publishes the 2028 list,
add it to `holidays.py` — a run past the last seeded year still executes but
prints and Telegrams a loud warning rather than silently assuming the market
is open.
