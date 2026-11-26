"""dashboard.guide: that every indicator is explained and the facts read correctly."""
import pytest

from dashboard import charts, guide
from src.econ_data.config import INDICATORS, INDICATORS_BY_ID, Indicator


def test_every_indicator_in_config_has_an_explanation():
    assert {i.indicator_id for i in INDICATORS} <= set(guide.GUIDES)


def test_every_explanation_belongs_to_an_indicator_in_config():
    assert set(guide.GUIDES) <= set(INDICATORS_BY_ID)


def test_every_explanation_says_what_it_is_and_how_to_read_it():
    for entry in guide.GUIDES.values():
        assert entry.what.strip()
        assert entry.reading and all(point.strip() for point in entry.reading)


def test_the_three_kinds_of_range_are_explained():
    assert [title.split(" (")[0] for title, _ in guide.RANGE_GUIDE] == ["Date range", "Target range", "Valid range"]


@pytest.mark.parametrize(
    "value, units, expected",
    [(0, "percent", "0%"), (25, "percent", "25%"), (0.25, "percent", "0.25%"), (100, "index", "100"),
     (50000, "index", "50,000")],
)
def test_limits_read_by_their_units(value, units, expected):
    assert guide.format_limit(value, units) == expected


def test_the_valid_range_is_read_from_config():
    assert guide.valid_range_text(INDICATORS_BY_ID["DFF"]) == "0% to 25%"
    assert guide.valid_range_text(INDICATORS_BY_ID["SP500"]) == "100 to 50,000"


def test_the_facts_line_holds_what_config_holds():
    line = guide.facts_line(INDICATORS_BY_ID["FEDFUNDS"])
    assert line == "FRED series FEDFUNDS · monthly · percent · valid range 0% to 25%"


def test_the_heading_is_one_line_with_the_series_color_and_an_escaped_name():
    indicator = Indicator(
        indicator_id="DFF", series_id="DFF", name="<b>x</b>", description="", frequency="daily",
        units="percent", min_value=0, max_value=1, lookback=1,
    )
    html = guide.heading_html(indicator)
    assert "\n" not in html
    assert charts.color_of("DFF") in html
    assert "&lt;b&gt;" in html and "<b>" not in html


def test_the_text_has_no_dollar_signs_because_markdown_reads_them_as_math():
    texts = [entry.what for entry in guide.GUIDES.values()]
    texts += [point for entry in guide.GUIDES.values() for point in entry.reading]
    texts += [text for _, text in guide.RANGE_GUIDE]
    assert not any("$" in text for text in texts)
