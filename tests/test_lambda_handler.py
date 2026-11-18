from contextlib import contextmanager
from datetime import date
from pathlib import Path

import pytest

from src.econ_data import lambda_handler as handler
from src.econ_data.config import Settings
from src.econ_data.pipeline import RunSummary

SETTINGS = Settings(db_name="econ_data")


class FakeCursor:
    def __init__(self, fetchone_result=None, fetchall_result=None):
        self.executed = []
        self._fetchone_result = fetchone_result
        self._fetchall_result = fetchall_result or []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, query, params=None):
        self.executed.append((query, params))

    def fetchone(self):
        return self._fetchone_result

    def fetchall(self):
        return self._fetchall_result


class FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor
        self.autocommit = False
        self.closed = False

    def cursor(self):
        return self._cursor

    def close(self):
        self.closed = True


@pytest.fixture
def schema_file(tmp_path):
    path = tmp_path / "schema.sql"
    path.write_text("CREATE TABLE IF NOT EXISTS t (id INT);", encoding="utf-8")
    return path


@pytest.fixture
def database(monkeypatch):
    """Replace connect() and connection() with fakes. Returns what they were given.

    Set `database["exists"]` to choose whether the maintenance query finds the database.
    """
    state = {"exists": True, "connect_settings": [], "maintenance": None, "target_cursor": FakeCursor()}

    def fake_connect(settings):
        state["connect_settings"].append(settings)
        state["maintenance"] = FakeConnection(FakeCursor(fetchone_result=(1,) if state["exists"] else None))
        return state["maintenance"]

    @contextmanager
    def fake_connection(settings):
        yield FakeConnection(state["target_cursor"])

    monkeypatch.setattr(handler, "connect", fake_connect)
    monkeypatch.setattr(handler, "connection", fake_connection)
    return state


# --- lambda_handler: choosing a mode -----------------------------------------


@pytest.mark.parametrize(
    "event, expected",
    [(None, "fetch"), ({}, "fetch"), ({"mode": "fetch"}, "fetch"),
     ({"mode": "verify"}, "verify"), ({"mode": "setup"}, "setup")],
)
def test_event_selects_the_mode_and_fetch_is_the_default(monkeypatch, event, expected):
    called = []
    for name in ("fetch_all", "verify_database", "setup_database"):
        monkeypatch.setattr(handler, name, lambda settings, n=name: called.append(n) or {"mode": n})

    handler.lambda_handler(event, None)

    assert called == [{"fetch": "fetch_all", "verify": "verify_database", "setup": "setup_database"}[expected]]


def test_unknown_mode_is_an_error_not_a_silent_fetch():
    with pytest.raises(ValueError, match="Unknown mode 'verfy'.*fetch, verify, setup"):
        handler.lambda_handler({"mode": "verfy"}, None)


def test_mode_functions_receive_settings_read_from_the_environment(monkeypatch):
    monkeypatch.setenv("DB_NAME", "from_env")
    received = []
    monkeypatch.setattr(handler, "verify_database", lambda settings: received.append(settings) or {})

    handler.lambda_handler({"mode": "verify"}, None)

    assert received[0].db_name == "from_env"


# --- fetch_all ---------------------------------------------------------------


def test_fetch_returns_every_summary_as_plain_data(monkeypatch):
    summaries = [
        RunSummary(indicator_id="DFF", fetched=10, inserted=2, unchanged=8),
        RunSummary(indicator_id="SP500", fetched=10, rejected=1, rejection_examples=("2026-11-12: bad",)),
    ]
    monkeypatch.setattr(handler, "run_pipeline", lambda settings: summaries)

    result = handler.fetch_all(SETTINGS)

    assert result["mode"] == "fetch"
    assert [s["indicator_id"] for s in result["summaries"]] == ["DFF", "SP500"]
    assert result["summaries"][0]["inserted"] == 2
    assert result["summaries"][1]["rejection_examples"] == ("2026-11-12: bad",)


def test_fetch_passes_the_settings_to_the_pipeline(monkeypatch):
    received = []
    monkeypatch.setattr(handler, "run_pipeline", lambda settings: received.append(settings) or [])
    handler.fetch_all(SETTINGS)
    assert received == [SETTINGS]


def test_fetch_raises_naming_every_failed_indicator(monkeypatch):
    summaries = [
        RunSummary(indicator_id="DFF", fetched=10),
        RunSummary(indicator_id="SP500", error="SP500: HTTP 500"),
        RunSummary(indicator_id="VIXCLS", error="VIXCLS: FRED returned no observations"),
    ]
    monkeypatch.setattr(handler, "run_pipeline", lambda settings: summaries)

    with pytest.raises(handler.PipelineError) as exc:
        handler.fetch_all(SETTINGS)

    message = str(exc.value)
    assert message.startswith("2 of 3 indicators failed")
    assert "SP500: HTTP 500" in message
    assert "VIXCLS: FRED returned no observations" in message
    assert "SP500: SP500" not in message
    assert "DFF:" not in message


def test_database_errors_from_the_pipeline_are_not_swallowed(monkeypatch):
    def failing(settings):
        raise RuntimeError("database down")

    monkeypatch.setattr(handler, "run_pipeline", failing)
    with pytest.raises(RuntimeError, match="database down"):
        handler.fetch_all(SETTINGS)


# --- verify_database ---------------------------------------------------------


def test_verify_returns_count_and_latest_date_per_indicator(database):
    database["target_cursor"] = FakeCursor(
        fetchall_result=[("DFF", 120, date(2026, 11, 12)), ("SP500", 0, None)]
    )

    result = handler.verify_database(SETTINGS)

    assert result == {
        "mode": "verify",
        "rows": [
            {"indicator_id": "DFF", "count": 120, "max_date": "2026-11-12"},
            {"indicator_id": "SP500", "count": 0, "max_date": None},
        ],
    }
    assert database["target_cursor"].executed == [(handler.VERIFY_SQL, None)]


def test_verify_on_an_empty_database_returns_no_rows(database):
    assert handler.verify_database(SETTINGS)["rows"] == []


# --- setup_database ----------------------------------------------------------


def test_setup_creates_the_database_when_it_is_missing(database, schema_file):
    database["exists"] = False

    result = handler.setup_database(SETTINGS, schema_file)

    assert result == {"mode": "setup", "database": "econ_data", "created": True, "schema_applied": True}
    maintenance_cursor = database["maintenance"]._cursor
    assert len(maintenance_cursor.executed) == 2
    create_query = maintenance_cursor.executed[1][0]
    assert create_query.seq[0].string == "CREATE DATABASE "
    assert create_query.seq[1].strings == ("econ_data",)


def test_setup_skips_creation_when_the_database_exists(database, schema_file):
    database["exists"] = True

    result = handler.setup_database(SETTINGS, schema_file)

    assert result["created"] is False
    assert result["schema_applied"] is True
    queries = [str(q) for q, _ in database["maintenance"]._cursor.executed]
    assert not any("CREATE DATABASE" in q for q in queries)


def test_setup_checks_for_the_database_with_a_parameter(database, schema_file):
    handler.setup_database(SETTINGS, schema_file)
    query, params = database["maintenance"]._cursor.executed[0]
    assert "datname = %s" in query
    assert params == ("econ_data",)


def test_setup_connects_to_the_maintenance_database_with_the_same_server(database, schema_file):
    settings = Settings(db_host="db.example.com", db_name="econ_data")

    handler.setup_database(settings, schema_file)

    (used,) = database["connect_settings"]
    assert used.db_name == handler.MAINTENANCE_DB
    assert used.db_host == "db.example.com"
    assert settings.db_name == "econ_data"  # the original settings are not changed


def test_setup_uses_autocommit_and_closes_the_maintenance_connection(database, schema_file):
    database["exists"] = False
    handler.setup_database(SETTINGS, schema_file)
    assert database["maintenance"].autocommit is True
    assert database["maintenance"].closed is True


def test_setup_closes_the_maintenance_connection_when_create_fails(
    database, schema_file, monkeypatch
):
    database["exists"] = False
    fake_connect = handler.connect

    def connect_with_failing_create(settings):
        conn = fake_connect(settings)
        real_execute = conn._cursor.execute

        def execute(query, params=None):
            if "CREATE" in str(query):
                raise RuntimeError("permission denied")
            real_execute(query, params)

        conn._cursor.execute = execute
        return conn

    monkeypatch.setattr(handler, "connect", connect_with_failing_create)

    with pytest.raises(RuntimeError, match="permission denied"):
        handler.setup_database(SETTINGS, schema_file)
    assert database["maintenance"].closed is True


def test_setup_applies_the_schema_file_to_the_target_database(database, schema_file):
    handler.setup_database(SETTINGS, schema_file)
    assert database["target_cursor"].executed == [("CREATE TABLE IF NOT EXISTS t (id INT);", None)]


def test_database_name_is_quoted_as_an_identifier_not_pasted_into_the_sql(database, schema_file):
    database["exists"] = False
    hostile = 'x"; DROP DATABASE postgres; --'

    handler.setup_database(Settings(db_name=hostile), schema_file)

    create_query = database["maintenance"]._cursor.executed[1][0]
    assert create_query.seq[1].strings == (hostile,)


def test_missing_schema_file_fails_before_any_database_work(database, tmp_path):
    with pytest.raises(FileNotFoundError):
        handler.setup_database(SETTINGS, tmp_path / "nope.sql")
    assert database["connect_settings"] == []


def test_default_schema_path_points_at_the_schema_in_the_repo():
    assert handler.SCHEMA_PATH.name == "schema.sql"
    assert handler.SCHEMA_PATH.is_file()


def test_schema_sql_has_no_destructive_drop():
    # setup runs on every deploy, so the schema file must never delete data.
    schema = Path(__file__).resolve().parents[1] / "db" / "schema.sql"
    assert "DROP TABLE" not in schema.read_text().upper()