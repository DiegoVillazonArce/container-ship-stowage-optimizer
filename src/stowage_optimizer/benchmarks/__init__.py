"""Reproducible benchmark scenarios and runners for Phase 8."""

from stowage_optimizer.benchmarks.scenarios import (
    BENCHMARK_SCENARIOS,
    BenchmarkScenario,
    get_benchmark_scenario,
    iter_benchmark_scenarios,
)

__all__ = [
    "BENCHMARK_SCENARIOS",
    "BENCHMARK_SOLVERS",
    "BenchmarkConfig",
    "BenchmarkRecord",
    "BenchmarkScenario",
    "get_benchmark_scenario",
    "iter_benchmark_scenarios",
    "records_to_csv",
    "records_to_markdown",
    "run_benchmarks",
]


def __getattr__(name: str):
    """Lazily expose runner helpers without preloading ``runner`` for ``python -m``."""
    if name in {
        "BENCHMARK_SOLVERS",
        "BenchmarkConfig",
        "BenchmarkRecord",
        "records_to_csv",
        "records_to_markdown",
        "run_benchmarks",
    }:
        from stowage_optimizer.benchmarks import runner

        return getattr(runner, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
