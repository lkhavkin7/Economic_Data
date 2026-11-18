"""db against a real PostgreSQL server: connecting, committing, rolling back and failing."""
import psycopg2
import pytest
from pydantic import SecretStr

from src.econ_data import db


# --- connect -------------------------------------------------------------------


def test_connect_opens_a_connection_to_the_configured_database_and_user(database):
    conn = db.connect(database.settings)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT current_database(), current_user")
            assert cur.fetchone() == (database.settings.db_name, database.settings.db_user)
    finally:
        conn.close()


def test_connect_sets_the_connection_timeout(database):
    conn = db.connect(database.settings)
    try:
        assert conn.get_dsn_parameters()["connect_timeout"] == str(db.CONNECT_TIMEOUT_SECONDS)
    finally:
        conn.close()


def test_a_wrong_password_raises_operational_error(database):
    wrong = database.settings.model_copy(update={"db_password": SecretStr("not-the-password")})
    try:
        conn = db.connect(wrong)
    except psycopg2.OperationalError as exc:
        assert "password authentication failed" in str(exc)
    else:
        conn.close()
        pytest.skip("this server accepts any password (trust authentication)")


def test_a_server_that_is_not_listening_raises_operational_error(database, unused_port):
    nobody_home = database.settings.model_copy(update={"db_host": "127.0.0.1", "db_port": unused_port})
    with pytest.raises(psycopg2.OperationalError):
        db.connect(nobody_home)


# --- connection ----------------------------------------------------------------


def test_leaving_the_block_normally_commits_and_closes(database):
    with db.connection(database.settings) as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO indicator_metadata (indicator_id, name) VALUES ('KEPT', 'kept')")

    assert conn.closed
    # A different connection sees the row, so it really was committed.
    assert database.execute("SELECT indicator_id FROM indicator_metadata") == [("KEPT",)]


def test_an_error_in_the_block_rolls_back_closes_and_reraises(database):
    with pytest.raises(RuntimeError, match="boom"):
        with db.connection(database.settings) as conn:
            with conn.cursor() as cur:
                cur.execute("INSERT INTO indicator_metadata (indicator_id, name) VALUES ('LOST', 'lost')")
            raise RuntimeError("boom")

    assert conn.closed
    assert database.count("indicator_metadata") == 0


def test_a_database_error_part_way_through_undoes_the_statements_before_it(database):
    with pytest.raises(psycopg2.errors.UniqueViolation):
        with db.connection(database.settings) as conn:
            with conn.cursor() as cur:
                cur.execute("INSERT INTO indicator_metadata (indicator_id, name) VALUES ('A', 'first')")
                cur.execute("INSERT INTO indicator_metadata (indicator_id, name) VALUES ('B', 'second')")
                cur.execute("INSERT INTO indicator_metadata (indicator_id, name) VALUES ('A', 'again')")

    assert conn.closed
    assert database.count("indicator_metadata") == 0
