# Portfolio Analyst Layer — Design

**Date:** 2026-07-10
**Status:** Approved
**Supersedes:** `sentiment.py` (narrow AVERAGE→AVOID news gate)

## Goal

Replace the one-directional news-sentiment gate with a **senior-equity-analyst overlay**
that reasons over the whole portfolio in a single LLM call, produces a portfolio brief,
and may adjust per-stock action flags — transparently and only when confident.

`rules.py` stays 100% pure and unit-tested. The analyst is an explicit layer on top:
every digest can show "rules said X → analyst changed to Y (why)".

## Decisions (from brainstorming)

- **Scope:** full portfolio analyst (per-stock + portfolio-level: concentration, sector, macro).
- **Authority:** analyst may adjust flags (LLM-driven), but the deterministic core is preserved
  as a separate, tested layer — the override is applied by a *pure* function, not by mutating rules.
- **Guardrail:** analyst must attach `confidence` (high/med/low) + `thesis`. **Apply the override
  only when `confidence == high`.** med/low → deterministic flag holds, analyst view shown as a
  non-applied suggestion. Nothing changes silently.
- Nothing auto-trades; every flag is human-reviewed before execution. The analyst adjusts
  *recommendations*, not money.

## Inputs (all free: yfinance + Gemini)

Per stock: deterministic flag, P&L%, weight, %-below-peak, headlines, fundamentals
(`trailingPE`, `forwardPE`, sector, `recommendationKey`, `targetMeanPrice`, `numberOfAnalystOpinions`),
momentum (vs cost, vs peak).
Portfolio: total value, position weights, sector concentration (weights aggregated by sector).
Macro: NIFTY 50 (`^NSEI`) 5-day trend + India VIX (`^INDIAVIX`).

## LLM call

ONE Gemini call, whole portfolio in context, prompt casts it as a senior analyst.
Returns JSON:
- `brief`: `{regime, stance, concentration}` — short strings
- `stocks[SYM]`: `{flag, confidence, thesis, key_risk}` — `flag` constrained to the rules vocabulary
  plus `AVOID`.

Same-day cached (brief carries a date; a cached brief for today reuses all per-symbol scores → ~1
call/day, hourly reruns free). 15s timeout, 1 attempt. Any failure (no key, no data, bad JSON) →
pure deterministic flags, brief omitted. Never breaks or delays a run beyond the timeout.

## Override application (pure, tested)

`apply_overrides(flags, scores, holdings, total_value)`:
- `NO PRICE` / `CORP ACTION` flags: never touched.
- analyst flag == rules flag: unchanged.
- differs **and confidence == high**: apply analyst flag; re-size via `rules.size_position`;
  tag `analyst_override = {was, confidence, thesis, key_risk}`.
- differs, med/low: keep deterministic flag; attach `analyst_suggestion` (shown, not applied).

## Digest

New `🧠 ANALYST BRIEF` block after the header (regime / stance / concentration).
Overridden line: analyst's emoji/verb + `(analyst · was HOLD)` tag + `↳ thesis: … risk: …`.
Suggestion line: original flag + `↳ analyst (med): … [not applied]`.

## Modules

- **new `analyst.py`** — enrich (fundamentals) + prompt + `score_portfolio` + `apply_overrides` (pure)
  + `analyze` orchestrator. Replaces `sentiment.py`.
- **`prices.py`** — add `get_macro()` (`^NSEI`, `^INDIAVIX`), best-effort.
- **`rules.py`** — add public `size_position` wrapper over `_shares`; otherwise untouched (stays pure).
- **`notify.py`** — brief block + override/suggestion rendering.
- **`state.py`** — cache key `sentiment` → `analyst` (`{brief, SYM:{...}}`).
- **`sentinel.py`** — compute portfolio before analyst; swap `sentiment.adjust` → `analyst.analyze`;
  pass `brief` to `format_digest`; save under `analyst`.

## Testing

`rules.py` unchanged. `apply_overrides`, confidence gating, brief/line rendering, and `analyze`
caching are pure or mocked-I/O → unit-tested. Fetchers mocked. Keeps the deterministic-core
guarantee and the 80% bar.

## Senior-dev caveats

- yfinance `.info` is slow/flaky per symbol — every fundamental field best-effort; a missing P/E
  never blocks the analyst.
- `confidence` is LLM self-reported, not calibrated. The struck-through original flag is the honesty check.
