# Phase 2: Durable State & Portfolio Telemetry - Research

**Researched:** 2026-07-10
**Domain:** Stateful daily-snapshot persistence for a pure-core Python cron pipeline; corporate-action-safe P&L math; yfinance intraday/prev-close semantics
**Confidence:** MEDIUM-HIGH (state-machine/atomic-write/trend-math patterns are stdlib-level HIGH confidence; the two brokerage/vendor unknowns — Groww `average_price` corp-action adjustment and yfinance live-vs-close daily bar behavior — are CITED/MEDIUM, not independently lab-verified this session)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**State shape & cadence (STATE-01..04)**
- **D-01:** Run cadence is **market-hours hourly** (~9:15-15:30 IST weekdays, ~7 runs/day). This supersedes the original once-daily 08:30 design — a Phase-3 cron change (RUN-01). Captured here because it drives snapshot design.
- **D-02:** Snapshots are **keyed per calendar date** (one entry/day). Intraday reruns **overwrite** that day's entry -> idempotent (STATE-04). Peak still updates on **every** run (captures intraday highs).
- **D-03:** `state.json` schema (single file, repo root):
  ```json
  {
    "peaks": { "SYMBOL": {"peak": float, "qty": int, "avg_cost": float} },
    "snapshots": {
      "YYYY-MM-DD": {
        "total_value": float,
        "symbols": { "SYMBOL": {"price": float, "value": float} },
        "flags_fired": int
      }
    },
    "sentiment": { "SYMBOL": {"date": "YYYY-MM-DD", "label": str, "reason": str} }
  }
  ```
  `peaks` also stores prior `qty`/`avg_cost` for corp-action detection (D-09).
- **D-04:** `new_state` is **rebuilt from current holdings each run** (STATE-02): prior state is a read-only lookup. A symbol no longer held is dropped -> its peak resets; rebuying re-seeds (STATE-03).
- **D-05:** `snapshots` bounded to the most recent ~10 dated entries (enough for a 5-day trend + weekly); prune older. `sentiment` bounded to current holdings.
- **D-06:** During market hours yfinance's last close ~= today's live price, so intraday snapshots reflect current value (the `ltp` slot stays the generic "current price"). Purity of `rules.py` preserved -- `today` and prior state are injected, no clock/IO in rules.

**P&L reporting (PNL-01..05)**
- **D-07:** Header/report shows: overall unrealized P&L vs cost (PNL-01); **day change = today's value vs the prior *day's* stored snapshot** (PNL-02, not vs prior run); **5-trading-day trend** direction + % (PNL-03); intraday % when the price source exposes previous close (PNL-04). Compact, e.g. `Day +1.2% - 5d up +3.4%`.
- **D-08:** Friday's digest appends a **weekly block** (PNL-05): best/worst **2-3 movers by % price change over the trading week** (from per-symbol snapshot history), week portfolio value change, and **flags-fired count** (sum of stored daily `flags_fired`).

**Corporate-action safety (RULES-06)**
- **D-09:** Detect a distorted average cost via a **quantity jump vs stored prior `qty`** without a proportional cost basis change (bonus/split signature). On detection, that run **replaces the P&L-based flag (STOP/BOOK/AVERAGE) with a `CORP-ACTION` warning line** so a distorted cost can't fire a false trade. Weight-based TRIM and peak-based TRAIL WATCH still evaluate normally. Detection input (prior qty/avg_cost) comes from state -> keep `rules.py` pure by passing it in.

**Sentiment caching**
- **D-10:** Cache sentiment in `state.sentiment` keyed by symbol; reuse for the **same calendar day**, re-score next day. Hourly runs -> ~**1 model call/day** total (first market-hours run scores; rest reuse), and it smooths the flaky-news problem. A cache miss/stale entry triggers a (batched) re-score for just the uncached AVERAGE candidates.

### Claude's Discretion
- Exact trend arrow glyphs / wording, weekly-block layout, and how many movers (2 vs 3).
- Prune thresholds (the ~10-entry bound) and the corp-action quantity-jump tolerance %.
- Whether day-change/trend live in the header or a small "TELEMETRY" section.

### Deferred Ideas (OUT OF SCOPE)
- **Committing state.json back to the repo** each run -> Phase 3 (RUN-03), needs `contents: write`.
- **Hourly market-hours cron** (D-01) is a Phase 3 scheduling change (RUN-01 was 08:30 pre-market) -- implement the schedule there; Phase 2 only assumes per-day snapshot semantics.
- **Sturdier news source** than yfinance (Google News RSS fallback) -- improves sentiment reliability; not required for Phase 2 (same-day cache already reduces exposure). Revisit if flakiness persists.
- Contribution-to-portfolio weekly view (alternative to %-movers) -- considered, deferred.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-------------------|
| STATE-01 | Track per-symbol peak price keyed to the current holding period | See "Peak lifecycle" + "Rebuild-not-merge wiring" below; existing `rules.py` already has the `peak = max(prior_peak, ltp)` mechanic, extend the stored tuple to `{peak, qty, avg_cost}`. |
| STATE-02 | Rebuild `new_state` from current holdings each run, prior state read-only | Existing `rules.py` `new_state = {}` loop already does this correctly for `peak`; extend the same loop to also carry `qty`/`avg_cost` forward for RULES-06. No architecture change needed. |
| STATE-03 | Prune state for symbols no longer held; reset peak on exit, re-seed on rebuy | Falls out for free from STATE-02's rebuild-not-merge (a symbol absent from `holdings` is never written into `new_state`). Verify with the 3 boundary tests named in "Test Matrix" below. |
| STATE-04 | Daily portfolio + per-symbol snapshots keyed by date; same-day rerun overwrites; bounded history | See "Snapshot write/prune mechanics" -- `snapshots[today_str] = {...}` (overwrite, not append) + `dict(sorted(...)[-10:])` prune, one-liner each. |
| PNL-01 | Overall unrealized P&L vs cost | Already computed in `sentinel._portfolio_summary` -- no new research needed, carry forward unchanged. |
| PNL-02 | Day P&L = snapshot delta vs prior *day's* stored value (not prior run) | See "Day-change: the off-by-one trap" below -- must explicitly find the latest snapshot key strictly `< today`, not just `sorted(keys)[-2]`. |
| PNL-03 | N-day portfolio trend from stored snapshots | See "5-day trend computation" below; handle 0/1-4/5+ prior-entry cases explicitly. |
| PNL-04 | Intraday % when price source exposes previous close | See "yfinance previous-close API" below -- `fast_info.previous_close` / `fast_info.last_price`, confirmed available attributes. |
| PNL-05 | Friday weekly summary: movers, week value change, flags-fired count | See "Weekly block computation" below -- week-start = Monday of `today`'s ISO week, using earliest available snapshot in that window as baseline. |
| RULES-06 | Detect corp-action-distorted avg cost; warn instead of false STOP/BOOK/AVERAGE | See "Corporate-action detection heuristic" below -- concrete qty-jump + cost-flat formula with proposed tolerances. |

</phase_requirements>

## Summary

This phase turns three currently-stubbed inputs (`state={}` in `sentinel.py`, no snapshot history, no sentiment cache) into real, persisted, bounded state — without touching `rules.py`'s pure-function contract established in Phase 1. The two genuine unknowns are (1) whether Groww's `average_price` is corporate-action-adjusted, and (2) whether yfinance's daily bar reflects a live intraday price during market hours. Neither is fully documented by the vendors. For (1), Groww's own consumer help center **does** state that `average_price` (and 52-week high/low) is adjusted after a bonus/split at the account level — which is the same backend data the TradeAPI reads from — so it is reasonable to expect the field is already adjusted; the API docs themselves stay silent, so this is CITED-not-VERIFIED and the D-09 quantity-jump detector should be built as a required backstop regardless, not skipped because "the docs said it's probably fine." Critically, the field that is **not** protected by that adjustment is the locally-stored `peak` — it's a raw price level captured pre-split, so the concrete recommendation below is to scale `peak` down by the qty ratio when a corp-action is detected (not to leave it untouched), even though only STOP/BOOK/AVERAGE are named for override in D-09.

For (2), yfinance's `fast_info.previous_close` and `fast_info.last_price` are confirmed distinct, available attributes (yfinance >= 0.2.14; project pins 1.5.1) — this directly answers PNL-04's "intraday % when the source exposes previous close" without needing a second data source. Whether `yf.download(period="5d")`'s final row is a live-updating partial bar during market hours (the existing D-06 assumption) is long-standing common Yahoo Finance behavior but not something either vendor documents explicitly; treat it as ASSUMED and word the digest defensively (see Pitfalls).

The rest of the phase is mechanical: date-keyed dict snapshots with overwrite-not-append, a bounded-history prune (`sorted(...)[-10:]`), a same-day sentiment cache keyed by date, and a rebuild-not-merge state transition that already has a working template in the existing `rules.py` peak-seeding loop.

**Primary recommendation:** Extend `rules.py`'s existing `state[symbol] -> new_state[symbol]` loop (already correct for peaks) to also carry `qty`/`avg_cost` and run the corp-action check inline (same pure function, one more input field per symbol, no new I/O). Keep all snapshot/trend/weekly/sentiment-cache bookkeeping in the impure shell (a new `state.py` per the roadmap, or `sentinel.py`), as pure helper functions that take `(snapshots, today) -> ...` so they stay unit-testable without file I/O.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|-----------------|-----------|
| Peak tracking + corp-action detection (RULES-06, STATE-01) | Pure core (`rules.py`) | -- | Needs `qty`/`avg_cost`/`ltp` per symbol, already the exact shape `rules.py` consumes; keeping it here avoids a second source of truth for "is this a fresh holding period." |
| state.json load/save/atomic-write | I/O shell (new `state.py`, per ROADMAP 02-01) | -- | Filesystem access; must never live in `rules.py`. |
| Snapshot write + prune (STATE-04) | I/O shell, but the merge/prune logic itself can be a pure helper `write_snapshot(snapshots, today, portfolio) -> new_snapshots` | Pure helper | The write target is a file, but "what the new dict should look like" is pure data transformation -- testable without touching disk. |
| Day-change / 5-day trend / weekly movers (PNL-02/03/05) | Pure helper (e.g., `telemetry.py` or functions in `state.py`) | -- | Input is `(snapshots: dict, today: date)`, output is plain numbers -- no reason to entangle with file I/O or Telegram formatting. |
| Sentiment cache read/reuse decision | Impure shell (`sentiment.py`, already impure) | -- | Already the file that owns the Gemini network call; cache-hit/miss branching belongs next to the call it's gating. |
| Digest text rendering of telemetry/weekly block | `notify.py` (pure `format_digest`) | -- | Already pure; extend its input dict, don't add new I/O there. |

## Standard Stack

### Core
No new runtime dependencies this phase. Everything needed (`json`, `os`, `tempfile`, `datetime`, `zoneinfo`) is Python stdlib; `yfinance` and `google-genai` are already pinned from Phase 1.

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|----------------|
| `json` (stdlib) | 3.13 stdlib | Read/write `state.json` | No schema library needed for a 3-key JSON file -- matches project's existing YAGNI posture (STACK.md already rejected heavier tooling at this scale). |
| `os` / `tempfile` (stdlib) | 3.13 stdlib | Atomic write (temp file + `os.replace`) | `os.replace()` is documented atomic on POSIX and Windows since Python 3.3; the CI runner is `ubuntu-latest`, so same-filesystem atomicity holds. [CITED: docs.python.org os.replace, widely corroborated by multiple atomic-write guides found this session] |
| `datetime` / `zoneinfo` (stdlib) | 3.13 stdlib | Friday detection, week-boundary math | `today.weekday() == 4` for Friday (Monday=0); `today` is already injected as an IST `date` per D-06 -- no new clock code needed anywhere. |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `yfinance` | 1.5.1 (already pinned) | `fast_info.previous_close` / `fast_info.last_price` for PNL-04 intraday % | Only if implementing the "intraday %" sub-metric; the existing `prices.get_prev_close` batched `yf.download` call already covers PNL-01/02/03/05's needs without a second network round trip. |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Hand-rolled atomic write (`tempfile.NamedTemporaryFile` + `os.replace`) | A PyPI atomic-write library (`atomicwrites`, etc.) | Unmaintained/deprecated in favor of the stdlib pattern per current Python community consensus (a stdlib `atomicwrite` proposal exists but isn't merged) -- for one file written once per run, the 6-line stdlib pattern is simpler and has zero new dependency risk. |
| `fast_info.previous_close` for PNL-04 | A second `yf.Ticker(...).info` dict lookup | `info` is documented slower and has had attribute-availability inconsistencies reported across tickers in yfinance's own issue tracker; `fast_info` is the purpose-built lightweight path introduced specifically to replace slow `info` lookups. |

**Installation:** No changes to `requirements.txt` needed this phase.

**Version verification:**
```bash
pip show yfinance   # confirms 1.5.1, already installed
python3 --version   # 3.13.0 in this environment; project targets 3.11+
```

## Package Legitimacy Audit

No new external packages are introduced by this phase — state persistence uses only Python stdlib (`json`, `os`, `tempfile`, `datetime`), and PNL-04 reuses the already-vetted, already-pinned `yfinance` package from Phase 1. No legitimacy check is required.

**Packages removed due to [SLOP] verdict:** none (n/a — no new packages)
**Packages flagged as suspicious [SUS]:** none (n/a — no new packages)

## Architecture Patterns

### System Architecture Diagram

```
                    ┌─────────────────────────────────────────┐
                    │        state.json (on disk, repo root)    │
                    │  {peaks, snapshots, sentiment}            │
                    └───────────────┬───────────────┬──────────┘
                            load    │               │ atomic write
                          (read)    │               │ (temp + os.replace)
                                    ▼               │
┌──────────┐   holdings   ┌──────────────────┐      │
│broker.py │ ───────────► │                  │      │
└──────────┘              │   sentinel.py /  │      │
┌──────────┐   prev_close │   state.py       │──────┘
│prices.py │ ───────────► │  (impure shell)  │
└──────────┘              │                  │
                           │  - loads state   │
                           │  - calls rules   │
                           │  - computes      │
                           │    trend/weekly  │
                           │    (pure helpers)│
                           │  - writes state  │
                           └────┬────────┬────┘
                                │        │
                     (holdings, │        │ flags, new_peaks
                      state.peaks,       │
                      today)    ▼        ▼
                          ┌──────────────────┐
                          │    rules.py       │  <- pure, unchanged contract
                          │  evaluate(...)    │     one more per-symbol input
                          │  + corp-action    │     field: prior qty/avg_cost
                          │    detection      │
                          └────┬─────────────┘
                               │ flags (some now CORP-ACTION)
                               ▼
                   ┌───────────────────────┐
                   │  sentiment.py          │  <- reads/writes state.sentiment
                   │  adjust(flags, cache,  │     cache, gated by "same day"
                   │         today)         │
                   └────────┬──────────────┘
                            ▼
                   ┌───────────────────────┐
                   │  notify.py             │  <- format_digest extended with
                   │  format_digest(flags,  │     day-change/trend/weekly dict
                   │    portfolio+telemetry)│
                   └────────┬──────────────┘
                            ▼
                     Telegram sendMessage
```

### Recommended Project Structure
```
groww-sentinel/
├── rules.py           # unchanged contract; extend per-symbol state tuple + corp-action check
├── state.py           # NEW: load/save state.json (atomic write), snapshot write+prune,
│                       #      trend/day-change/weekly pure helpers (per ROADMAP 02-01/02-02)
├── sentinel.py         # wire: load state -> rules.evaluate(holdings, state["peaks"], today)
│                       #       -> sentiment.adjust(flags, state["sentiment"], today)
│                       #       -> state.write_snapshot(...) -> notify.format_digest(...)
│                       #       -> state.save(new_state)
├── sentiment.py        # extend adjust() signature to take/return a cache dict
├── notify.py            # extend format_digest()'s portfolio dict with day_change/trend/weekly
└── tests/
    ├── test_rules.py     # extend: corp-action boundary tests, qty/avg_cost carry-forward
    ├── test_state.py      # NEW: snapshot overwrite/prune, trend math, atomic write
    └── test_sentiment.py   # extend: same-day cache hit/miss
```

### Pattern 1: Rebuild-not-merge for the peaks dict (already in place, just extend it)

**What:** `rules.py` already builds `new_state[symbol] = {"peak": peak}` fresh from current holdings each run, using `state.get(symbol, {})` as a read-only lookup. This is exactly STATE-02/03's required mechanism.
**When to use:** Extend the same dict, don't add a parallel structure.
**Example:**
```python
# rules.py -- extend the existing loop (today's code already has lines 116-120)
prior = state.get(symbol, {})
prior_peak = prior.get("peak")
prior_qty = prior.get("qty")          # NEW: None on first-seen (no corp-action check possible)
prior_avg_cost = prior.get("avg_cost")  # NEW

peak = prior_peak if prior_peak is not None else max(ltp, avg_cost)
peak = max(peak, ltp)

corp_action = _detect_corp_action(prior_qty, prior_avg_cost, qty, avg_cost)
if corp_action:
    # scale the stored peak down proportionally -- it was captured on the
    # pre-action share count and is no longer comparable to post-action ltp
    peak = peak * (prior_qty / qty) if prior_qty else peak

new_state[symbol] = {"peak": peak, "qty": qty, "avg_cost": avg_cost}
```

### Pattern 2: Date-keyed idempotent snapshot write (STATE-04)

**What:** `snapshots[today.isoformat()] = {...}` -- a dict write, not a list append. A second run the same day overwrites the same key.
**When to use:** Every write to `state["snapshots"]`.
**Example:**
```python
# state.py
def write_snapshot(snapshots: dict, today, total_value: float,
                    per_symbol: dict, flags_fired: int, keep: int = 10) -> dict:
    """Pure: returns a NEW snapshots dict, never mutates the input (STATE-04)."""
    key = today.isoformat()
    updated = {**snapshots, key: {
        "total_value": total_value, "symbols": per_symbol, "flags_fired": flags_fired,
    }}
    # bound to the most recent `keep` dated entries -- one-liner prune (D-05)
    return dict(sorted(updated.items())[-keep:])
```

### Pattern 3: Day-change lookup -- explicit "strictly before today", not "second-to-last key"

**What:** PNL-02 needs "vs the prior *day's* stored value" -- but on an hourly rerun, `snapshots` may **already contain today's own key** from an earlier run this same day. `sorted(keys)[-2]` is correct on the *first* run of the day (today isn't in the dict yet) but **wrong on the second+ run** (it would grab today's own earlier value, not yesterday's).
**When to use:** Any day-change calculation.
**Example:**
```python
# state.py
def day_change(snapshots: dict, today) -> float | None:
    """% change of today's (not-yet-written) value vs the latest snapshot
    strictly before today. None on first run ever (no prior day exists)."""
    prior_dates = sorted(d for d in snapshots if d < today.isoformat())
    if not prior_dates:
        return None
    prior_value = snapshots[prior_dates[-1]]["total_value"]
    return prior_value  # caller computes (today_value - prior_value) / prior_value
```
Call this **before** writing today's snapshot (Pattern 2), using the *loaded* `snapshots` dict, not the post-write one — otherwise a same-day rerun would diff against itself.

### Pattern 4: 5-trading-day trend with graceful degradation

**What:** PNL-03's "N-day trend" needs to handle three cases without crashing: zero prior snapshots (first run), 1-4 prior snapshots (early days), 5+ (steady state).
**Example:**
```python
# state.py
def n_day_trend(snapshots: dict, today, n: int = 5) -> dict | None:
    prior_dates = sorted(d for d in snapshots if d < today.isoformat())
    if not prior_dates:
        return None  # first run -- no trend possible
    window = prior_dates[-n:]           # up to n most recent prior days; fewer is fine
    baseline_value = snapshots[window[0]]["total_value"]
    return {"days": len(window), "baseline": baseline_value}
    # caller: pct = (today_value - baseline_value) / baseline_value
    # label "Nd" using the ACTUAL len(window), not a hardcoded "5d" --
    # week 1 will genuinely only have a 1-4 day trend, and the digest should say so.
```

### Pattern 5: Friday weekly-block week-boundary

**What:** "Movers over the trading week" needs a week-start date, not just "the last 5 entries."
**Example:**
```python
from datetime import timedelta

def week_start(today):
    return today - timedelta(days=today.weekday())  # Monday=0

def weekly_symbol_movers(snapshots: dict, today, top_n: int = 3) -> list[dict]:
    monday = week_start(today).isoformat()
    week_dates = sorted(d for d in snapshots if monday <= d <= today.isoformat())
    if len(week_dates) < 2:
        return []  # not enough history this week yet (e.g., first run of the week)
    baseline_date = week_dates[0]
    per_symbol_pct = {}
    for sym in snapshots[today.isoformat()]["symbols"]:
        start = snapshots[baseline_date]["symbols"].get(sym, {}).get("price")
        end = snapshots[today.isoformat()]["symbols"].get(sym, {}).get("price")
        if start and end:
            per_symbol_pct[sym] = (end - start) / start
    ranked = sorted(per_symbol_pct.items(), key=lambda kv: kv[1], reverse=True)
    return ranked[:top_n] + ranked[-top_n:] if len(ranked) > top_n else ranked
```

### Anti-Patterns to Avoid
- **Mutating `state["peaks"]`/`state["snapshots"]` in place:** always build a new dict and return it (already the project's established pattern -- see ARCHITECTURE.md Anti-Pattern 2). Same discipline applies to the new snapshot/sentiment dicts.
- **Using `sorted(snapshots)[-2]` for "yesterday":** breaks on the second+ run of the same day (Pattern 3 above) -- always filter `< today` explicitly.
- **Hardcoding "5d" in the digest label when fewer than 5 days of history exist:** label with the actual window length (Pattern 4) -- otherwise the first week of use produces a misleading "5d" trend computed from 1-2 days of data.
- **Trusting `average_price` as adjusted without the qty-jump backstop:** even though Groww's help center suggests bonus/split adjustment happens at the account level, the API docs don't confirm this for the TradeAPI response specifically -- RULES-06's detector must run regardless, as a backstop not a redundancy.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|--------------|-----|
| Atomic JSON write | A custom lock-file / retry scheme | `tempfile.NamedTemporaryFile(dir=same_dir, delete=False)` + `os.replace(tmp, target)` | `os.replace` is documented atomic cross-platform since Python 3.3; this is the standard idiom, not a library-worthy problem. [CITED: docs.python.org, corroborated by multiple 2026 atomic-write guides found this session] |
| Previous-close price | A second scrape/API integration | `yfinance.Ticker(...).fast_info.previous_close` (or the existing batched `yf.download` last-but-one row) | Already in the approved stack; `fast_info` is yfinance's own purpose-built lightweight quote path. |
| Week-boundary math | A calendar/date-range library | stdlib `date.weekday()` + `timedelta` | Five lines of stdlib arithmetic; no dependency justifies itself for "what's the Monday of this week." |

**Key insight:** Every mechanism this phase needs (atomic write, date-keyed dict, rebuild-not-merge, week-boundary) is a stdlib one-liner or a small pure function — the existing project research (ARCHITECTURE.md) already anticipated this shape; Phase 2 is "wire it up," not "solve a new hard problem," except for the two vendor-behavior unknowns below.

## Common Pitfalls

### Pitfall 1: Corp-action detector fires on a genuine large manual buy
**What goes wrong:** `AVERAGE_ADD_FRAC = 0.25` in `rules.py` means a real AVERAGE-down purchase can grow qty by 25%+ in one run — if the corp-action detector only checks "did qty jump," a real manual buy gets mislabeled CORP-ACTION and its legitimate AVERAGE flag is suppressed.
**Why it happens:** Looking at qty growth alone can't distinguish "bonus shares, zero cost" from "bought more at market price."
**How to avoid:** Require **both** conditions: qty grew past a threshold, **and** total invested capital (`qty * avg_cost`) stayed flat (within a small tolerance). A genuine purchase moves total capital roughly in proportion to the qty added at ~market price; a bonus/split moves qty with ~zero new capital. Concretely:
```python
QTY_JUMP_PCT = 0.05        # qty grew > 5% since last run's stored qty
COST_FLAT_TOLERANCE = 0.05  # total invested capital changed < 5% over the same jump

def _detect_corp_action(prior_qty, prior_avg, qty, avg_cost) -> bool:
    if not prior_qty or prior_qty <= 0:
        return False  # first-seen symbol -- no baseline, never flag (STATE-05 territory)
    qty_growth = (qty - prior_qty) / prior_qty
    if qty_growth <= QTY_JUMP_PCT:
        return False
    prior_capital = prior_qty * prior_avg
    new_capital = qty * avg_cost
    cost_growth = abs(new_capital - prior_capital) / prior_capital if prior_capital else 0.0
    return cost_growth < COST_FLAT_TOLERANCE
```
**Warning signs:** A large manual AVERAGE purchase shows CORP-ACTION instead of AVERAGE the next run; unit-test this exact scenario (qty +25%, avg_cost moves toward market price) alongside the true-positive bonus scenario (qty +100%, avg_cost roughly halves, total capital flat).

### Pitfall 2: Stale peak survives a corp action, producing a phantom TRAIL WATCH
**What goes wrong:** D-09 only names STOP/BOOK/AVERAGE for override, leaving TRAIL WATCH ("evaluates normally") — but the stored `peak` was captured on the pre-action share count/price level. After a 1:1 bonus, market price roughly halves; a peak of 200 compared to a post-bonus ltp of ~100 reads as "50% below peak," a false trailing-stop trigger even though nothing economically changed.
**Why it happens:** "Evaluates normally" is correct for the *flag logic*, but the *peak value itself* still needs a one-time proportional rescale to stay comparable — otherwise "normal" evaluation runs on a corrupted number.
**How to avoid:** On corp-action detection, rescale `peak *= (prior_qty / qty)` (mirrors how avg_cost naturally rescales for a real bonus/split) before continuing the normal `peak = max(peak, ltp)` — this keeps TRAIL WATCH's math meaningful without suppressing the flag itself, staying consistent with D-09's letter (only STOP/BOOK/AVERAGE are literally replaced) while fixing the input the untouched flags depend on.
**Warning signs:** A CORP-ACTION run immediately followed by a TRAIL WATCH on the same symbol with an implausibly large `pct_below_peak` (roughly matching the corp-action ratio, e.g. ~50% for a 1:1 bonus).

### Pitfall 3: Day-change computed against today's own already-written entry (see Pattern 3)
**What goes wrong:** On an hourly rerun, `state["snapshots"]` already contains today's key from an earlier run. Naively taking "the second-to-last sorted key" silently degrades to comparing today against itself once today's key exists.
**How to avoid:** Always filter `date < today.isoformat()` explicitly (Pattern 3); never assume position in sort order.
**Warning signs:** "Day change" reads suspiciously close to 0% specifically starting from the second run of a day onward.

### Pitfall 4: Trusting yfinance's daily bar to be "live" without a freshness caveat
**What goes wrong:** D-06 assumes "during market hours yfinance's last close ~= today's live price" — this is common, long-observed Yahoo Finance behavior (the current session's daily bar is a live-updating partial candle until close) but neither Yahoo nor yfinance's docs make an explicit contractual guarantee of this, and yfinance's own community has open discussions noting inconsistent timestamp/freshness handling in `fast_info`/`info` across tickers.
**How to avoid:** Word any "as of" language in the digest defensively (e.g., "price as of last available quote," not "live price"), and prefer `fast_info.last_price`/`fast_info.previous_close` (purpose-built for this) over parsing the tail of a `period="5d"` daily download when precision matters (PNL-04 specifically).
**Warning signs:** A digest's reported day-change doesn't match what the Groww app shows at the same moment — expected occasional drift given Yahoo's own data-freshness variability, not a bug to chase indefinitely.

### Pitfall 5: Sentiment cache never invalidates within the same day even if headlines change
**What goes wrong:** D-10 intentionally caches per calendar day — this is a deliberate feature (smooths flaky news, 1 model call/day), not a bug, but it means a stock that turns genuinely bearish mid-morning won't get re-scored until the next calendar day.
**How to avoid:** Nothing to fix — this is the locked design. Just don't "improve" it by adding an intraday re-score without discussing it first; document the tradeoff inline in `sentiment.py` (as the existing docstring style already does) so a future reader doesn't mistake it for an oversight.

## Code Examples

### Wiring rules.py's extended state through sentinel.py
```python
# sentinel.py -- replace the current `state={}` stub
state = state_mod.load()  # {"peaks": {}, "snapshots": {}, "sentiment": {}} on first run
flags, new_peaks = rules.evaluate(merged, state=state["peaks"], today=today)

sentiment_cache = state["sentiment"]
flags, new_sentiment = sentiment.adjust(flags, env.get("GEMINI_API_KEY"), sentiment_cache, today)

prior_day_value = state_mod.day_change(state["snapshots"], today)  # look up BEFORE writing today
new_snapshots = state_mod.write_snapshot(
    state["snapshots"], today, portfolio["total_value"], per_symbol_prices,
    flags_fired=sum(1 for f in flags if f["flag"] not in ("HOLD", "NO PRICE")),
)

new_state = {"peaks": new_peaks, "snapshots": new_snapshots, "sentiment": new_sentiment}
state_mod.save(new_state)  # atomic temp-file + os.replace
```

### Atomic write (state.py)
```python
import json
import os
import tempfile

STATE_PATH = "state.json"

def load() -> dict:
    try:
        with open(STATE_PATH) as f:
            return json.load(f)
    except FileNotFoundError:
        return {"peaks": {}, "snapshots": {}, "sentiment": {}}

def save(state: dict) -> None:
    directory = os.path.dirname(os.path.abspath(STATE_PATH)) or "."
    fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".state-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(state, f, indent=2, default=str)  # default=str for any stray date objects
        os.replace(tmp_path, STATE_PATH)  # atomic on POSIX + Windows
    except Exception:
        os.unlink(tmp_path)
        raise
```

### yfinance previous-close for PNL-04
```python
# Confirmed available attributes (yfinance >= 0.2.14; project pins 1.5.1):
import yfinance as yf
t = yf.Ticker(f"{symbol}.NS")
prev_close = t.fast_info.previous_close   # yesterday's close
last = t.fast_info.last_price             # current/latest quote (may lag during low-liquidity periods)
intraday_pct = (last - prev_close) / prev_close if prev_close else None
```
[CITED: yfinance GitHub issue #1518 discussion + multiple 2026 yfinance guides confirming `fast_info` exposes both `previous_close` and `last_price` as distinct attributes; not independently executed against a live ticker this session]

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|--------------------|-----------------|--------|
| `yf.Ticker(...).info` for quote fields | `yf.Ticker(...).fast_info` | Introduced yfinance v0.2.14 | Faster, purpose-built for exactly `last_price`/`previous_close`-style lookups; project should prefer it over `.info` for PNL-04 rather than parsing a broader dict. |

**Deprecated/outdated:**
- Relying on `.info` dict key names (`regularMarketPreviousClose`, etc.) for a single scalar previous-close value — still works but `fast_info` is the documented faster/lighter path for exactly this use case.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|-----------------|
| A1 | `yf.download(period="5d")`'s final daily row updates live during NSE market hours (D-06's existing assumption) | Pitfall 4, Summary | If false, intraday snapshots during market hours would silently show yesterday's close relabeled as "current" — digest day-change/trend would be flat/wrong until after 15:30 IST close. Verify at impl time by running once mid-session and comparing to the Groww app's shown price. |
| A2 | Groww's `average_price` field (as returned by the TradeAPI, not just the consumer app) is proportionally adjusted after a bonus/split | Summary, "Don't Hand-Roll" | If false, `pnl_pct` itself (not just `peak`) is distorted post-corp-action, and the RULES-06 override needs to also suppress a wider set of derived numbers (e.g., `pct` shown in the digest for that symbol) rather than just the flag. The qty-jump detector already treats this defensively (backstop regardless), so the practical risk is contained even if this assumption is wrong. |
| A3 | Proposed tolerances `QTY_JUMP_PCT = 0.05`, `COST_FLAT_TOLERANCE = 0.05` correctly separate corp-action from a real large AVERAGE purchase (25% qty add) | Pitfall 1 | If a manual buy's cost-basis-per-share lands unusually close to the prior avg_cost (e.g., buying at a price very near the existing average), it could produce `cost_growth` below 5% and be misflagged CORP-ACTION for one run — low-probability, self-correcting next run since qty/avg_cost update regardless. Unit test both scenarios explicitly per Pitfall 1. |
| A4 | Rights-issue-style corporate actions (qty increases with a discounted, non-zero cash outlay) aren't reliably classified by this heuristic either way | Pitfall 1, Open Questions | Low likelihood for this portfolio's holdings; if it happens, worst case is a missed CORP-ACTION warning (falls through to normal P&L ladder) or a false one for a single run — acceptable per YAGNI, not pre-built for. |

**If this table is empty:** N/A — see entries above; none of these block planning, but A1/A2 should be spot-verified against real data at implementation time per the project's own established "verify at impl, don't guess" pattern (already the disposition STACK.md took for this exact `average_price` question).

## Open Questions (RESOLVED)

1. **Does `average_price` timing lag corporate-action settlement (T+N days)?** — RESOLVED: detector is timing-agnostic (fires whichever run first sees the new qty); no special handling, observe empirically.
   - What we know: Groww's help center describes the *eventual* adjusted state; brokerages commonly have a settlement delay between a corporate action's record date and when it's reflected in the demat/holdings API.
   - What's unclear: Whether there's a window where `quantity` still shows the pre-action count (not yet credited) while `average_price` is unchanged, versus both jumping together on the same run.
   - Recommendation: The qty-jump-plus-cost-flat detector is agnostic to *when* the jump happens — it fires whichever run first sees the new qty, regardless of settlement timing. No special handling needed; flag as something to observe empirically on the first real corporate action this account experiences.

2. **Should the CORP-ACTION-detected run also suppress the digest's `pct` display?** — RESOLVED: yes, omit `pct` context like NO PRICE does (implemented in plan 02-01/02-03).
   - What we know: D-09 replaces the *flag*; the digest's `_context()` formatting in `notify.py` still shows `pct` for most flags.
   - What's unclear: Whether a CORP-ACTION line showing a wildly wrong `+/-N%` (computed against a stale-for-one-run avg_cost) undermines the "don't mis-flag" intent even if the *action* flag itself is safe.
   - Recommendation: Have `notify.py`'s CORP-ACTION line omit the `pct` context entirely (like NO PRICE already does) rather than showing a number known to be transiently wrong — a small addition to `_context()`'s existing flag-based branching, not a new mechanism.

## Environment Availability

No new external dependencies. This phase adds only stdlib usage (`json`, `os`, `tempfile`, `datetime.timedelta`) and reuses already-installed, already-pinned packages from Phase 1.

| Dependency | Required By | Available | Version | Fallback |
|------------|--------------|-----------|---------|-----------|
| `yfinance` | PNL-04 `fast_info` lookup | not installed in this research sandbox, but pinned in `requirements.txt` | 1.5.1 (pinned) | n/a — already the project's chosen price source |
| Python stdlib (`json`, `os`, `tempfile`, `datetime`) | state.json persistence, trend/week math | Yes | 3.13.0 in this environment (project targets 3.11+) | n/a |

**Missing dependencies with no fallback:** none.
**Missing dependencies with fallback:** none — `yfinance` not being importable in this research sandbox is a sandbox artifact (package not installed here), not a project gap; it's correctly pinned in `requirements.txt` and already used successfully in Phase 1's `prices.py`.

## Security Domain

`security_enforcement` is not explicitly disabled in `.planning/config.json`; treated as enabled. This phase has a narrow surface: no new network endpoints, no user-facing auth, no new secrets. Most ASVS web categories don't apply to a CLI/cron pipeline with no HTTP server or session model.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|-----------------|---------|--------------------|
| V2 Authentication | No | No new auth surface this phase (Groww/Telegram auth unchanged from Phase 1). |
| V3 Session Management | No | No sessions; TOTP-derived token already handled in `broker.py`, untouched this phase. |
| V4 Access Control | No | Single-user personal script, no multi-tenant access model. |
| V5 Input Validation | Yes | `state.json` is read back every run — treat it as untrusted-ish input at the boundary: guard `json.load` with a `try/except (json.JSONDecodeError, FileNotFoundError)` that falls back to the empty-state shape (already the existing pattern for `FileNotFoundError`; extend to corrupt-JSON too, since a partially-written file from a crash mid-write is exactly what the atomic-write pattern above prevents, but defense-in-depth costs one extra `except` clause). |
| V6 Cryptography | No | No new cryptographic operations this phase. |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|------------------------|
| Corrupt/truncated `state.json` (e.g., process killed mid-write in a future non-atomic implementation) crashes every subsequent run | Denial of Service (self-inflicted) | Atomic write via temp-file + `os.replace` (Code Examples above) — the file on disk is always either the old complete version or the new complete version, never partial. |
| A stale/never-pruned `sentiment` or `snapshots` dict growing unbounded over years | Resource exhaustion (minor, git-diff-size class, not a security vuln proper) | D-05's bound (~10 snapshot entries, sentiment pruned to current holdings) already addresses this — carried forward from ARCHITECTURE.md's existing "Performance Traps" table. |

## Sources

### Primary (HIGH confidence)
- Existing project files read this session: `rules.py`, `sentinel.py`, `prices.py`, `broker.py`, `sentiment.py`, `notify.py`, `tests/test_rules.py`, `tests/test_prices.py` — ground truth for current contracts and shapes.
- `.planning/phases/02-durable-state-portfolio-telemetry/02-CONTEXT.md` — locked decisions D-01..D-10.
- `.planning/ROADMAP.md`, `.planning/REQUIREMENTS.md` — phase scope and requirement IDs.
- `.planning/research/ARCHITECTURE.md`, `STACK.md`, `PITFALLS.md` (Phase 1 research, already vetted) — corp-action pitfall (#1), peak-lifecycle pitfall (#2), and the rebuild-not-merge / date-keyed-snapshot patterns this phase directly extends.

### Secondary (MEDIUM confidence)
- [Groww help center — "Why has the average price reduced after receiving bonus?"](https://groww.in/help/stocks,-f&o-&-ipo/corporate-action/why-has-the-average-price-reduced-after-receiving-bonus--56) — CITED: describes account-level average-price/52-week-high adjustment after a bonus; does not explicitly confirm the TradeAPI's `average_price` field mirrors this.
- [Groww TradeAPI Portfolio docs](https://groww.in/trade-api/docs/python-sdk/portfolio) — CITED: field-level docs for `average_price` / `corporate_action_additional_quantity`; both described only in one-line generic terms, corp-action adjustment behavior not stated.
- yfinance `fast_info` attribute confirmation via GitHub issues #1518, #1360, #1381 and multiple third-party 2026 yfinance guides (Marketcalls, pythontutorials.net) — CITED: `fast_info.previous_close` and `fast_info.last_price` are real, distinct, documented-by-community attributes since yfinance v0.2.14.
- Python `os.replace` atomic-write pattern corroborated by multiple current (2026) guides (BSWEN, TheLinuxCode, dev.to) in addition to stdlib docs knowledge — CITED.

### Tertiary (LOW confidence)
- Whether `yf.download(period="5d")`'s current-session bar is truly "live" during market hours (vs. only finalizing at close) — not found explicitly stated in any source checked this session; based on long-standing common knowledge of Yahoo Finance's daily-bar behavior. Marked ASSUMED (A1 in Assumptions Log) — verify empirically at implementation time by running mid-session and comparing to the Groww app.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new dependencies; existing pins already verified in Phase 1.
- Architecture: HIGH — directly extends already-validated Phase 1 patterns (pure-core/imperative-shell, rebuild-not-merge, date-keyed snapshots) from the project's own prior research.
- Pitfalls: MEDIUM — the corp-action detection formula and peak-rescale recommendation are original engineering derivations (sound reasoning, not independently lab-verified against a real Groww bonus/split this session); the yfinance intraday-liveness assumption is LOW/ASSUMED and explicitly flagged for impl-time verification.

**Research date:** 2026-07-10
**Valid until:** 2026-08-09 (30 days — stack is stable; re-check sooner only if a real corporate action occurs in the account before then, since that's the actual empirical test of A1/A2)
