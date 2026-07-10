# Phase 3: Autonomous & Failure-Safe Runtime - Research

**Researched:** 2026-07-10
**Domain:** GitHub Actions cron scheduling, git-committed state persistence, external dead-man's-switch monitoring
**Confidence:** HIGH (GitHub Actions mechanics, git-auto-commit-action, healthchecks.io ping API — all cross-checked against official docs/GitHub API); MEDIUM (NSE 2026 holiday date list — cross-checked across two independent brokerage sources, not NSE's own site directly, since nseindia.com timed out on fetch); LOW (2027 NSE dates — not yet published anywhere, correctly so per D-03's own "warn past last seeded year" design)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** Run **3×/weekday**, not hourly (revises Phase-2 D-01 and the roadmap's original 08:30-only SC): **pre-open ~09:00, midday ~12:30, close ~15:30 IST**. Fewer runs/commits/API calls while covering the key moments; peaks/telemetry still update intraday.
- **D-02:** GHA cron is UTC (IST = UTC+5:30) → ~03:30, 07:00, 10:00 UTC, **weekdays only** (`1-5`), on a **non-top-of-hour minute** (GHA best-effort drifts 5–30 min; avoid the :00 congestion). `workflow_dispatch` also enabled (RUN-05).
- **D-03:** Hand-maintained **static `holidays.py`** NSE trading-holiday date set, **seeded 2026–2027** (project research chose static over `pandas_market_calendars` — no heavy pandas dep, can't silently drift). A run on a date **past the last seeded year emits a loud warning** (fail-loud, not silent-wrong) rather than assuming "open". Holiday/weekend → clean early exit, no digest.
- **D-04:** Commit updated `state.json` back to the repo each run via **`stefanzweifel/git-auto-commit-action@v5`**, with workflow **`permissions: contents: write`** on the default `GITHUB_TOKEN`. Use `[skip ci]` / path-scoped triggers so the commit doesn't re-trigger the workflow.
- **D-05:** **ThePubDoc-org token caveat:** verify `contents: write` works with the default token at **first-run (`workflow_dispatch`)**. If the org restricts it, fall back to a **fine-grained PAT** (contents:write, this repo only) stored as secret `STATE_PAT`. Resolve empirically, don't pre-assume.
- **D-06:** GHA **`concurrency:` group** (e.g. `groww-sentinel-run`, `cancel-in-progress: false`) so overlapping/duplicate runs can't clobber state.json.
- **D-07:** NOTIFY-04 is largely built (sentinel sends a Telegram warning naming the reason + exits non-zero on auth/fetch failure). Phase 3 ensures the **workflow surfaces that non-zero as a failed run** (no `|| true` masking) so GitHub's own failure signal also fires.
- **D-08:** **healthchecks.io** (free external monitor). Sentinel **pings a success URL** (`HEALTHCHECK_URL` secret) only after a digest is actually sent/printed; healthchecks alerts (email/push) if no ping arrives within the grace window — catching **both a cron that never fired AND a crash before send**. External by design: survives even total GHA outage. GitHub's native failed-run email is a secondary backstop, not the primary (it can't detect a never-triggered cron). Ping placement: only on the true success path (after `notify.send`), and on the clean holiday/no-holdings exits too (those are "ran fine, nothing to do" — a missed *ping* must mean a real miss, not a holiday). Grace window tuned to the 3×/day cadence.
- **D-09:** All required + optional secrets as encrypted repo secrets, injected via `env:`: `GROWW_API_KEY`, `GROWW_TOTP_SEED`, `TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID` (required), plus optional `GEMINI_API_KEY` (sentiment), `HEALTHCHECK_URL` (dead-man switch), and `STATE_PAT` (only if D-05 fallback needed). Never echoed to logs.

### Claude's Discretion

- Exact cron minute values (non-:00), the `concurrency` group name, healthchecks grace-period number, and whether holiday/weekend skip lives in `sentinel.py` (Python early-exit, testable) vs a workflow `if:` guard — prefer Python so it's unit-testable and `workflow_dispatch` respects it too.
- `.github/workflows/*.yml` filename + step ordering.

### Deferred Ideas (OUT OF SCOPE)

- Full hourly cadence (Phase-2 D-01) — dropped in favour of lean 3×/day (D-01 here). Revisit only if intraday coverage proves insufficient.
- `pandas_market_calendars` holiday source — deferred; static list preferred (D-03).
- Sturdier news source than yfinance (carried from Phase 2 deferred) — still open, not required for v1 autonomy.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| RUN-01 | GHA cron ~08:30 IST weekdays, non-top-of-hour minute — **superseded by D-01/D-02: 3×/weekday at ~09:00/12:30/15:30 IST** | Cron math verified below (03:30/07:00/10:00 UTC); GitHub's own "avoid `:00`" guidance confirmed in Architecture Patterns §GHA cron |
| RUN-02 | Skip NSE trading holidays (static list) | Concrete 2026 date list provided below (cross-checked, MEDIUM); 2027 not yet published — warn-path design confirmed correct |
| RUN-03 | Commit `state.json` back (`contents: write`) as a post-process workflow step | `git-auto-commit-action@v5` YAML pattern + `[skip ci]` in Code Examples; version currency flagged in State of the Art |
| RUN-04 | `concurrency` guard preventing overlapping/duplicate runs | Syntax + `cancel-in-progress: false` confirmed in Architecture Patterns |
| RUN-05 | `workflow_dispatch` manual trigger | Confirmed alongside `schedule:` in Code Examples |
| NOTIFY-04 | Fail-loud Telegram + non-zero exit on auth/fetch failure — largely built in `sentinel.py` already | Workflow-level requirement: don't mask exit code (`run: python -m sentinel` with no `|| true`); confirmed in Common Pitfalls |
| NOTIFY-05 | Independent dead-man's-switch | healthchecks.io ping API fully resolved below (URL formats, HTTP methods, cron-schedule mode, grace time, free-tier limits) |
</phase_requirements>

## Summary

This phase is almost entirely CI/workflow glue around an already-complete `sentinel.py` — no new Python dependencies, no new architecture, just wiring. Three things needed hard verification and are now resolved: (1) the concrete NSE 2026 holiday date list (15 dates, cross-checked across two brokerage sources — 2027 is genuinely not published yet anywhere, which validates D-03's "warn past last seeded year" design rather than being a research gap); (2) healthchecks.io's ping API is simple (`GET/HEAD/POST https://hc-ping.com/<uuid>`, `/start`, `/fail` suffixes) and supports a **cron-expression schedule mode** that natively understands "weekdays only, 3×/day" — this is the correct way to configure the check so a genuine weekend gap never false-alarms; (3) `stefanzweifel/git-auto-commit-action` is current at `@v7`, but `@v5` (the locked decision) still exists as a valid, resolvable tag — it will work, just isn't receiving new features/fixes; this is flagged for the user, not silently overridden.

**Primary recommendation:** Build `.github/workflows/sentinel.yml` with three `schedule:` cron entries (`30 3 * * 1-5`, `0 7 * * 1-5`, `0 10 * * 1-5`) plus `workflow_dispatch`, a `concurrency` group, `permissions: contents: write`, a `pip install` step with `cache: pip`, `run: python -m sentinel` (exit code un-masked), and `stefanzweifel/git-auto-commit-action@v5` scoped to `file_pattern: state.json` with `[skip ci]` in the commit message. Add a small `holidays.py` module (static 2026 set, `is_trading_holiday(today)`, warns past 2027) and a `healthcheck_ping(url)` helper called from `sentinel.py` on every non-error exit path (success, holiday, no-holdings) — never on the error path, so a genuinely broken run correctly stays silent to healthchecks and it alerts.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Cron scheduling / trigger | CI (GitHub Actions workflow YAML) | — | GHA-native; not something Python code can control |
| Weekend/holiday skip decision | Application (Python, `sentinel.py`/`holidays.py`) | — | Must be unit-testable with injected `today`; must also apply on `workflow_dispatch` manual runs, which a workflow-level `if:` guard on `github.event.schedule` cannot see |
| State persistence (`state.json` write) | Application (`state.py`, already built) | CI (git commit-back step) | App writes the file to disk; CI is responsible only for getting the already-correct file back into git — no business logic belongs in the commit step |
| Failure detection (auth/fetch error) | Application (`sentinel.py` exception handler, already built) | CI (workflow must not mask exit code) | The *reason* for failure is app-level; the *propagation* of that failure as a red X is a one-line CI contract (no `|| true`) |
| Dead-man's-switch (missed cron / crash-before-send) | External (healthchecks.io) | Application (ping call on success path) | Must be genuinely independent of the GHA job — a monitor that also runs inside the same failed pipeline can't detect "pipeline never started" |
| Concurrency safety | CI (workflow `concurrency:` block) | — | Native GHA feature; no equivalent exists inside a single Python process invocation |

## Standard Stack

### Core

No new runtime dependencies this phase. `requests` (already pinned `2.32.3` in `requirements.txt`) covers the healthchecks.io ping — a single `requests.get(url, timeout=10)` call, same pattern already used for Telegram in `notify.py`.

| Component | Version | Purpose | Why Standard |
|-----------|---------|---------|---------------|
| `stefanzweifel/git-auto-commit-action` | `@v5` (locked, D-04) — current major is `@v7` | Commits `state.json` back to the repo post-run | Locked decision; de facto standard for this exact "commit generated file back" pattern (confirmed via `research/STACK.md`) — see State of the Art for the version-currency note |
| `actions/checkout` | `@v4` or `@v5` | Checkout repo before running | Standard first step in every GHA workflow |
| `actions/setup-python` | `@v5` | Python runtime + `cache: pip` | Already used per `research/STACK.md`; speeds repeat installs |
| healthchecks.io (external service, no package) | n/a (free "Hobbyist" tier) | Dead-man's-switch ping target | Free tier: **20 checks, 3 team members, 100 log entries/check** `[CITED: healthchecks.io pricing comparisons, cross-checked across 2 sources]` — one check is more than sufficient for this project |

### Supporting

No new supporting libraries. `holidays.py` is a pure-stdlib data module (a `set[date]` or `set[str]` literal + one comparison function) — a dependency here would violate the project's own D-03 rationale (avoid `pandas_market_calendars`'s pandas weight).

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `stefanzweifel/git-auto-commit-action@v5` (locked) | `@v7` (current) | `@v7` gets ongoing fixes; `@v5` is frozen but still resolves and functions today (verified: tag exists on the repo) — a version bump is a zero-risk follow-up, not required for this phase |
| healthchecks.io | UptimeRobot, Cronitor, a second parallel GHA workflow with a schedule offset | healthchecks.io is free-tier sufficient, has a native cron-aware schedule mode (handles "weekdays only" natively) that generic uptime monitors lack — this is why D-08 already locked it |
| Static `holidays.py` (locked, D-03) | `pandas_market_calendars` (`XNSE`) | Deferred per D-03/roadmap RUN-06 — heavier dependency, better long-term accuracy; static list chosen for v1 to avoid the pandas dependency weight |

**Installation:** No new packages to install — `requirements.txt` is unchanged this phase.

**Version verification:**
```bash
# git-auto-commit-action tag currency (confirmed via GitHub API, not npm/pip)
curl -s https://api.github.com/repos/stefanzweifel/git-auto-commit-action/tags | head -30
# -> v7.2.0 is current; v5, v5.0.0..v5.2.0 all still exist and resolve
```
`requests==2.32.3` is already installed and pinned; no re-verification needed for this phase's usage (a GET call, no new API surface).

## Package Legitimacy Audit

**No new packages installed this phase.** `requests` is an existing, already-audited dependency (Phase 1). `holidays.py` and the healthcheck-ping helper are hand-written stdlib/`requests`-only modules, not third-party packages. `stefanzweifel/git-auto-commit-action` is a GitHub Action (not a PyPI/npm package) — already locked by CONTEXT.md D-04 and cross-checked directly against the GitHub repo's own tag list above (not a registry lookup, since Actions aren't published to npm/PyPI).

**Packages removed due to [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

## Architecture Patterns

### System Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│ GitHub Actions: .github/workflows/sentinel.yml                       │
│                                                                       │
│  Trigger ─┬─ schedule: cron (3× weekdays, UTC)                       │
│           └─ workflow_dispatch (manual)                              │
│                          │                                           │
│                          ▼                                           │
│  concurrency: { group: groww-sentinel-run, cancel-in-progress:false }│
│                          │                                           │
│                          ▼                                           │
│  actions/checkout → actions/setup-python (cache: pip) → pip install  │
│                          │                                           │
│                          ▼                                           │
│  run: python -m sentinel   (env: secrets injected)                   │
│       │                                                               │
│       ├─▶ sentinel.py: is_trading_holiday(today)? ──yes──▶ ping      │
│       │        (weekend/holiday)                     healthchecks   │
│       │        │no                                    (success)     │
│       │        ▼                                       then exit 0  │
│       │   auth → holdings → prices → rules → notify                 │
│       │        │                          │                          │
│       │        │ error at any stage       │ success                 │
│       │        ▼                          ▼                         │
│       │   Telegram warning            Telegram digest sent          │
│       │   exit 1 or 2                 ping healthchecks (success)   │
│       │   (NO healthcheck ping)        exit 0                       │
│       ▼                                                              │
│  process exit code propagates to the shell step (no `|| true`) ──┐   │
│                                                                    │  │
│                          ▼ (only if exit 0)                       │  │
│  stefanzweifel/git-auto-commit-action@v5                          │  │
│    file_pattern: state.json                                       │  │
│    commit_message: "chore: update state.json [skip ci]"           │  │
└────────────────────────────────────────────────────────────────────┘  │
                                                                          │
        exit 1/2 propagates ──▶ GitHub Actions marks run FAILED ─────────┘
                                        │
                                        ▼
                          GitHub's native "workflow failed" email
                          (secondary backstop, per D-08)

Independent of all of the above:
        healthchecks.io check (cron-schedule mode, weekdays 3×/day)
                │
                no ping arrives within grace window
                ▼
        healthchecks.io alerts (email/push) — the PRIMARY dead-man's-switch,
        catches "cron never fired" which nothing inside the GHA run can see.
```

### Recommended Project Structure

```
.github/
└── workflows/
    └── sentinel.yml       # cron + workflow_dispatch + concurrency + commit-back
holidays.py                # NEW: static NSE trading-holiday set + is_trading_holiday(today)
sentinel.py                # MODIFIED: holiday/weekend early-exit + healthcheck ping calls
```

No other files change. `broker.py`, `rules.py`, `notify.py`, `state.py`, `prices.py`, `sentiment.py` are untouched by this phase.

### Pattern 1: Python-side holiday/weekend early-exit (not a workflow `if:` guard)

**What:** `sentinel.main()` checks `today.weekday() >= 5 or holidays.is_trading_holiday(today)` immediately after computing IST `today`, before any network call, and exits cleanly (ping healthchecks, no digest, exit 0).
**When to use:** Always for this phase — per CONTEXT.md's own Established Patterns note.
**Why not a workflow `if:` guard:** A `workflow_dispatch` manual run must still respect market-closed days consistently with the scheduled run (same code path, same test coverage); a YAML-level `if:` can only see `github.event.schedule`, not "is today a holiday" (GHA has no calendar awareness), so the actual holiday logic has to live in Python regardless — a workflow guard would be redundant at best, wrong at worst (it can't know NSE's calendar).
**Example:**
```python
# holidays.py — Source: static NSE 2026 date list, cross-checked (see Sources)
from datetime import date

# NSE full trading holidays, 2026 (weekday holidays only — Sat/Sun are
# already non-trading and handled separately by today.weekday() >= 5).
# [CITED: zerodha.com/marketintel/holiday-calendar, cleartax.in/s/nse-holidays-2026
#  — cross-checked, both list the same 15 dates]
NSE_HOLIDAYS_2026 = {
    date(2026, 1, 15),   # Maharashtra municipal elections
    date(2026, 1, 26),   # Republic Day
    date(2026, 3, 3),    # Holi
    date(2026, 3, 26),   # Shri Ram Navami
    date(2026, 3, 31),   # Shri Mahavir Jayanti
    date(2026, 4, 3),    # Good Friday
    date(2026, 4, 14),   # Dr. Baba Saheb Ambedkar Jayanti
    date(2026, 5, 1),    # Maharashtra Day
    date(2026, 5, 28),   # Bakri Id
    date(2026, 6, 26),   # Muharram
    date(2026, 9, 14),   # Ganesh Chaturthi
    date(2026, 10, 2),   # Mahatma Gandhi Jayanti
    date(2026, 10, 20),  # Dussehra
    date(2026, 11, 10),  # Diwali-Balipratipada
    date(2026, 12, 25),  # Christmas
}

# 2027 dates: NOT YET PUBLISHED by NSE or any brokerage as of 2026-07-10
# [ASSUMED absence confirmed via WebSearch — no source publishes 2027 NSE
#  holidays this early; NSE typically releases the following year's list
#  around December]. D-03's "seeded 2026-2027" intent cannot be fully met
# until NSE publishes 2027 — ship 2026 now, add 2027 when published
# (expect ~December 2026), and rely on the warn-path below in the meantime.
LAST_SEEDED_YEAR = 2026

ALL_HOLIDAYS = NSE_HOLIDAYS_2026  # union in future years


def is_trading_holiday(today: date) -> tuple[bool, str | None]:
    """Returns (is_holiday, warning). Warning is set when `today` is past the
    last seeded year — fail-loud per D-03, never silently assume 'open'."""
    warning = None
    if today.year > LAST_SEEDED_YEAR:
        warning = (
            f"holidays.py has no data for {today.year} "
            f"(last seeded: {LAST_SEEDED_YEAR}) — update the static list"
        )
    return today in ALL_HOLIDAYS, warning
```

### Pattern 2: healthchecks.io ping as a best-effort side effect, never a failure cause

**What:** A single `requests.get`/`HEAD` call to `HEALTHCHECK_URL`, wrapped in the same best-effort `try/except: pass` style already used for `_best_effort_notify` in `sentinel.py` — a ping failure must never crash or fail the run (that would be the monitor becoming a second point of failure).
**When to use:** After a successful digest send, after the weekend/holiday early-exit, and after the "no holdings" early-exit. **Never** on the exception path (D-08: an unpinged run during a real failure is exactly what should trip the dead-man's-switch).
**Example:**
```python
# Source: https://healthchecks.io/docs/http_api/ — GET/HEAD/POST all accepted;
# plain success ping is just the bare UUID URL, no suffix needed.
def healthcheck_ping(url: str | None) -> None:
    if not url:
        return
    try:
        requests.get(url, timeout=10)
    except Exception:
        pass  # best-effort — a monitoring ping must never break the run
```
```python
# sentinel.py call sites (illustrative — exact placement is planner's call):
if today.weekday() >= 5 or (holiday := holidays.is_trading_holiday(today))[0]:
    healthcheck_ping(env.get("HEALTHCHECK_URL"))
    return 0
...
notify.send(env["TELEGRAM_TOKEN"], env["TELEGRAM_CHAT_ID"], message)
healthcheck_ping(env.get("HEALTHCHECK_URL"))
return 0
```

### Pattern 3: GHA cron + workflow_dispatch + concurrency

**What:** Three `schedule:` cron entries (one per run time), `workflow_dispatch` with no required inputs, a `concurrency` block to serialize overlapping runs, `permissions: contents: write` at workflow level.
**When to use:** Always — this is the whole workflow trigger/guard surface for this phase.
**Example:**
```yaml
# .github/workflows/sentinel.yml
# Source: docs.github.com/actions (schedule event, concurrency) — verified live
name: Groww Sentinel

on:
  schedule:
    # 03:30 UTC = 09:00 IST (pre-open), Mon-Fri
    - cron: "30 3 * * 1-5"
    # 07:00 UTC = 12:30 IST (midday), Mon-Fri
    - cron: "0 7 * * 1-5"
    # 10:00 UTC = 15:30 IST (close), Mon-Fri
    - cron: "0 10 * * 1-5"
  workflow_dispatch: {}

concurrency:
  group: groww-sentinel-run
  cancel-in-progress: false

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

      - name: Run Sentinel
        run: python -m sentinel
        env:
          GROWW_API_KEY: ${{ secrets.GROWW_API_KEY }}
          GROWW_TOTP_SEED: ${{ secrets.GROWW_TOTP_SEED }}
          TELEGRAM_TOKEN: ${{ secrets.TELEGRAM_TOKEN }}
          TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
          GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
          HEALTHCHECK_URL: ${{ secrets.HEALTHCHECK_URL }}
        # NOTE: no `|| true` here — a non-zero exit must fail the job (NOTIFY-04/D-07)

      - name: Commit updated state.json
        uses: stefanzweifel/git-auto-commit-action@v5
        with:
          commit_message: "chore: update state.json [skip ci]"
          file_pattern: state.json
        # If org policy blocks the default GITHUB_TOKEN (D-05), swap in:
        #   with: { ..., commit_options: '' }
        # and add `token: ${{ secrets.STATE_PAT }}` to actions/checkout above.
```

### Anti-Patterns to Avoid

- **`run: python -m sentinel || true`:** Masks the process exit code, silently defeating NOTIFY-04/D-07 — GitHub would show a green check even on a real auth/fetch failure.
- **Cron in IST intuition (`30 8 * * 1-5`) instead of converted UTC:** Fires 5.5 hours off with no error — the job "succeeds," you just get the wrong-time message and don't notice for a while (Pitfall 8 in `research/PITFALLS.md`).
- **Workflow-level `if:` for holiday/weekend skip:** Can't see NSE's calendar (only `github.event.schedule`/`github.event_name`), and diverges from `workflow_dispatch` behavior — keep this in Python (CONTEXT.md Established Patterns already mandates this).
- **healthchecks.io "Simple" (period+grace) schedule mode for a weekdays-only job:** A simple period/grace check has no concept of "weekend gap" — a Friday-to-Monday gap of ~65 hours will look "late" to a naive period-based check unless the grace window is set absurdly wide (which then also delays real Monday-morning-miss alerts). Use the **Cron schedule mode** instead (see Common Pitfalls).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|--------------|-----|
| Committing a generated file back to the repo | Raw `git add`/`commit`/`push` shell steps | `stefanzweifel/git-auto-commit-action@v5` | Handles "nothing changed, skip commit" idempotency, git identity config, and push conflict edge cases that a hand-rolled 3-line shell block gets subtly wrong (already called out in `research/STACK.md`/`PITFALLS.md`) |
| Dead-man's-switch / missed-cron detection | A second GHA workflow that checks "did the first one run" | healthchecks.io | A monitor that lives in the same platform (GitHub Actions) as the thing it's monitoring can't detect "GitHub Actions itself didn't fire" — must be external by construction (D-08's own stated rationale) |
| Weekday-aware schedule-miss detection | Home-rolled "did today's ping come in, accounting for weekends" logic | healthchecks.io's built-in **Cron schedule mode** (accepts a real cron expression + timezone) | The service already solves "this check only expects pings on a cron schedule, don't alert on the naturally-quiet gaps" — reinventing it with a Simple period/grace check requires manually reasoning about the weekend gap, which is exactly the kind of off-by-a-day bug this feature exists to prevent |

**Key insight:** Every component in this phase (state-commit, weekday-aware monitoring) has a purpose-built, free, well-maintained tool — the only genuinely custom code is the ~15-line `holidays.py` data table and the ~5-line ping wrapper, both correctly scoped as "too small/specific to be worth a dependency."

## Common Pitfalls

### Pitfall 1: `stefanzweifel/git-auto-commit-action@v5` is locked but not current

**What goes wrong:** CONTEXT.md D-04 locks `@v5`; the action is currently on `@v7.2.0`. `@v5` still resolves (verified live against the GitHub tags API) and will keep working, but it won't receive new bug fixes or security patches going forward.
**Why it happens:** The locked decision predates this research pass; pinning a major-version tag is normal practice, but "locked" doesn't mean "still current."
**How to avoid:** Ship with `@v5` as locked (don't silently override a locked decision), but flag this explicitly to the user as a zero-risk, no-rush follow-up (bump to `@v7` in a future maintenance pass) — see Assumptions Log.
**Warning signs:** None operationally — this is a "known, accepted" gap, not a functional risk today.

### Pitfall 2: healthchecks.io "Simple" schedule mode false-alarms on weekend gaps

**What goes wrong:** If the check is configured with a plain Period + Grace Time (the default for a new check) rather than a Cron-expression schedule, the ~65-hour Friday-close-to-Monday-pre-open gap will exceed any reasonable grace window sized for the ~3-hour weekday gaps, causing a false "down" alert every single weekend.
**Why it happens:** Simple mode is the default UI flow when creating a new check; Cron mode requires deliberately switching the schedule type.
**How to avoid:** At setup, switch the check to **Cron schedule mode**, enter a cron expression matching the three run times (e.g. `30 3,7,10 * * 1-5` is not valid cron for three distinct hour:minute pairs — use the three separate times or `30 3 * * 1-5`/`0 7,10 * * 1-5` style, or simplest: configure it with the loosest reasonable single daily grace and rely on the Cron mode's per-scheduled-time grace, whichever the dashboard UI supports at setup time — verify the exact multi-time cron syntax the healthchecks.io UI accepts when configuring) `[CITED: healthchecks.io/docs/configuring_checks/]`.
**Warning signs:** A "down" alert email arriving reliably every Saturday morning.

### Pitfall 3: `contents: write` blocked by org policy — verify before trusting the cron

Carried directly from `research/PITFALLS.md` Pitfall 3 (unchanged, still the top operational risk this phase): default `GITHUB_TOKEN` may be read-only under `ThePubDoc` org policy regardless of the workflow's own `permissions:` block. **Must** be verified with a real `workflow_dispatch` run producing a visible new commit to `state.json` before the cron is trusted unattended. If blocked, the PAT fallback (`STATE_PAT`, D-05/D-09) is the documented escape hatch — set it up proactively rather than discovering the failure on the first real cron-triggered run.

### Pitfall 4: 60-day workflow auto-disable (new finding this phase)

**What goes wrong:** GitHub Actions automatically disables a scheduled workflow in a repository after **60 days of repository inactivity** (no commits) `[CITED: docs.github.com — schedule event documentation]`.
**Why it happens:** GitHub's anti-abuse measure for stale repos with cron jobs nobody's using.
**How to avoid:** Not a practical risk here — the state-commit step itself pushes a commit on every successful weekday run, keeping the repo active. Worth knowing only as a "why did the cron stop firing" diagnostic if the state-commit step (Pitfall 3) is silently broken for 60+ days straight — the two failures would then compound (state never persists → repo goes quiet → GHA disables the schedule → total silence, caught only by the external healthchecks.io monitor).
**Warning signs:** Workflow shows as "disabled" in the Actions tab (distinct from "failed").

### Pitfall 5–9 (carried forward, unchanged)

Cron best-effort delay/drift, UTC/IST conversion mistakes, the "alerter has no watcher" meta-risk, and concurrent/double-run snapshot corruption are all already fully documented in `research/PITFALLS.md` (Pitfalls 3, 4, 7, 8, 9) and remain accurate for this phase without new findings — this phase's job is to implement the mitigations already prescribed there (non-top-of-hour minute ✓ already in D-02, `concurrency:` group ✓ D-06, external healthchecks.io ✓ D-08).

## Code Examples

### Full workflow YAML

See Architecture Patterns → Pattern 3 above — that example is the complete, ready-to-adapt workflow file.

### `holidays.py` full module

See Architecture Patterns → Pattern 1 above.

### healthcheck ping helper

See Architecture Patterns → Pattern 2 above.

### Minimal test shape for `holidays.py` (per project's TEST-01/02 pattern and pytest convention)

```python
# tests/test_holidays.py — AAA structure, matches existing test style in this repo
from datetime import date
import holidays

def test_republic_day_2026_is_holiday():
    is_holiday, warning = holidays.is_trading_holiday(date(2026, 1, 26))
    assert is_holiday is True
    assert warning is None

def test_ordinary_weekday_2026_is_not_holiday():
    is_holiday, warning = holidays.is_trading_holiday(date(2026, 1, 27))
    assert is_holiday is False
    assert warning is None

def test_date_past_last_seeded_year_warns():
    is_holiday, warning = holidays.is_trading_holiday(date(2028, 1, 1))
    assert warning is not None
    assert "2028" in warning
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|-------------------|---------------|--------|
| `git-auto-commit-action@v5` (locked, D-04) | `@v7.2.0` is the current major/latest | v6.0.0 and v7.0.0 tags exist on the upstream repo (verified) | `@v5` still resolves and functions — no forced-upgrade risk today, but the version pin is stale relative to upstream; safe, no-rush follow-up |
| Hourly cron (Phase-2 D-01, deferred) | 3×/weekday (D-01, this phase) | Locked in CONTEXT.md this phase | Fewer commits/API calls, same coverage of the moments that matter (pre-open/midday/close) |

**Deprecated/outdated:** None specific to this phase's tool choices — everything recommended here is the current standard as of this research date.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|-----------------|
| A1 | NSE 2026 holiday date list (15 dates) is complete and correct | `holidays.py` example / Standard Stack | If wrong, a real trading day is skipped (missed digest — low severity, self-correcting next run) or a real holiday isn't skipped (wasted run, still low severity — no digest content changes, just noise); **recommend a one-time manual cross-check against NSE's own official circular before first use**, since the direct nseindia.com fetch timed out during this research pass and both sources used are brokerage secondary sources, not NSE primary |
| A2 | 2027 NSE holidays are genuinely not yet published anywhere as of 2026-07-10 | `holidays.py` LAST_SEEDED_YEAR | If a 2027 list actually exists somewhere not surfaced by this search pass, the warn-path fires unnecessarily starting 2027-01-01 — low severity (loud warning, not silent wrong), self-correcting once the list is added |
| A3 | healthchecks.io's Cron schedule mode is available on the free "Hobbyist" tier (not a paid-only feature) | Common Pitfalls #2 | If it's actually gated to a paid tier, the Simple period/grace mode must be used instead with a manually-reasoned grace window wide enough to span the weekend gap without missing a real Monday-morning failure — verify in the dashboard UI at setup time, this is a 2-minute check |
| A4 | The multi-time-of-day cron syntax accepted by healthchecks.io's Cron mode UI supports three distinct HH:MM pairs per weekday cleanly | Common Pitfalls #2 | If the UI only accepts a single daily cron expression, either run three separate checks (one per time slot, all pinged independently) or fall back to Simple mode with a carefully-sized grace window — verify in the dashboard at setup time |

**If this table is empty:** N/A — see above; all four items are low-severity, self-correcting, or a one-time 2-minute verification at setup — none block implementation.

## Open Questions

1. **Does `ThePubDoc` org actually restrict the default `GITHUB_TOKEN`'s `contents: write`?**
   - What we know: GitHub's own docs confirm org-level defaults can force read-only and disable the permissive per-repo override entirely.
   - What's unclear: Whether this specific org has that restriction active — CONTEXT.md D-05 already correctly scopes this as "resolve empirically, don't pre-assume."
   - Recommendation: First real workflow run should be a `workflow_dispatch`, checked for an actual new `state.json` commit, before the cron schedule is relied upon unattended. If blocked, wire the `STATE_PAT` fallback immediately (D-09 already provisions the secret name).

2. **Exact healthchecks.io multi-time cron syntax in the dashboard UI**
   - What we know: The service supports a genuine cron-expression + timezone + grace-time schedule mode.
   - What's unclear: Whether three distinct daily HH:MM times can be expressed as a single cron check, or whether three separate healthchecks.io checks (one per run-time) is the cleaner setup.
   - Recommendation: At setup time, try a single check with `30 3 * * 1-5` / `0 7 * * 1-5` / `0 10 * * 1-5` as three OR'd cron fields if the UI supports a list; if not, create three checks and ping all three from the same `healthcheck_ping()` call site (harmless — an extra ping to an unrelated check simply gets ignored) — or simplest: one check per run, keyed by which HH:MM the process observes at runtime. This is a 10-minute dashboard task, not a code design decision.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|--------------|-----------|---------|----------|
| GitHub Actions (`ubuntu-latest`) | All of RUN-01..05 | ✓ (platform-provided) | n/a | — |
| healthchecks.io (external SaaS) | NOTIFY-05 | ✓ (public service, free tier confirmed sufficient) | n/a | If the service becomes unavailable long-term: any cron-aware ping-based monitor (Cronitor, Better Uptime) is a drop-in URL swap — the ping call itself is provider-agnostic |
| `stefanzweifel/git-auto-commit-action` (GitHub Marketplace Action) | RUN-03 | ✓ (tags v5.x through v7.x all resolve) | `@v5` locked | Raw git shell steps (explicitly rejected in `research/STACK.md` — reinvents a solved problem) |
| Fine-grained PAT (`STATE_PAT`) | RUN-03/D-05 fallback only | Not yet created — must be generated in GitHub UI if D-05's org restriction proves real | n/a | N/A — this *is* the fallback; if it's also unavailable, the org admin would need to grant an exception |

**Missing dependencies with no fallback:** None — every dependency in this phase has either a working default or an already-designed fallback (PAT for the token restriction).

**Missing dependencies with fallback:** `STATE_PAT` doesn't exist yet; create only if the `workflow_dispatch` verification (Open Question 1) shows the default token is blocked.

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|----------------|---------|--------------------|
| V2 Authentication | No (no new auth surface this phase — Groww TOTP auth is Phase 1's concern) | — |
| V3 Session Management | No | — |
| V4 Access Control | Yes — repo push access | `permissions: contents: write` scoped at workflow level (least-privilege: no other permission scopes granted); PAT fallback scoped to `contents: write` on this one repo only, per D-09/`research/STACK.md`'s existing guidance |
| V5 Input Validation | Marginal — `HEALTHCHECK_URL` is operator-supplied, not user input | Treat as a trusted secret like the other three; no additional validation needed beyond "is it set" (matches existing `validate_secrets` pattern in `sentinel.py`, which is optional-secret-aware already for `GEMINI_API_KEY`) |
| V6 Cryptography | No | — |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|------------------------|
| Secret leakage via exception string reaching a Telegram message or GHA log | Information Disclosure | Already implemented in `sentinel.py`'s `_redact()` helper (Phase 1/2) — this phase adds no new secret-bearing exception paths, since `healthcheck_ping()` is a bare best-effort `try/except: pass` with no message construction from the exception at all |
| Overprivileged PAT if the D-05 fallback is used carelessly | Elevation of Privilege | Use a fine-grained PAT scoped to exactly this one repo and exactly `contents: write` — never a classic PAT with broad `repo` scope (already the documented guidance in `research/PITFALLS.md` Security Mistakes table) |
| A leaked `HEALTHCHECK_URL` letting an attacker suppress real alerts by pinging "success" on your behalf | Tampering / Repudiation | Low severity for a personal single-user monitor (worst case: a stolen URL lets someone silence your dead-man's-switch, not access any financial data or account) — store as a GitHub encrypted secret like the others (D-09), no special handling needed beyond that |

## Sources

### Primary (HIGH confidence)

- https://docs.github.com/en/actions/using-workflows/events-that-trigger-workflows#schedule — cron syntax, "avoid top-of-hour" guidance, 60-day auto-disable, best-effort delay statement (fetched directly, official GitHub docs)
- https://api.github.com/repos/stefanzweifel/git-auto-commit-action/tags — direct GitHub API call confirming `v5`, `v5.0.0`–`v5.2.0`, `v6.x`, `v7.x` all exist as resolvable tags
- https://healthchecks.io/docs/http_api/ — ping URL formats (`/start`, `/fail`, `/<exit-status>`), supported HTTP methods (HEAD/GET/POST), rate-limit note (max 5 pings/min)
- GitHub Actions concurrency documentation (`docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency`) — `group`/`cancel-in-progress` syntax
- GitHub org-level workflow permissions documentation (`docs.github.com` + `github.blog/changelog/2021-04-20-github-actions-control-permissions-for-github_token`) — confirms org defaults can force read-only and disable the permissive override

### Secondary (MEDIUM confidence)

- https://zerodha.com/marketintel/holiday-calendar/ and https://cleartax.in/s/nse-holidays-2026 — NSE 2026 holiday date list, cross-checked identical across both (neither is NSE's own primary site; nseindia.com fetch timed out during this research pass — recommend a one-time manual cross-check, see Assumptions Log A1)
- https://healthchecks.io/docs/configuring_checks/ and healthchecks.io blog post on cron-expression monitoring — Cron schedule mode (cron expression + timezone + grace time) exists and is documented; free-tier availability of this specific mode not explicitly confirmed in fetched pages (see Assumptions Log A3)
- Pricing comparisons (drumbeats.io, toolradar.com) cross-checked for healthchecks.io free tier (20 checks, 3 team members, 100 log entries/check) — third-party aggregators, not healthchecks.io's own pricing page directly

### Tertiary (LOW confidence)

- 2027 NSE holiday non-publication — absence-of-evidence from WebSearch only; genuinely unconfirmable until NSE actually publishes (expected ~December 2026)

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new packages, all tooling choices already locked/verified in prior phase research plus this pass's live tag/API checks
- Architecture: HIGH — every workflow YAML element (schedule, concurrency, permissions, commit-back action) is directly sourced from official GitHub docs or a live API check
- Pitfalls: MEDIUM-HIGH — carried-forward pitfalls are HIGH (already well-documented); the two new findings (git-auto-commit-action version currency, healthchecks.io cron-mode weekend handling) are MEDIUM pending the two Open Questions' 2-minute dashboard verifications

**Research date:** 2026-07-10
**Valid until:** 2026-08-09 (30 days — stable domain, but re-verify the NSE holiday list against NSE's own site before relying on it unattended, and re-check `git-auto-commit-action` currency if this phase's implementation slips past a few months)
