"""Pure decision core for Groww Sentinel (RULES-01, RULES-02, RULES-03).

evaluate(holdings, state, today) -> (flags, new_state) is side-effect-free:
no network, no file, no clock, no env. `today` is accepted for signature
stability (later phases add calendar-aware behavior).

ONE uniform P&L action ladder applies to EVERY holding -- no core/tactical
tagging, no config. Each flag also carries a concrete size (`shares` to
buy/sell + rupee `value`) so the digest can say exactly how much to trade.

TRAIL WATCH is a genuine-drawdown signal: it fires only when the tracked peak
is strictly ABOVE average cost (the stock was in profit, then fell >20% off
that high) -- never on a plain loser whose seeded peak collapses to avg_cost.
So in Phase 1 (`state` always {}, no durable peaks until Phase 2) TRAIL WATCH
effectively never fires and losers resolve to AVERAGE / STOP; it comes alive
once Phase 2 persists real peaks. Intentional, not a bug.
"""

import math
from datetime import date  # noqa: F401 -- signature stability, unused this phase

# Named threshold constants (RULES-03) -- single place to tune. Every P&L
# comparison is strict `>`: a value exactly on a threshold does NOT trip it.
BOOK_HALF_GAIN = 0.50      # gain > 0.50 -> book half
BOOK_QUARTER_GAIN = 0.25   # gain > 0.25 -> book a quarter
AVERAGE_DROP = 0.10        # drop > 0.10 -> average down
STOP_DROP = 0.25           # drop > 0.25 -> cut the loss
TRIM_WEIGHT = 0.10         # weight > 0.10 of portfolio -> trim concentration
TRAIL_BELOW_PEAK = 0.20    # > 0.20 below a real peak -> trailing-stop watch

# Corp-action (bonus/split) detection tolerances (RULES-06, D-09). A real
# AVERAGE-down buy moves invested capital roughly in proportion to qty added;
# a bonus/split moves qty with ~zero new capital -- both conditions together
# separate the two (see _detect_corp_action).
QTY_JUMP_PCT = 0.05        # qty grew > 5% since last run's stored qty
COST_FLAT_TOLERANCE = 0.05  # invested capital changed < 5% over that jump

# Position sizing (tunable). Sell fractions are implied by the BOOK tiers /
# STOP; AVERAGE adds a measured tranche of the current holding.
BOOK_HALF_SELL = 0.50
BOOK_QUARTER_SELL = 0.25
AVERAGE_ADD_FRAC = 0.25    # AVERAGE -> buy this fraction more shares

NO_PRICE = "NO PRICE"
CORP_ACTION = "CORP ACTION"
STOP = "STOP"
TRIM = "TRIM"
BOOK_50 = "BOOK 50%"
BOOK_25 = "BOOK 25%"
TRAIL_WATCH = "TRAIL WATCH"
AVERAGE = "AVERAGE"
HOLD = "HOLD"


def _resolve(drop: float, gain: float, weight: float, trail: float) -> str:
    """Ordered precedence, first match wins; strict `>` throughout.
    STOP > TRIM > BOOK > TRAIL WATCH > AVERAGE > HOLD.

    TRIM outranking AVERAGE means an over-weight loser is trimmed, never
    averaged into -- the 'don't add to a heavy position' guard is free.
    """
    if drop > STOP_DROP:
        return STOP
    if weight > TRIM_WEIGHT:
        return TRIM
    if gain > BOOK_QUARTER_GAIN:
        return BOOK_50 if gain > BOOK_HALF_GAIN else BOOK_25
    if trail > TRAIL_BELOW_PEAK:
        return TRAIL_WATCH
    if drop > AVERAGE_DROP:
        return AVERAGE
    return HOLD


def _detect_corp_action(prior_qty, prior_avg, qty: int, avg_cost: float) -> bool:
    """True when qty jumped but invested capital stayed flat (D-09).

    A genuine AVERAGE-down buy moves qty*avg_cost roughly in proportion to
    the shares added; a bonus/split moves qty with ~zero new capital. Both
    conditions (qty jump AND capital-flat) must hold -- qty growth alone
    would mislabel a real large purchase (see 02-RESEARCH Pitfall 1).
    """
    if not prior_qty or prior_qty <= 0:
        return False  # first-seen symbol -- no baseline to compare against
    qty_growth = (qty - prior_qty) / prior_qty
    if qty_growth <= QTY_JUMP_PCT:
        return False
    prior_capital = prior_qty * prior_avg
    new_capital = qty * avg_cost
    cost_growth = abs(new_capital - prior_capital) / prior_capital if prior_capital else 0.0
    return cost_growth < COST_FLAT_TOLERANCE


def _shares(flag: str, qty: int, ltp: float, total_value: float) -> int:
    """How many whole shares to trade for this flag (0 = no sizing / watch-only)."""
    if flag == STOP:
        n = qty                                    # exit the whole position
    elif flag == BOOK_50:
        n = qty * BOOK_HALF_SELL
    elif flag == BOOK_25:
        n = qty * BOOK_QUARTER_SELL
    elif flag == AVERAGE:
        n = qty * AVERAGE_ADD_FRAC
    elif flag == TRIM:
        # sell just enough to bring weight back to the TRIM gate (10%)
        excess_value = qty * ltp - TRIM_WEIGHT * total_value
        n = math.ceil(excess_value / ltp) if ltp else 0
    else:
        return 0
    # a fired action always sizes to >=1 whole share (qty is always >=1);
    # avoids a dangling "buy"/"sell" with no number on tiny positions.
    return max(1, int(round(n)))


def size_position(flag: str, qty: int, ltp: float, total_value: float) -> int:
    """Public sizing hook (whole shares for a flag) -- lets the analyst overlay
    re-size a flag it overrides using the exact same rules math. Pure."""
    return _shares(flag, qty, ltp, total_value)


def evaluate(holdings: list, state: dict, today: date):
    """Map each holding to exactly one action flag + a trade size (RULES-02).

    holdings: [{"symbol", "qty", "avg_cost", "ltp"}, ...] -- ltp may be None.
    state: read-only peak lookup, {} in Phase 1 (STATE-05 seeds first-run peaks).
    Returns (flags, new_state). Each flag dict carries `shares` (whole shares to
    buy/sell for the action) and `value` (rupees of that trade).
    """
    total_value = sum(h["qty"] * h["ltp"] for h in holdings if h.get("ltp") is not None)

    flags = []
    new_state = {}
    for h in holdings:
        symbol, qty, avg_cost, ltp = h["symbol"], h["qty"], h["avg_cost"], h.get("ltp")

        if ltp is None:
            flags.append({
                "symbol": symbol, "flag": NO_PRICE, "pct": None, "weight": None,
                "pct_below_peak": None, "shares": 0, "value": 0.0, "reminder": False,
            })
            new_state[symbol] = state.get(symbol, {})
            continue

        pnl_frac = (ltp - avg_cost) / avg_cost
        drop = max(0.0, -pnl_frac)
        gain = max(0.0, pnl_frac)
        weight = (qty * ltp / total_value) if total_value else 0.0

        prior = state.get(symbol, {})
        prior_peak = prior.get("peak")
        prior_qty = prior.get("qty")
        prior_avg_cost = prior.get("avg_cost")

        corp_action = _detect_corp_action(prior_qty, prior_avg_cost, qty, avg_cost)

        peak = prior_peak if prior_peak is not None else max(ltp, avg_cost)
        if corp_action and prior_qty:
            # the stored peak was captured on the pre-action share count and
            # is otherwise incomparable to the post-action ltp (D-11) --
            # rescale before the max(peak, ltp) / below-peak math below.
            peak = peak * (prior_qty / qty)
        peak = max(peak, ltp)
        pct_below_peak = (peak - ltp) / peak if peak else 0.0
        new_state[symbol] = {"peak": peak, "qty": qty, "avg_cost": avg_cost}

        # only a drawdown from a peak ABOVE cost counts as a trailing stop
        trail = pct_below_peak if peak > avg_cost else 0.0

        if corp_action:
            # P&L-derived drop/gain are unreliable on a distorted cost basis
            # (RULES-06, D-09) -- only weight (TRIM) and peak (TRAIL WATCH)
            # still fire; STOP/BOOK/AVERAGE are replaced with CORP_ACTION.
            if weight > TRIM_WEIGHT:
                flag = TRIM
            elif trail > TRAIL_BELOW_PEAK:
                flag = TRAIL_WATCH
            else:
                flag = CORP_ACTION
        else:
            flag = _resolve(drop, gain, weight, trail)

        if flag == CORP_ACTION:
            # a distorted cost basis must not display a pct or a trade size
            shares, value, pct, reminder = 0, 0.0, None, False
        else:
            shares = _shares(flag, qty, ltp, total_value)
            value = shares * ltp
            pct = pnl_frac
            reminder = flag == AVERAGE

        flags.append({
            "symbol": symbol, "flag": flag, "pct": pct, "weight": weight,
            "pct_below_peak": pct_below_peak, "shares": shares,
            "value": value, "reminder": reminder,
        })

    return flags, new_state
