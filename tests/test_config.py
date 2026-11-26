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


def write_env_file(tmp_path, text):
    path = tmp_path / ".env"
    path.write_text(text, encoding="utf-8")
    return path


def test_settings_read_values_from_an_env_file(tmp_path):
    path = write_env_file(
        tmp_path, "DB_PORT=6543\nDB_PASSWORD=from-file\nFRED_API_KEY = abc123\n"
    )

    settings = Settings(_env_file=path)

    assert settings.db_port == 6543
    assert settings.db_password.get_secret_value() == "from-file"
    assert settings.fred_api_key.get_secret_value() == "abc123"
    assert settings.db_host == "localhost"  # not in the file: default


def test_environment_variables_take_priority_over_the_env_file(tmp_path, monkeypatch):
    path = write_env_file(tmp_path, "DB_HOST=from-file\nDB_NAME=from-file\n")
    monkeypatch.setenv("DB_HOST", "from-environment")

    settings = Settings(_env_file=path)

    assert settings.db_host == "from-environment"
    assert settings.db_name == "from-file"


def test_variables_in_the_env_file_that_are_not_settings_are_ignored(tmp_path):
    path = write_env_file(tmp_path, "POSTGRES_PASSWORD=legacy\nSOMETHING_ELSE=1\nDB_USER=me\n")
    assert Settings(_env_file=path).db_user == "me"


def test_an_env_file_saved_with_a_byte_order_mark_is_read_correctly(tmp_path):
    # Some Windows editors and PowerShell 5.1 put a BOM at the start of the file,
    # which would otherwise turn the first name into "\ufeffDB_HOST".
    path = tmp_path / ".env"
    path.write_bytes(b"\xef\xbb\xbfDB_HOST=from-bom-file\nDB_USER=me\n")
    settings = Settings(_env_file=path)
    assert (settings.db_host, settings.db_user) == ("from-bom-file", "me")


def test_a_missing_env_file_is_not_an_error(tmp_path):
    assert Settings(_env_file=tmp_path / "nope.env").db_host == "localhost"


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
