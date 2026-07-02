import pytest

from stowage_optimizer.core import (
    Container,
    ContainerType,
    ProblemInstance,
    Route,
    Ship,
    StowageMetrics,
    StowageSolution,
    evaluate_solution,
)
from stowage_optimizer.core.examples import create_small_example_instance
from stowage_optimizer.solvers import (
    GeneticConfig,
    GeneticSolver,
    GreedySolver,
    MILPSolver,
    SolverResult,
    SolverStatus,
)


def _instance(ship: Ship, route: Route, containers: tuple[Container, ...]) -> ProblemInstance:
    return ProblemInstance(ship=ship, route=route, containers=containers)


def test_genetic_solves_small_example_instance() -> None:
    instance = create_small_example_instance()

    result = GeneticSolver(
        population_size=16,
        max_generations=12,
        random_seed=7,
    ).solve(instance)

    assert result.status == SolverStatus.FEASIBLE
    assert result.is_feasible
    assert result.metrics.is_feasible
    assert len(result.solution.assignments) == len(instance.containers)
    assert result.metrics.unassigned_container_count == 0
    assert result.runtime_seconds >= 0.0


def test_genetic_result_uses_common_interface() -> None:
    instance = create_small_example_instance()

    result = GeneticSolver(population_size=8, max_generations=3, random_seed=1).solve(instance)

    assert isinstance(result, SolverResult)
    assert isinstance(result.metrics, StowageMetrics)
    assert result.status in tuple(SolverStatus)
    assert result.objective_value is None
    assert result.gap is None


def test_genetic_is_reproducible_with_random_seed() -> None:
    instance = create_small_example_instance()

    first = GeneticSolver(population_size=14, max_generations=8, random_seed=21).solve(instance)
    second = GeneticSolver(population_size=14, max_generations=8, random_seed=21).solve(instance)

    assert first.solution.assignment_map == second.solution.assignment_map
    assert first.metrics.as_dict() == second.metrics.as_dict()


def test_genetic_encoding_and_decoding_preserve_containers() -> None:
    instance = _instance(
        Ship(bays=1, rows=2, tiers=1),
        Route(("Panama",)),
        (
            Container("C1", 10.0, "Panama", ContainerType.NORMAL),
            Container("C2", 10.0, "Panama", ContainerType.NORMAL),
        ),
    )
    solution = StowageSolution.from_mapping({"C1": (1, 1, 1), "C2": (1, 2, 1)})
    solver = GeneticSolver(random_seed=1)

    chromosome = solver._encode(instance, solution)
    decoded = solver._decode(instance, chromosome)

    assert decoded.assignment_map == solution.assignment_map
    assert decoded.assigned_container_ids == ("C1", "C2")


def test_genetic_repair_avoids_duplicate_slots_when_possible() -> None:
    instance = _instance(
        Ship(bays=1, rows=2, tiers=1),
        Route(("Panama",)),
        (
            Container("C1", 10.0, "Panama", ContainerType.NORMAL),
            Container("C2", 10.0, "Panama", ContainerType.NORMAL),
        ),
    )
    solver = GeneticSolver(random_seed=1)

    repaired = solver._repair_chromosome(instance, ((1, 1, 1), (1, 1, 1)))
    assigned_slots = [slot for slot in repaired if slot is not None]
    metrics = evaluate_solution(instance, solver._decode(instance, repaired))

    assert len(assigned_slots) == 2
    assert len(set(assigned_slots)) == 2
    assert metrics.duplicate_slot_violations == 0
    assert metrics.unassigned_container_count == 0


def test_genetic_fitness_penalizes_invalid_solutions() -> None:
    instance = _instance(
        Ship(bays=1, rows=2, tiers=1),
        Route(("Panama",)),
        (
            Container("C1", 10.0, "Panama", ContainerType.NORMAL),
            Container("C2", 10.0, "Panama", ContainerType.NORMAL),
        ),
    )
    solver = GeneticSolver(random_seed=1)

    valid = ((1, 1, 1), (1, 2, 1))
    duplicate_slot = ((1, 1, 1), (1, 1, 1))

    assert solver._fitness(instance, duplicate_slot) > solver._fitness(instance, valid)


def test_genetic_respects_reefer_compatibility() -> None:
    instance = _instance(
        Ship(bays=1, rows=2, tiers=1, reefer_slots=((1, 1, 1),)),
        Route(("Panama",)),
        (
            Container("REE", 10.0, "Panama", ContainerType.REEFER),
            Container("NRM", 10.0, "Panama", ContainerType.NORMAL),
        ),
    )

    result = GeneticSolver(population_size=10, max_generations=5, random_seed=3).solve(instance)

    assert result.is_feasible
    assert result.solution.slot_for("REE") == (1, 1, 1)
    assert result.metrics.reefer_violations == 0


def test_genetic_produces_feasible_solution_in_simple_stack_case() -> None:
    instance = _instance(
        Ship(bays=1, rows=1, tiers=2),
        Route(("Panama",)),
        (
            Container("LIGHT", 10.0, "Panama", ContainerType.NORMAL),
            Container("HEAVY", 30.0, "Panama", ContainerType.NORMAL),
        ),
    )

    result = GeneticSolver(population_size=8, max_generations=6, random_seed=5).solve(instance)

    assert result.is_feasible
    assert result.metrics.stack_continuity_violations == 0
    assert result.solution.slot_for("HEAVY") == (1, 1, 1)
    assert result.solution.slot_for("LIGHT") == (1, 1, 2)


def test_genetic_reports_infeasible_when_capacity_is_insufficient() -> None:
    instance = _instance(
        Ship(bays=1, rows=1, tiers=1),
        Route(("Panama",)),
        (
            Container("C1", 10.0, "Panama", ContainerType.NORMAL),
            Container("C2", 10.0, "Panama", ContainerType.NORMAL),
        ),
    )

    result = GeneticSolver(population_size=8, max_generations=5, random_seed=9).solve(instance)

    assert result.status == SolverStatus.INFEASIBLE
    assert not result.is_feasible
    assert result.solution.assignments == ()
    assert result.metrics.unassigned_container_count == 2
    assert result.solver_status_detail is not None
    assert "Validation failed" in result.solver_status_detail


def test_genetic_validates_instance_before_solving() -> None:
    instance = _instance(
        Ship(bays=1, rows=2, tiers=1),
        Route(("Panama",)),
        (
            Container("C1", 10.0, "Panama", ContainerType.NORMAL),
            Container("C1", 20.0, "Panama", ContainerType.NORMAL),
        ),
    )

    result = GeneticSolver(population_size=8, max_generations=5, random_seed=9).solve(instance)

    assert result.status == SolverStatus.INFEASIBLE
    assert not result.is_feasible
    assert result.solution.assignments == ()
    assert result.solver_status_detail is not None
    assert "Validation failed" in result.solver_status_detail


def test_genetic_separates_incompatible_cargo_when_possible() -> None:
    instance = _instance(
        Ship(bays=3, rows=1, tiers=1),
        Route(("Panama",)),
        (
            Container("FLAM", 10.0, "Panama", ContainerType.FLAMMABLE),
            Container("OXID", 10.0, "Panama", ContainerType.OXIDIZER),
            Container("NRM", 10.0, "Panama", ContainerType.NORMAL),
        ),
    )

    result = GeneticSolver(
        population_size=12,
        max_generations=8,
        random_seed=13,
        min_incompatible_bay_distance=2,
    ).solve(instance)

    assert result.is_feasible
    assert result.metrics.incompatible_cargo_violations == 0
    assert abs(result.solution.slot_for("FLAM")[0] - result.solution.slot_for("OXID")[0]) >= 2


def test_genetic_rejects_out_of_range_swap_mutation_probability() -> None:
    with pytest.raises(ValueError, match="swap_mutation_probability"):
        GeneticSolver(config=GeneticConfig(swap_mutation_probability=1.5))


def test_genetic_rejects_out_of_range_drop_mutation_probability() -> None:
    with pytest.raises(ValueError, match="drop_mutation_probability"):
        GeneticSolver(config=GeneticConfig(drop_mutation_probability=-0.1))


def test_genetic_mutation_shape_is_configurable() -> None:
    instance = create_small_example_instance()
    config = GeneticConfig(
        population_size=10,
        max_generations=5,
        random_seed=11,
        swap_mutation_probability=0.9,
        drop_mutation_probability=0.5,
    )

    result = GeneticSolver(config=config).solve(instance)

    assert result.is_feasible


def test_genetic_does_not_break_greedy_or_milp() -> None:
    instance = create_small_example_instance()

    assert GreedySolver().solve(instance).is_feasible
    assert MILPSolver().solve(instance).is_feasible
