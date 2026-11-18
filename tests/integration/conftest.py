"""Fixtures for the integration tests: tests that run against a real PostgreSQL server.

The server is the one from docker-compose.yml. The tests find it the way the
pipeline does: from environment variables, then from the .env file in the
repository root. They never use the database named in .env. They create a
separate one, econ_data_test, drop it and rebuild it from db/schema.sql at the
start of every test run, and empty its tables before every test.

If the server cannot be reached the tests are skipped, so the rest of the suite
still runs on a computer without Docker. When the CI environment variable is set
(GitHub Actions sets it) they fail instead, so a pipeline with no database
cannot pass by skipping its database tests.

The scaffolding here talks to PostgreSQL with psycopg2 directly, not through
src/econ_data/db, so a bug in the code under test cannot hide itself.
"""
from __future__ import annotations

import os
import socket
from contextlib import contextmanager
from pathlib import Path

import psycopg2
import pytest
from psycopg2 import sql

from src.econ_data.config import INDICATORS, Settings
from src.econ_data.fred_client import FredError, Observation

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO_ROOT / "db" / "schema.sql"

TEST_DB_NAME = "econ_data_test"
MAINTENANCE_DB = "postgres"  # always exists; the place to create and drop other databases from


def pytest_collection_modifyitems(items):
    """Mark every test in this folder as an integration test."""
    here = Path(__file__).parent
    for item in items:
        if here in item.path.parents:
            item.add_marker(pytest.mark.integration)


def require_test_database(name: str) -> None:
    """Refuse to continue unless `name` is a test database.

    Every statement here that deletes data or a database calls this first, so
    a wrong setting cannot make the tests wipe a real database.
    """
    if not name.endswith("_test"):
        raise RuntimeError(f"Refusing to change database {name!r}: test database names end with _test")


def _open(settings: Settings, db_name: str):
    return psycopg2.connect(
        host=settings.db_host,
        port=settings.db_port,
        dbname=db_name,
        user=settings.db_user,
        password=settings.db_password.get_secret_value(),
        connect_timeout=5,
    )


# --- the server ----------------------------------------------------------------


class Server:
    """The PostgreSQL server: creates, drops and looks up databases on it."""

    def __init__(self, settings: Settings):
        self.settings = settings

    def settings_for(self, db_name: str) -> Settings:
        return self.settings.model_copy(update={"db_name": db_name})

    def _run(self, query, params=None) -> list[tuple]:
        # CREATE DATABASE and DROP DATABASE cannot run inside a transaction block,
        # so this connection uses autocommit.
        conn = _open(self.settings, MAINTENANCE_DB)
        try:
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute(query, params)
                return cur.fetchall() if cur.description else []
        finally:
            conn.close()

    def database_exists(self, name: str) -> bool:
        return bool(self._run("SELECT 1 FROM pg_database WHERE datname = %s", (name,)))

    def create_database(self, name: str) -> None:
        require_test_database(name)
        self._run(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))

    def drop_database(self, name: str) -> None:
        """Drop a test database, closing any connections still open to it."""
        require_test_database(name)
        self._run(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name)))


def _unavailable(message: str):
    """Skip the test, or fail it when running in CI."""
    if os.environ.get("CI"):
        pytest.fail(message, pytrace=False)
    pytest.skip(message)


@pytest.fixture(scope="session")
def server() -> Server:
    """The PostgreSQL server named by the environment variables and .env."""
    settings = Settings(_env_file=REPO_ROOT / ".env")
    if not settings.db_password or not settings.db_password.get_secret_value():
        _unavailable("Integration tests need DB_PASSWORD, set as an environment variable or in .env")

    found = Server(settings)
    try:
        found.database_exists(TEST_DB_NAME)
    except psycopg2.OperationalError as exc:
        _unavailable(
            f"Cannot reach PostgreSQL at {settings.db_host}:{settings.db_port} "
            f"({str(exc).splitlines()[0]}). Start it with: docker compose up -d --wait"
        )
    return found


@pytest.fixture(scope="session")
def database_settings(server) -> Settings:
    """Settings for the test database, rebuilt from the project schema once per test run.

    The database is left in place when the run ends, so after a failure you can
    open it with psql and look at what the test left behind.
    """
    server.drop_database(TEST_DB_NAME)
    server.create_database(TEST_DB_NAME)
    settings = server.settings_for(TEST_DB_NAME)

    conn = _open(settings, TEST_DB_NAME)
    try:
        with conn, conn.cursor() as cur:
            cur.execute(SCHEMA_PATH.read_text(encoding="utf-8"))
    finally:
        conn.close()
    return settings


# --- the test database ---------------------------------------------------------


class ScratchDatabase:
    """The test database, with helpers for putting rows in and reading them back."""

    def __init__(self, settings: Settings):
        require_test_database(settings.db_name)
        self.settings = settings

    @contextmanager
    def cursor(self):
        """A cursor on its own connection: commits when the block ends, rolls back on an error."""
        conn = _open(self.settings, self.settings.db_name)
        try:
            with conn, conn.cursor() as cur:
                yield cur
        finally:
            conn.close()

    def execute(self, query, params=None) -> list[tuple]:
        """Run one statement and return its rows (an empty list if it returns none)."""
        with self.cursor() as cur:
            cur.execute(query, params)
            return cur.fetchall() if cur.description else []

    def empty(self) -> None:
        self.execute("TRUNCATE economic_indicators, indicator_metadata RESTART IDENTITY")

    def count(self, table: str) -> int:
        return self.execute(sql.SQL("SELECT COUNT(*) FROM {}").format(sql.Identifier(table)))[0][0]

    def seed(self, indicator_id: str, observations: dict[str, float] | None = None, fetched_at=None) -> None:
        """Insert an indicator and some observations directly, without the pipeline.

        `observations` maps "YYYY-MM-DD" to a value. `fetched_at`, if given, is
        stored on every row; otherwise the database fills in the current time.
        """
        with self.cursor() as cur:
            cur.execute(
                "INSERT INTO indicator_metadata (indicator_id, name) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (indicator_id, indicator_id),
            )
            for day, value in (observations or {}).items():
                if fetched_at is None:
                    cur.execute(
                        "INSERT INTO economic_indicators (indicator_id, date, value) VALUES (%s, %s, %s)",
                        (indicator_id, day, value),
                    )
                else:
                    cur.execute(
                        "INSERT INTO economic_indicators (indicator_id, date, value, fetched_at)"
                        " VALUES (%s, %s, %s, %s)",
                        (indicator_id, day, value, fetched_at),
                    )

    def stored(self, indicator_id: str) -> list[tuple[str, float]]:
        """The (date, value) rows stored for an indicator, oldest first."""
        rows = self.execute(
            "SELECT date, value FROM economic_indicators WHERE indicator_id = %s ORDER BY date",
            (indicator_id,),
        )
        return [(day.isoformat(), float(value)) for day, value in rows]

    def fetched_at(self, indicator_id: str) -> dict:
        """When each stored row was last written, by date."""
        rows = self.execute(
            "SELECT date, fetched_at FROM economic_indicators WHERE indicator_id = %s", (indicator_id,)
        )
        return {day.isoformat(): stamp for day, stamp in rows}

    @contextmanager
    def read_only(self):
        """Make the database refuse every write, for the length of the block.

        This is a setting on the database itself, applied to each new connection.
        """
        name = sql.Identifier(self.settings.db_name)
        self._alter(sql.SQL("ALTER DATABASE {} SET default_transaction_read_only = on").format(name))
        try:
            yield
        finally:
            self._alter(sql.SQL("ALTER DATABASE {} RESET default_transaction_read_only").format(name))

    def _alter(self, statement) -> None:
        with self.cursor() as cur:
            # While the database is read-only so is this connection, so it must ask
            # for a read-write transaction to be allowed to switch the setting back.
            cur.execute("SET TRANSACTION READ WRITE")
            cur.execute(statement)


@pytest.fixture
def database(database_settings, monkeypatch) -> ScratchDatabase:
    """The test database, emptied, and set as the one Settings() reads from the environment.

    Code that builds its own Settings(), such as the MCP server and the Lambda
    handler, therefore connects to the test database.
    """
    scratch = ScratchDatabase(database_settings)
    scratch.empty()

    monkeypatch.setenv("DB_HOST", database_settings.db_host)
    monkeypatch.setenv("DB_PORT", str(database_settings.db_port))
    monkeypatch.setenv("DB_NAME", database_settings.db_name)
    monkeypatch.setenv("DB_USER", database_settings.db_user)
    monkeypatch.setenv("DB_PASSWORD", database_settings.db_password.get_secret_value())
    return scratch


@pytest.fixture
def open_database():
    """The ScratchDatabase class, for tests that create databases of their own.

    Call it with the Settings of any database whose name ends with _test.
    """
    return ScratchDatabase


@pytest.fixture
def unused_port() -> int:
    """A port on this computer that nothing is listening on."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


# --- FRED ----------------------------------------------------------------------


class FakeFred:
    """Stands in for FRED, so the tests need no network and no API key.

    Pass an instance wherever the pipeline takes a `fetch` function. It answers
    like FRED does: newest observations first, at most `limit` of them (all of
    them for None).
    """

    def __init__(self):
        self._series: dict[str, dict[str, float | None]] = {}
        self._errors: dict[str, str] = {}
        self.calls: list[tuple[str, int | None]] = []  # (indicator_id, limit) of each request

    def publish(self, indicator_id: str, observations: dict[str, float | None]) -> None:
        """Set what FRED returns for an indicator: a dict of "YYYY-MM-DD" to value (None = no value)."""
        self._series[indicator_id] = dict(observations)

    def publish_every_indicator(self, day: str = "2026-11-12") -> None:
        """Publish one observation per indicator, in the middle of its valid range."""
        for indicator in INDICATORS:
            self.publish(indicator.indicator_id, {day: (indicator.min_value + indicator.max_value) / 2})

    def fail(self, indicator_id: str, message: str = "HTTP 500") -> None:
        """Make requests for an indicator fail the way a FRED outage does."""
        self._errors[indicator_id] = message

    def __call__(self, indicator, limit, settings) -> list[Observation]:
        self.calls.append((indicator.indicator_id, limit))
        if indicator.indicator_id in self._errors:
            raise FredError(f"{indicator.series_id}: {self._errors[indicator.indicator_id]}")

        newest_first = sorted(self._series.get(indicator.indicator_id, {}).items(), reverse=True)
        if limit is not None:
            newest_first = newest_first[:limit]
        return [Observation(date=day, value=value) for day, value in newest_first]


@pytest.fixture
def fred() -> FakeFred:
    return FakeFred()
