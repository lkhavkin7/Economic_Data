"""cli against a real PostgreSQL server, including `python -m src.econ_data` run as a separate process."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

from src.econ_data import cli
from src.econ_data.pipeline import run_pipeline

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def run_with_fred(fred):
    """A `run` function for cli.main that reads from FakeFred instead of FRED.

    The database is not faked: run_pipeline reads its settings from the
    environment, which the `database` fixture points at the test database.
    """

    def run(indicators, backfill):
        return run_pipeline(indicators=indicators, fetch=fred, backfill=backfill)

    return run


def test_a_successful_run_stores_the_rows_prints_the_table_and_exits_0(database, fred, run_with_fred, capsys):
    fred.publish("DFF", {"2026-11-11": 4.32, "2026-11-12": 4.33})

    code = cli.main(["--indicator", "DFF"], run_with_fred)

    assert code == cli.EXIT_OK
    assert database.stored("DFF") == [("2026-11-11", 4.32), ("2026-11-12", 4.33)]
    lines = capsys.readouterr().out.splitlines()
    assert lines[1].split() == ["DFF", "2", "2", "0", "0", "0", "0", "ok"]
    assert lines[-1] == "1 indicator: 1 ok, 0 failed"


def test_a_failed_indicator_exits_1_but_the_other_indicators_are_stored(database, fred, run_with_fred, capsys):
    fred.publish("DFF", {"2026-11-12": 4.33})
    fred.fail("SP500", "HTTP 500")

    code = cli.main(["--indicator", "DFF", "SP500"], run_with_fred)

    assert code == cli.EXIT_INDICATOR_FAILED
    assert database.stored("DFF") == [("2026-11-12", 4.33)]
    assert "SP500: HTTP 500" in capsys.readouterr().out


def test_backfill_stores_the_full_history(database, fred, run_with_fred):
    fred.publish("DFF", {f"2026-10-{day:02d}": 4.0 + day / 100 for day in range(1, 31)})

    cli.main(["--indicator", "DFF"], run_with_fred)
    assert database.count("economic_indicators") == 10  # the lookback

    cli.main(["--indicator", "DFF", "--backfill"], run_with_fred)
    assert database.count("economic_indicators") == 30


def test_a_database_that_cannot_be_reached_exits_2_and_saves_nothing(
    database, fred, run_with_fred, monkeypatch, unused_port, capsys
):
    fred.publish("DFF", {"2026-11-12": 4.33})
    monkeypatch.setenv("DB_HOST", "127.0.0.1")
    monkeypatch.setenv("DB_PORT", str(unused_port))

    code = cli.main(["--indicator", "DFF"], run_with_fred)

    captured = capsys.readouterr()
    assert code == cli.EXIT_RUN_FAILED
    assert "Run failed, nothing was saved" in captured.err
    assert captured.out == ""
    assert database.count("economic_indicators") == 0


# --- the real command ----------------------------------------------------------


def run_command(tmp_path, *arguments, **environment):
    """Run `python -m src.econ_data` as a new process.

    The process starts in an empty folder, so it cannot read the .env file in
    the repository, and it gets only the variables passed in `environment`
    (plus those the operating system needs), so no real FRED key can leak in.
    """
    own = {k: v for k, v in os.environ.items() if not k.startswith(("DB_", "FRED_"))}
    env = {**own, "PYTHONPATH": str(REPO_ROOT), **environment}
    return subprocess.run(
        [sys.executable, "-m", "src.econ_data", *arguments],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60,
    )


def database_environment(database):
    s = database.settings
    return {
        "DB_HOST": s.db_host,
        "DB_PORT": str(s.db_port),
        "DB_NAME": s.db_name,
        "DB_USER": s.db_user,
        "DB_PASSWORD": s.db_password.get_secret_value(),
    }


def test_the_command_without_a_fred_key_exits_1_after_writing_the_indicator_definitions(database, tmp_path):
    done = run_command(tmp_path, "--indicator", "DFF", **database_environment(database))

    assert done.returncode == cli.EXIT_INDICATOR_FAILED
    assert "DFF: FRED_API_KEY is not set" in done.stdout
    assert "ERROR src.econ_data.pipeline: DFF: FRED_API_KEY is not set" in done.stderr  # the log line
    assert database.execute("SELECT indicator_id FROM indicator_metadata") == [("DFF",)]
    assert database.count("economic_indicators") == 0


def test_the_command_without_database_credentials_exits_2(tmp_path):
    done = run_command(tmp_path, FRED_API_KEY="not-used")

    assert done.returncode == cli.EXIT_RUN_FAILED
    assert "No database credentials" in done.stderr
    assert done.stdout == ""


def test_the_command_rejects_an_unknown_indicator_with_exit_2(tmp_path):
    done = run_command(tmp_path, "--indicator", "GDP")

    assert done.returncode == cli.EXIT_RUN_FAILED
    assert "invalid choice" in done.stderr
