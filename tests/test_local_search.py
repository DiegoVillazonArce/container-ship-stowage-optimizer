import pytest

from stowage_optimizer.core import (
    Container,
    ContainerType,
    ProblemInstance,
    Route,
    Ship,
    StowageSolution,
    evaluate_solution,
)
from stowage_optimizer.solvers import (
    GeneticSolver,
    GreedySolver,
    LocalSearchConfig,
    SolverStatus,
    improve_solution,
)


def _instance(ship: Ship, route: Route, containers: tuple[Container, ...]) -> ProblemInstance:
    return ProblemInstance(ship=ship, route=route, containers=containers)


def _cg_improvement_instance() -> ProblemInstance:
    return _instance(
        Ship(bays=3, rows=1, tiers=1),
        Route(("Panama",)),
        (
            Container("H", 30.0, "Panama", ContainerType.NORMAL),
            Container("M", 29.0, "Panama", ContainerType.NORMAL),
            Container("L", 1.0, "Panama", ContainerType.NORMAL),
        ),
    )


def test_local_search_preserves_hard_constraints_on_hand_checkable_instance() -> None:
    instance = _instance(
        Ship(bays=3, rows=2, tiers=1, reefer_slots=((2, 1, 1),)),
        Route(("Panama", "Brazil")),
        (
            Container("REE", 18.0, "Brazil", ContainerType.REEFER),
            Container("FLAM", 12.0, "Panama", ContainerType.FLAMMABLE),
            Container("OXID", 10.0, "Brazil", ContainerType.OXIDIZER),
            Container("NORM", 15.0, "Panama", ContainerType.NORMAL),
        ),
    )
    solution = StowageSolution.from_mapping(
        {
            "FLAM": (1, 1, 1),
            "REE": (2, 1, 1),
            "NORM": (2, 2, 1),
            "OXID": (3, 2, 1),
        }
    )

    result = improve_solution(
        instance,
        solution,
        config=LocalSearchConfig(max_iterations=20, min_incompatible_bay_distance=2),
    )
    final_metrics = evaluate_solution(
        instance,
        result.solution,
        min_incompatible_bay_distance=2,
    )

    assert result.ran
    assert len(result.solution.assignments) == len(instance.containers)
    assert len(set(result.solution.assignment_map.values())) == len(instance.containers)
    assert final_metrics.constraint_violations == 0
    assert final_metrics.reefer_violations == 0
    assert final_metrics.stack_continuity_violations == 0
    assert final_metrics.incompatible_cargo_violations == 0


def test_local_search_improves_horizontal_cg_with_clear_swap() -> None:
    instance = _cg_improvement_instance()
    solution = StowageSolution.from_mapping(
        {"H": (2, 1, 1), "M": (1, 1, 1), "L": (3, 1, 1)}
    )
    before = evaluate_solution(instance, solution, cg_tolerance_lon=0.25)

    result = improve_solution(
        instance,
        solution,
        config=LocalSearchConfig(
            max_iterations=10,
            max_rounds_without_improvement=1,
            cg_tolerance_lon=0.25,
        ),
    )

    assert result.accepted_swaps >= 1
    assert abs(result.metrics.cg_x) < abs(before.cg_x)
    assert not before.operationally_feasible
    assert result.metrics.operationally_feasible
    assert result.became_operationally_feasible


def test_local_search_improves_real_rehandling_when_swap_is_available() -> None:
    instance = _instance(
        Ship(bays=1, rows=1, tiers=2),
        Route(("Panama", "Brazil")),
        (
            Container("EARLY", 10.0, "Panama", ContainerType.NORMAL),
            Container("LATE", 10.0, "Brazil", ContainerType.NORMAL),
        ),
    )
    solution = StowageSolution.from_mapping(
        {"EARLY": (1, 1, 1), "LATE": (1, 1, 2)}
    )
    before = evaluate_solution(instance, solution)

    result = improve_solution(
        instance,
        solution,
        config=LocalSearchConfig(max_iterations=5, max_rounds_without_improvement=1),
    )

    assert before.real_rehandling == 1
    assert result.metrics.real_rehandling == 0
    assert result.rehandling_improvement == 1
    assert result.metrics.constraint_violations == 0


def test_local_search_rejects_swap_that_breaks_reefer_compatibility() -> None:
    instance = _instance(
        Ship(bays=1, rows=3, tiers=1, reefer_slots=((1, 1, 1),)),
        Route(("Panama",)),
        (
            Container("REE", 30.0, "Panama", ContainerType.REEFER),
            Container("NORM", 10.0, "Panama", ContainerType.NORMAL),
        ),
    )
    solution = StowageSolution.from_mapping({"REE": (1, 1, 1), "NORM": (1, 2, 1)})

    result = improve_solution(
        instance,
        solution,
        config=LocalSearchConfig(
            max_iterations=5,
            max_rounds_without_improvement=1,
            cg_tolerance_lat=0.0,
        ),
    )

    assert result.accepted_swaps == 0
    assert result.solution.assignment_map == solution.assignment_map
    assert result.metrics.reefer_violations == 0


def test_local_search_skips_initial_solution_with_stack_continuity_violation() -> None:
    instance = _instance(
        Ship(bays=1, rows=2, tiers=2),
        Route(("Panama",)),
        (
            Container("A", 10.0, "Panama", ContainerType.NORMAL),
            Container("B", 10.0, "Panama", ContainerType.NORMAL),
        ),
    )
    solution = StowageSolution.from_mapping({"A": (1, 1, 2), "B": (1, 2, 1)})

    result = improve_solution(instance, solution)

    assert not result.ran
    assert result.stopped_reason == "initial_solution_structurally_infeasible"
    assert result.accepted_swaps == 0
    assert result.solution.assignment_map == solution.assignment_map
    assert result.metrics.stack_continuity_violations == 1


def test_local_search_rejects_swap_that_breaks_incompatible_cargo_separation() -> None:
    instance = _instance(
        Ship(bays=3, rows=1, tiers=1),
        Route(("Panama",)),
        (
            Container("FLAM", 10.0, "Panama", ContainerType.FLAMMABLE),
            Container("NORM", 10.0, "Panama", ContainerType.NORMAL),
            Container("OXID", 30.0, "Panama", ContainerType.OXIDIZER),
        ),
    )
    solution = StowageSolution.from_mapping(
        {"FLAM": (1, 1, 1), "NORM": (2, 1, 1), "OXID": (3, 1, 1)}
    )

    result = improve_solution(
        instance,
        solution,
        config=LocalSearchConfig(
            max_iterations=10,
            max_rounds_without_improvement=1,
            min_incompatible_bay_distance=2,
        ),
    )

    assert result.accepted_swaps == 0
    assert result.solution.assignment_map == solution.assignment_map
    assert result.metrics.incompatible_cargo_violations == 0


def test_local_search_stops_at_max_iterations() -> None:
    instance = _cg_improvement_instance()
    solution = StowageSolution.from_mapping(
        {"H": (2, 1, 1), "M": (1, 1, 1), "L": (3, 1, 1)}
    )

    result = improve_solution(
        instance,
        solution,
        config=LocalSearchConfig(max_iterations=1, max_rounds_without_improvement=1),
    )

    assert result.evaluated_swaps == 1
    assert result.iterations_evaluated == 1
    assert result.stopped_reason == "max_iterations"


def test_local_search_stops_after_round_without_improvement() -> None:
    instance = _instance(
        Ship(bays=3, rows=1, tiers=1),
        Route(("Panama",)),
        (
            Container("A", 10.0, "Panama", ContainerType.NORMAL),
            Container("B", 10.0, "Panama", ContainerType.NORMAL),
            Container("C", 10.0, "Panama", ContainerType.NORMAL),
        ),
    )
    solution = StowageSolution.from_mapping(
        {"A": (1, 1, 1), "B": (2, 1, 1), "C": (3, 1, 1)}
    )

    result = improve_solution(
        instance,
        solution,
        config=LocalSearchConfig(max_iterations=10, max_rounds_without_improvement=1),
    )

    assert result.accepted_swaps == 0
    assert result.evaluated_swaps == 3
    assert result.rounds_completed == 1
    assert result.stopped_reason == "no_improvement"


def test_greedy_local_search_option_updates_final_metrics() -> None:
    instance = _cg_improvement_instance()
    baseline = GreedySolver().solve(instance)

    improved = GreedySolver(
        enable_local_search=True,
        local_search_config=LocalSearchConfig(max_iterations=10),
    ).solve(instance)

    assert baseline.status == SolverStatus.INFEASIBLE
    assert baseline.metrics.is_structurally_feasible
    assert not baseline.metrics.cg_within_tolerance
    assert improved.status == SolverStatus.FEASIBLE
    assert improved.is_feasible
    assert improved.local_search_result is not None
    assert improved.local_search_result.accepted_swaps >= 1
    assert abs(improved.metrics.cg_x) < abs(baseline.metrics.cg_x)


def test_genetic_local_search_option_updates_final_metrics() -> None:
    instance = _cg_improvement_instance()

    result = GeneticSolver(
        population_size=1,
        max_generations=0,
        random_seed=1,
        enable_local_search=True,
        local_search_config=LocalSearchConfig(max_iterations=10),
    ).solve(instance)

    assert result.status == SolverStatus.FEASIBLE
    assert result.is_feasible
    assert result.local_search_result is not None
    assert result.local_search_result.accepted_swaps >= 1
    assert result.metrics.cg_within_tolerance


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("max_iterations", -1),
        ("max_rounds_without_improvement", 0),
        ("time_limit_seconds", -0.1),
    ),
)
def test_local_search_rejects_invalid_config(field: str, value: int | float) -> None:
    kwargs = {field: value}
    config = LocalSearchConfig(**kwargs)
    instance = _cg_improvement_instance()
    solution = StowageSolution.from_mapping(
        {"H": (2, 1, 1), "M": (1, 1, 1), "L": (3, 1, 1)}
    )

    with pytest.raises(ValueError):
        improve_solution(instance, solution, config=config)
