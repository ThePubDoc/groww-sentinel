# Architecture Research

**Domain:** Headless scheduled data-pipeline job (fetch → pure decision logic → notify), run on GitHub Actions cron, no server, no database.
**Researched:** 2026-07-09
**Confidence:** HIGH (pure-core/imperative-shell, cron-job idempotency, and GitHub Actions scheduling are well-established, low-ambiguity patterns for this scale; the only MEDIUM-confidence item is `growwapi` SDK method surface, which is a phase-time verification, not an architecture question).

## Standard Architecture

### System Overview

```
┌──────────────────────────────────────────────────────────────────┐
│                    GitHub Actions (cron, weekday)                 │
│  1. checkout repo  2. setup python  3. run sentinel.py  4. commit │
└───────────────────────────────┬────────────────────────────────────┘
                                 │ env: 4 secrets
                                 ▼
┌──────────────────────────────────────────────────────────────────┐
│                          sentinel.py (shell)                      │
│  validate secrets → holiday/weekday guard → orchestrate → catch   │
└───┬─────────────────────┬──────────────────────┬──────────────────┘
    │ I/O                 │ pure                 │ I/O
    ▼                     ▼                      ▼
┌─────────┐         ┌──────────┐            ┌──────────┐
│broker.py│  dicts → │ rules.py │ → flags,   │notify.py │
│(fetch)  │          │(compute) │   new_state│(format+  │
│         │          │no I/O    │            │  send)   │
└─────────┘         └──────────┘            └──────────┘
    │                     ▲    │                   │
    │ reads                │    │ writes            │ sends
    ▼                     │    ▼                   ▼
 Groww TradeAPI      state.json (read)      state.json (write)   Telegram API
 config.yaml (read)                          (committed by workflow, not python)
```

### Component Responsibilities

| Component | Responsibility | Typical Implementation |
|-----------|----------------|-------------------------|
| `broker.py` | Auth + fetch holdings + fetch LTPs. Boundary to the outside world on the *read* side. | `growwapi` SDK client wrapped in 2-3 functions returning plain `dict`/`list[dict]` — never SDK objects, never custom classes. Raises plain exceptions on failure; does not catch. |
| `rules.py` | All decision logic: peak tracking, flag thresholds, snapshot bookkeeping. | One pure function `evaluate(holdings, config, state, today) -> (flags, new_state)`. No `datetime.now()`, no file/network access inside — `today` is passed in so tests are deterministic. |
| `notify.py` | Format the digest text + push it. Boundary to the outside world on the *write* side. | `format_digest(flags, portfolio, is_friday) -> str` (pure, easy to snapshot-test) + `send(message: str) -> None` (I/O, thin wrapper over Telegram Bot HTTP API). |
| `sentinel.py` | Wire the above in order, own all top-level error handling, own the process exit code. | A single `main()` with try/except around the fetch step specifically (that's where failures are expected) and a bare top-level guard for anything else. |
| `config.yaml` | Static user input: which bucket (`core`/`tactical`) each symbol belongs to. | Loaded read-only each run; never written by the app. |
| `state.json` | Only piece of mutable app state. Peak price + recent daily snapshots per symbol. | Loaded read-only by `sentinel.py`, transformed by `rules.py` (pure), written once by `sentinel.py`. |
| GitHub Actions workflow | Scheduling, secrets injection, committing `state.json` back. | One `.yml` file. Git commit-back is a shell step *after* the Python process exits — not inside Python. |

This is a straightforward **pure-core / imperative-shell** split, and the spec's 4-module boundary is correct as proposed. The one addition worth making explicit: `rules.py` must not call `date.today()` or read env/files itself — the caller (`sentinel.py`) computes "today" once (in IST) and passes it in. That's what makes the money-path function trivially unit-testable with hand-built fixtures, and it's also what makes the idempotency story (below) work cleanly.

## Recommended Project Structure

```
groww-sentinel/
├── sentinel.py          # orchestrator + top-level error handling (~100-150 lines)
├── broker.py             # Groww auth + fetch (holdings, LTPs) — I/O, thin
├── rules.py               # pure evaluate() + named threshold constants
├── notify.py              # format_digest() [pure] + send() [I/O]
├── holidays.py            # static NSE holiday date list + is_trading_day()
├── config.yaml             # user-owned: symbol -> core/tactical tags
├── state.json               # app-owned: committed each run, seeded on first run
├── tests/
│   ├── test_rules.py        # AAA, one test per flag path — the money path
│   └── test_notify.py       # format_digest() snapshot-style assertions
└── .github/workflows/
    └── sentinel.yml          # cron schedule + secrets + commit-back step
```

### Structure Rationale

- **Flat, no `src/` package layout:** this is a ~5-file script, not an application. A nested package adds import-path ceremony for zero benefit at this size. Revisit only if the file count doubles.
- **`holidays.py` is its own tiny module, not inlined in `sentinel.py`:** it's the one piece of "calendar data" that gets edited once a year independent of any logic change — isolating it means a yearly holiday-list update touches one file with no logic in it.
- **`tests/` mirrors the pure/impure split:** `rules.py` gets full unit coverage (it's the money path); `broker.py` gets no live-API tests (mock the SDK boundary only if it earns its keep — for a single personal cron job, a manual dry-run against the real sandbox is arguably enough; write `test_notify.py` for `format_digest` because that's pure and cheap to assert on).

## Architectural Patterns

### Pattern 1: Pure-core / imperative-shell

**What:** All *decisions* (flags, peak updates, snapshot bookkeeping) live in one pure function with no I/O. All I/O (network, filesystem, clock) lives in thin wrapper functions at the edges, called only from `sentinel.py`.
**When to use:** Any job where "what should happen" is complex/testable and "how it talks to the world" is boilerplate. Exactly this project's shape.
**Trade-offs:** Slightly more plumbing (pass `today`, pass loaded config/state as plain dicts instead of reaching for globals) — worth it because it makes `rules.py` testable with zero mocks, which is the one place a bug is expensive (wrong STOP HIT / wrong AVG CANDIDATE).

**Example:**
```python
# rules.py
from datetime import date

AVG_DROP_THRESHOLDS = (0.10, 0.20, 0.30)
TRAIL_WATCH_PCT_BELOW_PEAK = 0.20
TRIM_WEIGHT_PCT = 0.10
BOOK_50_GAIN_PCT = 0.25
STOP_HIT_DROP_PCT = 0.12
STOP_HIT_PCT_BELOW_PEAK = 0.15

def evaluate(
    holdings: list[dict],   # [{symbol, qty, avg_cost, ltp}, ...] — ltp may be None
    config: dict,           # {"RELIANCE": "core", ...}
    state: dict,            # prior state.json contents
    today: date,            # caller-supplied, IST calendar date
) -> tuple[list[dict], dict]:
    ...  # no clock calls, no file/network access — everything is a parameter
    return flags, new_state
```

### Pattern 2: Rebuild-not-merge state transition

**What:** `rules.py` builds `new_state` fresh from *current* `holdings` each run — it does not patch/merge the old `state` in place. For each currently held symbol, it looks up the old state entry (if any) to carry forward `peak_price` and the snapshot history; for any symbol *not* in current holdings, it simply omits it from `new_state`.
**When to use:** Whenever "state" is fully derivable from "current truth + limited history," which is the case here (holdings response is the source of truth for what's currently held).
**Trade-offs:** This single mechanism gets you pruning-on-exit and re-seed-on-rebuy for free, with no separate diff/prune step to write or test — see the State Design section below. The only cost is you must remember "old state is a lookup table, not a base to mutate," which is a one-line docstring away from being obvious.

### Pattern 3: Date-keyed idempotent snapshots

**What:** Every mutable record that accumulates over time (per-symbol daily snapshot, portfolio daily snapshot) is stored in a dict keyed by ISO date string (`"2026-07-09"`), not appended to a list. Writing "today's" entry always does `snapshots[today_str] = {...}` — a second run on the same day overwrites the same key instead of appending a duplicate.
**When to use:** Any daily-cron job that might legitimately run twice in one calendar day (manual re-trigger after a failure, `workflow_dispatch` re-run, GHA retry).
**Trade-offs:** Dict-keyed-by-date is marginally less compact in JSON than a list, and "oldest 7" pruning requires a sort-by-key-and-slice instead of a simple `list[-7:]` — both are one-liners, not a real cost.

## Data Flow

### Request Flow (single run)

```
GitHub Actions cron fires (weekday, ~08:30 IST)
    ↓
sentinel.py: validate 4 secrets present → exit 2 if not (see Secrets Validation)
    ↓
sentinel.py: is_trading_day(today)? → if holiday: notify "market closed", exit 0
    ↓
broker.py: pyotp.totp(seed) → groww login → fetch_holdings()
    │  on exception → notify.send("⚠️ fetch failed: <reason>") → exit 1
    ↓
holdings empty? → notify.send("no holdings"), exit 0
    ↓
broker.py: fetch_ltp(symbol) per held symbol
    │  per-symbol failure → ltp=None for that symbol, continue (not fatal)
    ↓
load config.yaml (read-only) + load state.json (seed {} if missing)
    ↓
rules.evaluate(holdings, config, state, today) → (flags, new_state)
    ↓
notify.format_digest(flags, portfolio_summary, is_friday) → message string
notify.send(message)
    ↓
write new_state.json to disk (sentinel.py, not rules.py)
    ↓
process exits 0
    ↓
[separate GHA workflow step] git diff state.json → if changed: commit + push
```

### Key Data Flows

1. **Holdings → flags:** `broker.py` hands `sentinel.py` plain dicts; `sentinel.py` merges in LTPs and hands the combined list to `rules.py` untouched by any formatting/business logic. `rules.py` never touches the network.
2. **State continuity:** `state.json` is the *only* channel carrying information from one run to the next (peaks, snapshot history). Everything else (holdings, LTP, config) is re-fetched/re-read from scratch every run — there is no in-memory cache to go stale.
3. **Failure → notification:** every failure path that has any hope of reaching Telegram (i.e., Telegram secrets are present) must still notify. Only a genuinely un-notifiable failure (Telegram secrets themselves missing, or Telegram API itself down) falls back to "log to stderr + non-zero exit," relying on the GHA run log as the last-resort channel.

## Concrete `state.json` Schema

```json
{
  "schema_version": 1,
  "symbols": {
    "RELIANCE": {
      "peak_price": 2950.5,
      "peak_set_date": "2026-06-20",
      "first_seen_date": "2026-05-01",
      "snapshots": {
        "2026-07-03": { "ltp": 2820.0, "qty": 10, "avg_cost": 2500.0, "value": 28200.0 },
        "2026-07-04": { "ltp": 2790.5, "qty": 10, "avg_cost": 2500.0, "value": 27905.0 },
        "2026-07-07": { "ltp": 2810.0, "qty": 10, "avg_cost": 2500.0, "value": 28100.0 },
        "2026-07-08": { "ltp": 2795.0, "qty": 10, "avg_cost": 2500.0, "value": 27950.0 },
        "2026-07-09": { "ltp": 2801.25, "qty": 10, "avg_cost": 2500.0, "value": 28012.5 }
      }
    }
  },
  "portfolio": {
    "snapshots": {
      "2026-07-08": { "value": 512340.0 },
      "2026-07-09": { "value": 514102.5 }
    }
  },
  "last_run": {
    "date": "2026-07-09",
    "status": "ok"
  }
}
```

**Design notes:**

- **`schema_version`:** one field, bumped only if the shape changes. Cheap insurance for a file that lives long enough to outlast the code that wrote it.
- **Snapshots keyed by `YYYY-MM-DD` (IST calendar date), not a list:** a double-run on the same day writes to the same key — that *is* the idempotency mechanism, no separate "did we already run today" check needed.
- **Bounded to ~7 entries per symbol:** enforced in `rules.py` at write time — `dict(sorted(snapshots.items())[-7:])` after inserting today's entry. Same for `portfolio.snapshots`. This is a one-line prune, not a background job.
- **Pruning symbols no longer held:** `new_state["symbols"]` is built by iterating *current* `holdings` only (see Pattern 2 above) — a symbol absent from this run's holdings is simply never written into `new_state`, so it silently drops out. No separate "delete stale symbols" step exists or is needed.
- **Reset peak on exit, re-seed on rebuy:** falls out of the same mechanism — if `RELIANCE` is sold and later rebought, the rebuy run finds no `RELIANCE` key in the (pruned) old state, so it's treated as first-seen: `peak_price = today's ltp`, fresh `snapshots`. No explicit "was this held before" check is required; absence of history *is* the reset.
- **`last_run`:** small operational breadcrumb — lets a human (or a future health-check) confirm the job actually ran on the expected date without needing to re-derive it from `portfolio.snapshots`.
- **First run (file absent):** `sentinel.py` treats `FileNotFoundError` as `state = {"schema_version": 1, "symbols": {}, "portfolio": {"snapshots": {}}}` and proceeds — `rules.py` then seeds every held symbol as first-seen. No special-case branch inside `rules.py` itself.

## GitHub Actions Job Design

```yaml
# .github/workflows/sentinel.yml
name: sentinel
on:
  schedule:
    - cron: "0 3 * * 1-5"   # 08:30 IST = 03:00 UTC, Mon-Fri
  workflow_dispatch: {}      # manual re-run after a failure, or for testing

permissions:
  contents: write            # required to commit state.json back

concurrency:
  group: sentinel-run
  cancel-in-progress: false  # never cancel a run mid-fetch; let overlaps queue instead

jobs:
  run:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -r requirements.txt
      - run: python sentinel.py
        env:
          GROWW_API_KEY: ${{ secrets.GROWW_API_KEY }}
          GROWW_TOTP_SEED: ${{ secrets.GROWW_TOTP_SEED }}
          TELEGRAM_TOKEN: ${{ secrets.TELEGRAM_TOKEN }}
          TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
      - name: commit state.json if changed
        run: |
          git config user.name "sentinel-bot"
          git config user.email "actions@users.noreply.github.com"
          git diff --quiet state.json && exit 0
          git add state.json
          git commit -m "chore: update sentinel state $(date -I)"
          git push
```

**Design decisions, with rationale:**

- **Single workflow file, single job.** No matrix, no multi-job DAG — there's nothing here to parallelize; splitting into separate jobs would only add artifact-passing overhead between fetch/rules/notify for no benefit.
- **`0 3 * * 1-5` UTC = 08:30 IST weekdays.** Weekday filtering happens at the cron level *and* again defensively inside `sentinel.py` (cheap, and covers `workflow_dispatch` manual runs on a Saturday).
- **NSE holiday skip lives in code (`holidays.py`), not in the cron expression** — cron can't express "except these 15 dates a year." `holidays.py` holds a static, manually-maintained list of NSE trading holidays (`set[date]`), updated once a year from the NSE's published calendar. *Rejected alternative:* the `nse-workday` PyPI package — its data only covers 2010–2025 at last check, meaning it will silently go stale for 2026+ without warning. A static list committed to the repo is one manual edit a year and fails loudly (wrong flag) rather than silently if forgotten — acceptable for a project this size. `ponytail: static list, upgrade to a maintained holiday-calendar package only if it starts covering future years reliably and the yearly manual edit becomes a real burden.`
- **Cron delay is expected and unfixable from this side.** GitHub does not guarantee exact-time execution — schedules can slip 5-30+ minutes, especially at top-of-hour, and can be skipped entirely during platform incidents. Scheduling at `:30` rather than `:00`/`:15` helps marginally but doesn't eliminate this. For a pre-market advisory digest (not a regulatory deadline), this is an acceptable, undocumented risk — not something to build retry infrastructure around. `workflow_dispatch` is the manual escape hatch if a run is ever missed.
- **`contents: write` at the job level**, not repo-wide default permissions — least privilege, and it's the one permission this workflow actually needs.
- **Commit-back is a separate shell step after the Python process, not done inside Python.** `git` binary + `GITHUB_TOKEN` are already present in the runner environment; shelling out from Python to invoke git adds a subprocess dependency for something the workflow YAML does natively in 5 lines. This also means `sentinel.py` has zero knowledge of git — it just writes a file to disk, which keeps its surface area smaller and testable without a git repo in the loop.
- **Scope caveat noted in the spec** (`ThePubDoc` token missing `workflow` scope) is a one-time push problem, not an architecture concern — resolve by pushing the `.yml` file from an account/token that has `workflow` scope once; subsequent runs use the default `GITHUB_TOKEN`, which always has this permission scoped to its own repo.
- **Failure notification path:** if `python sentinel.py` exits non-zero, the job step fails and GitHub sends its own failure email/notification to the repo watchers — this is a free secondary channel on top of the Telegram warning message `sentinel.py` sends itself before exiting. No extra `if: failure()` step is needed for a single-user personal project; add one only if the built-in GitHub failure email turns out to be insufficient in practice.

## Error-Handling Architecture

| Failure point | Behavior | Exit code | Rationale |
|---|---|---|---|
| Missing required secret(s) | Log which secret(s) missing to stderr. If `TELEGRAM_TOKEN`+`TELEGRAM_CHAT_ID` are present, also send a Telegram warning naming the missing secret(s). | 2 | Fail loud, name the culprit — never a cryptic downstream `KeyError`/`AttributeError`. |
| Groww auth/fetch failure (holdings or LTP call itself, not per-symbol) | `notify.send("⚠️ fetch failed: <reason>")`, then exit. | 1 | Never silently skip a day — this is the failure mode the spec calls out explicitly as unacceptable to swallow. |
| Missing LTP for one symbol (others succeed) | That symbol is carried through with `ltp=None`; `rules.py` skips its peak/flag computation and instead emits a note (e.g. "⚠️ INFY: no price data, skipped") in the digest. | 0 | Partial data is still useful data — one bad symbol shouldn't cancel the whole digest. |
| Empty holdings response | `notify.send("no holdings currently held")`, exit clean. | 0 | Not an error — a legitimate state (fully in cash). |
| Market holiday (via `holidays.py`) | `notify.send("market closed today")`, exit before touching the broker at all. | 0 | Pre-market runs on a holiday would show stale prior-day prices — worse than not running. Checked *before* any Groww call, saving an auth round-trip. |
| `state.json` missing (first run ever) | Seed `state = {"symbols": {}, "portfolio": {"snapshots": {}}}`; every held symbol becomes first-seen this run. | 0 (normal run) | No special first-run mode — it's just "old state was empty," handled by the same rebuild-not-merge logic as any other run. |
| Anything else unexpected (bug, unhandled exception) | Top-level `try/except Exception` in `sentinel.py`'s `main()` catches, attempts a best-effort Telegram notification ("⚠️ sentinel crashed: <type>: <msg>"), re-raises or exits non-zero. | 1 | A catch-all safety net around the *whole* run, distinct from the fetch-specific handling above — guarantees the job never fails invisibly even for a bug the code above didn't anticipate. |

**Ordering inside `sentinel.py`:** secrets validation → holiday/weekday guard → broker fetch (own try/except) → empty-holdings check → per-symbol LTP tolerance → `rules.evaluate` (no failure mode — pure function, bad input is a bug not a runtime error) → `notify.send` → write `state.json` → exit 0. A bare top-level `try/except Exception` wraps steps after secrets validation, as the last-resort net.

## Secrets Validation at Startup

```python
# sentinel.py (excerpt)
REQUIRED_SECRETS = ["GROWW_API_KEY", "GROWW_TOTP_SEED", "TELEGRAM_TOKEN", "TELEGRAM_CHAT_ID"]

def validate_secrets(env: dict) -> list[str]:
    return [name for name in REQUIRED_SECRETS if not env.get(name)]
```

- Check **all four up front**, before any network call — one pass, not a chain of individual `if not X: raise` scattered through `broker.py`/`notify.py`. This keeps the "what's missing" message complete (all missing secrets named at once) instead of stopping at the first one found.
- **Bootstrap ordering matters:** check `TELEGRAM_TOKEN`/`TELEGRAM_CHAT_ID` availability *first* within the missing-list, because those two are what determine whether the failure can even be reported via Telegram. If Telegram secrets are the ones missing, fall back to stderr + exit 2 — there's no channel left to notify through, and that's fine; the GHA run log is the fallback of last resort.
- This is a 5-line function with one job — no config-validation library, no schema tool. `ponytail: plain dict/list comprehension, add a validation library only if the secret list grows past a handful of ad-hoc types (e.g. URLs needing format checks).`

## Anti-Patterns

### Anti-Pattern 1: Rules engine reads global state / clock

**What people do:** Call `date.today()` or read `os.environ` directly inside the "business logic" function, because it's convenient and the file only has one caller anyway.
**Why it's wrong:** Immediately kills unit-testability of the money path — every test now has to freeze time or monkeypatch the clock, and a timezone bug (server UTC vs IST) becomes invisible until it fires on a specific date in production.
**Do this instead:** `sentinel.py` computes `today = datetime.now(ZoneInfo("Asia/Kolkata")).date()` once, and passes it into `rules.evaluate(..., today=today)` as a plain argument.

### Anti-Pattern 2: Mutating `state.json` in place across the run

**What people do:** Load `state`, then do `state["symbols"][sym]["peak"] = max(...)` directly, mutating the loaded dict, and write the same object back.
**Why it's wrong:** Makes it easy to accidentally carry forward a stale entry for a symbol that was sold (nothing forces you to visit and remove it), and makes `rules.py` harder to unit test (assertions on a mutated input vs. a fresh returned value are easy to get backwards).
**Do this instead:** `rules.evaluate` returns a brand-new `new_state` dict built only from *current* holdings, consulting the old `state` purely as a read-only lookup for continuity (peak, snapshot history). See Pattern 2 above — this is also what gives you pruning-on-exit for free.

### Anti-Pattern 3: Over-building the holiday/scheduling layer

**What people do:** Reach for a market-calendar Python package, or hand-roll Muhurat-trading-session / half-day logic, for a personal single-portfolio advisory tool.
**Why it's wrong:** Adds a dependency whose data can silently go stale (see the `nse-workday` 2010-2025 coverage gap found during this research) for a problem that's really "check today against ~15 known dates a year."
**Do this instead:** A static, manually-maintained `set[date]` in `holidays.py`, refreshed once a year from NSE's published calendar. Wrong-by-omission fails loudly (a flag fires on a holiday) rather than silently (a stale package quietly returns "not a holiday" forever after its data window ends).

## Scaling Considerations

Scaling in the traditional sense (concurrent users, request volume) does not apply — this is a single-user, single-portfolio, once-a-day batch job. The only axes that matter:

| Axis | At current scale (1 user, ~10-30 holdings) | If it grew (multiple portfolios / users) |
|---|---|---|
| Holdings count | Trivial — loop over a list of ~10-30 symbols, one LTP call each. | Batch the LTP fetch if the SDK supports multi-symbol requests; otherwise fine up to a few hundred. |
| `state.json` size | A few KB (bounded snapshot history × symbol count). | Would eventually want per-user state files instead of one shared file — not a concern here. |
| Notification volume | One message per weekday. | Per-user digests, still one message each — same pattern repeated, not a new architecture. |

**This is explicitly a "don't build for scale" case** — the spec's own Out-of-Scope list (no dashboard, no DB) already reflects that this system's ceiling is "personal cron job," and the architecture above should not be padded with growth-path abstractions (interfaces for swappable brokers, plugin notification channels, etc.) that no current or near-term requirement calls for. If a second broker or a second notification channel is ever genuinely needed, `broker.py`/`notify.py`'s existing "plain functions, plain dicts" boundary is already the right shape to extend without a rewrite.

## Suggested Build Order

Dependency-driven, not file-list order:

1. **Data contracts first:** finalize the `state.json` shape (above) and the `config.yaml` shape (`{symbol: "core"|"tactical"}`) — every other module's function signatures follow from these.
2. **`rules.py`** — build and fully unit-test with hand-built fixtures (AAA, one test per flag path) before `broker.py` or `notify.py` exist at all. It has zero dependencies on the other modules and is the highest-value code to get right first.
3. **`broker.py`** and **`notify.py`** in parallel — both are independent thin I/O wrappers with no shared logic between them. `broker.py` needs live Groww credentials to fully verify against the real API (including confirming the exact `growwapi` live-data method name and whether `average_price` is corporate-action-adjusted — both flagged as open items in the design spec); `notify.py` needs a live Telegram bot token but is otherwise trivial to verify manually.
4. **`holidays.py`** — trivial, no dependencies; can be done any time before step 5, in parallel with step 3.
5. **`sentinel.py`** — last, because it's the only module that imports all the others. Wire it, run it once manually end-to-end against real credentials before touching GitHub Actions at all.
6. **`.github/workflows/sentinel.yml`** — last of all. Get the whole pipeline working locally first (`python sentinel.py` from a terminal with secrets in `.env`/exported vars); only then move it into GHA, where debugging is slower (push-and-wait vs local iteration).

This order also naturally front-loads the one piece of test-driven-development the spec explicitly calls for (the pure rules engine) and defers the piece with the most external-dependency uncertainty (the exact `growwapi` surface) to when it can be verified against the real, live API rather than guessed at from documentation.

## Integration Points

### External Services

| Service | Integration Pattern | Notes |
|---|---|---|
| Groww TradeAPI (`growwapi` SDK) | Direct SDK call, wrapped in `broker.py` functions returning plain dicts. Auth via API key + TOTP generated at runtime from a stored seed (`pyotp`). | Confirm at implementation time: exact live-data/LTP method name, per-symbol vs batch fetch, and whether `average_price` is already corporate-action-adjusted (spec flags both as open items — this is a phase-time verification task, not an architecture decision). |
| Telegram Bot API | Plain HTTPS POST to `sendMessage`, no SDK needed for a single outbound message type. | `requests` (already a near-certain dependency) is enough — no telegram-bot framework needed for a fire-and-forget one-way notification. |

### Internal Boundaries

| Boundary | Communication | Notes |
|---|---|---|
| `sentinel.py` ↔ `broker.py` | Direct function calls, plain dicts/lists in and out. | `broker.py` raises on failure; `sentinel.py` decides what to do about it (that's a policy decision, not a fetch-layer decision). |
| `sentinel.py` ↔ `rules.py` | Direct function call, one pure `evaluate(...)` entry point. | All of `rules.py`'s inputs are plain data (dicts/lists/a `date`) — no shared mutable objects crossing the boundary. |
| `sentinel.py` ↔ `notify.py` | Direct function calls: `format_digest(...)` (pure) then `send(...)` (I/O). | Keeping these two separate (rather than one `notify(...)` that both formats and sends) is what makes the message text itself testable without mocking HTTP. |
| `sentinel.py` ↔ filesystem (`state.json`, `config.yaml`) | Plain `json`/`yaml` load and one `json.dump` at the end. | No ORM, no schema library — a five-key JSON file doesn't need one. |
| GHA workflow ↔ `sentinel.py` | Environment variables in, process exit code + stdout/stderr out. | The only contract between the workflow YAML and the Python process — keep it that thin. |

## Sources

- [GitHub Actions scheduled workflow reliability, delay behavior, and best practices — Cronuru guide](https://cronuru.com/guides/github-actions-scheduled-workflows)
- [GitHub Community Discussion: unexpected delay in scheduled GitHub Actions workflows](https://github.com/orgs/community/discussions/156282)
- [nse-workday on PyPI — NSE holiday/workday calculation package](https://pypi.org/project/nse-workday/) (evaluated and rejected in favor of a static list — see Anti-Pattern 3 / GHA job design rationale)
- Project design spec: `docs/superpowers/specs/2026-07-09-groww-sentinel-design.md` (module split, flag thresholds, error-handling requirements — this research validates and concretizes it)
- Project context: `.planning/PROJECT.md`
- Established software design patterns applied here: pure-core/imperative-shell (a.k.a. functional core, imperative shell), idempotent-by-construction state via date-keyed records — general software architecture principles, not domain-specific citations.

---
*Architecture research for: headless Python cron-job advisory pipeline (Groww Sentinel)*
*Researched: 2026-07-09*
