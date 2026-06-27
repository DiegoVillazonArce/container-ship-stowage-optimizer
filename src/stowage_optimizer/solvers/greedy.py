"""Greedy constructive baseline solver.

The greedy solver builds an assignment one container at a time. It processes
the most constrained containers first (reefer, then dangerous cargo, then by
descending weight), retries temporarily blocked containers after new support
slots are filled, and places each one in the currently feasible slot with the
best score. The score balances four concerns from DESIGN.md sections 10-13:

- horizontal center-of-gravity impact (keep ``CG_x`` and ``CG_y`` centered),
- vertical placement (keep heavy cargo in lower tiers, lowering ``CG_z``),
- rehandling risk (keep early-leaving cargo near the top of its stack),
- incompatible-cargo separation (keep Flammable and Oxidizer bays apart).

Construction enforces slot capacity, stack continuity, and reefer
compatibility as hard rules: a slot is only a candidate if it is empty,
supported from below, and reefer-capable when required. After construction an
optional swap-based repair tries to remove structural violations. A separate
optional local-search post-processing step can then swap assigned containers to
rebalance horizontal CG and reduce real rehandling while preserving hard
constraints.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, replace

from stowage_optimizer.core.container import Container, ContainerType
from stowage_optimizer.core.metrics import (
    DEFAULT_CG_TOLERANCE_LAT,
    DEFAULT_CG_TOLERANCE_LON,
    DEFAULT_MIN_INCOMPATIBLE_BAY_DISTANCE,
    evaluate_solution,
)
from stowage_optimizer.core.problem import ProblemInstance
from stowage_optimizer.core.ship import Slot
from stowage_optimizer.core.solution import SlotPosition, StowageSolution
from stowage_optimizer.solvers.base import (
    Solver,
    SolverResult,
    SolverStatus,
    validate_solver_input,
)
from stowage_optimizer.solvers.local_search import (
    LocalSearchConfig,
    LocalSearchResult,
    LocalSearchWeights,
    improve_solution,
)

# Maximum number of full improvement passes attempted during swap repair.
_MAX_REPAIR_PASSES = 20


@dataclass(frozen=True, slots=True)
class GreedyWeights:
    """Relative importance of each scoring term during construction."""

    cg_lon: float = 1.0
    cg_lat: float = 1.0
    vertical: float = 1.0
    rehandling: float = 1.0
    incompatible_penalty: float = 1000.0


class GreedySolver(Solver):
    """Fast constructive heuristic used as the project baseline."""

    name = "greedy"

    def __init__(
        self,
        *,
        weights: GreedyWeights = GreedyWeights(),
        cg_tolerance_lon: float = DEFAULT_CG_TOLERANCE_LON,
        cg_tolerance_lat: float = DEFAULT_CG_TOLERANCE_LAT,
        min_incompatible_bay_distance: int = DEFAULT_MIN_INCOMPATIBLE_BAY_DISTANCE,
        enable_repair: bool = True,
        enable_local_search: bool = False,
        local_search_config: LocalSearchConfig | None = None,
    ) -> None:
        self._weights = weights
        self._cg_tolerance_lon = cg_tolerance_lon
        self._cg_tolerance_lat = cg_tolerance_lat
        self._min_distance = min_incompatible_bay_distance
        self._enable_repair = enable_repair
        self._enable_local_search = enable_local_search
        base_local_search_config = local_search_config or LocalSearchConfig(
            weights=LocalSearchWeights(
                cg_lon=weights.cg_lon,
                cg_lat=weights.cg_lat,
                rehandling=weights.rehandling,
                vertical=0.05 * weights.vertical,
            )
        )
        self._local_search_config = replace(
            base_local_search_config,
            cg_tolerance_lon=cg_tolerance_lon,
            cg_tolerance_lat=cg_tolerance_lat,
            min_incompatible_bay_distance=min_incompatible_bay_distance,
        )

    def solve(self, instance: ProblemInstance) -> SolverResult:
        start = time.perf_counter()
        invalid_result = validate_solver_input(
            instance,
            runtime_seconds=time.perf_counter() - start,
            cg_tolerance_lon=self._cg_tolerance_lon,
            cg_tolerance_lat=self._cg_tolerance_lat,
            min_incompatible_bay_distance=self._min_distance,
        )
        if invalid_result is not None:
            return invalid_result

        assignment = self._construct(instance)
        solution = StowageSolution.from_mapping(assignment)
        metrics = evaluate_solution(
            instance,
            solution,
            cg_tolerance_lon=self._cg_tolerance_lon,
            cg_tolerance_lat=self._cg_tolerance_lat,
            min_incompatible_bay_distance=self._min_distance,
        )
        status = SolverStatus.FEASIBLE if metrics.is_feasible else SolverStatus.INFEASIBLE
        repair_applied = False

        if not metrics.is_structurally_feasible and self._enable_repair:
            repaired = self._repair(instance, assignment)
            repaired_solution = StowageSolution.from_mapping(repaired)
            repaired_metrics = evaluate_solution(
                instance,
                repaired_solution,
                cg_tolerance_lon=self._cg_tolerance_lon,
                cg_tolerance_lat=self._cg_tolerance_lat,
                min_incompatible_bay_distance=self._min_distance,
            )
            if repaired_metrics.is_feasible:
                solution, metrics = repaired_solution, repaired_metrics
                status = SolverStatus.REPAIRED
                repair_applied = True
            elif repaired_metrics.constraint_violations < metrics.constraint_violations:
                solution, metrics = repaired_solution, repaired_metrics
                status = SolverStatus.INFEASIBLE
                repair_applied = True

        local_search_result: LocalSearchResult | None = None
        if self._enable_local_search:
            local_search_result = improve_solution(
                instance,
                solution,
                config=self._local_search_config,
            )
            solution = local_search_result.solution
            metrics = local_search_result.metrics
            if metrics.is_feasible:
                status = SolverStatus.REPAIRED if repair_applied else SolverStatus.FEASIBLE
            else:
                status = SolverStatus.INFEASIBLE

        runtime = time.perf_counter() - start
        return SolverResult(
            solution=solution,
            status=status,
            runtime_seconds=runtime,
            metrics=metrics,
            local_search_result=local_search_result,
        )

    # -- Construction ----------------------------------------------------

    def _construct(self, instance: ProblemInstance) -> dict[str, SlotPosition]:
        slots_by_position = {slot.position: slot for slot in instance.ship.slots}
        occupied: set[SlotPosition] = set()
        assignment: dict[str, SlotPosition] = {}

        total_weight = 0.0
        moment_lon = 0.0
        moment_lat = 0.0
        flammable_bays: set[int] = set()
        oxidizer_bays: set[int] = set()

        pending = self._ordered_containers(instance.containers)
        while pending:
            next_pending: list[Container] = []
            made_progress = False

            for container in pending:
                candidates = self._candidate_slots(container, slots_by_position, occupied)
                if not candidates:
                    next_pending.append(container)
                    continue

                best = min(
                    candidates,
                    key=lambda slot: self._slot_score(
                        container,
                        slot,
                        instance,
                        total_weight,
                        moment_lon,
                        moment_lat,
                        flammable_bays,
                        oxidizer_bays,
                    ),
                )

                assignment[container.id] = best.position
                occupied.add(best.position)
                total_weight += container.weight
                moment_lon += container.weight * best.x
                moment_lat += container.weight * best.y
                made_progress = True

                if container.type == ContainerType.FLAMMABLE:
                    flammable_bays.add(best.bay)
                elif container.type == ContainerType.OXIDIZER:
                    oxidizer_bays.add(best.bay)

            if not made_progress:
                break

            pending = next_pending

        return assignment

    def _ordered_containers(self, containers: tuple[Container, ...]) -> list[Container]:
        return sorted(
            containers,
            key=lambda container: (self._priority(container), -container.weight, container.id),
        )

    @staticmethod
    def _priority(container: Container) -> int:
        if container.is_reefer:
            return 0
        if container.type in (ContainerType.FLAMMABLE, ContainerType.OXIDIZER):
            return 1
        return 2

    @staticmethod
    def _candidate_slots(
        container: Container,
        slots_by_position: dict[SlotPosition, Slot],
        occupied: set[SlotPosition],
    ) -> list[Slot]:
        candidates: list[Slot] = []
        for position, slot in slots_by_position.items():
            if position in occupied:
                continue  # Slot capacity.
            if container.is_reefer and not slot.is_reefer:
                continue  # Reefer compatibility.
            bay, row, tier = position
            if tier > 1 and (bay, row, tier - 1) not in occupied:
                continue  # Stack continuity: cannot float above an empty slot.
            candidates.append(slot)
        return candidates

    def _slot_score(
        self,
        container: Container,
        slot: Slot,
        instance: ProblemInstance,
        total_weight: float,
        moment_lon: float,
        moment_lat: float,
        flammable_bays: set[int],
        oxidizer_bays: set[int],
    ) -> float:
        new_weight = total_weight + container.weight
        cg_lon_term = abs(moment_lon + container.weight * slot.x) / new_weight
        cg_lat_term = abs(moment_lat + container.weight * slot.y) / new_weight
        vertical_term = slot.z
        rehandling_term = self._rehandling_risk(container, slot, instance)
        penalty = self._incompatible_penalty(container, slot, flammable_bays, oxidizer_bays)

        return (
            self._weights.cg_lon * cg_lon_term
            + self._weights.cg_lat * cg_lat_term
            + self._weights.vertical * vertical_term
            + self._weights.rehandling * rehandling_term
            + penalty
        )

    @staticmethod
    def _rehandling_risk(container: Container, slot: Slot, instance: ProblemInstance) -> float:
        route = instance.route
        if not route.contains(container.destination_port):
            return 0.0

        order = route.order_of(container.destination_port)
        last_order = len(route.ports)
        tiers = instance.ship.tiers
        early = (last_order - order) / (last_order - 1) if last_order > 1 else 0.0
        depth = (tiers - slot.tier) / (tiers - 1) if tiers > 1 else 0.0
        return early * depth

    def _incompatible_penalty(
        self,
        container: Container,
        slot: Slot,
        flammable_bays: set[int],
        oxidizer_bays: set[int],
    ) -> float:
        if container.type == ContainerType.FLAMMABLE:
            conflicting_bays = oxidizer_bays
        elif container.type == ContainerType.OXIDIZER:
            conflicting_bays = flammable_bays
        else:
            return 0.0

        too_close = any(
            abs(slot.bay - bay) < self._min_distance for bay in conflicting_bays
        )
        return self._weights.incompatible_penalty if too_close else 0.0

    # -- Repair ----------------------------------------------------------

    def _repair(
        self, instance: ProblemInstance, assignment: dict[str, SlotPosition]
    ) -> dict[str, SlotPosition]:
        """Reduce violations by swapping pairs of container slot positions.

        Each accepted swap strictly lowers the total constraint-violation
        count. Minimizing that shared count keeps reefer and stack-continuity
        rules intact, since breaking one would raise the count rather than
        lower it. The search stops when no swap improves further.
        """
        best = dict(assignment)
        best_violations = self._violation_count(instance, best)
        if best_violations == 0:
            return best

        container_ids = list(best.keys())
        for _ in range(_MAX_REPAIR_PASSES):
            improved = False
            for i in range(len(container_ids)):
                for j in range(i + 1, len(container_ids)):
                    first, second = container_ids[i], container_ids[j]
                    trial = dict(best)
                    trial[first], trial[second] = best[second], best[first]
                    violations = self._violation_count(instance, trial)
                    if violations < best_violations:
                        best, best_violations = trial, violations
                        improved = True
            if not improved or best_violations == 0:
                break

        return best

    def _violation_count(
        self, instance: ProblemInstance, assignment: dict[str, SlotPosition]
    ) -> int:
        solution = StowageSolution.from_mapping(assignment)
        metrics = evaluate_solution(
            instance,
            solution,
            cg_tolerance_lon=self._cg_tolerance_lon,
            cg_tolerance_lat=self._cg_tolerance_lat,
            min_incompatible_bay_distance=self._min_distance,
        )
        return metrics.constraint_violations
