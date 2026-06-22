"""Mixed Integer Linear Programming reference solver.

The MILP solver is the exact optimization reference for small instances. It
builds the binary assignment model described in DESIGN.md sections 7-13 with
PuLP and solves it with the bundled CBC backend. Compared with the greedy
baseline it does not construct a solution step by step; instead it states every
hard constraint and the linear objective up front and lets the solver search
for an optimal feasible assignment.

Decision variables:

- ``x[c, p] = 1`` if container ``c`` is assigned to slot ``p``. Reefer
  containers only receive variables for reefer-capable slots, which enforces
  reefer compatibility structurally and keeps the model smaller.
- ``F[b]`` / ``O[b]`` flag whether bay ``b`` holds a flammable / oxidizer
  container, used for the simplified bay-distance separation rule.
- ``d_lon`` / ``d_lat`` linearize the absolute horizontal moment deviations
  used in the objective.

Hard constraints: unique assignment, slot capacity, stack continuity, reefer
compatibility, incompatible-cargo bay separation, and horizontal center-of-
gravity moment limits. The objective minimizes longitudinal and lateral CG
deviation, a normalized vertical CG penalty, and a linear rehandling proxy.

PuLP is chosen over OR-Tools/Pyomo for academic clarity and zero-config
install: it ships the CBC solver, so no external solver setup is required.

Optimality is reported only when CBC certifies it. Under a time limit CBC may
stop with a feasible incumbent while still labelling its status ``Optimal``; the
solver inspects ``sol_status`` to tell a proven optimum (``SolverStatus.OPTIMAL``)
from such an uncertified incumbent, which is reported as ``NOT_SOLVED`` rather
than presented as optimal. Recovering and returning that incumbent is a separate
future enhancement (see ROADMAP).
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import pulp

from stowage_optimizer.core.container import Container, ContainerType
from stowage_optimizer.core.metrics import (
    DEFAULT_CG_TOLERANCE_LAT,
    DEFAULT_CG_TOLERANCE_LON,
    DEFAULT_MIN_INCOMPATIBLE_BAY_DISTANCE,
    evaluate_solution,
)
from stowage_optimizer.core.problem import ProblemInstance
from stowage_optimizer.core.ship import Ship, Slot
from stowage_optimizer.core.solution import SlotPosition, StowageSolution
from stowage_optimizer.solvers.base import (
    Solver,
    SolverResult,
    SolverStatus,
    validate_solver_input,
)


@dataclass(frozen=True, slots=True)
class MILPWeights:
    """Relative importance of each linear objective term.

    Mirrors the coefficients ``alpha_lon``, ``alpha_lat``, ``lambda``, and
    ``delta`` from DESIGN.md section 13.
    """

    cg_lon: float = 1.0
    cg_lat: float = 1.0
    vertical: float = 1.0
    rehandling: float = 1.0


class MILPSolver(Solver):
    """Exact MILP reference solver for small instances."""

    name = "milp"

    def __init__(
        self,
        *,
        weights: MILPWeights = MILPWeights(),
        cg_tolerance_lon: float = DEFAULT_CG_TOLERANCE_LON,
        cg_tolerance_lat: float = DEFAULT_CG_TOLERANCE_LAT,
        min_incompatible_bay_distance: int = DEFAULT_MIN_INCOMPATIBLE_BAY_DISTANCE,
        time_limit_seconds: float | None = None,
    ) -> None:
        self._weights = weights
        self._cg_tolerance_lon = cg_tolerance_lon
        self._cg_tolerance_lat = cg_tolerance_lat
        self._min_distance = min_incompatible_bay_distance
        self._time_limit_seconds = time_limit_seconds

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

        problem, assignment_vars = self._build_model(instance)
        backend = pulp.PULP_CBC_CMD(msg=False, timeLimit=self._time_limit_seconds)
        problem.solve(backend)

        runtime = time.perf_counter() - start
        is_proven_optimal, solver_status_detail = self._classify_backend_status(
            problem.status, problem.sol_status
        )

        if is_proven_optimal:
            solution = self._extract_solution(assignment_vars)
            objective_value = pulp.value(problem.objective)
        else:
            # No certified optimal solution is available. Report an empty
            # assignment so the common metrics flag every container as
            # unassigned, but keep the backend status distinct below. A feasible
            # incumbent found under the time limit is intentionally discarded
            # here; recovering it is a separate future enhancement (ROADMAP).
            solution = StowageSolution(())
            objective_value = None

        metrics = evaluate_solution(
            instance,
            solution,
            cg_tolerance_lon=self._cg_tolerance_lon,
            cg_tolerance_lat=self._cg_tolerance_lat,
            min_incompatible_bay_distance=self._min_distance,
        )
        status = self._solver_status(is_proven_optimal, problem.status, metrics.is_feasible)

        return SolverResult(
            solution=solution,
            status=status,
            runtime_seconds=runtime,
            metrics=metrics,
            objective_value=objective_value,
            # CBC, the default PuLP backend, does not expose the MIP optimality
            # gap through PuLP's public API, so it is reported as unknown.
            gap=None,
            solver_status_detail=solver_status_detail,
        )

    @staticmethod
    def _classify_backend_status(
        status_code: int, sol_status_code: int
    ) -> tuple[bool, str]:
        """Decide whether CBC certified an optimum and build a status string.

        CBC (PuLP's default backend) leaves ``problem.status`` at
        ``LpStatusOptimal`` even when it stops at the configured time limit with
        a feasible incumbent it never proved optimal. Only ``problem.sol_status``
        separates a certified optimum (``LpSolutionOptimal``) from such an
        uncertified incumbent (``LpSolutionIntegerFeasible``). Returning the
        optimality flag here keeps the rest of ``solve`` from reporting an
        unproven incumbent as ``Optimal``.
        """
        if status_code == pulp.LpStatusOptimal:
            if sol_status_code == pulp.LpSolutionOptimal:
                return True, "Optimal"
            # Feasible but not certified: surface the native solution status and
            # make the time-limit caveat explicit instead of claiming optimality.
            native = pulp.LpSolution.get(sol_status_code, str(sol_status_code))
            return False, f"{native} (time limit; optimality not certified)"
        return False, pulp.LpStatus[status_code]

    @staticmethod
    def _solver_status(
        is_proven_optimal: bool, status_code: int, metrics_are_feasible: bool
    ) -> SolverStatus:
        if is_proven_optimal:
            return SolverStatus.OPTIMAL if metrics_are_feasible else SolverStatus.INFEASIBLE
        if status_code == pulp.LpStatusInfeasible:
            return SolverStatus.INFEASIBLE
        return SolverStatus.NOT_SOLVED

    # -- Model construction ----------------------------------------------

    def _build_model(
        self, instance: ProblemInstance
    ) -> tuple[pulp.LpProblem, dict[str, dict[SlotPosition, pulp.LpVariable]]]:
        ship = instance.ship
        slots = ship.slots
        containers = tuple(instance.containers)
        total_weight = sum(container.weight for container in containers)

        problem = pulp.LpProblem("stowage", pulp.LpMinimize)

        assignment_vars = self._create_assignment_vars(containers, slots)
        self._add_unique_assignment(problem, containers, assignment_vars)
        self._add_slot_capacity(problem, slots, assignment_vars)
        self._add_stack_continuity(problem, ship, assignment_vars)
        self._add_incompatible_cargo(problem, instance, slots, assignment_vars)
        d_lon, d_lat = self._add_cg_constraints(
            problem, instance, slots, assignment_vars, total_weight
        )
        self._set_objective(
            problem, instance, slots, assignment_vars, total_weight, d_lon, d_lat
        )

        return problem, assignment_vars

    def _create_assignment_vars(
        self, containers: tuple[Container, ...], slots: tuple[Slot, ...]
    ) -> dict[str, dict[SlotPosition, pulp.LpVariable]]:
        """Create ``x[c, p]`` binaries, skipping reefer-incompatible slots.

        Omitting non-reefer slots for reefer containers enforces reefer
        compatibility structurally: such a container simply has no way to be
        placed there.
        """
        assignment_vars: dict[str, dict[SlotPosition, pulp.LpVariable]] = {}
        for c_index, container in enumerate(containers):
            slot_vars: dict[SlotPosition, pulp.LpVariable] = {}
            for slot in slots:
                if container.is_reefer and not slot.is_reefer:
                    continue
                bay, row, tier = slot.position
                name = f"x_{c_index}_{bay}_{row}_{tier}"
                slot_vars[slot.position] = pulp.LpVariable(name, cat=pulp.LpBinary)
            assignment_vars[container.id] = slot_vars
        return assignment_vars

    @staticmethod
    def _add_unique_assignment(
        problem: pulp.LpProblem,
        containers: tuple[Container, ...],
        assignment_vars: dict[str, dict[SlotPosition, pulp.LpVariable]],
    ) -> None:
        # Each container is placed exactly once. A reefer with no compatible
        # slot yields an empty sum == 1, which is correctly infeasible.
        for container in containers:
            problem += (
                pulp.lpSum(assignment_vars[container.id].values()) == 1,
                f"assign_once_{container.id}",
            )

    @staticmethod
    def _add_slot_capacity(
        problem: pulp.LpProblem,
        slots: tuple[Slot, ...],
        assignment_vars: dict[str, dict[SlotPosition, pulp.LpVariable]],
    ) -> None:
        # At most one container per slot.
        for slot in slots:
            occupants = [
                slot_vars[slot.position]
                for slot_vars in assignment_vars.values()
                if slot.position in slot_vars
            ]
            if occupants:
                bay, row, tier = slot.position
                problem += (pulp.lpSum(occupants) <= 1, f"capacity_{bay}_{row}_{tier}")

    @staticmethod
    def _occupancy(
        position: SlotPosition,
        assignment_vars: dict[str, dict[SlotPosition, pulp.LpVariable]],
    ) -> list[pulp.LpVariable]:
        return [
            slot_vars[position]
            for slot_vars in assignment_vars.values()
            if position in slot_vars
        ]

    def _add_stack_continuity(
        self,
        problem: pulp.LpProblem,
        ship: Ship,
        assignment_vars: dict[str, dict[SlotPosition, pulp.LpVariable]],
    ) -> None:
        # A slot above tier 1 may only be filled if the slot below it is too.
        for bay in range(1, ship.bays + 1):
            for row in range(1, ship.rows + 1):
                for tier in range(2, ship.tiers + 1):
                    above = self._occupancy((bay, row, tier), assignment_vars)
                    below = self._occupancy((bay, row, tier - 1), assignment_vars)
                    if above:
                        problem += (
                            pulp.lpSum(above) <= pulp.lpSum(below),
                            f"continuity_{bay}_{row}_{tier}",
                        )

    def _add_incompatible_cargo(
        self,
        problem: pulp.LpProblem,
        instance: ProblemInstance,
        slots: tuple[Slot, ...],
        assignment_vars: dict[str, dict[SlotPosition, pulp.LpVariable]],
    ) -> None:
        """Separate Flammable and Oxidizer cargo with bay-level binaries.

        ``F[b]`` / ``O[b]`` activate when bay ``b`` holds the matching cargo,
        and a pair constraint forbids the two classes within ``min_distance``
        bays of each other (DESIGN.md section 9).
        """
        slots_by_bay: dict[int, list[Slot]] = {}
        for slot in slots:
            slots_by_bay.setdefault(slot.bay, []).append(slot)

        bays = sorted(slots_by_bay)
        flammable_flags = {b: pulp.LpVariable(f"F_{b}", cat=pulp.LpBinary) for b in bays}
        oxidizer_flags = {b: pulp.LpVariable(f"O_{b}", cat=pulp.LpBinary) for b in bays}

        for container in instance.containers:
            if container.type == ContainerType.FLAMMABLE:
                flags = flammable_flags
            elif container.type == ContainerType.OXIDIZER:
                flags = oxidizer_flags
            else:
                continue
            for position, var in assignment_vars[container.id].items():
                bay = position[0]
                problem += (var <= flags[bay], f"flag_{container.id}_{bay}_{position[1]}_{position[2]}")

        # Forbid incompatible bays that are closer than the minimum distance.
        for first in bays:
            for second in bays:
                if abs(first - second) < self._min_distance:
                    problem += (
                        flammable_flags[first] + oxidizer_flags[second] <= 1,
                        f"separation_{first}_{second}",
                    )

    def _add_cg_constraints(
        self,
        problem: pulp.LpProblem,
        instance: ProblemInstance,
        slots: tuple[Slot, ...],
        assignment_vars: dict[str, dict[SlotPosition, pulp.LpVariable]],
        total_weight: float,
    ) -> tuple[pulp.LpVariable, pulp.LpVariable]:
        """Bound horizontal CG via weight moments and link deviation variables.

        ``abs(CG_x) <= tau_lon`` and ``abs(CG_y) <= tau_lat`` are enforced as
        ``-tau * W <= Moment <= tau * W``. ``d_lon`` / ``d_lat`` capture the
        absolute moment deviation for the objective.
        """
        coord_by_position = {slot.position: slot for slot in slots}
        weight_by_id = {c.id: c.weight for c in instance.containers}

        moment_lon = pulp.lpSum(
            weight_by_id[c_id] * coord_by_position[position].x * var
            for c_id, slot_vars in assignment_vars.items()
            for position, var in slot_vars.items()
        )
        moment_lat = pulp.lpSum(
            weight_by_id[c_id] * coord_by_position[position].y * var
            for c_id, slot_vars in assignment_vars.items()
            for position, var in slot_vars.items()
        )

        problem += (moment_lon <= self._cg_tolerance_lon * total_weight, "cg_lon_upper")
        problem += (moment_lon >= -self._cg_tolerance_lon * total_weight, "cg_lon_lower")
        problem += (moment_lat <= self._cg_tolerance_lat * total_weight, "cg_lat_upper")
        problem += (moment_lat >= -self._cg_tolerance_lat * total_weight, "cg_lat_lower")

        d_lon = pulp.LpVariable("d_lon", lowBound=0.0)
        d_lat = pulp.LpVariable("d_lat", lowBound=0.0)
        problem += (d_lon >= moment_lon, "abs_lon_pos")
        problem += (d_lon >= -moment_lon, "abs_lon_neg")
        problem += (d_lat >= moment_lat, "abs_lat_pos")
        problem += (d_lat >= -moment_lat, "abs_lat_neg")

        return d_lon, d_lat

    def _set_objective(
        self,
        problem: pulp.LpProblem,
        instance: ProblemInstance,
        slots: tuple[Slot, ...],
        assignment_vars: dict[str, dict[SlotPosition, pulp.LpVariable]],
        total_weight: float,
        d_lon: pulp.LpVariable,
        d_lat: pulp.LpVariable,
    ) -> None:
        coord_by_position = {slot.position: slot for slot in slots}
        weight_by_id = {c.id: c.weight for c in instance.containers}

        weight_norm = total_weight if total_weight else 1.0

        vertical_penalty = pulp.lpSum(
            weight_by_id[c_id] * coord_by_position[position].z * var
            for c_id, slot_vars in assignment_vars.items()
            for position, var in slot_vars.items()
        )

        rehandling_proxy, proxy_max = self._rehandling_proxy(
            instance, coord_by_position, assignment_vars
        )
        proxy_norm = proxy_max if proxy_max else 1.0

        problem += (
            self._weights.cg_lon * (d_lon / weight_norm)
            + self._weights.cg_lat * (d_lat / weight_norm)
            + self._weights.vertical * (vertical_penalty / weight_norm)
            + self._weights.rehandling * (rehandling_proxy / proxy_norm)
        )

    def _rehandling_proxy(
        self,
        instance: ProblemInstance,
        coord_by_position: dict[SlotPosition, Slot],
        assignment_vars: dict[str, dict[SlotPosition, pulp.LpVariable]],
    ) -> tuple[pulp.LpAffineExpression, float]:
        """Build the linear rehandling proxy and its normalizer.

        ``phi[c, p] = Early(c) * Depth(p)`` penalizes early-leaving cargo placed
        deep in a stack (DESIGN.md section 12). ``proxy_max`` sums each
        container's largest possible ``phi`` so the term normalizes to ``[0, 1]``.
        """
        containers_by_id = {c.id: c for c in instance.containers}
        terms: list[pulp.LpAffineExpression] = []
        proxy_max = 0.0

        for c_id, slot_vars in assignment_vars.items():
            container = containers_by_id[c_id]
            early = self._early_factor(instance, container)
            best_phi = 0.0
            for position, var in slot_vars.items():
                tier = position[2]
                phi = early * self._depth_factor(instance, tier)
                if phi:
                    terms.append(phi * var)
                best_phi = max(best_phi, phi)
            proxy_max += best_phi

        return pulp.lpSum(terms), proxy_max

    @staticmethod
    def _early_factor(instance: ProblemInstance, container: Container) -> float:
        route = instance.route
        if not route.contains(container.destination_port):
            return 0.0
        last_order = len(route.ports)
        if last_order <= 1:
            return 0.0
        order = route.order_of(container.destination_port)
        return (last_order - order) / (last_order - 1)

    @staticmethod
    def _depth_factor(instance: ProblemInstance, tier: int) -> float:
        tiers = instance.ship.tiers
        if tiers <= 1:
            return 0.0
        return (tiers - tier) / (tiers - 1)

    # -- Solution extraction ---------------------------------------------

    @staticmethod
    def _extract_solution(
        assignment_vars: dict[str, dict[SlotPosition, pulp.LpVariable]],
    ) -> StowageSolution:
        assignment: dict[str, SlotPosition] = {}
        for container_id, slot_vars in assignment_vars.items():
            for position, var in slot_vars.items():
                value = var.value()
                if value is not None and value > 0.5:
                    assignment[container_id] = position
                    break
        return StowageSolution.from_mapping(assignment)
