"""MCP server that exposes the stored economic data.

Tools (actions a model can call):
    get_latest_indicator   newest stored observation for one indicator
    get_indicator_history  newest stored observations for one indicator
    fetch_fresh_data       run the pipeline for one indicator or all of them

Resources (read-only context, addressed by URI):
    fred://catalog                  the indicators in the database and how much data each has
    fred://series/{indicator_id}    the newest stored observations for one indicator

The indicators the server accepts come from config. Only fetch_fresh_data
writes to the database; every other function here only reads.

Run it with:
    python -m src.econ_data.mcp_server        stdio, launched by an MCP host
    python -m src.econ_data.mcp_server http   Streamable HTTP on 127.0.0.1:8765/mcp
"""
import json
import logging
import sys
from dataclasses import asdict
from typing import Annotated, Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ResourceNotFoundError
from mcp.types import ToolAnnotations
from pydantic import Field

from .config import INDICATORS, INDICATORS_BY_ID, Settings, get_indicator
from .db import connection
from .pipeline import run_pipeline

logger = logging.getLogger(__name__)

SERVER_NAME = "economic-data-server"
SERVER_VERSION = "0.3.0"  # passed explicitly: an unversioned server reports an empty version
HTTP_HOST = "127.0.0.1"
HTTP_PORT = 8765

DEFAULT_HISTORY_LIMIT = 10
MAX_HISTORY_LIMIT = 1000
SERIES_RESOURCE_LIMIT = 100

# The values a model may pass as indicator_id. They come from config, so adding
# an indicator there makes it available here without editing this file.
IndicatorId = Literal[tuple(INDICATORS_BY_ID)]
IndicatorIdOrAll = Literal[tuple(INDICATORS_BY_ID) + ("all",)]
HistoryLimit = Annotated[int, Field(ge=1, le=MAX_HISTORY_LIMIT)]

LATEST_SQL = """
SELECT date, value, fetched_at
FROM economic_indicators
WHERE indicator_id = %s
ORDER BY date DESC
LIMIT 1
"""

HISTORY_SQL = """
SELECT date, value
FROM economic_indicators
WHERE indicator_id = %s
ORDER BY date DESC
LIMIT %s
"""

CATALOG_SQL = """
SELECT m.indicator_id, m.name, m.description, m.frequency, m.units, m.source,
       COUNT(e.id), MAX(e.date)
FROM indicator_metadata m
LEFT JOIN economic_indicators e ON e.indicator_id = m.indicator_id
GROUP BY m.indicator_id
ORDER BY m.indicator_id
"""

# Tool annotations are hints to the host: it can run read-only tools without asking.
READ_ONLY = ToolAnnotations(read_only_hint=True)
WRITES_DATA = ToolAnnotations(read_only_hint=False, idempotent_hint=True, open_world_hint=True)

mcp = MCPServer(SERVER_NAME, version=SERVER_VERSION)


# --- Resources: read-only context -------------------------------------------


@mcp.resource(
    "fred://catalog",
    name="catalog",
    description="The indicators stored in the database, with row count and latest date for each",
    mime_type="application/json",
)
def catalog() -> str:
    rows = _query(CATALOG_SQL)
    return _to_json(
        {
            "indicators": [
                {
                    "indicator_id": indicator_id,
                    "name": name,
                    "description": description,
                    "frequency": frequency,
                    "units": units,
                    "source": source,
                    "count": count,
                    "latest_date": latest.isoformat() if latest else None,
                }
                for indicator_id, name, description, frequency, units, source, count, latest in rows
            ]
        }
    )


@mcp.resource(
    "fred://series/{indicator_id}",
    name="series",
    description=f"The newest {SERIES_RESOURCE_LIMIT} stored observations for one indicator",
    mime_type="application/json",
)
def series(indicator_id: str) -> str:
    if indicator_id not in INDICATORS_BY_ID:
        raise ResourceNotFoundError(f"No indicator named {indicator_id}")
    data = _load_history(indicator_id, SERIES_RESOURCE_LIMIT)
    return _to_json({"indicator": indicator_id, "count": len(data), "data": data})


# --- Tools: actions the model decides to call -------------------------------
# These are plain `def`, not `async def`: the SDK runs them on a worker thread,
# so the blocking database and network calls do not freeze the server.


@mcp.tool(annotations=READ_ONLY)
def get_latest_indicator(indicator_id: IndicatorId) -> str:
    """Get the most recent stored value for an economic indicator"""
    rows = _query(LATEST_SQL, (indicator_id,))
    if not rows:
        return f"No data found for {indicator_id}"

    date, value, fetched_at = rows[0]
    return _to_json(
        {
            "indicator": indicator_id,
            "date": str(date),
            "value": float(value),
            "fetched_at": str(fetched_at),
        }
    )


@mcp.tool(annotations=READ_ONLY)
def get_indicator_history(
    indicator_id: IndicatorId, limit: HistoryLimit = DEFAULT_HISTORY_LIMIT
) -> str:
    """Get the newest stored observations for an economic indicator, newest first"""
    data = _load_history(indicator_id, limit)
    if not data:
        return f"No data found for {indicator_id}"
    return _to_json({"indicator": indicator_id, "count": len(data), "data": data})


@mcp.tool(annotations=WRITES_DATA)
def fetch_fresh_data(indicator_id: IndicatorIdOrAll) -> str:
    """Fetch fresh data from FRED for one indicator, or all of them, and store it.

    Returns one summary per indicator: how many observations were fetched,
    inserted, updated or rejected, and an error message if FRED failed.
    """
    indicators = INDICATORS if indicator_id == "all" else (get_indicator(indicator_id),)
    summaries = run_pipeline(Settings(), indicators=indicators)
    return _to_json({"summaries": [asdict(s) for s in summaries]})


# --- Helpers ----------------------------------------------------------------


def _query(sql: str, params: tuple = ()) -> list[tuple]:
    """Run one read-only query and return all its rows."""
    with connection(Settings()) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()


def _load_history(indicator_id: str, limit: int) -> list[dict]:
    rows = _query(HISTORY_SQL, (indicator_id, limit))
    return [{"date": str(date), "value": float(value)} for date, value in rows]


def _to_json(payload: dict) -> str:
    return json.dumps(payload, indent=2)


def main(argv: list[str] | None = None) -> None:
    """Start the server: Streamable HTTP if the first argument is `http`, else stdio."""
    args = sys.argv[1:] if argv is None else argv
    if args[:1] == ["http"]:
        mcp.run(transport="streamable-http", host=HTTP_HOST, port=HTTP_PORT)
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()  