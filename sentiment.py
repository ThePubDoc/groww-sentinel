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

MODEL = "gemini-2.5-flash"
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


def score(client, symbol: str, headlines: list[str]) -> dict:
    """One Gemini Flash call -> {'label','reason'}. Raises on API/parse error (caller guards)."""
    prompt = (
        f"Recent news headlines for the stock {symbol}:\n"
        + "\n".join(f"- {h}" for h in headlines)
        + '\n\nClassify near-term sentiment for someone deciding whether to buy '
        'more of this stock. Reply ONLY compact JSON: '
        '{"label":"bullish|neutral|bearish","reason":"<=12 words"}.'
    )
    resp = client.models.generate_content(
        model=MODEL,
        contents=prompt,
        config={
            "response_mime_type": "application/json",
            "max_output_tokens": 200,
            # 2.5-flash is a thinking model; disable thinking so the token
            # budget produces the JSON answer, not hidden reasoning.
            "thinking_config": {"thinking_budget": 0},
        },
    )
    data = json.loads(resp.text)
    return {"label": data.get("label", "neutral"), "reason": data.get("reason", "")}


def adjust(flags: list[dict], api_key: str | None) -> list[dict]:
    """Downgrade AVERAGE -> AVOID when news is bearish. No-op without a key.

    Only AVERAGE flags are examined (that is the only risky *add*); every other
    flag passes through unchanged. Per-symbol failures degrade to the original
    flag so a flaky feed or API never blocks the digest.
    """
    if not api_key:
        return flags
    from google import genai
    from google.genai import types

    # bounded: a slow/broken key must not add many seconds to an unattended
    # cron run -- fail fast and degrade to the deterministic flag.
    client = genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(timeout=10_000, retry_options=types.HttpRetryOptions(attempts=1)),
    )
    out = []
    for f in flags:
        if f["flag"] != "AVERAGE":
            out.append(f)
            continue
        headlines = fetch_headlines(f["symbol"])
        if not headlines:
            out.append(f)
            continue
        try:
            s = score(client, f["symbol"], headlines)
        except Exception:
            out.append(f)
            continue
        if s["label"] == "bearish":
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
