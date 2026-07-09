"""Write-side boundary: pure format_digest + thin Telegram send (NOTIFY-01..03, RULES-05).

format_digest is pure -- zero I/O, fully testable without mocking HTTP. send()
is the only network call in this module: plain text (no special formatting-mode
key at all) to Telegram's sendMessage, truncated at 4096 chars on a newline
boundary, raising on any non-2xx response. Plain text sidesteps the whole
Markdown/HTML escaping failure class (RESEARCH.md Pattern 5) -- deliberate.
"""

import requests

TELEGRAM_MAX_LEN = 4096

_ACTION_FLAGS = ("STOP", "TRIM", "TRAIL WATCH")
_OPPORTUNITY_FLAGS = ("BOOK 50%", "BOOK 25%", "AVERAGE")

_GATE_REMINDER = (
    "     3-gate check: results still good? is the fall market-wide (not "
    "company-bad-news)? would I buy this fresh today?"
)


def _line(f: dict) -> str:
    line = f" - {f['message']}"
    if f["flag"] == "AVERAGE":
        line += "\n" + _GATE_REMINDER
    return line


def _value_str(total_value: float) -> str:
    if total_value >= 100_000:
        return f"Rs {total_value / 100_000:.2f}L"
    return f"Rs {total_value:,.0f}"


def format_digest(flags: list[dict], portfolio: dict) -> str:
    """Pure: rules.evaluate()'s flags + a portfolio summary -> digest text.

    portfolio: {"total_value": float, "overall_pnl_pct": float, "date": date}.
    """
    pnl_pct = portfolio["overall_pnl_pct"] * 100
    header = (
        f"Groww Sentinel -- {portfolio['date'].strftime('%d %b')}\n"
        f"Value {_value_str(portfolio['total_value'])} | P&L {pnl_pct:+.1f}%"
    )

    non_hold = [f for f in flags if f["flag"] != "HOLD"]
    if not non_hold:
        return f"{header}\n\nAll quiet -- nothing to flag today, job ran fine."

    action = [f for f in non_hold if f["flag"] in _ACTION_FLAGS]
    opportunity = [f for f in non_hold if f["flag"] in _OPPORTUNITY_FLAGS]
    no_price = [f for f in non_hold if f["flag"] == "NO PRICE"]

    sections = []
    if action:
        sections.append("ACTION\n" + "\n".join(_line(f) for f in action))
    if opportunity:
        sections.append("OPPORTUNITY\n" + "\n".join(_line(f) for f in opportunity))
    if no_price:
        sections.append("NO PRICE\n" + "\n".join(_line(f) for f in no_price))

    return header + "\n\n" + "\n\n".join(sections)


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
