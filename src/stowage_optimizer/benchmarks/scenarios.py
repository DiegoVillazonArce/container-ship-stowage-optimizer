"""Shared benchmark scenarios for reproducible solver comparison.

The scenarios in this module are intentionally deterministic and small enough
to be useful in tests, examples, and manual benchmark runs. They cover the
Phase 8 comparison surface without adding new model assumptions: base loading,
reefers, incompatible cargo, multi-port unloading pressure, and a moderate
scalability case.
"""

from __future__ import annotations

from dataclasses import dataclass

from stowage_optimizer.core.container import Container, ContainerType
from stowage_optimizer.core.examples import create_small_example_instance
from stowage_optimizer.core.metrics import (
    DEFAULT_CG_TOLERANCE_LAT,
    DEFAULT_CG_TOLERANCE_LON,
    DEFAULT_MIN_INCOMPATIBLE_BAY_DISTANCE,
)
from stowage_optimizer.core.problem import ProblemInstance
from stowage_optimizer.core.route import Route
from stowage_optimizer.core.ship import Ship
from stowage_optimizer.core.solution import StowageSolution


@dataclass(frozen=True, slots=True)
class BenchmarkScenario:
    """A named, documented problem instance for solver comparison."""

    name: str
    title: str
    description: str
    instance: ProblemInstance
    cg_tolerance_lon: float = DEFAULT_CG_TOLERANCE_LON
    cg_tolerance_lat: float = DEFAULT_CG_TOLERANCE_LAT
    min_incompatible_bay_distance: int = DEFAULT_MIN_INCOMPATIBLE_BAY_DISTANCE
    reference_solution: StowageSolution | None = None
    notes: str = ""

    @property
    def container_count(self) -> int:
        """Return the number of containers in the scenario."""
        return len(self.instance.containers)

    @property
    def slot_count(self) -> int:
        """Return the number of vessel slots in the scenario."""
        return self.instance.ship.slot_count


def _small_base() -> BenchmarkScenario:
    return BenchmarkScenario(
        name="small_base",
        title="Small base scenario",
        description=(
            "Hand-checkable 6 x 4 x 4 example with normal, reefer, flammable, "
            "and oxidizer cargo."
        ),
        instance=create_small_example_instance(),
        notes="Recommended first smoke scenario for all solvers.",
    )


def _reefer_focus() -> BenchmarkScenario:
    instance = ProblemInstance(
        ship=Ship(
            bays=3,
            rows=2,
            tiers=2,
            reefer_slots=((1, 1, 1), (1, 2, 1), (2, 1, 1), (2, 1, 2)),
        ),
        route=Route(("Panama", "Brazil", "Spain")),
        containers=(
            Container("RF01", 14.0, "Panama", ContainerType.REEFER),
            Container("RF02", 16.0, "Brazil", ContainerType.REEFER),
            Container("NR01", 24.0, "Spain", ContainerType.NORMAL),
            Container("NR02", 18.0, "Brazil", ContainerType.NORMAL),
            Container("NR03", 10.0, "Panama", ContainerType.NORMAL),
        ),
    )
    return BenchmarkScenario(
        name="reefer_focus",
        title="Reefer-constrained scenario",
        description=(
            "Small instance with multiple refrigerated containers and limited "
            "reefer-capable slots."
        ),
        instance=instance,
        cg_tolerance_lon=0.60,
        cg_tolerance_lat=0.60,
        notes="Exercises reefer capacity and slot compatibility without tight CG stress.",
    )


def _incompatible_cargo() -> BenchmarkScenario:
    instance = ProblemInstance(
        ship=Ship(bays=4, rows=2, tiers=1),
        route=Route(("Panama", "Brazil")),
        containers=(
            Container("DG-F", 18.0, "Panama", ContainerType.FLAMMABLE),
            Container("DG-O", 16.0, "Brazil", ContainerType.OXIDIZER),
            Container("N-01", 12.0, "Panama", ContainerType.NORMAL),
            Container("N-02", 12.0, "Brazil", ContainerType.NORMAL),
        ),
    )
    return BenchmarkScenario(
        name="incompatible_cargo",
        title="Incompatible-cargo separation scenario",
        description=(
            "Flammable and oxidizer cargo must be separated by at least two "
            "bays, with normal cargo available to balance the plan."
        ),
        instance=instance,
        cg_tolerance_lon=1.0,
        cg_tolerance_lat=1.0,
        min_incompatible_bay_distance=2,
        notes="CG tolerances are relaxed so the benchmark isolates dangerous-cargo separation.",
    )


def _multi_port_rehandling() -> BenchmarkScenario:
    instance = ProblemInstance(
        ship=Ship(bays=2, rows=2, tiers=3),
        route=Route(("Panama", "Cartagena", "Rotterdam")),
        containers=(
            Container("P-HEAVY", 30.0, "Panama", ContainerType.NORMAL),
            Container("P-LIGHT", 8.0, "Panama", ContainerType.NORMAL),
            Container("C-HEAVY", 24.0, "Cartagena", ContainerType.NORMAL),
            Container("C-LIGHT", 12.0, "Cartagena", ContainerType.NORMAL),
            Container("R-HEAVY", 28.0, "Rotterdam", ContainerType.NORMAL),
            Container("R-LIGHT", 10.0, "Rotterdam", ContainerType.NORMAL),
        ),
    )
    reference_solution = StowageSolution.from_mapping(
        {
            "P-HEAVY": (1, 1, 1),
            "R-LIGHT": (1, 1, 2),
            "C-HEAVY": (1, 2, 1),
            "R-HEAVY": (1, 2, 2),
            "P-LIGHT": (2, 1, 1),
            "C-LIGHT": (2, 2, 1),
        }
    )
    return BenchmarkScenario(
        name="multi_port_rehandling",
        title="Multi-port rehandling scenario",
        description=(
            "Three-port route with mixed early, middle, and late destinations. "
            "The included reference layout has real rehandling, making the "
            "unloading metric easy to inspect."
        ),
        instance=instance,
        cg_tolerance_lon=0.75,
        cg_tolerance_lat=0.75,
        reference_solution=reference_solution,
        notes="Use final real rehandling for comparison; solver objectives may use proxies.",
    )


def _medium_scalability() -> BenchmarkScenario:
    instance = ProblemInstance(
        ship=Ship(
            bays=5,
            rows=4,
            tiers=3,
            reefer_slots=(
                (1, 1, 1),
                (1, 2, 1),
                (2, 1, 1),
                (2, 2, 1),
                (3, 1, 1),
                (3, 2, 1),
            ),
        ),
        route=Route(("Panama", "Brazil", "Spain", "Morocco")),
        containers=(
            Container("M001", 28.0, "Panama", ContainerType.NORMAL),
            Container("M002", 26.0, "Brazil", ContainerType.NORMAL),
            Container("M003", 24.0, "Spain", ContainerType.NORMAL),
            Container("M004", 22.0, "Morocco", ContainerType.NORMAL),
            Container("M005", 20.0, "Panama", ContainerType.REEFER),
            Container("M006", 18.0, "Brazil", ContainerType.REEFER),
            Container("M007", 16.0, "Spain", ContainerType.REEFER),
            Container("M008", 14.0, "Morocco", ContainerType.NORMAL),
            Container("M009", 12.0, "Panama", ContainerType.NORMAL),
            Container("M010", 10.0, "Brazil", ContainerType.NORMAL),
            Container("M011", 29.0, "Spain", ContainerType.FLAMMABLE),
            Container("M012", 27.0, "Morocco", ContainerType.OXIDIZER),
            Container("M013", 25.0, "Panama", ContainerType.NORMAL),
            Container("M014", 23.0, "Brazil", ContainerType.NORMAL),
            Container("M015", 21.0, "Spain", ContainerType.NORMAL),
            Container("M016", 19.0, "Morocco", ContainerType.NORMAL),
            Container("M017", 17.0, "Panama", ContainerType.NORMAL),
            Container("M018", 15.0, "Brazil", ContainerType.NORMAL),
        ),
    )
    return BenchmarkScenario(
        name="medium_scalability",
        title="Medium scalability scenario",
        description=(
            "Moderate 5 x 4 x 3 instance with 18 containers, reefers, dangerous "
            "cargo, and four destination ports."
        ),
        instance=instance,
        cg_tolerance_lon=0.70,
        cg_tolerance_lat=0.70,
        notes=(
            "Useful for manual runtime comparison. Keep heavyweight timing "
            "claims outside fragile pytest assertions."
        ),
    )


BENCHMARK_SCENARIOS: tuple[BenchmarkScenario, ...] = (
    _small_base(),
    _reefer_focus(),
    _incompatible_cargo(),
    _multi_port_rehandling(),
    _medium_scalability(),
)


def iter_benchmark_scenarios(
    names: tuple[str, ...] | list[str] | None = None,
) -> tuple[BenchmarkScenario, ...]:
    """Return scenarios in canonical order, optionally filtered by name."""
    if names is None:
        return BENCHMARK_SCENARIOS

    requested = {name.strip() for name in names}
    scenarios = tuple(scenario for scenario in BENCHMARK_SCENARIOS if scenario.name in requested)
    missing = requested.difference(scenario.name for scenario in scenarios)
    if missing:
        raise KeyError(f"Unknown benchmark scenario(s): {', '.join(sorted(missing))}.")
    return scenarios


def get_benchmark_scenario(name: str) -> BenchmarkScenario:
    """Return one named benchmark scenario."""
    return iter_benchmark_scenarios((name,))[0]
