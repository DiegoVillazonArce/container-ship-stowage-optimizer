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


@dataclass(frozen=True, slots=True)
class SolverResult:
    """A solver's produced solution together with its evaluation."""

    solution: StowageSolution
    status: SolverStatus
    runtime_seconds: float
    metrics: StowageMetrics

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
