"""Pure, Streamlit-independent helpers for the stowage Streamlit app.

This module is intentionally free of any ``streamlit`` import so the CSV,
route, and reefer-slot parsing, the solver wiring, and the table-shaping logic
can be unit-tested directly without spinning up a Streamlit session. The thin
UI layer in :mod:`main` wires these helpers into widgets.

Domain validation (duplicate IDs, unknown types, destinations missing from the
route, capacity, reefer capacity) is intentionally **not** duplicated here. It
lives in :func:`stowage_optimizer.core.validation.validate_instance`, which the
app runs after a :class:`ProblemInstance` is built and solvers also run as an
API safety check. The parsers below only catch file-format problems (missing
columns, blank cells, non-numeric weights, badly formatted slot triples) so the
user gets clear, early feedback.
"""

from __future__ import annotations

import csv
import io
import math
import re
from dataclasses import dataclass

from stowage_optimizer.core import Container, ProblemInstance, StowageSolution
from stowage_optimizer.core.metrics import (
    DEFAULT_CG_TOLERANCE_LAT,
    DEFAULT_CG_TOLERANCE_LON,
    DEFAULT_MIN_INCOMPATIBLE_BAY_DISTANCE,
)
from stowage_optimizer.solvers import (
    GeneticSolver,
    GeneticWeights,
    GreedySolver,
    GreedyWeights,
    MILPSolver,
    MILPWeights,
    Solver,
    SolverResult,
)

REQUIRED_CONTAINER_COLUMNS: tuple[str, ...] = ("id", "weight", "destination_port", "type")

# A leading UTF-8 byte-order mark can survive into the first CSV header name.
_BOM = chr(0xFEFF)

# Labels shown for selecting algorithms in the UI. The order is the run order.
ALGORITHMS: tuple[str, ...] = ("Greedy", "MILP", "Genetic Algorithm")

# Upper bound for MILP assignment binaries allowed from the Streamlit UI.
# The MILP remains available from code for deliberate experiments; this guard
# keeps an interactive run from accidentally building an oversized model.
MILP_ASSIGNMENT_VARIABLE_LIMIT = 100_000

# Simple presets for the genetic algorithm so users do not need to tune every
# operator. "Balanced" mirrors :class:`GeneticConfig` defaults.
GA_PRESETS: dict[str, dict[str, int]] = {
    "Fast": {"population_size": 20, "max_generations": 30},
    "Balanced": {"population_size": 50, "max_generations": 100},
    "Deeper search": {"population_size": 80, "max_generations": 250},
}

# Human-readable labels for the flat metrics dictionary produced by
# ``StowageMetrics.as_dict``. Used to render the common metrics table.
METRIC_LABELS: dict[str, str] = {
    "total_weight": "Total weight (t)",
    "slot_utilization": "Slot utilization",
    "longitudinal_moment": "Longitudinal moment",
    "lateral_moment": "Lateral moment",
    "cg_x": "CG x (longitudinal)",
    "cg_y": "CG y (lateral)",
    "cg_z_normalized": "CG z (normalized)",
    "port_side_weight": "Port-side weight (t)",
    "starboard_side_weight": "Starboard-side weight (t)",
    "bow_weight": "Bow weight (t)",
    "stern_weight": "Stern weight (t)",
    "within_lon_tolerance": "Within longitudinal CG tolerance",
    "within_lat_tolerance": "Within lateral CG tolerance",
    "unassigned_container_count": "Unassigned containers",
    "duplicate_slot_violations": "Duplicate-slot violations",
    "reefer_violations": "Reefer violations",
    "stack_continuity_violations": "Stack-continuity violations",
    "incompatible_cargo_violations": "Incompatible-cargo violations",
    "constraint_violations": "Total constraint violations",
    "real_rehandling": "Real rehandling moves",
    "real_rehandling_normalized": "Real rehandling (normalized)",
    "is_structurally_feasible": "Structurally feasible",
    "cg_within_tolerance": "CG within tolerance",
    "operationally_feasible": "Operationally feasible",
    "is_feasible": "Operationally feasible",
}


# --------------------------------------------------------------------------- #
# Parsing                                                                       #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ContainerParseResult:
    """Outcome of parsing a container CSV payload."""

    containers: tuple[Container, ...]
    errors: tuple[str, ...]

    @property
    def ok(self) -> bool:
        """Return whether the payload parsed without any format errors."""
        return not self.errors


@dataclass(frozen=True)
class CsvDecodeResult:
    """Decoded CSV upload text or a user-facing decoding error."""

    text: str | None
    error: str | None

    @property
    def ok(self) -> bool:
        return self.error is None


@dataclass(frozen=True)
class ReeferParseResult:
    """Outcome of parsing the reefer-slot text input."""

    positions: tuple[tuple[int, int, int], ...]
    errors: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.errors


@dataclass(frozen=True)
class RouteParseResult:
    """Outcome of parsing the route (port sequence) text input."""

    ports: tuple[str, ...]
    errors: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.errors


def decode_csv_upload(data: bytes) -> CsvDecodeResult:
    """Decode uploaded CSV bytes using common encodings.

    UTF-8 with an optional BOM is preferred. Windows-1252 is accepted as a
    practical fallback because CSV files exported from Excel on Windows often
    use that encoding. If neither works, return a clean UI-facing error instead
    of letting the Streamlit script fail during sidebar rendering.
    """
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return CsvDecodeResult(text=data.decode(encoding), error=None)
        except UnicodeDecodeError:
            continue

    return CsvDecodeResult(
        text=None,
        error=(
            "Could not decode the uploaded CSV as UTF-8 or Windows-1252. "
            "Please save the file as UTF-8 CSV and upload it again."
        ),
    )


def parse_containers_csv(text: str) -> ContainerParseResult:
    """Parse container rows from CSV text.

    Expects the columns ``id``, ``weight``, ``destination_port`` and ``type``
    (case-insensitive, surrounding whitespace ignored). Reports missing columns,
    blank required cells, and non-numeric weights with row numbers so the user
    can locate problems quickly. Rows with errors are skipped; valid rows are
    returned as :class:`Container` objects for later domain validation.
    """
    reader = csv.DictReader(io.StringIO(text))
    fieldnames = reader.fieldnames
    if not fieldnames:
        return ContainerParseResult((), ("The CSV file is empty or has no header row.",))

    # Map normalized column name -> original header so lookups tolerate case
    # and whitespace differences (and a leading UTF-8 BOM on the first header).
    normalized = {
        name.strip().lstrip(_BOM).lower(): name
        for name in fieldnames
        if name is not None
    }
    missing = [column for column in REQUIRED_CONTAINER_COLUMNS if column not in normalized]
    if missing:
        return ContainerParseResult(
            (),
            (
                "Missing required column(s): "
                f"{', '.join(missing)}. Expected columns: "
                f"{', '.join(REQUIRED_CONTAINER_COLUMNS)}.",
            ),
        )

    errors: list[str] = []
    containers: list[Container] = []
    row_number = 1  # The header is row 1; data rows start at 2.

    for raw_row in reader:
        row_number += 1
        container_id = _cell(raw_row, normalized["id"])
        weight_raw = _cell(raw_row, normalized["weight"])
        destination = _cell(raw_row, normalized["destination_port"])
        cargo_type = _cell(raw_row, normalized["type"])

        # A completely empty line (common trailing newline) is silently skipped.
        if not any((container_id, weight_raw, destination, cargo_type)):
            continue

        row_errors: list[str] = []
        if not container_id:
            row_errors.append(f"Row {row_number}: missing container id.")
        if not destination:
            row_errors.append(f"Row {row_number}: missing destination_port.")
        if not cargo_type:
            row_errors.append(f"Row {row_number}: missing type.")

        weight: float | None = None
        if not weight_raw:
            row_errors.append(f"Row {row_number}: missing weight.")
        else:
            try:
                weight = float(weight_raw)
            except ValueError:
                row_errors.append(f"Row {row_number}: weight `{weight_raw}` is not a number.")
            else:
                if not math.isfinite(weight):
                    row_errors.append(
                        f"Row {row_number}: weight `{weight_raw}` must be finite."
                    )

        if row_errors:
            errors.extend(row_errors)
            continue

        assert weight is not None  # Guaranteed: weight_raw was present and numeric.
        containers.append(
            Container(
                id=container_id,
                weight=weight,
                destination_port=destination,
                type=cargo_type,
            )
        )

    if not containers and not errors:
        errors.append("The CSV file does not contain any container rows.")

    return ContainerParseResult(tuple(containers), tuple(errors))


def parse_reefer_slots(text: str) -> ReeferParseResult:
    """Parse reefer-capable slot positions from free text.

    Accepts ``(bay,row,tier)`` triples separated by newlines or semicolons; the
    surrounding parentheses are optional. An empty input means "no reefer slots".
    """
    if not text or not text.strip():
        return ReeferParseResult((), ())

    errors: list[str] = []
    positions: list[tuple[int, int, int]] = []

    for token in re.split(r"[;\n]+", text):
        cleaned = token.strip().strip("()").strip()
        if not cleaned:
            continue

        parts = [part.strip() for part in cleaned.split(",")]
        if len(parts) != 3:
            errors.append(f"Invalid reefer slot `{token.strip()}`: expected `(bay, row, tier)`.")
            continue
        try:
            bay, row, tier = (int(part) for part in parts)
        except ValueError:
            errors.append(
                f"Invalid reefer slot `{token.strip()}`: bay, row and tier must be integers."
            )
            continue

        position = (bay, row, tier)
        if position not in positions:
            positions.append(position)

    return ReeferParseResult(tuple(positions), tuple(errors))


def parse_route_ports(text: str) -> RouteParseResult:
    """Parse an ordered list of ports separated by commas or newlines."""
    ports = [port.strip() for port in re.split(r"[,\n]+", text or "") if port.strip()]

    errors: list[str] = []
    if not ports:
        errors.append("The route must contain at least one port.")

    duplicates = sorted({port for port in ports if ports.count(port) > 1})
    for port in duplicates:
        errors.append(f"Duplicate port in route: `{port}`. Route ports must be unique.")

    return RouteParseResult(tuple(ports), tuple(errors))


def _cell(row: dict[str, str | None], key: str) -> str:
    """Return a trimmed cell value, treating missing cells as blank."""
    return (row.get(key) or "").strip()


# --------------------------------------------------------------------------- #
# Solver wiring                                                                 #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class SolverParams:
    """Resolved configuration shared by the UI and :func:`build_solver`.

    The four common objective weights (``cg_lon``, ``cg_lat``, ``vertical``,
    ``rehandling``) map onto every solver. The remaining fields apply only where
    the corresponding solver supports them. Greedy uses CG tolerances when
    evaluating the final plan; MILP enforces them as hard constraints; GA uses
    them in the fitness penalty and final evaluation.
    """

    cg_lon: float = 1.0
    cg_lat: float = 1.0
    vertical: float = 1.0
    rehandling: float = 1.0
    cg_tolerance_lon: float = DEFAULT_CG_TOLERANCE_LON
    cg_tolerance_lat: float = DEFAULT_CG_TOLERANCE_LAT
    min_incompatible_bay_distance: int = DEFAULT_MIN_INCOMPATIBLE_BAY_DISTANCE
    milp_time_limit_seconds: float | None = None
    ga_population_size: int = 50
    ga_max_generations: int = 100
    ga_mutation_probability: float = 0.05
    ga_crossover_probability: float = 0.80
    ga_random_seed: int | None = 42


def build_solver(algorithm: str, params: SolverParams) -> Solver:
    """Construct a configured solver for ``algorithm``.

    ``algorithm`` must be one of :data:`ALGORITHMS`.
    """
    if algorithm == "Greedy":
        return GreedySolver(
            weights=GreedyWeights(
                cg_lon=params.cg_lon,
                cg_lat=params.cg_lat,
                vertical=params.vertical,
                rehandling=params.rehandling,
            ),
            cg_tolerance_lon=params.cg_tolerance_lon,
            cg_tolerance_lat=params.cg_tolerance_lat,
            min_incompatible_bay_distance=params.min_incompatible_bay_distance,
        )

    if algorithm == "MILP":
        return MILPSolver(
            weights=MILPWeights(
                cg_lon=params.cg_lon,
                cg_lat=params.cg_lat,
                vertical=params.vertical,
                rehandling=params.rehandling,
            ),
            cg_tolerance_lon=params.cg_tolerance_lon,
            cg_tolerance_lat=params.cg_tolerance_lat,
            min_incompatible_bay_distance=params.min_incompatible_bay_distance,
            time_limit_seconds=params.milp_time_limit_seconds,
        )

    if algorithm == "Genetic Algorithm":
        return GeneticSolver(
            weights=GeneticWeights(
                cg_lon=params.cg_lon,
                cg_lat=params.cg_lat,
                vertical=params.vertical,
                rehandling=params.rehandling,
            ),
            population_size=params.ga_population_size,
            max_generations=params.ga_max_generations,
            mutation_probability=params.ga_mutation_probability,
            crossover_probability=params.ga_crossover_probability,
            random_seed=params.ga_random_seed,
            cg_tolerance_lon=params.cg_tolerance_lon,
            cg_tolerance_lat=params.cg_tolerance_lat,
            min_incompatible_bay_distance=params.min_incompatible_bay_distance,
        )

    raise ValueError(f"Unknown algorithm: {algorithm!r}. Expected one of {ALGORITHMS}.")


def milp_assignment_variable_upper_bound(instance: ProblemInstance) -> int:
    """Return an upper bound for MILP container-slot assignment binaries."""
    return len(instance.containers) * instance.ship.slot_count


def milp_size_guard_message(
    instance: ProblemInstance,
    *,
    max_assignment_variables: int = MILP_ASSIGNMENT_VARIABLE_LIMIT,
) -> str | None:
    """Return a user-facing skip reason when a MILP run is too large for the UI."""
    estimate = milp_assignment_variable_upper_bound(instance)
    if estimate <= max_assignment_variables:
        return None

    return (
        "MILP was skipped because this scenario can create up to "
        f"{estimate:,} assignment variables "
        f"({len(instance.containers):,} containers x {instance.ship.slot_count:,} slots), "
        f"above the Streamlit UI limit of {max_assignment_variables:,}. "
        "Reduce the vessel size or container count, or run Greedy / Genetic Algorithm."
    )


# --------------------------------------------------------------------------- #
# Table shaping                                                                 #
# --------------------------------------------------------------------------- #


def assignment_rows(
    instance: ProblemInstance, solution: StowageSolution
) -> list[dict[str, object]]:
    """Build stowage-plan rows sorted by ``(bay, row, tier)``.

    Each row always carries ``container_id``, ``bay``, ``row`` and ``tier`` as
    required by Phase 6, plus the container's weight, destination and type for
    convenient inspection.
    """
    containers_by_id = {container.id: container for container in instance.containers}

    rows: list[dict[str, object]] = []
    for assignment in solution.assignments:
        bay, row, tier = assignment.slot_position
        container = containers_by_id.get(assignment.container_id)
        rows.append(
            {
                "container_id": assignment.container_id,
                "bay": bay,
                "row": row,
                "tier": tier,
                "weight": container.weight if container else None,
                "destination_port": container.destination_port if container else None,
                "type": str(container.type) if container else None,
            }
        )

    rows.sort(key=lambda entry: (entry["bay"], entry["row"], entry["tier"]))
    return rows


def metrics_table_rows(metrics_dict: dict[str, object]) -> list[dict[str, object]]:
    """Map a flat metrics dictionary to labelled ``metric``/``value`` rows."""
    hidden_keys = {"is_feasible"} if "operationally_feasible" in metrics_dict else set()
    return [
        {"metric": METRIC_LABELS.get(key, key), "value": value}
        for key, value in metrics_dict.items()
        if key not in hidden_keys
    ]


def comparison_row(algorithm_label: str, result: SolverResult) -> dict[str, object]:
    """Build one row of the multi-algorithm comparison table.

    Comparison relies on shared final metrics rather than raw internal objective
    values, which are not comparable across algorithms (see DESIGN.md s.13).
    """
    metrics = result.metrics
    return {
        "algorithm": algorithm_label,
        "status": str(result.status),
        "structural_feasible": result.is_structurally_feasible,
        "cg_ok": result.cg_within_tolerance,
        "operational_feasible": result.is_feasible,
        "runtime_s": round(result.runtime_seconds, 4),
        "utilization": round(metrics.slot_utilization, 4),
        "cg_x": round(metrics.cg_x, 4),
        "cg_y": round(metrics.cg_y, 4),
        "cg_z_norm": round(metrics.cg_z_normalized, 4),
        "real_rehandling": metrics.real_rehandling,
        "violations": metrics.constraint_violations,
        "objective": (
            round(result.objective_value, 4) if result.objective_value is not None else None
        ),
    }
