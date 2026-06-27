"""Swap-based local search for improving completed stowage plans.

The search is intentionally a post-processing helper rather than a new solver.
It starts from an existing assignment, swaps pairs of already-assigned
containers, evaluates each candidate with the shared metrics engine, and accepts
only score-improving swaps that preserve structural hard constraints.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from stowage_optimizer.core.metrics import (
    DEFAULT_CG_TOLERANCE_LAT,
    DEFAULT_CG_TOLERANCE_LON,
    DEFAULT_MIN_INCOMPATIBLE_BAY_DISTANCE,
    StowageMetrics,
    evaluate_solution,
)
from stowage_optimizer.core.problem import ProblemInstance
from stowage_optimizer.core.solution import StowageSolution


@dataclass(frozen=True, slots=True)
class LocalSearchWeights:
    """Weights used by the local-search acceptance score.

    Excess outside the configured horizontal CG tolerances is weighted
    separately from absolute CG deviation so an out-of-tolerance plan is first
    pushed back toward feasibility, then refined by common quality metrics.
    """

    cg_excess_lon: float = 10.0
    cg_excess_lat: float = 10.0
    cg_lon: float = 1.0
    cg_lat: float = 1.0
    rehandling: float = 1.0
    vertical: float = 0.05


@dataclass(frozen=True, slots=True)
class LocalSearchConfig:
    """Configuration for deterministic swap local search."""

    max_iterations: int = 500
    max_rounds_without_improvement: int = 2
    time_limit_seconds: float | None = None
    min_score_improvement: float = 1e-12
    max_cg_z_worsening: float = 0.05
    weights: LocalSearchWeights = field(default_factory=LocalSearchWeights)
    cg_tolerance_lon: float = DEFAULT_CG_TOLERANCE_LON
    cg_tolerance_lat: float = DEFAULT_CG_TOLERANCE_LAT
    min_incompatible_bay_distance: int = DEFAULT_MIN_INCOMPATIBLE_BAY_DISTANCE


@dataclass(frozen=True, slots=True)
class LocalSearchResult:
    """Outcome and diagnostics for one local-search post-processing run."""

    initial_solution: StowageSolution
    solution: StowageSolution
    initial_metrics: StowageMetrics
    metrics: StowageMetrics
    ran: bool
    evaluated_swaps: int
    accepted_swaps: int
    rounds_completed: int
    runtime_seconds: float
    initial_score: float
    final_score: float
    stopped_reason: str

    @property
    def improved(self) -> bool:
        """Return whether at least one swap was accepted."""
        return self.accepted_swaps > 0

    @property
    def iterations_evaluated(self) -> int:
        """Alias used by UI/reporting code."""
        return self.evaluated_swaps

    @property
    def abs_cg_x_improvement(self) -> float:
        """Return the reduction in absolute longitudinal CG deviation."""
        return abs(self.initial_metrics.cg_x) - abs(self.metrics.cg_x)

    @property
    def abs_cg_y_improvement(self) -> float:
        """Return the reduction in absolute lateral CG deviation."""
        return abs(self.initial_metrics.cg_y) - abs(self.metrics.cg_y)

    @property
    def rehandling_improvement(self) -> int:
        """Return the reduction in real rehandling moves."""
        return self.initial_metrics.real_rehandling - self.metrics.real_rehandling

    @property
    def became_operationally_feasible(self) -> bool:
        """Return whether local search moved the plan into full feasibility."""
        return (
            not self.initial_metrics.operationally_feasible
            and self.metrics.operationally_feasible
        )

    def as_dict(self) -> dict[str, object]:
        """Return a flat metadata dictionary for UI tables and exports."""
        return {
            "ran": self.ran,
            "evaluated_swaps": self.evaluated_swaps,
            "accepted_swaps": self.accepted_swaps,
            "rounds_completed": self.rounds_completed,
            "runtime_seconds": self.runtime_seconds,
            "stopped_reason": self.stopped_reason,
            "initial_score": self.initial_score,
            "final_score": self.final_score,
            "improved": self.improved,
            "abs_cg_x_before": abs(self.initial_metrics.cg_x),
            "abs_cg_x_after": abs(self.metrics.cg_x),
            "abs_cg_x_improvement": self.abs_cg_x_improvement,
            "abs_cg_y_before": abs(self.initial_metrics.cg_y),
            "abs_cg_y_after": abs(self.metrics.cg_y),
            "abs_cg_y_improvement": self.abs_cg_y_improvement,
            "real_rehandling_before": self.initial_metrics.real_rehandling,
            "real_rehandling_after": self.metrics.real_rehandling,
            "real_rehandling_improvement": self.rehandling_improvement,
            "operationally_feasible_before": self.initial_metrics.operationally_feasible,
            "operationally_feasible_after": self.metrics.operationally_feasible,
            "became_operationally_feasible": self.became_operationally_feasible,
        }


class SwapLocalSearch:
    """Deterministic pair-swap local search over assigned containers."""

    def __init__(self, config: LocalSearchConfig | None = None) -> None:
        self._config = config or LocalSearchConfig()
        self._validate_config(self._config)

    def improve(
        self,
        instance: ProblemInstance,
        solution: StowageSolution,
    ) -> LocalSearchResult:
        """Return the best solution found by hard-constraint-preserving swaps."""
        start = time.perf_counter()
        initial_metrics = self._evaluate(instance, solution)
        initial_score = self._score(initial_metrics)

        if initial_metrics.constraint_violations:
            return self._result(
                initial_solution=solution,
                solution=solution,
                initial_metrics=initial_metrics,
                metrics=initial_metrics,
                ran=False,
                evaluated_swaps=0,
                accepted_swaps=0,
                rounds_completed=0,
                runtime_seconds=time.perf_counter() - start,
                initial_score=initial_score,
                final_score=initial_score,
                stopped_reason="initial_solution_structurally_infeasible",
            )

        assignment = solution.assignment_map
        container_ids = sorted(assignment)
        if len(container_ids) < 2:
            return self._result(
                initial_solution=solution,
                solution=solution,
                initial_metrics=initial_metrics,
                metrics=initial_metrics,
                ran=True,
                evaluated_swaps=0,
                accepted_swaps=0,
                rounds_completed=0,
                runtime_seconds=time.perf_counter() - start,
                initial_score=initial_score,
                final_score=initial_score,
                stopped_reason="not_enough_assigned_containers",
            )

        if self._config.max_iterations == 0:
            return self._result(
                initial_solution=solution,
                solution=solution,
                initial_metrics=initial_metrics,
                metrics=initial_metrics,
                ran=True,
                evaluated_swaps=0,
                accepted_swaps=0,
                rounds_completed=0,
                runtime_seconds=time.perf_counter() - start,
                initial_score=initial_score,
                final_score=initial_score,
                stopped_reason="max_iterations",
            )

        current_assignment = dict(assignment)
        current_solution = solution
        current_metrics = initial_metrics
        current_score = initial_score
        evaluated_swaps = 0
        accepted_swaps = 0
        rounds_completed = 0
        rounds_without_improvement = 0
        stopped_reason = "no_improvement"

        while rounds_without_improvement < self._config.max_rounds_without_improvement:
            improved_this_round = False
            should_stop = False

            for first_index, first_id in enumerate(container_ids):
                for second_id in container_ids[first_index + 1:]:
                    if evaluated_swaps >= self._config.max_iterations:
                        stopped_reason = "max_iterations"
                        should_stop = True
                        break
                    if self._time_limit_reached(start):
                        stopped_reason = "time_limit"
                        should_stop = True
                        break

                    trial_assignment = dict(current_assignment)
                    trial_assignment[first_id], trial_assignment[second_id] = (
                        current_assignment[second_id],
                        current_assignment[first_id],
                    )
                    trial_solution = StowageSolution.from_mapping(trial_assignment)
                    trial_metrics = self._evaluate(instance, trial_solution)
                    evaluated_swaps += 1

                    if not self._candidate_preserves_hard_constraints(trial_metrics):
                        continue
                    if self._strongly_worsens_cg_z(current_metrics, trial_metrics):
                        continue

                    trial_score = self._score(trial_metrics)
                    if trial_score < current_score - self._config.min_score_improvement:
                        current_assignment = trial_assignment
                        current_solution = trial_solution
                        current_metrics = trial_metrics
                        current_score = trial_score
                        accepted_swaps += 1
                        improved_this_round = True

                if should_stop:
                    break

            if should_stop:
                break

            rounds_completed += 1
            if improved_this_round:
                rounds_without_improvement = 0
            else:
                rounds_without_improvement += 1

        return self._result(
            initial_solution=solution,
            solution=current_solution,
            initial_metrics=initial_metrics,
            metrics=current_metrics,
            ran=True,
            evaluated_swaps=evaluated_swaps,
            accepted_swaps=accepted_swaps,
            rounds_completed=rounds_completed,
            runtime_seconds=time.perf_counter() - start,
            initial_score=initial_score,
            final_score=current_score,
            stopped_reason=stopped_reason,
        )

    def _evaluate(
        self,
        instance: ProblemInstance,
        solution: StowageSolution,
    ) -> StowageMetrics:
        return evaluate_solution(
            instance,
            solution,
            cg_tolerance_lon=self._config.cg_tolerance_lon,
            cg_tolerance_lat=self._config.cg_tolerance_lat,
            min_incompatible_bay_distance=self._config.min_incompatible_bay_distance,
        )

    def _score(self, metrics: StowageMetrics) -> float:
        weights = self._config.weights
        lon_deviation = abs(metrics.cg_x)
        lat_deviation = abs(metrics.cg_y)
        lon_excess = max(0.0, lon_deviation - self._config.cg_tolerance_lon)
        lat_excess = max(0.0, lat_deviation - self._config.cg_tolerance_lat)
        return (
            weights.cg_excess_lon * lon_excess
            + weights.cg_excess_lat * lat_excess
            + weights.cg_lon * lon_deviation
            + weights.cg_lat * lat_deviation
            + weights.rehandling * metrics.real_rehandling_normalized
            + weights.vertical * metrics.cg_z_normalized
        )

    @staticmethod
    def _candidate_preserves_hard_constraints(metrics: StowageMetrics) -> bool:
        return metrics.constraint_violations == 0

    def _strongly_worsens_cg_z(
        self,
        current_metrics: StowageMetrics,
        candidate_metrics: StowageMetrics,
    ) -> bool:
        worsening = candidate_metrics.cg_z_normalized - current_metrics.cg_z_normalized
        return worsening > self._config.max_cg_z_worsening

    def _time_limit_reached(self, start: float) -> bool:
        limit = self._config.time_limit_seconds
        return limit is not None and time.perf_counter() - start >= limit

    @staticmethod
    def _validate_config(config: LocalSearchConfig) -> None:
        if config.max_iterations < 0:
            raise ValueError("`max_iterations` must be non-negative.")
        if config.max_rounds_without_improvement < 1:
            raise ValueError("`max_rounds_without_improvement` must be at least 1.")
        if config.time_limit_seconds is not None and config.time_limit_seconds < 0.0:
            raise ValueError("`time_limit_seconds` must be non-negative or None.")
        if config.min_score_improvement < 0.0:
            raise ValueError("`min_score_improvement` must be non-negative.")
        if config.max_cg_z_worsening < 0.0:
            raise ValueError("`max_cg_z_worsening` must be non-negative.")
        if config.cg_tolerance_lon < 0.0:
            raise ValueError("`cg_tolerance_lon` must be non-negative.")
        if config.cg_tolerance_lat < 0.0:
            raise ValueError("`cg_tolerance_lat` must be non-negative.")
        if config.min_incompatible_bay_distance < 0:
            raise ValueError("`min_incompatible_bay_distance` must be non-negative.")

    @staticmethod
    def _result(**kwargs: object) -> LocalSearchResult:
        return LocalSearchResult(**kwargs)


def improve_solution(
    instance: ProblemInstance,
    solution: StowageSolution,
    *,
    config: LocalSearchConfig | None = None,
) -> LocalSearchResult:
    """Convenience wrapper around :class:`SwapLocalSearch`."""
    return SwapLocalSearch(config).improve(instance, solution)
