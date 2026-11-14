import pytest
from pydantic import ValidationError

from src.econ_data.config import INDICATORS, Settings, get_indicator


def test_settings_defaults_when_nothing_is_set():
    settings = Settings()
    assert settings.db_host == "localhost"
    assert settings.db_port == 5432
    assert settings.db_name == "econ_data"
    assert settings.db_user == "econ"
    assert settings.db_password is None
    assert settings.db_secret_arn is None
    assert settings.fred_api_key is None


def test_settings_read_environment_variables(monkeypatch):
    monkeypatch.setenv("DB_HOST", "db.example")
    monkeypatch.setenv("DB_PORT", "6543")
    monkeypatch.setenv("DB_NAME", "mydb")
    monkeypatch.setenv("DB_USER", "me")
    monkeypatch.setenv("DB_PASSWORD", "hunter2")
    monkeypatch.setenv("DB_SECRET_ARN", "arn:secret")
    monkeypatch.setenv("FRED_API_KEY", "abc123")

    settings = Settings()

    assert settings.db_host == "db.example"
    assert settings.db_port == 6543
    assert isinstance(settings.db_port, int)
    assert settings.db_name == "mydb"
    assert settings.db_user == "me"
    assert settings.db_password.get_secret_value() == "hunter2"
    assert settings.db_secret_arn == "arn:secret"
    assert settings.fred_api_key.get_secret_value() == "abc123"


def test_arguments_take_priority_over_the_environment(monkeypatch):
    monkeypatch.setenv("DB_HOST", "from-environment")
    assert Settings(db_host="from-argument").db_host == "from-argument"


def test_invalid_port_error_names_the_field(monkeypatch):
    monkeypatch.setenv("DB_PORT", "abc")
    with pytest.raises(ValidationError, match="db_port"):
        Settings()


def test_secrets_do_not_appear_in_repr_or_str():
    settings = Settings(db_password="hunter2", fred_api_key="abc123")
    for text in (repr(settings), str(settings)):
        assert "hunter2" not in text
        assert "abc123" not in text


def test_settings_cannot_be_changed_after_creation():
    settings = Settings()
    with pytest.raises(ValidationError):
        settings.db_host = "elsewhere"


def test_indicator_ids_are_unique():
    ids = [i.indicator_id for i in INDICATORS]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("indicator", INDICATORS, ids=lambda i: i.indicator_id)
def test_every_indicator_has_a_usable_range_and_lookback(indicator):
    assert indicator.min_value < indicator.max_value
    assert indicator.lookback > 0
    assert indicator.frequency in {"daily", "monthly"}


def test_get_indicator_returns_the_matching_entry():
    assert get_indicator("DFF").frequency == "daily"
    assert get_indicator("FEDFUNDS").frequency == "monthly"


def test_get_indicator_unknown_id_raises_and_lists_known_ids():
    with pytest.raises(KeyError, match="Unknown indicator.*DFF"):
        get_indicator("GDP")