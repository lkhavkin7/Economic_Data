"""dashboard.charts: the colors, and that each figure holds the right series."""
import pandas as pd
import pytest

from dashboard import charts, data
from src.econ_data.config import INDICATORS, INDICATORS_BY_ID


def table() -> pd.DataFrame:
    """Two years of every indicator, daily, ending 2026-11-20."""
    days = pd.date_range("2024-11-20", "2026-11-20", freq="D")
    rows = [
        (indicator.indicator_id, day, float(position % 7) + 4.0, pd.Timestamp("2026-11-21"))
        for indicator in INDICATORS
        for position, day in enumerate(days)
    ]
    return pd.DataFrame(rows, columns=data.COLUMNS)


def names(figure) -> list:
    return [trace.name for trace in figure.data if trace.name]


# --- colors ----------------------------------------------------------------------


def test_every_indicator_in_config_has_a_color():
    assert {i.indicator_id for i in INDICATORS} <= set(charts.SERIES_COLORS)


def test_an_unknown_indicator_has_no_color_instead_of_a_wrong_one():
    with pytest.raises(KeyError):
        charts.color_of("NOT_AN_INDICATOR")


def test_the_fed_funds_series_share_one_color_and_the_others_differ():
    colors = charts.SERIES_COLORS
    assert colors["DFF"] == colors["DFEDTARU"] == colors["DFEDTARL"]
    assert len({colors["DFF"], colors["FEDFUNDS"], colors["SP500"], colors["VIXCLS"]}) == 4


def test_rgba_converts_a_hex_color():
    assert charts.rgba("#338ced", 0.5) == "rgba(51, 140, 237, 0.5)"


def test_hover_and_label_formats_follow_the_units():
    assert charts.hover_format("percent") == "%{y:.2f}%"
    assert charts.hover_format("index") == "%{y:,.2f}"
    assert charts.end_label_text(4.333, "percent") == "4.33%"
    assert charts.end_label_text(6812.3, "index") == "6,812.30"


# --- overview_figure ---------------------------------------------------------------


def test_overview_draws_every_series_on_its_own_value_axis_and_one_date_axis():
    figure = charts.overview_figure(table(), None)

    by_name = {}
    for trace in figure.data:
        by_name.setdefault(trace.name, set()).add(trace.yaxis)
    assert by_name["Target range"] == {"y"}
    assert by_name["Effective rate"] == {"y"}
    assert by_name["S&P 500"] == {"y2"}
    assert by_name["VIX"] == {"y3"}
    assert {trace.xaxis for trace in figure.data} <= {None, "x"}


def test_overview_tooltip_lists_every_panel():
    figure = charts.overview_figure(table(), None)
    assert figure.layout.hovermode == "x unified"
    assert figure.layout.hoversubplots == "axis"


def test_overview_titles_each_panel():
    figure = charts.overview_figure(table(), None)
    assert [a.text for a in figure.layout.annotations] == list(charts.PANEL_TITLES)


def test_overview_shows_only_the_chosen_range():
    figure = charts.overview_figure(table(), pd.Timestamp("2026-10-20"))
    line = next(trace for trace in figure.data if trace.name == "VIX")
    assert pd.Timestamp(line.x[0]) == pd.Timestamp("2026-10-20")
    assert pd.Timestamp(line.x[-1]) == pd.Timestamp("2026-11-20")


def test_overview_labels_the_newest_value_of_each_line():
    figure = charts.overview_figure(table(), None)
    labels = [trace.text[0] for trace in figure.data if trace.mode == "markers+text"]
    assert len(labels) == 3


def test_overview_leaves_room_after_the_newest_date_for_the_labels():
    figure = charts.overview_figure(table(), None)
    assert pd.Timestamp(figure.layout.xaxis.range[1]) > pd.Timestamp("2026-11-20")


def test_overview_skips_a_series_with_no_rows_without_failing():
    only_vix = table()
    only_vix = only_vix[only_vix["indicator_id"] == "VIXCLS"]
    assert names(charts.overview_figure(only_vix, None)) == ["VIX"]


def test_overview_of_an_empty_table_is_an_empty_figure():
    assert len(charts.overview_figure(pd.DataFrame(columns=data.COLUMNS), None).data) == 0


# --- explore_figure ----------------------------------------------------------------


def test_explore_draws_one_series_in_its_own_color_with_a_slider():
    indicator = INDICATORS_BY_ID["SP500"]
    series = data.series_for(table(), "SP500")
    figure = charts.explore_figure(indicator, series)

    assert len(figure.data) == 1
    assert figure.data[0].line.color == charts.color_of("SP500")
    assert figure.layout.xaxis.rangeslider.visible
    assert [b.label for b in figure.layout.xaxis.rangeselector.buttons] == ["1M", "6M", "1Y", "5Y", "Max"]
    assert figure.layout.showlegend is False
