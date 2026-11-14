"""Client for the FRED observations API.

fetch_observations() requests the observations for one indicator and returns
them newest first. Requests have a timeout. Timeouts, connection errors, HTTP
429 and HTTP 5xx are retried with doubling delays; any other failure raises
FredError immediately. Error messages never contain the API key or the URL.
"""
from __future__ import annotations

import time
from typing import Callable

import requests
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from .config import Indicator, Settings

FRED_URL = "https://api.stlouisfed.org/fred/series/observations"
TIMEOUT_SECONDS = (5, 30)  # (connect, read)
MAX_ATTEMPTS = 3
BACKOFF_SECONDS = 1.0  # delay after the first failed attempt; doubles each time
MISSING_VALUE = "."  # what FRED sends for an observation with no value


class FredError(Exception):
    """A FRED request failed or returned something unusable."""


class Observation(BaseModel):
    """One observation. `value` is None when FRED has no value for the date."""

    model_config = ConfigDict(frozen=True)

    date: str  # YYYY-MM-DD
    value: float | None

    @field_validator("value", mode="before")
    @classmethod
    def missing_marker_to_none(cls, value):
        return None if value == MISSING_VALUE else value


class FredResponse(BaseModel):
    """The part of FRED's response this client uses. Other fields are ignored."""

    observations: list[Observation]


def fetch_observations(
    indicator: Indicator,
    limit: int | None,
    settings: Settings | None = None,
    session=None,
    sleep: Callable[[float], None] = time.sleep,
) -> list[Observation]:
    """Fetch observations for one indicator, newest first.

    `limit` is the number of most recent observations to request; None
    requests the full history. `session` is any object with a requests-style
    get(); it defaults to the requests module. `sleep` is called between
    retries. Raises FredError if the API key is not set or the request fails.
    """
    settings = Settings() if settings is None else settings
    api_key = settings.fred_api_key.get_secret_value() if settings.fred_api_key else ""
    series_id = indicator.series_id
    if not api_key:
        raise FredError("FRED_API_KEY is not set")

    params = {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
        "sort_order": "desc",
    }
    if limit is not None:
        params["limit"] = limit

    get = (session or requests).get
    failure = ""

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = get(FRED_URL, params=params, timeout=TIMEOUT_SECONDS)
        except (requests.Timeout, requests.ConnectionError) as exc:
            # Only the exception class is reported: its text can contain the URL.
            failure = type(exc).__name__
            retryable = True
        except requests.RequestException as exc:
            raise FredError(f"{series_id}: request failed ({type(exc).__name__})") from None
        else:
            if response.status_code == 200:
                return _parse(response, series_id)
            failure = f"HTTP {response.status_code}{_error_detail(response, api_key)}"
            retryable = response.status_code == 429 or response.status_code >= 500

        if not retryable:
            raise FredError(f"{series_id}: {failure}") from None
        if attempt < MAX_ATTEMPTS:
            sleep(BACKOFF_SECONDS * 2 ** (attempt - 1))

    raise FredError(f"{series_id}: failed after {MAX_ATTEMPTS} attempts ({failure})")


def _error_detail(response, api_key: str) -> str:
    """Return ': <message>' from a FRED error body, with the API key masked."""
    try:
        message = response.json().get("error_message")
    except (ValueError, AttributeError):
        return ""
    if not message:
        return ""
    return ": " + str(message).replace(api_key, "***")


def _parse(response, series_id: str) -> list[Observation]:
    try:
        body = response.json()
    except ValueError:
        raise FredError(f"{series_id}: response is not valid JSON") from None

    try:
        return FredResponse.model_validate(body).observations
    except ValidationError as exc:
        first = exc.errors()[0]
        location = ".".join(str(part) for part in first["loc"]) or "top level"
        raise FredError(
            f"{series_id}: unexpected response ({location}: {first['msg']})"
        ) from None