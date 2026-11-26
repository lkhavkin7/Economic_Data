"""The dashboard's Plotly figures, and the colors they are drawn in.

An indicator is drawn in the same color in every figure. The series colors were
checked against SURFACE with a palette validator (colorblind separation, contrast
against the background). Text uses the two text colors, never a series color.
"""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from dashboard import data
from src.econ_data.config import Indicator

SURFACE = "#1a1a1a"  # the page and chart background: 90% black
RAISED = "#242424"  # tiles and tooltips, one step above the background
TEXT = "#cce3fd"  # light blue, for titles and values
TEXT_MUTED = "#8fb0d4"  # axis labels, the legend and captions
GRID = "#303030"  # hairline gridlines
AXIS = "#474747"  # the baseline and the hover crosshair

BLUE = "#338ced"
AQUA = "#00a888"
ORANGE = "#e76624"
VIOLET = "#9887ef"

# The three Fed funds series are one family of lines, so they share a color.
SERIES_COLORS = {
    "DFF": BLUE,
    "DFEDTARU": BLUE,
    "DFEDTARL": BLUE,
    "FEDFUNDS": VIOLET,
    "SP500": AQUA,
    "VIXCLS": ORANGE,
}

FONT = "system-ui, -apple-system, 'Segoe UI', sans-serif"
LINE_WIDTH = 2
MARKER_SIZE = 9
BAND_FILL_OPACITY = 0.16
BAND_EDGE_OPACITY = 0.5
LABEL_ROOM = 0.06  # the share of the date range left empty after the newest date, for end labels

# The overview's three panels, top to bottom: their titles and the part of the figure's height each one fills.
PANEL_TITLES = ("Fed funds rate and target range", "S&P 500", "VIX, expected 30-day volatility")
PANEL_DOMAINS = ((0.64, 1.0), (0.31, 0.58), (0.0, 0.25))


def color_of(indicator_id: str) -> str:
    """The color an indicator is drawn in."""
    return SERIES_COLORS[indicator_id]


def rgba(color: str, opacity: float) -> str:
    """A #rrggbb color as a CSS rgba() string."""
    red, green, blue = (int(color[i : i + 2], 16) for i in (1, 3, 5))
    return f"rgba({red}, {green}, {blue}, {opacity})"


def hover_format(units: str) -> str:
    """How a value reads in a tooltip: rates with a percent sign, index levels with thousands separators."""
    return "%{y:.2f}%" if units == "percent" else "%{y:,.2f}"


def end_label_text(value: float, units: str) -> str:
    return f"{value:.2f}%" if units == "percent" else f"{value:,.2f}"


# --- shared pieces ---------------------------------------------------------------


def _line(series: pd.Series, name: str, color: str, hover: str, **options) -> go.Scatter:
    return go.Scatter(
        x=series.index,
        y=series.values,
        mode="lines",
        name=name,
        line={"color": color, "width": LINE_WIDTH, "shape": "linear"},
        hovertemplate=hover,
        **options,
    )


def _end_label(series: pd.Series, color: str, units: str, **options) -> go.Scatter:
    """A dot on the newest point with its value beside it.

    The ring in the surface color keeps the dot clear of the line it ends.
    """
    return go.Scatter(
        x=[series.index[-1]],
        y=[series.iloc[-1]],
        mode="markers+text",
        marker={"size": MARKER_SIZE, "color": color, "line": {"color": SURFACE, "width": 2}},
        text=[end_label_text(float(series.iloc[-1]), units)],
        textposition="middle right",
        textfont={"color": TEXT, "size": 12},
        cliponaxis=False,
        showlegend=False,
        hoverinfo="skip",
        **options,
    )


def _style(fig: go.Figure) -> None:
    """The look shared by every figure: dark surface, recessive grid, one crosshair."""
    fig.update_layout(
        paper_bgcolor=SURFACE,
        plot_bgcolor=SURFACE,
        font={"family": FONT, "color": TEXT_MUTED, "size": 12},
        hoverlabel={"bgcolor": RAISED, "bordercolor": GRID, "font": {"color": TEXT, "family": FONT}},
        legend={"font": {"color": TEXT_MUTED}, "bgcolor": "rgba(0,0,0,0)"},
    )
    fig.update_xaxes(
        showgrid=False,
        zeroline=False,
        linecolor=AXIS,
        showspikes=True,
        spikemode="across",
        spikesnap="cursor",
        spikethickness=1,
        spikedash="solid",
        spikecolor=AXIS,
    )
    fig.update_yaxes(showgrid=True, gridcolor=GRID, gridwidth=1, zeroline=False, showline=False, automargin=True)
    fig.update_xaxes(automargin=True)


# --- figures -----------------------------------------------------------------------


def overview_figure(observations: pd.DataFrame, start: pd.Timestamp | None) -> go.Figure:
    """Fed funds rates, the S&P 500 and the VIX in three panels that share one date axis.

    The first panel draws the effective rate over the range the Fed is aiming for.
    All three panels use the same date axis, so hovering anywhere shows every
    series' value for that date in one tooltip.
    """

    def visible(indicator_id: str) -> pd.Series:
        return data.slice_series(data.series_for(observations, indicator_id), start)

    lower, upper, effective = visible("DFEDTARL"), visible("DFEDTARU"), visible("DFF")
    sp500, vix = visible("SP500"), visible("VIXCLS")
    band_color = color_of("DFF")
    edge = rgba(band_color, BAND_EDGE_OPACITY)

    fig = go.Figure()
    if not lower.empty and not upper.empty:
        # The lower edge goes first: the upper edge fills down to the trace before it.
        fig.add_trace(
            _line(lower, "Target range", edge, "lower %{y:.2f}%", legendgroup="target", showlegend=False, yaxis="y")
        )
        fig.add_trace(
            _line(
                upper,
                "Target range",
                edge,
                "upper %{y:.2f}%",
                legendgroup="target",
                fill="tonexty",
                fillcolor=rgba(band_color, BAND_FILL_OPACITY),
                yaxis="y",
            )
        )
    if not effective.empty:
        fig.add_trace(_line(effective, "Effective rate", band_color, hover_format("percent"), yaxis="y"))
        fig.add_trace(_end_label(effective, band_color, "percent", yaxis="y"))
    if not sp500.empty:
        fig.add_trace(_line(sp500, "S&P 500", color_of("SP500"), hover_format("index"), yaxis="y2"))
        fig.add_trace(_end_label(sp500, color_of("SP500"), "index", yaxis="y2"))
    if not vix.empty:
        fig.add_trace(_line(vix, "VIX", color_of("VIXCLS"), hover_format("index"), yaxis="y3"))
        fig.add_trace(_end_label(vix, color_of("VIXCLS"), "index", yaxis="y3"))

    _style(fig)
    fig.update_layout(
        height=700,
        margin={"l": 8, "r": 16, "t": 70, "b": 8},
        hovermode="x unified",
        hoversubplots="axis",  # the tooltip also lists the panels stacked on the same date axis
        legend={"orientation": "h", "x": 0, "y": 1.11, "yanchor": "bottom"},
        # One date axis under the bottom panel. Each panel has its own value axis, in its own band of the figure.
        xaxis={"anchor": "y3", "hoverformat": "%b %d, %Y"},
        yaxis={"domain": PANEL_DOMAINS[0], "anchor": "x", "ticksuffix": "%"},
        yaxis2={"domain": PANEL_DOMAINS[1], "anchor": "x", "tickformat": ","},
        yaxis3={"domain": PANEL_DOMAINS[2], "anchor": "x"},
        annotations=[
            {
                "text": title,
                "x": 0,
                "y": domain[1],
                "xref": "paper",
                "yref": "paper",
                "xanchor": "left",
                "yanchor": "bottom",
                "showarrow": False,
                "font": {"color": TEXT, "size": 14, "family": FONT},
            }
            for title, domain in zip(PANEL_TITLES, PANEL_DOMAINS, strict=True)
        ],
    )
    shown = [series for series in (lower, upper, effective, sp500, vix) if not series.empty]
    if shown:
        # Leaves room after the newest date for the value labels.
        first = min(series.index[0] for series in shown)
        last = max(series.index[-1] for series in shown)
        fig.update_xaxes(range=[first, last + (last - first) * LABEL_ROOM])
    return fig


def explore_figure(indicator: Indicator, series: pd.Series) -> go.Figure:
    """One indicator's whole history, with range buttons and a slider to pick the dates shown."""
    color = color_of(indicator.indicator_id)
    fig = go.Figure()
    fig.add_trace(_line(series, indicator.name, color, hover_format(indicator.units)))

    _style(fig)
    fig.update_layout(
        height=520,
        margin={"l": 8, "r": 16, "t": 40, "b": 8},
        hovermode="x",
        showlegend=False,
    )
    if indicator.units == "percent":
        fig.update_yaxes(ticksuffix="%")
    else:
        fig.update_yaxes(tickformat=",")
    fig.update_xaxes(
        rangeslider={"visible": True, "thickness": 0.08, "bgcolor": RAISED, "bordercolor": GRID, "borderwidth": 1},
        rangeselector={
            "buttons": [
                {"count": 1, "label": "1M", "step": "month", "stepmode": "backward"},
                {"count": 6, "label": "6M", "step": "month", "stepmode": "backward"},
                {"count": 1, "label": "1Y", "step": "year", "stepmode": "backward"},
                {"count": 5, "label": "5Y", "step": "year", "stepmode": "backward"},
                {"step": "all", "label": "Max"},
            ],
            "bgcolor": RAISED,
            "activecolor": GRID,
            "bordercolor": GRID,
            "borderwidth": 1,
            "font": {"color": TEXT},
            "x": 0,
            "y": 1.02,
        },
    )
    return fig
