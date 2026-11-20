"""Command line entry point for the pipeline.

    python -m src.econ_data                          latest observations of every indicator
    python -m src.econ_data --backfill               full history of every indicator
    python -m src.econ_data --indicator DFF SP500    only the named indicators

main() prints one line per indicator and returns the exit code:

    0  every indicator succeeded
    1  at least one indicator failed (for example FRED returned an error)
    2  the run could not complete: bad arguments, bad configuration, or a
       database error. Nothing from that run was kept.

The indicators that can be named come from config.
"""
from __future__ import annotations

import argparse
import logging
import sys
from typing import Callable, Sequence

import psycopg2

from .config import INDICATORS, INDICATORS_BY_ID, get_indicator
from .pipeline import RunSummary, run_pipeline

EXIT_OK = 0
EXIT_INDICATOR_FAILED = 1
EXIT_RUN_FAILED = 2

COLUMNS = ("fetched", "inserted", "updated", "unchanged", "missing", "rejected")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Read the command line. Invalid arguments exit with code 2 and a usage message."""
    parser = argparse.ArgumentParser(
        prog="python -m src.econ_data",
        description="Load FRED observations into the database.",
    )
    parser.add_argument(
        "--backfill",
        action="store_true",
        help="fetch each indicator's full history instead of its latest observations",
    )
    parser.add_argument(
        "--indicator",
        nargs="+",
        dest="indicators",
        choices=sorted(INDICATORS_BY_ID),
        metavar="ID",
        help="only run these indicators (default: all). Choices: "
        + ", ".join(sorted(INDICATORS_BY_ID)),
    )
    return parser.parse_args(argv)


def format_summaries(summaries: Sequence[RunSummary]) -> str:
    """Return the run as text: a table, then details of failures and rejections."""
    width = max([len("indicator")] + [len(s.indicator_id) for s in summaries])
    header = f"{'indicator':<{width}}" + "".join(f"{name:>11}" for name in COLUMNS) + "  status"
    lines = [header]

    for s in summaries:
        counts = "".join(f"{getattr(s, name):>11}" for name in COLUMNS)
        lines.append(f"{s.indicator_id:<{width}}{counts}  {'ok' if s.ok else 'FAILED'}")

    details = []
    for s in summaries:
        if not s.ok:
            details.append(f"FAILED    {s.error}")
        if s.rejected:
            details.append(f"rejected  {s.indicator_id}: {s.rejected} observations, for example:")
            details.extend(f"            {example}" for example in s.rejection_examples)
    if details:
        lines += ["", *details]

    failed = sum(not s.ok for s in summaries)
    noun = "indicator" if len(summaries) == 1 else "indicators"
    lines += ["", f"{len(summaries)} {noun}: {len(summaries) - failed} ok, {failed} failed"]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None, run: Callable = run_pipeline) -> int:
    """Run the pipeline as the command line asks and return the exit code."""
    args = parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

    indicators = (
        [get_indicator(indicator_id) for indicator_id in args.indicators]
        if args.indicators
        else INDICATORS
    )

    try:
        summaries = run(indicators=indicators, backfill=args.backfill)
    except (ValueError, psycopg2.Error) as exc:
        # ValueError covers bad or missing settings. Other exceptions are bugs and
        # are left to show their traceback.
        print(f"Run failed, nothing was saved: {exc}", file=sys.stderr)
        return EXIT_RUN_FAILED

    print(format_summaries(summaries))
    return EXIT_OK if all(s.ok for s in summaries) else EXIT_INDICATOR_FAILED
