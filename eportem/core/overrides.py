"""Holiday, location and business-trip overrides as data.

The legacy override files hold "START,END" (or a single date) for holidays and
business trips, and "LOCATION,DATE" for a one-day location. These functions
parse that text; they never touch files.
"""
import datetime

from eportem.core.schedule import LOCATIONS


class OverrideFormatError(ValueError):
    """The override text can't be understood."""


def parse_date_range(text):
    """(start, end) from 'START,END' or a single 'DATE' (YYYY-MM-DD). Raises
    OverrideFormatError, which must stop clocking when it is a holiday."""
    parts = [p.strip() for p in text.split(",")]
    if len(parts) not in (1, 2):
        raise OverrideFormatError(f"expected 'START,END' or a single date, got {text!r}")
    try:
        start = datetime.date.fromisoformat(parts[0])
        end = datetime.date.fromisoformat(parts[-1])
    except ValueError as e:
        raise OverrideFormatError(f"expected YYYY-MM-DD dates, got {text!r}") from e
    if end < start:
        raise OverrideFormatError(f"the end date {end} is before the start date {start}")
    return start, end


def parse_strict_date_range(text):
    """(start, end) from exactly 'START,END'; raises ValueError otherwise.
    The business-trip file has always required both dates."""
    start_str, end_str = text.strip().split(",")
    return datetime.date.fromisoformat(start_str), datetime.date.fromisoformat(end_str)


def parse_location_override(text):
    """(location, date) from 'LOCATION,DATE'. Raises ValueError."""
    location, date_str = [p.strip() for p in text.split(",")]
    location = location.lower()
    if location not in LOCATIONS:
        raise ValueError(f"location must be home or office, got {location!r}")
    return location, datetime.date.fromisoformat(date_str)


def range_state(start, end, today):
    """'past', 'active' or 'future' for an inclusive date range."""
    if end < today:
        return "past"
    if start <= today:
        return "active"
    return "future"
