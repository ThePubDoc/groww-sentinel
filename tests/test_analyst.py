"""Tests for the senior-analyst overlay -- pure apply_overrides + mocked-I/O
analyze (no network, no live LLM). The high-confidence guardrail and same-day
cache reuse are the behaviors that matter most (money-path)."""

from datetime import date
from unittest.mock import patch

import analyst
import rules

TODAY = date(2026, 7, 10)


def flag(symbol="RELIANCE", f="HOLD", pct=-0.04, weight=0.2, shares=0, value=0.0):
    return {"symbol": symbol, "flag": f, "pct": pct, "weight": weight,
            "pct_below_peak": 0.0, "shares": shares, "value": value, "reminder": False}


def holding(symbol="RELIANCE", qty=10, ltp=2400.0):
    return {"symbol": symbol, "qty": qty, "avg_cost": 2500.0, "ltp": ltp}


# --- apply_overrides (pure) -------------------------------------------------

def test_agreeing_verdict_leaves_flag_untouched():
    f = flag(f="HOLD")
    scores = {"RELIANCE": {"flag": "HOLD", "confidence": "high", "thesis": "steady"}}
    out = analyst.apply_overrides([f], scores, [holding()], 24000.0)
    assert out[0] == f  # unchanged, no annotations


def test_high_confidence_disagreement_applies_and_resizes():
    f = flag(f="HOLD", shares=0, value=0.0)
    scores = {"RELIANCE": {"flag": "STOP", "confidence": "high",
                           "thesis": "guidance cut", "key_risk": "turnaround"}}
    out = analyst.apply_overrides([f], scores, [holding(qty=10, ltp=2400.0)], 24000.0)
    assert out[0]["flag"] == "STOP"
    assert out[0]["shares"] == 10                     # STOP -> exit whole position
    assert out[0]["value"] == 24000.0
    assert out[0]["analyst_override"] == {
        "was": "HOLD", "confidence": "high", "thesis": "guidance cut", "key_risk": "turnaround"}


def test_medium_confidence_disagreement_is_suggestion_not_applied():
    f = flag(f="HOLD")
    scores = {"RELIANCE": {"flag": "STOP", "confidence": "medium", "thesis": "maybe weak"}}
    out = analyst.apply_overrides([f], scores, [holding()], 24000.0)
    assert out[0]["flag"] == "HOLD"                   # deterministic flag holds
    assert "analyst_override" not in out[0]
    assert out[0]["analyst_suggestion"]["flag"] == "STOP"


def test_average_override_sets_reminder_and_size():
    f = flag(f="HOLD")
    scores = {"RELIANCE": {"flag": "AVERAGE", "confidence": "high", "thesis": "buy dip"}}
    out = analyst.apply_overrides([f], scores, [holding(qty=10, ltp=2400.0)], 24000.0)
    assert out[0]["flag"] == "AVERAGE"
    assert out[0]["reminder"] is True
    assert out[0]["shares"] == rules.size_position("AVERAGE", 10, 2400.0, 24000.0)


def test_no_price_and_corp_action_never_overridden():
    scores = {"A": {"flag": "STOP", "confidence": "high", "thesis": "x"},
              "B": {"flag": "STOP", "confidence": "high", "thesis": "y"}}
    flags = [flag("A", f=rules.NO_PRICE), flag("B", f=rules.CORP_ACTION)]
    out = analyst.apply_overrides(flags, scores, [holding("A"), holding("B")], 1.0)
    assert out[0]["flag"] == rules.NO_PRICE
    assert out[1]["flag"] == rules.CORP_ACTION


def test_symbol_without_verdict_passes_through():
    f = flag(f="BOOK 50%")
    out = analyst.apply_overrides([f], {}, [holding()], 24000.0)
    assert out[0] == f


# --- analyze (orchestration, mocked I/O) ------------------------------------

def test_no_key_is_a_noop():
    flags = [flag()]
    cache = {"brief": {"date": "old"}}
    out, brief, out_cache = analyst.analyze(flags, {"total_value": 1.0}, [holding()], None, cache, TODAY)
    assert out is flags
    assert brief is None
    assert out_cache is cache


def test_same_day_cache_reuses_verdicts_without_fetch_or_call():
    cache = {
        "brief": {"date": "2026-07-10", "regime": "calm"},
        "RELIANCE": {"date": "2026-07-10", "flag": "STOP", "confidence": "high", "thesis": "cached"},
    }
    with patch("analyst.fetch_fundamentals") as ff, patch("analyst.fetch_headlines") as fh, \
         patch("analyst.score_portfolio") as sp, patch("analyst._make_client") as mc:
        out, brief, out_cache = analyst.analyze(
            [flag(f="HOLD")], {"total_value": 24000.0}, [holding()], "k", cache, TODAY)
    ff.assert_not_called()
    fh.assert_not_called()
    sp.assert_not_called()
    mc.assert_not_called()
    assert out[0]["flag"] == "STOP"          # cached high-confidence override applied
    assert brief == cache["brief"]
    assert out_cache is cache


def test_score_failure_degrades_to_deterministic_flags_no_brief():
    cache = {}
    with patch("analyst.fetch_fundamentals", return_value={}), \
         patch("analyst.fetch_headlines", return_value=[]), \
         patch("analyst.prices.get_macro", return_value={"nifty_5d_pct": None, "vix": None}), \
         patch("analyst._make_client", return_value=object()), \
         patch("analyst.score_portfolio", side_effect=RuntimeError("api down")):
        out, brief, out_cache = analyst.analyze(
            [flag(f="HOLD")], {"total_value": 24000.0}, [holding()], "k", cache, TODAY)
    assert out[0]["flag"] == "HOLD"
    assert brief is None
    assert out_cache is cache


def test_fresh_score_builds_dated_pruned_cache_and_applies_override():
    cache = {"OLD_SOLD": {"date": "2026-07-01", "flag": "STOP", "confidence": "high"}}
    result = {
        "brief": {"regime": "risk-off", "stance": "defensive"},
        "stocks": {"RELIANCE": {"flag": "STOP", "confidence": "high",
                                "thesis": "downgrade", "key_risk": "recovery"}},
    }
    with patch("analyst.fetch_fundamentals", return_value={"sector": "Energy"}), \
         patch("analyst.fetch_headlines", return_value=["bad news"]), \
         patch("analyst.prices.get_macro", return_value={"nifty_5d_pct": -0.02, "vix": 15.0}), \
         patch("analyst._make_client", return_value=object()), \
         patch("analyst.score_portfolio", return_value=result):
        out, brief, out_cache = analyst.analyze(
            [flag(f="HOLD")], {"total_value": 24000.0}, [holding()], "k", cache, TODAY)
    assert out[0]["flag"] == "STOP"
    assert out[0]["analyst_override"]["was"] == "HOLD"
    assert brief["date"] == "2026-07-10"
    assert "OLD_SOLD" not in out_cache            # pruned to current holdings
    assert out_cache["RELIANCE"]["date"] == "2026-07-10"


def test_score_portfolio_drops_out_of_vocab_flags():
    class FakeResp:
        text = ('{"brief":{"regime":"x"},"stocks":{'
                '"A":{"flag":"MOON","confidence":"high","thesis":"t"},'
                '"B":{"flag":"STOP","confidence":"high","thesis":"t"}}}')

    class FakeModels:
        def generate_content(self, **kwargs):
            return FakeResp()

    class FakeClient:
        models = FakeModels()

    result = analyst.score_portfolio(FakeClient(), [flag("B", f="HOLD")],
                                     {"overall_pnl_pct": 0.1}, {}, {}, {})
    assert "A" not in result["stocks"]            # MOON not in vocab, dropped
    assert result["stocks"]["B"]["flag"] == "STOP"
