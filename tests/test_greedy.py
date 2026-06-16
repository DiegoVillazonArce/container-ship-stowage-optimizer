import pytest

from stowage_optimizer.core import (
    Container,
    ContainerType,
    ProblemInstance,
    Route,
    Ship,
)
from stowage_optimizer.core.examples import create_small_example_instance
from stowage_optimizer.solvers import GreedySolver, SolverStatus


def _instance(ship: Ship, route: Route, containers: tuple[Container, ...]) -> ProblemInstance:
    return ProblemInstance(ship=ship, route=route, containers=containers)


def test_greedy_solves_small_example_instance() -> None:
    instance = create_small_example_instance()

    result = GreedySolver().solve(instance)

    assert result.status == SolverStatus.FEASIBLE
    assert result.is_feasible
    assert result.metrics.is_feasible
    # Every container is placed exactly once.
    assert len(result.solution.assignments) == len(instance.containers)
    assert result.metrics.unassigned_container_count == 0
    assert result.runtime_seconds >= 0.0


def test_greedy_places_heavier_container_in_lower_tier() -> None:
    # Single column, single port: only the vertical term differs between tiers.
    instance = _instance(
        Ship(bays=1, rows=1, tiers=2),
        Route(("Panama",)),
        (
            Container("LIGHT", 10.0, "Panama", ContainerType.NORMAL),
            Container("HEAVY", 30.0, "Panama", ContainerType.NORMAL),
        ),
    )

    result = GreedySolver().solve(instance)

    assert result.is_feasible
    assert result.solution.slot_for("HEAVY") == (1, 1, 1)  # bottom tier
    assert result.solution.slot_for("LIGHT") == (1, 1, 2)  # top tier


def test_greedy_assigns_reefer_to_reefer_slot() -> None:
    instance = _instance(
        Ship(bays=1, rows=2, tiers=1, reefer_slots=((1, 1, 1),)),
        Route(("Panama",)),
        (
            Container("REE", 10.0, "Panama", ContainerType.REEFER),
            Container("NRM", 10.0, "Panama", ContainerType.NORMAL),
        ),
    )

    result = GreedySolver().solve(instance)

    assert result.is_feasible
    assert result.solution.slot_for("REE") == (1, 1, 1)
    assert result.metrics.reefer_violations == 0


def test_greedy_retries_reefer_after_support_becomes_available() -> None:
    # The only reefer-capable slot is on tier 2. The reefer is processed first,
    # but it must wait until a normal container fills tier 1 as support.
    instance = _instance(
        Ship(bays=1, rows=1, tiers=2, reefer_slots=((1, 1, 2),)),
        Route(("Panama",)),
        (
            Container("REE", 10.0, "Panama", ContainerType.REEFER),
            Container("NRM", 20.0, "Panama", ContainerType.NORMAL),
        ),
    )

    result = GreedySolver().solve(instance)

    assert result.status == SolverStatus.FEASIBLE
    assert result.is_feasible
    assert result.solution.slot_for("NRM") == (1, 1, 1)
    assert result.solution.slot_for("REE") == (1, 1, 2)
    assert result.metrics.unassigned_container_count == 0


def test_greedy_separates_incompatible_cargo() -> None:
    # Two bays, two tiers: the oxidizer could share the flammable's bay, but
    # the penalty steers it to a different bay.
    instance = _instance(
        Ship(bays=2, rows=1, tiers=2),
        Route(("Panama",)),
        (
            Container("FLAM", 20.0, "Panama", ContainerType.FLAMMABLE),
            Container("OXID", 10.0, "Panama", ContainerType.OXIDIZER),
        ),
    )

    result = GreedySolver().solve(instance)

    assert result.is_feasible
    assert result.metrics.incompatible_cargo_violations == 0
    flammable_bay = result.solution.slot_for("FLAM")[0]
    oxidizer_bay = result.solution.slot_for("OXID")[0]
    assert flammable_bay != oxidizer_bay


def test_greedy_reports_infeasible_when_reefer_slot_missing() -> None:
    # Two reefer containers but only one reefer-capable slot.
    instance = _instance(
        Ship(bays=1, rows=1, tiers=2, reefer_slots=((1, 1, 1),)),
        Route(("Panama",)),
        (
            Container("R1", 10.0, "Panama", ContainerType.REEFER),
            Container("R2", 10.0, "Panama", ContainerType.REEFER),
        ),
    )

    result = GreedySolver().solve(instance)

    assert result.status == SolverStatus.INFEASIBLE
    assert not result.is_feasible
    assert result.metrics.unassigned_container_count == 1


def test_greedy_repairs_incompatible_layout_with_swap() -> None:
    # Three single-tier bays with a strict 2-bay separation rule. Greedy first
    # parks the flammable in the central bay (best for CG), which forces an
    # incompatible-cargo violation; a swap with the normal container fixes it.
    instance = _instance(
        Ship(bays=3, rows=1, tiers=1),
        Route(("Panama",)),
        (
            Container("C1", 10.0, "Panama", ContainerType.FLAMMABLE),
            Container("C2", 10.0, "Panama", ContainerType.OXIDIZER),
            Container("C3", 10.0, "Panama", ContainerType.NORMAL),
        ),
    )

    result = GreedySolver(min_incompatible_bay_distance=2).solve(instance)

    assert result.status == SolverStatus.REPAIRED
    assert result.is_feasible
    assert result.metrics.incompatible_cargo_violations == 0


def test_greedy_can_disable_repair() -> None:
    instance = _instance(
        Ship(bays=3, rows=1, tiers=1),
        Route(("Panama",)),
        (
            Container("C1", 10.0, "Panama", ContainerType.FLAMMABLE),
            Container("C2", 10.0, "Panama", ContainerType.OXIDIZER),
            Container("C3", 10.0, "Panama", ContainerType.NORMAL),
        ),
    )

    result = GreedySolver(min_incompatible_bay_distance=2, enable_repair=False).solve(instance)

    assert result.status == SolverStatus.INFEASIBLE
    assert result.metrics.incompatible_cargo_violations == 1
