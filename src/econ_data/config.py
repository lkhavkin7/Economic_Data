"""Config for the pipeline.

Holds two things: the settings (database location, credentials, FRED API key),
read from environment variables, and the indicators, one entry per tracked
series with its name, units, frequency, valid range and lookback.
"""
from __future__ import annotations

from dataclasses import dataclass

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


# ---------------------------------------------------------------------------
# Indicators
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Indicator:
    indicator_id: str   # the name this project uses for the indicator
    series_id: str      # the name the data source uses for the series
    name: str
    description: str
    frequency: str      # how often the source publishes: "daily" or "monthly"
    units: str
    min_value: float    # lowest accepted value
    max_value: float    # highest accepted value
    lookback: int       # number of most recent observations requested per run
    source: str = "FRED"


INDICATORS: tuple[Indicator, ...] = (
    Indicator(
        indicator_id="DFF",
        series_id="DFF",
        name="Effective Federal Funds Rate",
        description="Rate banks actually paid each other for overnight loans, published daily",
        frequency="daily",
        units="percent",
        min_value=0,
        max_value=20,
        lookback=10,
    ),
    Indicator(
        indicator_id="DFEDTARU",
        series_id="DFEDTARU",
        name="Federal Funds Target Rate, Upper Limit",
        description="Top of the range the Fed is aiming for, changes only at Fed decisions",
        frequency="daily",
        units="percent",
        min_value=0,
        max_value=20,
        lookback=10,
    ),
    Indicator(
        indicator_id="DFEDTARL",
        series_id="DFEDTARL",
        name="Federal Funds Target Rate, Lower Limit",
        description="Bottom of the range the Fed is aiming for, changes only at Fed decisions",
        frequency="daily",
        units="percent",
        min_value=0,
        max_value=20,
        lookback=10,
    ),
    Indicator(
        indicator_id="FEDFUNDS",
        series_id="FEDFUNDS",
        name="Federal Funds Rate, Monthly Average",
        description="Monthly average of the effective federal funds rate",
        frequency="monthly",
        units="percent",
        min_value=0,
        max_value=20,
        lookback=3,
    ),
    Indicator(
        indicator_id="SP500",
        series_id="SP500",
        name="S&P 500 Index",
        description="Closing level of the S&P 500 stock index",
        frequency="daily",
        units="index",
        min_value=100,
        max_value=50000,
        lookback=10,
    ),
    Indicator(
        indicator_id="VIXCLS",
        series_id="VIXCLS",
        name="CBOE Volatility Index (VIX)",
        description="Closing level of the market's expected 30-day volatility",
        frequency="daily",
        units="index",
        min_value=5,
        max_value=100,
        lookback=10,
    ),
)

INDICATORS_BY_ID: dict[str, Indicator] = {i.indicator_id: i for i in INDICATORS}


def get_indicator(indicator_id: str) -> Indicator:
    """Look up one indicator, raising a clear error for an unknown id."""
    try:
        return INDICATORS_BY_ID[indicator_id]
    except KeyError:
        known = ", ".join(sorted(INDICATORS_BY_ID))
        raise KeyError(f"Unknown indicator {indicator_id!r}. Known: {known}") from None


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

class Settings(BaseSettings):
    """Settings read from environment variables.

    Each field is filled from the environment variable with the same name in
    capitals (db_host from DB_HOST). Arguments passed to Settings() take
    priority over the environment. Secrets are SecretStr, which prints as
    '**********'; call .get_secret_value() to read one.
    """

    model_config = SettingsConfigDict(frozen=True)

    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "econ_data"
    db_user: str = "econ"
    db_password: SecretStr | None = None
    # ARN of the AWS Secrets Manager secret that holds the database credentials.
    db_secret_arn: str | None = None
    fred_api_key: SecretStr | None = None