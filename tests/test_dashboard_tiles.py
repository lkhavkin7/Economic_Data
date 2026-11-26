"""dashboard.tiles: how a tile's figures read."""
from datetime import date

import pytest

from dashboard import charts, tiles
from dashboard.data import Tile


def make_tile(**overrides) -> Tile:
    values = {
        "indicator_id": "DFF",
        "name": "Effective Federal Funds Rate",
        "units": "percent",
        "first_date": date(1954, 7, 1),
        "latest_date": date(2026, 11, 20),
        "latest_value": 4.33,
        "change_1m": -0.04,
        "change_1y": -0.2,
        "change_unit": "pp",
        "percentile": None,
    }
    return Tile(**{**values, **overrides})


@pytest.mark.parametrize(
    "value, units, expected",
    [(4.333, "percent", "4.33%"), (6812.3, "index", "6,812.30"), (16.4, "index", "16.40")],
)
def test_values_read_by_their_units(value, units, expected):
    assert tiles.format_value(value, units) == expected


def test_dates_have_no_leading_zero_on_the_day():
    assert tiles.format_date(date(2026, 10, 1)) == "Oct 1, 2026"


@pytest.mark.parametrize(
    "change, unit, amount, arrow",
    [
        (0.1, "pp", "+0.10 pp", "▲"),
        (-0.25, "pp", "-0.25 pp", "▼"),
        (1.94, "%", "+1.9%", "▲"),
        (-39.1, "%", "-39.1%", "▼"),
        (0.0, "pp", "+0.00 pp", "–"),
    ],
)
def test_a_change_shows_its_sign_and_direction(change, unit, amount, arrow):
    text = tiles.format_change(change, unit)
    assert amount in text
    assert arrow in text


def test_a_missing_change_is_a_dash():
    assert tiles.format_change(None, "pp") == tiles.NO_VALUE


def test_a_tile_shows_the_value_date_and_both_changes():
    html = tiles.tile_html(make_tile())

    assert "4.33%" in html
    assert "as of Nov 20, 2026" in html
    assert "-0.04 pp" in html and "vs 1 month ago" in html
    assert "-0.20 pp" in html and "vs 1 year ago" in html


def test_a_tile_carries_its_series_color_on_the_swatch_only():
    html = tiles.tile_html(make_tile())
    assert html.count(charts.color_of("DFF")) == 1
    assert f"background:{charts.color_of('DFF')}" in html


def test_a_tile_is_one_line_because_markdown_treats_indented_lines_as_code():
    assert "\n" not in tiles.tile_html(make_tile())


def test_only_a_tile_with_a_percentile_shows_the_note():
    assert "readings since" not in tiles.tile_html(make_tile())
    html = tiles.tile_html(make_tile(indicator_id="VIXCLS", percentile=27.6, first_date=date(1990, 1, 2)))
    assert "Higher than 28% of readings since 1990" in html


def test_a_name_is_escaped():
    assert "&lt;b&gt;" in tiles.tile_html(make_tile(name="<b>x</b>"))


def test_tiles_do_not_use_green_or_red_for_direction():
    css = tiles.TILE_CSS.lower()
    assert "green" not in css and "red" not in css
