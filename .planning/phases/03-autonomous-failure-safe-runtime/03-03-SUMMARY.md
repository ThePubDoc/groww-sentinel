# Plan 03-03 Summary — First-Dispatch Verification (human-verify)

**Status:** Complete — verified live on GitHub Actions 2026-07-10.
**Requirements:** RUN-03, RUN-05, NOTIFY-04, NOTIFY-05

## What was verified (real infra, not local mocks)

The repo was created (`ThePubDoc/groww-sentinel`, private) and pushed, then a
first `workflow_dispatch` run completed **green (exit 0)**:

| Check | Result |
|-------|--------|
| Workflow triggers (`workflow_dispatch`, RUN-05) | ✅ dispatched + ran |
| `python -m sentinel` runs unattended in CI | ✅ all steps green |
| Telegram digest sent (NOTIFY-04 success path) | ✅ user confirmed on phone |
| state.json committed back (RUN-03) | ✅ commit `973b962 chore: update state.json [skip ci]`, 7752 bytes, by the `ThePubDoc` bot |
| Default `GITHUB_TOKEN` `contents: write` under the org (D-05) | ✅ **works — no PAT/STATE_PAT needed** (the long-standing org-token caveat resolved empirically in our favour) |
| 3×/weekday cron armed (RUN-01) | ✅ configured; will fire on schedule |
| Concurrency guard (RUN-04) | ✅ in workflow |

## Resolved open questions

- **D-05 (org token):** the default token pushes state.json fine — the `STATE_PAT` fallback path stays as a documented, unused safety net.
- **Push caveat (PROJECT.md):** confirmed real — the `ThePubDoc` gh account lacked `workflow` scope and the initial push of `.github/workflows/sentinel.yml` was rejected; resolved by `gh auth refresh -s workflow`. Documented for future workflow edits.

## Follow-up (non-blocking, operational)

- **NOTIFY-05 dead-man's-switch is dormant by config:** `healthcheck_ping` code is built + unit-tested and fires on every clean exit, but `HEALTHCHECK_URL` was not set as a repo secret this session, so the external monitor is inactive. A missed cron is therefore not yet alertable (GitHub only emails on failed runs, not never-fired ones). **To activate:** create a healthchecks.io check in cron-schedule mode (weekday 3×/day) and add its ping URL as the `HEALTHCHECK_URL` repo secret — no code change needed.
- `git-auto-commit-action@v5` works; upstream is `@v7` — zero-risk bump someday.
- NSE 2026 holiday dates came from two brokerage sources; cross-check against NSE's own circular once. 2027 dates get added when NSE publishes (the warn-past-2026 guard covers the gap).

## Evidence
Green run + `973b962` present in git history; `state.json` on disk has 34 real peaks, 1 snapshot, 5 sentiment cache entries. Full suite 130 passed.
