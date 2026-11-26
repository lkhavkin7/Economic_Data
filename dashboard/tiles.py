"""The indicator tiles: the text each one shows, as HTML, and the style sheet for them.

Tiles show direction with an arrow and a sign, in the text colors. They do not use
green and red, because a rising rate or a rising VIX is not good or bad news in itself.
"""
from __future__ import annotations

from datetime import date
from html import escape

from dashboard import charts
from dashboard.data import Tile

NO_VALUE = "—"

TILE_CSS = f"""
<style>
.tile {{
    background: {charts.RAISED};
    border: 1px solid {charts.GRID};
    border-radius: 8px;
    padding: 16px 18px;
    margin-bottom: 14px;
    min-height: 215px;
    font-family: {charts.FONT};
    color: {charts.TEXT};
}}
.tile-label {{ color: {charts.TEXT_MUTED}; font-size: 0.85rem; display: flex; align-items: center; gap: 8px; }}
.tile-swatch {{ width: 10px; height: 10px; border-radius: 50%; flex: none; }}
.tile-value {{ font-size: 1.9rem; font-weight: 600; line-height: 1.25; margin: 6px 0 2px 0; }}
.tile-asof {{ color: {charts.TEXT_MUTED}; font-size: 0.8rem; margin-bottom: 10px; }}
.tile-change {{ display: flex; justify-content: space-between; font-size: 0.85rem; padding: 3px 0;
                border-top: 1px solid {charts.GRID}; }}
.tile-change span:last-child {{ color: {charts.TEXT_MUTED}; }}
.tile-arrow {{ color: {charts.TEXT_MUTED}; font-size: 0.7rem; margin-right: 2px; }}
.tile-note {{ color: {charts.TEXT_MUTED}; font-size: 0.8rem; margin-top: 8px; }}
</style>
"""


def format_value(value: float, units: str) -> str:
    """4.33% for a rate, 6,812.34 for an index level."""
    return f"{value:.2f}%" if units == "percent" else f"{value:,.2f}"


def format_date(day: date) -> str:
    return f"{day:%b} {day.day}, {day.year}"


def format_change(change: float | None, unit: str) -> str:
    """A change as HTML: a small arrow and the signed amount, such as ▲ +0.10 pp or ▼ -1.2%. No value gives a dash."""
    if change is None:
        return NO_VALUE
    arrow = "▲" if change > 0 else "▼" if change < 0 else "–"
    amount = f"{change:+.2f} pp" if unit == "pp" else f"{change:+.1f}%"
    return f'<span class="tile-arrow">{arrow}</span> {amount}'


def _change_row(change: float | None, unit: str, period: str) -> str:
    return f'<div class="tile-change"><span>{format_change(change, unit)}</span><span>vs {period} ago</span></div>'


def tile_html(tile: Tile) -> str:
    """The HTML of one tile. It is a single line, because Markdown treats indented lines as code."""
    swatch = f'<span class="tile-swatch" style="background:{charts.color_of(tile.indicator_id)}"></span>'
    parts = [
        '<div class="tile">',
        f'<div class="tile-label">{swatch}{escape(tile.name)}</div>',
        f'<div class="tile-value">{format_value(tile.latest_value, tile.units)}</div>',
        f'<div class="tile-asof">as of {format_date(tile.latest_date)}</div>',
        _change_row(tile.change_1m, tile.change_unit, "1 month"),
        _change_row(tile.change_1y, tile.change_unit, "1 year"),
    ]
    if tile.percentile is not None:
        parts.append(
            f'<div class="tile-note">Higher than {tile.percentile:.0f}% of readings since {tile.first_date.year}</div>'
        )
    parts.append("</div>")
    return "".join(parts)
