---
phase: 03-autonomous-failure-safe-runtime
plan: 02
subsystem: infra
tags: [github-actions, cron, ci-cd, git-auto-commit-action, healthchecks-io]

requires:
  - phase: 03-autonomous-failure-safe-runtime plan 01
    provides: holidays.py market-closed check + notify.healthcheck_ping wired into sentinel.py
provides:
  - .github/workflows/sentinel.yml -- 3x/weekday UTC cron + workflow_dispatch, serialized via concurrency group, contents:write permission, unmasked python -m sentinel run, state.json commit-back via git-auto-commit-action@v5
  - README.md -- secrets table, healthchecks.io Cron-schedule-mode setup, first-dispatch verification runbook, STATE_PAT org-token fallback path
affects: [deployment, ci-cd, phase-03-plan-03]

tech-stack:
  added: []
  patterns: ["CI-only glue (cron/secrets/commit-back) lives entirely in the workflow YAML; all testable logic (holiday check, healthcheck ping placement) already lives in sentinel.py/holidays.py per established pure-core/impure-shell pattern -- no new Python this plan"]

key-files:
  created:
    - .github/workflows/sentinel.yml
    - README.md
  modified: []

key-decisions:
  - "Workflow YAML follows 03-RESEARCH Pattern 3 verbatim: three separate cron entries (30 3 * * 1-5 / 0 7 * * 1-5 / 0 10 * * 1-5) rather than a combined expression, since standard cron syntax can't express three distinct HH:MM pairs in one line"
  - "Avoided writing the literal substring '|| true' inside an explanatory YAML comment -- it would false-positive the plan's own negative verify grep for exit-code masking; reworded the comment instead of weakening the check"
  - "STATE_PAT fallback documented as a commented block in the workflow (checkout step) plus a full runbook section in README, per D-05 -- not pre-wired active, since the org-token restriction must be verified empirically on first workflow_dispatch"

patterns-established:
  - "CI trigger/guard surface (schedule, concurrency, permissions) fully declarative in the workflow file; no workflow-level `if:` holiday logic -- that stays in Python per 03-CONTEXT's established pattern and 03-RESEARCH's anti-pattern warning"

requirements-completed: [RUN-01, RUN-03, RUN-04, RUN-05, NOTIFY-04, NOTIFY-05]

coverage:
  - id: D1
    description: "Workflow fires 3x/weekday (UTC crons for 09:00/12:30/15:30 IST) plus on-demand workflow_dispatch"
    requirement: "RUN-01"
    verification:
      - kind: other
        ref: "grep -c 'cron:' .github/workflows/sentinel.yml (excl. comments) == 3; grep 'workflow_dispatch' present"
        status: pass
    human_judgment: false
  - id: D2
    description: "concurrency group with cancel-in-progress:false serializes overlapping runs so state.json can't be clobbered"
    requirement: "RUN-04"
    verification:
      - kind: other
        ref: "grep 'cancel-in-progress: false' .github/workflows/sentinel.yml"
        status: pass
    human_judgment: false
  - id: D3
    description: "state.json is committed back to the repo each run via git-auto-commit-action@v5, scoped to state.json only, with [skip ci], under a contents:write permission"
    requirement: "RUN-03"
    verification:
      - kind: other
        ref: "grep 'git-auto-commit-action@v5' and 'contents: write' (non-comment) in .github/workflows/sentinel.yml"
        status: pass
    human_judgment: true
    rationale: "The GitHub org-token restriction (D-05) can only be confirmed by an actual workflow_dispatch run producing a real state.json commit -- static grep proves the YAML declares the right permission, not that ThePubDoc org policy honors it. This is explicitly deferred to the first live workflow_dispatch (03-03 checkpoint)."
  - id: D4
    description: "A non-zero exit from python -m sentinel fails the GitHub run -- no exit-code masking"
    requirement: "NOTIFY-04"
    verification:
      - kind: other
        ref: "negative grep for literal '|| true' in .github/workflows/sentinel.yml returns clean"
        status: pass
    human_judgment: false
  - id: D5
    description: "README documents all secrets, healthchecks.io Cron-schedule-mode setup (not Simple period/grace), and the first-workflow_dispatch verification runbook including the STATE_PAT fallback"
    requirement: "NOTIFY-05"
    verification:
      - kind: other
        ref: "grep HEALTHCHECK_URL, STATE_PAT, 'cron schedule' (case-insens), workflow_dispatch, GROWW_API_KEY in README.md"
        status: pass
    human_judgment: false

duration: 12min
completed: 2026-07-10
status: complete
---

# Phase 3 Plan 2: GitHub Actions Runtime + Deploy Runbook Summary

**`.github/workflows/sentinel.yml` firing 3x/weekday via UTC cron plus workflow_dispatch, serialized by a concurrency group, committing state.json back with git-auto-commit-action@v5 under a never-masked exit code, paired with a README runbook covering secrets, healthchecks.io Cron-mode setup, and first-dispatch verification.**

## Performance

- **Duration:** 12 min
- **Started:** 2026-07-10T09:04:00Z (approx, per plan handoff)
- **Completed:** 2026-07-10T09:16:00Z
- **Tasks:** 2
- **Files modified:** 2 (both new)

## Accomplishments
- CI trigger/guard surface fully declared: 3 weekday UTC crons (03:30/07:00/10:00 = 09:00/12:30/15:30 IST) + `workflow_dispatch`, a `groww-sentinel-run` concurrency group with `cancel-in-progress: false`, and workflow-level `permissions: contents: write`.
- Run step invokes `python -m sentinel` with all 6 secrets (4 required + `GEMINI_API_KEY` + `HEALTHCHECK_URL`) injected via `env:`, with no exit-suppressing shell suffix -- a real failure turns the GitHub run red.
- `stefanzweifel/git-auto-commit-action@v5` commits `state.json` only, with a `[skip ci]` message, plus a commented `STATE_PAT` fallback directly in the checkout step for the org-token caveat.
- README deploy runbook: secrets table (7 entries with sources), healthchecks.io Cron-schedule-mode setup (explicitly warning against Simple period/grace due to the weekend-gap false-alarm), and a first-`workflow_dispatch` verification checklist covering digest arrival, the state.json commit, the healthcheck ping, and the STATE_PAT escape hatch.

## Task Commits

Each task was committed atomically:

1. **Task 1: .github/workflows/sentinel.yml** - `3513746` (feat)
2. **Task 2: README.md deploy runbook** - `fdd6ae2` (docs)

**Plan metadata:** (this commit)

## Files Created/Modified
- `.github/workflows/sentinel.yml` - GHA workflow: 3x weekday cron + dispatch, concurrency, contents:write, setup-python(pip cache), unmasked sentinel run, state.json commit-back with STATE_PAT fallback note
- `README.md` - Deploy runbook: project one-liner + "not investment advice", secrets table, healthchecks.io Cron-mode setup, first-dispatch verification, org-token/PAT fallback, holiday-list maintenance note

## Decisions Made
- Followed 03-RESEARCH Pattern 3 verbatim for the workflow YAML (exact cron strings, concurrency block, step ordering) rather than improvising an alternative structure.
- Reworded an explanatory YAML comment that originally contained the literal substring `|| true` (describing what NOT to do) because it would have false-tripped the plan's own anti-masking negative-grep verify step -- the comment now describes the requirement without using the banned literal string. This is a wording-only change; the actual run step still has zero exit-suppressing suffix.
- Left `STATE_PAT`/`token:` wiring commented-out rather than active, per D-05's "resolve empirically" instruction -- the org-token restriction is unconfirmed until a real `workflow_dispatch` run is observed (deferred to 03-03).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] YAML comment text collided with its own verify grep**
- **Found during:** Task 1 verification
- **Issue:** The workflow comment explaining "no exit-code masking" literally contained the string `|| true` (as prose, not as executable YAML), which is exactly the substring the task's own negative-grep verify checks for. This made the automated verify fail even though the actual `run:` step had no masking suffix.
- **Fix:** Reworded the comment to describe the requirement in prose without using the literal `|| true` string.
- **Files modified:** `.github/workflows/sentinel.yml`
- **Verification:** Re-ran the full verify command set; all 8 checks (YAML parse, 3-cron count, workflow_dispatch, contents:write, cancel-in-progress:false, python -m sentinel, git-auto-commit-action@v5, no-mask negative grep) pass clean.
- **Committed in:** `3513746` (Task 1 commit -- fixed before commit, not a separate commit)

---

**Total deviations:** 1 auto-fixed (1 bug)
**Impact on plan:** Comment wording only; no functional change to the workflow's actual masking behavior. No scope creep.

## Issues Encountered
None beyond the deviation above.

## User Setup Required
External services require manual configuration before the cron can run unattended -- see README.md "Secrets" and "First run / verification" sections:
- Add 4 required + up to 3 optional GitHub encrypted repo secrets (GROWW_API_KEY, GROWW_TOTP_SEED, TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, GEMINI_API_KEY, HEALTHCHECK_URL, STATE_PAT).
- Create and configure a healthchecks.io check in Cron schedule mode.
- Trigger a manual `workflow_dispatch` and confirm digest delivery, the state.json commit, and the healthcheck ping -- this is also exercised as a human checkpoint in plan 03-03.

## Next Phase Readiness
- The workflow file and runbook are complete and committed; no code changes were needed (full 130-test suite still green, untouched).
- Plan 03-03 owns the actual live verification (first `workflow_dispatch`, confirming `contents: write` works or wiring `STATE_PAT`) -- this plan intentionally stops at "declared correctly," per D-05's empirical-resolution instruction.
- No blockers for 03-03.

---
*Phase: 03-autonomous-failure-safe-runtime*
*Completed: 2026-07-10*

## Self-Check: PASSED

- FOUND: .github/workflows/sentinel.yml
- FOUND: README.md
- FOUND: commit 3513746
- FOUND: commit fdd6ae2
