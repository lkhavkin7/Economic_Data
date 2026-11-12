import json
import sys
from pathlib import Path
from typing import Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ResourceNotFoundError

from src.db_connection import get_db_connection

# ---------------------------------------------------------------------------
# TOOL LOGIC + PRIMITIVES (what the server offers). Nothing here knows how
# messages arrive.
# ---------------------------------------------------------------------------

# Pass `version` explicitly: in v2 an unversioned server reports an empty version.
mcp = MCPServer("economic-data-server", version="0.2.0")

Indicator = Literal["GDP", "FEDFUNDS", "UMCSENT"]
IndicatorOrAll = Literal["GDP", "FEDFUNDS", "UMCSENT", "all"]

CACHE_FILE = Path(__file__).parent / "data" / "fred_cache.json"


def _load_cache() -> dict:
    with CACHE_FILE.open(encoding="utf-8") as f:
        return json.load(f)


# --- Resources: read-only context, no side effects, no database -------------
@mcp.resource(
    "fred://catalog",
    name="catalog",
    description="Which cached indicators exist",
    mime_type="application/json",
)
def catalog() -> str:
    cache = _load_cache()
    return json.dumps(
        {"indicators": sorted(cache["series"]), "note": cache["note"]}, indent=2
    )


@mcp.resource(
    "fred://series/{indicator_id}",
    name="cached_series",
    description="Cached observations for one indicator, read from a local file",
    mime_type="application/json",
)
def cached_series(indicator_id: str) -> str:
    cache = _load_cache()
    if indicator_id not in cache["series"]:
        raise ResourceNotFoundError(f"No cached series named {indicator_id}")
    payload = {"indicator": indicator_id, "note": cache["note"], **cache["series"][indicator_id]}
    return json.dumps(payload, indent=2)


# --- Tools: actions the model decides to call. These still use the database. -
# Plain `def` on purpose: v2 runs sync handlers on a worker thread, so blocking
# psycopg2 calls don't freeze the event loop.
@mcp.tool()
def get_latest_indicator(indicator_id: Indicator) -> str:
    """Get the most recent value for an economic indicator"""
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT date, value, fetched_at
        FROM economic_indicators
        WHERE indicator_id = %s
        ORDER BY date DESC
        LIMIT 1
        """,
        (indicator_id,),
    )

    result = cur.fetchone()
    cur.close()
    conn.close()

    if result:
        date, value, fetched_at = result
        response = {
            "indicator": indicator_id,
            "date": str(date),
            "value": float(value),
            "fetched_at": str(fetched_at),
        }
        return json.dumps(response, indent=2)
    return f"No data found for {indicator_id}"


@mcp.tool()
def get_indicator_history(indicator_id: Indicator, limit: int = 10) -> str:
    """Get historical data for an economic indicator"""
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT date, value
        FROM economic_indicators
        WHERE indicator_id = %s
        ORDER BY date DESC
        LIMIT %s
        """,
        (indicator_id, limit),
    )

    results = cur.fetchall()
    cur.close()
    conn.close()

    if results:
        history = [{"date": str(date), "value": float(value)} for date, value in results]
        response = {
            "indicator": indicator_id,
            "count": len(history),
            "data": history,
        }
        return json.dumps(response, indent=2)
    return f"No data found for {indicator_id}"


@mcp.tool()
def fetch_fresh_data(indicator_id: IndicatorOrAll) -> str:
    """Fetch fresh data from FRED API and update database"""
    from src.fetch_data import fetch_and_store_indicator

    if indicator_id == "all":
        indicators = [
            ("GDP", "GDP", 5),
            ("FEDFUNDS", "FEDFUNDS", 10),
            ("UMCSENT", "UMCSENT", 5),
        ]

        results = {}
        for ind_id, series_id, limit in indicators:
            try:
                inserted = fetch_and_store_indicator(ind_id, series_id, limit)
                results[ind_id] = f"{inserted} new records"
            except Exception as e:
                results[ind_id] = f"Error: {str(e)}"
        return json.dumps(results, indent=2)

    try:
        inserted = fetch_and_store_indicator(indicator_id, indicator_id, 10)
        return f"Fetched {inserted} new records for {indicator_id}"
    except Exception as e:
        return f"Error fetching {indicator_id}: {str(e)}"


# ---------------------------------------------------------------------------
# TRANSPORT (how messages arrive). Everything above is identical either way.
#   python mcp_server_v2.py          -> stdio (a host launches this as a subprocess)
#   python mcp_server_v2.py http     -> Streamable HTTP on 127.0.0.1:8765/mcp
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "http":
        mcp.run(transport="streamable-http", host="127.0.0.1", port=8765)
    else:
        mcp.run(transport="stdio")
