"""Small integration scenarios used as lightweight benchmark smoke tests."""

from stowage_optimizer.core import Container, ContainerType, ProblemInstance, Route, Ship
from stowage_optimizer.core.examples import create_small_example_instance
from stowage_optimizer.solvers import GeneticSolver, GreedySolver, MILPSolver


def test_small_example_scenario_is_solved_by_all_solvers() -> None:
    instance = create_small_example_instance()

    _assert_all_solvers_feasible(instance)


def test_tight_reefer_scenario_is_solved_by_all_solvers() -> None:
    instance = ProblemInstance(
        ship=Ship(bays=1, rows=2, tiers=1, reefer_slots=((1, 1, 1),)),
        route=Route(("Panama", "Brazil")),
        containers=(
            Container("REE", 10.0, "Panama", ContainerType.REEFER),
            Container("NRM", 10.0, "Brazil", ContainerType.NORMAL),
        ),
    )

    _assert_all_solvers_feasible(instance)


def test_strict_incompatible_cargo_scenario_is_solved_by_all_solvers() -> None:
    instance = ProblemInstance(
        ship=Ship(bays=3, rows=1, tiers=1),
        route=Route(("Panama",)),
        containers=(
            Container("FLAM", 10.0, "Panama", ContainerType.FLAMMABLE),
            Container("OXID", 10.0, "Panama", ContainerType.OXIDIZER),
            Container("NRM", 10.0, "Panama", ContainerType.NORMAL),
        ),
    )

    _assert_all_solvers_feasible(instance, min_incompatible_bay_distance=2)


def _assert_all_solvers_feasible(
    instance: ProblemInstance,
    *,
    min_incompatible_bay_distance: int = 1,
) -> None:
    solvers = (
        GreedySolver(min_incompatible_bay_distance=min_incompatible_bay_distance),
        MILPSolver(min_incompatible_bay_distance=min_incompatible_bay_distance),
        GeneticSolver(
            population_size=16,
            max_generations=12,
            random_seed=17,
            min_incompatible_bay_distance=min_incompatible_bay_distance,
        ),
    )

    for solver in solvers:
        result = solver.solve(instance)
        assert result.is_feasible, (
            f"{solver.name} failed benchmark smoke scenario: "
            f"status={result.status}, metrics={result.metrics.as_dict()}"
        )
