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
    "CORP ACTION": "⚠️", "HOLD": "😴",
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
    override = f.get("analyst_override")
    if override:
        line += f"   (analyst · was {override['was']} · {override.get('confidence', '?')})"
        line += f"\n   ↳ {override.get('thesis', '')}"
        if override.get("key_risk"):
            line += f" · risk: {override['key_risk']}"
    suggestion = f.get("analyst_suggestion")
    if suggestion:
        line += (
            f"\n   ↳ analyst ({suggestion.get('confidence', '?')}): "
            f"{suggestion.get('flag', '')} — {suggestion.get('thesis', '')} [not applied]"
        )
    if f.get("reminder"):
        line += "\n" + _GATE_REMINDER
    return line


def _hold_line(f: dict) -> str:
    """Detailed steady-holding line: symbol + P&L%, plus the analyst's take
    (thesis · key risk) when present. Falls back to the bare head line if the
    analyst had no note for it."""
    head = f"😴 {f['symbol']}  {f['pct'] * 100:+.0f}%"
    note = f.get("analyst_note") or {}
    thesis = note.get("thesis")
    if not thesis:
        return head
    line = f"{head}\n   ↳ {thesis}"
    if note.get("key_risk"):
        line += f" · risk: {note['key_risk']}"
    return line


def _holds_section(holds: list[dict], budget: int) -> str:
    """😴 HOLDING block. The most-notable holdings (biggest absolute move) get
    full analyst detail; the rest render as a compact 'SYM +3%' tail. The number
    given detail is the largest that keeps the WHOLE section within `budget`, so
    the message never has to be hard-truncated by send() (NOTIFY-01). Section
    length is monotonic in that count, so a single forward scan finds the max."""
    title = f"😴 HOLDING ({len(holds)})"
    ranked = sorted(holds, key=lambda f: abs(f.get("pct") or 0.0), reverse=True)

    def _compact(f):
        return f"{f['symbol']} {f['pct'] * 100:+.0f}%"

    def _render(n_detail):
        detailed = "\n\n".join(_hold_line(f) for f in ranked[:n_detail])
        compact = ", ".join(_compact(f) for f in ranked[n_detail:])
        body = "\n\n".join(p for p in (detailed, compact) if p)
        return f"{title}\n{body}" if body else title

    best = 0
    for n in range(len(ranked) + 1):
        if len(_render(n)) <= budget:
            best = n
        else:
            break
    return _render(best)


def _brief_block(brief: dict) -> str:
    """🧠 ANALYST BRIEF: portfolio-level regime / stance / concentration read.
    Rendered only when the analyst layer produced a brief (caller passes None
    otherwise). Omits any field the model left blank."""
    lines = ["🧠 ANALYST BRIEF"]
    for key in ("regime", "stance", "concentration"):
        val = brief.get(key)
        if val:
            lines.append(val)
    return "\n".join(lines)


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


def _weekly_block(weekly: dict) -> str:
    """PNL-05: Friday-only weekly recap -- best/worst movers, week value
    change, and flags-fired count. Rendered only when `weekly` is truthy
    (caller already omits it on a thin week, D-08/T-02-04)."""
    movers = " · ".join(f"{sym} {pct * 100:+.1f}%" for sym, pct in weekly["movers"])
    value_change = weekly.get("value_change")
    value_part = f"Value {value_change * 100:+.1f}%" if value_change is not None else "Value n/a"
    return f"📅 WEEK\n{movers}\n{value_part} · {weekly['flags_fired']} flags fired"


def format_digest(flags: list[dict], portfolio: dict, weekly: dict | None = None,
                  brief: dict | None = None) -> str:
    """Pure: rules.evaluate()'s flags + a portfolio summary -> digest text.

    portfolio: {"total_value": float, "overall_pnl_pct": float, "date": date,
    "day_change_pct": float|None, "trend": {"days": int, "pct": float}|None,
    "intraday_pct": float|None}. The three telemetry keys are optional and
    default to None-shaped omission when absent.

    weekly: optional {"movers": [(symbol, pct), ...], "value_change": float|None,
    "flags_fired": int} (PNL-05) -- appended as the final section on Fridays
    only; omitted entirely (no stray heading) when None.

    brief: optional analyst portfolio brief {"regime","stance","concentration"}
    -- rendered as a 🧠 block right under the header; omitted entirely when None.
    """
    header = (
        f"📊 Groww Sentinel · {portfolio['date'].strftime('%d %b')}\n"
        f"💰 {_rupees(portfolio['total_value'])} · {_telemetry_line(portfolio)}"
    )
    if brief:
        header += "\n\n" + _brief_block(brief)

    non_hold = [f for f in flags if f["flag"] != "HOLD"]
    # a HOLD the analyst had something to say about (override that landed on HOLD,
    # or an unapplied suggestion) gets its own line, not the compact summary --
    # otherwise a real analyst call would vanish into the steady list.
    holds_noted = [f for f in flags if f["flag"] == "HOLD"
                   and (f.get("analyst_override") or f.get("analyst_suggestion"))]
    holds = [f for f in flags if f["flag"] == "HOLD" and f not in holds_noted]

    groups = [
        ("🔴 ACTION", [f for f in non_hold if f["flag"] in _ACTION_FLAGS]),
        ("🟢 OPPORTUNITY", [f for f in non_hold if f["flag"] in _OPPORTUNITY_FLAGS]),
        ("⚪ NO PRICE", [f for f in non_hold if f["flag"] == "NO PRICE"]),
        ("🧠 ANALYST", holds_noted),
    ]
    sections = [
        title + "\n\n" + "\n\n".join(_line(f) for f in items)
        for title, items in groups
        if items
    ]

    weekly_section = _weekly_block(weekly) if weekly else None

    if not sections and not holds:
        digest = f"{header}\n\n✅ All quiet — nothing to flag today, job ran fine."
        return f"{digest}\n\n\n{weekly_section}" if weekly_section else digest

    # Assemble everything except the steady-HOLD block first, then fit the HOLD
    # detail (analyst take per holding can be long) into the remaining Telegram
    # budget -- trimming the least-notable holdings rather than tail-truncating.
    body = "✅ Nothing to act on.\n\n\n" if not non_hold else ""
    core = header + "\n\n\n" + body + "\n\n\n".join(sections)
    if holds:
        reserved = len(core) + (len(weekly_section) + 3 if weekly_section else 0)
        holds_section = _holds_section(holds, max(0, TELEGRAM_MAX_LEN - reserved - 6))
        core += ("\n\n\n" if sections or body else "") + holds_section
    return f"{core}\n\n\n{weekly_section}" if weekly_section else core


def healthcheck_ping(url: str | None) -> None:
    """Best-effort dead-man's-switch heartbeat (NOTIFY-05, D-08). No-op when
    `url` is unset; a failed ping is swallowed -- a monitoring heartbeat must
    never crash or fail the run."""
    if not url:
        return
    try:
        requests.get(url, timeout=10)
    except Exception:
        pass


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
