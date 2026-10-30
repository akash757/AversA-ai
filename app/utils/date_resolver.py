from typing import Optional
from datetime import datetime, date, timedelta, timezone
import re

from app.config import settings

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

NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "fourteen": 14,
}


def _get_tz(timezone_str: Optional[str] = None) -> timezone:
    """Returns a timezone object supporting Windows without requiring external tzdata."""
    tz_name = (timezone_str or getattr(settings, "DEFAULT_TIMEZONE", "Asia/Kolkata")).strip().lower()
    if tz_name in ("asia/kolkata", "ist", "asia/calcutta"):
        return IST
    if tz_name in ("utc", "z", "gmt"):
        return timezone.utc
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(tz_name)
    except Exception:
        return timezone.utc


def resolve_due_date(
    due_phrase: Optional[str],
    meeting_date: Optional[datetime],
    timezone_str: Optional[str] = None,
) -> Optional[str]:
    """
    Deterministically resolves a spoken due phrase against a meeting timestamp.
    
    Fixed rules:
    - "day after tomorrow": meeting date + 2 days.
    - "tomorrow" as a word anywhere (e.g. "by tomorrow afternoon", "tomorrow EOD"): meeting date + 1 day.
    - "today" (e.g. "by end of the day", "eod", "today"): meeting date in local timezone.
    - "in N days" / "in two days": meeting date + N days.
    - "next <weekday>" (e.g. "next Friday"): ambiguous, returns None to let PM confirm.
    - "<weekday>" (e.g. "by Friday", "this Friday"): next occurrence strictly after the meeting day.
      NOTE: If a call occurs on a Friday and a speaker says "by Friday", it resolves to next Friday (+7 days).
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

    # 1. "day after tomorrow"
    if "day after tomorrow" in phrase:
        return (anchor_date + timedelta(days=2)).isoformat()

    # 2. "tomorrow" as a word anywhere (e.g. "by tomorrow afternoon", "tomorrow EOD", "tomorrow evening")
    if re.search(r"\btomorrow\b", phrase):
        return (anchor_date + timedelta(days=1)).isoformat()

    # 3. "today", "end of the day", "end of day", "eod", "cob"
    if (
        re.search(r"\b(?:today|eod|cob)\b", phrase)
        or "end of the day" in phrase
        or "end of day" in phrase
        or "end of today" in phrase
    ):
        return anchor_date.isoformat()

    # 4. "in N days" / "within N days" with digits or number words (e.g. "in two days", "in 3 days")
    in_days_match = re.search(r"\b(?:in|within)\s+(\w+)\s+days?\b", phrase)
    if in_days_match:
        val_str = in_days_match.group(1)
        days_num = int(val_str) if val_str.isdigit() else NUMBER_WORDS.get(val_str)
        if days_num is not None and 1 <= days_num <= 60:
            return (anchor_date + timedelta(days=days_num)).isoformat()

    # 5. "next <weekday>" is ambiguous (e.g. "next Friday" said on Monday could mean this week or next week)
    if re.search(r"\bnext\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", phrase):
        return None

    # 6. Standard weekday name (e.g. "by Friday", "this Friday", "on Tuesday")
    words = re.findall(r"[a-z]+", phrase)
    for word in words:
        if word in WEEKDAYS:
            target_weekday = WEEKDAYS[word]
            current_weekday = anchor_date.weekday()
            days_ahead = (target_weekday - current_weekday) % 7
            if days_ahead == 0:
                # If meeting is on Friday and speaker says "by Friday", refers to next occurrence (+7 days)
                days_ahead = 7
            return (anchor_date + timedelta(days=days_ahead)).isoformat()

    # Vague phrases remain None
    return None
