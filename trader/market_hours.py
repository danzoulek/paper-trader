"""US stock market (NYSE/Nasdaq) regular-session calendar.

Regular hours are 9:30-16:00 New York time on weekdays, minus exchange
holidays, with 13:00 early closes on a few days. The holiday list covers
2026-2027; extend it each year (NYSE publishes it at nyse.com/markets/hours-calendars).
"""
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
OPEN = time(9, 30)
CLOSE = time(16, 0)
EARLY_CLOSE = time(13, 0)

HOLIDAYS = {
    # 2026
    date(2026, 1, 1), date(2026, 1, 19), date(2026, 2, 16), date(2026, 4, 3),
    date(2026, 5, 25), date(2026, 6, 19), date(2026, 7, 3), date(2026, 9, 7),
    date(2026, 11, 26), date(2026, 12, 25),
    # 2027
    date(2027, 1, 1), date(2027, 1, 18), date(2027, 2, 15), date(2027, 3, 26),
    date(2027, 5, 31), date(2027, 6, 18), date(2027, 7, 5), date(2027, 9, 6),
    date(2027, 11, 25), date(2027, 12, 24),
}

EARLY_CLOSES = {
    date(2026, 11, 27), date(2026, 12, 24),
    date(2027, 11, 26),
}


def is_trading_day(d: date) -> bool:
    return d.weekday() < 5 and d not in HOLIDAYS


def session_close(d: date) -> time:
    return EARLY_CLOSE if d in EARLY_CLOSES else CLOSE


def is_market_open(now: datetime | None = None) -> bool:
    now = (now or datetime.now(NY)).astimezone(NY)
    d = now.date()
    if not is_trading_day(d):
        return False
    return OPEN <= now.time() < session_close(d)
