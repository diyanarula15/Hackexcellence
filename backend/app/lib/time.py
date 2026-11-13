"""Time helpers. All catalog times are local to the place; no time-zone math is done here.

Clock times are "HH:MM". "24:00" means midnight at the end of the day. A window whose end is
earlier than its start (e.g. 06:00-00:30) runs past midnight. Both ends of a window are included.
"""
from datetime import date, datetime, timedelta

WEEKDAYS = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]


def parse_date(s: str) -> date:
    return date.fromisoformat(s[:10])


def parse_dt(s: str) -> datetime:
    """Parse a local date-time "YYYY-MM-DDTHH:MM" or "YYYY-MM-DDTHH:MM:SS"."""
    return datetime.fromisoformat(s)


def fmt_dt(dt: datetime) -> str:
    """Format as the trip-format local date-time "YYYY-MM-DDTHH:MM"."""
    return dt.strftime("%Y-%m-%dT%H:%M")


def minutes_of_day(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def at(day: date, hhmm: str) -> datetime:
    """The datetime of clock time hhmm on day; "24:00" gives the next day's 00:00."""
    return datetime(day.year, day.month, day.day) + timedelta(minutes=minutes_of_day(hhmm))


def window_on(day: date, start: str, until: str) -> tuple[datetime, datetime]:
    """The dated interval of a daily window that opens on `day` (handles overnight and 24:00)."""
    s = at(day, start)
    e = at(day, until)
    if e < s:
        e += timedelta(days=1)
    return s, e


def in_window(t: datetime, start: str, until: str) -> bool:
    """True if t lies inside the daily window, counting a window opened the previous day."""
    for d in (t.date() - timedelta(days=1), t.date()):
        s, e = window_on(d, start, until)
        if s <= t <= e:
            return True
    return False


def on_slot(t: datetime, start: str, until: str, frequency_minutes: int) -> bool:
    """True if t is a scheduled departure: window start + n * frequency, inside the window."""
    for d in (t.date() - timedelta(days=1), t.date()):
        s, e = window_on(d, start, until)
        if s <= t <= e:
            diff = (t - s).total_seconds()
            if diff % (frequency_minutes * 60) == 0:
                return True
    return False


def weekday_code(d: date) -> str:
    return WEEKDAYS[d.weekday()]


def date_range(start: date, nights: int) -> list[date]:
    """The night dates of a stay: start .. start + nights - 1 (crosses month ends correctly)."""
    return [start + timedelta(days=i) for i in range(nights)]


def overlaps(a: tuple[datetime, datetime], b: tuple[datetime, datetime]) -> bool:
    """Half-open overlap: touching end-to-start is not an overlap."""
    return a[0] < b[1] and b[0] < a[1]
