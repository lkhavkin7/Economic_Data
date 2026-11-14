import pytest

from src.econ_data import db
from src.econ_data.config import Settings


class FakeConnection:
    def __init__(self):
        self.calls = []

    def commit(self):
        self.calls.append("commit")

    def rollback(self):
        self.calls.append("rollback")

    def close(self):
        self.calls.append("close")


@pytest.fixture
def fake_connect(monkeypatch):
    """Replace psycopg2.connect with a fake that records its arguments."""
    conn = FakeConnection()
    conn.connect_kwargs = {}

    def connect(**kwargs):
        conn.connect_kwargs.update(kwargs)
        return conn

    monkeypatch.setattr(db.psycopg2, "connect", connect)
    return conn


@pytest.fixture
def no_secrets(monkeypatch):
    """Fail the test if anything tries to read from Secrets Manager."""

    def fail(arn):
        raise AssertionError("Secrets Manager should not be called")

    monkeypatch.setattr(db, "_fetch_secret", fail)


def test_password_in_config_is_used_directly(no_secrets):
    settings = Settings(db_user="econ", db_password="pw")
    assert db.get_credentials(settings) == ("econ", "pw")


def test_password_in_config_wins_over_secret_arn(no_secrets):
    settings = Settings(db_user="econ", db_password="pw", db_secret_arn="arn:secret")
    assert db.get_credentials(settings) == ("econ", "pw")


def test_secret_supplies_user_and_password(monkeypatch):
    seen = []

    def fetch(arn):
        seen.append(arn)
        return {"username": "secret_user", "password": "secret_pw"}

    monkeypatch.setattr(db, "_fetch_secret", fetch)
    settings = Settings(db_user="econ", db_secret_arn="arn:secret")

    assert db.get_credentials(settings) == ("secret_user", "secret_pw")
    assert seen == ["arn:secret"]


def test_secret_missing_password_raises(monkeypatch):
    monkeypatch.setattr(db, "_fetch_secret", lambda arn: {"username": "u"})
    with pytest.raises(ValueError, match="missing username or password"):
        db.get_credentials(Settings(db_secret_arn="arn:secret"))


def test_no_credentials_raises(no_secrets):
    with pytest.raises(ValueError, match="No database credentials"):
        db.get_credentials(Settings())


def test_empty_password_counts_as_not_set(no_secrets):
    with pytest.raises(ValueError, match="No database credentials"):
        db.get_credentials(Settings(db_password=""))


def test_connect_passes_settings_to_psycopg2(fake_connect):
    settings = Settings(
        db_host="db.example", db_port=6543, db_name="mydb", db_user="u", db_password="pw"
    )
    db.connect(settings)
    assert fake_connect.connect_kwargs == {
        "host": "db.example",
        "port": 6543,
        "dbname": "mydb",
        "user": "u",
        "password": "pw",
        "connect_timeout": db.CONNECT_TIMEOUT_SECONDS,
    }


def test_connection_commits_then_closes_on_success(fake_connect):
    with db.connection(Settings(db_password="pw")) as conn:
        assert conn is fake_connect
    assert fake_connect.calls == ["commit", "close"]


def test_connection_rolls_back_closes_and_reraises_on_error(fake_connect):
    with pytest.raises(RuntimeError, match="boom"):
        with db.connection(Settings(db_password="pw")):
            raise RuntimeError("boom")
    assert fake_connect.calls == ["rollback", "close"]


def test_connect_failure_propagates(monkeypatch):
    def connect(**kwargs):
        raise db.psycopg2.OperationalError("cannot connect")

    monkeypatch.setattr(db.psycopg2, "connect", connect)
    with pytest.raises(db.psycopg2.OperationalError):
        with db.connection(Settings(db_password="pw")):
            pass