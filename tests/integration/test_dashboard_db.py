"""dashboard.data and the dashboard page against a real PostgreSQL server."""
from datetime import date
from html import escape
from pathlib import Path

import pandas as pd
import psycopg2.errors
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from dashboard import data
from src.econ_data.config import INDICATORS

APP = str(Path(__file__).resolve().parents[2] / "dashboard" / "app.py")


def seed_every_indicator(database) -> None:
    for indicator in INDICATORS:
        database.seed(
            indicator.indicator_id,
            {"2026-11-10": 5.0, "2026-11-11": 5.5, "2026-11-12": 6.0},
            fetched_at="2026-11-13 08:00:00",
        )


@pytest.fixture(autouse=True)
def fresh_cache():
    """The page caches its query, so each test starts without what an earlier one stored."""
    st.cache_data.clear()
    yield
    st.cache_data.clear()


# --- read_observations -----------------------------------------------------------


def test_reads_every_row_with_dates_values_and_write_times(database):
    database.seed("DFF", {"2026-11-11": 4.3, "2026-11-12": 4.4}, fetched_at="2026-11-13 08:00:00")
    database.seed("SP500", {"2026-11-12": 6812.34}, fetched_at="2026-11-13 09:30:00")

    table = data.read_observations()

    assert list(table.columns) == data.COLUMNS
    assert list(table["indicator_id"]) == ["DFF", "DFF", "SP500"]
    assert list(table["date"]) == [pd.Timestamp("2026-11-11"), pd.Timestamp("2026-11-12"), pd.Timestamp("2026-11-12")]
    assert list(table["value"]) == [4.3, 4.4, 6812.34]
    assert table["value"].dtype == "float64"
    assert table["fetched_at"].iloc[2] == pd.Timestamp("2026-11-13 09:30:00")


def test_an_empty_database_gives_an_empty_table_with_the_same_columns(database):
    table = data.read_observations()
    assert table.empty
    assert list(table.columns) == data.COLUMNS


def test_the_connection_it_reads_with_refuses_writes(database, monkeypatch):
    write = "INSERT INTO indicator_metadata (indicator_id, name) VALUES ('X', 'X')"
    monkeypatch.setattr(data, "OBSERVATIONS_SQL", write)

    with pytest.raises(psycopg2.errors.ReadOnlySqlTransaction):
        data.read_observations()

    assert database.count("indicator_metadata") == 0


def test_the_figures_read_from_the_database_flow_into_tiles(database):
    database.seed("DFF", {"2026-10-12": 4.4, "2026-11-12": 4.5})
    table = data.read_observations()

    tile = data.make_tile(INDICATORS[0], data.series_for(table, "DFF"))

    assert tile.latest_value == 4.5
    assert tile.change_1m == pytest.approx(0.1)


def test_freshness_counts_what_is_stored(database):
    database.seed("DFF", {"2026-11-10": 4.3, "2026-11-12": 4.4})
    result = data.freshness_table(data.read_observations(), date(2026, 11, 14)).set_index("Indicator")

    assert result.loc["DFF", "Rows"] == 2
    assert result.loc["DFF", "Days behind"] == 2
    assert result.loc["SP500", "Status"] == data.STATUS_EMPTY


# --- the page ----------------------------------------------------------------------


def test_the_page_renders_with_data_and_shows_every_tab(database):
    seed_every_indicator(database)

    app = AppTest.from_file(APP, default_timeout=60).run()

    assert not app.exception
    assert [tab.label for tab in app.tabs] == ["Overview", "Explore", "Data quality", "Guide"]


def test_the_guide_explains_every_indicator_on_the_page(database):
    seed_every_indicator(database)

    app = AppTest.from_file(APP, default_timeout=60).run()

    assert not app.exception
    assert "Reading the ranges" in [heading.value for heading in app.subheader]
    shown = " ".join(markdown.value for markdown in app.markdown)
    assert all(escape(indicator.name) in shown for indicator in INDICATORS)


def test_the_page_says_how_to_load_data_when_the_database_is_empty(database):
    app = AppTest.from_file(APP, default_timeout=60).run()

    assert not app.exception
    assert any("backfill" in info.value for info in app.info)


def test_the_page_reports_an_unreachable_database_instead_of_a_traceback(database, monkeypatch, unused_port):
    monkeypatch.setenv("DB_PORT", str(unused_port))

    app = AppTest.from_file(APP, default_timeout=60).run()

    assert not app.exception
    assert any("Could not read the database" in error.value for error in app.error)
