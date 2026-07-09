"""Write-side boundary: pure format_digest + thin Telegram send (NOTIFY-01..03, RULES-05).

format_digest is pure -- zero I/O, fully testable without mocking HTTP. It
renders each flag as an emoji line with the P&L context and the concrete trade
size (how many shares to buy/sell + rupee value). send() is the only network
call: plain text (no parse_mode key at all) to Telegram's sendMessage, so no
Markdown/HTML escaping failure class -- emojis + layout carry the visual weight.
"""

import requests

TELEGRAM_MAX_LEN = 4096

_ACTION_FLAGS = ("STOP", "TRIM", "TRAIL WATCH", "AVOID")
_OPPORTUNITY_FLAGS = ("BOOK 50%", "BOOK 25%", "AVERAGE")

_EMOJI = {
    "STOP": "🛑", "TRIM": "✂️", "TRAIL WATCH": "📉", "AVOID": "🚫",
    "BOOK 50%": "💰", "BOOK 25%": "💵", "AVERAGE": "➕", "NO PRICE": "❔",
}
_VERB = {
    "STOP": "cut it — sell all", "TRIM": "trim — sell",
    "BOOK 50%": "book half — sell", "BOOK 25%": "book 25% — sell",
    "AVERAGE": "average — buy", "TRAIL WATCH": "tighten stop / consider exit",
    "AVOID": "hold — don't average (bad news)", "NO PRICE": "price unavailable",
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
    if f["flag"] == "NO PRICE":
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


def format_digest(flags: list[dict], portfolio: dict) -> str:
    """Pure: rules.evaluate()'s flags + a portfolio summary -> digest text.

    portfolio: {"total_value": float, "overall_pnl_pct": float, "date": date}.
    """
    pnl_pct = portfolio["overall_pnl_pct"] * 100
    arrow = "📈" if pnl_pct >= 0 else "📉"
    header = (
        f"📊 Groww Sentinel · {portfolio['date'].strftime('%d %b')}\n"
        f"💰 {_rupees(portfolio['total_value'])}   {arrow} {pnl_pct:+.1f}%"
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
