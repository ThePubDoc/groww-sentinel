"""Tests for the optional sentiment layer -- mocked headlines + batched scorer,
no network, no live LLM calls (TEST-02). adjust() returns (flags, new_cache)
and reuses a same-day cache entry instead of re-scoring (D-10)."""

from datetime import date
from unittest.mock import patch

import sentiment

TODAY = date(2026, 7, 10)
YESTERDAY = date(2026, 7, 9)


def avg(symbol="RELIANCE"):
    return {"symbol": symbol, "flag": "AVERAGE", "shares": 12, "value": 15000.0,
            "reminder": True, "pct": -0.14}


def other(symbol="INDUSINDBK", flag="BOOK 50%"):
    return {"symbol": symbol, "flag": flag, "shares": 50, "value": 50000.0,
            "reminder": False, "pct": 0.54}


def test_no_key_is_a_noop():
    flags = [avg()]
    cache = {"x": 1}
    out_flags, out_cache = sentiment.adjust(flags, None, cache, TODAY)
    assert out_flags is flags
    assert out_cache is cache


def test_bearish_downgrades_average_to_avoid():
    with patch("sentiment.fetch_headlines", return_value=["bad news"]), \
         patch("sentiment.score_batch",
               return_value={"RELIANCE": {"label": "bearish", "reason": "fraud probe"}}):
        out, cache = sentiment.adjust([avg()], "k", {}, TODAY)
    assert out[0]["flag"] == sentiment.AVOID
    assert out[0]["reminder"] is False
    assert out[0]["shares"] == 0
    assert out[0]["sentiment"]["reason"] == "fraud probe"
    assert cache["RELIANCE"] == {"date": "2026-07-10", "label": "bearish", "reason": "fraud probe"}


def test_bullish_leaves_average_unchanged():
    with patch("sentiment.fetch_headlines", return_value=["great news"]), \
         patch("sentiment.score_batch",
               return_value={"RELIANCE": {"label": "bullish", "reason": "strong results"}}):
        out, _cache = sentiment.adjust([avg()], "k", {}, TODAY)
    assert out[0]["flag"] == "AVERAGE"


def test_only_one_model_call_for_many_candidates():
    flags = [avg("A"), avg("B"), avg("C")]
    with patch("sentiment.fetch_headlines", return_value=["h"]), \
         patch("sentiment.score_batch", return_value={}) as sb:
        sentiment.adjust(flags, "k", {}, TODAY)
    sb.assert_called_once()  # batched: single call regardless of candidate count


def test_non_average_flags_never_scored():
    with patch("sentiment.fetch_headlines") as fh, patch("sentiment.score_batch") as sb:
        out, _cache = sentiment.adjust([other()], "k", {}, TODAY)
    assert out[0]["flag"] == "BOOK 50%"
    fh.assert_not_called()
    sb.assert_not_called()


def test_no_headlines_skips_model_call():
    with patch("sentiment.fetch_headlines", return_value=[]), patch("sentiment.score_batch") as sb:
        out, _cache = sentiment.adjust([avg()], "k", {}, TODAY)
    assert out[0]["flag"] == "AVERAGE"
    sb.assert_not_called()


def test_scorer_error_degrades_to_original_flag():
    with patch("sentiment.fetch_headlines", return_value=["news"]), \
         patch("sentiment.score_batch", side_effect=RuntimeError("api down")):
        out, _cache = sentiment.adjust([avg()], "k", {}, TODAY)
    assert out[0]["flag"] == "AVERAGE"  # never breaks the run


def test_scorer_error_keeps_prior_cache_entry_for_failed_symbol():
    prior_cache = {"RELIANCE": {"date": "2026-07-01", "label": "bullish", "reason": "old"}}
    with patch("sentiment.fetch_headlines", return_value=["news"]), \
         patch("sentiment.score_batch", side_effect=RuntimeError("api down")):
        _out, cache = sentiment.adjust([avg()], "k", prior_cache, TODAY)
    assert cache["RELIANCE"] == prior_cache["RELIANCE"]


def test_same_day_cache_hit_skips_fetch_and_score_batch():
    cache = {"RELIANCE": {"date": "2026-07-10", "label": "bearish", "reason": "cached bad news"}}
    with patch("sentiment.fetch_headlines") as fh, patch("sentiment.score_batch") as sb:
        out, new_cache = sentiment.adjust([avg()], "k", cache, TODAY)
    fh.assert_not_called()
    sb.assert_not_called()
    assert out[0]["flag"] == sentiment.AVOID  # cached bearish still downgrades
    assert new_cache["RELIANCE"] == cache["RELIANCE"]


def test_stale_next_day_cache_entry_triggers_rescore():
    cache = {"RELIANCE": {"date": "2026-07-09", "label": "bullish", "reason": "yesterday"}}
    with patch("sentiment.fetch_headlines", return_value=["fresh news"]), \
         patch("sentiment.score_batch",
               return_value={"RELIANCE": {"label": "neutral", "reason": "steady"}}) as sb:
        out, new_cache = sentiment.adjust([avg()], "k", cache, TODAY)
    sb.assert_called_once()
    assert out[0]["flag"] == "AVERAGE"
    assert new_cache["RELIANCE"] == {"date": "2026-07-10", "label": "neutral", "reason": "steady"}


def test_new_cache_pruned_to_symbols_in_current_flags():
    cache = {"OLD_SOLD_SYMBOL": {"date": "2026-07-10", "label": "bearish", "reason": "stale holding"}}
    with patch("sentiment.fetch_headlines", return_value=["news"]), \
         patch("sentiment.score_batch",
               return_value={"RELIANCE": {"label": "neutral", "reason": "ok"}}):
        _out, new_cache = sentiment.adjust([avg()], "k", cache, TODAY)
    assert "OLD_SOLD_SYMBOL" not in new_cache
