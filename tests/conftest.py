import pytest

from src.econ_data.config import Settings

CONFIG_ENVIRONMENT_VARIABLES = (
    "DB_HOST",
    "DB_PORT",
    "DB_NAME",
    "DB_USER",
    "DB_PASSWORD",
    "DB_SECRET_ARN",
    "FRED_API_KEY",
)


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    """Start every test with no config environment variables and no .env file.

    Settings reads a .env file from the current directory, which on a
    developer machine holds real values. Tests that need a .env file pass one
    explicitly with Settings(_env_file=path).
    """
    for name in CONFIG_ENVIRONMENT_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setitem(Settings.model_config, "env_file", None)