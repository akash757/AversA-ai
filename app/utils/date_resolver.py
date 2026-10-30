from typing import Optional
from datetime import datetime, date, timedelta, timezone
import re

DEFAULT_TIMEZONE = "Asia/Kolkata"
IST = timezone(timedelta(hours=5, minutes=30))

WEEKDAYS = {
    "monday": 0,
    "mon": 0,
    "tuesday": 1,
    "tue": 1,
    "wednesday": 2,
    "wed": 2,
    "thursday": 3,
    "thu": 3,
    "friday": 4,
    "fri": 4,
    "saturday": 5,
    "sat": 5,
    "sunday": 6,
    "sun": 6,
}


def _get_tz(timezone_str: str) -> timezone:
    """Returns a timezone object supporting Windows without requiring external tzdata."""
    norm = (timezone_str or "").strip().lower()
    if norm in ("asia/kolkata", "ist", "asia/calcutta"):
        return IST
    if norm in ("utc", "z", "gmt"):
        return timezone.utc
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(timezone_str)
    except Exception:
        return timezone.utc


def resolve_due_date(
    due_phrase: Optional[str],
    meeting_date: Optional[datetime],
    timezone_str: str = DEFAULT_TIMEZONE,
) -> Optional[str]:
    """
    Deterministically resolves a spoken due phrase against a meeting timestamp.
    
    Fixed rules:
    - "today": meeting date in the configured timezone.
    - "tomorrow": meeting date + 1 day in the configured timezone.
    - Day after tomorrow: meeting date + 2 days.
    - Weekday name (e.g. "friday", "this friday", "by next monday"):
      the next occurrence of that weekday strictly after the meeting day.
    - Vague phrases ("next week", "soon", "by end of sprint"): returns None.
    
    Returns ISO date string 'YYYY-MM-DD' or None.
    """
    if not due_phrase or not due_phrase.strip() or not meeting_date:
        return None

    phrase = due_phrase.strip().lower()
    tz = _get_tz(timezone_str)

    if meeting_date.tzinfo is None:
        meeting_local = meeting_date.replace(tzinfo=timezone.utc).astimezone(tz)
    else:
        meeting_local = meeting_date.astimezone(tz)

    anchor_date: date = meeting_local.date()

    # Clean leading prepositions
    clean = re.sub(r"^(?:by|before|on|around|due)\s+", "", phrase).strip()

    # 1. "today" / "end of today" / "eod"
    if clean in ("today", "eod", "end of day", "end of today"):
        return anchor_date.isoformat()

    # 2. "tomorrow" / "by tomorrow"
    if clean in ("tomorrow", "end of tomorrow"):
        return (anchor_date + timedelta(days=1)).isoformat()

    # 3. "day after tomorrow"
    if clean in ("day after tomorrow", "the day after tomorrow"):
        return (anchor_date + timedelta(days=2)).isoformat()

    # 4. Check for weekday names (e.g. "friday", "this friday", "next monday")
    words = re.findall(r"[a-z]+", clean)
    for word in words:
        if word in WEEKDAYS:
            target_weekday = WEEKDAYS[word]
            current_weekday = anchor_date.weekday()
            days_ahead = (target_weekday - current_weekday) % 7
            if days_ahead == 0:
                # If meeting is on Friday and speaker says "by Friday", it refers to next week's Friday (+7)
                days_ahead = 7
            return (anchor_date + timedelta(days=days_ahead)).isoformat()

    # Vague or unresolvable phrases stay None
    return None
