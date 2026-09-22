from datetime import datetime, timedelta

import pytest

from src.validate_data import validate_value, validate_date


@pytest.mark.parametrize(
    "indicator_id,value",
    [
        ("GDP", 25000),
        ("FEDFUNDS", 5.25),
        ("UMCSENT", 70),
    ],
)
def test_validate_value_in_range(indicator_id, value):
    assert validate_value(indicator_id, value) == (True, None)


INDICATOR_NAMES = {
    "GDP": "GDP (billions USD)",
    "FEDFUNDS": "Federal Funds Rate (%)",
    "UMCSENT": "Consumer Sentiment Index",
}


@pytest.mark.parametrize(
    "indicator_id,value",
    [
        ("GDP", 999),
        ("FEDFUNDS", -1),
        ("UMCSENT", -1),
    ],
)
def test_validate_value_below_minimum(indicator_id, value):
    is_valid, message = validate_value(indicator_id, value)
    assert is_valid is False
    assert INDICATOR_NAMES[indicator_id] in message


@pytest.mark.parametrize(
    "indicator_id,value",
    [
        ("GDP", 100001),
        ("FEDFUNDS", 21),
        ("UMCSENT", 151),
    ],
)
def test_validate_value_above_maximum(indicator_id, value):
    is_valid, message = validate_value(indicator_id, value)
    assert is_valid is False
    assert INDICATOR_NAMES[indicator_id] in message


def test_validate_value_unknown_indicator_accepts_anything():
    assert validate_value("UNKNOWN", -999999) == (True, None)


def test_validate_date_valid_recent_date():
    assert validate_date("2024-01-15") == (True, None)


def test_validate_date_malformed_string():
    is_valid, message = validate_date("01/15/2024")
    assert is_valid is False
    assert "Invalid date format" in message


def test_validate_date_before_1950():
    is_valid, message = validate_date("1949-12-31")
    assert is_valid is False
    assert "1950" in message


def test_validate_date_too_far_in_future():
    future_date = (datetime.now() + timedelta(days=400)).strftime("%Y-%m-%d")
    is_valid, message = validate_date(future_date)
    assert is_valid is False
    assert "future" in message
