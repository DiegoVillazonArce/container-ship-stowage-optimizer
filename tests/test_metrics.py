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
from stowage_optimizer.core.examples import create_small_example_instance


def _instance(ship: Ship, route: Route, containers: tuple[Container, ...]) -> ProblemInstance:
    return ProblemInstance(ship=ship, route=route, containers=containers)


def test_weight_utilization_moments_and_horizontal_cg() -> None:
    # 2x2x2 grid: bay1 x=-1, bay2 x=+1; row1 y=-1, row2 y=+1; tier1 z=0.
    instance = _instance(
        Ship(bays=2, rows=2, tiers=2),
        Route(("Panama",)),
        (
            Container("C001", 10.0, "Panama", ContainerType.NORMAL),
            Container("C002", 10.0, "Panama", ContainerType.NORMAL),
        ),
    )
    solution = StowageSolution.from_mapping({"C001": (1, 1, 1), "C002": (2, 2, 1)})

    metrics = evaluate_solution(instance, solution)

    assert metrics.total_weight == 20.0
    assert metrics.slot_utilization == pytest.approx(2 / 8)
    # Symmetric placement cancels both horizontal moments.
    assert metrics.longitudinal_moment == pytest.approx(0.0)
    assert metrics.lateral_moment == pytest.approx(0.0)
    assert metrics.cg_x == pytest.approx(0.0)
    assert metrics.cg_y == pytest.approx(0.0)
    assert metrics.within_lon_tolerance
    assert metrics.within_lat_tolerance
    # Side and end reporting splits the two containers.
    assert metrics.port_side_weight == 10.0
    assert metrics.starboard_side_weight == 10.0
    assert metrics.stern_weight == 10.0
    assert metrics.bow_weight == 10.0


def test_normalized_vertical_cg_weights_higher_tiers() -> None:
    # 1x1x2 column: tier1 z=0, tier2 z=1; heavy container placed on top.
    instance = _instance(
        Ship(bays=1, rows=1, tiers=2),
        Route(("Panama",)),
        (
            Container("C001", 10.0, "Panama", ContainerType.NORMAL),
            Container("C002", 30.0, "Panama", ContainerType.NORMAL),
        ),
    )
    solution = StowageSolution.from_mapping({"C001": (1, 1, 1), "C002": (1, 1, 2)})

    metrics = evaluate_solution(instance, solution)

    # CG_z = (10*0 + 30*1) / 40 = 0.75.
    assert metrics.cg_z_normalized == pytest.approx(0.75)
    assert metrics.slot_utilization == pytest.approx(1.0)


def test_horizontal_cg_tolerance_breach_is_flagged() -> None:
    # 2x1x1 grid: heavy weight pushes CG_x to +0.5, beyond the 0.25 default.
    instance = _instance(
        Ship(bays=2, rows=1, tiers=1),
        Route(("Panama",)),
        (
            Container("C001", 10.0, "Panama", ContainerType.NORMAL),
            Container("C002", 30.0, "Panama", ContainerType.NORMAL),
        ),
    )
    solution = StowageSolution.from_mapping({"C001": (1, 1, 1), "C002": (2, 1, 1)})

    metrics = evaluate_solution(instance, solution)

    assert metrics.cg_x == pytest.approx(0.5)
    assert not metrics.within_lon_tolerance
    assert metrics.within_lat_tolerance  # CG_y stays centered on a single row.


def test_reefer_violation_is_counted() -> None:
    instance = _instance(
        Ship(bays=1, rows=2, tiers=1, reefer_slots=((1, 1, 1),)),
        Route(("Panama",)),
        (Container("C001", 10.0, "Panama", ContainerType.REEFER),),
    )
    # Reefer container assigned to a non-reefer slot.
    solution = StowageSolution.from_mapping({"C001": (1, 2, 1)})

    metrics = evaluate_solution(instance, solution)

    assert metrics.reefer_violations == 1
    assert not metrics.is_feasible


def test_stack_continuity_violation_is_counted() -> None:
    instance = _instance(
        Ship(bays=1, rows=1, tiers=2),
        Route(("Panama",)),
        (Container("C001", 10.0, "Panama", ContainerType.NORMAL),),
    )
    # Container floats on tier 2 with nothing supporting it on tier 1.
    solution = StowageSolution.from_mapping({"C001": (1, 1, 2)})

    metrics = evaluate_solution(instance, solution)

    assert metrics.stack_continuity_violations == 1


def test_incompatible_cargo_violation_same_bay() -> None:
    instance = _instance(
        Ship(bays=1, rows=1, tiers=2),
        Route(("Panama",)),
        (
            Container("C001", 10.0, "Panama", ContainerType.FLAMMABLE),
            Container("C002", 10.0, "Panama", ContainerType.OXIDIZER),
        ),
    )
    # Both incompatible classes share bay 1.
    solution = StowageSolution.from_mapping({"C001": (1, 1, 1), "C002": (1, 1, 2)})

    metrics = evaluate_solution(instance, solution)

    assert metrics.incompatible_cargo_violations == 1


def test_incompatible_cargo_separation_respected_by_default() -> None:
    instance = _instance(
        Ship(bays=2, rows=1, tiers=1),
        Route(("Panama",)),
        (
            Container("C001", 10.0, "Panama", ContainerType.FLAMMABLE),
            Container("C002", 10.0, "Panama", ContainerType.OXIDIZER),
        ),
    )
    solution = StowageSolution.from_mapping({"C001": (1, 1, 1), "C002": (2, 1, 1)})

    # Distance of one bay is allowed by the default; a stricter rule flags it.
    assert evaluate_solution(instance, solution).incompatible_cargo_violations == 0
    strict = evaluate_solution(instance, solution, min_incompatible_bay_distance=2)
    assert strict.incompatible_cargo_violations == 1


def test_real_rehandling_zero_when_well_stowed() -> None:
    # Earlier-leaving cargo on top of later-leaving cargo: no blocking moves.
    instance = _instance(
        Ship(bays=1, rows=1, tiers=2),
        Route(("Panama", "Brazil")),
        (
            Container("C001", 10.0, "Brazil", ContainerType.NORMAL),
            Container("C002", 10.0, "Panama", ContainerType.NORMAL),
        ),
    )
    solution = StowageSolution.from_mapping({"C001": (1, 1, 1), "C002": (1, 1, 2)})

    metrics = evaluate_solution(instance, solution)

    assert metrics.real_rehandling == 0
    assert metrics.real_rehandling_normalized == pytest.approx(0.0)


def test_real_rehandling_counts_blocking_move() -> None:
    # Later-leaving cargo sits on top of earlier-leaving cargo: one rehandle.
    instance = _instance(
        Ship(bays=1, rows=1, tiers=2),
        Route(("Panama", "Brazil")),
        (
            Container("C001", 10.0, "Panama", ContainerType.NORMAL),
            Container("C002", 10.0, "Brazil", ContainerType.NORMAL),
        ),
    )
    solution = StowageSolution.from_mapping({"C001": (1, 1, 1), "C002": (1, 1, 2)})

    metrics = evaluate_solution(instance, solution)

    assert metrics.real_rehandling == 1
    # Max rehandling for one 2-tier stack is 1, so normalization is 1.0.
    assert metrics.real_rehandling_normalized == pytest.approx(1.0)


def test_unassigned_container_makes_solution_infeasible() -> None:
    instance = _instance(
        Ship(bays=1, rows=1, tiers=2),
        Route(("Panama",)),
        (
            Container("C001", 10.0, "Panama", ContainerType.NORMAL),
            Container("C002", 10.0, "Panama", ContainerType.NORMAL),
        ),
    )
    # Only one of the two containers is placed.
    solution = StowageSolution.from_mapping({"C001": (1, 1, 1)})

    metrics = evaluate_solution(instance, solution)

    assert metrics.unassigned_container_count == 1
    assert metrics.constraint_violations >= 1
    assert not metrics.is_feasible


def test_duplicate_slot_assignment_is_counted() -> None:
    instance = _instance(
        Ship(bays=1, rows=1, tiers=2),
        Route(("Panama",)),
        (
            Container("C001", 10.0, "Panama", ContainerType.NORMAL),
            Container("C002", 10.0, "Panama", ContainerType.NORMAL),
        ),
    )
    # Both containers target the same slot.
    solution = StowageSolution.from_mapping({"C001": (1, 1, 1), "C002": (1, 1, 1)})

    metrics = evaluate_solution(instance, solution)

    assert metrics.duplicate_slot_violations == 1
    assert metrics.slot_utilization == pytest.approx(1 / 2)
    assert not metrics.is_feasible


def test_cg_tolerance_does_not_affect_structural_feasibility() -> None:
    # 2x1x1 grid with all weight on one bay: CG_x breaches the default
    # tolerance, so the assignment is structurally valid but not operationally
    # feasible.
    instance = _instance(
        Ship(bays=2, rows=1, tiers=1),
        Route(("Panama",)),
        (
            Container("C001", 10.0, "Panama", ContainerType.NORMAL),
            Container("C002", 30.0, "Panama", ContainerType.NORMAL),
        ),
    )
    solution = StowageSolution.from_mapping({"C001": (1, 1, 1), "C002": (2, 1, 1)})

    metrics = evaluate_solution(instance, solution)

    assert not metrics.within_lon_tolerance
    assert metrics.constraint_violations == 0
    assert metrics.is_structurally_feasible
    assert not metrics.cg_within_tolerance
    assert not metrics.operationally_feasible
    assert not metrics.is_feasible


def test_unknown_container_in_solution_raises() -> None:
    instance = _instance(
        Ship(bays=1, rows=1, tiers=1),
        Route(("Panama",)),
        (Container("C001", 10.0, "Panama", ContainerType.NORMAL),),
    )
    solution = StowageSolution.from_mapping({"C999": (1, 1, 1)})

    with pytest.raises(ValueError, match="unknown container"):
        evaluate_solution(instance, solution)


def test_example_instance_evaluates_as_feasible() -> None:
    instance = create_small_example_instance()
    solution = StowageSolution.from_mapping(
        {
            "C001": (3, 3, 1),
            "C002": (2, 2, 1),  # reefer container in a reefer-capable slot
            "C003": (5, 3, 1),  # flammable
            "C004": (3, 2, 1),  # oxidizer, separated from the flammable
        }
    )

    metrics = evaluate_solution(instance, solution)

    assert metrics.total_weight == pytest.approx(87.0)
    assert metrics.is_feasible
    assert metrics.is_structurally_feasible
    assert metrics.cg_within_tolerance
    assert metrics.as_dict()["constraint_violations"] == 0
