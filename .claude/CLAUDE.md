<!-- GSD:project-start source:PROJECT.md -->
## Project

**Groww Sentinel**

A daily automated advisor over my personal Groww equity holdings. Each weekday
morning it fetches holdings + live prices, applies my profit-booking + averaging
strategy as deterministic rules, and pings me on Telegram with per-stock flags
(average / trim / book / stop / hold) plus a portfolio P&L trend. Friday's digest
also carries a weekly summary. It surfaces candidates and reminds me to run manual
judgment gates — it does **not** trade and does **not** make the final decision.

> **Not investment advice.** Rules encode a personal strategy. All actions are
> reviewed and executed manually.

**Core Value:** Every trading morning I get a short, trustworthy Telegram digest that flags which
of my holdings need attention today — so I never miss a stop, trim, or averaging
opportunity, and I never have to open the app to check.

### Constraints

- **Tech stack**: Python + `growwapi` SDK + `pyotp` — official, headless-friendly, free.
- **Runtime**: GitHub Actions cron only — no always-on server; ~08:30 IST weekdays.
- **Security**: Secrets (`GROWW_API_KEY`, `GROWW_TOTP_SEED`, `TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID`) as GitHub encrypted secrets — never committed.
- **State persistence**: state.json committed back to repo → workflow token needs `contents: write`; under the `ThePubDoc` org this may be restricted (same family as the `workflow`-scope caveat). Resolve at impl time.
- **File size**: keep modules focused (<200 lines each): broker / rules / notify / sentinel split.
- **Correctness**: rules engine must be a pure, fully unit-testable function — no I/O.
<!-- GSD:project-end -->

<!-- GSD:stack-start source:research/STACK.md -->
## Technology Stack

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
# Core
# Holiday calendar (recommended)
# Dev/test
## growwapi: concretely resolved
# -> {"NSE_RELIANCE": 2500.5, "NSE_TCS": 3450.0}
- Method is `get_ltp()`, not `get_live_price()` or similar — this resolves the spec's open item on exact method name.
- **Up to 50 instruments per call.** For a personal portfolio (almost certainly <50 holdings), this means **one call per run**, not one call per symbol — better than the spec assumed, and rate limits are a non-issue at this volume.
- Symbols must be prefixed with exchange (`NSE_<SYMBOL>`), built from the `trading_symbol` returned by holdings.
| API type | Per-second | Per-minute |
|----------|-----------|------------|
| Orders | 10 | 250 |
| Live Data | 10 | 300 |
| Non-Trading | 20 | 500 |
## average_price corporate-action adjustment: **unresolved by documentation — flag, don't guess**
## Telegram: raw HTTP via `requests`, not `python-telegram-bot`
## NSE trading-holiday calendar: recommend `pandas_market_calendars` (`XNSE`)
## GitHub Actions: committing `state.json` back to the repo
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
<!-- GSD:stack-end -->

<!-- GSD:conventions-start source:CONVENTIONS.md -->
## Conventions

Conventions not yet established. Will populate as patterns emerge during development.
<!-- GSD:conventions-end -->

<!-- GSD:architecture-start source:ARCHITECTURE.md -->
## Architecture

Architecture not yet mapped. Follow existing patterns found in the codebase.
<!-- GSD:architecture-end -->

<!-- GSD:skills-start source:skills/ -->
## Project Skills

No project skills found. Add skills to any of: `.claude/skills/`, `.agents/skills/`, `.cursor/skills/`, `.github/skills/`, or `.codex/skills/` with a `SKILL.md` index file.
<!-- GSD:skills-end -->

<!-- GSD:workflow-start source:GSD defaults -->
## GSD Workflow Enforcement

Before using Edit, Write, or other file-changing tools, start work through a GSD command so planning artifacts and execution context stay in sync.

Use these entry points:
- `/gsd-quick` for small fixes, doc updates, and ad-hoc tasks
- `/gsd-debug` for investigation and bug fixing
- `/gsd-execute-phase` for planned phase work

Do not make direct repo edits outside a GSD workflow unless the user explicitly asks to bypass it.
<!-- GSD:workflow-end -->



<!-- GSD:profile-start -->
## Developer Profile

> Profile not yet configured. Run `/gsd-profile-user` to generate your developer profile.
> This section is managed by `generate-claude-profile` -- do not edit manually.
<!-- GSD:profile-end -->
