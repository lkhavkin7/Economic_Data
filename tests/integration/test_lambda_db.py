"""lambda_handler against a real PostgreSQL server: verify, setup and fetch."""
from datetime import date

import pytest

from src.econ_data import lambda_handler as handler
from src.econ_data.pipeline import run_pipeline

# setup_database creates databases, so these tests use throwaway names of their own.
# Like the main test database, their names end with _test.
SETUP_DB_NAME = "econ_data_setup_test"


@pytest.fixture
def setup_target(server):
    """Settings for a database that does not exist yet. It is dropped before and after the test."""
    server.drop_database(SETUP_DB_NAME)
    yield server.settings_for(SETUP_DB_NAME)
    server.drop_database(SETUP_DB_NAME)


def table_names(scratch):
    """The tables a database has in its public schema."""
    rows = scratch.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' ORDER BY 1"
    )
    return [name for (name,) in rows]


# --- verify_database -----------------------------------------------------------


def test_verify_on_an_empty_database_returns_no_rows(database):
    assert handler.verify_database(database.settings) == {"mode": "verify", "rows": []}


def test_verify_returns_the_count_and_latest_date_of_each_indicator(database):
    database.seed("DFF", {"2026-11-10": 4.31, "2026-11-11": 4.32, "2026-11-12": 4.33})
    database.seed("SP500", {"2026-11-09": 6000.5})

    result = handler.verify_database(database.settings)

    assert result == {
        "mode": "verify",
        "rows": [
            {"indicator_id": "DFF", "count": 3, "max_date": "2026-11-12"},
            {"indicator_id": "SP500", "count": 1, "max_date": "2026-11-09"},
        ],
    }


def test_verify_lists_only_indicators_that_have_observations(database):
    database.seed("DFF", {"2026-11-12": 4.33})
    database.seed("SP500")  # defined, but no observations stored

    rows = handler.verify_database(database.settings)["rows"]

    assert [row["indicator_id"] for row in rows] == ["DFF"]


# --- setup_database ------------------------------------------------------------


def test_setup_creates_a_missing_database_and_applies_the_schema(server, setup_target, open_database):
    result = handler.setup_database(setup_target)

    assert result == {"mode": "setup", "database": SETUP_DB_NAME, "created": True, "schema_applied": True}
    assert server.database_exists(SETUP_DB_NAME)
    assert table_names(open_database(setup_target)) == ["economic_indicators", "indicator_metadata"]


def test_running_setup_again_keeps_the_database_and_the_rows_in_it(setup_target, open_database):
    handler.setup_database(setup_target)
    stored = open_database(setup_target)
    stored.seed("DFF", {"2026-11-12": 4.33})

    second = handler.setup_database(setup_target)

    assert (second["created"], second["schema_applied"]) == (False, True)
    assert stored.stored("DFF") == [("2026-11-12", 4.33)]


def test_setup_on_a_database_that_already_has_the_schema_changes_nothing(database):
    database.seed("DFF", {"2026-11-12": 4.33})

    result = handler.setup_database(database.settings)

    assert result["created"] is False
    assert database.stored("DFF") == [("2026-11-12", 4.33)]


def test_a_database_name_is_quoted_so_it_cannot_run_sql(server):
    hostile = 'x"; DROP DATABASE postgres; --_test'
    server.drop_database(hostile)
    try:
        result = handler.setup_database(server.settings_for(hostile))

        assert result["created"] is True
        assert server.database_exists(hostile)    # created under exactly that name
        assert server.database_exists("postgres")  # and nothing else was dropped
    finally:
        server.drop_database(hostile)


def test_the_maintenance_connection_is_closed_when_setup_fails(database, monkeypatch):
    opened = []
    real_connect = handler.connect

    def recording_connect(settings):
        conn = real_connect(settings)
        opened.append(conn)
        return conn

    monkeypatch.setattr(handler, "connect", recording_connect)
    # PostgreSQL names cannot contain a NUL character, so the first query fails.
    impossible_name = database.settings.model_copy(update={"db_name": "bad\x00name"})

    with pytest.raises(ValueError):
        handler.setup_database(impossible_name)

    assert len(opened) == 1
    assert opened[0].closed


# --- fetch_all -----------------------------------------------------------------


@pytest.fixture
def fred_in_handler(monkeypatch, fred):
    """Make the handler's pipeline run read from FakeFred instead of FRED."""
    monkeypatch.setattr(handler, "run_pipeline", lambda settings: run_pipeline(settings, fetch=fred))
    return fred


def test_fetch_stores_the_observations_and_returns_the_summaries(database, fred_in_handler):
    fred_in_handler.publish_every_indicator()

    result = handler.fetch_all(database.settings)

    assert result["mode"] == "fetch"
    assert all(summary["inserted"] == 1 for summary in result["summaries"])
    assert database.count("economic_indicators") == len(result["summaries"])


def test_fetch_with_a_failed_indicator_raises_but_keeps_what_the_others_stored(database, fred_in_handler):
    fred_in_handler.publish_every_indicator()
    fred_in_handler.fail("SP500", "HTTP 503")

    with pytest.raises(handler.PipelineError, match="1 of 6 indicators failed.*SP500: HTTP 503"):
        handler.fetch_all(database.settings)

    assert database.stored("SP500") == []
    assert database.stored("DFF")


# --- lambda_handler ------------------------------------------------------------


def test_the_handler_reads_its_database_from_the_environment(database):
    database.seed("DFF", {"2026-11-12": 4.33})
    assert handler.lambda_handler({"mode": "verify"}, None)["rows"][0]["indicator_id"] == "DFF"


def test_the_handler_runs_setup_and_fetch_end_to_end(database, fred_in_handler):
    fred_in_handler.publish_every_indicator(date(2026, 11, 12).isoformat())

    assert handler.lambda_handler({"mode": "setup"}, None)["created"] is False
    assert handler.lambda_handler({}, None)["mode"] == "fetch"
    assert handler.lambda_handler({"mode": "verify"}, None)["rows"][0]["count"] == 1
