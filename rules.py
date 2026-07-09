"""Pure decision core for Groww Sentinel (RULES-01..05, STATE-05).

evaluate(holdings, config, state, today) -> (flags, new_state) is a
side-effect-free function: no network, no file, no clock, no env access.
`today` is accepted for signature stability (future phases add calendar-aware
behavior) but Phase 1's rules have no date dependency.

Phase 1 note (see 01-RESEARCH.md Pitfall 1): `state` is always {} this phase
(no durable state.json until Phase 2's STATE-01..04). Every run therefore
re-seeds each symbol's peak fresh as max(ltp, avg_cost) -- the below-peak
clauses (STOP HIT's second clause, TRAIL WATCH) collapse to the same-run
drop-from-avg-cost fraction and will rarely reflect a genuine historical
drawdown. Expected, not a bug.
"""

from datetime import date  # noqa: F401 -- signature stability, unused this phase

# Named threshold constants (RULES-03, D-01) -- single place to tune.
AVG_TIER_1 = 0.10
AVG_TIER_2 = 0.20
AVG_TIER_3 = 0.30
AVG_WEIGHT_GATE = 0.10  # D-04: applies at every tier, including the deepest
TRIM_WEIGHT = 0.10
BOOK_GAIN = 0.25
STOP_DROP = 0.12
STOP_BELOW_PEAK = 0.15
TRAIL_BELOW_PEAK = 0.20

NO_PRICE = "NO PRICE"
UNTAGGED = "UNTAGGED"
STOP_HIT = "STOP HIT"
TRIM = "TRIM"
BOOK_50 = "BOOK 50%"
TRAIL_WATCH = "TRAIL WATCH"
AVG_CANDIDATE = "AVG CANDIDATE"
HOLD = "HOLD"


def _bucket(symbol, config):
    """D-11: missing or non-core/tactical tag resolves to 'untagged', never raises."""
    tag = config.get(symbol)
    return tag if tag in ("core", "tactical") else "untagged"


def _resolve(bucket, drop, gain, weight, pct_below_peak):
    """Single ordered precedence chain, first match wins (D-13). All
    comparisons are strict > (D-14)."""
    if bucket == "untagged":
        return UNTAGGED, None
    if bucket == "tactical" and (drop > STOP_DROP or pct_below_peak > STOP_BELOW_PEAK):
        return STOP_HIT, None
    if weight > TRIM_WEIGHT:
        return TRIM, None
    if bucket == "tactical" and gain > BOOK_GAIN:
        return BOOK_50, None
    if bucket == "core" and pct_below_peak > TRAIL_BELOW_PEAK:
        return TRAIL_WATCH, None
    if bucket == "core" and drop > AVG_TIER_1 and weight < AVG_WEIGHT_GATE:
        tier = 3 if drop > AVG_TIER_3 else 2 if drop > AVG_TIER_2 else 1
        return AVG_CANDIDATE, tier
    return HOLD, None


def _message(symbol, flag, tier, drop, gain):
    if flag == AVG_CANDIDATE:
        return f"{symbol}: AVG CANDIDATE tier {tier} (-{drop * 100:.0f}%)"
    if flag == STOP_HIT:
        return f"{symbol}: STOP HIT (-{drop * 100:.0f}% vs avg)"
    if flag == BOOK_50:
        return f"{symbol}: BOOK 50% (+{gain * 100:.0f}% vs avg)"
    if flag == TRAIL_WATCH:
        return f"{symbol}: TRAIL WATCH"
    if flag == TRIM:
        return f"{symbol}: TRIM (over-weight)"
    if flag == UNTAGGED:
        return f"{symbol}: UNTAGGED -- add to config.yaml"
    if flag == NO_PRICE:
        return f"{symbol}: NO PRICE -- LTP unavailable this run"
    return f"{symbol}: HOLD"


def evaluate(holdings: list, config: dict, state: dict, today: date):
    """Map each holding to exactly one flag (RULES-02).

    holdings: [{"symbol", "qty", "avg_cost", "ltp"}, ...] -- ltp may be None.
    config: {symbol: "core" | "tactical" | anything-else-or-missing}.
    state: read-only lookup, {} in Phase 1 (STATE-05).
    """
    # D-02: weight denominator = total equity holdings value. A symbol with
    # ltp=None contributes 0 -- its own value is unknown, and it never reaches
    # weight-dependent flags anyway (short-circuited to NO_PRICE below).
    total_value = sum(h["qty"] * h["ltp"] for h in holdings if h.get("ltp") is not None)

    flags = []
    new_state = {}
    for h in holdings:
        symbol, qty, avg_cost, ltp = h["symbol"], h["qty"], h["avg_cost"], h.get("ltp")
        bucket = _bucket(symbol, config)

        if ltp is None:
            flags.append(
                {
                    "symbol": symbol,
                    "bucket": bucket,
                    "flag": NO_PRICE,
                    "pct": None,
                    "weight": None,
                    "pct_below_peak": None,
                    "tier": None,
                    "reminder": False,
                    "message": _message(symbol, NO_PRICE, None, 0.0, 0.0),
                }
            )
            new_state[symbol] = state.get(symbol, {})  # unchanged, nothing to seed
            continue

        pnl_frac = (ltp - avg_cost) / avg_cost
        drop = max(0.0, -pnl_frac)
        gain = max(0.0, pnl_frac)
        weight = (qty * ltp / total_value) if total_value else 0.0

        # STATE-05: first-run peak seed. state is a read-only lookup; Phase 1
        # always passes {} so every symbol is first-seen (see module docstring).
        prior_peak = state.get(symbol, {}).get("peak")
        peak = prior_peak if prior_peak is not None else max(ltp, avg_cost)
        peak = max(peak, ltp)
        pct_below_peak = (peak - ltp) / peak if peak else 0.0
        new_state[symbol] = {"peak": peak}

        flag, tier = _resolve(bucket, drop, gain, weight, pct_below_peak)

        flags.append(
            {
                "symbol": symbol,
                "bucket": bucket,
                "flag": flag,
                "pct": gain if gain else -drop,
                "weight": weight,
                "pct_below_peak": pct_below_peak,
                "tier": tier,
                "reminder": flag == AVG_CANDIDATE,
                "message": _message(symbol, flag, tier, drop, gain),
            }
        )

    return flags, new_state
