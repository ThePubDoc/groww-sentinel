"""Senior-equity-analyst overlay (optional, impure I/O).

Supersedes the old narrow news-sentiment gate. Runs AFTER the pure rules engine:
reasons over the whole portfolio in ONE Gemini call (per-stock news + fundamentals
+ momentum, portfolio concentration, macro regime) and returns

  1. a short portfolio `brief` (regime / stance / concentration), and
  2. a per-stock verdict {flag, confidence, thesis, key_risk}.

`apply_overrides` (pure) then reconciles the analyst's verdict with the deterministic
flag under ONE guardrail: an override lands ONLY when confidence == "high"; med/low
verdicts that disagree are shown as non-applied suggestions, never silently applied.
rules.py stays untouched and fully deterministic -- this layer is an explicit,
human-reviewed overlay on top of it.

Disabled (no GEMINI_API_KEY) -> pure no-op. Any failure (no data, API error, bad
JSON) falls back to the deterministic flags with no brief -- the analyst can never
break or stall a run beyond its bounded timeout. Same-day cached: a brief already
built today reuses all per-stock verdicts, so hourly reruns collapse to ~1 call/day.
"""

import json
import logging
import sys
import warnings

import yfinance as yf

import prices
import rules

logging.getLogger("yfinance").setLevel(logging.CRITICAL)

MODEL = "gemini-3.1-flash-lite"
HEADLINE_LIMIT = 6
AVOID = "AVOID"
HIGH = "high"

# analyst may return any deterministic action flag plus AVOID; NO PRICE / CORP
# ACTION are mechanical and never handed to (or overridden by) the analyst.
_ALLOWED_FLAGS = {
    rules.STOP, rules.TRIM, rules.BOOK_50, rules.BOOK_25,
    rules.TRAIL_WATCH, rules.AVERAGE, rules.HOLD, AVOID,
}
_UNSCORED_FLAGS = {rules.NO_PRICE, rules.CORP_ACTION}
_FUND_KEYS = (
    "trailingPE", "forwardPE", "sector", "recommendationKey",
    "targetMeanPrice", "numberOfAnalystOpinions",
)


def fetch_headlines(symbol: str, limit: int = HEADLINE_LIMIT) -> list[str]:
    """Free per-ticker headlines via yfinance (<symbol>.NS); [] on any failure."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            items = yf.Ticker(f"{symbol}.NS").news or []
    except Exception:
        return []
    titles = []
    for it in items[:limit]:
        content = it.get("content") if isinstance(it.get("content"), dict) else it
        title = (content or {}).get("title")
        if title:
            titles.append(title)
    return titles


def fetch_fundamentals(symbol: str) -> dict:
    """Best-effort valuation/rating snapshot via yfinance `.info`. Every field is
    optional -- `.info` is slow and flaky, so a missing key just drops out of the
    prompt rather than blocking the analyst. {} on total failure."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            info = yf.Ticker(f"{symbol}.NS").info or {}
    except Exception:
        return {}
    return {k: info.get(k) for k in _FUND_KEYS if info.get(k) is not None}


def _sector_weights(flags: list[dict], sectors: dict[str, str]) -> dict[str, float]:
    """Aggregate position weights by sector (unknown sector -> 'Unknown')."""
    agg: dict[str, float] = {}
    for f in flags:
        w = f.get("weight")
        if not w:
            continue
        sector = sectors.get(f["symbol"]) or "Unknown"
        agg[sector] = agg.get(sector, 0.0) + w
    return agg


def _build_prompt(flags, portfolio, funds, macro, sector_weights) -> str:
    """Assemble the single analyst prompt. Pure string assembly."""
    macro_bits = []
    if macro.get("nifty_5d_pct") is not None:
        macro_bits.append(f"NIFTY50 {macro['nifty_5d_pct'] * 100:+.1f}% over 5d")
    if macro.get("vix") is not None:
        macro_bits.append(f"India VIX {macro['vix']:.1f}")
    macro_line = "; ".join(macro_bits) or "unavailable"

    conc = ", ".join(
        f"{s} {w * 100:.0f}%" for s, w in
        sorted(sector_weights.items(), key=lambda kv: kv[1], reverse=True)
    ) or "unavailable"

    blocks = []
    for f in flags:
        if f["flag"] in _UNSCORED_FLAGS:
            continue
        sym = f["symbol"]
        parts = [f"{sym}: rules={f['flag']}"]
        if f.get("pct") is not None:
            parts.append(f"pnl={f['pct'] * 100:+.0f}%")
        if f.get("weight") is not None:
            parts.append(f"weight={f['weight'] * 100:.0f}%")
        if f.get("pct_below_peak"):
            parts.append(f"{f['pct_below_peak'] * 100:.0f}%_below_peak")
        for k, v in funds.get(sym, {}).items():
            parts.append(f"{k}={v}")
        heads = funds.get(sym, {}).get("_headlines", [])
        block = "  ".join(parts)
        if heads:
            block += "\n    news:\n" + "\n".join(f"      - {h}" for h in heads)
        blocks.append(block)

    return (
        "You are a senior Indian-equity portfolio analyst. Review this portfolio and "
        "each holding, then judge -- for the OWNER deciding what to do TODAY -- the "
        "single best action per stock, weighing the deterministic rules verdict against "
        "valuation, momentum, news, sector concentration and the market regime.\n\n"
        f"Portfolio: total P&L {portfolio.get('overall_pnl_pct', 0) * 100:+.1f}%. "
        f"Sector concentration: {conc}. Market regime: {macro_line}.\n\n"
        f"Holdings:\n" + "\n\n".join(blocks) + "\n\n"
        "Reply ONLY compact JSON with two keys:\n"
        '  "brief": {"regime":"<=16 words","stance":"<=16 words","concentration":"<=16 words"}\n'
        '  "stocks": { "<TICKER>": {"flag":"<one of '
        f"{'|'.join(sorted(_ALLOWED_FLAGS))}"
        '>","confidence":"high|medium|low","thesis":"<=15 words","key_risk":"<=10 words"} }\n'
        "Only set flag different from the rules verdict when you genuinely disagree; "
        "reserve \"high\" confidence for clear, well-supported calls."
    )


def _make_client(api_key: str):
    """Bounded Gemini client (15s timeout, 1 attempt) -- a slow/broken key must
    not add many seconds to an unattended run. Isolated so tests can stub it."""
    from google import genai
    from google.genai import types

    return genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(timeout=15_000, retry_options=types.HttpRetryOptions(attempts=1)),
    )


def score_portfolio(client, flags, portfolio, funds, macro, sector_weights) -> dict:
    """ONE Gemini call -> {"brief": {...}, "stocks": {sym: {...}}}. Raises on
    API/parse error (caller guards)."""
    prompt = _build_prompt(flags, portfolio, funds, macro, sector_weights)
    resp = client.models.generate_content(
        model=MODEL,
        contents=prompt,
        config={
            "response_mime_type": "application/json",
            # ~45 output tokens/holding (flag+confidence+thesis+key_risk); a real
            # portfolio is 30-40 names, so 1200 truncated the JSON mid-string and
            # json.loads blew up. 8192 = ~4x headroom (fits ~150 holdings).
            "max_output_tokens": 8192,
            "thinking_config": {"thinking_budget": 0},
        },
    )
    data = json.loads(resp.text)
    brief = data.get("brief") if isinstance(data.get("brief"), dict) else {}
    stocks = data.get("stocks") if isinstance(data.get("stocks"), dict) else {}
    clean = {}
    for sym, v in stocks.items():
        if not isinstance(v, dict):
            continue
        flag = v.get("flag")
        if flag not in _ALLOWED_FLAGS:
            continue
        clean[sym] = {
            "flag": flag,
            "confidence": (v.get("confidence") or "low").lower(),
            "thesis": v.get("thesis", ""),
            "key_risk": v.get("key_risk", ""),
        }
    return {"brief": brief, "stocks": clean}


def apply_overrides(flags: list[dict], scores: dict, holdings: list[dict],
                    total_value: float) -> list[dict]:
    """PURE. Reconcile analyst verdicts with deterministic flags under the
    high-confidence guardrail.

    - NO PRICE / CORP ACTION: never touched.
    - analyst agrees, or no verdict: flag unchanged.
    - disagrees & confidence == high: APPLY analyst flag, re-size via
      rules.size_position, tag `analyst_override`.
    - disagrees & medium/low: keep deterministic flag, attach `analyst_suggestion`
      (shown in the digest, NOT applied).
    """
    by_symbol = {h["symbol"]: h for h in holdings}
    out = []
    for f in flags:
        verdict = scores.get(f["symbol"])
        if not verdict or f["flag"] in _UNSCORED_FLAGS:
            out.append(f)
            continue

        a_flag = verdict.get("flag")
        note = {
            "confidence": verdict.get("confidence"),
            "thesis": verdict.get("thesis", ""),
            "key_risk": verdict.get("key_risk", ""),
        }

        if not a_flag or a_flag == f["flag"]:
            out.append(f)
            continue

        if verdict.get("confidence") == HIGH:
            h = by_symbol.get(f["symbol"], {})
            qty, ltp = h.get("qty"), h.get("ltp")
            shares = rules.size_position(a_flag, qty, ltp, total_value) if ltp else 0
            g = dict(f)
            g["flag"] = a_flag
            g["shares"] = shares
            g["value"] = shares * ltp if ltp else 0.0
            g["reminder"] = a_flag == rules.AVERAGE
            g["analyst_override"] = {"was": f["flag"], **note}
            out.append(g)
        else:
            g = dict(f)
            g["analyst_suggestion"] = {"flag": a_flag, **note}
            out.append(g)
    return out


def analyze(flags, portfolio, holdings, api_key, cache, today):
    """Orchestrate the analyst overlay. Returns (flags, brief, new_cache).

    No key -> (flags, None, cache) no-op. Same-day cache (brief dated today)
    reuses all verdicts with zero fetch/model calls. Any failure degrades to the
    deterministic flags with brief=None; the run is never broken or stalled.
    `new_cache` = {"brief": {...,"date"}, SYM: {...,"date"}} pruned to current
    holdings (D-05, bounded)."""
    if not api_key:
        return flags, None, cache

    today_str = today.isoformat()
    total_value = portfolio.get("total_value", 0.0)
    scorable = [f for f in flags if f["flag"] not in _UNSCORED_FLAGS]

    cached_brief = cache.get("brief") if isinstance(cache.get("brief"), dict) else None
    if cached_brief and cached_brief.get("date") == today_str:
        scores = {f["symbol"]: cache[f["symbol"]] for f in scorable if f["symbol"] in cache}
        out = apply_overrides(flags, scores, holdings, total_value)
        return out, cached_brief, cache

    funds = {}
    for f in scorable:
        sym = f["symbol"]
        data = fetch_fundamentals(sym)
        heads = fetch_headlines(sym)
        if heads:
            data["_headlines"] = heads
        funds[sym] = data

    macro = prices.get_macro()
    sector_weights = _sector_weights(flags, {s: d.get("sector") for s, d in funds.items()})

    try:
        client = _make_client(api_key)
        result = score_portfolio(client, flags, portfolio, funds, macro, sector_weights)
    except Exception as exc:
        # Never break the run -- but fail LOUD (redacted): a silently-skipped
        # analyst is indistinguishable from "nothing to add". Print the reason
        # to stderr so a broken key/model/SDK surfaces in the run logs.
        reason = str(exc)
        if api_key:
            reason = reason.replace(api_key, "[KEY]")
        print(f"analyst: scoring skipped ({type(exc).__name__}): {reason[:300]}", file=sys.stderr)
        return flags, None, cache

    scores = result["stocks"]
    brief = {**result["brief"], "date": today_str}
    out = apply_overrides(flags, scores, holdings, total_value)

    current = {f["symbol"] for f in flags}
    new_cache = {"brief": brief}
    for sym, v in scores.items():
        if sym in current:
            new_cache[sym] = {**v, "date": today_str}

    # counts only (no symbols/values) -- ops signal that the overlay ran.
    applied = sum(1 for f in out if f.get("analyst_override"))
    print(f"analyst: brief ok, {applied} override(s) applied across {len(scores)} scored",
          file=sys.stderr)
    return out, brief, new_cache
