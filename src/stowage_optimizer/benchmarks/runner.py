"""Benchmark runner helpers and CLI for comparing solvers.

The runner evaluates Greedy, MILP, and Genetic Algorithm outputs using common
final metrics. It reports internal objective values only when a solver exposes
one, and it does not treat those objectives as cross-solver equivalents.
"""

from __future__ import annotations

import argparse
import csv
import io
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from stowage_optimizer.benchmarks.scenarios import (
    BENCHMARK_SCENARIOS,
    BenchmarkScenario,
    iter_benchmark_scenarios,
)
from stowage_optimizer.solvers import GeneticSolver, GreedySolver, MILPSolver, Solver

BENCHMARK_SOLVERS: tuple[str, ...] = ("greedy", "milp", "genetic")

_SOLVER_LABELS = {
    "greedy": "Greedy",
    "milp": "MILP",
    "genetic": "Genetic",
}

_TABLE_COLUMNS: tuple[str, ...] = (
    "scenario",
    "solver",
    "status",
    "feasible",
    "structural_feasible",
    "cg_within_tolerance",
    "runtime_seconds",
    "utilization",
    "cg_x",
    "cg_y",
    "cg_z_normalized",
    "real_rehandling",
    "violations",
    "objective_value",
    "gap",
    "detail",
)


@dataclass(frozen=True, slots=True)
class BenchmarkConfig:
    """Configuration shared by benchmark runs."""

    milp_time_limit_seconds: float | None = 10.0
    ga_population_size: int = 30
    ga_max_generations: int = 40
    ga_random_seed: int | None = 42
    ga_mutation_probability: float = 0.05
    ga_crossover_probability: float = 0.80

    @classmethod
    def quick(cls) -> BenchmarkConfig:
        """Return a lightweight configuration suitable for smoke checks."""
        return cls(
            milp_time_limit_seconds=5.0,
            ga_population_size=12,
            ga_max_generations=8,
            ga_random_seed=42,
        )


@dataclass(frozen=True, slots=True)
class BenchmarkRecord:
    """One solver result flattened for benchmark tables."""

    scenario: str
    solver: str
    status: str
    feasible: bool
    structural_feasible: bool
    cg_within_tolerance: bool
    runtime_seconds: float
    utilization: float
    cg_x: float
    cg_y: float
    cg_z_normalized: float
    real_rehandling: int
    violations: int
    objective_value: float | None
    gap: float | None
    detail: str | None = None
    error: str | None = None

    def as_dict(self) -> dict[str, object]:
        """Return a stable row dictionary for CSV or Markdown rendering."""
        return {
            "scenario": self.scenario,
            "solver": self.solver,
            "status": self.status,
            "feasible": self.feasible,
            "structural_feasible": self.structural_feasible,
            "cg_within_tolerance": self.cg_within_tolerance,
            "runtime_seconds": self.runtime_seconds,
            "utilization": self.utilization,
            "cg_x": self.cg_x,
            "cg_y": self.cg_y,
            "cg_z_normalized": self.cg_z_normalized,
            "real_rehandling": self.real_rehandling,
            "violations": self.violations,
            "objective_value": self.objective_value,
            "gap": self.gap,
            "detail": self.error or self.detail,
        }


def run_benchmarks(
    scenarios: Iterable[BenchmarkScenario] | None = None,
    *,
    solver_names: Iterable[str] = BENCHMARK_SOLVERS,
    config: BenchmarkConfig = BenchmarkConfig(),
) -> tuple[BenchmarkRecord, ...]:
    """Run configured solvers on configured scenarios."""
    selected_scenarios = tuple(scenarios) if scenarios is not None else BENCHMARK_SCENARIOS
    selected_solver_names = tuple(_normalize_solver_name(name) for name in solver_names)

    records: list[BenchmarkRecord] = []
    for scenario in selected_scenarios:
        for solver_name in selected_solver_names:
            solver = _build_solver(solver_name, scenario, config)
            records.append(_run_one(scenario, solver_name, solver))
    return tuple(records)


def records_to_markdown(records: Iterable[BenchmarkRecord]) -> str:
    """Render benchmark records as a GitHub-flavored Markdown table."""
    rows = [_public_row(record) for record in records]
    header = "| " + " | ".join(_TABLE_COLUMNS) + " |"
    separator = "| " + " | ".join("---" for _ in _TABLE_COLUMNS) + " |"
    body = [
        "| " + " | ".join(_format_value(row[column]) for column in _TABLE_COLUMNS) + " |"
        for row in rows
    ]
    return "\n".join((header, separator, *body))


def records_to_csv(records: Iterable[BenchmarkRecord]) -> str:
    """Render benchmark records as CSV text."""
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=_TABLE_COLUMNS)
    writer.writeheader()
    for record in records:
        writer.writerow(
            {column: _format_value(_public_row(record)[column]) for column in _TABLE_COLUMNS}
        )
    return buffer.getvalue()


def main(argv: list[str] | None = None) -> int:
    """CLI entry point used by ``python -m`` and the package script."""
    parser = argparse.ArgumentParser(
        description="Run reproducible stowage optimizer benchmark scenarios."
    )
    parser.add_argument(
        "--scenario",
        action="append",
        choices=[scenario.name for scenario in BENCHMARK_SCENARIOS],
        help="Scenario to run. Can be passed more than once. Defaults to all scenarios.",
    )
    parser.add_argument(
        "--solver",
        action="append",
        type=_solver_name_argument,
        metavar="{greedy,milp,genetic}",
        help=(
            "Solver to run; aliases such as `ga` are accepted. "
            "Can be passed more than once. Defaults to all solvers."
        ),
    )
    parser.add_argument(
        "--format",
        choices=("markdown", "csv"),
        default="markdown",
        help="Output format.",
    )
    parser.add_argument("--output", help="Optional output path for the rendered table.")
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Use a short GA search and bounded MILP solve for smoke checks.",
    )
    parser.add_argument(
        "--milp-time-limit",
        type=float,
        default=None,
        help="MILP time limit in seconds. Use 0 for no explicit limit.",
    )
    parser.add_argument("--ga-population-size", type=int, default=None)
    parser.add_argument("--ga-generations", type=int, default=None)
    parser.add_argument("--ga-seed", type=int, default=None)

    args = parser.parse_args(argv)

    scenarios = iter_benchmark_scenarios(tuple(args.scenario) if args.scenario else None)
    config = BenchmarkConfig.quick() if args.quick else BenchmarkConfig()
    config = _apply_cli_overrides(config, args)
    records = run_benchmarks(
        scenarios,
        solver_names=tuple(args.solver) if args.solver else BENCHMARK_SOLVERS,
        config=config,
    )
    rendered = records_to_csv(records) if args.format == "csv" else records_to_markdown(records)

    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    else:
        print(rendered)
    return 0


def _run_one(
    scenario: BenchmarkScenario,
    solver_name: str,
    solver: Solver,
) -> BenchmarkRecord:
    try:
        result = solver.solve(scenario.instance)
    except Exception as exc:  # noqa: BLE001 - benchmark tables should survive one failure.
        return BenchmarkRecord(
            scenario=scenario.name,
            solver=_SOLVER_LABELS[solver_name],
            status="error",
            feasible=False,
            structural_feasible=False,
            cg_within_tolerance=False,
            runtime_seconds=0.0,
            utilization=0.0,
            cg_x=0.0,
            cg_y=0.0,
            cg_z_normalized=0.0,
            real_rehandling=0,
            violations=0,
            objective_value=None,
            gap=None,
            error=f"{type(exc).__name__}: {exc}",
        )

    metrics = result.metrics
    return BenchmarkRecord(
        scenario=scenario.name,
        solver=_SOLVER_LABELS[solver_name],
        status=str(result.status),
        feasible=result.is_feasible,
        structural_feasible=result.is_structurally_feasible,
        cg_within_tolerance=result.cg_within_tolerance,
        runtime_seconds=result.runtime_seconds,
        utilization=metrics.slot_utilization,
        cg_x=metrics.cg_x,
        cg_y=metrics.cg_y,
        cg_z_normalized=metrics.cg_z_normalized,
        real_rehandling=metrics.real_rehandling,
        violations=metrics.constraint_violations,
        objective_value=result.objective_value,
        gap=result.gap,
        detail=result.solver_status_detail,
    )


def _build_solver(
    solver_name: str,
    scenario: BenchmarkScenario,
    config: BenchmarkConfig,
) -> Solver:
    common = {
        "cg_tolerance_lon": scenario.cg_tolerance_lon,
        "cg_tolerance_lat": scenario.cg_tolerance_lat,
        "min_incompatible_bay_distance": scenario.min_incompatible_bay_distance,
    }

    if solver_name == "greedy":
        return GreedySolver(**common)
    if solver_name == "milp":
        return MILPSolver(**common, time_limit_seconds=config.milp_time_limit_seconds)
    if solver_name == "genetic":
        return GeneticSolver(
            **common,
            population_size=config.ga_population_size,
            max_generations=config.ga_max_generations,
            mutation_probability=config.ga_mutation_probability,
            crossover_probability=config.ga_crossover_probability,
            random_seed=config.ga_random_seed,
        )

    raise ValueError(f"Unknown benchmark solver: {solver_name!r}.")


def _solver_name_argument(value: str) -> str:
    """Normalize a CLI ``--solver`` value, reporting aliases-aware errors.

    Wrapping :func:`_normalize_solver_name` lets argparse accept aliases like
    ``ga`` (a plain ``choices`` list would reject them before normalization)
    while unknown names still fail with the normalizer's message.
    """
    try:
        return _normalize_solver_name(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from None


def _normalize_solver_name(name: str) -> str:
    normalized = name.strip().lower().replace(" ", "_").replace("-", "_")
    aliases = {
        "ga": "genetic",
        "genetic_algorithm": "genetic",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized not in BENCHMARK_SOLVERS:
        raise ValueError(
            f"Unknown benchmark solver {name!r}. Expected one of {BENCHMARK_SOLVERS}."
        )
    return normalized


def _public_row(record: BenchmarkRecord) -> dict[str, object]:
    row = record.as_dict()
    return {column: row[column] for column in _TABLE_COLUMNS}


def _format_value(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)


def _apply_cli_overrides(config: BenchmarkConfig, args: argparse.Namespace) -> BenchmarkConfig:
    milp_time_limit = config.milp_time_limit_seconds
    if args.milp_time_limit is not None:
        milp_time_limit = None if args.milp_time_limit <= 0 else args.milp_time_limit

    return BenchmarkConfig(
        milp_time_limit_seconds=milp_time_limit,
        ga_population_size=args.ga_population_size or config.ga_population_size,
        ga_max_generations=args.ga_generations or config.ga_max_generations,
        ga_random_seed=args.ga_seed if args.ga_seed is not None else config.ga_random_seed,
        ga_mutation_probability=config.ga_mutation_probability,
        ga_crossover_probability=config.ga_crossover_probability,
    )


if __name__ == "__main__":
    raise SystemExit(main())
