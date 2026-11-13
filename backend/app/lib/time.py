"""Time helpers. All catalog times are local; clock times are HH:MM, and 24:00 means end of day."""
from datetime import date, datetime, timedelta


def parse_date(s: str) -> date:
    return date.fromisoformat(s[:10])


def parse_dt(s: str) -> datetime:
    return datetime.fromisoformat(s)


def minutes_of_day(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def date_range(start: date, nights: int) -> list[date]:
    """The night dates of a stay: start .. start + nights - 1."""
    return [start + timedelta(days=i) for i in range(nights)]
