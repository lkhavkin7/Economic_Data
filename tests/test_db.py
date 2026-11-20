"""db credential lookup. Nothing here opens a connection; connecting, committing and
rolling back are tested against a real database in tests/integration/test_connection."""
import pytest

from src.econ_data import db
from src.econ_data.config import Settings


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
