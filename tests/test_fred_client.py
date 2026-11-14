import pytest
import requests

from src.econ_data import fred_client
from src.econ_data.config import Settings, get_indicator
from src.econ_data.fred_client import FredError, Observation, fetch_observations

KEY = "testkey123"
SETTINGS = Settings(fred_api_key=KEY)
DFF = get_indicator("DFF")


class FakeResponse:
    def __init__(self, status=200, body=None, invalid_json=False):
        self.status_code = status
        self._body = body
        self._invalid_json = invalid_json

    def json(self):
        if self._invalid_json:
            raise ValueError("not json")
        return self._body


class FakeSession:
    """Returns scripted results in order; an Exception in the script is raised."""

    def __init__(self, *script):
        self.script = list(script)
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append({"url": url, "params": params, "timeout": timeout})
        result = self.script.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def ok(*pairs):
    return FakeResponse(200, {"observations": [{"date": d, "value": v} for d, v in pairs]})


def fetch(session, limit=10, sleeps=None):
    sleeps = [] if sleeps is None else sleeps
    return fetch_observations(DFF, limit, SETTINGS, session=session, sleep=sleeps.append)


def test_missing_api_key_raises_before_any_request():
    session = FakeSession()
    with pytest.raises(FredError, match="FRED_API_KEY is not set"):
        fetch_observations(DFF, 10, Settings(), session=session)
    assert session.calls == []


def test_request_uses_series_key_limit_and_timeout():
    session = FakeSession(ok(("2026-11-12", "4.33")))
    fetch(session, limit=5)
    call = session.calls[0]
    assert call["url"] == fred_client.FRED_URL
    assert call["params"] == {
        "series_id": "DFF",
        "api_key": KEY,
        "file_type": "json",
        "sort_order": "desc",
        "limit": 5,
    }
    assert call["timeout"] == fred_client.TIMEOUT_SECONDS


def test_limit_none_leaves_limit_out_of_the_request():
    session = FakeSession(ok(("2026-11-12", "4.33")))
    fetch(session, limit=None)
    assert "limit" not in session.calls[0]["params"]


def test_observations_are_parsed_in_the_order_received():
    session = FakeSession(ok(("2026-11-12", "4.33"), ("2026-11-11", "4.31")))
    assert fetch(session) == [
        Observation(date="2026-11-12", value=4.33),
        Observation(date="2026-11-11", value=4.31),
    ]


def test_missing_value_marker_becomes_none():
    session = FakeSession(ok(("2026-11-11", "."), ("2026-11-10", "4.30")))
    assert fetch(session) == [
        Observation(date="2026-11-11", value=None),
        Observation(date="2026-11-10", value=4.30),
    ]


def test_empty_observation_list_returns_empty_list():
    assert fetch(FakeSession(ok())) == []


def test_rate_limit_then_success_retries_after_one_second():
    session = FakeSession(FakeResponse(429), ok(("2026-11-12", "4.33")))
    sleeps = []
    assert fetch(session, sleeps=sleeps) == [Observation(date="2026-11-12", value=4.33)]
    assert len(session.calls) == 2
    assert sleeps == [1.0]


def test_timeout_then_success_retries():
    session = FakeSession(requests.Timeout("slow"), ok(("2026-11-12", "4.33")))
    sleeps = []
    assert fetch(session, sleeps=sleeps) == [Observation(date="2026-11-12", value=4.33)]
    assert sleeps == [1.0]


def test_server_errors_stop_after_three_attempts_with_doubling_delay():
    session = FakeSession(FakeResponse(500), FakeResponse(502), FakeResponse(503))
    sleeps = []
    with pytest.raises(FredError, match="failed after 3 attempts") as exc:
        fetch(session, sleeps=sleeps)
    assert "HTTP 503" in str(exc.value)
    assert len(session.calls) == 3
    assert sleeps == [1.0, 2.0]


def test_connection_errors_stop_after_three_attempts():
    session = FakeSession(*[requests.ConnectionError("down")] * 3)
    with pytest.raises(FredError, match="failed after 3 attempts.*ConnectionError"):
        fetch(session)
    assert len(session.calls) == 3


def test_client_error_is_not_retried_and_reports_fred_message():
    body = {"error_message": "Bad Request. The series does not exist."}
    session = FakeSession(FakeResponse(400, body))
    sleeps = []
    with pytest.raises(FredError, match="HTTP 400: Bad Request. The series does not exist."):
        fetch(session, sleeps=sleeps)
    assert len(session.calls) == 1
    assert sleeps == []


def test_api_key_is_masked_if_fred_echoes_it():
    body = {"error_message": f"The value {KEY} is not a registered key"}
    session = FakeSession(FakeResponse(400, body))
    with pytest.raises(FredError) as exc:
        fetch(session)
    assert KEY not in str(exc.value)
    assert "***" in str(exc.value)


def test_exception_text_with_url_is_not_leaked_or_chained():
    leaky = requests.ConnectionError(f"HTTPSConnectionPool: /observations?api_key={KEY}")
    session = FakeSession(leaky, leaky, leaky)
    with pytest.raises(FredError) as exc:
        fetch(session)
    assert KEY not in str(exc.value)


def test_unretryable_request_error_has_no_chained_cause():
    leaky = requests.exceptions.InvalidURL(f"bad url with {KEY}")
    with pytest.raises(FredError) as exc:
        fetch(FakeSession(leaky))
    assert KEY not in str(exc.value)
    assert exc.value.__cause__ is None
    assert exc.value.__suppress_context__ is True


def test_invalid_json_raises():
    session = FakeSession(FakeResponse(200, invalid_json=True))
    with pytest.raises(FredError, match="not valid JSON"):
        fetch(session)


def test_response_without_observations_raises():
    session = FakeSession(FakeResponse(200, {"something": "else"}))
    with pytest.raises(FredError, match="observations: Field required"):
        fetch(session)


def test_observation_missing_a_field_raises():
    session = FakeSession(FakeResponse(200, {"observations": [{"date": "2026-11-12"}]}))
    with pytest.raises(FredError, match="observations.0.value: Field required"):
        fetch(session)


def test_response_that_is_not_an_object_raises():
    session = FakeSession(FakeResponse(200, ["not", "an", "object"]))
    with pytest.raises(FredError, match="unexpected response \\(top level"):
        fetch(session)


def test_extra_fields_in_the_response_are_ignored():
    body = {
        "realtime_start": "2026-11-14",
        "count": 1,
        "observations": [
            {
                "realtime_start": "2026-11-14",
                "realtime_end": "2026-11-14",
                "date": "2026-11-12",
                "value": "4.33",
            }
        ],
    }
    result = fetch(FakeSession(FakeResponse(200, body)))
    assert result == [Observation(date="2026-11-12", value=4.33)]


def test_non_numeric_value_raises():
    session = FakeSession(ok(("2026-11-12", "abc")))
    with pytest.raises(FredError, match="observations.0.value: Input should be a valid number"):
        fetch(session)