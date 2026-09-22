import requests

import src.fetch_data as fetch_data


class FakeResponse:
    def __init__(self, json_data):
        self._json_data = json_data

    def raise_for_status(self):
        pass

    def json(self):
        return self._json_data


class FakeCursor:
    def __init__(self, rowcount=1):
        self._rowcount = rowcount
        self.executed = []

    def execute(self, query, params=None):
        self.executed.append((query, params))

    @property
    def rowcount(self):
        return self._rowcount

    def close(self):
        pass


class FakeConn:
    def __init__(self, cursor):
        self._cursor = cursor
        self.committed = False
        self.closed = False

    def cursor(self):
        return self._cursor

    def commit(self):
        self.committed = True

    def close(self):
        self.closed = True


def test_fetch_fred_data_success(monkeypatch):
    observations = [{"date": "2024-01-01", "value": "27000.5"}]

    def fake_get(url, params=None):
        return FakeResponse({"observations": observations})

    monkeypatch.setattr(fetch_data.requests, "get", fake_get)

    result = fetch_data.fetch_fred_data("GDP", limit=5)
    assert result == observations


def test_fetch_fred_data_returns_empty_list_on_request_exception(monkeypatch):
    def fake_get(url, params=None):
        raise requests.exceptions.RequestException("connection timed out")

    monkeypatch.setattr(fetch_data.requests, "get", fake_get)

    result = fetch_data.fetch_fred_data("GDP", limit=5)
    assert result == []


def _run_insert_data(monkeypatch, observations, rowcount=1):
    cursor = FakeCursor(rowcount=rowcount)
    conn = FakeConn(cursor)
    monkeypatch.setattr(fetch_data, "get_db_connection", lambda: conn)

    inserted, skipped = fetch_data.insert_data("GDP", observations)
    return inserted, skipped, cursor, conn


def test_insert_data_skips_missing_value_marker(monkeypatch):
    observations = [{"date": "2024-01-01", "value": "."}]
    inserted, skipped, cursor, conn = _run_insert_data(monkeypatch, observations)

    assert inserted == 0
    assert skipped == 1
    assert cursor.executed == []


def test_insert_data_skips_invalid_date(monkeypatch):
    observations = [{"date": "not-a-date", "value": "25000"}]
    inserted, skipped, cursor, conn = _run_insert_data(monkeypatch, observations)

    assert inserted == 0
    assert skipped == 1
    assert cursor.executed == []


def test_insert_data_skips_non_numeric_value(monkeypatch):
    observations = [{"date": "2024-01-01", "value": "not-a-number"}]
    inserted, skipped, cursor, conn = _run_insert_data(monkeypatch, observations)

    assert inserted == 0
    assert skipped == 1
    assert cursor.executed == []


def test_insert_data_skips_value_outside_validation_range(monkeypatch):
    observations = [{"date": "2024-01-01", "value": "999999"}]  # above GDP max
    inserted, skipped, cursor, conn = _run_insert_data(monkeypatch, observations)

    assert inserted == 0
    assert skipped == 1
    assert cursor.executed == []


def test_insert_data_inserts_valid_observation(monkeypatch):
    observations = [{"date": "2024-01-01", "value": "25000"}]
    inserted, skipped, cursor, conn = _run_insert_data(monkeypatch, observations, rowcount=1)

    assert inserted == 1
    assert skipped == 0
    assert len(cursor.executed) == 1
    assert conn.committed is True
    assert conn.closed is True


def test_insert_data_conflict_do_nothing_does_not_count_as_inserted(monkeypatch):
    observations = [{"date": "2024-01-01", "value": "25000"}]
    inserted, skipped, cursor, conn = _run_insert_data(monkeypatch, observations, rowcount=0)

    assert inserted == 0
    assert skipped == 0
    assert len(cursor.executed) == 1


def test_fetch_and_store_indicator_calls_insert_with_fetched_observations(monkeypatch):
    observations = [{"date": "2024-01-01", "value": "25000"}]
    calls = {}

    monkeypatch.setattr(fetch_data, "fetch_fred_data", lambda series_id, limit: observations)

    def fake_insert_data(indicator_id, obs):
        calls["indicator_id"] = indicator_id
        calls["observations"] = obs
        return 3, 0

    monkeypatch.setattr(fetch_data, "insert_data", fake_insert_data)

    result = fetch_data.fetch_and_store_indicator("GDP", "GDP", limit=5)

    assert result == 3
    assert calls["indicator_id"] == "GDP"
    assert calls["observations"] == observations
