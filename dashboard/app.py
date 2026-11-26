"""The Economic Data dashboard: a read-only view of what the pipeline has stored.

Run it from the repository root, with the database up:
    python -m streamlit run dashboard/app.py

Streamlit runs this whole script again on every click. The query is cached, so a
click does not open a new database connection or read the tables again.
"""
from __future__ import annotations

from datetime import date

import pandas as pd
import psycopg2
import streamlit as st

from dashboard import charts, data, guide, tiles
from src.econ_data.config import INDICATORS, INDICATORS_BY_ID

CACHE_SECONDS = 60
DEFAULT_RANGE = "1Y"
PLOT_CONFIG = {"displaylogo": False}

st.set_page_config(page_title="Economic data", page_icon="📈", layout="wide")
st.markdown(tiles.TILE_CSS, unsafe_allow_html=True)


@st.cache_data(ttl=CACHE_SECONDS, show_spinner="Reading the database")
def load_observations() -> pd.DataFrame:
    return data.read_observations()


def show_overview(observations: pd.DataFrame, latest: pd.Timestamp) -> None:
    columns = st.columns(3)
    for position, indicator in enumerate(INDICATORS):
        tile = data.make_tile(indicator, data.series_for(observations, indicator.indicator_id))
        with columns[position % 3]:
            if tile is None:
                st.markdown(
                    f'<div class="tile"><div class="tile-label">{indicator.name}</div>'
                    '<div class="tile-asof">No data stored yet</div></div>',
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(tiles.tile_html(tile), unsafe_allow_html=True)

    chosen = st.segmented_control("Date range", data.RANGE_LABELS, default=DEFAULT_RANGE, key="range")
    start = data.range_start(latest, chosen or DEFAULT_RANGE)
    st.plotly_chart(charts.overview_figure(observations, start), theme=None, config=PLOT_CONFIG)
    st.caption(
        "The target range begins in December 2008, when the Fed started setting a range instead of a single rate. "
        "FRED provides only about the last ten years of the S&P 500."
    )


def show_explore(observations: pd.DataFrame) -> None:
    choice = st.selectbox(
        "Indicator",
        [indicator.indicator_id for indicator in INDICATORS],
        format_func=lambda indicator_id: f"{indicator_id}: {INDICATORS_BY_ID[indicator_id].name}",
    )
    indicator = INDICATORS_BY_ID[choice]
    series = data.series_for(observations, choice)
    if series.empty:
        st.info(f"No observations of {choice} are stored yet.")
        return

    st.caption(f"{indicator.description}. {indicator.frequency.capitalize()}, in {indicator.units}.")
    st.plotly_chart(charts.explore_figure(indicator, series), theme=None, config=PLOT_CONFIG)

    table = series.rename("value").rename_axis("date").reset_index()
    table["date"] = table["date"].dt.date
    table = table.sort_values("date", ascending=False)
    with st.expander("Table"):
        st.dataframe(table, hide_index=True, width="stretch")
    st.download_button("Download CSV", table.to_csv(index=False), file_name=f"{choice}.csv", mime="text/csv")


def show_data_quality(observations: pd.DataFrame) -> None:
    st.subheader("Freshness")
    st.dataframe(
        data.freshness_table(observations, date.today()),
        hide_index=True,
        width="stretch",
        column_config={
            "Rows": st.column_config.NumberColumn(format="localized"),
            "Last written": st.column_config.DatetimeColumn(format="YYYY-MM-DD HH:mm"),
        },
    )
    st.caption(
        f"A series is stale when its latest observation is more than {data.STALE_AFTER_DAYS['daily']} days old "
        f"(daily) or {data.STALE_AFTER_DAYS['monthly']} days old (monthly). Last written is when a row's current "
        "value was stored; a row whose value has not changed is not rewritten."
    )

    st.subheader("Recent writes")
    st.dataframe(
        data.recent_writes(observations),
        hide_index=True,
        width="stretch",
        column_config={
            "Value": st.column_config.NumberColumn(format="%.2f"),
            "Written": st.column_config.DatetimeColumn(format="YYYY-MM-DD HH:mm"),
        },
    )
    st.caption("The rows the latest runs added or whose value they changed.")

def show_guide() -> None:
    st.subheader("Reading the ranges")
    for title, text in guide.RANGE_GUIDE:
        st.markdown(f"**{title}.** {text}")

    st.subheader("The indicators")
    for indicator in INDICATORS:
        entry = guide.GUIDES[indicator.indicator_id]
        with st.container(border=True):
            st.markdown(guide.heading_html(indicator), unsafe_allow_html=True)
            st.caption(guide.facts_line(indicator))
            st.markdown(f"**What it is.** {entry.what}")
            st.markdown("**How to read it**")
            st.markdown("\n".join(f"- {point}" for point in entry.reading))

st.title("Economic data")

try:
    observations = load_observations()
except (psycopg2.Error, ValueError) as error:
    st.error(
        f"Could not read the database: {str(error).splitlines()[0]}. "
        "Start it with `docker compose up -d --wait` and check DB_HOST, DB_PORT and DB_PASSWORD in `.env`."
    )
    st.stop()

latest = data.latest_date(observations)
if latest is None:
    st.info("The database has no observations yet. Load them with `python -m src.econ_data --backfill`.")
    st.stop()

caption, reload = st.columns([6, 1], vertical_alignment="center")
caption.caption(
    f"Latest observation {latest:%b} {latest.day}, {latest.year}. "
    f"The database is read at most once every {CACHE_SECONDS} seconds."
)
if reload.button("Reload", help="Read the database again now"):
    load_observations.clear()
    st.rerun()

overview_tab, explore_tab, quality_tab, guide_tab = st.tabs(["Overview", "Explore", "Data quality", "Guide"])
with overview_tab:
    show_overview(observations, latest)
with explore_tab:
    show_explore(observations)
with quality_tab:
    show_data_quality(observations)
with guide_tab:
    show_guide()
