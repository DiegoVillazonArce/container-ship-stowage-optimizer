"""Genetic Algorithm stowage solver.

The genetic solver is a metaheuristic for small and medium instances where a
complete MILP search may become too expensive. It does not provide optimality
proofs. Instead, it evolves complete or partially complete assignments,
repairs simple structural defects when possible, and scores every candidate
through the common metrics engine so its output can be compared with Greedy
and MILP results.

Chromosome representation:

``chromosome[i]`` is the slot assigned to ``instance.containers[i]``. A gene
may be ``None`` when no valid slot could be assigned, which lets infeasible
instances remain decodable and diagnosable through ``evaluate_solution``.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field, replace
from typing import TypeAlias

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
from stowage_optimizer.solvers.greedy import GreedySolver
from stowage_optimizer.solvers.local_search import (
    LocalSearchConfig,
    LocalSearchResult,
    LocalSearchWeights,
    improve_solution,
)

Chromosome: TypeAlias = tuple[SlotPosition | None, ...]


@dataclass(frozen=True, slots=True)
class GeneticWeights:
    """Relative importance of each term in the GA fitness score.

    The score is minimized. Constraint and CG-tolerance penalties are kept much
    larger than quality terms so infeasible individuals are useful for search
    diagnostics but are not preferred over feasible layouts.
    """

    cg_lon: float = 1.0
    cg_lat: float = 1.0
    vertical: float = 1.0
    rehandling: float = 1.0
    constraint_violation: float = 1000.0
    cg_tolerance_violation: float = 100.0


@dataclass(frozen=True, slots=True)
class GeneticConfig:
    """Configuration for the genetic search process.

    ``swap_mutation_probability`` and ``drop_mutation_probability`` shape what
    happens to a gene once ``mutation_probability`` selects it: first a swap
    with another random gene is attempted, otherwise the gene may be dropped to
    ``None``, and only then is it reassigned to a random compatible slot.
    """

    population_size: int = 50
    max_generations: int = 100
    mutation_probability: float = 0.05
    crossover_probability: float = 0.80
    swap_mutation_probability: float = 0.35
    drop_mutation_probability: float = 0.10
    tournament_size: int = 3
    elitism_count: int = 1
    random_seed: int | None = None
    weights: GeneticWeights = field(default_factory=GeneticWeights)
    min_incompatible_bay_distance: int = DEFAULT_MIN_INCOMPATIBLE_BAY_DISTANCE
    cg_tolerance_lon: float = DEFAULT_CG_TOLERANCE_LON
    cg_tolerance_lat: float = DEFAULT_CG_TOLERANCE_LAT
    enable_local_search: bool = False
    local_search_config: LocalSearchConfig | None = None


@dataclass(frozen=True, slots=True)
class _ScoredChromosome:
    """Internal population member with cached fitness."""

    score: float
    chromosome: Chromosome


@dataclass(slots=True)
class _AssignmentState:
    """Running totals used to score repair placements incrementally.

    Recomputing weight, horizontal moments, and dangerous-cargo bays from the
    full gene list for every candidate slot made repair scoring quadratic in
    practice; this state is built once per repair fill and updated as genes are
    placed, which yields identical scores at a fraction of the cost.
    """

    total_weight: float = 0.0
    moment_lon: float = 0.0
    moment_lat: float = 0.0
    flammable_bays: set[int] = field(default_factory=set)
    oxidizer_bays: set[int] = field(default_factory=set)

    def place(self, container: Container, slot: Slot) -> None:
        """Account for one container placed in one slot."""
        self.total_weight += container.weight
        self.moment_lon += container.weight * slot.x
        self.moment_lat += container.weight * slot.y
        if container.type == ContainerType.FLAMMABLE:
            self.flammable_bays.add(slot.bay)
        elif container.type == ContainerType.OXIDIZER:
            self.oxidizer_bays.add(slot.bay)


class GeneticSolver(Solver):
    """Genetic Algorithm solver using the common solver interface."""

    name = "genetic"

    def __init__(
        self,
        *,
        config: GeneticConfig | None = None,
        population_size: int | None = None,
        max_generations: int | None = None,
        mutation_probability: float | None = None,
        crossover_probability: float | None = None,
        tournament_size: int | None = None,
        elitism_count: int | None = None,
        random_seed: int | None = None,
        weights: GeneticWeights | None = None,
        min_incompatible_bay_distance: int | None = None,
        cg_tolerance_lon: float | None = None,
        cg_tolerance_lat: float | None = None,
        enable_local_search: bool | None = None,
        local_search_config: LocalSearchConfig | None = None,
    ) -> None:
        base_config = config or GeneticConfig()
        overrides = {
            key: value
            for key, value in {
                "population_size": population_size,
                "max_generations": max_generations,
                "mutation_probability": mutation_probability,
                "crossover_probability": crossover_probability,
                "tournament_size": tournament_size,
                "elitism_count": elitism_count,
                "random_seed": random_seed,
                "weights": weights,
                "min_incompatible_bay_distance": min_incompatible_bay_distance,
                "cg_tolerance_lon": cg_tolerance_lon,
                "cg_tolerance_lat": cg_tolerance_lat,
                "enable_local_search": enable_local_search,
                "local_search_config": local_search_config,
            }.items()
            if value is not None
        }
        self._config = replace(base_config, **overrides)
        self._validate_config(self._config)
        base_local_search_config = self._config.local_search_config or LocalSearchConfig(
            weights=LocalSearchWeights(
                cg_lon=self._config.weights.cg_lon,
                cg_lat=self._config.weights.cg_lat,
                rehandling=self._config.weights.rehandling,
                vertical=0.05 * self._config.weights.vertical,
            )
        )
        self._local_search_config = replace(
            base_local_search_config,
            cg_tolerance_lon=self._config.cg_tolerance_lon,
            cg_tolerance_lat=self._config.cg_tolerance_lat,
            min_incompatible_bay_distance=self._config.min_incompatible_bay_distance,
        )
        self._rng = random.Random(self._config.random_seed)
        # Per-instance memo for the slot lookup; population loops rebuild it
        # thousands of times otherwise. Keyed by identity because solve() runs
        # against one instance at a time.
        self._slots_memo_instance: ProblemInstance | None = None
        self._slots_memo: dict[SlotPosition, Slot] = {}

    def solve(self, instance: ProblemInstance) -> SolverResult:
        start = time.perf_counter()
        self._rng = random.Random(self._config.random_seed)
        invalid_result = validate_solver_input(
            instance,
            runtime_seconds=time.perf_counter() - start,
            cg_tolerance_lon=self._config.cg_tolerance_lon,
            cg_tolerance_lat=self._config.cg_tolerance_lat,
            min_incompatible_bay_distance=self._config.min_incompatible_bay_distance,
        )
        if invalid_result is not None:
            return invalid_result

        population = self._initial_population(instance)
        scored = self._score_population(instance, population)
        best = min(scored, key=lambda item: item.score)
        generations_run = 0

        for _ in range(self._config.max_generations):
            generations_run += 1
            next_population = self._elite_chromosomes(scored)
            while len(next_population) < self._config.population_size:
                parent_a = self._select(scored)
                parent_b = self._select(scored)

                if self._rng.random() < self._config.crossover_probability:
                    child_a, child_b = self._crossover(instance, parent_a, parent_b)
                else:
                    child_a, child_b = parent_a, parent_b

                next_population.append(self._mutate(instance, child_a))
                if len(next_population) < self._config.population_size:
                    next_population.append(self._mutate(instance, child_b))

            scored = self._score_population(instance, next_population)
            generation_best = min(scored, key=lambda item: item.score)
            if generation_best.score < best.score:
                best = generation_best

        solution = self._decode(instance, best.chromosome)
        metrics = evaluate_solution(
            instance,
            solution,
            cg_tolerance_lon=self._config.cg_tolerance_lon,
            cg_tolerance_lat=self._config.cg_tolerance_lat,
            min_incompatible_bay_distance=self._config.min_incompatible_bay_distance,
        )
        local_search_result: LocalSearchResult | None = None
        if self._config.enable_local_search:
            local_search_result = improve_solution(
                instance,
                solution,
                config=self._local_search_config,
            )
            solution = local_search_result.solution
            metrics = local_search_result.metrics

        runtime = time.perf_counter() - start
        status = SolverStatus.FEASIBLE if metrics.is_feasible else SolverStatus.INFEASIBLE

        return SolverResult(
            solution=solution,
            status=status,
            runtime_seconds=runtime,
            metrics=metrics,
            solver_status_detail=f"generations_run={generations_run}",
            local_search_result=local_search_result,
        )

    # -- Encoding and decoding ------------------------------------------

    def _encode(self, instance: ProblemInstance, solution: StowageSolution) -> Chromosome:
        """Encode a solution in instance container order."""
        return tuple(solution.slot_for(container.id) for container in instance.containers)

    def _decode(self, instance: ProblemInstance, chromosome: Chromosome) -> StowageSolution:
        """Decode a chromosome into a solution without hiding violations.

        Duplicate slots, reefers in non-reefer slots, and floating containers
        are kept so the metrics layer can penalize them. Unknown or malformed
        positions are skipped and therefore counted as unassigned containers.
        """
        valid_positions = {slot.position for slot in instance.ship.slots}
        assignment: dict[str, SlotPosition] = {}

        for container, gene in zip(instance.containers, self._normalize_chromosome(instance, chromosome)):
            position = self._coerce_position(gene)
            if position is None or position not in valid_positions:
                continue
            assignment[container.id] = position

        return StowageSolution.from_mapping(assignment)

    # -- Population lifecycle -------------------------------------------

    def _initial_population(self, instance: ProblemInstance) -> list[Chromosome]:
        population: list[Chromosome] = []

        greedy_result = GreedySolver(
            cg_tolerance_lon=self._config.cg_tolerance_lon,
            cg_tolerance_lat=self._config.cg_tolerance_lat,
            min_incompatible_bay_distance=self._config.min_incompatible_bay_distance
        ).solve(instance)
        population.append(self._repair_chromosome(instance, self._encode(instance, greedy_result.solution)))

        while len(population) < self._config.population_size:
            if self._rng.random() < 0.25:
                seed = self._rng.choice(population)
                candidate = self._mutate(instance, seed)
            else:
                candidate = self._random_chromosome(instance)
            population.append(candidate)

        return population

    def _random_chromosome(self, instance: ProblemInstance) -> Chromosome:
        """Generate a random complete individual when capacity allows it."""
        genes: list[SlotPosition | None] = [None] * len(instance.containers)
        occupied: set[SlotPosition] = set()
        slots_by_position = self._slots_by_position(instance)

        pending = self._shuffled_container_indices(instance)
        while pending:
            next_pending: list[int] = []
            made_progress = False

            for index in pending:
                container = instance.containers[index]
                candidates = self._candidate_slots(container, slots_by_position, occupied)
                if not candidates:
                    next_pending.append(index)
                    continue

                slot = self._rng.choice(candidates)
                genes[index] = slot.position
                occupied.add(slot.position)
                made_progress = True

            if not made_progress:
                break
            pending = next_pending

        return tuple(genes)

    def _score_population(
        self, instance: ProblemInstance, population: list[Chromosome]
    ) -> list[_ScoredChromosome]:
        return [
            _ScoredChromosome(score=self._fitness(instance, chromosome), chromosome=chromosome)
            for chromosome in population
        ]

    def _elite_chromosomes(self, scored: list[_ScoredChromosome]) -> list[Chromosome]:
        elite_count = min(self._config.elitism_count, self._config.population_size, len(scored))
        if elite_count <= 0:
            return []
        return [
            item.chromosome
            for item in sorted(scored, key=lambda item: item.score)[:elite_count]
        ]

    # -- Fitness ---------------------------------------------------------

    def _fitness(self, instance: ProblemInstance, chromosome: Chromosome) -> float:
        solution = self._decode(instance, chromosome)
        metrics = evaluate_solution(
            instance,
            solution,
            cg_tolerance_lon=self._config.cg_tolerance_lon,
            cg_tolerance_lat=self._config.cg_tolerance_lat,
            min_incompatible_bay_distance=self._config.min_incompatible_bay_distance,
        )
        weights = self._config.weights
        lon_excess = max(0.0, abs(metrics.cg_x) - self._config.cg_tolerance_lon)
        lat_excess = max(0.0, abs(metrics.cg_y) - self._config.cg_tolerance_lat)

        return (
            weights.cg_lon * abs(metrics.cg_x)
            + weights.cg_lat * abs(metrics.cg_y)
            + weights.vertical * metrics.cg_z_normalized
            + weights.rehandling * metrics.real_rehandling_normalized
            + weights.constraint_violation * metrics.constraint_violations
            + weights.cg_tolerance_violation * (lon_excess + lat_excess)
        )

    # -- Genetic operators ----------------------------------------------

    def _select(self, scored: list[_ScoredChromosome]) -> Chromosome:
        tournament_size = min(self._config.tournament_size, len(scored))
        contenders = self._rng.sample(scored, tournament_size)
        return min(contenders, key=lambda item: item.score).chromosome

    def _crossover(
        self, instance: ProblemInstance, first: Chromosome, second: Chromosome
    ) -> tuple[Chromosome, Chromosome]:
        first_genes = self._normalize_chromosome(instance, first)
        second_genes = self._normalize_chromosome(instance, second)

        child_a: list[SlotPosition | None] = []
        child_b: list[SlotPosition | None] = []
        for first_gene, second_gene in zip(first_genes, second_genes):
            if self._rng.random() < 0.5:
                child_a.append(first_gene)
                child_b.append(second_gene)
            else:
                child_a.append(second_gene)
                child_b.append(first_gene)

        return (
            self._repair_chromosome(instance, tuple(child_a)),
            self._repair_chromosome(instance, tuple(child_b)),
        )

    def _mutate(self, instance: ProblemInstance, chromosome: Chromosome) -> Chromosome:
        genes = list(self._normalize_chromosome(instance, chromosome))
        slots = tuple(instance.ship.slots)

        for index, container in enumerate(instance.containers):
            if self._rng.random() >= self._config.mutation_probability:
                continue

            if len(genes) > 1 and self._rng.random() < self._config.swap_mutation_probability:
                other = self._rng.randrange(len(genes))
                genes[index], genes[other] = genes[other], genes[index]
                continue

            if self._rng.random() < self._config.drop_mutation_probability:
                genes[index] = None
                continue

            compatible_slots = [
                slot for slot in slots if not container.is_reefer or slot.is_reefer
            ]
            genes[index] = self._rng.choice(compatible_slots).position if compatible_slots else None

        return self._repair_chromosome(instance, tuple(genes))

    # -- Repair ----------------------------------------------------------

    def _repair_chromosome(self, instance: ProblemInstance, chromosome: Chromosome) -> Chromosome:
        """Repair duplicate, missing, reefer-incompatible, and floating genes.

        The repair is intentionally local and conservative: it only assigns
        valid, unique, supported slots when such slots are currently available.
        In tightly constrained or over-capacity instances, remaining containers
        stay as ``None`` and are penalized as unassigned by the fitness layer.
        """
        genes = list(self._normalize_chromosome(instance, chromosome))
        slots_by_position = self._slots_by_position(instance)
        used: set[SlotPosition] = set()
        pending: set[int] = set()

        for index, gene in enumerate(genes):
            container = instance.containers[index]
            position = self._coerce_position(gene)
            if position is None or position not in slots_by_position:
                genes[index] = None
                pending.add(index)
                continue

            slot = slots_by_position[position]
            if position in used or (container.is_reefer and not slot.is_reefer):
                genes[index] = None
                pending.add(index)
                continue

            genes[index] = position
            used.add(position)

        self._remove_floating_assignments(genes, used, pending)
        self._fill_pending_assignments(instance, genes, used, pending)

        return tuple(genes)

    def _remove_floating_assignments(
        self,
        genes: list[SlotPosition | None],
        used: set[SlotPosition],
        pending: set[int],
    ) -> None:
        changed = True
        while changed:
            changed = False
            occupied = {position for position in genes if position is not None}
            for index, position in enumerate(tuple(genes)):
                if position is None:
                    continue
                bay, row, tier = position
                if tier > 1 and (bay, row, tier - 1) not in occupied:
                    genes[index] = None
                    used.discard(position)
                    pending.add(index)
                    changed = True

    def _fill_pending_assignments(
        self,
        instance: ProblemInstance,
        genes: list[SlotPosition | None],
        used: set[SlotPosition],
        pending: set[int],
    ) -> None:
        slots_by_position = self._slots_by_position(instance)
        pending_order = self._ordered_indices(instance, pending)
        state = self._assignment_state(instance, genes, slots_by_position)

        while pending_order:
            next_pending: list[int] = []
            made_progress = False

            for index in pending_order:
                container = instance.containers[index]
                candidates = self._candidate_slots(container, slots_by_position, used)
                if not candidates:
                    next_pending.append(index)
                    continue

                slot = min(
                    candidates,
                    key=lambda candidate: (
                        self._repair_slot_score(instance, state, container, candidate),
                        candidate.position,
                    ),
                )
                genes[index] = slot.position
                used.add(slot.position)
                state.place(container, slot)
                made_progress = True

            if not made_progress:
                break
            pending_order = next_pending

    @staticmethod
    def _assignment_state(
        instance: ProblemInstance,
        genes: list[SlotPosition | None],
        slots_by_position: dict[SlotPosition, Slot],
    ) -> _AssignmentState:
        """Build the running repair totals from the currently assigned genes."""
        state = _AssignmentState()
        for index, position in enumerate(genes):
            if position is None:
                continue
            state.place(instance.containers[index], slots_by_position[position])
        return state

    def _repair_slot_score(
        self,
        instance: ProblemInstance,
        state: _AssignmentState,
        container: Container,
        slot: Slot,
    ) -> float:
        new_weight = state.total_weight + container.weight
        weights = self._config.weights
        cg_lon = abs(state.moment_lon + container.weight * slot.x) / new_weight
        cg_lat = abs(state.moment_lat + container.weight * slot.y) / new_weight
        incompatible_penalty = self._incompatible_slot_penalty(
            container, slot, state.flammable_bays, state.oxidizer_bays
        )

        return (
            weights.cg_lon * cg_lon
            + weights.cg_lat * cg_lat
            + weights.vertical * slot.z
            + weights.rehandling * self._rehandling_risk(container, slot, instance)
            + incompatible_penalty
        )

    # -- Helpers ---------------------------------------------------------

    @staticmethod
    def _validate_config(config: GeneticConfig) -> None:
        if config.population_size < 1:
            raise ValueError("`population_size` must be at least 1.")
        if config.max_generations < 0:
            raise ValueError("`max_generations` must be non-negative.")
        if not 0.0 <= config.mutation_probability <= 1.0:
            raise ValueError("`mutation_probability` must be between 0 and 1.")
        if not 0.0 <= config.crossover_probability <= 1.0:
            raise ValueError("`crossover_probability` must be between 0 and 1.")
        if not 0.0 <= config.swap_mutation_probability <= 1.0:
            raise ValueError("`swap_mutation_probability` must be between 0 and 1.")
        if not 0.0 <= config.drop_mutation_probability <= 1.0:
            raise ValueError("`drop_mutation_probability` must be between 0 and 1.")
        if config.tournament_size < 1:
            raise ValueError("`tournament_size` must be at least 1.")
        if config.elitism_count < 0:
            raise ValueError("`elitism_count` must be non-negative.")
        if config.min_incompatible_bay_distance < 0:
            raise ValueError("`min_incompatible_bay_distance` must be non-negative.")
        if config.cg_tolerance_lon < 0.0:
            raise ValueError("`cg_tolerance_lon` must be non-negative.")
        if config.cg_tolerance_lat < 0.0:
            raise ValueError("`cg_tolerance_lat` must be non-negative.")

    def _slots_by_position(self, instance: ProblemInstance) -> dict[SlotPosition, Slot]:
        if self._slots_memo_instance is not instance:
            self._slots_memo_instance = instance
            self._slots_memo = {slot.position: slot for slot in instance.ship.slots}
        return self._slots_memo

    def _normalize_chromosome(
        self, instance: ProblemInstance, chromosome: Chromosome
    ) -> tuple[SlotPosition | None, ...]:
        genes = list(chromosome[: len(instance.containers)])
        if len(genes) < len(instance.containers):
            genes.extend([None] * (len(instance.containers) - len(genes)))
        return tuple(genes)

    @staticmethod
    def _coerce_position(gene: SlotPosition | None) -> SlotPosition | None:
        if gene is None:
            return None
        try:
            position = tuple(gene)
        except TypeError:
            return None
        if len(position) != 3:
            return None
        if any(isinstance(value, bool) or not isinstance(value, int) for value in position):
            return None
        return position

    def _shuffled_container_indices(self, instance: ProblemInstance) -> list[int]:
        grouped: dict[int, list[int]] = {}
        for index, container in enumerate(instance.containers):
            grouped.setdefault(self._priority(container), []).append(index)

        ordered: list[int] = []
        for priority in sorted(grouped):
            group = grouped[priority]
            self._rng.shuffle(group)
            ordered.extend(group)
        return ordered

    def _ordered_indices(self, instance: ProblemInstance, indices: set[int]) -> list[int]:
        return sorted(
            indices,
            key=lambda index: (
                self._priority(instance.containers[index]),
                -instance.containers[index].weight,
                instance.containers[index].id,
            ),
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
                continue
            if container.is_reefer and not slot.is_reefer:
                continue
            bay, row, tier = position
            if tier > 1 and (bay, row, tier - 1) not in occupied:
                continue
            candidates.append(slot)
        return candidates

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

    def _incompatible_slot_penalty(
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
            abs(slot.bay - bay) < self._config.min_incompatible_bay_distance
            for bay in conflicting_bays
        )
        return self._config.weights.constraint_violation if too_close else 0.0
