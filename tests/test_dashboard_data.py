"""dashboard.data logic that needs no database: tile figures, date ranges and the data-quality tables.

read_observations is tested in tests/integration/test_dashboard_db against a real PostgreSQL server.
"""
from datetime import date, datetime

import pandas as pd
import pytest

from dashboard import data
from src.econ_data.config import INDICATORS, INDICATORS_BY_ID

WRITTEN = datetime(2026, 11, 20, 9, 0)


def series(points: dict[str, float]) -> pd.Series:
    """A series from a dict of "YYYY-MM-DD" to value."""
    return pd.Series(list(points.values()), index=pd.to_datetime(list(points))).sort_index()


def observations(rows: list[tuple]) -> pd.DataFrame:
    """An observation table from (indicator_id, "YYYY-MM-DD", value[, fetched_at]) tuples."""
    full = [(r[0], r[1], r[2], r[3] if len(r) > 3 else WRITTEN) for r in rows]
    table = pd.DataFrame(full, columns=data.COLUMNS)
    table["date"] = pd.to_datetime(table["date"])
    table["fetched_at"] = pd.to_datetime(table["fetched_at"])
    return table


# --- series_for ------------------------------------------------------------------


def test_series_for_returns_one_indicator_oldest_first():
    table = observations([("DFF", "2026-11-12", 4.3), ("SP500", "2026-11-12", 6000.0), ("DFF", "2026-11-11", 4.2)])
    result = data.series_for(table, "DFF")
    assert list(result.index.strftime("%Y-%m-%d")) == ["2026-11-11", "2026-11-12"]
    assert list(result) == [4.2, 4.3]


def test_series_for_an_indicator_with_no_rows_is_empty():
    assert data.series_for(observations([("DFF", "2026-11-12", 4.3)]), "VIXCLS").empty


# --- value_on_or_before ----------------------------------------------------------


def test_value_on_or_before_uses_the_exact_date_when_there_is_one():
    s = series({"2026-10-01": 1.0, "2026-10-15": 2.0, "2026-11-01": 3.0})
    assert data.value_on_or_before(s, pd.Timestamp("2026-10-15")) == 2.0


def test_value_on_or_before_falls_back_to_the_last_earlier_date():
    s = series({"2026-10-01": 1.0, "2026-10-15": 2.0, "2026-11-01": 3.0})
    assert data.value_on_or_before(s, pd.Timestamp("2026-10-20")) == 2.0


def test_value_on_or_before_is_none_before_the_series_starts():
    assert data.value_on_or_before(series({"2026-10-01": 1.0}), pd.Timestamp("2026-09-01")) is None


def test_value_on_or_before_is_none_across_a_long_gap():
    s = series({"2026-01-02": 1.0})
    assert data.value_on_or_before(s, pd.Timestamp("2026-01-02") + pd.Timedelta(days=data.MAX_GAP_DAYS)) == 1.0
    assert data.value_on_or_before(s, pd.Timestamp("2026-01-02") + pd.Timedelta(days=data.MAX_GAP_DAYS + 1)) is None


# --- change ----------------------------------------------------------------------


def test_a_rate_changes_by_a_difference_in_percentage_points():
    assert data.change(5.0, 4.0, "percent") == pytest.approx(1.0)


def test_an_index_changes_by_a_percent():
    assert data.change(110.0, 100.0, "index") == pytest.approx(10.0)


def test_a_change_from_nothing_is_none():
    assert data.change(5.0, None, "percent") is None


def test_a_percent_change_from_zero_is_none():
    assert data.change(5.0, 0.0, "index") is None


# --- percentile_rank -------------------------------------------------------------


def test_percentile_rank_is_the_share_of_values_at_or_below():
    assert data.percentile_rank(series({"2026-01-01": 1, "2026-01-02": 2, "2026-01-03": 3, "2026-01-04": 4}), 3) == 75.0


# --- make_tile -------------------------------------------------------------------


def test_tile_reports_the_latest_value_and_changes_against_one_month_and_one_year_back():
    s = series({"2025-11-12": 4.0, "2026-10-12": 4.4, "2026-11-12": 4.5})
    tile = data.make_tile(INDICATORS_BY_ID["DFF"], s)

    assert (tile.first_date, tile.latest_date, tile.latest_value) == (date(2025, 11, 12), date(2026, 11, 12), 4.5)
    assert tile.change_1m == pytest.approx(0.1)
    assert tile.change_1y == pytest.approx(0.5)
    assert tile.change_unit == "pp"
    assert tile.percentile is None


def test_an_index_tile_reports_percent_changes():
    s = series({"2025-11-12": 5000.0, "2026-10-12": 5500.0, "2026-11-12": 6000.0})
    tile = data.make_tile(INDICATORS_BY_ID["SP500"], s)

    assert tile.change_1m == pytest.approx(9.0909, abs=1e-3)
    assert tile.change_1y == pytest.approx(20.0)
    assert tile.change_unit == "%"


def test_a_monthly_series_compares_against_the_previous_month():
    s = series({"2025-10-01": 4.0, "2026-09-01": 4.1, "2026-10-01": 4.2})
    tile = data.make_tile(INDICATORS_BY_ID["FEDFUNDS"], s)

    assert tile.change_1m == pytest.approx(0.1)
    assert tile.change_1y == pytest.approx(0.2)


def test_a_short_series_has_no_changes_instead_of_wrong_ones():
    tile = data.make_tile(INDICATORS_BY_ID["DFF"], series({"2026-11-12": 4.5}))
    assert (tile.change_1m, tile.change_1y) == (None, None)


def test_an_empty_series_has_no_tile():
    assert data.make_tile(INDICATORS_BY_ID["DFF"], series({})) is None


def test_only_vix_gets_a_percentile():
    history = {f"2026-01-{day:02d}": float(day) for day in range(1, 11)}
    assert data.make_tile(INDICATORS_BY_ID["VIXCLS"], series(history)).percentile == 100.0
    assert data.make_tile(INDICATORS_BY_ID["SP500"], series(history)).percentile is None


# --- date ranges -----------------------------------------------------------------


@pytest.mark.parametrize(
    "label, expected",
    [("1M", "2026-10-12"), ("6M", "2026-05-12"), ("1Y", "2025-11-12"), ("5Y", "2021-11-12"), ("Max", None)],
)
def test_range_start_counts_back_from_the_latest_date(label, expected):
    start = data.range_start(pd.Timestamp("2026-11-12"), label)
    assert (None if start is None else start.strftime("%Y-%m-%d")) == expected


def test_unknown_range_is_an_error():
    with pytest.raises(ValueError, match="Unknown range '2Y'.*1M, 6M, 1Y, 5Y, Max"):
        data.range_start(pd.Timestamp("2026-11-12"), "2Y")


def test_slice_series_keeps_everything_from_the_start_date():
    s = series({"2026-01-01": 1.0, "2026-06-01": 2.0, "2026-11-01": 3.0})
    assert list(data.slice_series(s, pd.Timestamp("2026-06-01"))) == [2.0, 3.0]
    assert list(data.slice_series(s, None)) == [1.0, 2.0, 3.0]


def test_latest_date_is_the_newest_of_every_indicator():
    table = observations([("DFF", "2026-11-12", 4.3), ("SP500", "2026-11-13", 6000.0)])
    assert data.latest_date(table) == pd.Timestamp("2026-11-13")
    assert data.latest_date(observations([])) is None


# --- freshness_table ---------------------------------------------------------------


def test_every_frequency_in_config_has_a_staleness_limit():
    assert {i.frequency for i in INDICATORS} <= set(data.STALE_AFTER_DAYS)


def test_freshness_lists_every_indicator_in_config_even_with_no_data():
    table = data.freshness_table(observations([]), date(2026, 11, 24))
    assert list(table["Indicator"]) == [i.indicator_id for i in INDICATORS]
    assert set(table["Status"]) == {data.STATUS_EMPTY}
    assert set(table["Rows"]) == {0}


def test_freshness_reports_rows_dates_and_last_write():
    table = observations(
        [
            ("DFF", "2026-11-18", 4.3, datetime(2026, 11, 19, 8, 0)),
            ("DFF", "2026-11-20", 4.4, datetime(2026, 11, 21, 8, 0)),
        ]
    )
    row = data.freshness_table(table, date(2026, 11, 24)).set_index("Indicator").loc["DFF"]

    assert row["Rows"] == 2
    assert (row["First date"], row["Latest date"]) == (date(2026, 11, 18), date(2026, 11, 20))
    assert row["Days behind"] == 4
    assert row["Last written"] == pd.Timestamp("2026-11-21 08:00")
    assert row["Status"] == data.STATUS_CURRENT


def test_a_daily_series_is_stale_after_its_limit_but_a_monthly_one_is_not():
    # Both were last observed 30 days before today.
    table = observations([("DFF", "2026-10-25", 4.3), ("FEDFUNDS", "2026-10-25", 4.1)])
    result = data.freshness_table(table, date(2026, 11, 24)).set_index("Indicator")

    assert result.loc["DFF", "Status"] == data.STATUS_STALE
    assert result.loc["FEDFUNDS", "Status"] == data.STATUS_CURRENT


def test_a_monthly_value_is_current_until_the_next_one_is_due():
    # October's value is dated Oct 1. On Dec 2 November's has just been published, so it still counts as current.
    table = observations([("FEDFUNDS", "2026-10-01", 4.1)])
    assert data.freshness_table(table, date(2026, 12, 2)).set_index("Indicator").loc["FEDFUNDS", "Status"] == (
        data.STATUS_CURRENT
    )
    assert data.freshness_table(table, date(2026, 12, 8)).set_index("Indicator").loc["FEDFUNDS", "Status"] == (
        data.STATUS_STALE
    )


def test_a_series_exactly_at_its_limit_is_still_current():
    day = pd.Timestamp("2026-11-24") - pd.Timedelta(days=data.STALE_AFTER_DAYS["daily"])
    table = observations([("DFF", day.strftime("%Y-%m-%d"), 4.3)])
    result = data.freshness_table(table, date(2026, 11, 24)).set_index("Indicator")
    assert result.loc["DFF", "Status"] == data.STATUS_CURRENT


# --- recent_writes -----------------------------------------------------------------


def test_recent_writes_lists_the_newest_writes_first_and_respects_the_limit():
    table = observations(
        [
            ("DFF", "2026-11-10", 4.1, datetime(2026, 11, 11, 8, 0)),
            ("DFF", "2026-11-11", 4.2, datetime(2026, 11, 12, 8, 0)),
            ("DFF", "2026-11-12", 4.3, datetime(2026, 11, 13, 8, 0)),
        ]
    )
    result = data.recent_writes(table, limit=2)

    assert list(result["Date"]) == [date(2026, 11, 12), date(2026, 11, 11)]
    assert list(result.columns) == ["Indicator", "Date", "Value", "Written"]


def test_rows_written_together_are_ordered_by_newest_date_then_indicator():
    table = observations(
        [("VIXCLS", "2026-11-12", 15.0), ("DFF", "2026-11-12", 4.3), ("DFF", "2026-11-11", 4.2)]
    )
    result = data.recent_writes(table)

    assert list(zip(result["Indicator"], result["Date"])) == [
        ("DFF", date(2026, 11, 12)),
        ("VIXCLS", date(2026, 11, 12)),
        ("DFF", date(2026, 11, 11)),
    ]


# --- read_observations: what it asks the database for -----------------------------


class FakeCursor:
    def __init__(self, calls, rows):
        self.calls, self.rows = calls, rows

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, query):
        self.calls.append(("execute", query))

    def fetchall(self):
        return self.rows


class FakeConnection:
    def __init__(self, rows):
        self.calls = []
        self.rows = rows

    def set_session(self, **kwargs):
        self.calls.append(("set_session", kwargs))

    def cursor(self):
        return FakeCursor(self.calls, self.rows)


def test_the_connection_is_made_read_only_before_the_query_runs(monkeypatch):
    from contextlib import contextmanager

    fake = FakeConnection([])

    @contextmanager
    def fake_connection(settings):
        yield fake

    monkeypatch.setattr(data, "connection", fake_connection)
    result = data.read_observations()

    assert fake.calls[0] == ("set_session", {"readonly": True})
    assert fake.calls[1] == ("execute", data.OBSERVATIONS_SQL)
    assert list(result.columns) == data.COLUMNS
    assert result.empty
