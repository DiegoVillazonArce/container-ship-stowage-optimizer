"""Common solver interface shared by every stowage algorithm.

Every solver consumes a :class:`ProblemInstance` and returns a
:class:`SolverResult` that bundles the produced assignment, a feasibility
status, the measured runtime, and the common final metrics computed through
the shared evaluation layer. Reporting results this way keeps Greedy, MILP,
and Genetic Algorithm outputs directly comparable.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum

from stowage_optimizer.core.metrics import (
    DEFAULT_CG_TOLERANCE_LAT,
    DEFAULT_CG_TOLERANCE_LON,
    DEFAULT_MIN_INCOMPATIBLE_BAY_DISTANCE,
    StowageMetrics,
    evaluate_solution,
)
from stowage_optimizer.core.problem import ProblemInstance
from stowage_optimizer.core.solution import StowageSolution
from stowage_optimizer.core.validation import ValidationResult, validate_instance


class SolverStatus(StrEnum):
    """Outcome of a solve attempt."""

    OPTIMAL = "optimal"
    FEASIBLE = "feasible"
    REPAIRED = "repaired"
    INFEASIBLE = "infeasible"
    NOT_SOLVED = "not_solved"


@dataclass(frozen=True, slots=True)
class SolverResult:
    """A solver's produced solution together with its evaluation.

    ``objective_value`` and ``gap`` are optional and only populated by exact
    solvers. Heuristic solvers leave them as ``None`` because their internal
    scores are not comparable across algorithms (see DESIGN.md section 13).
    ``gap`` may also stay ``None`` when the underlying MILP backend does not
    expose an optimality gap. ``solver_status_detail`` preserves the backend's
    native status string when a solver can provide one.
    """

    solution: StowageSolution
    status: SolverStatus
    runtime_seconds: float
    metrics: StowageMetrics
    objective_value: float | None = None
    gap: float | None = None
    solver_status_detail: str | None = None

    @property
    def is_feasible(self) -> bool:
        """Return whether the solution is operationally feasible.

        ``OPTIMAL`` (a certified optimum from an exact solver), ``FEASIBLE``
        (no repair needed), and ``REPAIRED`` (made feasible by
        post-construction repair) all count as feasible outcomes, but only when
        the common metrics also confirm structural validity and horizontal CG
        tolerances.
        """
        return (
            self.status
            in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE, SolverStatus.REPAIRED)
            and self.metrics.operationally_feasible
        )

    @property
    def is_structurally_feasible(self) -> bool:
        """Return whether the result satisfies non-CG structural rules."""
        return self.metrics.is_structurally_feasible

    @property
    def cg_within_tolerance(self) -> bool:
        """Return whether the result satisfies configured horizontal CG limits."""
        return self.metrics.cg_within_tolerance


class Solver(ABC):
    """Abstract base class for every stowage solver."""

    name: str = "solver"

    @abstractmethod
    def solve(self, instance: ProblemInstance) -> SolverResult:
        """Produce a stowage solution for ``instance`` and evaluate it."""
        raise NotImplementedError


def validation_failure_result(
    instance: ProblemInstance,
    validation: ValidationResult,
    *,
    runtime_seconds: float,
    cg_tolerance_lon: float = DEFAULT_CG_TOLERANCE_LON,
    cg_tolerance_lat: float = DEFAULT_CG_TOLERANCE_LAT,
    min_incompatible_bay_distance: int = DEFAULT_MIN_INCOMPATIBLE_BAY_DISTANCE,
) -> SolverResult:
    """Build a common solver result for invalid input instances."""
    solution = StowageSolution(())
    metrics = evaluate_solution(
        instance,
        solution,
        cg_tolerance_lon=cg_tolerance_lon,
        cg_tolerance_lat=cg_tolerance_lat,
        min_incompatible_bay_distance=min_incompatible_bay_distance,
    )
    detail = "Validation failed: " + "; ".join(
        issue.message for issue in validation.errors
    )
    return SolverResult(
        solution=solution,
        status=SolverStatus.INFEASIBLE,
        runtime_seconds=runtime_seconds,
        metrics=metrics,
        solver_status_detail=detail,
    )


def validate_solver_input(
    instance: ProblemInstance,
    *,
    runtime_seconds: float,
    cg_tolerance_lon: float = DEFAULT_CG_TOLERANCE_LON,
    cg_tolerance_lat: float = DEFAULT_CG_TOLERANCE_LAT,
    min_incompatible_bay_distance: int = DEFAULT_MIN_INCOMPATIBLE_BAY_DISTANCE,
) -> SolverResult | None:
    """Return an invalid-input result, or ``None`` when solving may proceed."""
    validation = validate_instance(instance)
    if validation.is_valid:
        return None
    return validation_failure_result(
        instance,
        validation,
        runtime_seconds=runtime_seconds,
        cg_tolerance_lon=cg_tolerance_lon,
        cg_tolerance_lat=cg_tolerance_lat,
        min_incompatible_bay_distance=min_incompatible_bay_distance,
    )
