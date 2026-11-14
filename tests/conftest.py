import pytest

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
    """Start every test with none of the config environment variables set."""
    for name in CONFIG_ENVIRONMENT_VARIABLES:
        monkeypatch.delenv(name, raising=False)