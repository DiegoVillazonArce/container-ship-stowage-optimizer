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
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from stowage_optimizer.core import Container, ProblemInstance, Route, Ship, StowageSolution
from stowage_optimizer.core.validation import validate_instance
from stowage_optimizer.core.metrics import (
    DEFAULT_CG_TOLERANCE_LAT,
    DEFAULT_CG_TOLERANCE_LON,
    DEFAULT_MIN_INCOMPATIBLE_BAY_DISTANCE,
    StowageMetrics,
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
    SolverStatus,
)

REQUIRED_CONTAINER_COLUMNS: tuple[str, ...] = ("id", "weight", "destination_port", "type")
SCENARIO_SCHEMA_VERSION = 1

PLAN_CSV_COLUMNS: tuple[str, ...] = (
    "container_id",
    "bay",
    "row",
    "tier",
    "weight",
    "destination_port",
    "type",
)
METRICS_CSV_COLUMNS: tuple[str, ...] = ("metric", "value")
COMPARISON_CSV_COLUMNS: tuple[str, ...] = (
    "algorithm",
    "status",
    "structural_feasible",
    "cg_ok",
    "operational_feasible",
    "runtime_s",
    "utilization",
    "cg_x",
    "cg_y",
    "cg_z_norm",
    "real_rehandling",
    "violations",
    "objective",
)

EXAMPLE_DATASET_SIZES: tuple[int, ...] = (20, 40, 60, 80)
EXAMPLE_DATASET_DIR = Path(__file__).resolve().parent.parent / "data" / "examples"
EXAMPLE_DATASET_DESCRIPTIONS: dict[int, str] = {
    20: "Small mixed-cargo dataset for quick interactive runs.",
    40: "Moderate mixed-cargo dataset for comparing solver behavior.",
    60: "Larger UI dataset for Greedy or Genetic Algorithm experiments.",
    80: "Largest bundled dataset for medium-scale stress testing.",
}

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


@dataclass(frozen=True)
class ExampleDataset:
    """Bundled example CSV exposed by the Streamlit app."""

    size: int
    file_name: str
    description: str
    csv_text: str


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


@dataclass(frozen=True)
class ScenarioImportResult:
    """Validated scenario import outcome."""

    instance: ProblemInstance | None
    params: SolverParams
    algorithms: tuple[str, ...]
    errors: tuple[str, ...]
    warnings: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        """Return whether the scenario is ready to load into the app."""
        return self.instance is not None and not self.errors


# --------------------------------------------------------------------------- #
# Scenario import/export                                                       #
# --------------------------------------------------------------------------- #


def scenario_to_dict(
    instance: ProblemInstance,
    params: SolverParams,
    algorithms: tuple[str, ...] = ("Greedy",),
) -> dict[str, Any]:
    """Return the complete, versioned JSON-ready scenario payload."""
    selected_algorithms = tuple(algorithms) or ("Greedy",)
    return {
        "schema_version": SCENARIO_SCHEMA_VERSION,
        "vessel": {
            "bays": instance.ship.bays,
            "rows": instance.ship.rows,
            "tiers": instance.ship.tiers,
        },
        "route": list(instance.route.ports),
        "containers": [
            {
                "id": container.id,
                "weight": container.weight,
                "destination_port": container.destination_port,
                "type": str(container.type),
            }
            for container in instance.containers
        ],
        "reefer": {
            "slots": [
                {"bay": bay, "row": row, "tier": tier}
                for bay, row, tier in sorted(instance.ship.reefer_slots)
            ],
        },
        "cg_tolerances": {
            "longitudinal": params.cg_tolerance_lon,
            "lateral": params.cg_tolerance_lat,
        },
        "objective_weights": {
            "cg_lon": params.cg_lon,
            "cg_lat": params.cg_lat,
            "vertical": params.vertical,
            "rehandling": params.rehandling,
        },
        "solver_settings": {
            "selected_algorithms": list(selected_algorithms),
            "min_incompatible_bay_distance": params.min_incompatible_bay_distance,
            "milp_time_limit_seconds": params.milp_time_limit_seconds,
            "ga_population_size": params.ga_population_size,
            "ga_max_generations": params.ga_max_generations,
            "ga_mutation_probability": params.ga_mutation_probability,
            "ga_crossover_probability": params.ga_crossover_probability,
            "ga_random_seed": params.ga_random_seed,
        },
    }


def scenario_to_json(
    instance: ProblemInstance,
    params: SolverParams,
    algorithms: tuple[str, ...] = ("Greedy",),
) -> str:
    """Serialize a complete scenario to deterministic, readable JSON."""
    return json.dumps(
        scenario_to_dict(instance, params, algorithms),
        indent=2,
    ) + "\n"


def import_scenario_json(text: str) -> ScenarioImportResult:
    """Parse, build, and validate a scenario JSON payload.

    Invalid scenarios return user-facing errors and no instance. The caller can
    safely avoid updating UI state or running solvers unless ``result.ok`` is
    true.
    """
    default_params = SolverParams()
    default_algorithms = ("Greedy",)

    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        return ScenarioImportResult(
            instance=None,
            params=default_params,
            algorithms=default_algorithms,
            errors=(
                "Invalid scenario JSON: "
                f"{exc.msg} at line {exc.lineno}, column {exc.colno}.",
            ),
        )

    if not isinstance(payload, dict):
        return ScenarioImportResult(
            instance=None,
            params=default_params,
            algorithms=default_algorithms,
            errors=("Scenario JSON must contain an object at the top level.",),
        )

    errors: list[str] = []
    version = payload.get("schema_version")
    if version != SCENARIO_SCHEMA_VERSION:
        errors.append(
            "Unsupported scenario schema_version "
            f"{version!r}; expected {SCENARIO_SCHEMA_VERSION}."
        )

    params, param_errors = _solver_params_from_payload(payload)
    algorithms, algorithm_errors = _algorithms_from_payload(payload)
    errors.extend(param_errors)
    errors.extend(algorithm_errors)

    vessel_data = _required_mapping(payload, "vessel", errors)
    route_data = _required_sequence(payload, "route", errors)
    container_data = _required_sequence(payload, "containers", errors)
    reefer_data = _required_mapping(payload, "reefer", errors)

    if errors:
        return ScenarioImportResult(
            instance=None,
            params=params,
            algorithms=algorithms,
            errors=tuple(errors),
        )

    assert vessel_data is not None
    assert route_data is not None
    assert container_data is not None
    assert reefer_data is not None

    try:
        reefer_slots = _reefer_slots_from_payload(reefer_data)
        ship = Ship(
            bays=_int_field(vessel_data, "bays", "vessel.bays"),
            rows=_int_field(vessel_data, "rows", "vessel.rows"),
            tiers=_int_field(vessel_data, "tiers", "vessel.tiers"),
            reefer_slots=reefer_slots,
        )
        route = Route(_route_ports_from_payload(route_data))
        containers = _containers_from_payload(container_data)
        instance = ProblemInstance(ship=ship, containers=containers, route=route)
    except ValueError as exc:
        return ScenarioImportResult(
            instance=None,
            params=params,
            algorithms=algorithms,
            errors=(f"Scenario is invalid: {exc}",),
        )

    validation = validate_instance(instance)
    if not validation.is_valid:
        return ScenarioImportResult(
            instance=None,
            params=params,
            algorithms=algorithms,
            errors=tuple(issue.message for issue in validation.errors),
            warnings=tuple(issue.message for issue in validation.warnings),
        )

    return ScenarioImportResult(
        instance=instance,
        params=params,
        algorithms=algorithms,
        errors=(),
        warnings=tuple(issue.message for issue in validation.warnings),
    )


def scenario_reefer_text(instance: ProblemInstance) -> str:
    """Format an instance's reefer slots for the Streamlit text area."""
    return "\n".join(
        f"({bay}, {row}, {tier})" for bay, row, tier in sorted(instance.ship.reefer_slots)
    )


def containers_to_csv_text(containers: tuple[Container, ...]) -> str:
    """Serialize containers using the stable input CSV schema."""
    rows = [
        {
            "id": container.id,
            "weight": container.weight,
            "destination_port": container.destination_port,
            "type": str(container.type),
        }
        for container in containers
    ]
    return _rows_to_csv(rows, REQUIRED_CONTAINER_COLUMNS)


# --------------------------------------------------------------------------- #
# CSV exports and bundled datasets                                             #
# --------------------------------------------------------------------------- #


def stowage_plan_csv(instance: ProblemInstance, solution: StowageSolution) -> str:
    """Serialize the final stowage plan with stable column names."""
    return _rows_to_csv(assignment_rows(instance, solution), PLAN_CSV_COLUMNS)


def metrics_csv(metrics_dict: dict[str, object]) -> str:
    """Serialize final metrics as stable ``metric,value`` rows."""
    rows = [
        {"metric": metric, "value": value}
        for metric, value in metrics_dict.items()
    ]
    return _rows_to_csv(rows, METRICS_CSV_COLUMNS)


def comparison_csv(rows: list[dict[str, object]]) -> str:
    """Serialize algorithm comparison rows with stable column names."""
    return _rows_to_csv(rows, COMPARISON_CSV_COLUMNS)


def example_dataset_catalog() -> tuple[ExampleDataset, ...]:
    """Return the bundled downloadable example container datasets."""
    datasets: list[ExampleDataset] = []
    for size in EXAMPLE_DATASET_SIZES:
        path = EXAMPLE_DATASET_DIR / f"containers_{size}.csv"
        datasets.append(
            ExampleDataset(
                size=size,
                file_name=path.name,
                description=EXAMPLE_DATASET_DESCRIPTIONS[size],
                csv_text=path.read_text(encoding="utf-8-sig"),
            )
        )
    return tuple(datasets)


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


def result_status_message(algorithm_label: str, result: SolverResult) -> tuple[str, str]:
    """Return a UI message level and text for a solver result."""
    if is_uncertified_milp_incumbent(algorithm_label, result):
        return (
            "warning",
            "MILP returned a feasible incumbent before optimality was certified. "
            "The plan is valid, but it is not proven optimal.",
        )

    if result.is_feasible:
        return ("success", f"Feasible solution ({result.status}).")

    if result.is_structurally_feasible and not result.cg_within_tolerance:
        return (
            "warning",
            f"Structurally feasible, but CG tolerance exceeded ({result.status}). "
            "Review CG x/y or relax the configured tolerances.",
        )

    if result.status == SolverStatus.NOT_SOLVED:
        return (
            "warning",
            "MILP stopped before certifying optimality and no certified or "
            "feasible incumbent plan was returned. Increase the time limit, "
            "or compare with the Greedy/GA solvers.",
        )

    return (
        "warning",
        f"No feasible solution ({result.status}). "
        "Check the violation counts and consider relaxing tolerances or adding capacity.",
    )


def is_uncertified_milp_incumbent(algorithm_label: str, result: SolverResult) -> bool:
    """Return whether a MILP result is a feasible but non-certified incumbent."""
    detail = (result.solver_status_detail or "").lower()
    return (
        algorithm_label == "MILP"
        and result.status == SolverStatus.FEASIBLE
        and result.is_feasible
        and "incumbent" in detail
        and "not certified" in detail
    )


# --------------------------------------------------------------------------- #
# Visual diagnostics (Phase 12)                                                #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class CgDiagnostic:
    """Structured center-of-gravity diagnostic for the visual layer.

    ``cg_x`` / ``cg_y`` are the computed horizontal center of gravity. The ideal
    academic reference is the vessel geometric center ``(0, 0)`` (see
    DESIGN.md section 10). Tolerance status is derived from the resolved
    :class:`SolverParams` so it stays consistent with how the plan was evaluated.
    """

    cg_x: float
    cg_y: float
    tolerance_lon: float
    tolerance_lat: float
    within_lon_tolerance: bool
    within_lat_tolerance: bool
    ideal_x: float = 0.0
    ideal_y: float = 0.0

    @property
    def within_tolerance(self) -> bool:
        """Return whether both horizontal CG axes are within tolerance."""
        return self.within_lon_tolerance and self.within_lat_tolerance

    @property
    def lon_deviation(self) -> float:
        """Return the absolute longitudinal deviation from the ideal point."""
        return abs(self.cg_x - self.ideal_x)

    @property
    def lat_deviation(self) -> float:
        """Return the absolute lateral deviation from the ideal point."""
        return abs(self.cg_y - self.ideal_y)


@dataclass(frozen=True)
class ViolationExplanation:
    """One readable, actionable diagnostic line for the results UI.

    ``severity`` is ``"error"`` for structural rule breaks, ``"warning"`` for a
    horizontal CG tolerance breach (a structurally valid plan may still be
    deliberately unbalanced), and ``"ok"`` for the positive "no issues" entry.
    ``metric_key`` links the explanation back to the shared metric it summarizes.
    """

    code: str
    title: str
    severity: str
    count: int
    message: str
    metric_key: str | None = None


def bay_row_balance_rows(
    instance: ProblemInstance, solution: StowageSolution
) -> list[dict[str, object]]:
    """Aggregate stowed weight and container counts per ``(bay, row)`` stack.

    Returns one row for every ``(bay, row)`` stack in the vessel grid, including
    empty stacks reported as zero, so the Streamlit balance map can render a
    complete bay-row heatmap. Rows are ordered by ``(bay, row)``. Assignments
    that reference an unknown container or a position outside the grid are
    skipped defensively rather than raising, keeping the diagnostic robust for
    partial or hand-built solutions.
    """
    containers_by_id = {container.id: container for container in instance.containers}

    totals: dict[tuple[int, int], tuple[float, int]] = {}
    for assignment in solution.assignments:
        bay, row, _tier = assignment.slot_position
        if not (1 <= bay <= instance.ship.bays and 1 <= row <= instance.ship.rows):
            continue
        container = containers_by_id.get(assignment.container_id)
        if container is None:
            continue
        prev_weight, prev_count = totals.get((bay, row), (0.0, 0))
        totals[(bay, row)] = (prev_weight + container.weight, prev_count + 1)

    rows: list[dict[str, object]] = []
    for bay in range(1, instance.ship.bays + 1):
        for row in range(1, instance.ship.rows + 1):
            weight, count = totals.get((bay, row), (0.0, 0))
            rows.append(
                {
                    "bay": bay,
                    "row": row,
                    "total_weight": weight,
                    "container_count": count,
                }
            )
    return rows


def cg_diagnostic(metrics: StowageMetrics, params: SolverParams) -> CgDiagnostic:
    """Build the center-of-gravity diagnostic against the ideal point ``(0, 0)``.

    Tolerance status is recomputed from the resolved :class:`SolverParams` so the
    diagnostic is self-contained and testable with explicit tolerances while
    matching the tolerances used to evaluate the plan.
    """
    return CgDiagnostic(
        cg_x=metrics.cg_x,
        cg_y=metrics.cg_y,
        tolerance_lon=params.cg_tolerance_lon,
        tolerance_lat=params.cg_tolerance_lat,
        within_lon_tolerance=abs(metrics.cg_x) <= params.cg_tolerance_lon,
        within_lat_tolerance=abs(metrics.cg_y) <= params.cg_tolerance_lat,
    )


def violation_explanations(result: SolverResult) -> list[ViolationExplanation]:
    """Build readable, actionable diagnostics from a solver result.

    Explanations are derived entirely from the shared final metrics so they stay
    consistent with the comparison table and CSV exports. Structural rule breaks
    are reported as errors; a horizontal CG tolerance breach is reported as a
    warning because a structurally valid plan may still be deliberately
    unbalanced. When nothing is wrong, a single positive ``"ok"`` entry is
    returned.
    """
    metrics = result.metrics
    explanations: list[ViolationExplanation] = []

    if metrics.unassigned_container_count:
        count = metrics.unassigned_container_count
        explanations.append(
            ViolationExplanation(
                code="unassigned",
                title="Unassigned containers",
                severity="error",
                count=count,
                message=(
                    f"{count} container(s) were not placed, so the stowage plan is "
                    "incomplete. Add slot capacity, relax constraints, or try "
                    "another algorithm."
                ),
                metric_key="unassigned_container_count",
            )
        )

    if metrics.duplicate_slot_violations:
        count = metrics.duplicate_slot_violations
        explanations.append(
            ViolationExplanation(
                code="duplicate_slot",
                title="Duplicate-slot violations",
                severity="error",
                count=count,
                message=(
                    f"{count} extra container(s) share an already-occupied slot. "
                    "Each (bay, row, tier) position may hold at most one container."
                ),
                metric_key="duplicate_slot_violations",
            )
        )

    if metrics.reefer_violations:
        count = metrics.reefer_violations
        explanations.append(
            ViolationExplanation(
                code="reefer",
                title="Reefer violations",
                severity="error",
                count=count,
                message=(
                    f"{count} reefer container(s) are in non-reefer slots. Move them "
                    "to reefer-capable positions or add more reefer slots."
                ),
                metric_key="reefer_violations",
            )
        )

    if metrics.stack_continuity_violations:
        count = metrics.stack_continuity_violations
        explanations.append(
            ViolationExplanation(
                code="stack_continuity",
                title="Stack-continuity violations",
                severity="error",
                count=count,
                message=(
                    f"{count} container(s) float above an empty slot. A tier may only "
                    "be used when the slot directly below it is occupied."
                ),
                metric_key="stack_continuity_violations",
            )
        )

    if metrics.incompatible_cargo_violations:
        count = metrics.incompatible_cargo_violations
        explanations.append(
            ViolationExplanation(
                code="incompatible_cargo",
                title="Incompatible-cargo violations",
                severity="error",
                count=count,
                message=(
                    f"{count} Flammable/Oxidizer bay pair(s) are closer than the "
                    "required minimum bay distance. Separate these cargo classes "
                    "into more distant bays."
                ),
                metric_key="incompatible_cargo_violations",
            )
        )

    if not metrics.within_lon_tolerance:
        direction = "bow-heavy" if metrics.cg_x > 0 else "stern-heavy"
        explanations.append(
            ViolationExplanation(
                code="cg_lon",
                title="Longitudinal CG out of tolerance",
                severity="warning",
                count=1,
                message=(
                    f"Longitudinal CG x is {metrics.cg_x:.3f} ({direction}), outside "
                    "the configured tolerance. Rebalance heavy containers along the "
                    "bays or relax the longitudinal tolerance."
                ),
                metric_key="cg_x",
            )
        )

    if not metrics.within_lat_tolerance:
        direction = "starboard-heavy" if metrics.cg_y > 0 else "port-heavy"
        explanations.append(
            ViolationExplanation(
                code="cg_lat",
                title="Lateral CG out of tolerance",
                severity="warning",
                count=1,
                message=(
                    f"Lateral CG y is {metrics.cg_y:.3f} ({direction}), outside the "
                    "configured tolerance. Rebalance heavy containers across the rows "
                    "or relax the lateral tolerance."
                ),
                metric_key="cg_y",
            )
        )

    if not explanations:
        explanations.append(
            ViolationExplanation(
                code="none",
                title="No violations",
                severity="ok",
                count=0,
                message=(
                    "No structural constraint violations and the horizontal center "
                    "of gravity is within tolerance."
                ),
            )
        )

    return explanations


def algorithm_diagnostic_row(algorithm_label: str, result: SolverResult) -> dict[str, object]:
    """Build one row of the side-by-side visual-diagnostics comparison.

    Focuses on feasibility, horizontal balance, and per-rule violation counts so
    solver tradeoffs are easy to scan. Complements :func:`comparison_row`, which
    carries the broader KPI set used for the comparison CSV export.
    """
    metrics = result.metrics
    return {
        "algorithm": algorithm_label,
        "operational_feasible": result.is_feasible,
        "structural_feasible": result.is_structurally_feasible,
        "cg_ok": result.cg_within_tolerance,
        "cg_x": round(metrics.cg_x, 4),
        "cg_y": round(metrics.cg_y, 4),
        "utilization": round(metrics.slot_utilization, 4),
        "real_rehandling": metrics.real_rehandling,
        "unassigned": metrics.unassigned_container_count,
        "duplicate_slots": metrics.duplicate_slot_violations,
        "reefer_violations": metrics.reefer_violations,
        "stack_continuity_violations": metrics.stack_continuity_violations,
        "incompatible_cargo_violations": metrics.incompatible_cargo_violations,
        "total_violations": metrics.constraint_violations,
    }


def _rows_to_csv(rows: list[dict[str, object]], columns: tuple[str, ...]) -> str:
    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=columns,
        extrasaction="ignore",
        lineterminator="\n",
    )
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


def _required_mapping(
    payload: dict[str, Any], key: str, errors: list[str]
) -> dict[str, Any] | None:
    value = payload.get(key)
    if not isinstance(value, dict):
        errors.append(f"Scenario field `{key}` must be an object.")
        return None
    return value


def _required_sequence(
    payload: dict[str, Any], key: str, errors: list[str]
) -> list[Any] | None:
    value = payload.get(key)
    if not isinstance(value, list):
        errors.append(f"Scenario field `{key}` must be a list.")
        return None
    return value


def _solver_params_from_payload(payload: dict[str, Any]) -> tuple[SolverParams, tuple[str, ...]]:
    errors: list[str] = []
    tolerances = _required_mapping(payload, "cg_tolerances", errors) or {}
    weights = _required_mapping(payload, "objective_weights", errors) or {}
    settings = _required_mapping(payload, "solver_settings", errors) or {}

    min_distance = _int_payload_field(
        settings,
        "min_incompatible_bay_distance",
        "solver_settings.min_incompatible_bay_distance",
        errors,
        default=DEFAULT_MIN_INCOMPATIBLE_BAY_DISTANCE,
    )
    ga_population = _int_payload_field(
        settings,
        "ga_population_size",
        "solver_settings.ga_population_size",
        errors,
        default=50,
    )
    ga_generations = _int_payload_field(
        settings,
        "ga_max_generations",
        "solver_settings.ga_max_generations",
        errors,
        default=100,
    )
    ga_seed = _optional_int_payload_field(
        settings,
        "ga_random_seed",
        "solver_settings.ga_random_seed",
        errors,
        default=42,
    )
    milp_time_limit = _optional_float_payload_field(
        settings,
        "milp_time_limit_seconds",
        "solver_settings.milp_time_limit_seconds",
        errors,
        default=None,
    )
    ga_mutation = _float_payload_field(
        settings,
        "ga_mutation_probability",
        "solver_settings.ga_mutation_probability",
        errors,
        default=0.05,
    )
    ga_crossover = _float_payload_field(
        settings,
        "ga_crossover_probability",
        "solver_settings.ga_crossover_probability",
        errors,
        default=0.80,
    )

    if min_distance < 0:
        errors.append("solver_settings.min_incompatible_bay_distance must be non-negative.")
    if ga_population <= 0:
        errors.append("solver_settings.ga_population_size must be positive.")
    if ga_generations <= 0:
        errors.append("solver_settings.ga_max_generations must be positive.")
    if milp_time_limit is not None and milp_time_limit < 0:
        errors.append("solver_settings.milp_time_limit_seconds must be non-negative or null.")
    if not 0.0 <= ga_mutation <= 1.0:
        errors.append("solver_settings.ga_mutation_probability must be between 0 and 1.")
    if not 0.0 <= ga_crossover <= 1.0:
        errors.append("solver_settings.ga_crossover_probability must be between 0 and 1.")

    params = SolverParams(
        cg_lon=_float_payload_field(
            weights, "cg_lon", "objective_weights.cg_lon", errors, default=1.0
        ),
        cg_lat=_float_payload_field(
            weights, "cg_lat", "objective_weights.cg_lat", errors, default=1.0
        ),
        vertical=_float_payload_field(
            weights, "vertical", "objective_weights.vertical", errors, default=1.0
        ),
        rehandling=_float_payload_field(
            weights, "rehandling", "objective_weights.rehandling", errors, default=1.0
        ),
        cg_tolerance_lon=_float_payload_field(
            tolerances,
            "longitudinal",
            "cg_tolerances.longitudinal",
            errors,
            default=DEFAULT_CG_TOLERANCE_LON,
        ),
        cg_tolerance_lat=_float_payload_field(
            tolerances,
            "lateral",
            "cg_tolerances.lateral",
            errors,
            default=DEFAULT_CG_TOLERANCE_LAT,
        ),
        min_incompatible_bay_distance=min_distance,
        milp_time_limit_seconds=milp_time_limit,
        ga_population_size=ga_population,
        ga_max_generations=ga_generations,
        ga_mutation_probability=ga_mutation,
        ga_crossover_probability=ga_crossover,
        ga_random_seed=ga_seed,
    )
    return params, tuple(errors)


def _algorithms_from_payload(payload: dict[str, Any]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    errors: list[str] = []
    settings = payload.get("solver_settings")
    if not isinstance(settings, dict):
        return ("Greedy",), ()

    raw_algorithms = settings.get("selected_algorithms")
    if not isinstance(raw_algorithms, list) or not raw_algorithms:
        return ("Greedy",), ("solver_settings.selected_algorithms must be a non-empty list.",)

    algorithms: list[str] = []
    for index, raw_algorithm in enumerate(raw_algorithms, start=1):
        if not isinstance(raw_algorithm, str):
            errors.append(f"solver_settings.selected_algorithms[{index}] must be a string.")
            continue
        if raw_algorithm not in ALGORITHMS:
            errors.append(
                f"Unknown algorithm `{raw_algorithm}` in scenario. "
                f"Expected one of: {', '.join(ALGORITHMS)}."
            )
            continue
        algorithms.append(raw_algorithm)

    return tuple(algorithms) or ("Greedy",), tuple(errors)


def _float_payload_field(
    mapping: dict[str, Any],
    key: str,
    label: str,
    errors: list[str],
    *,
    default: float,
) -> float:
    if key not in mapping:
        errors.append(f"Scenario field `{label}` is required.")
        return default
    value = mapping[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        errors.append(f"Scenario field `{label}` must be a finite number.")
        return default
    return float(value)


def _optional_float_payload_field(
    mapping: dict[str, Any],
    key: str,
    label: str,
    errors: list[str],
    *,
    default: float | None,
) -> float | None:
    if key not in mapping:
        errors.append(f"Scenario field `{label}` is required.")
        return default
    value = mapping[key]
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        errors.append(f"Scenario field `{label}` must be a finite number or null.")
        return default
    return float(value)


def _int_payload_field(
    mapping: dict[str, Any],
    key: str,
    label: str,
    errors: list[str],
    *,
    default: int,
) -> int:
    if key not in mapping:
        errors.append(f"Scenario field `{label}` is required.")
        return default
    return _int_value(mapping[key], label, errors, default=default)


def _optional_int_payload_field(
    mapping: dict[str, Any],
    key: str,
    label: str,
    errors: list[str],
    *,
    default: int | None,
) -> int | None:
    if key not in mapping:
        errors.append(f"Scenario field `{label}` is required.")
        return default
    value = mapping[key]
    if value is None:
        return None
    return _int_value(value, label, errors, default=default if default is not None else 0)


def _int_value(value: Any, label: str, errors: list[str], *, default: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        errors.append(f"Scenario field `{label}` must be an integer.")
        return default
    return value


def _reefer_slots_from_payload(reefer_data: dict[str, Any]) -> tuple[tuple[int, int, int], ...]:
    raw_slots = reefer_data.get("slots")
    if not isinstance(raw_slots, list):
        raise ValueError("reefer.slots must be a list.")

    slots: list[tuple[int, int, int]] = []
    for index, raw_slot in enumerate(raw_slots, start=1):
        label = f"reefer.slots[{index}]"
        if isinstance(raw_slot, dict):
            slot = (
                _int_field(raw_slot, "bay", f"{label}.bay"),
                _int_field(raw_slot, "row", f"{label}.row"),
                _int_field(raw_slot, "tier", f"{label}.tier"),
            )
        elif isinstance(raw_slot, list) and len(raw_slot) == 3:
            slot = (
                _json_int(raw_slot[0], f"{label}[0]"),
                _json_int(raw_slot[1], f"{label}[1]"),
                _json_int(raw_slot[2], f"{label}[2]"),
            )
        else:
            raise ValueError(f"{label} must be an object or [bay, row, tier] list.")

        if slot not in slots:
            slots.append(slot)

    return tuple(slots)


def _route_ports_from_payload(route_data: list[Any]) -> tuple[str, ...]:
    ports: list[str] = []
    for index, raw_port in enumerate(route_data, start=1):
        if not isinstance(raw_port, str):
            raise ValueError(f"route[{index}] must be a string.")
        ports.append(raw_port)
    return tuple(ports)


def _containers_from_payload(container_data: list[Any]) -> tuple[Container, ...]:
    containers: list[Container] = []
    required = set(REQUIRED_CONTAINER_COLUMNS)
    for index, raw_container in enumerate(container_data, start=1):
        label = f"containers[{index}]"
        if not isinstance(raw_container, dict):
            raise ValueError(f"{label} must be an object.")
        missing = sorted(required - raw_container.keys())
        if missing:
            raise ValueError(f"{label} is missing required field(s): {', '.join(missing)}.")
        containers.append(
            Container(
                id=raw_container["id"],
                weight=raw_container["weight"],
                destination_port=raw_container["destination_port"],
                type=raw_container["type"],
            )
        )
    return tuple(containers)


def _int_field(mapping: dict[str, Any], key: str, label: str) -> int:
    if key not in mapping:
        raise ValueError(f"{label} is required.")
    return _json_int(mapping[key], label)


def _json_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{label} must be an integer.")
    return value
