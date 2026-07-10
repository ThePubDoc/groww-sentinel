"""Write-side boundary: pure format_digest + thin Telegram send (NOTIFY-01..03, RULES-05).

format_digest is pure -- zero I/O, fully testable without mocking HTTP. It
renders each flag as an emoji line with the P&L context and the concrete trade
size (how many shares to buy/sell + rupee value). send() is the only network
call: plain text (no parse_mode key at all) to Telegram's sendMessage, so no
Markdown/HTML escaping failure class -- emojis + layout carry the visual weight.
"""

import requests

TELEGRAM_MAX_LEN = 4096

_ACTION_FLAGS = ("STOP", "TRIM", "TRAIL WATCH", "AVOID", "CORP ACTION")
_OPPORTUNITY_FLAGS = ("BOOK 50%", "BOOK 25%", "AVERAGE")

_EMOJI = {
    "STOP": "🛑", "TRIM": "✂️", "TRAIL WATCH": "📉", "AVOID": "🚫",
    "BOOK 50%": "💰", "BOOK 25%": "💵", "AVERAGE": "➕", "NO PRICE": "❔",
    "CORP ACTION": "⚠️",
}
_VERB = {
    "STOP": "cut it — sell all", "TRIM": "trim — sell",
    "BOOK 50%": "book half — sell", "BOOK 25%": "book 25% — sell",
    "AVERAGE": "average — buy", "TRAIL WATCH": "tighten stop / consider exit",
    "AVOID": "hold — don't average (bad news)", "NO PRICE": "price unavailable",
    "CORP ACTION": "corporate action distorted avg cost — ignoring P&L flag",
}
_GATE_REMINDER = (
    "   ↳ 3-gate: results still good? fall market-wide (not company bad news)? "
    "would I buy fresh today?"
)


def _rupees(value: float) -> str:
    v = round(value)
    if v >= 100_000:
        return f"₹{v / 100_000:.2f}L"
    return f"₹{v:,}"


def _context(f: dict) -> str:
    if f["flag"] == "TRIM":
        return f"{f['weight'] * 100:.0f}% of book"
    if f["flag"] == "TRAIL WATCH":
        return f"-{f['pct_below_peak'] * 100:.0f}% from peak"
    if f["flag"] in ("NO PRICE", "CORP ACTION"):
        return ""
    return f"{f['pct'] * 100:+.0f}%"


def _line(f: dict) -> str:
    emoji = _EMOJI.get(f["flag"], "•")
    ctx = _context(f)
    verb = _VERB.get(f["flag"], "")
    qty = f" {f['shares']} sh (~{_rupees(f['value'])})" if f.get("shares") else ""
    parts = [f"{emoji} {f['symbol']}"]
    if ctx:
        parts.append(f"  {ctx}")
    if verb:
        parts.append(f"  ·  {verb}{qty}")
    line = "".join(parts)
    if f.get("sentiment", {}).get("reason"):
        line += f"\n   ↳ news: {f['sentiment']['reason']}"
    if f.get("reminder"):
        line += "\n" + _GATE_REMINDER
    return line


def _telemetry_line(portfolio: dict) -> str:
    """Overall P&L (PNL-01, always present) plus Day/Nd-trend/Intraday
    (PNL-02..04) -- each appended only when its portfolio field isn't None,
    never rendered as a misleading "0%" (D-07). Trend labels with the actual
    window length passed in, never a hardcoded "5d" (02-RESEARCH Pattern 4)."""
    pnl_pct = portfolio["overall_pnl_pct"] * 100
    arrow = "📈" if pnl_pct >= 0 else "📉"
    parts = [f"{arrow} P&L {pnl_pct:+.1f}%"]

    day_change_pct = portfolio.get("day_change_pct")
    if day_change_pct is not None:
        parts.append(f"Day {day_change_pct * 100:+.1f}%")

    trend = portfolio.get("trend")
    if trend is not None:
        trend_arrow = "↗" if trend["pct"] >= 0 else "↘"
        parts.append(f"{trend['days']}d {trend_arrow} {trend['pct'] * 100:+.1f}%")

    intraday_pct = portfolio.get("intraday_pct")
    if intraday_pct is not None:
        parts.append(f"Intraday {intraday_pct * 100:+.1f}%")

    return " · ".join(parts)


def format_digest(flags: list[dict], portfolio: dict) -> str:
    """Pure: rules.evaluate()'s flags + a portfolio summary -> digest text.

    portfolio: {"total_value": float, "overall_pnl_pct": float, "date": date,
    "day_change_pct": float|None, "trend": {"days": int, "pct": float}|None,
    "intraday_pct": float|None}. The three telemetry keys are optional and
    default to None-shaped omission when absent.
    """
    header = (
        f"📊 Groww Sentinel · {portfolio['date'].strftime('%d %b')}\n"
        f"💰 {_rupees(portfolio['total_value'])} · {_telemetry_line(portfolio)}"
    )

    non_hold = [f for f in flags if f["flag"] != "HOLD"]
    holds = [f for f in flags if f["flag"] == "HOLD"]

    groups = [
        ("🔴 ACTION", [f for f in non_hold if f["flag"] in _ACTION_FLAGS]),
        ("🟢 OPPORTUNITY", [f for f in non_hold if f["flag"] in _OPPORTUNITY_FLAGS]),
        ("⚪ NO PRICE", [f for f in non_hold if f["flag"] == "NO PRICE"]),
    ]
    sections = [
        title + "\n\n" + "\n\n".join(_line(f) for f in items)
        for title, items in groups
        if items
    ]

    # compact one-block HOLD summary -- proof every steady holding was checked
    if holds:
        steady = ", ".join(f"{f['symbol']} {f['pct'] * 100:+.0f}%" for f in holds)
        sections.append(f"😴 HOLDING ({len(holds)})\n{steady}")

    if not sections:
        return f"{header}\n\n✅ All quiet — nothing to flag today, job ran fine."
    body = "✅ Nothing to act on.\n\n\n" if not non_hold else ""
    return header + "\n\n\n" + body + "\n\n\n".join(sections)


def send(token: str, chat_id: str, text: str) -> None:
    """POST plain text to Telegram sendMessage; raises on non-2xx (NOTIFY-01)."""
    if len(text) > TELEGRAM_MAX_LEN:
        text = text[: TELEGRAM_MAX_LEN - 20].rsplit("\n", 1)[0] + "\n...truncated"
    resp = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": text},
        timeout=10,
    )
    resp.raise_for_status()
