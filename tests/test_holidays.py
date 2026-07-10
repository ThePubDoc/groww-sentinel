"""Tests for holidays.py: static NSE 2026 holiday set + is_trading_holiday
(RUN-02, D-03). Pure stdlib, no I/O, no network.
"""

from datetime import date

import holidays


def test_republic_day_2026_is_holiday():
    is_holiday, warning = holidays.is_trading_holiday(date(2026, 1, 26))
    assert is_holiday is True
    assert warning is None


def test_ordinary_weekday_2026_is_not_holiday():
    is_holiday, warning = holidays.is_trading_holiday(date(2026, 1, 27))
    assert is_holiday is False
    assert warning is None


def test_last_seeded_date_christmas_2026_is_holiday():
    is_holiday, warning = holidays.is_trading_holiday(date(2026, 12, 25))
    assert is_holiday is True
    assert warning is None


def test_date_past_last_seeded_year_warns_and_is_not_holiday():
    is_holiday, warning = holidays.is_trading_holiday(date(2028, 1, 1))
    assert is_holiday is False
    assert warning is not None
    assert "2028" in warning


def test_module_holds_exactly_fifteen_2026_dates():
    assert len(holidays.NSE_HOLIDAYS_2026) == 15
    assert holidays.LAST_SEEDED_YEAR == 2026


def test_weekend_dates_are_not_in_the_holiday_set():
    # Weekends are sentinel's concern (today.weekday()), not holidays.py's.
    saturday = date(2026, 7, 11)
    assert saturday not in holidays.NSE_HOLIDAYS_2026
