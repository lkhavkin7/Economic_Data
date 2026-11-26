"""pipeline against a real PostgreSQL server.

FRED is replaced by FakeFred (see conftest); everything from there on, the SQL,
the constraints and the transactions, is the real thing.
"""
from datetime import date, datetime, timedelta
from decimal import Decimal

import psycopg2
import pytest

from src.econ_data.config import INDICATORS, get_indicator
from src.econ_data.pipeline import (
    UPSERT_PAGE_SIZE,
    run_indicator,
    run_pipeline,
    sync_metadata,
    upsert_observations,
)

TODAY = date(2026, 11, 14)
DFF = get_indicator("DFF")
LONG_AGO = datetime(2020, 1, 1)


# --- sync_metadata -------------------------------------------------------------


def test_sync_metadata_writes_every_indicator_in_config(database):
    with database.cursor() as cur:
        sync_metadata(cur)

    stored = database.execute(
        "SELECT indicator_id, name, description, frequency, units, source"
        " FROM indicator_metadata ORDER BY indicator_id"
    )
    expected = sorted(
        (i.indicator_id, i.name, i.description, i.frequency, i.units, i.source) for i in INDICATORS
    )
    assert stored == expected


def test_sync_metadata_overwrites_an_old_definition_and_keeps_the_observations(database):
    database.execute(
        "INSERT INTO indicator_metadata (indicator_id, name, frequency) VALUES ('DFF', 'old name', 'monthly')"
    )
    database.execute(
        "INSERT INTO economic_indicators (indicator_id, date, value) VALUES ('DFF', '2026-11-12', 4.33)"
    )

    with database.cursor() as cur:
        sync_metadata(cur, [DFF])

    assert database.execute("SELECT name, frequency FROM indicator_metadata") == [(DFF.name, "daily")]
    assert database.stored("DFF") == [("2026-11-12", 4.33)]


def test_sync_metadata_leaves_indicators_that_are_not_in_config_alone(database):
    database.seed("RETIRED")

    with database.cursor() as cur:
        sync_metadata(cur, [DFF])

    assert database.execute("SELECT indicator_id FROM indicator_metadata ORDER BY 1") == [("DFF",), ("RETIRED",)]


def test_sync_metadata_twice_leaves_one_row_per_indicator(database):
    for _ in range(2):
        with database.cursor() as cur:
            sync_metadata(cur)
    assert database.count("indicator_metadata") == len(INDICATORS)


# --- upsert_observations -------------------------------------------------------


def upsert(database, indicator_id, rows):
    with database.cursor() as cur:
        return upsert_observations(cur, indicator_id, rows)


def test_new_observations_are_inserted(database):
    database.seed("DFF")

    result = upsert(database, "DFF", [("2026-11-10", 4.31), ("2026-11-11", 4.32), ("2026-11-12", 4.33)])

    assert result == (3, 0)
    assert database.stored("DFF") == [("2026-11-10", 4.31), ("2026-11-11", 4.32), ("2026-11-12", 4.33)]


def test_an_observation_with_the_same_value_is_left_untouched(database):
    database.seed("DFF", {"2026-11-12": 4.33}, fetched_at=LONG_AGO)

    result = upsert(database, "DFF", [("2026-11-12", 4.33)])

    assert result == (0, 0)
    assert list(database.fetched_at("DFF").values()) == [LONG_AGO]


def test_a_revised_value_replaces_the_old_one_and_renews_fetched_at(database):
    database.seed("DFF", {"2026-11-12": 4.33}, fetched_at=LONG_AGO)

    result = upsert(database, "DFF", [("2026-11-12", 4.35)])

    assert result == (0, 1)
    assert database.stored("DFF") == [("2026-11-12", 4.35)]
    assert database.fetched_at("DFF")["2026-11-12"] > LONG_AGO


def test_a_batch_can_mix_new_revised_and_unchanged_rows(database):
    database.seed("DFF", {"2026-11-10": 4.31, "2026-11-11": 4.32}, fetched_at=LONG_AGO)

    result = upsert(database, "DFF", [("2026-11-10", 4.31), ("2026-11-11", 4.99), ("2026-11-12", 4.33)])

    assert result == (1, 1)
    assert database.stored("DFF") == [("2026-11-10", 4.31), ("2026-11-11", 4.99), ("2026-11-12", 4.33)]
    stamps = database.fetched_at("DFF")
    assert stamps["2026-11-10"] == LONG_AGO  # unchanged: not touched
    assert stamps["2026-11-11"] > LONG_AGO   # revised: renewed


def test_the_column_keeps_four_decimal_places(database):
    database.seed("DFF")
    upsert(database, "DFF", [("2026-11-12", 4.33)])
    assert database.execute("SELECT value FROM economic_indicators") == [(Decimal("4.3300"),)]


def test_a_value_with_more_than_four_decimals_is_rounded_and_a_rerun_sees_no_change(database):
    database.seed("DFF")

    assert upsert(database, "DFF", [("2026-11-12", 4.33333)]) == (1, 0)
    assert database.execute("SELECT value FROM economic_indicators") == [(Decimal("4.3333"),)]
    assert upsert(database, "DFF", [("2026-11-12", 4.33333)]) == (0, 0)


def test_an_indicator_with_no_metadata_row_is_refused_by_the_foreign_key(database):
    with pytest.raises(psycopg2.errors.ForeignKeyViolation):
        upsert(database, "DFF", [("2026-11-12", 4.33)])
    assert database.count("economic_indicators") == 0


def test_a_batch_larger_than_the_page_size_is_written_and_counted_in_full(database):
    database.seed("DFF")
    count = UPSERT_PAGE_SIZE * 2 + 500
    start = date(2000, 1, 1)
    rows = [((start + timedelta(days=n)).isoformat(), 4.0 + (n % 100) / 100) for n in range(count)]

    assert upsert(database, "DFF", rows) == (count, 0)
    assert database.count("economic_indicators") == count
    assert upsert(database, "DFF", rows) == (0, 0)

    revised = [(day, value + 1) for day, value in rows]
    assert upsert(database, "DFF", revised) == (0, count)


# --- run_indicator -------------------------------------------------------------


def run_one(database, fred, **options):
    database.seed("DFF")  # run_indicator expects the indicator's metadata row to exist already
    with database.cursor() as cur:
        return run_indicator(cur, DFF, database.settings, fetch=fred, today=TODAY, **options)


def test_an_incremental_run_asks_for_the_lookback_from_config(database, fred):
    fred.publish("DFF", {"2026-11-12": 4.33})
    run_one(database, fred)
    assert fred.calls == [("DFF", DFF.lookback)]


def test_a_backfill_asks_for_the_full_history(database, fred):
    fred.publish("DFF", {"2026-11-12": 4.33})
    run_one(database, fred, backfill=True)
    assert fred.calls == [("DFF", None)]


def test_every_observation_is_counted_once_and_only_the_valid_ones_are_stored(database, fred):
    database.seed("DFF", {"2026-11-10": 4.30, "2026-11-11": 4.00})
    fred.publish(
        "DFF",
        {
            "2026-11-12": 4.33,   # new
            "2026-11-11": 4.31,   # revised from 4.00
            "2026-11-10": 4.30,   # unchanged
            "2026-11-09": None,   # FRED has no value
            "2026-11-08": 99.0,   # outside the valid range
        },
    )

    summary = run_one(database, fred)

    assert summary.ok
    assert (summary.fetched, summary.missing, summary.rejected) == (5, 1, 1)
    assert (summary.inserted, summary.updated, summary.unchanged) == (1, 1, 1)
    assert summary.fetched == (
        summary.missing + summary.rejected + summary.inserted + summary.updated + summary.unchanged
    )
    assert database.stored("DFF") == [("2026-11-10", 4.30), ("2026-11-11", 4.31), ("2026-11-12", 4.33)]


def test_a_fred_failure_writes_nothing(database, fred):
    fred.fail("DFF")
    summary = run_one(database, fred)

    assert not summary.ok
    assert database.count("economic_indicators") == 0


# --- run_pipeline --------------------------------------------------------------


def test_a_run_writes_the_metadata_and_the_observations_of_every_indicator(database, fred):
    fred.publish_every_indicator()

    summaries = run_pipeline(database.settings, fetch=fred, today=TODAY)

    assert [s.indicator_id for s in summaries] == [i.indicator_id for i in INDICATORS]
    assert all(s.ok and s.inserted == 1 for s in summaries)
    assert database.count("indicator_metadata") == len(INDICATORS)
    assert database.count("economic_indicators") == len(INDICATORS)


def test_running_twice_changes_nothing(database, fred):
    fred.publish_every_indicator()
    run_pipeline(database.settings, fetch=fred, today=TODAY)
    snapshot = database.execute("SELECT * FROM economic_indicators ORDER BY id")

    second = run_pipeline(database.settings, fetch=fred, today=TODAY)

    assert all((s.inserted, s.updated, s.unchanged) == (0, 0, 1) for s in second)
    assert database.execute("SELECT * FROM economic_indicators ORDER BY id") == snapshot  # fetched_at included


def test_a_revision_from_fred_overwrites_the_stored_value(database, fred):
    fred.publish_every_indicator("2026-11-12")
    fred.publish("DFF", {"2026-11-12": 4.33})
    run_pipeline(database.settings, fetch=fred, today=TODAY)
    first_fetch = database.fetched_at("DFF")["2026-11-12"]

    fred.publish("DFF", {"2026-11-12": 4.35})  # FRED corrects yesterday's number
    second = run_pipeline(database.settings, fetch=fred, today=TODAY)

    dff = next(s for s in second if s.indicator_id == "DFF")
    assert (dff.inserted, dff.updated, dff.unchanged) == (0, 1, 0)
    assert database.stored("DFF") == [("2026-11-12", 4.35)]
    assert database.fetched_at("DFF")["2026-11-12"] > first_fetch


def test_one_indicator_failing_does_not_stop_the_others_and_their_rows_are_kept(database, fred):
    fred.publish_every_indicator()
    fred.fail("DFEDTARU")

    summaries = run_pipeline(database.settings, fetch=fred, today=TODAY)

    failed = [s.indicator_id for s in summaries if not s.ok]
    assert failed == ["DFEDTARU"]
    assert database.stored("DFEDTARU") == []
    assert all(database.stored(i.indicator_id) for i in INDICATORS if i.indicator_id != "DFEDTARU")


def test_only_the_indicators_it_is_given_are_run(database, fred):
    fred.publish_every_indicator()

    run_pipeline(database.settings, indicators=[DFF], fetch=fred, today=TODAY)

    assert database.execute("SELECT indicator_id FROM indicator_metadata") == [("DFF",)]
    assert [call[0] for call in fred.calls] == ["DFF"]


def test_a_backfill_fills_in_the_history_around_what_an_incremental_run_stored(database, fred):
    history = {f"2026-10-{day:02d}": 4.0 + day / 100 for day in range(1, 31)}
    fred.publish("DFF", history)

    incremental = run_pipeline(database.settings, indicators=[DFF], fetch=fred, today=TODAY)
    assert incremental[0].inserted == DFF.lookback
    assert database.count("economic_indicators") == DFF.lookback

    backfill = run_pipeline(database.settings, indicators=[DFF], fetch=fred, today=TODAY, backfill=True)

    assert (backfill[0].inserted, backfill[0].unchanged) == (30 - DFF.lookback, DFF.lookback)
    assert database.stored("DFF") == sorted(history.items())


# A rule added to the test database only. It lets the test make the database
# refuse a value that the pipeline's own validation accepts.
@pytest.fixture
def database_refuses_values_of_5_or_more(database):
    database.execute("ALTER TABLE economic_indicators ADD CONSTRAINT below_5 CHECK (value < 5)")
    yield
    database.execute("ALTER TABLE economic_indicators DROP CONSTRAINT below_5")


def test_a_database_error_rolls_back_the_whole_run(database, fred, database_refuses_values_of_5_or_more):
    fred.publish("DFF", {"2026-11-12": 4.33})        # passes validation and the database
    fred.publish("DFEDTARU", {"2026-11-12": 10.0})   # passes validation, refused by the database

    with pytest.raises(psycopg2.errors.CheckViolation):
        run_pipeline(database.settings, indicators=[DFF, get_indicator("DFEDTARU")], fetch=fred, today=TODAY)

    # DFF was processed before the failure, but nothing from the run was kept,
    # not its rows and not the metadata written at the start.
    assert database.count("economic_indicators") == 0
    assert database.count("indicator_metadata") == 0
