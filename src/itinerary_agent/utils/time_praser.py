import re
from typing import Optional

def normalize_time(value: str) -> Optional[str]:
    """
    Normalizes time strings to 24-hour 'HH:MM' format.

    Examples:
        '1.5 hours' -> '01:30'
        '5pm' -> '17:00'
        'before 6pm' -> '18:00'
        (Returns None if format is invalid)
    """
    value = value.strip().lower()

    # Match: "X hours" or "X.Y hours"
    m = re.match(r"^(\d+(?:\.\d+)?)\s*hours?$", value)
    if m:
        hours_float = float(m.group(1))
        hours = int(hours_float)
        minutes = int(round((hours_float - hours) * 60))
        if 0 <= hours < 24 and 0 <= minutes < 60:
            return f"{hours:02}:{minutes:02}"
        else:
            return None

    # Match: "before N(am/pm)"
    m = re.match(r"^(?:before|by)\s+(\d{1,2})(:(\d{2}))?\s*([ap]m)$", value)
    if m:
        hour = int(m.group(1))
        minute = int(m.group(3) or 0)
        period = m.group(4)
        if 1 <= hour <= 12 and 0 <= minute < 60:
            if period == "pm" and hour != 12:
                hour += 12
            elif period == "am" and hour == 12:
                hour = 0
            return f"{hour:02}:{minute:02}"
        else:
            return None
    m = re.match(r"^(?:before|by)\s+(\d{1,2})\s*([ap]m)$", value)
    if m:
        hour = int(m.group(1))
        period = m.group(2)
        minute = 0
        if 1 <= hour <= 12:
            if period == "pm" and hour != 12:
                hour += 12
            elif period == "am" and hour == 12:
                hour = 0
            return f"{hour:02}:00"
        else:
            return None

    # Match: "N(am/pm)" or "N:MM(am/pm)"
    m = re.match(r"^(\d{1,2})(:(\d{2}))?\s*([ap]m)$", value)
    if m:
        hour = int(m.group(1))
        minute = int(m.group(3) or 0)
        period = m.group(4)
        if 1 <= hour <= 12 and 0 <= minute < 60:
            if period == "pm" and hour != 12:
                hour += 12
            elif period == "am" and hour == 12:
                hour = 0
            return f"{hour:02}:{minute:02}"
        else:
            return None

    # Match: "before N" (24hr)
    m = re.match(r"^(?:before|by)\s+(\d{1,2})(:(\d{2}))?$", value)
    if m:
        hour = int(m.group(1))
        minute = int(m.group(3) or 0)
        if 0 <= hour < 24 and 0 <= minute < 60:
            return f"{hour:02}:{minute:02}"
        else:
            return None

    # Match: 'HH:MM'
    m = re.match(r"^(\d{1,2}):(\d{2})$", value)
    if m:
        hour = int(m.group(1))
        minute = int(m.group(2))
        if 0 <= hour < 24 and 0 <= minute < 60:
            return f"{hour:02}:{minute:02}"
        else:
            return None

    return None