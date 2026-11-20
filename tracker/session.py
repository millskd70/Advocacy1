"""Decide whether the Legislature is in session and whether to scan today."""
from __future__ import annotations

import datetime as dt


def second_monday_of_january(year: int) -> dt.date:
    d = dt.date(year, 1, 1)
    first_monday = d + dt.timedelta(days=(0 - d.weekday()) % 7)
    return first_monday + dt.timedelta(days=7)


def session_window(year: int, session_end: str = "05-31") -> tuple[dt.date, dt.date]:
    m, d = (int(x) for x in session_end.split("-"))
    return second_monday_of_january(year), dt.date(year, m, d)


def in_session_window(today: dt.date, session_end: str = "05-31") -> bool:
    start, end = session_window(today.year, session_end)
    return start <= today <= end


def recent_floor_activity(bills: list[dict], today: dt.date, days: int = 3) -> bool:
    """True if any bill (tracked or not) had a recorded action in the last few days."""
    cutoff = (today - dt.timedelta(days=days)).isoformat()
    for b in bills:
        if (b.get("last_action_date") or "") >= cutoff:
            return True
    return False


def month_was_in_session(year: int, month: int, session_end: str = "05-31") -> bool:
    start, end = session_window(year, session_end)
    first = dt.date(year, month, 1)
    nxt = dt.date(year + (month == 12), month % 12 + 1, 1)
    last = nxt - dt.timedelta(days=1)
    return first <= end and last >= start
