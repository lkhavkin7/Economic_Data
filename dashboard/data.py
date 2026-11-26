"""What the dashboard shows, worked out from the stored observations.

read_observations() is the only function here that touches the database. It
returns one table with every stored row. Every other function takes that table
(or one series cut from it) and returns plain values, so the logic can be tested
without a database and without Streamlit.

An observation table has the columns indicator_id, date, value and fetched_at.
A series is the values of one indicator, oldest first, indexed by date.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd

from src.econ_data.config import INDICATORS_BY_ID, Indicator, Settings
from src.econ_data.db import connection

OBSERVATIONS_SQL = """
SELECT indicator_id, date, value, fetched_at
FROM economic_indicators
ORDER BY indicator_id, date
"""

COLUMNS = ["indicator_id", "date", "value", "fetched_at"]

# The date ranges the dashboard offers, and how many months back each one reaches.
# "Max" has no start: it shows everything.
RANGE_MONTHS = {"1M": 1, "6M": 6, "1Y": 12, "5Y": 60}
RANGE_LABELS = (*RANGE_MONTHS, "Max")

# A series is stale when its latest observation is older than this many days.
# A monthly value is dated the first of its month and published in the first days of
# the next month, so the newest one is normally up to about 62 days behind just before
# the following month's value arrives. Every frequency in config needs an entry.
STALE_AFTER_DAYS = {"daily": 7, "monthly": 65}

# The indicators whose latest value is also shown as a percentile of their history.
# A percentile only means something for a series that returns to a usual range. An
# index that trends upward, like the S&P 500, would sit near the top almost always.
PERCENTILE_INDICATORS = ("VIXCLS",)

# The older of the two observations in a change may be at most this many days before
# the date it stands for. Past that the series has a gap, and the change would be
# measured against a value from a different period.
MAX_GAP_DAYS = 45

RECENT_WRITES_LIMIT = 15

STATUS_CURRENT = "✓ Current"
STATUS_STALE = "! Stale"
STATUS_EMPTY = "– No data"


@dataclass(frozen=True)
class Tile:
    """The figures for one indicator's tile."""

    indicator_id: str
    name: str
    units: str  # "percent" or "index", as in config
    first_date: date  # the oldest stored observation, which a percentile is measured since
    latest_date: date
    latest_value: float
    change_1m: float | None  # None when the series has no observation that far back
    change_1y: float | None
    change_unit: str  # "pp" (percentage points) or "%"
    percentile: float | None  # 0 to 100, only for PERCENTILE_INDICATORS


# --- reading -------------------------------------------------------------------


def read_observations(settings: Settings | None = None) -> pd.DataFrame:
    """Read every stored observation, oldest first within each indicator."""
    with connection(settings) as conn:
        # Refuses any write on this connection, so the dashboard cannot change data by accident.
        conn.set_session(readonly=True)
        with conn.cursor() as cur:
            cur.execute(OBSERVATIONS_SQL)
            rows = cur.fetchall()

    table = pd.DataFrame(rows, columns=COLUMNS)
    table["date"] = pd.to_datetime(table["date"])
    table["value"] = table["value"].astype(float)  # the database returns exact decimals
    table["fetched_at"] = pd.to_datetime(table["fetched_at"])
    return table


def series_for(observations: pd.DataFrame, indicator_id: str) -> pd.Series:
    """The values of one indicator, oldest first, indexed by date."""
    rows = observations[observations["indicator_id"] == indicator_id]
    return rows.set_index("date")["value"].sort_index()


# --- tiles ---------------------------------------------------------------------


def value_on_or_before(series: pd.Series, target: pd.Timestamp) -> float | None:
    """The last value dated on or before target, or None if there is none or it is too old."""
    earlier = series.loc[:target]
    if earlier.empty:
        return None
    if (target - earlier.index[-1]).days > MAX_GAP_DAYS:
        return None
    return float(earlier.iloc[-1])


def change(latest: float, previous: float | None, units: str) -> float | None:
    """How far latest has moved from previous.

    Rates move by a difference, in percentage points, because a rise from 4% to 5%
    is one point, not twenty-five percent. Index levels move by a percent change.
    """
    if previous is None:
        return None
    if units == "percent":
        return latest - previous
    if previous == 0:
        return None
    return (latest / previous - 1) * 100


def percentile_rank(series: pd.Series, value: float) -> float:
    """The share of the series' values that are at or below value, from 0 to 100."""
    return float((series <= value).mean() * 100)


def make_tile(indicator: Indicator, series: pd.Series) -> Tile | None:
    """The tile for one indicator, or None if it has no stored values."""
    if series.empty:
        return None

    latest_date = series.index[-1]
    latest = float(series.iloc[-1])
    month_ago = value_on_or_before(series, latest_date - pd.DateOffset(months=1))
    year_ago = value_on_or_before(series, latest_date - pd.DateOffset(years=1))

    return Tile(
        indicator_id=indicator.indicator_id,
        name=indicator.name,
        units=indicator.units,
        first_date=series.index[0].date(),
        latest_date=latest_date.date(),
        latest_value=latest,
        change_1m=change(latest, month_ago, indicator.units),
        change_1y=change(latest, year_ago, indicator.units),
        change_unit="pp" if indicator.units == "percent" else "%",
        percentile=percentile_rank(series, latest) if indicator.indicator_id in PERCENTILE_INDICATORS else None,
    )


# --- date ranges ---------------------------------------------------------------


def latest_date(observations: pd.DataFrame) -> pd.Timestamp | None:
    """The newest observation date of any indicator, or None for an empty table."""
    return None if observations.empty else observations["date"].max()


def range_start(latest: pd.Timestamp, label: str) -> pd.Timestamp | None:
    """The first date a range label shows, counting back from latest. None means no limit."""
    if label not in RANGE_LABELS:
        raise ValueError(f"Unknown range {label!r}. Use one of: {', '.join(RANGE_LABELS)}")
    if label == "Max":
        return None
    return latest - pd.DateOffset(months=RANGE_MONTHS[label])


def slice_series(series: pd.Series, start: pd.Timestamp | None) -> pd.Series:
    """The part of a series from start onward. A start of None keeps all of it."""
    return series if start is None else series.loc[start:]


# --- data quality --------------------------------------------------------------


def freshness_table(observations: pd.DataFrame, today: date) -> pd.DataFrame:
    """One row per indicator in config: how much is stored, how recent it is, and whether it is stale.

    Indicators with nothing stored are listed too, with the status "No data".
    """
    today_stamp = pd.Timestamp(today)
    rows = []
    for indicator in INDICATORS_BY_ID.values():
        mine = observations[observations["indicator_id"] == indicator.indicator_id]
        row = {
            "Indicator": indicator.indicator_id,
            "Frequency": indicator.frequency,
            "Rows": len(mine),
            "First date": None,
            "Latest date": None,
            "Days behind": None,
            "Last written": None,
            "Status": STATUS_EMPTY,
        }
        if not mine.empty:
            latest = mine["date"].max()
            days_behind = (today_stamp - latest).days
            row["First date"] = mine["date"].min().date()
            row["Latest date"] = latest.date()
            row["Days behind"] = days_behind
            row["Last written"] = mine["fetched_at"].max()
            row["Status"] = STATUS_STALE if days_behind > STALE_AFTER_DAYS[indicator.frequency] else STATUS_CURRENT
        rows.append(row)
    return pd.DataFrame(rows)


def recent_writes(observations: pd.DataFrame, limit: int = RECENT_WRITES_LIMIT) -> pd.DataFrame:
    """The rows written most recently, newest first.

    A row is written when it is new or its value changed, so these are the rows the
    latest runs added or revised. Rows written in one run share a timestamp and are
    then listed newest observation date first.
    """
    newest = observations.sort_values(
        ["fetched_at", "date", "indicator_id"], ascending=[False, False, True]
    ).head(limit)
    return pd.DataFrame(
        {
            "Indicator": newest["indicator_id"],
            "Date": newest["date"].dt.date,
            "Value": newest["value"],
            "Written": newest["fetched_at"],
        }
    ).reset_index(drop=True)
