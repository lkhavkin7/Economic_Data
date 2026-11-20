"""lambda_handler logic that needs no database: choosing a mode, reporting failed
indicators, and the schema file.

verify, setup and a whole fetch run are tested against a real PostgreSQL server in
tests/integration/test_lambda_db.
"""
from pathlib import Path

import pytest

from src.econ_data import lambda_handler as handler
from src.econ_data.config import Settings
from src.econ_data.pipeline import RunSummary

SETTINGS = Settings(db_name="econ_data")


@pytest.fixture
def no_database(monkeypatch):
    """Fail the test if anything tries to open a database connection."""

    def fail(*args, **kwargs):
        raise AssertionError("the database should not be used")

    monkeypatch.setattr(handler, "connect", fail)
    monkeypatch.setattr(handler, "connection", fail)


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


# --- setup_database ----------------------------------------------------------


def test_missing_schema_file_fails_before_any_database_work(no_database, tmp_path):
    with pytest.raises(FileNotFoundError):
        handler.setup_database(SETTINGS, tmp_path / "nope.sql")


def test_default_schema_path_points_at_the_schema_in_the_repo():
    assert handler.SCHEMA_PATH.name == "schema.sql"
    assert handler.SCHEMA_PATH.is_file()


def test_schema_sql_has_no_destructive_drop():
    # setup runs on every deploy, so the schema file must never delete data.
    schema = Path(__file__).resolve().parents[1] / "db" / "schema.sql"
    assert "DROP TABLE" not in schema.read_text().upper()
