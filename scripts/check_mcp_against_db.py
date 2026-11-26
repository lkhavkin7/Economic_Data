"""Check that the MCP server returns what is stored in the database.

Starts the real server as a subprocess, the way an MCP host does, calls its
tools and reads its resources over stdio, and compares each answer with the same
rows read straight from PostgreSQL. The comparison uses its own SQL, so a bug in
the server's queries cannot make both sides agree on a wrong answer.

For every indicator in config it checks:
    get_latest_indicator    against the newest row
    get_indicator_history   against the newest HISTORY_LIMIT rows
    fred://series/{id}      against the newest SERIES_LIMIT rows
    fred://catalog          against the row count and latest date

Run from the repository root, with the database up and filled:
    python -m scripts.check_mcp_against_db

Exit code 0 means every check matched. 1 means a mismatch, or an empty database.
"""
from __future__ import annotations

import asyncio
import json
import sys
from decimal import Decimal
from pathlib import Path

import psycopg2
from mcp import Client, StdioServerParameters

from src.econ_data.config import INDICATORS, Settings
from src.econ_data.db import get_credentials

REPO_ROOT = Path(__file__).resolve().parents[1]

HISTORY_LIMIT = 10   # the limit passed to get_indicator_history
SERIES_LIMIT = 100   # how many rows fred://series/{id} is documented to return

CHECKS = ("latest", "history", "series", "catalog")

ROWS_SQL = """
SELECT date, value, fetched_at
FROM economic_indicators
WHERE indicator_id = %s
ORDER BY date DESC
LIMIT %s
"""

SUMMARY_SQL = """
SELECT COUNT(*), MAX(date)
FROM economic_indicators
WHERE indicator_id = %s
"""


def server_parameters(settings: Settings) -> StdioServerParameters:
    """How to launch the server: the same command a host would run, on the same database.

    The client gives the subprocess only a minimal environment, so the database
    settings are passed explicitly instead of being inherited.
    """
    user, password = get_credentials(settings)
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "src.econ_data.mcp_server"],
        cwd=str(REPO_ROOT),
        env={
            "DB_HOST": settings.db_host,
            "DB_PORT": str(settings.db_port),
            "DB_NAME": settings.db_name,
            "DB_USER": user,
            "DB_PASSWORD": password,
        },
    )


def read_database(settings: Settings) -> dict[str, dict]:
    """Read, for each indicator, its newest rows, its row count and its latest date."""
    user, password = get_credentials(settings)
    conn = psycopg2.connect(
        host=settings.db_host,
        port=settings.db_port,
        dbname=settings.db_name,
        user=user,
        password=password,
        connect_timeout=10,
    )
    try:
        with conn.cursor() as cur:
            expected = {}
            for indicator in INDICATORS:
                cur.execute(ROWS_SQL, (indicator.indicator_id, SERIES_LIMIT))
                rows = cur.fetchall()
                cur.execute(SUMMARY_SQL, (indicator.indicator_id,))
                count, latest = cur.fetchone()
                expected[indicator.indicator_id] = {"rows": rows, "count": count, "latest": latest}
            return expected
    finally:
        conn.close()


def compare_rows(served: list[dict], stored: list[tuple]) -> str | None:
    """Return None if the served rows equal the stored rows, else a description of the first difference.

    Both are newest first. A served value is a JSON number, so it is converted back
    through its text form to compare exactly with the stored DECIMAL.
    """
    if len(served) != len(stored):
        return f"server returned {len(served)} rows, database has {len(stored)}"
    for position, (row, (date, value, _fetched_at)) in enumerate(zip(served, stored)):
        if row["date"] != str(date):
            return f"row {position}: server date {row['date']}, database date {date}"
        if Decimal(str(row["value"])) != value:
            return f"row {position} ({date}): server value {row['value']}, database value {value}"
    return None


def text_of_tool(result) -> str:
    """The text a tool call returned, or an error if the call itself failed."""
    if result.is_error:
        raise RuntimeError(result.content[0].text)
    return result.content[0].text


def check_latest(served_text: str, indicator_id: str, stored: dict) -> str | None:
    if not stored["rows"]:
        expected = f"No data found for {indicator_id}"
        return None if served_text == expected else f"expected {expected!r}, server said {served_text!r}"

    served = json.loads(served_text)
    date, value, fetched_at = stored["rows"][0]
    if served["date"] != str(date):
        return f"server date {served['date']}, database date {date}"
    if Decimal(str(served["value"])) != value:
        return f"server value {served['value']}, database value {value}"
    if served["fetched_at"] != str(fetched_at):
        return f"server fetched_at {served['fetched_at']}, database fetched_at {fetched_at}"
    return None


def check_history(served_text: str, indicator_id: str, stored: dict) -> str | None:
    rows = stored["rows"][:HISTORY_LIMIT]
    if not rows:
        expected = f"No data found for {indicator_id}"
        return None if served_text == expected else f"expected {expected!r}, server said {served_text!r}"

    served = json.loads(served_text)
    if served["count"] != len(served["data"]):
        return f"count says {served['count']} but data has {len(served['data'])} rows"
    return compare_rows(served["data"], rows)


def check_series(served_text: str, stored: dict) -> str | None:
    served = json.loads(served_text)
    if served["count"] != len(served["data"]):
        return f"count says {served['count']} but data has {len(served['data'])} rows"
    return compare_rows(served["data"], stored["rows"][:SERIES_LIMIT])


def check_catalog(entry: dict | None, stored: dict) -> str | None:
    if entry is None:
        return "indicator is missing from the catalog"
    if entry["count"] != stored["count"]:
        return f"catalog count {entry['count']}, database count {stored['count']}"
    latest = stored["latest"].isoformat() if stored["latest"] else None
    if entry["latest_date"] != latest:
        return f"catalog latest_date {entry['latest_date']}, database latest date {latest}"
    return None


async def run_checks(settings: Settings, expected: dict[str, dict]) -> dict[str, dict[str, str | None]]:
    """Call the server for every indicator. Return {indicator: {check: None or a problem}}."""
    problems: dict[str, dict[str, str | None]] = {}

    async with Client(server_parameters(settings)) as client:
        catalog = json.loads((await client.read_resource("fred://catalog")).contents[0].text)
        catalog_by_id = {entry["indicator_id"]: entry for entry in catalog["indicators"]}

        for indicator in INDICATORS:
            indicator_id = indicator.indicator_id
            stored = expected[indicator_id]

            latest = await client.call_tool("get_latest_indicator", {"indicator_id": indicator_id})
            history = await client.call_tool(
                "get_indicator_history", {"indicator_id": indicator_id, "limit": HISTORY_LIMIT}
            )
            series = await client.read_resource(f"fred://series/{indicator_id}")

            problems[indicator_id] = {
                "latest": check_latest(text_of_tool(latest), indicator_id, stored),
                "history": check_history(text_of_tool(history), indicator_id, stored),
                "series": check_series(series.contents[0].text, stored),
                "catalog": check_catalog(catalog_by_id.get(indicator_id), stored),
            }

    return problems


def print_report(expected: dict[str, dict], problems: dict[str, dict[str, str | None]]) -> int:
    """Print a table and the details of every mismatch. Return the number of failed checks."""
    print(f"{'indicator':<10} {'rows':>6}  " + "  ".join(f"{name:<8}" for name in CHECKS))
    failed = []
    for indicator_id, results in problems.items():
        cells = []
        for name in CHECKS:
            cells.append(f"{'ok' if results[name] is None else 'MISMATCH':<8}")
            if results[name] is not None:
                failed.append((indicator_id, name, results[name]))
        print(f"{indicator_id:<10} {expected[indicator_id]['count']:>6}  " + "  ".join(cells))

    print()
    if failed:
        for indicator_id, name, problem in failed:
            print(f"  {indicator_id} {name}: {problem}")
        print(f"\n{len(failed)} of {len(problems) * len(CHECKS)} checks did not match.")
    else:
        print(f"All {len(problems) * len(CHECKS)} checks matched: the server returns what the database holds.")
    return len(failed)


def main() -> int:
    settings = Settings()
    expected = read_database(settings)

    if all(entry["count"] == 0 for entry in expected.values()):
        print(f"Database {settings.db_name} has no rows, so there is nothing to compare. Run a backfill first.")
        return 1

    problems = asyncio.run(run_checks(settings, expected))
    return 1 if print_report(expected, problems) else 0


if __name__ == "__main__":
    sys.exit(main())
