import psycopg2
import pytest

from src.econ_data import cli
from src.econ_data.config import INDICATORS, get_indicator
from src.econ_data.pipeline import RunSummary

OK_SUMMARIES = [
    RunSummary(indicator_id="DFF", fetched=10, inserted=2, updated=1, unchanged=7),
    RunSummary(indicator_id="SP500", fetched=10, missing=1, unchanged=9),
]


class FakeRun:
    """Stands in for run_pipeline: records its arguments and returns scripted summaries."""

    def __init__(self, result=None, error=None):
        self.result = OK_SUMMARIES if result is None else result
        self.error = error
        self.calls = []

    def __call__(self, indicators, backfill):
        self.calls.append((list(indicators), backfill))
        if self.error:
            raise self.error
        return self.result


# --- parse_args ----------------------------------------------------------------


def test_defaults_are_an_incremental_run_of_every_indicator():
    args = cli.parse_args([])
    assert args.backfill is False
    assert args.indicators is None


def test_backfill_flag_is_read():
    assert cli.parse_args(["--backfill"]).backfill is True


def test_indicators_can_be_named():
    assert cli.parse_args(["--indicator", "DFF", "SP500"]).indicators == ["DFF", "SP500"]


def test_an_indicator_not_in_config_exits_with_usage_error(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.parse_args(["--indicator", "GDP"])
    assert exc.value.code == cli.EXIT_RUN_FAILED
    assert "invalid choice" in capsys.readouterr().err


# --- format_summaries ----------------------------------------------------------


def test_table_has_a_header_and_one_row_per_indicator():
    lines = cli.format_summaries(OK_SUMMARIES).splitlines()
    assert lines[0].split() == ["indicator", "fetched", "inserted", "updated", "unchanged",
                                "missing", "rejected", "status"]
    assert lines[1].split() == ["DFF", "10", "2", "1", "7", "0", "0", "ok"]
    assert lines[2].split() == ["SP500", "10", "0", "0", "9", "1", "0", "ok"]


def test_table_ends_with_a_total():
    assert cli.format_summaries(OK_SUMMARIES).splitlines()[-1] == "2 indicators: 2 ok, 0 failed"


def test_failed_indicator_is_marked_and_its_error_is_listed():
    text = cli.format_summaries([RunSummary(indicator_id="DFF", error="DFF: HTTP 500")])
    assert "FAILED" in text.splitlines()[1]
    assert "FAILED    DFF: HTTP 500" in text
    assert text.splitlines()[-1] == "1 indicator: 0 ok, 1 failed"


def test_rejected_observations_are_listed_with_their_examples():
    summary = RunSummary(
        indicator_id="DFF", fetched=3, rejected=2,
        rejection_examples=("2026-11-12: too high", "2026-11-11: too high"),
    )
    text = cli.format_summaries([summary])
    assert "rejected  DFF: 2 observations, for example:" in text
    assert "2026-11-12: too high" in text


def test_no_detail_section_when_nothing_failed_or_was_rejected():
    assert "FAILED" not in cli.format_summaries(OK_SUMMARIES)
    assert "for example" not in cli.format_summaries(OK_SUMMARIES)


def test_long_indicator_names_keep_the_columns_aligned():
    summaries = [RunSummary(indicator_id="A_VERY_LONG_INDICATOR_ID", fetched=1, unchanged=1)]
    lines = cli.format_summaries(summaries).splitlines()
    assert lines[0].index("fetched") + len("fetched") == lines[1].index("1") + 1


# --- main ----------------------------------------------------------------------


def test_main_runs_every_indicator_incrementally_by_default():
    run = FakeRun()
    assert cli.main([], run) == cli.EXIT_OK
    assert run.calls == [(list(INDICATORS), False)]


def test_main_passes_backfill_through():
    run = FakeRun()
    cli.main(["--backfill"], run)
    assert run.calls == [(list(INDICATORS), True)]


def test_main_runs_only_the_named_indicators():
    run = FakeRun()
    cli.main(["--indicator", "SP500", "DFF"], run)
    assert run.calls == [([get_indicator("SP500"), get_indicator("DFF")], False)]


def test_main_prints_the_table(capsys):
    cli.main([], FakeRun())
    assert "indicator" in capsys.readouterr().out


def test_main_exits_1_when_an_indicator_failed(capsys):
    run = FakeRun(result=[RunSummary(indicator_id="DFF"), RunSummary(indicator_id="SP500", error="SP500: HTTP 500")])
    assert cli.main([], run) == cli.EXIT_INDICATOR_FAILED
    assert "SP500: HTTP 500" in capsys.readouterr().out


@pytest.mark.parametrize(
    "error",
    [ValueError("No database credentials: set DB_PASSWORD or DB_SECRET_ARN"),
     psycopg2.OperationalError("connection refused")],
)
def test_main_exits_2_with_a_message_when_the_run_cannot_complete(error, capsys):
    assert cli.main([], FakeRun(error=error)) == cli.EXIT_RUN_FAILED
    captured = capsys.readouterr()
    assert "nothing was saved" in captured.err
    assert str(error) in captured.err
    assert captured.out == ""


def test_main_does_not_hide_unexpected_errors():
    with pytest.raises(RuntimeError, match="bug"):
        cli.main([], FakeRun(error=RuntimeError("bug")))