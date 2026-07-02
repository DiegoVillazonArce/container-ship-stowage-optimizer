"""Tests for the benchmark runner CLI entry point and error handling."""

from pathlib import Path

import pytest

from stowage_optimizer.benchmarks import BenchmarkConfig, get_benchmark_scenario, run_benchmarks
from stowage_optimizer.benchmarks.runner import _run_one, main


def test_runner_cli_writes_csv_output_file(tmp_path: Path) -> None:
    output = tmp_path / "benchmark.csv"

    exit_code = main(
        [
            "--quick",
            "--scenario",
            "small_base",
            "--solver",
            "greedy",
            "--format",
            "csv",
            "--output",
            str(output),
        ]
    )

    text = output.read_text(encoding="utf-8")
    assert exit_code == 0
    assert text.startswith("scenario,solver,status")
    assert "small_base" in text
    assert "Greedy" in text


def test_runner_cli_prints_markdown_by_default(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["--quick", "--scenario", "small_base", "--solver", "greedy"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "| scenario | solver | status |" in captured.out
    assert "small_base" in captured.out


def test_runner_cli_applies_overrides_without_running_disabled_solvers(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # ``--milp-time-limit 0`` means "no explicit limit"; the override path is
    # exercised even though only the fast Greedy solver actually runs.
    exit_code = main(
        [
            "--quick",
            "--scenario",
            "small_base",
            "--solver",
            "greedy",
            "--milp-time-limit",
            "0",
            "--ga-population-size",
            "6",
            "--ga-generations",
            "2",
            "--ga-seed",
            "5",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Greedy" in captured.out
    assert "MILP" not in captured.out


def test_runner_cli_accepts_ga_alias(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(
        [
            "--quick",
            "--scenario",
            "small_base",
            "--solver",
            "GA",
            "--ga-population-size",
            "6",
            "--ga-generations",
            "2",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Genetic" in captured.out
    assert "Greedy" not in captured.out


def test_runner_cli_rejects_unknown_solver_with_clean_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["--solver", "bogus"])

    assert excinfo.value.code == 2
    assert "Unknown benchmark solver" in capsys.readouterr().err


def test_run_benchmarks_accepts_solver_name_aliases() -> None:
    scenario = get_benchmark_scenario("small_base")

    records = run_benchmarks(
        (scenario,),
        solver_names=("GA",),
        config=BenchmarkConfig(ga_population_size=6, ga_max_generations=2, ga_random_seed=3),
    )

    assert len(records) == 1
    assert records[0].solver == "Genetic"


def test_run_benchmarks_rejects_unknown_solver_names() -> None:
    scenario = get_benchmark_scenario("small_base")

    with pytest.raises(ValueError, match="Unknown benchmark solver"):
        run_benchmarks((scenario,), solver_names=("bogus",))


def test_run_one_captures_solver_exceptions_as_error_records() -> None:
    scenario = get_benchmark_scenario("small_base")

    class ExplodingSolver:
        def solve(self, instance):
            raise RuntimeError("boom")

    record = _run_one(scenario, "greedy", ExplodingSolver())

    assert record.status == "error"
    assert record.error == "RuntimeError: boom"
    assert not record.feasible
    assert record.as_dict()["detail"] == "RuntimeError: boom"
