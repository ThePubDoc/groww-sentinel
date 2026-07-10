# Phase 3: Autonomous & Failure-Safe Runtime - Context

**Gathered:** 2026-07-09
**Status:** Ready for planning

<domain>
## Phase Boundary

Make Sentinel run itself on GitHub Actions and make every failure/miss loud.
Adds the cron workflow, NSE-holiday skip, automatic state.json commit-back,
concurrency guard, manual dispatch, fail-loud-on-error, and an independent
dead-man's-switch so message-absence is never mistaken for "all quiet".

Delivers: RUN-01, RUN-02, RUN-03, RUN-04, RUN-05, NOTIFY-04, NOTIFY-05.
This is the last v1 phase — after it, Sentinel is fully autonomous.

</domain>

<decisions>
## Implementation Decisions

### Schedule (RUN-01)
- **D-01:** Run **3×/weekday**, not hourly (revises Phase-2 D-01 and the roadmap's original 08:30-only SC): **pre-open ~09:00, midday ~12:30, close ~15:30 IST**. Fewer runs/commits/API calls while covering the key moments; peaks/telemetry still update intraday.
- **D-02:** GHA cron is UTC (IST = UTC+5:30) → ~03:30, 07:00, 10:00 UTC, **weekdays only** (`1-5`), on a **non-top-of-hour minute** (GHA best-effort drifts 5–30 min; avoid the :00 congestion). `workflow_dispatch` also enabled (RUN-05).

### NSE holiday skip (RUN-02)
- **D-03:** Hand-maintained **static `holidays.py`** NSE trading-holiday date set, **seeded 2026–2027** (project research chose static over `pandas_market_calendars` — no heavy pandas dep, can't silently drift). A run on a date **past the last seeded year emits a loud warning** (fail-loud, not silent-wrong) rather than assuming "open". Holiday/weekend → clean early exit, no digest.

### State commit-back + org token (RUN-03)
- **D-04:** Commit updated `state.json` back to the repo each run via **`stefanzweifel/git-auto-commit-action@v5`**, with workflow **`permissions: contents: write`** on the default `GITHUB_TOKEN`. Use `[skip ci]` / path-scoped triggers so the commit doesn't re-trigger the workflow.
- **D-05:** **ThePubDoc-org token caveat:** verify `contents: write` works with the default token at **first-run (`workflow_dispatch`)**. If the org restricts it, fall back to a **fine-grained PAT** (contents:write, this repo only) stored as secret `STATE_PAT`. Resolve empirically, don't pre-assume.

### Concurrency + fail-loud (RUN-04, NOTIFY-04)
- **D-06:** GHA **`concurrency:` group** (e.g. `groww-sentinel-run`, `cancel-in-progress: false`) so overlapping/duplicate runs can't clobber state.json.
- **D-07:** NOTIFY-04 is largely built (sentinel sends a Telegram warning naming the reason + exits non-zero on auth/fetch failure). Phase 3 ensures the **workflow surfaces that non-zero as a failed run** (no `|| true` masking) so GitHub's own failure signal also fires.

### Dead-man's-switch (NOTIFY-05)
- **D-08:** **healthchecks.io** (free external monitor). Sentinel **pings a success URL** (`HEALTHCHECK_URL` secret) only after a digest is actually sent/printed; healthchecks alerts (email/push) if no ping arrives within the grace window — catching **both a cron that never fired AND a crash before send**. External by design: survives even total GHA outage. GitHub's native failed-run email is a secondary backstop, not the primary (it can't detect a never-triggered cron).
- Ping placement: only on the true success path (after `notify.send`), and on the clean holiday/no-holdings exits too (those are "ran fine, nothing to do" — a missed *ping* must mean a real miss, not a holiday). Grace window tuned to the 3×/day cadence.

### Secrets (GHA encrypted repo secrets)
- **D-09:** All required + optional secrets as encrypted repo secrets, injected via `env:`: `GROWW_API_KEY`, `GROWW_TOTP_SEED`, `TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID` (required), plus optional `GEMINI_API_KEY` (sentiment), `HEALTHCHECK_URL` (dead-man switch), and `STATE_PAT` (only if D-05 fallback needed). Never echoed to logs.

### Claude's Discretion
- Exact cron minute values (non-:00), the `concurrency` group name, healthchecks grace-period number, and whether holiday/weekend skip lives in `sentinel.py` (Python early-exit, testable) vs a workflow `if:` guard — prefer Python so it's unit-testable and `workflow_dispatch` respects it too.
- `.github/workflows/*.yml` filename + step ordering.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### This phase
- `.planning/ROADMAP.md` — Phase 3 goal + SC (note the "08:30 weekday" SC is superseded by D-01's 3×/day)
- `.planning/REQUIREMENTS.md` — RUN-01..05, NOTIFY-04, NOTIFY-05
- `.planning/research/STACK.md` — GitHub Actions state-commit pattern, `git-auto-commit-action`, `contents: write`, static-holiday-list rationale, secrets guidance
- `.planning/research/PITFALLS.md` — dead-man's-switch as hard requirement; cron best-effort/no-SLA; org-token restriction; `[skip ci]`

### Existing code this phase wraps
- `sentinel.py` — the entrypoint the workflow invokes; already loads/saves state.json, validates secrets (DATA-04), sends fail-loud Telegram warning + exits non-zero. Phase 3 adds: holiday/weekend early-exit + healthchecks ping.
- `state.py` — state.json read/write (the file the workflow commits back)
- `.env.example` — mirror the secret set into GHA repo secrets

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `sentinel.main()` already returns proper exit codes (0 ok / 2 missing-secret / 1 fetch-fail) and sends a best-effort failure Telegram — the workflow just must NOT mask the non-zero exit.
- `state.py` load/save already atomic — the workflow only needs to `git add state.json` + commit after the process exits.

### Established Patterns
- Pure-core/impure-shell: keep holiday check + healthcheck ping in `sentinel.py`/a small module (testable with injected `today`), not buried in YAML. Only genuinely CI-specific glue (cron, commit-back, secrets) lives in the workflow.

### Integration Points
- `.github/workflows/sentinel.yml`: cron + workflow_dispatch → setup-python + pip install (cache) → run `python -m sentinel` with secrets in env → git-auto-commit-action for state.json. Concurrency guard at workflow level.

</code_context>

<specifics>
## Specific Ideas

- First real deploy is a `workflow_dispatch` run to verify secrets + `contents: write` before enabling cron (D-05).
- `[skip ci]` on the state.json commit to avoid self-triggering.

</specifics>

<deferred>
## Deferred Ideas

- Full hourly cadence (Phase-2 D-01) — dropped in favour of lean 3×/day (D-01 here). Revisit only if intraday coverage proves insufficient.
- `pandas_market_calendars` holiday source — deferred; static list preferred (D-03).
- Sturdier news source than yfinance (carried from Phase 2 deferred) — still open, not required for v1 autonomy.

</deferred>

---

*Phase: 3-Autonomous & Failure-Safe Runtime*
*Context gathered: 2026-07-09*
