"""mcp_server against a real PostgreSQL server: the tools and resources read and write real rows.

The server reads its database from the environment, which the `database`
fixture points at the test database.
"""
import json
from datetime import date, timedelta

import psycopg2
import pytest

from src.econ_data import mcp_server
from src.econ_data.config import INDICATORS
from src.econ_data.pipeline import run_pipeline, sync_metadata

pytestmark = pytest.mark.asyncio


def text_of(result):
    """The text a tool call returned to the model."""
    return result.content[0].text


# --- get_latest_indicator ------------------------------------------------------


async def test_latest_returns_the_newest_stored_row(database):
    database.seed("DFF", {"2026-11-10": 4.31, "2026-11-12": 4.33, "2026-11-11": 4.32}, fetched_at="2026-11-13 03:04:05")

    result = await mcp_server.mcp.call_tool("get_latest_indicator", {"indicator_id": "DFF"})

    assert json.loads(text_of(result)) == {
        "indicator": "DFF",
        "date": "2026-11-12",
        "value": 4.33,
        "fetched_at": "2026-11-13 03:04:05",
    }


async def test_latest_for_an_indicator_with_no_rows_says_so(database):
    database.seed("DFF", {"2026-11-12": 4.33})
    result = await mcp_server.mcp.call_tool("get_latest_indicator", {"indicator_id": "SP500"})
    assert text_of(result) == "No data found for SP500"


async def test_latest_only_looks_at_the_requested_indicator(database):
    database.seed("DFF", {"2026-11-10": 4.33})
    database.seed("SP500", {"2026-11-12": 6000.5})

    result = await mcp_server.mcp.call_tool("get_latest_indicator", {"indicator_id": "DFF"})

    assert json.loads(text_of(result))["date"] == "2026-11-10"


# --- get_indicator_history -----------------------------------------------------


async def test_history_returns_the_newest_rows_first(database):
    database.seed("DFF", {"2026-11-10": 4.31, "2026-11-11": 4.32, "2026-11-12": 4.33})

    result = await mcp_server.mcp.call_tool("get_indicator_history", {"indicator_id": "DFF", "limit": 2})

    assert json.loads(text_of(result)) == {
        "indicator": "DFF",
        "count": 2,
        "data": [{"date": "2026-11-12", "value": 4.33}, {"date": "2026-11-11", "value": 4.32}],
    }


async def test_history_returns_ten_rows_when_no_limit_is_given(database):
    database.seed("DFF", {f"2026-10-{day:02d}": 4.0 + day / 100 for day in range(1, 16)})

    result = await mcp_server.mcp.call_tool("get_indicator_history", {"indicator_id": "DFF"})

    payload = json.loads(text_of(result))
    assert payload["count"] == 10
    assert payload["data"][0]["date"] == "2026-10-15"


async def test_history_for_an_indicator_with_no_rows_says_so(database):
    result = await mcp_server.mcp.call_tool("get_indicator_history", {"indicator_id": "VIXCLS"})
    assert text_of(result) == "No data found for VIXCLS"


# --- resources -----------------------------------------------------------------


async def test_catalog_lists_every_defined_indicator_with_its_count_and_latest_date(database):
    with database.cursor() as cur:
        sync_metadata(cur)
    database.seed("DFF", {"2026-11-11": 4.32, "2026-11-12": 4.33})

    (content,) = await mcp_server.mcp.read_resource("fred://catalog")

    indicators = {i["indicator_id"]: i for i in json.loads(content.content)["indicators"]}
    assert list(indicators) == sorted(i.indicator_id for i in INDICATORS)
    assert (indicators["DFF"]["count"], indicators["DFF"]["latest_date"]) == (2, "2026-11-12")
    assert indicators["DFF"]["units"] == "percent"
    # An indicator with a definition but no observations is listed with a count of 0.
    assert (indicators["SP500"]["count"], indicators["SP500"]["latest_date"]) == (0, None)


async def test_series_resource_returns_the_newest_hundred_rows(database):
    first_day = date(2026, 1, 1)
    database.seed("DFF", {(first_day + timedelta(days=n)).isoformat(): 4.0 for n in range(120)})

    (content,) = await mcp_server.mcp.read_resource("fred://series/DFF")

    payload = json.loads(content.content)
    assert payload["count"] == mcp_server.SERIES_RESOURCE_LIMIT == 100
    assert payload["data"][0]["date"] == "2026-04-30"
    assert payload["data"][-1]["date"] == "2026-01-21"


async def test_series_resource_for_a_known_indicator_with_no_rows_is_empty_not_an_error(database):
    (content,) = await mcp_server.mcp.read_resource("fred://series/DFF")
    assert json.loads(content.content) == {"indicator": "DFF", "count": 0, "data": []}


# --- reading never writes ------------------------------------------------------


async def test_every_read_path_works_on_a_database_that_refuses_writes(database):
    database.seed("DFF", {"2026-11-12": 4.33})
    with database.read_only():
        # Check first that the database really refuses writes, or the rest proves nothing.
        with pytest.raises(psycopg2.errors.ReadOnlySqlTransaction):
            database.execute("DELETE FROM economic_indicators")

        latest = await mcp_server.mcp.call_tool("get_latest_indicator", {"indicator_id": "DFF"})
        history = await mcp_server.mcp.call_tool("get_indicator_history", {"indicator_id": "DFF"})
        (catalog,) = await mcp_server.mcp.read_resource("fred://catalog")
        (series,) = await mcp_server.mcp.read_resource("fred://series/DFF")

    assert json.loads(text_of(latest))["value"] == 4.33
    assert json.loads(text_of(history))["count"] == 1
    assert json.loads(catalog.content)["indicators"][0]["count"] == 1
    assert json.loads(series.content)["count"] == 1


# --- fetch_fresh_data ----------------------------------------------------------


@pytest.fixture
def fred_in_server(monkeypatch, fred):
    """Make the fetch_fresh_data tool read from FakeFred instead of FRED."""
    monkeypatch.setattr(
        mcp_server, "run_pipeline", lambda settings, indicators: run_pipeline(settings, indicators, fetch=fred)
    )
    return fred


async def test_fetching_one_indicator_stores_its_rows_and_reports_the_summary(database, fred_in_server):
    fred_in_server.publish_every_indicator()

    result = await mcp_server.mcp.call_tool("fetch_fresh_data", {"indicator_id": "DFF"})

    (summary,) = json.loads(text_of(result))["summaries"]
    assert (summary["indicator_id"], summary["inserted"], summary["error"]) == ("DFF", 1, None)
    assert database.stored("DFF") == [("2026-11-12", 12.5)]
    assert database.execute("SELECT indicator_id FROM indicator_metadata") == [("DFF",)]


async def test_fetching_all_stores_every_indicator(database, fred_in_server):
    fred_in_server.publish_every_indicator()

    result = await mcp_server.mcp.call_tool("fetch_fresh_data", {"indicator_id": "all"})

    summaries = json.loads(text_of(result))["summaries"]
    assert [s["indicator_id"] for s in summaries] == [i.indicator_id for i in INDICATORS]
    assert database.count("economic_indicators") == len(INDICATORS)


async def test_fetching_twice_in_a_row_changes_nothing_the_second_time(database, fred_in_server):
    fred_in_server.publish_every_indicator()
    await mcp_server.mcp.call_tool("fetch_fresh_data", {"indicator_id": "DFF"})
    before = database.fetched_at("DFF")

    result = await mcp_server.mcp.call_tool("fetch_fresh_data", {"indicator_id": "DFF"})

    (summary,) = json.loads(text_of(result))["summaries"]
    assert (summary["inserted"], summary["updated"], summary["unchanged"]) == (0, 0, 1)
    assert database.fetched_at("DFF") == before


async def test_the_tool_reports_a_fred_failure_and_stores_nothing(database, fred_in_server):
    fred_in_server.fail("DFF", "HTTP 500")

    result = await mcp_server.mcp.call_tool("fetch_fresh_data", {"indicator_id": "DFF"})

    (summary,) = json.loads(text_of(result))["summaries"]
    assert summary["error"] == "DFF: HTTP 500"
    assert database.count("economic_indicators") == 0
