# Phase 2: Durable State & Portfolio Telemetry - Context

**Gathered:** 2026-07-09
**Status:** Ready for planning

<domain>
## Phase Boundary

Persist `state.json` across runs so the digest remembers per-symbol peaks and
portfolio history. Activates TRAIL WATCH (real peaks), reports P&L (overall +
day change + 5-day trend), appends a Friday weekly summary, caches sentiment,
and flags corporate-action-distorted cost instead of mis-flagging it.

Delivers: STATE-01..04, PNL-01..05, RULES-06.

Reading/writing state.json is in scope; **committing it back to the repo is
Phase 3** (RUN-03). Locally it's a file at repo root.

</domain>

<decisions>
## Implementation Decisions

### State shape & cadence (STATE-01..04)
- **D-01:** Run cadence is **market-hours hourly** (~9:15–15:30 IST weekdays, ~7 runs/day). This supersedes the original once-daily 08:30 design — a Phase-3 cron change (RUN-01). Captured here because it drives snapshot design.
- **D-02:** Snapshots are **keyed per calendar date** (one entry/day). Intraday reruns **overwrite** that day's entry → idempotent (STATE-04). Peak still updates on **every** run (captures intraday highs).
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
- **D-04:** `new_state` is **rebuilt from current holdings each run** (STATE-02): prior state is a read-only lookup. A symbol no longer held is dropped → its peak resets; rebuying re-seeds (STATE-03).
- **D-05:** `snapshots` bounded to the most recent ~10 dated entries (enough for a 5-day trend + weekly); prune older. `sentiment` bounded to current holdings.
- **D-06:** During market hours yfinance's last close ≈ today's live price, so intraday snapshots reflect current value (the `ltp` slot stays the generic "current price"). Purity of `rules.py` preserved — `today` and prior state are injected, no clock/IO in rules.

### P&L reporting (PNL-01..05)
- **D-07:** Header/report shows: overall unrealized P&L vs cost (PNL-01); **day change = today's value vs the prior *day's* stored snapshot** (PNL-02, not vs prior run); **5-trading-day trend** direction + % (PNL-03); intraday % when the price source exposes previous close (PNL-04). Compact, e.g. `Day +1.2% · 5d ↗ +3.4%`.
- **D-08:** Friday's digest appends a **weekly block** (PNL-05): best/worst **2–3 movers by % price change over the trading week** (from per-symbol snapshot history), week portfolio value change, and **flags-fired count** (sum of stored daily `flags_fired`).

### Corporate-action safety (RULES-06)
- **D-09:** Detect a distorted average cost via a **quantity jump vs stored prior `qty`** without a proportional cost basis change (bonus/split signature). On detection, that run **replaces the P&L-based flag (STOP/BOOK/AVERAGE) with a `CORP-ACTION` warning line** so a distorted cost can't fire a false trade. Weight-based TRIM and peak-based TRAIL WATCH still evaluate normally. Detection input (prior qty/avg_cost) comes from state → keep `rules.py` pure by passing it in.

### Sentiment caching
- **D-10:** Cache sentiment in `state.sentiment` keyed by symbol; reuse for the **same calendar day**, re-score next day. Hourly runs → ~**1 model call/day** total (first market-hours run scores; rest reuse), and it smooths the flaky-news problem. A cache miss/stale entry triggers a (batched) re-score for just the uncached AVERAGE candidates.

### Claude's Discretion
- Exact trend arrow glyphs / wording, weekly-block layout, and how many movers (2 vs 3).
- Prune thresholds (the ~10-entry bound) and the corp-action quantity-jump tolerance %.
- Whether day-change/trend live in the header or a small "📈 TELEMETRY" section.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### This phase
- `.planning/ROADMAP.md` — Phase 2 goal + success criteria (STATE-01..04, PNL-01..05, RULES-06)
- `.planning/REQUIREMENTS.md` — REQ text; note RULES-04 (tagging) SUPERSEDED, RULES-02 is the P&L ladder
- `.planning/phases/01-end-to-end-morning-digest/01-CONTEXT.md` — Phase 1 locked decisions (D-13 precedence, D-14 strict `>`, ladder)

### Existing code this phase extends
- `rules.py` — pure `evaluate(holdings, state, today)`; already seeds peaks from `state` (currently always `{}`). Phase 2 makes `state` real + adds corp-action input.
- `sentinel.py` — orchestrator; owns state load/save wiring + the sentiment call site
- `prices.py`, `broker.py`, `notify.py`, `sentiment.py` — price/holdings/digest/sentiment layers
- `docs/superpowers/specs/2026-07-09-groww-sentinel-design.md` — original design (state.json, peaks, trend intent)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `rules.evaluate(holdings, state, today)` already reads `state[sym]["peak"]` and emits `new_state` — Phase 2 populates/persists it rather than passing `{}`.
- `notify.format_digest(flags, portfolio)` already takes a `portfolio` dict with `total_value`/`overall_pnl_pct`/`date` — extend with day-change/trend/weekly fields.
- `sentiment.adjust(flags, api_key)` — add a cache read/write around the batched `score_batch` call (state-backed).

### Established Patterns
- Pure core / impure shell: `rules.py` stays pure (state injected); all IO (state.json read/write, prices, telegram, sentiment) at the edges. Keep it.
- `today` injected for determinism; corp-action + snapshot keying use it.

### Integration Points
- `sentinel.py` loads state.json → passes to `rules.evaluate` and `sentiment.adjust` → writes updated state.json. (The git commit-back of state.json is Phase 3, RUN-03.)

</code_context>

<specifics>
## Specific Ideas

- Digest header evolves to carry telemetry, e.g. `💰 ₹32.15L · P&L +17.1% · Day +1.2% · 5d ↗ +3.4%`.
- Friday-only weekly block sits at the bottom, above/below HOLDING summary.

</specifics>

<deferred>
## Deferred Ideas

- **Committing state.json back to the repo** each run → Phase 3 (RUN-03), needs `contents: write`.
- **Hourly market-hours cron** (D-01) is a Phase 3 scheduling change (RUN-01 was 08:30 pre-market) — implement the schedule there; Phase 2 only assumes per-day snapshot semantics.
- **Sturdier news source** than yfinance (Google News RSS fallback) — improves sentiment reliability; not required for Phase 2 (same-day cache already reduces exposure). Revisit if flakiness persists.
- Contribution-to-portfolio weekly view (alternative to %-movers) — considered, deferred.

</deferred>

---

*Phase: 2-Durable State & Portfolio Telemetry*
*Context gathered: 2026-07-09*
