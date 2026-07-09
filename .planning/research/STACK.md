# Stack Research

**Domain:** Headless personal finance cron bot (Python, brokerage API → rules → Telegram, GitHub Actions)
**Researched:** 2026-07-09
**Confidence:** HIGH (growwapi/pyotp/GitHub Actions mechanics verified against official docs/PyPI); MEDIUM (NSE holiday calendar accuracy; growwapi rate-limit numbers not independently re-verified beyond docs page); the `average_price` corporate-action question is **explicitly unresolved by Groww's docs** — flagged below, not guessed.

## Recommended Stack

### Core Technologies

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| Python | 3.11+ (SDK supports 3.9–3.13) | Runtime | Only language with an official `growwapi` SDK; matches GitHub Actions' fastest-available `setup-python` cache tier. |
| `growwapi` | **1.5.0** (PyPI, released 2025-12-06) | Official Groww TradeAPI SDK — auth, holdings, LTP | Sanctioned, free, no scraping risk. Sole officially supported access path per project constraints. |
| `pyotp` | **2.10.0** (PyPI) | Headless TOTP generation from stored seed | Purpose-built, zero-dependency, exactly what Groww's own docs show for headless/CI auth (`pyotp.TOTP(secret).now()`). Nothing lighter exists that's correct. |
| GitHub Actions (`ubuntu-latest` + cron) | n/a | Scheduler + runtime | Matches "no always-on server" constraint; free tier covers one run/weekday trivially; secrets + `contents: write` cover every remaining requirement (auth, state persistence). |

### Supporting Libraries

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `requests` | 2.32.x (stdlib-adjacent, already a transitive dep of `growwapi`) | Telegram `sendMessage` call | Always — see Telegram section below. No bot framework needed for a one-shot fire-and-exit message. |
| `PyYAML` | **6.0.3** (PyPI, 2025-09-25) | Parse `config.yaml` (core/tactical tags) | Always — de facto standard YAML parser, no viable stdlib alternative (stdlib has no YAML support). |
| `pandas_market_calendars` | latest (pulls in `exchange_calendars`) | NSE holiday check via `XNSE` calendar | Recommended — see rationale below. Only needed if you don't want to hand-maintain a static list. |
| `pytest` | **8.4.2** (PyPI, 2025-09-04) | Unit tests for `rules.py`, mocked I/O tests for `broker.py`/`notify.py` | Always — project requirement is explicit; pytest is the standard, no rationale needed beyond that. |

### Development Tools

| Tool | Purpose | Notes |
|------|---------|-------|
| `pip-tools` (`pip-compile`) *or* plain pinned `requirements.txt` | Dependency pinning | For a 5-dependency personal cron job, a hand-pinned `requirements.txt` with exact versions is enough — `pip-tools` is justified only if you want a lockfile-with-hashes workflow. Given YAGNI, start with pinned `requirements.txt`; add `pip-tools` only if dependency drift actually bites you. |
| GitHub Actions `setup-python` with `cache: pip` | Faster CI installs | One line in the workflow; avoids re-downloading the same 5 wheels every weekday run. |

## Installation

```bash
# Core
pip install growwapi==1.5.0 pyotp==2.10.0 requests==2.32.3 PyYAML==6.0.3

# Holiday calendar (recommended)
pip install pandas_market_calendars

# Dev/test
pip install pytest==8.4.2
```

Pin every version in `requirements.txt` — this is a cron job with no human watching each run; an unpinned transitive upgrade breaking `rules.py` silently on a Monday morning is exactly the failure mode this project exists to prevent.

## growwapi: concretely resolved

**Package:** `growwapi` on PyPI, current version **1.5.0** (2025-12-06), requires Python `>=3.9,<4.0`.

**Auth (headless, TOTP-based — matches project design):**
```python
from growwapi import GrowwAPI
import pyotp

totp = pyotp.TOTP(GROWW_TOTP_SEED).now()
access_token = GrowwAPI.get_access_token(api_key=GROWW_API_KEY, totp=totp)
groww = GrowwAPI(access_token)
```
Per Groww's own docs, the TOTP-based access token has **no expiry**, unlike the API-key+secret flow (which needs daily manual re-approval on the Groww Cloud dashboard — unusable for unattended cron). This confirms the project's chosen auth path is the *only* viable one for headless GitHub Actions.

**Holdings — confirmed method + fields:**
```python
holdings_response = groww.get_holdings_for_user(timeout=5)
```
Returns a collection with, per holding: `isin`, `trading_symbol`, `quantity`, `average_price`, `pledge_quantity`, `demat_locked_quantity`, `groww_locked_quantity`, `repledge_quantity`, `t1_quantity`, `demat_free_quantity`, `corporate_action_additional_quantity`, `active_demat_transfer_quantity`. **No LTP field** — confirms spec's assumption that LTP must be fetched separately.

**Live price (LTP) — resolved method name, spec's open item closed:**
```python
ltp_response = groww.get_ltp(
    segment=groww.SEGMENT_CASH,
    exchange_trading_symbols=("NSE_RELIANCE", "NSE_TCS")  # tuple, up to 50 per call
)
# -> {"NSE_RELIANCE": 2500.5, "NSE_TCS": 3450.0}
```
- Method is `get_ltp()`, not `get_live_price()` or similar — this resolves the spec's open item on exact method name.
- **Up to 50 instruments per call.** For a personal portfolio (almost certainly <50 holdings), this means **one call per run**, not one call per symbol — better than the spec assumed, and rate limits are a non-issue at this volume.
- Symbols must be prefixed with exchange (`NSE_<SYMBOL>`), built from the `trading_symbol` returned by holdings.

**Rate limits — resolved (from official docs, `exceptions` + intro pages):**

| API type | Per-second | Per-minute |
|----------|-----------|------------|
| Orders | 10 | 250 |
| Live Data | 10 | 300 |
| Non-Trading | 20 | 500 |

At one run/weekday with ≤1 holdings call + 1 LTP call, this project uses **~0.1% of the Live Data quota**. No throttling/backoff logic is needed beyond catching `GrowwAPIRateLimitException` defensively (cheap insurance, not a real risk here).

**Exception hierarchy** (for the "notify on failure, exit non-zero" requirement): `GrowwBaseException` → `GrowwAPIException` (covers `GrowwAPIAuthenticationException`, `GrowwAPIAuthorisationException`, `GrowwAPIRateLimitException`, `GrowwAPIBadRequestException`, `GrowwAPINotFoundException`, `GrowwAPITimeoutException`) and a separate `GrowwFeedException` for streaming (irrelevant here — this project only needs REST calls). Catch `GrowwAPIException` broadly in `broker.py`, let it bubble to `sentinel.py`, and have `sentinel.py`'s top-level handler format the Telegram failure alert.

## average_price corporate-action adjustment: **unresolved by documentation — flag, don't guess**

Groww's official schema docs describe `average_price` only as "the average price of the holding" with **no statement on whether bonus issues or stock splits are already factored in**. The presence of a separate `corporate_action_additional_quantity` field is suggestive (it implies quantity is tracked/adjusted for corporate actions) but says nothing about whether `average_price` itself is retroactively adjusted.

**Recommendation:** Do not build adjustment-handling logic speculatively (YAGNI — matches the project's own "verify at impl, don't pre-build" decision). Instead:
1. At implementation time, cross-check `average_price` for any holding that has had a real bonus/split against manually known cost basis.
2. If unadjusted: add a one-line caveat to the Telegram digest for affected symbols only (e.g., "⚠️ RELIANCE: avg cost may not reflect 2024 split") — this is a formatting change, not a rules-engine change.
3. Do not silently trust it either way; this is a money-path field.

**Confidence:** LOW on the underlying fact (Groww hasn't documented it) — this is the correct disposition, not a gap to fill with a guess.

## Telegram: raw HTTP via `requests`, not `python-telegram-bot`

**Recommendation: raw HTTP POST via `requests`.**

```python
import requests

def send_telegram(token: str, chat_id: str, text: str) -> None:
    resp = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
        timeout=10,
    )
    resp.raise_for_status()
```

**Why not `python-telegram-bot` (or `aiogram`/`Telebot`):** those libraries exist to run a *long-lived bot process* — polling updates, handling multiple chats, retrying rate limits across many messages per second. This job sends **one message, once a day, then exits.** A bot framework here is dependency weight (async event loop, `httpx`, update-handling machinery) with zero corresponding benefit — this is the textbook "installed dependency already solves it at one line" case, except here even the dependency isn't needed: `requests` (already a `growwapi` transitive dependency) is sufficient. Rate-limit retry logic that libraries provide is irrelevant at one call/day.

**What NOT to use:** `python-telegram-bot`, `aiogram`, `telebot`, `telegram-send` CLI wrapper — all add abstraction for a multi-message/interactive-bot use case this project doesn't have.

## NSE trading-holiday calendar: recommend `pandas_market_calendars` (`XNSE`)

Three options evaluated:

1. **`pandas_market_calendars`** (wraps `exchange_calendars`) — pulls the `XNSE` (National/Bombay Stock Exchange of India) calendar. Actively maintained, widely used in quant/fintech Python, has unit tests per its own calendar-status page. Usage:
   ```python
   import pandas_market_calendars as mcal
   nse = mcal.get_calendar("XNSE")
   is_trading_day = not nse.schedule(start_date=today, end_date=today).empty
   ```
2. **`nse-trading-calendar`** (PyPI, v0.1.6, last released 2026-01-30) — small, single-purpose, but far newer/less battle-tested and its "historical data"-based approach for forward dates is undocumented in terms of how far ahead it's accurate.
3. **Static hand-maintained list** — zero dependencies, but requires an annual manual update (NSE publishes each year's ~14 holidays around December) and silently goes stale if forgotten — this is the failure mode "never silently skip a day" was written to prevent, so a stale hardcoded list is actively dangerous here.

**Recommendation: `pandas_market_calendars`.** It's a real dependency, but it's the only option that's both maintained by a community with a direct incentive to keep exchange calendars current (quant trading, not a fintech side project) and has automated calendar generation (not a list someone forgot to update). Confidence: MEDIUM — `exchange_calendars`' NSE coverage isn't as heavily scrutinized as its US/UK calendars (fewer users), so **cross-check the 2025/2026 output against the NSE-published list once at implementation time** before trusting it blind. If it diverges, fall back to a static list refreshed each December — a one-line YAML/JSON list is an acceptable YAGNI fallback if the library proves wrong, not the default.

**What NOT to use:** `nsepython` — scrapes/hits unofficial NSE endpoints for many of its features; even though only the holiday-list feature would be used here, it violates the project's explicit "no scraping / unofficial APIs" constraint (stated for the broker but the same principle applies) and is a maintenance/breakage risk for a feature `pandas_market_calendars` covers cleanly.

## GitHub Actions: committing `state.json` back to the repo

**Confirmed pattern:**

```yaml
permissions:
  contents: write

jobs:
  sentinel:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
      - run: pip install -r requirements.txt
      - run: python sentinel.py
        env:
          GROWW_API_KEY: ${{ secrets.GROWW_API_KEY }}
          GROWW_TOTP_SEED: ${{ secrets.GROWW_TOTP_SEED }}
          TELEGRAM_TOKEN: ${{ secrets.TELEGRAM_TOKEN }}
          TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
      - uses: stefanzweifel/git-auto-commit-action@v5
        with:
          commit_message: "chore: update state.json [skip ci]"
          file_pattern: state.json
```

- `permissions: contents: write` on the workflow (or job) is **required** — the default `GITHUB_TOKEN` is otherwise read-only in many org/repo configurations. This directly addresses the PROJECT.md constraint about `ThePubDoc`-org token scope: `contents: write` under `permissions:` is a workflow-level grant, **separate from and unaffected by** the personal-account `workflow` OAuth scope caveat (that caveat only blocks *pushing the `.yml` file itself* from a scope-limited PAT, not the token the workflow uses at runtime). Once the workflow file itself is on the default branch, its `contents: write` permission works regardless of which account originally pushed it.
- `stefanzweifel/git-auto-commit-action` is the de facto standard for this exact pattern (commit generated files back to the triggering branch) — reinventing this with raw `git add/commit/push` shell steps is more code for identical behavior; use the maintained action.
- Add `[skip ci]` (or use `paths-ignore` on the workflow trigger) so the state-commit doesn't re-trigger the same workflow if it's ever configured to run `on: push`.
- **Secrets:** all four (`GROWW_API_KEY`, `GROWW_TOTP_SEED`, `TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID`) as GitHub encrypted repo secrets (Settings → Secrets and variables → Actions), injected via `env:` — never echoed to logs, never committed. Validate all four are present at process start (per PROJECT.md requirement) with a simple loop that raises naming the missing var, before any network call.

## Alternatives Considered

| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|--------------------------|
| `requests` raw HTTP for Telegram | `python-telegram-bot` | Only if this evolves into an interactive bot (replies, commands, multiple chats) — not this project's shape. |
| `pandas_market_calendars` (`XNSE`) | Static hardcoded holiday list | If the `XNSE` calendar is found to diverge from NSE's published list at impl-time verification — becomes the fallback, not the default. |
| Hand-pinned `requirements.txt` | `pip-tools` / `poetry` | If dependency count grows past ~10 or you want hash-pinned lockfiles — overkill for 5 packages. |
| `pytest` | `unittest` (stdlib) | Never here — project already commits to pytest idioms (fixtures, AAA) and it's the ecosystem standard; stdlib `unittest` would be more boilerplate for equal outcome. |

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| `python-telegram-bot`/`aiogram` | Long-lived-bot framework overhead (async loop, update polling machinery) for a one-shot daily message | Raw `requests.post()` to `sendMessage` |
| `nsepython` | Hits unofficial/scraped NSE endpoints — violates project's "official APIs only" posture; also less actively maintained for this narrow use | `pandas_market_calendars` (`XNSE`) |
| API-key+secret Groww auth flow (non-TOTP) | Requires **daily manual re-approval** on Groww's dashboard — fundamentally incompatible with unattended cron | TOTP flow (`pyotp` + `GrowwAPI.get_access_token(totp=...)`) — no expiry |
| Guessing `average_price` is corporate-action adjusted | Money-path field with undocumented behavior; guessing wrong silently corrupts every P&L/flag calculation for affected symbols | Verify empirically at impl time against a known bonus/split holding; caveat in digest if unadjusted |
| Raw `git commit`/`push` shell steps for state persistence | Reinvents a well-solved, well-tested problem; more failure surface (git identity config, push conflicts) for identical outcome | `stefanzweifel/git-auto-commit-action@v5` |

## Version Compatibility

| Package A | Compatible With | Notes |
|-----------|-----------------|-------|
| `growwapi==1.5.0` | Python 3.9–3.13 | Verified via PyPI classifiers; GitHub Actions `ubuntu-latest` ships 3.12 by default via `setup-python` — comfortably inside range. |
| `pyotp==2.10.0` | Python 3.8+ | No known conflicts with `growwapi`; zero heavy transitive deps. |
| `pandas_market_calendars` | pulls `pandas` + `exchange_calendars` as transitive deps | Heaviest dependency in this stack by far (pandas). Acceptable given no lighter maintained alternative exists for NSE-specific holiday accuracy; if this weight ever matters, the static-list fallback avoids it entirely. |

## Sources

- https://pypi.org/project/growwapi/ — version 1.5.0, Python range (HIGH confidence, official PyPI)
- https://groww.in/trade-api/docs/python-sdk — auth flows, TOTP vs API-key+secret expiry behavior (HIGH, official vendor docs)
- https://groww.in/trade-api/docs/python-sdk/portfolio — `get_holdings_for_user()` fields, `average_price` undocumented adjustment status (HIGH for schema, LOW/unresolved for adjustment behavior — explicitly flagged)
- https://groww.in/trade-api/docs/python-sdk/live-data — `get_ltp()` signature, 50-instrument batch limit (HIGH, official docs)
- https://groww.in/trade-api/docs/python-sdk/exceptions — exception hierarchy, rate-limit table (HIGH, official docs)
- https://pypi.org/project/PyOTP/ — version 2.10.0 (HIGH, official PyPI)
- https://pypi.org/project/PyYAML/ — version 6.0.3 (HIGH, official PyPI)
- https://pypi.org/project/pytest/ — version 8.4.2 (HIGH, official PyPI)
- https://pandas-market-calendars.readthedocs.io/en/latest/calendars.html — `XNSE` calendar existence/maintainer info (MEDIUM — no explicit accuracy rating published)
- https://pypi.org/project/nse-trading-calendar/ — alternative package, evaluated and not chosen (MEDIUM)
- https://github.com/stefanzweifel/git-auto-commit-action — GitHub Actions state-commit pattern, `contents: write` requirement (HIGH — widely used, well-documented action)

---
*Stack research for: personal Groww holdings → Telegram advisory cron bot*
*Researched: 2026-07-09*
