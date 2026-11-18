"""pipeline logic that needs no database.

Everything that reads or writes rows (the SQL, upserts, transactions, a whole
run) is tested against a real PostgreSQL server in tests/integration/test_pipeline_db.
"""
from datetime import date

import pytest

from src.econ_data.config import Settings, get_indicator
from src.econ_data.fred_client import FredError, Observation
from src.econ_data.pipeline import (
    MAX_REJECTION_EXAMPLES,
    RunSummary,
    run_indicator,
    upsert_observations,
    validate_observations,
)

TODAY = date(2026, 11, 14)
DFF = get_indicator("DFF")
SETTINGS = Settings(fred_api_key="testkey123")


def obs(day, value):
    return Observation(date=day, value=value)


# --- validate_observations ---------------------------------------------------


def test_passing_observations_become_date_value_rows_in_order():
    result = validate_observations(
        DFF, [obs("2026-11-12", 4.33), obs("2026-11-11", 4.31)], TODAY
    )
    assert result.rows == [("2026-11-12", 4.33), ("2026-11-11", 4.31)]
    assert (result.missing, result.rejected, result.rejection_examples) == (0, 0, ())


def test_observation_without_a_value_is_counted_as_missing_not_rejected():
    result = validate_observations(DFF, [obs("2026-11-12", None), obs("2026-11-11", 4.31)], TODAY)
    assert result.rows == [("2026-11-11", 4.31)]
    assert result.missing == 1
    assert result.rejected == 0


def test_value_outside_the_range_is_rejected_with_date_and_reason():
    result = validate_observations(DFF, [obs("2026-11-12", 30.0)], TODAY)
    assert result.rows == []
    assert result.rejected == 1
    assert result.rejection_examples == (
        f"2026-11-12: Effective Federal Funds Rate (percent) value 30.0 exceeds maximum {DFF.max_value}",
    )


def test_range_holds_the_1981_peak_of_the_effective_rate():
    # FRED's DFF history reaches 22.36 on 1981-07-22; a backfill must not reject it.
    result = validate_observations(DFF, [obs("1981-07-22", 22.36)], TODAY)
    assert result.rows == [("1981-07-22", 22.36)]
    assert result.rejected == 0


def test_invalid_date_is_rejected():
    result = validate_observations(DFF, [obs("not-a-date", 4.31)], TODAY)
    assert result.rows == []
    assert result.rejected == 1
    assert "Invalid date format" in result.rejection_examples[0]


def test_date_too_far_ahead_is_rejected():
    result = validate_observations(DFF, [obs("2028-01-01", 4.31)], TODAY)
    assert result.rejected == 1
    assert "future" in result.rejection_examples[0]


def test_nan_value_is_rejected():
    result = validate_observations(DFF, [obs("2026-11-12", float("nan"))], TODAY)
    assert result.rows == []
    assert result.rejected == 1


def test_rejection_examples_are_capped_but_every_rejection_is_counted():
    bad = [obs(f"2026-11-{d:02d}", 99.0) for d in range(1, 8)]
    result = validate_observations(DFF, bad, TODAY)
    assert result.rejected == 7
    assert len(result.rejection_examples) == MAX_REJECTION_EXAMPLES


def test_no_observations_gives_empty_result():
    result = validate_observations(DFF, [], TODAY)
    assert (result.rows, result.missing, result.rejected) == ([], 0, 0)


# --- upsert_observations -----------------------------------------------------


def test_upsert_with_no_rows_makes_no_database_calls():
    assert upsert_observations(None, "DFF", []) == (0, 0)


# --- run_indicator -------------------------------------------------------------
# These cases end before any row is written, so the cursor passed in is None: if
# the code touched the database, the test would fail with an AttributeError.


class FetchRecorder:
    """A fetch function that returns scripted observations or raises a scripted error."""

    def __init__(self, result):
        self.result = result

    def __call__(self, indicator, limit, settings):
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def test_fred_error_is_returned_in_the_summary_and_the_database_is_not_touched():
    fetch = FetchRecorder(FredError("DFF: HTTP 500"))
    summary = run_indicator(None, DFF, SETTINGS, fetch=fetch, today=TODAY)

    assert not summary.ok
    assert summary.error == "DFF: HTTP 500"
    assert summary.indicator_id == "DFF"


def test_empty_fred_response_is_an_error():
    summary = run_indicator(None, DFF, SETTINGS, fetch=FetchRecorder([]), today=TODAY)

    assert not summary.ok
    assert summary.error == "DFF: FRED returned no observations"


def test_all_observations_rejected_is_not_an_error_and_writes_nothing():
    fetch = FetchRecorder([obs("2026-11-12", 99.0), obs("2026-11-11", 98.0)])
    summary = run_indicator(None, DFF, SETTINGS, fetch=fetch, today=TODAY)

    assert summary.ok
    assert (summary.fetched, summary.rejected, summary.inserted, summary.updated) == (2, 2, 0, 0)


def test_unexpected_errors_are_not_swallowed():
    fetch = FetchRecorder(RuntimeError("bug"))
    with pytest.raises(RuntimeError, match="bug"):
        run_indicator(None, DFF, SETTINGS, fetch=fetch, today=TODAY)


def test_run_summary_ok_reflects_error():
    assert RunSummary(indicator_id="DFF").ok
    assert not RunSummary(indicator_id="DFF", error="boom").ok