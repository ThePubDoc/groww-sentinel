"""Optional news-sentiment layer (impure I/O).

Only ever BLOCKS a risky add: a bearish news read turns an AVERAGE (buy-the-dip)
verdict into AVOID ("don't average -- news is bad"). It never invents buys and
never changes a sell. Headlines are free (yfinance per-ticker news); the
sentiment call is Google Gemini Flash (free tier, no card). Disabled -> pure
no-op when GEMINI_API_KEY is absent, and any failure (no news, API error, bad
JSON) leaves the deterministic flag untouched -- sentiment can never break a run.
"""

import json
import logging
import warnings

import yfinance as yf

logging.getLogger("yfinance").setLevel(logging.CRITICAL)

MODEL = "gemini-3.1-flash-lite"
HEADLINE_LIMIT = 6
AVOID = "AVOID"


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


def score_batch(client, symbol_headlines: dict[str, list[str]]) -> dict[str, dict]:
    """ONE Gemini call for all candidates -> {symbol: {'label','reason'}}.

    Raises on API/parse error (caller guards). Batching keeps the model cost at
    a single request per run regardless of how many AVERAGE candidates there are.
    """
    blocks = [
        f"{sym}:\n" + "\n".join(f"  - {h}" for h in heads)
        for sym, heads in symbol_headlines.items()
    ]
    prompt = (
        "Classify near-term news sentiment for EACH stock below, for someone "
        "deciding whether to buy MORE of it. Judge each stock only on its own "
        "headlines.\n\nReply ONLY compact JSON mapping each ticker to an object "
        '{"label":"bullish|neutral|bearish","reason":"<=12 words"}, e.g. '
        '{"TCS":{"label":"neutral","reason":"..."}}.\n\n' + "\n\n".join(blocks)
    )
    resp = client.models.generate_content(
        model=MODEL,
        contents=prompt,
        config={
            "response_mime_type": "application/json",
            "max_output_tokens": 800,
            # flash models may 'think'; disable so the budget yields JSON, not reasoning.
            "thinking_config": {"thinking_budget": 0},
        },
    )
    data = json.loads(resp.text)
    return {
        sym: {"label": v.get("label", "neutral"), "reason": v.get("reason", "")}
        for sym, v in data.items()
        if isinstance(v, dict)
    }


def adjust(flags: list[dict], api_key: str | None) -> list[dict]:
    """Downgrade AVERAGE -> AVOID when news is bearish. No-op without a key.

    Only AVERAGE flags are examined (that is the only risky *add*); every other
    flag passes through unchanged. Per-symbol failures degrade to the original
    flag so a flaky feed or API never blocks the digest.
    """
    if not api_key:
        return flags

    # gather headlines for every AVERAGE candidate (news fetch is free; only the
    # model call is the cost we batch). Non-AVERAGE flags are never scored.
    items = {}
    for f in flags:
        if f["flag"] == "AVERAGE":
            heads = fetch_headlines(f["symbol"])
            if heads:
                items[f["symbol"]] = heads
    if not items:
        return flags

    from google import genai
    from google.genai import types

    # bounded: a slow/broken key must not add many seconds to an unattended run.
    client = genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(timeout=15_000, retry_options=types.HttpRetryOptions(attempts=1)),
    )
    try:
        scores = score_batch(client, items)  # ONE model call for all candidates
    except Exception:
        return flags  # sentiment never breaks the run

    out = []
    for f in flags:
        s = scores.get(f["symbol"]) if f["flag"] == "AVERAGE" else None
        if s and s["label"] == "bearish":
            blocked = dict(f)
            blocked["flag"] = AVOID
            blocked["reminder"] = False
            blocked["shares"] = 0
            blocked["value"] = 0.0
            blocked["sentiment"] = s
            out.append(blocked)
        else:
            out.append(f)
    return out
