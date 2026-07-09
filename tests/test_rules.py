"""Boundary/precedence tests for rules.py (TEST-01).

rules.py does not exist yet at the time this file is written — this suite is
the RED half of the RED/GREEN cycle for Phase 1's money-path logic. See
01-01-PLAN.md Task 1/Task 2 and 01-CONTEXT.md D-01/D-02/D-03/D-04/D-13/D-14.
"""

from datetime import date

import pytest

import rules

TODAY = date(2026, 7, 9)


def holding(symbol="TCS", qty=10, avg_cost=1000.0, ltp=1000.0):
    """Fixture helper — the exact input dict shape rules.evaluate() expects."""
    return {"symbol": symbol, "qty": qty, "avg_cost": avg_cost, "ltp": ltp}


def flag_for(flags, symbol):
    return next(f for f in flags if f["symbol"] == symbol)


def padded(target, pad_value=1_000_000.0):
    """A target holding plus a large padding holding, so target's weight stays
    well under the 10% TRIM/AVG-gate threshold and doesn't interfere with
    tests focused on price-action thresholds."""
    pad = holding("PAD", qty=1, avg_cost=pad_value, ltp=pad_value)
    return [target, pad]


# ---------------------------------------------------------------------------
# RULES-02: exactly one flag per held stock
# ---------------------------------------------------------------------------


def test_returns_exactly_one_entry_per_holding():
    # Arrange
    holdings = [
        holding("A", avg_cost=100.0, ltp=100.0),
        holding("B", avg_cost=100.0, ltp=100.0),
        holding("C", avg_cost=100.0, ltp=100.0),
    ]
    config = {"A": "core", "B": "tactical", "C": "core"}
    # Act
    flags, new_state = rules.evaluate(holdings, config, state={}, today=TODAY)
    # Assert
    assert len(flags) == 3
    assert {f["symbol"] for f in flags} == {"A", "B", "C"}
    assert isinstance(new_state, dict)


# ---------------------------------------------------------------------------
# STOP HIT (tactical) — strict > 12% drop from avg cost (D-14)
# ---------------------------------------------------------------------------


def test_stop_hit_does_not_fire_at_exactly_12_percent_drop():
    # Arrange: tactical stock down exactly 12.00% — boundary is exclusive
    h = holding("RELIANCE", avg_cost=1000.0, ltp=880.0)
    config = {"RELIANCE": "tactical"}
    # Act
    flags, _ = rules.evaluate(padded(h), {**config, "PAD": "core"}, state={}, today=TODAY)
    # Assert
    assert flag_for(flags, "RELIANCE")["flag"] != "STOP HIT"


def test_stop_hit_fires_just_past_12_percent_drop():
    # Arrange: tactical stock down 12.01%
    h = holding("RELIANCE", avg_cost=1000.0, ltp=879.9)
    config = {"RELIANCE": "tactical", "PAD": "core"}
    # Act
    flags, _ = rules.evaluate(padded(h), config, state={}, today=TODAY)
    # Assert
    assert flag_for(flags, "RELIANCE")["flag"] == "STOP HIT"


# ---------------------------------------------------------------------------
# TRIM (any bucket) — strict > 10% weight; denominator = total equity value (D-02)
# ---------------------------------------------------------------------------


def test_trim_does_not_fire_at_exactly_10_percent_weight():
    # Arrange: target value 1000, pad value 9000 -> weight exactly 10.00%
    target = holding("TCS", qty=1, avg_cost=1000.0, ltp=1000.0)
    pad = holding("PAD", qty=1, avg_cost=9000.0, ltp=9000.0)
    config = {"TCS": "core", "PAD": "core"}
    # Act
    flags, _ = rules.evaluate([target, pad], config, state={}, today=TODAY)
    # Assert
    assert flag_for(flags, "TCS")["flag"] != "TRIM"


def test_trim_fires_just_past_10_percent_weight():
    # Arrange: target value 1001, pad value 8999 -> weight exactly 10.01%
    target = holding("TCS", qty=1, avg_cost=1000.0, ltp=1001.0)
    pad = holding("PAD", qty=1, avg_cost=8999.0, ltp=8999.0)
    config = {"TCS": "core", "PAD": "core"}
    # Act
    flags, _ = rules.evaluate([target, pad], config, state={}, today=TODAY)
    # Assert
    assert flag_for(flags, "TCS")["flag"] == "TRIM"


# ---------------------------------------------------------------------------
# BOOK 50% (tactical) — strict > 25% gain from avg cost
# ---------------------------------------------------------------------------


def test_book_50_does_not_fire_at_exactly_25_percent_gain():
    # Arrange
    h = holding("HDFCBANK", avg_cost=1000.0, ltp=1250.0)  # exactly +25%
    config = {"HDFCBANK": "tactical", "PAD": "core"}
    # Act
    flags, _ = rules.evaluate(padded(h), config, state={}, today=TODAY)
    # Assert
    assert flag_for(flags, "HDFCBANK")["flag"] != "BOOK 50%"


def test_book_50_fires_just_past_25_percent_gain():
    # Arrange
    h = holding("HDFCBANK", avg_cost=1000.0, ltp=1250.1)  # +25.01%
    config = {"HDFCBANK": "tactical", "PAD": "core"}
    # Act
    flags, _ = rules.evaluate(padded(h), config, state={}, today=TODAY)
    # Assert
    assert flag_for(flags, "HDFCBANK")["flag"] == "BOOK 50%"


# ---------------------------------------------------------------------------
# TRAIL WATCH (core) — strict > 20% below tracked peak
# Phase 1: state={} always, so peak = max(ltp, avg_cost) same-run (STATE-05,
# Pitfall 1) -- pct_below_peak collapses to the drop-from-avg-cost fraction
# whenever price is down. This is expected first-run behavior, not a bug.
# ---------------------------------------------------------------------------


def test_trail_watch_does_not_fire_at_exactly_20_percent_below_peak():
    # Arrange: drop exactly 20.00% -> peak (seeded=avg_cost) - ltp = 20.00% below peak
    h = holding("INFY", avg_cost=1000.0, ltp=800.0)
    config = {"INFY": "core", "PAD": "core"}
    # Act
    flags, _ = rules.evaluate(padded(h), config, state={}, today=TODAY)
    # Assert
    assert flag_for(flags, "INFY")["flag"] != "TRAIL WATCH"


def test_trail_watch_fires_just_past_20_percent_below_peak():
    # Arrange: drop 20.01%
    h = holding("INFY", avg_cost=1000.0, ltp=799.9)
    config = {"INFY": "core", "PAD": "core"}
    # Act
    flags, _ = rules.evaluate(padded(h), config, state={}, today=TODAY)
    # Assert
    assert flag_for(flags, "INFY")["flag"] == "TRAIL WATCH"


# ---------------------------------------------------------------------------
# AVG CANDIDATE (core) — 3-tier escalation, strict boundaries, weight gate
# ---------------------------------------------------------------------------


def test_avg_candidate_does_not_fire_at_exactly_10_percent_drop():
    # Arrange: drop exactly 10.00% -> no tier
    h = holding("ITC", avg_cost=1000.0, ltp=900.0)
    config = {"ITC": "core", "PAD": "core"}
    # Act
    flags, _ = rules.evaluate(padded(h), config, state={}, today=TODAY)
    # Assert
    assert flag_for(flags, "ITC")["flag"] != "AVG CANDIDATE"


def test_avg_candidate_tier1_just_past_10_percent_drop():
    # Arrange: drop 10.01%
    h = holding("ITC", avg_cost=1000.0, ltp=899.9)
    config = {"ITC": "core", "PAD": "core"}
    # Act
    flags, _ = rules.evaluate(padded(h), config, state={}, today=TODAY)
    itc = flag_for(flags, "ITC")
    # Assert
    assert itc["flag"] == "AVG CANDIDATE"
    assert itc["tier"] == 1
    assert "tier 1" in itc["message"]


def test_avg_candidate_tier2_just_past_20_percent_drop():
    # Arrange: drop 20.01% from avg cost. Phase 1's peak seed collapses to
    # avg_cost when price is down (state={} -> peak=max(ltp,avg_cost)), which
    # would make pct_below_peak numerically equal to drop and let the
    # higher-precedence TRAIL WATCH (>20% below peak) shadow this tier -- an
    # extension of Pitfall 1. A pre-existing state peak equal to the current
    # ltp isolates the tier math from that same-run coincidence (sentinel.py
    # always passes state={} in Phase 1; this verifies the resolver's tier
    # logic is correct and forward-compatible for when Phase 2 persists peaks).
    h = holding("ITC", avg_cost=1000.0, ltp=799.9)
    config = {"ITC": "core", "PAD": "core"}
    state = {"ITC": {"peak": 799.9}}
    # Act
    flags, _ = rules.evaluate(padded(h), config, state=state, today=TODAY)
    itc = flag_for(flags, "ITC")
    # Assert
    assert itc["flag"] == "AVG CANDIDATE"
    assert itc["tier"] == 2


def test_avg_candidate_tier3_just_past_30_percent_drop():
    # Arrange: drop 30.01% -- see tier2 test above for why a non-empty state
    # peak (equal to current ltp) is needed to isolate this from TRAIL WATCH.
    h = holding("ITC", avg_cost=1000.0, ltp=699.9)
    config = {"ITC": "core", "PAD": "core"}
    state = {"ITC": {"peak": 699.9}}
    # Act
    flags, _ = rules.evaluate(padded(h), config, state=state, today=TODAY)
    itc = flag_for(flags, "ITC")
    # Assert
    assert itc["flag"] == "AVG CANDIDATE"
    assert itc["tier"] == 3


def test_avg_weight_gate_suppresses_avg_at_every_tier_including_deepest():
    # Arrange (D-04): core stock down 31% (would be tier 3) but weight > 10%
    # -> weight gate suppresses AVG; TRIM fires instead (weight > 10% too).
    target = holding("RELIANCE", qty=1, avg_cost=1000.0, ltp=690.0)  # drop 31%
    pad = holding("PAD", qty=1, avg_cost=6000.0, ltp=6000.0)  # weight ~10.31%
    config = {"RELIANCE": "core", "PAD": "core"}
    # Act
    flags, _ = rules.evaluate([target, pad], config, state={}, today=TODAY)
    # Assert
    reliance = flag_for(flags, "RELIANCE")
    assert reliance["flag"] == "TRIM"
    assert reliance["flag"] != "AVG CANDIDATE"


def test_avg_candidate_carries_reminder_marker():
    # Arrange (RULES-05): every AVG CANDIDATE entry carries a truthy reminder marker
    h = holding("WIPRO", avg_cost=1000.0, ltp=850.0)  # drop 15% -> tier 1
    config = {"WIPRO": "core", "PAD": "core"}
    # Act
    flags, _ = rules.evaluate(padded(h), config, state={}, today=TODAY)
    wipro = flag_for(flags, "WIPRO")
    # Assert
    assert wipro["flag"] == "AVG CANDIDATE"
    assert wipro["reminder"]


# ---------------------------------------------------------------------------
# Precedence (D-13) — first match wins, ordered chain not independent ifs
# ---------------------------------------------------------------------------


def test_precedence_stop_hit_wins_over_trim():
    # Arrange: tactical, drop 20% (STOP HIT) AND weight ~44% (also qualifies TRIM)
    target = holding("ADANIENT", qty=1, avg_cost=1000.0, ltp=800.0)
    pad = holding("PAD", qty=1, avg_cost=1000.0, ltp=1000.0)
    config = {"ADANIENT": "tactical", "PAD": "core"}
    # Act
    flags, _ = rules.evaluate([target, pad], config, state={}, today=TODAY)
    # Assert
    assert flag_for(flags, "ADANIENT")["flag"] == "STOP HIT"


def test_precedence_trim_wins_over_book_50():
    # Arrange: tactical, gain 30% (BOOK 50%) AND weight ~56% (also qualifies TRIM)
    target = holding("HDFCBANK", qty=1, avg_cost=1000.0, ltp=1300.0)
    pad = holding("PAD", qty=1, avg_cost=1000.0, ltp=1000.0)
    config = {"HDFCBANK": "tactical", "PAD": "core"}
    # Act
    flags, _ = rules.evaluate([target, pad], config, state={}, today=TODAY)
    # Assert
    assert flag_for(flags, "HDFCBANK")["flag"] == "TRIM"


# ---------------------------------------------------------------------------
# UNTAGGED (RULES-04, D-11) — missing or bad tag, never hard-fails
# ---------------------------------------------------------------------------


def test_untagged_when_symbol_missing_from_config():
    # Arrange
    h = holding("XYZ")
    config = {}
    # Act — must not raise
    flags, _ = rules.evaluate([h], config, state={}, today=TODAY)
    # Assert
    assert flag_for(flags, "XYZ")["flag"] == "UNTAGGED"


def test_untagged_when_symbol_has_bad_tag():
    # Arrange
    h = holding("ZOMATO")
    config = {"ZOMATO": "bogus-typo"}
    # Act — must not raise
    flags, _ = rules.evaluate([h], config, state={}, today=TODAY)
    # Assert
    assert flag_for(flags, "ZOMATO")["flag"] == "UNTAGGED"


# ---------------------------------------------------------------------------
# HOLD — a tagged stock triggering nothing
# ---------------------------------------------------------------------------


def test_hold_when_nothing_triggers():
    # Arrange
    h = holding("INFY", avg_cost=1000.0, ltp=1000.0)
    config = {"INFY": "core", "PAD": "core"}
    # Act
    flags, _ = rules.evaluate(padded(h), config, state={}, today=TODAY)
    # Assert
    assert flag_for(flags, "INFY")["flag"] == "HOLD"


# ---------------------------------------------------------------------------
# STATE-05 / Pitfall 1 — first-run peak seed, state always {} in Phase 1
# ---------------------------------------------------------------------------


def test_peak_is_seeded_same_run_when_state_is_empty():
    """Phase 1 has no durable state.json (that's Phase 2's STATE-01..04). With
    state={}, peak is seeded fresh every run as max(ltp, avg_cost) — so
    pct_below_peak here reflects only this run's drop-from-avg-cost, NOT a
    genuine multi-day drawdown from a real historical high. This test asserts
    that expected first-seen behavior; it does not attempt to simulate a
    multi-day trailing peak (out of scope this phase, see RESEARCH.md Pitfall 1).
    """
    # Arrange: core stock down 15% from avg cost, no prior state
    h = holding("HDFC", avg_cost=1000.0, ltp=850.0)
    config = {"HDFC": "core", "PAD": "core"}
    # Act
    flags, _ = rules.evaluate(padded(h), config, state={}, today=TODAY)
    # Assert
    hdfc = flag_for(flags, "HDFC")
    assert hdfc["pct_below_peak"] == pytest.approx(0.15)


# ---------------------------------------------------------------------------
# Missing LTP — explicit "no price" result, never silent HOLD
# ---------------------------------------------------------------------------


def test_missing_ltp_yields_explicit_no_price_result():
    # Arrange
    h = {"symbol": "ADANIPOWER", "qty": 5, "avg_cost": 1000.0, "ltp": None}
    config = {"ADANIPOWER": "core", "PAD": "core"}
    # Act — must not raise despite ltp=None
    flags, _ = rules.evaluate(padded(h), config, state={}, today=TODAY)
    # Assert
    assert flag_for(flags, "ADANIPOWER")["flag"] == "NO PRICE"
