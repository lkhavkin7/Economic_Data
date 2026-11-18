import contextlib
from contextlib import contextmanager
from datetime import date

import pytest

from src.econ_data import pipeline
from src.econ_data.config import INDICATORS, Settings, get_indicator
from src.econ_data.fred_client import FredError, Observation
from src.econ_data.pipeline import (
    MAX_REJECTION_EXAMPLES,
    RunSummary,
    run_indicator,
    run_pipeline,
    sync_metadata,
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


# --- sync_metadata -----------------------------------------------------------


class RecordingCursor:
    def __init__(self):
        self.executemany_calls = []

    def executemany(self, sql, params):
        self.executemany_calls.append((sql, params))


def test_sync_metadata_sends_the_six_metadata_fields_for_every_indicator():
    cur = RecordingCursor()
    sync_metadata(cur)

    (sql, params), = cur.executemany_calls
    assert "ON CONFLICT (indicator_id) DO UPDATE" in sql
    assert len(params) == len(INDICATORS)
    assert params[0] == (
        "DFF",
        "Effective Federal Funds Rate",
        "Rate banks actually paid each other for overnight loans, published daily",
        "daily",
        "percent",
        "FRED",
    )


def test_sync_metadata_only_sends_the_indicators_it_is_given():
    cur = RecordingCursor()
    sync_metadata(cur, [DFF])
    assert [p[0] for p in cur.executemany_calls[0][1]] == ["DFF"]


# --- upsert_observations -----------------------------------------------------


def test_upsert_with_no_rows_makes_no_database_calls():
    assert upsert_observations(None, "DFF", []) == (0, 0)


# --- run_indicator -----------------------------------------------------------


class FetchRecorder:
    """A fetch function that returns scripted observations and records its arguments."""

    def __init__(self, result):
        self.result = result
        self.calls = []

    def __call__(self, indicator, limit, settings):
        self.calls.append((indicator, limit, settings))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


@pytest.fixture
def recorded_upserts(monkeypatch):
    """Replace upsert_observations with a function that records calls and returns (2, 1)."""
    calls = []

    def fake_upsert(cur, indicator_id, rows):
        calls.append((indicator_id, list(rows)))
        return 2, 1

    monkeypatch.setattr(pipeline, "upsert_observations", fake_upsert)
    return calls


def test_run_indicator_requests_the_lookback_from_config(recorded_upserts):
    fetch = FetchRecorder([obs("2026-11-12", 4.33)])
    run_indicator(None, DFF, SETTINGS, fetch=fetch, today=TODAY)
    assert fetch.calls == [(DFF, DFF.lookback, SETTINGS)]


def test_run_indicator_backfill_requests_the_full_history(recorded_upserts):
    fetch = FetchRecorder([obs("2026-11-12", 4.33)])
    run_indicator(None, DFF, SETTINGS, fetch=fetch, today=TODAY, backfill=True)
    assert fetch.calls == [(DFF, None, SETTINGS)]


def test_run_indicator_counts_each_kind_of_observation(recorded_upserts):
    fetch = FetchRecorder(
        [
            obs("2026-11-12", 4.33),
            obs("2026-11-11", 4.31),
            obs("2026-11-10", 4.30),
            obs("2026-11-09", None),
            obs("2026-11-08", 99.0),
        ]
    )
    summary = run_indicator(None, DFF, SETTINGS, fetch=fetch, today=TODAY)

    assert recorded_upserts == [
        ("DFF", [("2026-11-12", 4.33), ("2026-11-11", 4.31), ("2026-11-10", 4.30)])
    ]
    assert summary.ok
    assert (summary.fetched, summary.missing, summary.rejected) == (5, 1, 1)
    assert (summary.inserted, summary.updated, summary.unchanged) == (2, 1, 0)
    assert summary.fetched == (
        summary.missing + summary.rejected + summary.inserted + summary.updated + summary.unchanged
    )


def test_run_indicator_unchanged_is_what_the_database_left_alone(recorded_upserts):
    fetch = FetchRecorder([obs(f"2026-11-{d:02d}", 4.0 + d / 100) for d in range(1, 7)])
    summary = run_indicator(None, DFF, SETTINGS, fetch=fetch, today=TODAY)
    assert (summary.inserted, summary.updated, summary.unchanged) == (2, 1, 3)


def test_fred_error_is_returned_in_the_summary_and_nothing_is_written(recorded_upserts):
    fetch = FetchRecorder(FredError("DFF: HTTP 500"))
    summary = run_indicator(None, DFF, SETTINGS, fetch=fetch, today=TODAY)

    assert not summary.ok
    assert summary.error == "DFF: HTTP 500"
    assert summary.indicator_id == "DFF"
    assert recorded_upserts == []


def test_empty_fred_response_is_an_error(recorded_upserts):
    summary = run_indicator(None, DFF, SETTINGS, fetch=FetchRecorder([]), today=TODAY)

    assert not summary.ok
    assert summary.error == "DFF: FRED returned no observations"
    assert recorded_upserts == []


def test_all_observations_rejected_is_not_an_error_and_writes_nothing():
    fetch = FetchRecorder([obs("2026-11-12", 99.0), obs("2026-11-11", 98.0)])
    summary = run_indicator(None, DFF, SETTINGS, fetch=fetch, today=TODAY)

    assert summary.ok
    assert (summary.fetched, summary.rejected, summary.inserted, summary.updated) == (2, 2, 0, 0)


def test_unexpected_errors_are_not_swallowed(recorded_upserts):
    fetch = FetchRecorder(RuntimeError("bug"))
    with pytest.raises(RuntimeError, match="bug"):
        run_indicator(None, DFF, SETTINGS, fetch=fetch, today=TODAY)


# --- run_pipeline ------------------------------------------------------------


class FakeConnection:
    def cursor(self):
        return contextlib.nullcontext(object())


@pytest.fixture
def events(monkeypatch):
    """Replace the database pieces with fakes that record what happened, in order."""
    log = []

    @contextmanager
    def fake_connection(settings):
        log.append("open")
        try:
            yield FakeConnection()
            log.append("commit")
        except Exception:
            log.append("rollback")
            raise

    def fake_sync(cur, indicators):
        log.append(f"sync:{len(indicators)}")

    def fake_upsert(cur, indicator_id, rows):
        log.append(f"upsert:{indicator_id}")
        return len(rows), 0

    monkeypatch.setattr(pipeline, "connection", fake_connection)
    monkeypatch.setattr(pipeline, "sync_metadata", fake_sync)
    monkeypatch.setattr(pipeline, "upsert_observations", fake_upsert)
    return log


def midpoint_fetch(fail=()):
    def fetch(indicator, limit, settings):
        if indicator.indicator_id in fail:
            raise FredError(f"{indicator.series_id}: HTTP 500")
        middle = (indicator.min_value + indicator.max_value) / 2
        return [obs("2026-11-12", middle)]

    return fetch


def test_run_pipeline_syncs_metadata_first_then_runs_every_indicator_in_one_transaction(events):
    summaries = run_pipeline(SETTINGS, fetch=midpoint_fetch(), today=TODAY)

    assert [s.indicator_id for s in summaries] == [i.indicator_id for i in INDICATORS]
    assert all(s.ok for s in summaries)
    assert events == (
        ["open", f"sync:{len(INDICATORS)}"]
        + [f"upsert:{i.indicator_id}" for i in INDICATORS]
        + ["commit"]
    )


def test_run_pipeline_continues_after_a_fred_failure_and_still_commits(events):
    summaries = run_pipeline(SETTINGS, fetch=midpoint_fetch(fail=("DFEDTARU",)), today=TODAY)

    failed = [s for s in summaries if not s.ok]
    assert [s.indicator_id for s in failed] == ["DFEDTARU"]
    assert "upsert:DFEDTARU" not in events
    assert len([e for e in events if e.startswith("upsert:")]) == len(INDICATORS) - 1
    assert events[-1] == "commit"


def test_run_pipeline_passes_backfill_to_every_indicator(events):
    limits = []

    def fetch(indicator, limit, settings):
        limits.append(limit)
        return midpoint_fetch()(indicator, limit, settings)

    run_pipeline(SETTINGS, fetch=fetch, today=TODAY, backfill=True)
    assert limits == [None] * len(INDICATORS)

    limits.clear()
    run_pipeline(SETTINGS, fetch=fetch, today=TODAY)
    assert limits == [i.lookback for i in INDICATORS]


def test_run_pipeline_only_runs_the_indicators_it_is_given(events):
    summaries = run_pipeline(SETTINGS, indicators=[DFF], fetch=midpoint_fetch(), today=TODAY)

    assert [s.indicator_id for s in summaries] == ["DFF"]
    assert events == ["open", "sync:1", "upsert:DFF", "commit"]


def test_run_pipeline_rolls_back_and_reraises_on_a_database_error(events, monkeypatch):
    def failing_upsert(cur, indicator_id, rows):
        events.append(f"upsert:{indicator_id}")
        if indicator_id == "DFEDTARU":
            raise RuntimeError("database failure")
        return len(rows), 0

    monkeypatch.setattr(pipeline, "upsert_observations", failing_upsert)

    with pytest.raises(RuntimeError, match="database failure"):
        run_pipeline(SETTINGS, fetch=midpoint_fetch(), today=TODAY)

    assert events[-1] == "rollback"
    assert "commit" not in events
    assert "upsert:DFEDTARL" not in events


def test_run_summary_ok_reflects_error():
    assert RunSummary(indicator_id="DFF").ok
    assert not RunSummary(indicator_id="DFF", error="boom").ok