"""Tests for notify.py: pure format_digest + mocked-HTTP send (TEST-02).

No live network calls anywhere in this file.
"""

from datetime import date
from unittest.mock import Mock, patch

import pytest

import notify


def flag(symbol, flag_name, message=None, reminder=False):
    return {
        "symbol": symbol,
        "flag": flag_name,
        "pct": 0.0,
        "weight": 0.0,
        "pct_below_peak": 0.0,
        "reminder": reminder,
        "message": message or f"{symbol}: {flag_name}",
    }


def portfolio(total_value=500000.0, overall_pnl_pct=0.05):
    return {
        "total_value": total_value,
        "overall_pnl_pct": overall_pnl_pct,
        "date": date(2026, 7, 9),
    }


# --- format_digest: header ---


def test_header_shows_value_and_overall_pnl_pct():
    text = notify.format_digest([], portfolio(total_value=500000.0, overall_pnl_pct=0.05))
    assert "5.00" in text or "500,000" in text  # value present in some form
    assert "5.0%" in text


def test_header_includes_date():
    text = notify.format_digest([], portfolio())
    assert "09 Jul" in text


# --- format_digest: non-HOLD only + all quiet ---


def test_hold_stocks_render_in_compact_summary_not_as_action():
    text = notify.format_digest([flag("TCS", "HOLD")], portfolio())
    assert "TCS" in text and "HOLDING" in text


def test_nothing_to_act_on_when_only_holds():
    flags = [flag("TCS", "HOLD"), flag("INFY", "HOLD")]
    text = notify.format_digest(flags, portfolio())
    assert "nothing to act on" in text.lower()
    assert "TCS" in text and "INFY" in text  # still listed in HOLDING summary


def test_all_quiet_when_flags_list_empty():
    assert "all quiet" in notify.format_digest([], portfolio()).lower()


# --- format_digest: grouping/ordering ---


def test_groups_ordered_action_then_opportunity_then_no_price():
    flags = [
        flag("CAPINVIT", "NO PRICE"),
        flag("INFY", "AVERAGE", reminder=True),
        flag("RELIANCE", "STOP"),
    ]
    text = notify.format_digest(flags, portfolio())
    assert text.index("RELIANCE") < text.index("INFY") < text.index("CAPINVIT")


def test_action_group_covers_stop_trim_trail_watch():
    flags = [flag("A", "STOP"), flag("B", "TRIM"), flag("C", "TRAIL WATCH")]
    text = notify.format_digest(flags, portfolio())
    assert all(sym in text for sym in ("A", "B", "C"))


def test_opportunity_group_covers_both_book_tiers_and_average():
    flags = [flag("D", "AVERAGE", reminder=True), flag("E", "BOOK 50%"), flag("G", "BOOK 25%")]
    text = notify.format_digest(flags, portfolio())
    assert all(sym in text for sym in ("D", "E", "G"))


def test_no_price_surfaces_as_explicit_note_not_omission():
    text = notify.format_digest([flag("F", "NO PRICE")], portfolio())
    assert "F" in text and "NO PRICE" in text


# --- AVERAGE 3-gate reminder (RULES-05) ---


def test_average_line_carries_3_gate_reminder():
    text = notify.format_digest([flag("INFY", "AVERAGE", reminder=True)], portfolio())
    assert "gate" in text.lower()


def test_non_average_line_has_no_gate_reminder_text():
    text = notify.format_digest([flag("RELIANCE", "STOP")], portfolio())
    assert "gate" not in text.lower()


# --- send() (mocked HTTP, TEST-02) ---


@patch("notify.requests.post")
def test_send_posts_expected_payload_no_format_mode_key(mock_post):
    mock_post.return_value = Mock(status_code=200, raise_for_status=Mock())
    notify.send(token="T", chat_id="C", text="all quiet")
    mock_post.assert_called_once_with(
        "https://api.telegram.org/botT/sendMessage",
        json={"chat_id": "C", "text": "all quiet"},
        timeout=10,
    )


@patch("notify.requests.post")
def test_send_failure_propagates(mock_post):
    mock_post.return_value = Mock(status_code=401)
    mock_post.return_value.raise_for_status.side_effect = Exception("401 Unauthorized")
    with pytest.raises(Exception):
        notify.send(token="bad", chat_id="C", text="msg")


@patch("notify.requests.post")
def test_send_truncates_long_text_on_newline_boundary(mock_post):
    mock_post.return_value = Mock(status_code=200, raise_for_status=Mock())
    long_text = "\n".join(f"line {i}" for i in range(2000))
    notify.send(token="T", chat_id="C", text=long_text)
    sent_text = mock_post.call_args.kwargs["json"]["text"]
    assert len(sent_text) <= notify.TELEGRAM_MAX_LEN
    assert not sent_text.endswith("line 1999")
