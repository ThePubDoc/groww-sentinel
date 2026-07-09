"""Pure decision core for Groww Sentinel (RULES-01, RULES-02, RULES-03).

evaluate(holdings, state, today) -> (flags, new_state) is side-effect-free:
no network, no file, no clock, no env. `today` is accepted for signature
stability (later phases add calendar-aware behavior); the ladder has no date
dependency this phase.

ONE uniform P&L action ladder applies to EVERY holding -- no core/tactical
tagging, no config file. Sentinel reads each stock's gain/loss vs average cost
and states the action directly.

TRAIL WATCH is a genuine-drawdown signal: it fires only when the tracked peak
is strictly ABOVE average cost (the stock was in profit, then fell >20% off
that high) -- never on a plain loser whose seeded peak collapses to avg_cost.
So in Phase 1 (`state` always {}, no durable peaks until Phase 2) TRAIL WATCH
effectively never fires and losers correctly resolve to AVERAGE / STOP; it
comes alive once Phase 2 persists real peaks. Intentional, not a bug.
"""

from datetime import date  # noqa: F401 -- signature stability, unused this phase

# Named threshold constants (RULES-03) -- single place to tune. Every comparison
# is strict `>`: a value exactly on a threshold does NOT trip it.
BOOK_HALF_GAIN = 0.50      # gain > 0.50 -> book half
BOOK_QUARTER_GAIN = 0.25   # gain > 0.25 -> book a quarter
AVERAGE_DROP = 0.10        # drop > 0.10 -> average down
STOP_DROP = 0.25           # drop > 0.25 -> cut the loss
TRIM_WEIGHT = 0.10         # weight > 0.10 of portfolio -> trim concentration
TRAIL_BELOW_PEAK = 0.20    # > 0.20 below tracked peak -> trailing-stop watch

NO_PRICE = "NO PRICE"
STOP = "STOP"
TRIM = "TRIM"
BOOK_50 = "BOOK 50%"
BOOK_25 = "BOOK 25%"
TRAIL_WATCH = "TRAIL WATCH"
AVERAGE = "AVERAGE"
HOLD = "HOLD"


def _resolve(drop: float, gain: float, weight: float, pct_below_peak: float) -> str:
    """One ordered precedence chain, first match wins; strict `>` throughout.

    STOP (deep loss) > TRIM (concentration) > BOOK (take profit) >
    TRAIL WATCH (peak drop) > AVERAGE (buy the dip) > HOLD.

    TRIM outranking AVERAGE means an over-weight loser is trimmed, never
    averaged into -- the 'don't add to an already-heavy position' guard falls
    out of precedence for free.
    """
    if drop > STOP_DROP:
        return STOP
    if weight > TRIM_WEIGHT:
        return TRIM
    if gain > BOOK_QUARTER_GAIN:
        return BOOK_50 if gain > BOOK_HALF_GAIN else BOOK_25
    if pct_below_peak > TRAIL_BELOW_PEAK:
        return TRAIL_WATCH
    if drop > AVERAGE_DROP:
        return AVERAGE
    return HOLD


def _message(symbol: str, flag: str, gain: float, drop: float,
             weight: float, pct_below_peak: float) -> str:
    if flag == STOP:
        return f"{symbol}: STOP (-{drop * 100:.0f}% vs avg) -> cut it"
    if flag == TRIM:
        return f"{symbol}: TRIM ({weight * 100:.0f}% of portfolio) -> reduce"
    if flag == BOOK_50:
        return f"{symbol}: BOOK 50% (+{gain * 100:.0f}% vs avg) -> sell half"
    if flag == BOOK_25:
        return f"{symbol}: BOOK 25% (+{gain * 100:.0f}% vs avg) -> sell a quarter"
    if flag == TRAIL_WATCH:
        return f"{symbol}: TRAIL WATCH (-{pct_below_peak * 100:.0f}% from peak) -> tighten stop / consider exit"
    if flag == AVERAGE:
        return f"{symbol}: AVERAGE (-{drop * 100:.0f}% vs avg) -> add more"
    if flag == NO_PRICE:
        return f"{symbol}: NO PRICE -- price unavailable this run"
    return f"{symbol}: HOLD"


def evaluate(holdings: list, state: dict, today: date):
    """Map each holding to exactly one action flag (RULES-02).

    holdings: [{"symbol", "qty", "avg_cost", "ltp"}, ...] -- ltp may be None.
    state: read-only peak lookup, {} in Phase 1 (STATE-05 seeds first-run peaks).
    Returns (flags, new_state).
    """
    # weight denominator = total equity holdings value; an unpriced symbol
    # contributes 0 and never reaches a weight-dependent flag (NO_PRICE below).
    total_value = sum(h["qty"] * h["ltp"] for h in holdings if h.get("ltp") is not None)

    flags = []
    new_state = {}
    for h in holdings:
        symbol, qty, avg_cost, ltp = h["symbol"], h["qty"], h["avg_cost"], h.get("ltp")

        if ltp is None:
            flags.append({
                "symbol": symbol, "flag": NO_PRICE, "pct": None, "weight": None,
                "pct_below_peak": None, "reminder": False,
                "message": _message(symbol, NO_PRICE, 0.0, 0.0, 0.0, 0.0),
            })
            new_state[symbol] = state.get(symbol, {})
            continue

        pnl_frac = (ltp - avg_cost) / avg_cost
        drop = max(0.0, -pnl_frac)
        gain = max(0.0, pnl_frac)
        weight = (qty * ltp / total_value) if total_value else 0.0

        prior_peak = state.get(symbol, {}).get("peak")
        peak = prior_peak if prior_peak is not None else max(ltp, avg_cost)
        peak = max(peak, ltp)
        pct_below_peak = (peak - ltp) / peak if peak else 0.0
        new_state[symbol] = {"peak": peak}

        # TRAIL WATCH only counts a drawdown from a peak ABOVE cost -- a plain
        # loser (peak seeded == avg_cost) is not "trailing down from a high",
        # it's just a loss, and belongs to AVERAGE/STOP instead.
        trail_pct = pct_below_peak if peak > avg_cost else 0.0
        flag = _resolve(drop, gain, weight, trail_pct)
        flags.append({
            "symbol": symbol, "flag": flag, "pct": pnl_frac, "weight": weight,
            "pct_below_peak": pct_below_peak, "reminder": flag == AVERAGE,
            "message": _message(symbol, flag, gain, drop, weight, pct_below_peak),
        })

    return flags, new_state
