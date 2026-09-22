import json
from datetime import date, datetime

import pytest

import src.mcp_server as mcp_server


class FakeCursor:
    def __init__(self, fetchone_result=None, fetchall_result=None):
        self._fetchone_result = fetchone_result
        self._fetchall_result = fetchall_result if fetchall_result is not None else []
        self.executed = []

    def execute(self, query, params=None):
        self.executed.append((query, params))

    def fetchone(self):
        return self._fetchone_result

    def fetchall(self):
        return self._fetchall_result

    def close(self):
        pass


class FakeConn:
    def __init__(self, cursor):
        self._cursor = cursor
        self.closed = False

    def cursor(self):
        return self._cursor

    def close(self):
        self.closed = True


@pytest.mark.asyncio
async def test_list_tools_returns_expected_tools_and_schemas():
    tools = await mcp_server.list_tools()
    tools_by_name = {tool.name: tool for tool in tools}

    assert set(tools_by_name) == {"get_latest_indicator", "get_indicator_history", "fetch_fresh_data"}

    latest = tools_by_name["get_latest_indicator"]
    assert latest.inputSchema["required"] == ["indicator_id"]
    assert latest.inputSchema["properties"]["indicator_id"]["enum"] == ["GDP", "FEDFUNDS", "UMCSENT"]

    history = tools_by_name["get_indicator_history"]
    assert history.inputSchema["required"] == ["indicator_id"]
    assert history.inputSchema["properties"]["limit"]["default"] == 10

    fetch_fresh = tools_by_name["fetch_fresh_data"]
    assert fetch_fresh.inputSchema["properties"]["indicator_id"]["enum"] == ["GDP", "FEDFUNDS", "UMCSENT", "all"]


@pytest.mark.asyncio
async def test_call_tool_get_latest_indicator_returns_data(monkeypatch):
    cursor = FakeCursor(fetchone_result=(date(2024, 1, 1), 25000.5, datetime(2024, 1, 2, 3, 4, 5)))
    conn = FakeConn(cursor)
    monkeypatch.setattr(mcp_server, "get_db_connection", lambda: conn)

    result = await mcp_server.call_tool("get_latest_indicator", {"indicator_id": "GDP"})

    assert len(result) == 1
    payload = json.loads(result[0].text)
    assert payload["indicator"] == "GDP"
    assert payload["date"] == "2024-01-01"
    assert payload["value"] == 25000.5
    assert conn.closed is True


@pytest.mark.asyncio
async def test_call_tool_get_latest_indicator_no_data(monkeypatch):
    cursor = FakeCursor(fetchone_result=None)
    conn = FakeConn(cursor)
    monkeypatch.setattr(mcp_server, "get_db_connection", lambda: conn)

    result = await mcp_server.call_tool("get_latest_indicator", {"indicator_id": "GDP"})

    assert len(result) == 1
    assert "No data found for GDP" in result[0].text


@pytest.mark.asyncio
async def test_call_tool_get_indicator_history_returns_data(monkeypatch):
    rows = [(date(2024, 1, 1), 25000.5), (date(2023, 10, 1), 24500.0)]
    cursor = FakeCursor(fetchall_result=rows)
    conn = FakeConn(cursor)
    monkeypatch.setattr(mcp_server, "get_db_connection", lambda: conn)

    result = await mcp_server.call_tool("get_indicator_history", {"indicator_id": "GDP", "limit": 2})

    assert len(result) == 1
    payload = json.loads(result[0].text)
    assert payload["indicator"] == "GDP"
    assert payload["count"] == 2
    assert payload["data"] == [
        {"date": "2024-01-01", "value": 25000.5},
        {"date": "2023-10-01", "value": 24500.0},
    ]


@pytest.mark.asyncio
async def test_call_tool_get_indicator_history_no_data(monkeypatch):
    cursor = FakeCursor(fetchall_result=[])
    conn = FakeConn(cursor)
    monkeypatch.setattr(mcp_server, "get_db_connection", lambda: conn)

    result = await mcp_server.call_tool("get_indicator_history", {"indicator_id": "UMCSENT"})

    assert len(result) == 1
    assert "No data found for UMCSENT" in result[0].text
