from stowage_optimizer.core import (
    Container,
    ContainerType,
    ProblemInstance,
    Route,
    Ship,
    StowageMetrics,
)
from stowage_optimizer.core.examples import create_small_example_instance
from stowage_optimizer.solvers import MILPSolver, SolverResult, SolverStatus


def _instance(ship: Ship, route: Route, containers: tuple[Container, ...]) -> ProblemInstance:
    return ProblemInstance(ship=ship, route=route, containers=containers)


def test_milp_solves_small_example_instance() -> None:
    instance = create_small_example_instance()

    result = MILPSolver().solve(instance)

    assert result.status == SolverStatus.FEASIBLE
    assert result.is_feasible
    assert result.metrics.is_feasible
    # Every container is placed exactly once on a distinct slot.
    assert len(result.solution.assignments) == len(instance.containers)
    assert result.metrics.unassigned_container_count == 0
    assert result.metrics.duplicate_slot_violations == 0
    assert result.runtime_seconds >= 0.0
    # The exact solver reports its objective value.
    assert result.objective_value is not None


def test_milp_result_uses_common_interface() -> None:
    instance = create_small_example_instance()

    result = MILPSolver().solve(instance)

    assert isinstance(result, SolverResult)
    assert isinstance(result.metrics, StowageMetrics)
    assert result.status in tuple(SolverStatus)
    assert result.solution is result.solution  # solution is a StowageSolution
    assert result.metrics.as_dict()["is_feasible"] is True
    # CBC does not expose an optimality gap through PuLP.
    assert result.gap is None


def test_milp_places_heavier_container_lower_and_keeps_continuity() -> None:
    # Single column, single port: the optimal plan keeps the heavy container low
    # (vertical penalty) and the stack continuous (no floating container).
    instance = _instance(
        Ship(bays=1, rows=1, tiers=2),
        Route(("Panama",)),
        (
            Container("LIGHT", 10.0, "Panama", ContainerType.NORMAL),
            Container("HEAVY", 30.0, "Panama", ContainerType.NORMAL),
        ),
    )

    result = MILPSolver().solve(instance)

    assert result.is_feasible
    assert result.metrics.stack_continuity_violations == 0
    assert result.solution.slot_for("HEAVY") == (1, 1, 1)  # bottom tier
    assert result.solution.slot_for("LIGHT") == (1, 1, 2)  # top tier


def test_milp_enforces_stack_continuity_for_single_container() -> None:
    # One container in a two-tier stack must sit on the bottom tier; placing it
    # on tier 2 alone would float above an empty slot.
    instance = _instance(
        Ship(bays=1, rows=1, tiers=2),
        Route(("Panama",)),
        (Container("ONLY", 12.0, "Panama", ContainerType.NORMAL),),
    )

    result = MILPSolver().solve(instance)

    assert result.is_feasible
    assert result.solution.slot_for("ONLY") == (1, 1, 1)
    assert result.metrics.stack_continuity_violations == 0


def test_milp_reports_infeasible_when_slots_are_missing() -> None:
    # Two containers but only one slot: complete assignment is impossible.
    instance = _instance(
        Ship(bays=1, rows=1, tiers=1),
        Route(("Panama",)),
        (
            Container("C1", 10.0, "Panama", ContainerType.NORMAL),
            Container("C2", 10.0, "Panama", ContainerType.NORMAL),
        ),
    )

    result = MILPSolver().solve(instance)

    assert result.status == SolverStatus.INFEASIBLE
    assert not result.is_feasible
    assert result.objective_value is None
    assert len(result.solution.assignments) == 0


def test_milp_reports_not_solved_separately_from_infeasible() -> None:
    # A zero-second limit prevents CBC from certifying a result. The instance
    # itself is feasible, so this must not be reported as mathematical
    # infeasibility.
    instance = create_small_example_instance()

    result = MILPSolver(time_limit_seconds=0.0).solve(instance)

    assert result.status == SolverStatus.NOT_SOLVED
    assert not result.is_feasible
    assert result.solver_status_detail == "Not Solved"
    assert result.objective_value is None
    assert result.metrics.unassigned_container_count == len(instance.containers)


def test_milp_reports_infeasible_when_reefer_slot_missing() -> None:
    # A reefer container with no reefer-capable slot cannot be placed.
    instance = _instance(
        Ship(bays=2, rows=1, tiers=1),  # two slots, none reefer-capable
        Route(("Panama",)),
        (Container("REE", 10.0, "Panama", ContainerType.REEFER),),
    )

    result = MILPSolver().solve(instance)

    assert result.status == SolverStatus.INFEASIBLE
    assert not result.is_feasible


def test_milp_assigns_reefer_to_reefer_slot() -> None:
    instance = _instance(
        Ship(bays=1, rows=2, tiers=1, reefer_slots=((1, 1, 1),)),
        Route(("Panama",)),
        (
            Container("REE", 10.0, "Panama", ContainerType.REEFER),
            Container("NRM", 10.0, "Panama", ContainerType.NORMAL),
        ),
    )

    result = MILPSolver().solve(instance)

    assert result.is_feasible
    assert result.solution.slot_for("REE") == (1, 1, 1)
    assert result.metrics.reefer_violations == 0


def test_milp_separates_incompatible_cargo() -> None:
    # Three single-tier bays with a strict 2-bay separation rule. The flammable
    # and oxidizer must end up at least two bays apart (bays 1 and 3).
    instance = _instance(
        Ship(bays=3, rows=1, tiers=1),
        Route(("Panama",)),
        (
            Container("FLAM", 20.0, "Panama", ContainerType.FLAMMABLE),
            Container("OXID", 10.0, "Panama", ContainerType.OXIDIZER),
        ),
    )

    # Relax the horizontal CG tolerance so this case isolates separation: with
    # only bays 1 and 3 usable, the longitudinal CG would otherwise dominate.
    result = MILPSolver(
        min_incompatible_bay_distance=2,
        cg_tolerance_lon=1.0,
        cg_tolerance_lat=1.0,
    ).solve(instance)

    assert result.is_feasible
    assert result.metrics.incompatible_cargo_violations == 0
    flammable_bay = result.solution.slot_for("FLAM")[0]
    oxidizer_bay = result.solution.slot_for("OXID")[0]
    assert abs(flammable_bay - oxidizer_bay) >= 2


def test_milp_respects_cg_tolerance_when_balance_is_possible() -> None:
    # Two equal-weight containers across the centerline can be perfectly
    # balanced, so a strict lateral tolerance is satisfiable.
    instance = _instance(
        Ship(bays=1, rows=2, tiers=1),
        Route(("Panama",)),
        (
            Container("A", 10.0, "Panama", ContainerType.NORMAL),
            Container("B", 10.0, "Panama", ContainerType.NORMAL),
        ),
    )

    result = MILPSolver(cg_tolerance_lat=0.0).solve(instance)

    assert result.is_feasible
    assert result.metrics.within_lat_tolerance
    assert result.metrics.cg_y == 0.0


def test_milp_infeasible_when_cg_tolerance_cannot_be_met() -> None:
    # Unequal weights on the only two opposing slots cannot balance laterally,
    # so a zero lateral tolerance makes the CG hard constraint infeasible.
    instance = _instance(
        Ship(bays=1, rows=2, tiers=1),
        Route(("Panama",)),
        (
            Container("LIGHT", 10.0, "Panama", ContainerType.NORMAL),
            Container("HEAVY", 30.0, "Panama", ContainerType.NORMAL),
        ),
    )

    result = MILPSolver(cg_tolerance_lat=0.0).solve(instance)

    assert result.status == SolverStatus.INFEASIBLE
    assert not result.is_feasible
