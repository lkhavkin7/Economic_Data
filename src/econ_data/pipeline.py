"""Pipeline that loads FRED observations into the database.

run_pipeline() writes the indicator definitions from config to the database,
then, for each indicator, fetches its observations from FRED, validates them
and upserts them. An incremental run fetches the latest `lookback`
observations of each indicator; a backfill run fetches its full history. It
returns one RunSummary per indicator. A FRED failure for one indicator is
recorded in its summary and the other indicators still run; a database error
stops the run and rolls it back.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Callable, Sequence

from psycopg2.extras import execute_values

from .config import INDICATORS, Indicator, Settings
from .db import connection
from .fred_client import FredError, Observation, fetch_observations
from .validate import validate_date, validate_value

logger = logging.getLogger(__name__)

MAX_REJECTION_EXAMPLES = 5
UPSERT_PAGE_SIZE = 1000  # rows sent to the database per statement

SYNC_METADATA_SQL = """
INSERT INTO indicator_metadata (indicator_id, name, description, frequency, units, source)
VALUES (%s, %s, %s, %s, %s, %s)
ON CONFLICT (indicator_id) DO UPDATE SET
    name = EXCLUDED.name,
    description = EXCLUDED.description,
    frequency = EXCLUDED.frequency,
    units = EXCLUDED.units,
    source = EXCLUDED.source
"""

SELECT_EXISTING_DATES_SQL = """
SELECT date FROM economic_indicators
WHERE indicator_id = %s AND date = ANY(%s::date[])
"""

# RETURNING lists only the rows that were inserted or changed. A conflicting
# row whose value is the same is skipped by the WHERE and left untouched.
UPSERT_OBSERVATIONS_SQL = """
INSERT INTO economic_indicators (indicator_id, date, value)
VALUES %s
ON CONFLICT (indicator_id, date) DO UPDATE SET
    value = EXCLUDED.value,
    fetched_at = CURRENT_TIMESTAMP
WHERE economic_indicators.value IS DISTINCT FROM EXCLUDED.value
RETURNING date
"""


@dataclass(frozen=True)
class RunSummary:
    """What happened for one indicator in one run.

    For a run that did not fail, fetched = missing + rejected + inserted +
    updated + unchanged.
    """

    indicator_id: str
    fetched: int = 0     # observations FRED returned
    missing: int = 0     # observations FRED had no value for
    rejected: int = 0    # observations that failed validation
    inserted: int = 0    # rows added to the database
    updated: int = 0     # existing rows whose value changed
    unchanged: int = 0   # existing rows that already had the same value
    rejection_examples: tuple[str, ...] = ()
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


@dataclass(frozen=True)
class ValidatedObservations:
    rows: list[tuple[str, float]]  # (date, value) for observations that passed
    missing: int
    rejected: int
    rejection_examples: tuple[str, ...]


def sync_metadata(cur, indicators: Sequence[Indicator] = INDICATORS) -> None:
    """Write each indicator's definition to indicator_metadata.

    An indicator that already has a row is overwritten with the values from
    config. Rows for indicators no longer in config are left alone.
    """
    cur.executemany(
        SYNC_METADATA_SQL,
        [
            (i.indicator_id, i.name, i.description, i.frequency, i.units, i.source)
            for i in indicators
        ],
    )


def validate_observations(
    indicator: Indicator,
    observations: Sequence[Observation],
    today: date | None = None,
) -> ValidatedObservations:
    """Split observations into rows that pass validation and counts of the rest.

    An observation with no value is counted as missing. One whose date or
    value fails validation is counted as rejected, and the first few reasons
    are kept. The order of the passing rows follows the input.
    """
    rows: list[tuple[str, float]] = []
    rejections: list[str] = []
    missing = 0

    for obs in observations:
        if obs.value is None:
            missing += 1
            continue

        valid, message = validate_date(obs.date, today)
        if valid:
            valid, message = validate_value(indicator.indicator_id, obs.value)
        if not valid:
            rejections.append(f"{obs.date}: {message}")
            continue

        rows.append((obs.date, obs.value))

    return ValidatedObservations(
        rows=rows,
        missing=missing,
        rejected=len(rejections),
        rejection_examples=tuple(rejections[:MAX_REJECTION_EXAMPLES]),
    )


def upsert_observations(
    cur, indicator_id: str, rows: Sequence[tuple[str, float]]
) -> tuple[int, int]:
    """Insert new observations and update ones whose value changed.

    Returns (inserted, updated). Rows that already hold the same value are
    not touched, so fetched_at only changes when the value does. The
    indicator must already have a row in indicator_metadata.
    """
    if not rows:
        return 0, 0

    cur.execute(SELECT_EXISTING_DATES_SQL, (indicator_id, [d for d, _ in rows]))
    existing = {row[0].isoformat() for row in cur.fetchall()}

    written = execute_values(
        cur,
        UPSERT_OBSERVATIONS_SQL,
        [(indicator_id, d, v) for d, v in rows],
        page_size=UPSERT_PAGE_SIZE,
        fetch=True,
    )
    written_dates = {row[0].isoformat() for row in written}

    return len(written_dates - existing), len(written_dates & existing)


def run_indicator(
    cur,
    indicator: Indicator,
    settings: Settings,
    fetch: Callable = fetch_observations,
    today: date | None = None,
    backfill: bool = False,
) -> RunSummary:
    """Fetch, validate and upsert the observations for one indicator.

    Requests indicator.lookback observations, or the full history if
    `backfill` is true. A FredError, or a response with no observations, is
    returned as a summary with `error` set. Database errors are not caught.
    """
    indicator_id = indicator.indicator_id
    limit = None if backfill else indicator.lookback

    try:
        observations = fetch(indicator, limit, settings)
    except FredError as exc:
        return _failed(indicator_id, str(exc))
    if not observations:
        return _failed(indicator_id, f"{indicator_id}: FRED returned no observations")

    checked = validate_observations(indicator, observations, today)
    inserted, updated = upsert_observations(cur, indicator_id, checked.rows)

    summary = RunSummary(
        indicator_id=indicator_id,
        fetched=len(observations),
        missing=checked.missing,
        rejected=checked.rejected,
        inserted=inserted,
        updated=updated,
        unchanged=len(checked.rows) - inserted - updated,
        rejection_examples=checked.rejection_examples,
    )
    logger.info(
        "%s: fetched=%d inserted=%d updated=%d unchanged=%d missing=%d rejected=%d",
        indicator_id,
        summary.fetched,
        summary.inserted,
        summary.updated,
        summary.unchanged,
        summary.missing,
        summary.rejected,
    )
    if summary.rejected:
        logger.warning(
            "%s: rejected %d observations, for example: %s",
            indicator_id,
            summary.rejected,
            "; ".join(summary.rejection_examples),
        )
    return summary


def run_pipeline(
    settings: Settings | None = None,
    indicators: Sequence[Indicator] = INDICATORS,
    fetch: Callable = fetch_observations,
    today: date | None = None,
    backfill: bool = False,
) -> list[RunSummary]:
    """Run every indicator in one database transaction and return the summaries.

    `backfill` fetches each indicator's full history instead of its latest
    observations.

    The transaction commits when all indicators have been processed. If a
    database error is raised, everything written during the run is rolled
    back and the error is re-raised.
    """
    settings = Settings() if settings is None else settings

    with connection(settings) as conn:
        with conn.cursor() as cur:
            sync_metadata(cur, indicators)
            return [run_indicator(cur, i, settings, fetch, today, backfill) for i in indicators]


def _failed(indicator_id: str, message: str) -> RunSummary:
    logger.error("%s", message)
    return RunSummary(indicator_id=indicator_id, error=message)
