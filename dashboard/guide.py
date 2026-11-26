"""The Guide tab's text: what each indicator is, how to read its values, and how to read the three kinds of range.

What an indicator is called, how often it is published and what values it accepts
come from config, so this page cannot disagree with what the pipeline enforces.
The explanations that config does not hold are written here, one entry per indicator.
"""
from __future__ import annotations

from dataclasses import dataclass
from html import escape

from dashboard import charts
from src.econ_data.config import Indicator


@dataclass(frozen=True)
class Guide:
    """The written explanation of one indicator."""

    what: str  # one paragraph: what is measured, and who produces it
    reading: tuple[str, ...]  # how to read its values, one point each


GUIDES: dict[str, Guide] = {
    "DFF": Guide(
        what=(
            "The interest rate banks charge each other for overnight loans of the money they hold at the "
            "Federal Reserve. The New York Fed works it out each business day from the loans actually made. "
            "FRED repeats the last business day's rate on weekends and holidays, so this series has a value "
            "for every calendar day. The Fed cannot set this rate directly: it sets a target range and steers "
            "the effective rate into it."
        ),
        reading=(
            "It normally sits inside the target range, the shaded band in the Overview chart. It leaves the band "
            "only briefly, when money markets are strained.",
            "The level is the cost of short-term borrowing. Near 0% (2009 to 2015, and 2020 to 2021) the Fed was "
            "keeping borrowing as cheap as it could to support growth. Above 5% (2023 to 2024) it was making "
            "borrowing expensive to slow inflation. It was close to 20% in 1980 and 1981.",
            "Changes on its tile are in percentage points (pp): a rise from 4.0% to 4.5% is +0.50 pp. A "
            "percent change would read as 12.5%, which hides that the rate moved half a point.",
        ),
    ),
    "DFEDTARU": Guide(
        what=(
            "The top of the range the Federal Open Market Committee (FOMC) is aiming for. The FOMC is the Fed "
            "committee that votes on interest rates. The series changes only on the day the FOMC announces a "
            "decision, so its line is flat with sudden steps."
        ),
        reading=(
            "The FOMC has eight scheduled meetings a year, so most days have no change. A move is usually "
            "0.25 percentage points, also written 25 basis points. A basis point is one hundredth of a "
            "percentage point.",
            "Since the range began it has been 0.25 points wide. The upper and lower limits move together, "
            "and the distance between them is the height of the shaded band.",
            "The series starts on 2008-12-16, when the Fed changed from aiming for a single rate to aiming "
            "for a range. Nothing is stored before that date.",
        ),
    ),
    "DFEDTARL": Guide(
        what=(
            "The bottom of the range the Federal Open Market Committee (FOMC) is aiming for. Like the upper "
            "limit, it changes only on the day of an FOMC decision."
        ),
        reading=(
            "A lower limit of 0.00% means the Fed had pushed its target as low as it practically goes. This is "
            "called the zero lower bound, and it held from 2008 to 2015 and again in 2020 and 2021.",
            "A change in this line is the Fed's decision. A change in the effective rate (DFF) is the market's "
            "response, and it follows on the day the decision takes effect.",
            "Like the upper limit, it starts on 2008-12-16.",
        ),
    ),
    "FEDFUNDS": Guide(
        what=(
            "The average of the daily effective federal funds rate over a calendar month. There is one value "
            "per month, dated the first day of that month, so the value dated Oct 1 is October's average."
        ),
        reading=(
            "It smooths a month of day-to-day movement and lags a rate change: after a change in the middle "
            "of a month, that month's average lands between the old and the new rate.",
            "It is published a few days after its month ends, so the newest value can be about two months "
            "behind. The Data quality tab allows 65 days before it calls a monthly series stale.",
            "Use it to line up with other monthly data. Use the effective rate (DFF) when the exact day of a "
            "decision matters.",
        ),
    ),
    "SP500": Guide(
        what=(
            "A stock index that follows 500 large US companies, each weighted by its market value (share price "
            "times shares outstanding). The value is the closing level at the end of each trading day. It is a "
            "price index, so it leaves out dividends. FRED carries only about the last ten years of it."
        ),
        reading=(
            "The level is in index points, not dollars, and the number means little by itself because the "
            "index is scaled to a base period. What matters is the percent change: a move from 6,000 to 6,060 "
            "is 1%.",
            "Its tile shows percent changes, where the rates show percentage points, because a point of "
            "index is worth less as the index rises.",
            "It trends upward over long periods, so it has no usual range. That is why its tile shows no "
            "percentile, while the VIX's does.",
            "Only trading days have values. A one-month change compares against the last trading day on or "
            "before that date.",
        ),
    ),
    "VIXCLS": Guide(
        what=(
            "The CBOE Volatility Index. The Chicago Board Options Exchange works it out from the prices of "
            "S&P 500 options, which are contracts that cost more when traders expect bigger price swings. It "
            "measures the size of the swings the market expects over the next 30 days, as an annualized "
            "percentage."
        ),
        reading=(
            "Higher means bigger expected swings. Since 1990 its average has been roughly 19 to 20. Below "
            "about 15 is usually calm and above about 30 usually means stress. These are rules of thumb, not "
            "official limits.",
            "To turn it into a daily size, divide by 16, the square root of the roughly 252 trading days in "
            "a year. A VIX of 16 implies about a 1% daily move in the S&P 500, and 32 implies about 2%.",
            "It rises fast and falls slowly, and usually rises when stocks fall. It went above 80 in late "
            "2008 and again in March 2020.",
            "The note on its tile, such as 'Higher than 60% of readings since 1990', is a percentile: the "
            "share of all stored days on which the VIX was at or below today's value. A percentile in the "
            "90s is rare and means unusual stress. Near 50 is a typical day.",
        ),
    ),
}

# The three kinds of range the dashboard uses, as (title, text).
RANGE_GUIDE: tuple[tuple[str, str], ...] = (
    (
        "Date range (1M, 6M, 1Y, 5Y, Max)",
        "Chooses how much history the Overview chart shows. It counts back from the newest observation in the "
        "database, not from today's date, so a database that has fallen behind still shows its latest stretch "
        "of data. The Explore tab has its own buttons and a slider that zoom the chart without reading the "
        "database again.",
    ),
    (
        "Target range (the shaded band)",
        "The band in the top panel of the Overview chart is the Fed's target range, drawn between the upper "
        "and lower limit series. The line is the effective rate. The distance between the line and the band's "
        "edges shows how closely the market is following the Fed's aim. When the whole band steps up or down, "
        "that is a Fed decision. The band begins in December 2008, so earlier history shows the effective "
        "rate alone.",
    ),
    (
        "Valid range",
        "Every indicator has a lowest and a highest accepted value in config. When the pipeline fetches a value "
        "outside them, it rejects the row instead of storing it, and the run summary counts it as rejected. "
        "The limits are wide on purpose: they catch impossible values, such as a misplaced decimal point or a "
        "mix-up of units, not unusual ones. So every value on this dashboard is inside its range. A value "
        "near an edge is a reason to check whether the limit itself needs widening. The limits shown below are "
        "read from config, so they match what the pipeline enforces.",
    ),
)


def format_limit(value: float, units: str) -> str:
    """25 percent as 25%, and 50000 index points as 50,000."""
    return f"{value:g}%" if units == "percent" else f"{value:,.0f}"


def valid_range_text(indicator: Indicator) -> str:
    """The accepted values as text, such as 0% to 25%."""
    low = format_limit(indicator.min_value, indicator.units)
    high = format_limit(indicator.max_value, indicator.units)
    return f"{low} to {high}"


def facts_line(indicator: Indicator) -> str:
    """The facts config holds about an indicator, on one line."""
    return (
        f"{indicator.source} series {indicator.series_id} · {indicator.frequency} · {indicator.units} · "
        f"valid range {valid_range_text(indicator)}"
    )


def heading_html(indicator: Indicator) -> str:
    """An indicator's name beside a dot in its chart color, as one line of HTML."""
    swatch = (
        f'<span style="width:10px;height:10px;border-radius:50%;flex:none;'
        f'background:{charts.color_of(indicator.indicator_id)}"></span>'
    )
    return (
        f'<div style="display:flex;align-items:center;gap:8px;font-size:1.1rem;font-weight:600;'
        f'color:{charts.TEXT}">{swatch}{escape(indicator.name)}</div>'
    )
