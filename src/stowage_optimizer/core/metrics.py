"""Common metrics engine shared by every solver.

This module evaluates a complete :class:`StowageSolution` against a
:class:`ProblemInstance` without calling any solver. It produces the common
final metrics used to compare Greedy, MILP, and Genetic Algorithm outputs:
total weight, utilization, horizontal/vertical center of gravity, side and
end balance reporting, constraint violation counts, and real rehandling
computed by simulated port-by-port unloading.

Axis convention (see DESIGN.md sections 5 and 10):

- ``x`` -> longitudinal direction -> ``CG_x`` -> longitudinal moment.
- ``y`` -> lateral direction      -> ``CG_y`` -> lateral moment.
- ``z`` -> vertical direction     -> ``CG_z`` (normalized in ``[0, 1]``).

Reporting convention for the visual balance metrics:

- Lateral: ``y < 0`` is port side, ``y > 0`` is starboard side.
- Longitudinal: ``x > 0`` is bow (forward), ``x < 0`` is stern (aft).
- Containers exactly on a centerline (coordinate ``0.0``) are reported as
  centered and excluded from both opposing sides.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any, NamedTuple

from stowage_optimizer.core.container import Container, ContainerType
from stowage_optimizer.core.problem import ProblemInstance
from stowage_optimizer.core.ship import Slot
from stowage_optimizer.core.solution import SlotPosition, StowageSolution

# Default minimum bay separation between Flammable and Oxidizer cargo.
# A value of ``1`` means incompatible cargo may not share the same bay
# (``abs(b1 - b2) < 1`` is only true for the same bay).
DEFAULT_MIN_INCOMPATIBLE_BAY_DISTANCE = 1

# Default horizontal CG tolerances used by the tolerance checks. These are
# normalized deviations from the vessel geometric center (``[-1, 1]`` axes).
DEFAULT_CG_TOLERANCE_LON = 0.25
DEFAULT_CG_TOLERANCE_LAT = 0.25


class _Placement(NamedTuple):
    """One resolved assignment: a container paired with its physical slot."""

    container: Container
    slot: Slot


@dataclass(frozen=True, slots=True)
class UnloadingStep:
    """One simulated unloading step for a route port.

    ``remaining_assignment`` contains only the containers still onboard after
    unloading ``port``. Each remaining stack is compacted bottom-up while
    preserving its relative order, matching the simplified unloading model used
    for the real rehandling metric.
    """

    port: str
    removed_container_ids: tuple[str, ...]
    rehandled_container_ids: tuple[str, ...]
    remaining_assignment: StowageSolution

    @property
    def rehandle_count(self) -> int:
        """Return the number of blocking moves for this port."""
        return len(self.rehandled_container_ids)


@dataclass(frozen=True, slots=True)
class StowageMetrics:
    """Deterministic evaluation of a complete stowage solution."""

    total_weight: float
    slot_utilization: float
    longitudinal_moment: float
    lateral_moment: float
    cg_x: float
    cg_y: float
    cg_z_normalized: float
    port_side_weight: float
    starboard_side_weight: float
    bow_weight: float
    stern_weight: float
    within_lon_tolerance: bool
    within_lat_tolerance: bool
    unassigned_container_count: int
    duplicate_slot_violations: int
    reefer_violations: int
    stack_continuity_violations: int
    incompatible_cargo_violations: int
    real_rehandling: int
    real_rehandling_normalized: float

    @property
    def constraint_violations(self) -> int:
        """Total count of structural hard-constraint violations for diagnostics.

        Covers the structural feasibility rules of DESIGN.md section 8:
        complete unique assignment, slot capacity, stack continuity, reefer
        compatibility, and incompatible-cargo separation. Horizontal CG
        tolerance is intentionally excluded here and reported separately via
        :attr:`within_lon_tolerance` and :attr:`within_lat_tolerance`, because
        those bounds are caller-configurable and a structurally valid plan may
        still be deliberately unbalanced (for example a row-edge test layout).
        """
        return (
            self.unassigned_container_count
            + self.duplicate_slot_violations
            + self.reefer_violations
            + self.stack_continuity_violations
            + self.incompatible_cargo_violations
        )

    @property
    def is_structurally_feasible(self) -> bool:
        """Return whether all non-CG hard structural rules are satisfied.

        True when no container is unassigned, no two containers share a slot,
        and no reefer, stack-continuity, or incompatible-cargo rule is broken.
        Horizontal CG tolerance is intentionally exposed as a separate signal
        because callers may need to distinguish a physically complete layout
        from one that also satisfies the configured balance tolerances.
        """
        return self.constraint_violations == 0

    @property
    def cg_within_tolerance(self) -> bool:
        """Return whether both horizontal CG checks pass."""
        return self.within_lon_tolerance and self.within_lat_tolerance

    @property
    def operationally_feasible(self) -> bool:
        """Return whether the solution is structurally valid and balanced."""
        return self.is_structurally_feasible and self.cg_within_tolerance

    @property
    def is_feasible(self) -> bool:
        """Return whether the solution satisfies structural and CG rules.

        This is the overall operational feasibility flag. Use
        :attr:`is_structurally_feasible` when a diagnostic needs to separate
        structural validity from horizontal center-of-gravity tolerance.
        """
        return self.operationally_feasible

    def as_dict(self) -> dict[str, Any]:
        """Return a flat dictionary suitable for tables and comparison."""
        return {
            "total_weight": self.total_weight,
            "slot_utilization": self.slot_utilization,
            "longitudinal_moment": self.longitudinal_moment,
            "lateral_moment": self.lateral_moment,
            "cg_x": self.cg_x,
            "cg_y": self.cg_y,
            "cg_z_normalized": self.cg_z_normalized,
            "port_side_weight": self.port_side_weight,
            "starboard_side_weight": self.starboard_side_weight,
            "bow_weight": self.bow_weight,
            "stern_weight": self.stern_weight,
            "within_lon_tolerance": self.within_lon_tolerance,
            "within_lat_tolerance": self.within_lat_tolerance,
            "unassigned_container_count": self.unassigned_container_count,
            "duplicate_slot_violations": self.duplicate_slot_violations,
            "reefer_violations": self.reefer_violations,
            "stack_continuity_violations": self.stack_continuity_violations,
            "incompatible_cargo_violations": self.incompatible_cargo_violations,
            "constraint_violations": self.constraint_violations,
            "real_rehandling": self.real_rehandling,
            "real_rehandling_normalized": self.real_rehandling_normalized,
            "is_structurally_feasible": self.is_structurally_feasible,
            "cg_within_tolerance": self.cg_within_tolerance,
            "operationally_feasible": self.operationally_feasible,
            "is_feasible": self.is_feasible,
        }


def evaluate_solution(
    instance: ProblemInstance,
    solution: StowageSolution,
    *,
    cg_tolerance_lon: float = DEFAULT_CG_TOLERANCE_LON,
    cg_tolerance_lat: float = DEFAULT_CG_TOLERANCE_LAT,
    min_incompatible_bay_distance: int = DEFAULT_MIN_INCOMPATIBLE_BAY_DISTANCE,
) -> StowageMetrics:
    """Evaluate a complete assignment with the common final metrics.

    The solution is matched against the instance; every assignment must
    reference a known container and an in-grid slot position. Tolerances and
    the incompatible-cargo separation distance are caller-configurable so the
    same engine can serve different scenarios.
    """
    placements = _resolve_placements(instance, solution)

    total_weight = sum(p.container.weight for p in placements)
    occupied_slot_count = len({p.slot.position for p in placements})
    slot_utilization = (
        occupied_slot_count / instance.ship.slot_count if instance.ship.slot_count else 0.0
    )

    longitudinal_moment = sum(p.container.weight * p.slot.x for p in placements)
    lateral_moment = sum(p.container.weight * p.slot.y for p in placements)
    vertical_moment = sum(p.container.weight * p.slot.z for p in placements)

    cg_x = longitudinal_moment / total_weight if total_weight else 0.0
    cg_y = lateral_moment / total_weight if total_weight else 0.0
    cg_z_normalized = vertical_moment / total_weight if total_weight else 0.0

    port_side_weight = sum(p.container.weight for p in placements if p.slot.y < 0)
    starboard_side_weight = sum(p.container.weight for p in placements if p.slot.y > 0)
    bow_weight = sum(p.container.weight for p in placements if p.slot.x > 0)
    stern_weight = sum(p.container.weight for p in placements if p.slot.x < 0)

    real_rehandling = _real_rehandling(instance, placements)
    real_rehandling_normalized = _normalize_real_rehandling(instance, real_rehandling)

    return StowageMetrics(
        total_weight=total_weight,
        slot_utilization=slot_utilization,
        longitudinal_moment=longitudinal_moment,
        lateral_moment=lateral_moment,
        cg_x=cg_x,
        cg_y=cg_y,
        cg_z_normalized=cg_z_normalized,
        port_side_weight=port_side_weight,
        starboard_side_weight=starboard_side_weight,
        bow_weight=bow_weight,
        stern_weight=stern_weight,
        within_lon_tolerance=abs(cg_x) <= cg_tolerance_lon,
        within_lat_tolerance=abs(cg_y) <= cg_tolerance_lat,
        unassigned_container_count=_unassigned_container_count(instance, placements),
        duplicate_slot_violations=_duplicate_slot_violations(placements),
        reefer_violations=_reefer_violations(placements),
        stack_continuity_violations=_stack_continuity_violations(placements),
        incompatible_cargo_violations=_incompatible_cargo_violations(
            placements, min_incompatible_bay_distance
        ),
        real_rehandling=real_rehandling,
        real_rehandling_normalized=real_rehandling_normalized,
    )


def simulate_unloading_events(
    instance: ProblemInstance,
    solution: StowageSolution,
) -> tuple[UnloadingStep, ...]:
    """Return port-by-port unloading events for a complete stowage plan.

    This exposes the same simplified simulation used by
    :func:`evaluate_solution` to count real rehandling. It is intended as the
    data contract for Phase 7 visualization: UI code can inspect removed
    containers, temporary rehandles, and the remaining compacted assignment
    after each route port.
    """
    placements = _resolve_placements(instance, solution)
    return _simulate_unloading_steps(instance, placements)


def _resolve_placements(
    instance: ProblemInstance, solution: StowageSolution
) -> tuple[_Placement, ...]:
    containers_by_id = {container.id: container for container in instance.containers}

    placements: list[_Placement] = []
    for assignment in solution.assignments:
        container = containers_by_id.get(assignment.container_id)
        if container is None:
            raise ValueError(
                f"Solution references unknown container ID: {assignment.container_id}."
            )
        bay, row, tier = assignment.slot_position
        slot = instance.ship.get_slot(bay, row, tier)
        placements.append(_Placement(container=container, slot=slot))

    return tuple(placements)


def _unassigned_container_count(
    instance: ProblemInstance, placements: tuple[_Placement, ...]
) -> int:
    assigned_ids = {p.container.id for p in placements}
    return sum(1 for container in instance.containers if container.id not in assigned_ids)


def _duplicate_slot_violations(placements: tuple[_Placement, ...]) -> int:
    slot_usage: Counter[SlotPosition] = Counter(p.slot.position for p in placements)
    return sum(count - 1 for count in slot_usage.values() if count > 1)


def _reefer_violations(placements: tuple[_Placement, ...]) -> int:
    return sum(
        1 for p in placements if p.container.is_reefer and not p.slot.is_reefer
    )


def _stack_continuity_violations(placements: tuple[_Placement, ...]) -> int:
    occupied_tiers: dict[tuple[int, int], set[int]] = {}
    for p in placements:
        occupied_tiers.setdefault((p.slot.bay, p.slot.row), set()).add(p.slot.tier)

    violations = 0
    for tiers in occupied_tiers.values():
        for tier in tiers:
            if tier > 1 and (tier - 1) not in tiers:
                violations += 1
    return violations


def _incompatible_cargo_violations(
    placements: tuple[_Placement, ...], min_distance: int
) -> int:
    flammable_bays = {
        p.slot.bay for p in placements if p.container.type == ContainerType.FLAMMABLE
    }
    oxidizer_bays = {
        p.slot.bay for p in placements if p.container.type == ContainerType.OXIDIZER
    }

    return sum(
        1
        for flammable_bay in flammable_bays
        for oxidizer_bay in oxidizer_bays
        if abs(flammable_bay - oxidizer_bay) < min_distance
    )


def _real_rehandling(
    instance: ProblemInstance, placements: tuple[_Placement, ...]
) -> int:
    """Count blocking moves by simulating unloading in route order.

    Each stack is a list ordered from bottom tier to top tier. Ports are
    unloaded following the route sequence. To reach a container leaving at the
    current port, every container above it that leaves at a later port must be
    moved aside; each such move is one rehandle. Containers placed back may
    block again at later ports, which is counted again.
    """
    return sum(
        step.rehandle_count
        for step in _simulate_unloading_steps(instance, placements)
    )


def _simulate_unloading_steps(
    instance: ProblemInstance, placements: tuple[_Placement, ...]
) -> tuple[UnloadingStep, ...]:
    stacks: dict[tuple[int, int], list[_Placement]] = {}
    for placement in sorted(
        placements, key=lambda item: (item.slot.bay, item.slot.row, item.slot.tier)
    ):
        stacks.setdefault((placement.slot.bay, placement.slot.row), []).append(placement)

    steps: list[UnloadingStep] = []
    for port in instance.route.ports:
        removed_ids: list[str] = []
        rehandled_ids: list[str] = []

        for position in sorted(stacks):
            stack = stacks[position]
            target_indices = [
                index
                for index, placement in enumerate(stack)
                if placement.container.destination_port == port
            ]
            if not target_indices:
                continue

            deepest_target = min(target_indices)
            rehandled_ids.extend(
                placement.container.id
                for placement in stack[deepest_target + 1:]
                if placement.container.destination_port != port
            )
            removed_ids.extend(
                placement.container.id
                for placement in stack
                if placement.container.destination_port == port
            )
            stacks[position] = [
                placement
                for placement in stack
                if placement.container.destination_port != port
            ]

        steps.append(
            UnloadingStep(
                port=port,
                removed_container_ids=tuple(removed_ids),
                rehandled_container_ids=tuple(rehandled_ids),
                remaining_assignment=_remaining_assignment_from_stacks(stacks),
            )
        )

    return tuple(steps)


def _remaining_assignment_from_stacks(
    stacks: dict[tuple[int, int], list[_Placement]]
) -> StowageSolution:
    assignments: dict[str, SlotPosition] = {}
    for (bay, row), stack in sorted(stacks.items()):
        for tier, placement in enumerate(stack, start=1):
            assignments[placement.container.id] = (bay, row, tier)
    return StowageSolution.from_mapping(assignments)


def _normalize_real_rehandling(instance: ProblemInstance, real_rehandling: int) -> float:
    tiers = instance.ship.tiers
    stack_count = instance.ship.bays * instance.ship.rows
    max_rehandling = stack_count * tiers * (tiers - 1) // 2
    if max_rehandling == 0:
        return 0.0
    return real_rehandling / max_rehandling
