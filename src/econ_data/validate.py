"""Validation for the dates and values of fetched observations.

The valid range for each indicator comes from config. Both functions return
(True, None) when the input is accepted and (False, message) when it is not.
"""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta

from .config import get_indicator

EARLIEST_YEAR = 1950
MAX_DAYS_AHEAD = 365


def validate_value(indicator_id: str, value: float) -> tuple[bool, str | None]:
    """Check a value against the range config sets for this indicator.

    The minimum and maximum themselves are accepted. NaN and infinity are
    rejected. Raises KeyError if config has no indicator with this id.
    """
    indicator = get_indicator(indicator_id)
    label = f"{indicator.name} ({indicator.units})"

    # Every comparison with NaN is False, so it would pass the range checks below.
    if not math.isfinite(value):
        return False, f"{label} value {value} is not a finite number"
    if value < indicator.min_value:
        return False, f"{label} value {value} is below minimum {indicator.min_value}"
    if value > indicator.max_value:
        return False, f"{label} value {value} exceeds maximum {indicator.max_value}"
    return True, None


def validate_date(date_str: str, today: date | None = None) -> tuple[bool, str | None]:
    """Check that a YYYY-MM-DD string is a real date between 1950 and one year ahead.

    `today` defaults to the current date; passing one fixes the reference point.
    """
    today = date.today() if today is None else today

    try:
        parsed = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return False, f"Invalid date format: {date_str}"

    if parsed.year < EARLIEST_YEAR:
        return False, f"Date {date_str} is before {EARLIEST_YEAR}"
    if parsed > today + timedelta(days=MAX_DAYS_AHEAD):
        return False, f"Date {date_str} is too far in the future"
    return True, None