import os
import sys
from pathlib import Path

import pytest


def test_db_connection_uses_env_and_secrets(monkeypatch):
    calls = {}

    class FakeSecretClient:
        def get_secret_value(self, SecretId):
            calls["secret_id"] = SecretId
            return {"SecretString": '{"username":"app_user","password":"super_secret"}'}

    class FakeConn:
        def cursor(self):
            return self

        def close(self):
            pass

    monkeypatch.setenv("DB_HOST", "db.example.com")
    monkeypatch.setenv("DB_NAME", "econ_mcp")
    monkeypatch.setenv("DB_SECRET_ARN", "arn:aws:secretsmanager:us-east-1:123:secret:db")

    import src.db_connection as db_connection

    fake_boto3 = type("FakeBoto3", (), {"client": lambda *args, **kwargs: FakeSecretClient()})
    def fake_connect(**kwargs):
        calls["connect_kwargs"] = kwargs
        return FakeConn()

    monkeypatch.setattr(db_connection, "boto3", fake_boto3, raising=False)
    monkeypatch.setattr(db_connection.psycopg2, "connect", fake_connect)

    conn = db_connection.get_db_connection()
    assert isinstance(conn, FakeConn)
    assert calls["connect_kwargs"]["host"] == "db.example.com"
    assert calls["connect_kwargs"]["database"] == "econ_mcp"
    assert calls["connect_kwargs"]["user"] == "app_user"
    assert calls["connect_kwargs"]["password"] == "super_secret"
    assert calls["secret_id"] == "arn:aws:secretsmanager:us-east-1:123:secret:db"


def test_lambda_handler_returns_summary_and_verify_mode(monkeypatch):
    import lambda_function

    calls = {}

    def fake_fetch(indicator_id, series_id, limit):
        calls.setdefault("fetches", []).append((indicator_id, series_id, limit))
        return 2

    monkeypatch.setattr(lambda_function, "fetch_and_store_indicator", fake_fetch)
    monkeypatch.setattr(lambda_function, "_verify_database_contents", lambda: [{"indicator_id": "GDP", "count": 1, "max_date": "2024-01-01"}])

    result = lambda_function.lambda_handler({"mode": "verify"}, None)
    assert isinstance(result, dict)
    assert result["mode"] == "verify"

    summary = lambda_function.lambda_handler({}, None)
    assert isinstance(summary, dict)
    assert summary["GDP"] == "2 new records"
    assert summary["FEDFUNDS"] == "2 new records"
    assert summary["UMCSENT"] == "2 new records"


class FakePgCursor:
    def __init__(self, fetchone_result=None):
        self.executed = []
        self._fetchone_result = fetchone_result

    def execute(self, query, params=None):
        self.executed.append((query, params))

    def fetchone(self):
        return self._fetchone_result

    def close(self):
        pass


class FakePgConn:
    def __init__(self, cursor):
        self._cursor = cursor
        self.autocommit = False
        self.committed = False
        self.closed = False

    def cursor(self):
        return self._cursor

    def commit(self):
        self.committed = True

    def close(self):
        self.closed = True


def _setup_setup_mode(monkeypatch, db_exists):
    monkeypatch.setenv("DB_HOST", "db.example.com")
    monkeypatch.setenv("DB_NAME", "econ_mcp")
    monkeypatch.setenv("DB_SECRET_ARN", "arn:aws:secretsmanager:us-east-1:123:secret:db")

    default_cursor = FakePgCursor(fetchone_result=(1,) if db_exists else None)
    default_conn = FakePgConn(default_cursor)
    target_cursor = FakePgCursor()
    target_conn = FakePgConn(target_cursor)

    class FakeSecretClient:
        def get_secret_value(self, SecretId):
            return {"SecretString": '{"username":"app_user","password":"super_secret"}'}

    fake_boto3 = type("FakeBoto3", (), {"client": staticmethod(lambda service: FakeSecretClient())})

    def fake_connect(**kwargs):
        if kwargs.get("dbname") == "postgres":
            return default_conn
        return target_conn

    fake_psycopg2 = type("FakePsycopg2", (), {"connect": staticmethod(fake_connect)})

    monkeypatch.setitem(sys.modules, "boto3", fake_boto3)
    monkeypatch.setitem(sys.modules, "psycopg2", fake_psycopg2)

    return default_cursor, target_cursor


def test_ensure_database_and_schema_creates_database_when_missing(monkeypatch):
    import lambda_function

    default_cursor, target_cursor = _setup_setup_mode(monkeypatch, db_exists=False)

    result = lambda_function._ensure_database_and_schema()

    assert result["created"] is True
    assert result["schema_applied"] is True
    create_calls = [q for q, _ in default_cursor.executed if "CREATE DATABASE" in q]
    assert len(create_calls) == 1
    assert len(target_cursor.executed) == 1


def test_ensure_database_and_schema_skips_create_when_database_exists(monkeypatch):
    import lambda_function

    default_cursor, target_cursor = _setup_setup_mode(monkeypatch, db_exists=True)

    result = lambda_function._ensure_database_and_schema()

    assert result["created"] is False
    assert result["schema_applied"] is True
    create_calls = [q for q, _ in default_cursor.executed if "CREATE DATABASE" in q]
    assert len(create_calls) == 0
    assert len(target_cursor.executed) == 1


def test_schema_sql_has_no_destructive_drop():
    schema = Path(__file__).resolve().parents[1] / "db" / "schema.sql"
    content = schema.read_text()
    assert "DROP TABLE" not in content.upper()
