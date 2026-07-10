"""Static NSE trading-holiday calendar (RUN-02, D-03).

Hand-maintained stdlib-only date set -- no `pandas_market_calendars` dependency
(D-03: avoid the pandas weight, can't silently drift). Weekends are NOT
included here; sentinel checks `today.weekday() >= 5` separately.

2027 dates: NOT YET PUBLISHED by NSE or any brokerage as of this writing.
NSE typically releases the following year's holiday list around December.
Add 2027 dates here (and bump LAST_SEEDED_YEAR) once published; until then
is_trading_holiday() warns loudly rather than silently assuming "open".
"""

from datetime import date

# NSE full trading holidays, 2026 (weekday holidays only).
# [CITED: zerodha.com/marketintel/holiday-calendar, cleartax.in/s/nse-holidays-2026]
NSE_HOLIDAYS_2026 = {
    date(2026, 1, 15),   # Maharashtra municipal elections
    date(2026, 1, 26),   # Republic Day
    date(2026, 3, 3),    # Holi
    date(2026, 3, 26),   # Shri Ram Navami
    date(2026, 3, 31),   # Shri Mahavir Jayanti
    date(2026, 4, 3),    # Good Friday
    date(2026, 4, 14),   # Dr. Baba Saheb Ambedkar Jayanti
    date(2026, 5, 1),    # Maharashtra Day
    date(2026, 5, 28),   # Bakri Id
    date(2026, 6, 26),   # Muharram
    date(2026, 9, 14),   # Ganesh Chaturthi
    date(2026, 10, 2),   # Mahatma Gandhi Jayanti
    date(2026, 10, 20),  # Dussehra
    date(2026, 11, 10),  # Diwali-Balipratipada
    date(2026, 12, 25),  # Christmas
}

LAST_SEEDED_YEAR = 2026
ALL_HOLIDAYS = NSE_HOLIDAYS_2026  # union point for future years


def is_trading_holiday(today: date) -> tuple[bool, str | None]:
    """Returns (is_holiday, warning). Warning is set only when `today` is
    past the last seeded year -- fail-loud per D-03, never silently assume
    the market is open."""
    warning = None
    if today.year > LAST_SEEDED_YEAR:
        warning = (
            f"holidays.py has no data for {today.year} "
            f"(last seeded: {LAST_SEEDED_YEAR}) -- update the static list"
        )
    return today in ALL_HOLIDAYS, warning
