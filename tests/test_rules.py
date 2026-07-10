"""Boundary + precedence unit tests for the pure rules ladder (TEST-01, AAA).

One uniform P&L ladder, no tagging. Thresholds are strict `>`:
  gain  > 50%  -> BOOK 50%      (else > 25% -> BOOK 25%)
  drop  > 25%  -> STOP          (else > 10% -> AVERAGE)
  weight> 10%  -> TRIM
  >20% below peak -> TRAIL WATCH
Precedence: STOP > TRIM > BOOK > TRAIL WATCH > AVERAGE > HOLD.
"""

from datetime import date

import rules

TODAY = date(2026, 7, 9)

# A large 0%-P&L filler so a single "target" stays well under the TRIM weight
# gate; tests that want TRIM make the target the heavy holding instead.
_FILLER = {"symbol": "FILL", "qty": 100000, "avg_cost": 1.0, "ltp": 1.0}


def _flag_for(ltp, avg=100.0, qty=1, state=None, extra=None):
    """Evaluate one target holding (diluted by filler) and return its flag dict."""
    target = {"symbol": "X", "qty": qty, "avg_cost": avg, "ltp": ltp}
    holdings = [target, _FILLER] + (extra or [])
    flags, _ = rules.evaluate(holdings, state or {}, TODAY)
    return next(f for f in flags if f["symbol"] == "X")


# --- gainer ladder -------------------------------------------------------

def test_gain_above_50_books_half():
    assert _flag_for(160.0)["flag"] == rules.BOOK_50  # +60%


def test_gain_exactly_50_is_book_25_not_50():
    # strict >: +50.0% does not trip BOOK 50%, but does trip BOOK 25%
    assert _flag_for(150.0)["flag"] == rules.BOOK_25


def test_gain_just_above_50_books_half():
    assert _flag_for(150.01)["flag"] == rules.BOOK_50


def test_gain_between_25_and_50_books_quarter():
    assert _flag_for(130.0)["flag"] == rules.BOOK_25  # +30%


def test_gain_exactly_25_is_hold_not_book():
    assert _flag_for(125.0)["flag"] == rules.HOLD


def test_gain_just_above_25_books_quarter():
    assert _flag_for(125.01)["flag"] == rules.BOOK_25


# --- hold band -----------------------------------------------------------

def test_flat_is_hold():
    assert _flag_for(100.0)["flag"] == rules.HOLD


def test_small_gain_is_hold():
    assert _flag_for(110.0)["flag"] == rules.HOLD  # +10%


def test_small_loss_is_hold():
    assert _flag_for(95.0)["flag"] == rules.HOLD  # -5%


# --- loser ladder --------------------------------------------------------

def test_loss_exactly_10_is_hold_not_average():
    assert _flag_for(90.0)["flag"] == rules.HOLD


def test_loss_just_below_10_averages():
    assert _flag_for(89.99)["flag"] == rules.AVERAGE


def test_moderate_loss_averages_with_reminder():
    f = _flag_for(85.0)  # -15%
    assert f["flag"] == rules.AVERAGE
    assert f["reminder"] is True


def test_loss_exactly_25_averages_not_stops():
    assert _flag_for(75.0)["flag"] == rules.AVERAGE


def test_loss_just_below_25_stops():
    assert _flag_for(74.99)["flag"] == rules.STOP


def test_deep_loss_stops_no_reminder():
    f = _flag_for(60.0)  # -40%
    assert f["flag"] == rules.STOP
    assert f["reminder"] is False


# --- concentration (TRIM) ------------------------------------------------

def test_overweight_flat_stock_trims():
    flags, _ = rules.evaluate(
        [{"symbol": "X", "qty": 100, "avg_cost": 100.0, "ltp": 100.0},
         {"symbol": "FILL", "qty": 1, "avg_cost": 1.0, "ltp": 1.0}],
        {}, TODAY,
    )
    assert next(f for f in flags if f["symbol"] == "X")["flag"] == rules.TRIM


def test_weight_exactly_10_is_not_trim():
    # X value 100, filler value 900 -> X weight = 100/1000 = exactly 10%
    flags, _ = rules.evaluate(
        [{"symbol": "X", "qty": 1, "avg_cost": 100.0, "ltp": 100.0},
         {"symbol": "FILL", "qty": 900, "avg_cost": 1.0, "ltp": 1.0}],
        {}, TODAY,
    )
    assert next(f for f in flags if f["symbol"] == "X")["flag"] == rules.HOLD


# --- trailing stop (peak-based, needs a prior peak) ----------------------

def test_trail_watch_when_far_below_prior_peak():
    # +7% vs cost (not a book), but 25% below a stored peak of 200
    f = _flag_for(150.0, avg=140.0, state={"X": {"peak": 200.0}})
    assert f["flag"] == rules.TRAIL_WATCH


# --- precedence ----------------------------------------------------------

def test_stop_beats_trim_on_overweight_deep_loser():
    flags, _ = rules.evaluate(
        [{"symbol": "X", "qty": 100, "avg_cost": 100.0, "ltp": 60.0},  # -40%, ~100% wt
         {"symbol": "FILL", "qty": 1, "avg_cost": 1.0, "ltp": 1.0}],
        {}, TODAY,
    )
    assert next(f for f in flags if f["symbol"] == "X")["flag"] == rules.STOP


def test_trim_beats_book_on_overweight_winner():
    flags, _ = rules.evaluate(
        [{"symbol": "X", "qty": 100, "avg_cost": 100.0, "ltp": 160.0},  # +60%, ~100% wt
         {"symbol": "FILL", "qty": 1, "avg_cost": 1.0, "ltp": 1.0}],
        {}, TODAY,
    )
    assert next(f for f in flags if f["symbol"] == "X")["flag"] == rules.TRIM


def test_trim_beats_average_on_overweight_loser():
    flags, _ = rules.evaluate(
        [{"symbol": "X", "qty": 100, "avg_cost": 100.0, "ltp": 85.0},  # -15%, ~100% wt
         {"symbol": "FILL", "qty": 1, "avg_cost": 1.0, "ltp": 1.0}],
        {}, TODAY,
    )
    assert next(f for f in flags if f["symbol"] == "X")["flag"] == rules.TRIM


def test_trail_beats_average_on_small_dip_far_below_peak():
    # -15% vs cost (AVERAGE band) but also >20% below a real prior peak -> TRAIL wins
    f = _flag_for(85.0, avg=100.0, state={"X": {"peak": 130.0}})
    assert f["flag"] == rules.TRAIL_WATCH


# --- missing price -------------------------------------------------------

def test_missing_price_flags_no_price():
    f = _flag_for(None)
    assert f["flag"] == rules.NO_PRICE
    assert f["reminder"] is False


# --- state seeding -------------------------------------------------------

def test_first_run_seeds_peak_from_max_ltp_avgcost():
    _, new_state = rules.evaluate(
        [{"symbol": "X", "qty": 1, "avg_cost": 100.0, "ltp": 120.0}], {}, TODAY,
    )
    assert new_state["X"]["peak"] == 120.0


# --- corp-action detection (RULES-06, D-09) -------------------------------

def test_detect_corp_action_true_on_bonus_shape():
    # 1:1 bonus: qty doubles, avg_cost halves -> capital flat
    assert rules._detect_corp_action(100, 200.0, 200, 100.0) is True


def test_detect_corp_action_false_on_real_average_buy():
    # +25% qty at ~market price -> capital moved 30%, not flat
    assert rules._detect_corp_action(100, 100.0, 125, 104.0) is False


def test_detect_corp_action_false_when_no_prior_qty():
    assert rules._detect_corp_action(None, None, 150, 100.0) is False


def test_detect_corp_action_false_when_qty_growth_at_or_below_threshold():
    # exactly 5% growth does not trip the strict-> threshold
    assert rules._detect_corp_action(100, 100.0, 105, 100.0) is False


def test_corp_action_overrides_would_be_average_flag_and_hides_pct():
    state = {"X": {"qty": 5, "avg_cost": 200.0}}
    f = _flag_for(90.0, avg=100.0, qty=10, state=state)
    assert f["flag"] == rules.CORP_ACTION
    assert f["pct"] is None


def test_corp_action_overweight_still_trims():
    flags, _ = rules.evaluate(
        [{"symbol": "X", "qty": 200, "avg_cost": 100.0, "ltp": 90.0},
         {"symbol": "FILL", "qty": 1, "avg_cost": 1.0, "ltp": 1.0}],
        {"X": {"qty": 100, "avg_cost": 200.0}}, TODAY,
    )
    assert next(f for f in flags if f["symbol"] == "X")["flag"] == rules.TRIM


def test_corp_action_still_trail_watches_far_below_peak():
    state = {"X": {"peak": 500.0, "qty": 5, "avg_cost": 200.0}}
    f = _flag_for(90.0, avg=100.0, qty=10, state=state)
    assert f["flag"] == rules.TRAIL_WATCH
