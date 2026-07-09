# Feature Research

**Domain:** Personal daily stock-holdings advisory bot (single-user, rules-based, Telegram digest)
**Researched:** 2026-07-09
**Confidence:** MEDIUM (design-spec claims are HIGH — curated, already-approved; general market conventions on thresholds/message design are MEDIUM, sourced from trading-education blogs and OSS examples, not academic backtests)

## Feature Landscape

### Threshold Reality Check (spec vs. market convention)

The spec's seven flags are the right primitive set — they cover entry (averaging), exit-for-profit
(booking), exit-for-loss (stop), long-term erosion (trailing watch), concentration risk (trim), and
the two required null states (hold, untagged). No primitive is missing that a personal profit-booking
+ averaging strategy needs, and none of the seven is superfluous. Where the spec's *numbers* sit
relative to general convention, gathered from trading-education sources (MEDIUM confidence — see
Sources):

| Flag | Spec threshold | General convention | Verdict |
|------|-----------------|---------------------|---------|
| TRAIL WATCH (core) | >20% below peak | Swing-trading trailing stops commonly run 5–10%, trend-following 5–10% | Wider than swing-trading norms — correct for this use case: `core` holdings are buy-and-hold, and a tight trail would fire on ordinary volatility. Deliberately loose to control noise, not a miscalibration. |
| STOP HIT (tactical) | >12% from avg cost, or >15% below peak | 8–10% common for disciplined swing trades; up to 15% seen for volatile names | Sits at the loose end but within range, consistent with NSE mid/small-cap volatility being higher than the US-centric sources this convention comes from |
| TRIM | portfolio weight >10% | A 2007 Journal of Financial Planning study found ~20% *relative* deviation from an asset's target weight is closer to optimal than 10–15% bands | Different model, not a contradiction: the study's band is relative-to-target-weight for a diversified rebalancing plan; the spec uses an absolute concentration cap with no per-holding target weight. Absolute 10% is a reasonable simplification for a solo discretionary book with no formal target-weight model — flag as a considered simplification, not copy the study's number in blindly. |
| BOOK 50% (tactical) | >25% from avg cost | No strong single convention; "sell half on strength" is a common discretionary tactic without a fixed number | Reasonable, personal-preference threshold — nothing in the research argues for a different number |
| AVG CANDIDATE (core) | -10/-20/-30% tiers, weight <10% | Tiered/staged dip-buying is a well-established DCA pattern; no fixed convention on tier size | Reasonable, personal-preference tiering |

Net: no threshold change is recommended from research alone. The one genuine design tension worth a
deliberate (not default) decision is TRIM's absolute-vs-relative model — worth a one-line note in
the spec/config confirming it's intentional, so a future "why not 20%" question has a documented
answer instead of reopening the debate.

### Table Stakes (Users Expect These)

For a solo-user advisory digest, "users" = the one person who will silently stop trusting it the first time it's wrong, noisy, or quiet-when-it-shouldn't-be. Table stakes here means: **missing it makes the tool unsafe or unusable**, not "missing it looks unpolished."

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Per-stock flag: HOLD (no-op default) | Without a default "nothing to do" state, every stock would need an explicit rule outcome — noisy and error-prone | LOW | Falls out naturally as the "else" branch of the rules engine |
| Per-stock flag: UNTAGGED (config gap) | A stock bought but not yet classified `core`/`tactical` must never silently get a guessed bucket — wrong bucket = wrong rule = wrong money decision | LOW | Pure config-lookup miss; must fire before any bucket-specific rule evaluates |
| Per-stock flag: STOP HIT (tactical) | Any personal trading strategy needs a defined loss-exit signal or losses run unchecked | LOW | Straightforward threshold on `pnl_pct` and/or `pct_below_peak` |
| Per-stock flag: AVG CANDIDATE (core) | Averaging strategy's core mechanic — without it the "averaging" half of the strategy doesn't exist | LOW–MEDIUM | Tiered (10/20/30%) thresholds + weight cap; needs the manual 3-gate reminder attached, see below |
| Per-stock flag: TRIM (concentration) | Single biggest silent portfolio risk for a solo retail investor is one stock growing to dominate the book without anyone noticing | LOW | Requires portfolio-wide weight calc (depends on all LTPs fetched that run) |
| Manual-gate reminder text on AVG CANDIDATE | This is what keeps the bot "advisory" instead of "auto-pilot" — a flag with no reminder invites blind action | LOW | Must render as part of the flag line, not a separable feature — coupling is intentional |
| Fetch-failure notification (never silent) | A digest that goes silent on error is indistinguishable from "all quiet" — destroys trust in the one signal (silence = OK) the whole design relies on | LOW–MEDIUM | Requires notify layer to work independently of the broker/rules layer that failed |
| "All quiet" heartbeat when no flags fire | Same trust mechanism as above from the other direction: proves the job ran today | LOW | One-line fallback message when every stock is HOLD |
| Non-HOLD-only filtering in digest | The #1 lever against alert fatigue — a daily message listing all 20+ holdings trains the user to skim past it within a week | LOW | Directly implements the "low-noise" requirement from PROJECT.md |
| Overall unrealized P&L (current value vs. cost basis) | The single most basic "how am I doing" number; a portfolio tool without it isn't a portfolio tool | LOW | Pure arithmetic over holdings + LTPs already fetched for flags |
| Per-symbol peak tracking (state.json) | Required infrastructure for both TRAIL WATCH and STOP HIT's peak-based leg — without persisted peaks, "how far below high" can't exist across runs | MEDIUM | Needs reset-on-exit / re-seed-on-rebuy logic to avoid stale peaks corrupting future flags |
| Holiday-aware skip (no run on NSE holidays) | Running pre-market against stale/holiday prices produces confidently wrong flags — worse than not running | LOW | Needs a maintained NSE holiday calendar; small but real maintenance burden |
| Startup secret validation (fail loud, name the missing one) | A silent auth failure in a headless cron job is a debugging nightmare with no logs to tail | LOW | Cheap insurance against the most likely first-week failure mode |

### Differentiators (Competitive Advantage)

Not required for the bot to be trustworthy, but meaningfully improve the "I never have to open the app" value proposition.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| TRAIL WATCH flag (core, peak-based) | Distinguishes "down from my cost" (temporary, maybe fine) from "down from its own high and hasn't recovered" (a real deterioration signal) — most personal trackers only do cost-basis P&L | MEDIUM | Depends on persisted peak tracking (table stakes above) |
| BOOK 50% flag (tactical profit-taking) | Encodes a specific, disciplined "sell half on strength" tactic rather than leaving profit-taking to memory/mood | LOW | Symmetric counterpart to STOP HIT; reuses the same threshold pattern |
| Day snapshot delta (vs. prior run) | Gives a "what changed since yesterday" number even pre-market, when true intraday % isn't available from the broker | LOW–MEDIUM | Works without needing a prev-close field from the LTP endpoint — good fallback design |
| N-day trend direction | Adds momentum context ("portfolio's been climbing for 3 sessions") beyond a single day's delta | LOW | Purely derived from snapshot history already being stored — cheap to add once daily snapshots exist |
| Weekly summary (Friday-only append) | Best/worst movers + week value change + flags-fired count gives a "week in review" without a second cron job or extra message | MEDIUM | Depends on daily snapshots existing for the full week; appended block, not a separate send |
| Grouped/triaged message layout (🔴 ACTION / 🟢 OPPORTUNITY / ⚠️ UNTAGGED) | Turns a flat list into a decision-ready triage view — matches the trading-education best practice of "have your response ready before the alert fires," because each group implies a different response | LOW | Pure formatting in `notify.py`; no new data needed |
| Inline reason/number on each flag line (e.g., "-13% vs avg") | Lets the user sanity-check the rule fired correctly without opening a spreadsheet — builds trust in a deterministic system | LOW | Already implied by spec's message shape; worth calling out as deliberate, not incidental |
| Corporate-action adjustment awareness (bonus/split guard) | Prevents a stock split from producing a phantom STOP HIT or AVG CANDIDATE the day after a bonus issue | MEDIUM | Spec correctly defers this to "verify at impl, don't pre-build" — only add real handling if `growwapi`'s `average_price` isn't already split-adjusted |

### Anti-Features (Commonly Requested, Often Problematic)

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|------------------|-------------|
| Auto-trading / order placement | "Just do it automatically, why wake me up" | Removes the human judgment gate that is the whole design's safety property; turns a personal-strategy tool into an unsupervised money-moving system; regulatory/liability surface for what's currently a personal script | Keep flags advisory; the 3-gate manual check is the feature, not friction |
| Auto-fundamentals (earnings, debt, news, sector checks) | "The bot could just check if the news is bad" | Judgment on "is this fall company-specific or market-wide" is exactly the kind of soft signal that's easy to get subtly wrong and hard to unwind after the fact; also pulls in paid/unofficial data sources outside the "official API only" constraint | Leave the 3-gate check as an explicit manual step, reminded by the message, not executed by it |
| Web dashboard / database / charts | "Wouldn't a dashboard be nicer to look at" | Doubles the UI surface (Telegram + web) for a single user; needs hosting beyond the "no always-on server" constraint; historical charting duplicates the sibling `groww-dashboard` project's job | Telegram message is the whole UI; defer historical views to the sibling project |
| Trade history / tax / charges reconstruction | "Since we're pulling holdings anyway..." | Different data shape (executed trades, not live positions), different cadence (annual/tax-season, not daily), scope creep that blurs the boundary with `groww-dashboard` | Keep Sentinel forward-looking only; tax/history stays in the other project |
| Multi-channel notify (WhatsApp/email/SMS) | "What if Telegram is down" | WhatsApp needs pre-approved templates that fight a dynamic daily digest; email/SMS add channel-specific formatting and delivery-failure handling for a single reader with no redundancy benefit | Keep the notify layer swappable in code, but ship Telegram-only for v1 |
| Real-time / intraday streaming alerts | "Why wait for one digest, tell me the moment it happens" | Breaks the "read once at breakfast" trust model this whole design optimizes for; requires an always-on process, violating the GitHub Actions cron constraint; converts a calm daily read into a stream to monitor | One deterministic run per weekday morning; if a threshold is crossed intraday, it'll show up tomorrow — that's the intended cadence |
| ML/adaptive threshold tuning | "The bot could learn my preferences over time" | Undermines the explicit design goal of deterministic, auditable rules with thresholds as named constants in one tunable place; an ML model is a black box exactly where trust matters most (the money path) | Hand-tune the named constants when the strategy changes; keep the rules engine pure and testable |
| Backtesting / strategy-optimization tooling | "Could tell me if 20% or 25% BOOK threshold performs better" | Different problem (historical analysis) from this tool's problem (daily forward-looking advisory); needs historical price ingestion beyond what the live-data endpoint provides | Treat threshold changes as manual strategy decisions, tune and observe live rather than backtest |
| Daily re-alerting on an unchanged, already-seen flag forever | "The bot already reminded me, wouldn't hurt to remind again" — actually the current spec's default behavior | Not disqualifying for v1 (a still-open STOP HIT *should* keep showing until acted on), but at scale becomes the exact "20 lines every morning" fatigue the non-HOLD filter was built to prevent, especially for a stock stuck 25% below peak for months | Consider (post-v1) a "flag unchanged since day N" annotation or periodic re-surface instead of full daily repeat — noted as a gap below, not a v1 blocker |

## Feature Dependencies

```
config.yaml (core/tactical tagging)
    └──requires──> UNTAGGED flag has a reference to check against

state.json (per-symbol peak tracking)
    └──requires──> TRAIL WATCH flag (>20% below peak)
    └──requires──> STOP HIT flag's peak-based leg (>15% below peak)
    └──requires──> peak reset-on-exit / re-seed-on-rebuy logic (else stale peaks corrupt flags)

state.json (daily snapshots, date-keyed)
    └──requires──> Day snapshot delta
                       └──enhances──> N-day trend direction
                                          └──requires──> Weekly summary (best/worst movers, week Δ, flags-fired count)

All-symbol LTP fetch succeeding in the same run
    └──requires──> Portfolio weight_pct calc (needs total portfolio value)
                       └──requires──> TRIM flag
    └──requires──> "All quiet" heartbeat being trustworthy (partial fetch must be noted, not hidden)

AVG CANDIDATE flag ──requires (rendering)──> Manual-gate reminder text
    (these are not separable features — shipping one without the other reintroduces the auto-pilot risk)

Fetch-failure notification ──requires──> notify.py reachable independently of broker.py's failure
    (if the same failure that breaks the fetch also breaks notify, the "never silent" guarantee breaks)

Corporate-action adjustment handling ──conflicts (if unnecessary)──> premature complexity
    (spec correctly gates this behind "verify average_price is already adjusted" before building anything)
```

### Dependency Notes

- **TRAIL WATCH and the peak-leg of STOP HIT both require durable per-symbol peak state.** This is the single piece of state infrastructure that unlocks two of the seven flags — get the reset/re-seed logic right once, both flags inherit correctness.
- **Weekly summary is a pure derivative of daily snapshots, not new plumbing.** If daily snapshot writing is skipped or breaks silently for a day, Friday's "week value change" silently misreports — the weekly feature is only as reliable as five days of prior daily runs.
- **TRIM depends on *all* LTPs resolving in the same run**, because portfolio weight is relative to total value. A partial-fetch run (one symbol's LTP missing) either needs to exclude that symbol from the weight denominator too, or the TRIM flag becomes silently wrong for every other stock that run — worth being explicit about in the rules engine, not just noting the missing symbol in the message.
- **Manual-gate reminder and AVG CANDIDATE are one feature, not two.** Any refactor that could produce an AVG CANDIDATE line without the reminder text (e.g., a message-length trim) reopens the auto-pilot risk this whole design exists to avoid.

## MVP Definition

### Launch With (v1)

Everything already in PROJECT.md's Active requirements is correctly scoped as v1 — nothing here should be cut further:

- [ ] All 7 flags (AVG CANDIDATE, TRAIL WATCH, TRIM, BOOK 50%, STOP HIT, HOLD, UNTAGGED) — the rules primitive set is right-sized, see Confidence Assessment below
- [ ] config.yaml core/tactical tagging + UNTAGGED safety net — without this, flags for wrongly-bucketed stocks are worse than no flags
- [ ] state.json peak tracking with reset/re-seed — required for 2 of 7 flags
- [ ] Overall unrealized P&L + day snapshot delta — minimum viable "how am I doing today"
- [ ] Grouped, non-HOLD-only, reason-annotated message + "all quiet" heartbeat — this *is* the low-noise, trustworthy digest the project exists to deliver
- [ ] Manual-gate reminder text on AVG CANDIDATE — non-negotiable per Core Value ("does not make the final decision")
- [ ] Fetch-failure notification + secret validation at startup — the minimum reliability bar for an unsupervised daily cron
- [ ] Holiday-calendar skip — cheap, prevents a class of confusing false signals from day one

### Add After Validation (v1.x)

Add once the daily digest has run for a couple of weeks and the core flags/thresholds feel right:

- [ ] N-day trend direction — trivial once daily snapshots are proven reliable; add when the single-day delta starts feeling context-free
- [ ] Weekly summary (Friday block) — add once a full week of clean daily snapshots exists to summarize; don't ship it against untested snapshot data
- [ ] Corporate-action adjustment handling — only if the impl-time check shows `growwapi`'s `average_price` is *not* already split/bonus-adjusted

### Future Consideration (v2+)

Defer until the v1 digest has been lived with for a while and a specific pain point (not a hypothetical one) shows up:

- [ ] Flag-repeat dampening (e.g., "still open, day 6" instead of a full repeat) — defer until daily repetition actually causes fatigue in practice, not before
- [ ] Tax-lot / holding-period-aware flag (e.g., annotate when a position crosses the 1-year LTCG boundary in India) — genuinely useful but overlaps the sibling `groww-dashboard` project's tax domain; coordinate boundary before building
- [ ] Per-symbol threshold overrides (vs. one global constant set) — only if a specific holding's volatility profile makes the global thresholds consistently wrong for it
- [ ] Multi-account / multi-broker support — irrelevant until there's a second account to track

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| 7-flag rules engine (all flags) | HIGH | MEDIUM | P1 |
| Manual-gate reminder on AVG CANDIDATE | HIGH | LOW | P1 |
| Non-HOLD filtering + all-quiet heartbeat | HIGH | LOW | P1 |
| Fetch-failure notification + secret validation | HIGH | LOW | P1 |
| Peak tracking (state.json, reset/re-seed) | HIGH | MEDIUM | P1 |
| Overall P&L + day snapshot delta | HIGH | LOW | P1 |
| Holiday-calendar skip | MEDIUM | LOW | P1 |
| N-day trend direction | MEDIUM | LOW | P2 |
| Weekly summary block | MEDIUM | MEDIUM | P2 |
| Corporate-action adjustment handling | LOW–MEDIUM (contingent) | MEDIUM | P2 (conditional) |
| Flag-repeat dampening | LOW (unproven need) | MEDIUM | P3 |
| Tax-lot/LTCG-aware flag | MEDIUM | MEDIUM–HIGH | P3 |
| Per-symbol threshold overrides | LOW (unproven need) | MEDIUM | P3 |

**Priority key:**
- P1: Must have for launch
- P2: Should have, add when possible
- P3: Nice to have, future consideration

## Competitor Feature Analysis

Direct competitors are sparse — this is a narrow, personal, rules-encoded niche — so the comparison is against adjacent categories: general market Telegram bots, commercial multi-channel alert products, and crypto trading bots (which have the most mature trailing-stop/take-profit UX).

| Feature | Stonky (OSS market bot) | PortfolioTrackr (commercial alerts) | Crypto trading bots | Groww Sentinel's approach |
|---------|--------------------------|--------------------------------------|----------------------|----------------------------|
| Trailing stop | Not present (momentum lists only) | Simple price-crossing alerts | Full trailing stop + take-profit attached to live orders | Peak-tracked, watch-only (no order execution) — deliberately softer than a trading bot's trailing stop |
| Averaging/DCA | Manual buy/sell logging, no rule-based trigger | Not a rules engine, just price alerts | DCA as an execution strategy, not an advisory flag | Rule-based AVG CANDIDATE *candidate* + mandatory manual 3-gate check — most conservative of the four |
| Position sizing / concentration | Not present | Not present | Present in some bots as risk % per trade | TRIM flag on portfolio weight — unique among these for being *portfolio-relative*, not per-trade |
| Take-profit / booking | P&L reporting on completed sells only (retrospective) | Price-target alerts | Full auto take-profit execution | BOOK 50% is advisory only — flags, doesn't execute |
| Channel | Telegram only | WhatsApp, Telegram, email, SMS | Usually in-bot/exchange UI, some Telegram | Telegram only by design (see anti-features) |
| Decision automation | None (query/reporting bot) | None (alerting only) | Full automation available | None by design — the manual gate is the differentiator, not a gap |

**Takeaway:** every adjacent category either does less rule-based advisory work (Stonky, PortfolioTrackr — pure alerting/reporting) or does more automated execution (crypto bots). Groww Sentinel's position — deterministic personal-strategy rules, always advisory, always manually gated — isn't a feature gap relative to competitors; it's the deliberate, correctly-scoped middle that this specific user wants. Nothing in the competitive landscape argues for adding automation.

## Sources

- [Groww Sentinel design spec](../../docs/superpowers/specs/2026-07-09-groww-sentinel-design.md) — HIGH confidence, project-internal, already approved
- [antirez/stonky](https://github.com/antirez/stonky) — OSS Telegram market bot, fetched via WebFetch — MEDIUM confidence (single OSS example, not a maintained product)
- [PortfolioTrackr — Telegram stock alerts](https://portfoliotrackr.com/blog/telegram-stock-alerts) and [Stock Portfolio Alerts](https://portfoliotrackr.com/alerts) — MEDIUM confidence (commercial marketing content, not independently verified)
- [TradingWithRayner — Trailing stop-loss techniques](https://www.tradingwithrayner.com/trailing-stop-loss/) and [Ticker Daily — Stop-loss strategies](https://tickerdaily.com/learn/swing-trading/stop-losses) — MEDIUM confidence (trading-education blogs; directionally consistent with each other on 3–15% trailing ranges for swing trading)
- [Kitces — Optimal Rebalancing thresholds](https://www.kitces.com/blog/best-opportunistic-rebalancing-frequency-time-horizons-vs-tolerance-band-thresholds/) — MEDIUM-HIGH confidence (references a 2007 Journal of Financial Planning study; more rigorous than the trading blogs, used only to flag a design tension, not to override the spec)
- [QuantifiedStrategies — Position sizing strategies](https://www.quantifiedstrategies.com/position-sizing-strategies/) — MEDIUM confidence (aggregator/blog content)

---
*Feature research for: personal stock-holdings advisory bot (Groww Sentinel)*
*Researched: 2026-07-09*
