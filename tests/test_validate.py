from datetime import date

import pytest

from src.econ_data.config import INDICATORS
from src.econ_data.validate import validate_date, validate_value

TODAY = date(2026, 11, 12)


@pytest.mark.parametrize(
    "indicator_id,value",
    [
        ("DFF", 5.25),
        ("DFEDTARU", 4.5),
        ("DFEDTARL", 4.25),
        ("FEDFUNDS", 5.33),
        ("SP500", 5000),
        ("VIXCLS", 20),
    ],
)
def test_value_in_range_is_accepted(indicator_id, value):
    assert validate_value(indicator_id, value) == (True, None)


@pytest.mark.parametrize("indicator", INDICATORS, ids=lambda i: i.indicator_id)
def test_minimum_and_maximum_themselves_are_accepted(indicator):
    assert validate_value(indicator.indicator_id, indicator.min_value) == (True, None)
    assert validate_value(indicator.indicator_id, indicator.max_value) == (True, None)


@pytest.mark.parametrize("indicator", INDICATORS, ids=lambda i: i.indicator_id)
def test_value_below_minimum_is_rejected(indicator):
    is_valid, message = validate_value(indicator.indicator_id, indicator.min_value - 1)
    assert is_valid is False
    assert indicator.name in message
    assert "below minimum" in message


@pytest.mark.parametrize("indicator", INDICATORS, ids=lambda i: i.indicator_id)
def test_value_above_maximum_is_rejected(indicator):
    is_valid, message = validate_value(indicator.indicator_id, indicator.max_value + 1)
    assert is_valid is False
    assert indicator.name in message
    assert "exceeds maximum" in message


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_value_is_rejected(value):
    is_valid, message = validate_value("DFF", value)
    assert is_valid is False
    assert "not a finite number" in message


def test_unknown_indicator_raises():
    with pytest.raises(KeyError, match="Unknown indicator"):
        validate_value("UNKNOWN", 1)


def test_recent_date_is_accepted():
    assert validate_date("2024-01-15", today=TODAY) == (True, None)


def test_malformed_date_is_rejected():
    is_valid, message = validate_date("01/15/2024", today=TODAY)
    assert is_valid is False
    assert "Invalid date format" in message


def test_nonexistent_calendar_date_is_rejected():
    is_valid, message = validate_date("2024-02-30", today=TODAY)
    assert is_valid is False
    assert "Invalid date format" in message


def test_date_before_1950_is_rejected():
    is_valid, message = validate_date("1949-12-31", today=TODAY)
    assert is_valid is False
    assert "1950" in message


def test_first_day_of_1950_is_accepted():
    assert validate_date("1950-01-01", today=TODAY) == (True, None)


def test_date_exactly_one_year_ahead_is_accepted():
    assert validate_date("2027-11-12", today=TODAY) == (True, None)


def test_date_more_than_one_year_ahead_is_rejected():
    is_valid, message = validate_date("2027-11-13", today=TODAY)
    assert is_valid is False
    assert "future" in message