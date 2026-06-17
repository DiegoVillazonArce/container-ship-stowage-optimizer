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

from stowage_optimizer.core.metrics import StowageMetrics
from stowage_optimizer.core.problem import ProblemInstance
from stowage_optimizer.core.solution import StowageSolution


class SolverStatus(StrEnum):
    """Outcome of a solve attempt."""

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
        """Return whether the solution satisfies all hard constraints.

        Both ``FEASIBLE`` (no repair needed) and ``REPAIRED`` (made feasible
        by post-construction repair) count as feasible outcomes.
        """
        return self.status in (SolverStatus.FEASIBLE, SolverStatus.REPAIRED)


class Solver(ABC):
    """Abstract base class for every stowage solver."""

    name: str = "solver"

    @abstractmethod
    def solve(self, instance: ProblemInstance) -> SolverResult:
        """Produce a stowage solution for ``instance`` and evaluate it."""
        raise NotImplementedError
