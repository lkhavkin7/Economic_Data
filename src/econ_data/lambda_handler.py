"""AWS Lambda entry point.

lambda_handler() runs the mode named by the "mode" key of the event:

    fetch   (default) run the pipeline for every indicator in config
    verify  report the row count and latest date stored for each indicator
    setup   create the database if it is missing, then apply db/schema.sql

Each mode is its own function, so it can be called and tested without Lambda.
A fetch run in which any indicator failed raises PipelineError after all
indicators have been processed, so Lambda records the invocation as failed.
"""
from __future__ import annotations

import logging
from dataclasses import asdict
from pathlib import Path

from psycopg2 import sql

from .config import Settings
from .db import connect, connection
from .pipeline import run_pipeline

logger = logging.getLogger(__name__)

SCHEMA_PATH = Path(__file__).resolve().parents[2] / "db" / "schema.sql"
MAINTENANCE_DB = "postgres"  # always exists; the only place CREATE DATABASE can run from
MODES = ("fetch", "verify", "setup")

VERIFY_SQL = """
SELECT indicator_id, COUNT(*), MAX(date)
FROM economic_indicators
GROUP BY indicator_id
ORDER BY indicator_id
"""


class PipelineError(Exception):
    """A fetch run finished but one or more indicators failed."""


def fetch_all(settings: Settings) -> dict:
    """Run the pipeline and return one summary per indicator.

    Raises PipelineError, naming the failed indicators, if any indicator
    failed. The indicators that succeeded have already been committed.
    """
    summaries = run_pipeline(settings)

    failed = [s for s in summaries if not s.ok]

    inserted = sum(s.inserted for s in summaries)
    updated = sum(s.updated for s in summaries)

    # One line per run, logged before any failure is raised, so a run in which some
    # indicators failed still reports its totals.
    logger.info(
        "run complete: %d indicators, %d failed, %d rows inserted, %d updated",
        len(summaries),
        len(failed),
        inserted,
        updated,
        extra={
            "event": "run_summary",
            "indicators": len(summaries),
            "failed": len(failed),
            "inserted": inserted,
            "updated": updated,
            "rows_written": inserted + updated,
        },
    )

    if failed:
        details = "; ".join(s.error for s in failed)
        raise PipelineError(f"{len(failed)} of {len(summaries)} indicators failed ({details})")

    return {"mode": "fetch", "summaries": [asdict(s) for s in summaries]}


def verify_database(settings: Settings) -> dict:
    """Return the row count and latest date stored for each indicator."""
    with connection(settings) as conn:
        with conn.cursor() as cur:
            cur.execute(VERIFY_SQL)
            rows = cur.fetchall()

    return {
        "mode": "verify",
        "rows": [
            {
                "indicator_id": indicator_id,
                "count": count,
                "max_date": latest.isoformat() if latest else None,
            }
            for indicator_id, count, latest in rows
        ],
    }


def setup_database(settings: Settings, schema_path: Path = SCHEMA_PATH) -> dict:
    """Create the database if it is missing, then apply the schema file to it.

    The schema file is read first, so a missing file fails before anything in
    the database server has changed. The schema file must be safe to apply
    repeatedly.
    """
    schema_sql = schema_path.read_text(encoding="utf-8")
    created = _create_database_if_missing(settings)

    with connection(settings) as conn:
        with conn.cursor() as cur:
            cur.execute(schema_sql)

    logger.info("setup: database=%s created=%s schema applied", settings.db_name, created)
    return {
        "mode": "setup",
        "database": settings.db_name,
        "created": created,
        "schema_applied": True,
    }


def lambda_handler(event, context):
    """Run the mode named in the event and return its result."""
    # Lambda's logger starts at WARNING, which would hide the per-indicator info lines.
    logging.getLogger().setLevel(logging.INFO)

    mode = (event or {}).get("mode", "fetch")
    if mode not in MODES:
        raise ValueError(f"Unknown mode {mode!r}. Use one of: {', '.join(MODES)}")

    settings = Settings()
    if mode == "verify":
        return verify_database(settings)
    if mode == "setup":
        return setup_database(settings)
    return fetch_all(settings)


def _create_database_if_missing(settings: Settings) -> bool:
    """Create settings.db_name if it does not exist. Return True if it was created."""
    maintenance = settings.model_copy(update={"db_name": MAINTENANCE_DB})
    conn = connect(maintenance)
    try:
        # CREATE DATABASE cannot run inside a transaction block.
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (settings.db_name,))
            if cur.fetchone() is not None:
                return False
            # A database name is an identifier, not a value, so it cannot be a %s parameter.
            cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(settings.db_name)))
            return True
    finally:
        conn.close()
