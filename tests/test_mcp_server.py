"""mcp_server behaviour that needs no database: the server's description of itself,
how inputs are validated, how the fetch tool calls the pipeline, and how the server starts.

Reading and writing real rows through the tools and resources is tested against a real
PostgreSQL server in tests/integration/test_mcp_db.
"""
import json

import pytest
from mcp.server.mcpserver.exceptions import ResourceNotFoundError, ToolError

from src.econ_data import mcp_server
from src.econ_data.config import INDICATORS, get_indicator
from src.econ_data.pipeline import RunSummary

INDICATOR_IDS = [i.indicator_id for i in INDICATORS]


@pytest.fixture
def no_database(monkeypatch):
    """Fail the test if anything tries to open a database connection."""

    def fail(*args, **kwargs):
        raise AssertionError("the database should not be used")

    monkeypatch.setattr(mcp_server, "connection", fail)


def text_of(result):
    """The text a tool call returned to the model."""
    return result.content[0].text


# --- the server ----------------------------------------------------------------


def test_server_name_and_version_are_set():
    assert mcp_server.mcp.name == "economic-data-server"
    assert mcp_server.mcp.version == mcp_server.SERVER_VERSION


# --- tool listing --------------------------------------------------------------


async def list_tools_by_name():
    return {t.name: t for t in await mcp_server.mcp.list_tools()}


@pytest.mark.asyncio
async def test_exactly_three_tools_are_offered():
    tools = await list_tools_by_name()
    assert set(tools) == {"get_latest_indicator", "get_indicator_history", "fetch_fresh_data"}


@pytest.mark.asyncio
async def test_indicator_choices_come_from_config():
    tools = await list_tools_by_name()
    for name in ("get_latest_indicator", "get_indicator_history"):
        assert tools[name].input_schema["properties"]["indicator_id"]["enum"] == INDICATOR_IDS
    fetch = tools["fetch_fresh_data"].input_schema["properties"]["indicator_id"]
    assert fetch["enum"] == INDICATOR_IDS + ["all"]


@pytest.mark.asyncio
async def test_history_limit_has_a_default_and_bounds():
    tools = await list_tools_by_name()
    schema = tools["get_indicator_history"].input_schema
    assert schema["required"] == ["indicator_id"]
    limit = schema["properties"]["limit"]
    assert (limit["default"], limit["minimum"], limit["maximum"]) == (10, 1, 1000)


@pytest.mark.asyncio
async def test_only_fetch_fresh_data_is_marked_as_writing():
    tools = await list_tools_by_name()
    assert tools["get_latest_indicator"].annotations.read_only_hint is True
    assert tools["get_indicator_history"].annotations.read_only_hint is True
    assert tools["fetch_fresh_data"].annotations.read_only_hint is False


# --- input validation ---------------------------------------------------------


@pytest.mark.asyncio
async def test_an_indicator_not_in_config_is_rejected_before_any_database_call(no_database):
    with pytest.raises(ToolError, match="indicator_id"):
        await mcp_server.mcp.call_tool("get_latest_indicator", {"indicator_id": "GDP"})


@pytest.mark.asyncio
@pytest.mark.parametrize("limit", [0, -1, 1001])
async def test_history_limit_outside_the_bounds_is_rejected_before_any_database_call(no_database, limit):
    with pytest.raises(ToolError, match="limit"):
        await mcp_server.mcp.call_tool("get_indicator_history", {"indicator_id": "DFF", "limit": limit})


# --- fetch_fresh_data ----------------------------------------------------------


@pytest.fixture
def pipeline_calls(monkeypatch):
    calls = []

    def fake_run_pipeline(settings, indicators):
        calls.append(list(indicators))
        return [RunSummary(indicator_id=i.indicator_id, fetched=10, inserted=1) for i in indicators]

    monkeypatch.setattr(mcp_server, "run_pipeline", fake_run_pipeline)
    return calls


@pytest.mark.asyncio
async def test_fetching_one_indicator_runs_the_pipeline_for_only_that_one(pipeline_calls):
    result = await mcp_server.mcp.call_tool("fetch_fresh_data", {"indicator_id": "DFF"})

    assert pipeline_calls == [[get_indicator("DFF")]]
    summaries = json.loads(text_of(result))["summaries"]
    assert [s["indicator_id"] for s in summaries] == ["DFF"]
    assert summaries[0]["inserted"] == 1


@pytest.mark.asyncio
async def test_fetching_all_runs_every_indicator_in_config(pipeline_calls):
    result = await mcp_server.mcp.call_tool("fetch_fresh_data", {"indicator_id": "all"})

    assert pipeline_calls == [list(INDICATORS)]
    summaries = json.loads(text_of(result))["summaries"]
    assert [s["indicator_id"] for s in summaries] == INDICATOR_IDS


@pytest.mark.asyncio
async def test_a_fred_failure_is_reported_in_the_summary_not_hidden(monkeypatch):
    failed = [RunSummary(indicator_id="DFF", error="DFF: HTTP 500")]
    monkeypatch.setattr(mcp_server, "run_pipeline", lambda settings, indicators: failed)

    result = await mcp_server.mcp.call_tool("fetch_fresh_data", {"indicator_id": "DFF"})

    assert json.loads(text_of(result))["summaries"][0]["error"] == "DFF: HTTP 500"


@pytest.mark.asyncio
async def test_a_database_error_becomes_a_tool_error_without_leaking_its_text(monkeypatch):
    def failing(settings, indicators):
        raise RuntimeError("connection to server at 10.0.0.5 refused")

    monkeypatch.setattr(mcp_server, "run_pipeline", failing)
    with pytest.raises(ToolError, match="Error executing tool fetch_fresh_data") as exc:
        await mcp_server.mcp.call_tool("fetch_fresh_data", {"indicator_id": "DFF"})
    assert "10.0.0.5" not in str(exc.value)


# --- resources -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_catalog_resource_and_series_template_are_listed():
    resources = await mcp_server.mcp.list_resources()
    templates = await mcp_server.mcp.list_resource_templates()

    assert [str(r.uri) for r in resources] == ["fred://catalog"]
    assert [t.uri_template for t in templates] == ["fred://series/{indicator_id}"]


@pytest.mark.asyncio
async def test_series_resource_for_an_unknown_indicator_is_not_found(no_database):
    with pytest.raises(ResourceNotFoundError, match="GDP"):
        await mcp_server.mcp.read_resource("fred://series/GDP")


# --- starting the server -------------------------------------------------------


@pytest.fixture
def run_calls(monkeypatch):
    calls = []
    monkeypatch.setattr(mcp_server.mcp, "run", lambda **kwargs: calls.append(kwargs))
    return calls


def test_main_defaults_to_stdio(run_calls):
    mcp_server.main([])
    assert run_calls == [{"transport": "stdio"}]


def test_main_http_runs_streamable_http_on_localhost(run_calls):
    mcp_server.main(["http"])
    assert run_calls == [{"transport": "streamable-http", "host": "127.0.0.1", "port": 8765}]


def test_main_ignores_an_unknown_argument_and_uses_stdio(run_calls):
    mcp_server.main(["bogus"])
    assert run_calls == [{"transport": "stdio"}]
