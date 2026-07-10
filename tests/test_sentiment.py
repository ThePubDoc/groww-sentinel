"""Tests for the optional sentiment layer -- mocked headlines + batched scorer,
no network, no live LLM calls (TEST-02)."""

from unittest.mock import patch

import sentiment


def avg(symbol="RELIANCE"):
    return {"symbol": symbol, "flag": "AVERAGE", "shares": 12, "value": 15000.0,
            "reminder": True, "pct": -0.14}


def other(symbol="INDUSINDBK", flag="BOOK 50%"):
    return {"symbol": symbol, "flag": flag, "shares": 50, "value": 50000.0,
            "reminder": False, "pct": 0.54}


def test_no_key_is_a_noop():
    flags = [avg()]
    assert sentiment.adjust(flags, None) is flags


def test_bearish_downgrades_average_to_avoid():
    with patch("sentiment.fetch_headlines", return_value=["bad news"]), \
         patch("sentiment.score_batch",
               return_value={"RELIANCE": {"label": "bearish", "reason": "fraud probe"}}):
        out = sentiment.adjust([avg()], api_key="k")
    assert out[0]["flag"] == sentiment.AVOID
    assert out[0]["reminder"] is False
    assert out[0]["shares"] == 0
    assert out[0]["sentiment"]["reason"] == "fraud probe"


def test_bullish_leaves_average_unchanged():
    with patch("sentiment.fetch_headlines", return_value=["great news"]), \
         patch("sentiment.score_batch",
               return_value={"RELIANCE": {"label": "bullish", "reason": "strong results"}}):
        out = sentiment.adjust([avg()], api_key="k")
    assert out[0]["flag"] == "AVERAGE"


def test_only_one_model_call_for_many_candidates():
    flags = [avg("A"), avg("B"), avg("C")]
    with patch("sentiment.fetch_headlines", return_value=["h"]), \
         patch("sentiment.score_batch", return_value={}) as sb:
        sentiment.adjust(flags, api_key="k")
    sb.assert_called_once()  # batched: single call regardless of candidate count


def test_non_average_flags_never_scored():
    with patch("sentiment.fetch_headlines") as fh, patch("sentiment.score_batch") as sb:
        out = sentiment.adjust([other()], api_key="k")
    assert out[0]["flag"] == "BOOK 50%"
    fh.assert_not_called()
    sb.assert_not_called()


def test_no_headlines_skips_model_call():
    with patch("sentiment.fetch_headlines", return_value=[]), patch("sentiment.score_batch") as sb:
        out = sentiment.adjust([avg()], api_key="k")
    assert out[0]["flag"] == "AVERAGE"
    sb.assert_not_called()


def test_scorer_error_degrades_to_original_flag():
    with patch("sentiment.fetch_headlines", return_value=["news"]), \
         patch("sentiment.score_batch", side_effect=RuntimeError("api down")):
        out = sentiment.adjust([avg()], api_key="k")
    assert out[0]["flag"] == "AVERAGE"  # never breaks the run
