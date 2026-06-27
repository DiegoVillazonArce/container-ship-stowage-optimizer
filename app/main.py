"""Streamlit interface for the Container Ship Stowage Optimizer.

Run with::

    streamlit run app/main.py

This is a deliberately simple, functional UI for configuring a scenario,
loading or generating containers, running the Greedy / MILP / Genetic solvers,
and inspecting KPIs, tabular results, 3D stowage views, and port-by-port
unloading simulation. It is a thin layer over the existing domain model and
solvers; reusable, testable support logic lives in ``app/app_helpers.py`` and
``stowage_optimizer.viz``.
"""

from __future__ import annotations

import sys
import traceback
from dataclasses import dataclass
from pathlib import Path

# --- Import bootstrap -------------------------------------------------------
# The package is normally installed in editable mode (``pip install -e .``),
# but to keep ``streamlit run app/main.py`` working straight from a clone we
# also add the local ``app`` and project ``src`` directories when needed.
_APP = Path(__file__).resolve().parent
_SRC = _APP.parent / "src"
for path in (_APP, _SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import pandas as pd
import streamlit as st

import app_helpers as helpers
from stowage_optimizer.core import ProblemInstance, Route, Ship, validate_instance
from stowage_optimizer.core.examples import create_small_example_instance
from stowage_optimizer.core.metrics import (
    DEFAULT_CG_TOLERANCE_LAT,
    DEFAULT_CG_TOLERANCE_LON,
    DEFAULT_MIN_INCOMPATIBLE_BAY_DISTANCE,
    evaluate_solution,
    simulate_unloading_events,
)
from stowage_optimizer.viz import (
    build_bay_row_balance_figure,
    build_cg_diagnostic_figure,
    build_stowage_figure,
)

# Defaults match ``create_small_example_instance`` so the internal example runs
# cleanly with the form's initial values and no uploaded file.
DEFAULT_BAYS = 6
DEFAULT_ROWS = 4
DEFAULT_TIERS = 4
DEFAULT_REEFER_TEXT = "(1, 1, 1)\n(1, 2, 1)\n(2, 1, 1)\n(2, 2, 1)"
DEFAULT_ROUTE_TEXT = "Panama, Brazil, Spain"
IMPORTED_SCENARIO_SOURCE = "Imported scenario JSON"

CSV_TEMPLATE = (
    "id,weight,destination_port,type\n"
    "C001,28.5,Panama,Normal\n"
    "C002,18.0,Brazil,Reefer\n"
    "C003,24.0,Spain,Flammable\n"
    "C004,16.5,Spain,Oxidizer\n"
)

COLOR_BY_OPTIONS = {
    "Destination port": "destination_port",
    "Cargo type": "cargo_type",
}


@dataclass(frozen=True)
class SidebarConfig:
    """Raw, unvalidated inputs collected from the sidebar form."""

    bays: int
    rows: int
    tiers: int
    reefer_text: str
    route_text: str
    uploaded_csv_text: str | None
    uploaded_csv_error: str | None
    uploaded_name: str | None
    algorithms: tuple[str, ...]
    params: helpers.SolverParams
    run: bool


# --------------------------------------------------------------------------- #
# Sidebar                                                                       #
# --------------------------------------------------------------------------- #


def _render_scenario_importer() -> None:
    """Render the JSON upload path and apply valid scenarios to widget state."""
    message = st.session_state.pop("scenario_import_message", None)
    if message:
        st.sidebar.success(message)

    stored_errors = st.session_state.pop("scenario_import_errors", None)
    if stored_errors:
        st.sidebar.error("Scenario import failed:")
        for error in stored_errors:
            st.sidebar.markdown(f"- {error}")

    st.sidebar.subheader("Scenario JSON")
    uploaded = st.sidebar.file_uploader(
        "Import scenario JSON",
        type=["json"],
        key="scenario_json_upload",
        help="Loads vessel, route, containers, reefer slots, tolerances, weights, and solver settings.",
    )
    if uploaded is None:
        return

    if not st.sidebar.button("Import scenario", use_container_width=True):
        return

    try:
        text = uploaded.getvalue().decode("utf-8-sig")
    except UnicodeDecodeError:
        st.session_state["scenario_import_errors"] = (
            "Could not decode the scenario JSON as UTF-8.",
        )
        st.rerun()

    result = helpers.import_scenario_json(text)
    if not result.ok:
        st.session_state["scenario_import_errors"] = result.errors
        st.rerun()

    if result.instance is None:
        st.session_state["scenario_import_errors"] = (
            "Scenario import succeeded without a problem instance. "
            "Please export the scenario again and retry.",
        )
        st.rerun()

    _apply_imported_scenario(result)
    st.session_state["scenario_import_message"] = "Scenario imported and validated."
    st.rerun()


def _ensure_sidebar_defaults() -> None:
    """Initialize keyed widgets once so imports can safely overwrite them."""
    defaults = {
        "container_upload_nonce": 0,
        "scenario_bays": DEFAULT_BAYS,
        "scenario_rows": DEFAULT_ROWS,
        "scenario_tiers": DEFAULT_TIERS,
        "scenario_reefer_text": DEFAULT_REEFER_TEXT,
        "scenario_route_text": DEFAULT_ROUTE_TEXT,
        "scenario_algorithms": ["Greedy"],
        "scenario_cg_tolerance_lon": DEFAULT_CG_TOLERANCE_LON,
        "scenario_cg_tolerance_lat": DEFAULT_CG_TOLERANCE_LAT,
        "scenario_weight_cg_lon": 1.0,
        "scenario_weight_cg_lat": 1.0,
        "scenario_weight_vertical": 1.0,
        "scenario_weight_rehandling": 1.0,
        "scenario_min_incompatible_distance": DEFAULT_MIN_INCOMPATIBLE_BAY_DISTANCE,
        "scenario_milp_time_limit_seconds": 10.0,
        "scenario_ga_population_size": helpers.GA_PRESETS["Balanced"]["population_size"],
        "scenario_ga_max_generations": helpers.GA_PRESETS["Balanced"]["max_generations"],
        "scenario_ga_mutation_probability": 0.05,
        "scenario_ga_crossover_probability": 0.80,
        "scenario_ga_use_seed": True,
        "scenario_ga_random_seed": 42,
        "scenario_greedy_local_search_enabled": False,
        "scenario_ga_local_search_enabled": False,
        "scenario_local_search_max_iterations": helpers.DEFAULT_LOCAL_SEARCH_MAX_ITERATIONS,
        "scenario_local_search_max_rounds_without_improvement": (
            helpers.DEFAULT_LOCAL_SEARCH_MAX_ROUNDS_WITHOUT_IMPROVEMENT
        ),
        "scenario_local_search_time_limit_seconds": 0.0,
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


def _apply_imported_scenario(result: helpers.ScenarioImportResult) -> None:
    """Copy a validated scenario into Streamlit widget state."""
    if result.instance is None:
        raise ValueError("Cannot apply an imported scenario without a problem instance.")

    instance = result.instance
    params = result.params

    st.session_state["scenario_bays"] = instance.ship.bays
    st.session_state["scenario_rows"] = instance.ship.rows
    st.session_state["scenario_tiers"] = instance.ship.tiers
    st.session_state["scenario_reefer_text"] = helpers.scenario_reefer_text(instance)
    st.session_state["scenario_route_text"] = ", ".join(instance.route.ports)
    st.session_state["scenario_algorithms"] = list(result.algorithms)
    st.session_state["scenario_cg_tolerance_lon"] = params.cg_tolerance_lon
    st.session_state["scenario_cg_tolerance_lat"] = params.cg_tolerance_lat
    st.session_state["scenario_weight_cg_lon"] = params.cg_lon
    st.session_state["scenario_weight_cg_lat"] = params.cg_lat
    st.session_state["scenario_weight_vertical"] = params.vertical
    st.session_state["scenario_weight_rehandling"] = params.rehandling
    st.session_state["scenario_min_incompatible_distance"] = (
        params.min_incompatible_bay_distance
    )
    st.session_state["scenario_milp_time_limit_seconds"] = (
        params.milp_time_limit_seconds if params.milp_time_limit_seconds is not None else 0.0
    )
    st.session_state["scenario_ga_population_size"] = params.ga_population_size
    st.session_state["scenario_ga_max_generations"] = params.ga_max_generations
    st.session_state["scenario_ga_mutation_probability"] = params.ga_mutation_probability
    st.session_state["scenario_ga_crossover_probability"] = params.ga_crossover_probability
    st.session_state["scenario_ga_use_seed"] = params.ga_random_seed is not None
    st.session_state["scenario_ga_random_seed"] = (
        params.ga_random_seed if params.ga_random_seed is not None else 42
    )
    st.session_state["scenario_greedy_local_search_enabled"] = (
        params.greedy_local_search_enabled
    )
    st.session_state["scenario_ga_local_search_enabled"] = params.ga_local_search_enabled
    st.session_state["scenario_local_search_max_iterations"] = (
        params.local_search_max_iterations
    )
    st.session_state["scenario_local_search_max_rounds_without_improvement"] = (
        params.local_search_max_rounds_without_improvement
    )
    st.session_state["scenario_local_search_time_limit_seconds"] = (
        params.local_search_time_limit_seconds
        if params.local_search_time_limit_seconds is not None
        else 0.0
    )
    st.session_state["imported_container_csv_text"] = helpers.containers_to_csv_text(
        instance.containers
    )
    st.session_state["imported_container_source"] = IMPORTED_SCENARIO_SOURCE
    st.session_state["container_upload_nonce"] = (
        st.session_state.get("container_upload_nonce", 0) + 1
    )


def _clear_imported_containers() -> None:
    """Remove imported container CSV state and reset the upload widget."""
    st.session_state.pop("imported_container_csv_text", None)
    st.session_state.pop("imported_container_source", None)
    st.session_state["container_upload_nonce"] = (
        st.session_state.get("container_upload_nonce", 0) + 1
    )


def _render_imported_container_notice() -> None:
    """Explain that containers are already loaded from an imported scenario."""
    imported_csv_text = st.session_state.get("imported_container_csv_text")
    if imported_csv_text is None:
        return

    parsed = helpers.parse_containers_csv(imported_csv_text)
    if parsed.ok:
        message = (
            f"{len(parsed.containers)} containers loaded from the imported scenario. "
            "Upload a CSV below only if you want to replace them."
        )
    else:
        message = (
            "Containers were loaded from the imported scenario. "
            "Upload a CSV below only if you want to replace them."
        )

    st.sidebar.info(message)
    st.sidebar.download_button(
        "Download loaded containers CSV",
        data=imported_csv_text,
        file_name="imported_scenario_containers.csv",
        mime="text/csv",
        key="download_imported_containers_csv",
        use_container_width=True,
    )
    if st.sidebar.button(
        "Clear imported containers",
        key="clear_imported_containers",
        use_container_width=True,
    ):
        _clear_imported_containers()
        st.rerun()


def _render_current_scenario_download(config: SidebarConfig) -> None:
    """Render a JSON download for the currently configured scenario."""
    st.sidebar.subheader("Export scenario")
    instance, errors, _summary = build_scenario(config)
    if errors or instance is None:
        st.sidebar.caption("Fix scenario inputs before exporting JSON.")
        return

    validation = validate_instance(instance)
    if not validation.is_valid:
        st.sidebar.caption("Fix validation errors before exporting JSON.")
        return

    st.sidebar.download_button(
        "Download scenario JSON",
        data=helpers.scenario_to_json(instance, config.params, config.algorithms),
        file_name="stowage_scenario.json",
        mime="application/json",
        use_container_width=True,
    )


def _render_example_dataset_downloads() -> None:
    """Render downloadable bundled example container CSVs."""
    st.sidebar.subheader("Example datasets")
    try:
        datasets = helpers.example_dataset_catalog()
    except OSError as exc:
        st.sidebar.warning(f"Example datasets are unavailable: {exc}")
        return

    for dataset in datasets:
        st.sidebar.caption(f"{dataset.size} containers - {dataset.description}")
        st.sidebar.download_button(
            f"Download {dataset.size} containers",
            data=dataset.csv_text,
            file_name=dataset.file_name,
            mime="text/csv",
            key=f"download_dataset_{dataset.size}",
            use_container_width=True,
        )


def render_sidebar() -> SidebarConfig:
    """Render every input control and return the collected configuration."""
    st.sidebar.header("Scenario configuration")
    _render_scenario_importer()
    _ensure_sidebar_defaults()

    st.sidebar.subheader("Vessel dimensions")
    bays = st.sidebar.number_input(
        "Bays",
        min_value=1,
        max_value=50,
        step=1,
        key="scenario_bays",
    )
    rows = st.sidebar.number_input(
        "Rows",
        min_value=1,
        max_value=50,
        step=1,
        key="scenario_rows",
    )
    tiers = st.sidebar.number_input(
        "Tiers",
        min_value=1,
        max_value=50,
        step=1,
        key="scenario_tiers",
    )

    st.sidebar.subheader("Reefer-capable slots")
    reefer_text = st.sidebar.text_area(
        "Positions as `(bay, row, tier)`",
        help="One slot per line (or separated by `;`). Leave empty for no reefer slots.",
        height=110,
        key="scenario_reefer_text",
    )

    st.sidebar.subheader("Route (port sequence)")
    route_text = st.sidebar.text_area(
        "Ports in unloading order",
        help="Separate ports with commas or new lines. Order matters for rehandling.",
        height=80,
        key="scenario_route_text",
    )

    st.sidebar.subheader("Containers")
    has_imported_containers = st.session_state.get("imported_container_csv_text") is not None
    if has_imported_containers:
        st.sidebar.markdown(f"**{IMPORTED_SCENARIO_SOURCE}**")
        _render_imported_container_notice()

    container_upload_help = (
        "Columns: id, weight, destination_port, type. "
        "If omitted, the imported scenario containers remain active."
        if has_imported_containers
        else "Columns: id, weight, destination_port, type. "
        "If omitted, a built-in example is used."
    )
    uploaded = st.sidebar.file_uploader(
        "Replace containers with CSV" if has_imported_containers else "Upload container CSV",
        type=["csv"],
        help=container_upload_help,
        key=f"container_csv_upload_{st.session_state.get('container_upload_nonce', 0)}",
    )
    uploaded_csv_text: str | None = None
    uploaded_csv_error: str | None = None
    uploaded_name: str | None = None
    if uploaded is not None:
        if has_imported_containers:
            _clear_imported_containers()
        decoded = helpers.decode_csv_upload(uploaded.getvalue())
        uploaded_csv_text = decoded.text
        uploaded_csv_error = decoded.error
        uploaded_name = uploaded.name
    elif st.session_state.get("imported_container_csv_text") is not None:
        uploaded_csv_text = st.session_state["imported_container_csv_text"]
        uploaded_name = st.session_state.get("imported_container_source", "Imported scenario")
    st.sidebar.download_button(
        "Download CSV template",
        data=CSV_TEMPLATE,
        file_name="containers_template.csv",
        mime="text/csv",
    )

    st.sidebar.subheader("Algorithms")
    algorithms = st.sidebar.multiselect(
        "Run one or more",
        options=list(helpers.ALGORITHMS),
        help="Selecting several runs them all and shows a comparison table.",
        key="scenario_algorithms",
    )

    st.sidebar.subheader("Center-of-gravity tolerances")
    cg_tolerance_lon = st.sidebar.slider(
        "Longitudinal tolerance (tau_lon)",
        0.0,
        1.0,
        step=0.05,
        key="scenario_cg_tolerance_lon",
    )
    cg_tolerance_lat = st.sidebar.slider(
        "Lateral tolerance (tau_lat)",
        0.0,
        1.0,
        step=0.05,
        key="scenario_cg_tolerance_lat",
    )

    st.sidebar.subheader("Objective weights")
    cg_lon = st.sidebar.number_input(
        "Longitudinal CG weight",
        0.0,
        100.0,
        step=0.5,
        key="scenario_weight_cg_lon",
    )
    cg_lat = st.sidebar.number_input(
        "Lateral CG weight",
        0.0,
        100.0,
        step=0.5,
        key="scenario_weight_cg_lat",
    )
    vertical = st.sidebar.number_input(
        "Vertical CG weight",
        0.0,
        100.0,
        step=0.5,
        key="scenario_weight_vertical",
    )
    rehandling = st.sidebar.number_input(
        "Rehandling weight",
        0.0,
        100.0,
        step=0.5,
        key="scenario_weight_rehandling",
    )

    with st.sidebar.expander("Advanced constraints"):
        min_distance = st.number_input(
            "Min. incompatible-cargo bay distance",
            min_value=0,
            max_value=50,
            step=1,
            help="Minimum bay separation between Flammable and Oxidizer cargo.",
            key="scenario_min_incompatible_distance",
        )

    milp_time_limit: float | None = None
    if "MILP" in algorithms:
        with st.sidebar.expander("MILP settings", expanded=True):
            limit = st.number_input(
                "Time limit (seconds, 0 = no limit)",
                min_value=0.0,
                max_value=3600.0,
                step=1.0,
                key="scenario_milp_time_limit_seconds",
            )
            milp_time_limit = limit if limit > 0 else None

    ga_population = helpers.GA_PRESETS["Balanced"]["population_size"]
    ga_generations = helpers.GA_PRESETS["Balanced"]["max_generations"]
    ga_mutation = 0.05
    ga_crossover = 0.80
    ga_seed: int | None = 42
    if "Genetic Algorithm" in algorithms:
        with st.sidebar.expander("Genetic algorithm settings", expanded=True):
            ga_population = st.number_input(
                "Population size",
                min_value=2,
                max_value=500,
                step=1,
                key="scenario_ga_population_size",
            )
            ga_generations = st.number_input(
                "Max generations",
                min_value=1,
                max_value=5000,
                step=1,
                key="scenario_ga_max_generations",
            )
            ga_mutation = st.slider(
                "Mutation probability",
                0.0,
                1.0,
                step=0.01,
                key="scenario_ga_mutation_probability",
            )
            ga_crossover = st.slider(
                "Crossover probability",
                0.0,
                1.0,
                step=0.05,
                key="scenario_ga_crossover_probability",
            )
            use_seed = st.checkbox(
                "Use fixed random seed (reproducible)",
                key="scenario_ga_use_seed",
            )
            seed_value = st.number_input(
                "Random seed",
                min_value=0,
                step=1,
                key="scenario_ga_random_seed",
            )
            ga_seed = int(seed_value) if use_seed else None

    greedy_local_search_enabled = False
    ga_local_search_enabled = False
    local_search_iterations = helpers.DEFAULT_LOCAL_SEARCH_MAX_ITERATIONS
    local_search_rounds = helpers.DEFAULT_LOCAL_SEARCH_MAX_ROUNDS_WITHOUT_IMPROVEMENT
    local_search_time_limit: float | None = None
    if "Greedy" in algorithms or "Genetic Algorithm" in algorithms:
        with st.sidebar.expander("Local search post-processing"):
            if "Greedy" in algorithms:
                greedy_local_search_enabled = st.checkbox(
                    "Apply after Greedy",
                    key="scenario_greedy_local_search_enabled",
                )
            if "Genetic Algorithm" in algorithms:
                ga_local_search_enabled = st.checkbox(
                    "Apply after Genetic Algorithm",
                    key="scenario_ga_local_search_enabled",
                )
            local_search_iterations = st.number_input(
                "Max evaluated swaps",
                min_value=0,
                max_value=100_000,
                step=10,
                key="scenario_local_search_max_iterations",
            )
            local_search_rounds = st.number_input(
                "Max rounds without improvement",
                min_value=1,
                max_value=100,
                step=1,
                key="scenario_local_search_max_rounds_without_improvement",
            )
            local_limit = st.number_input(
                "Time limit seconds (0 = no limit)",
                min_value=0.0,
                max_value=3600.0,
                step=0.5,
                key="scenario_local_search_time_limit_seconds",
            )
            local_search_time_limit = local_limit if local_limit > 0 else None

    params = helpers.SolverParams(
        cg_lon=cg_lon,
        cg_lat=cg_lat,
        vertical=vertical,
        rehandling=rehandling,
        cg_tolerance_lon=cg_tolerance_lon,
        cg_tolerance_lat=cg_tolerance_lat,
        min_incompatible_bay_distance=int(min_distance),
        milp_time_limit_seconds=milp_time_limit,
        ga_population_size=int(ga_population),
        ga_max_generations=int(ga_generations),
        ga_mutation_probability=ga_mutation,
        ga_crossover_probability=ga_crossover,
        ga_random_seed=ga_seed,
        greedy_local_search_enabled=greedy_local_search_enabled,
        ga_local_search_enabled=ga_local_search_enabled,
        local_search_max_iterations=int(local_search_iterations),
        local_search_max_rounds_without_improvement=int(local_search_rounds),
        local_search_time_limit_seconds=local_search_time_limit,
    )

    run = st.sidebar.button(
        "Run optimization",
        type="primary",
        use_container_width=True,
        key="scenario_run_optimization",
    )

    return SidebarConfig(
        bays=int(bays),
        rows=int(rows),
        tiers=int(tiers),
        reefer_text=reefer_text,
        route_text=route_text,
        uploaded_csv_text=uploaded_csv_text,
        uploaded_csv_error=uploaded_csv_error,
        uploaded_name=uploaded_name,
        algorithms=tuple(algorithms),
        params=params,
        run=run,
    )


# --------------------------------------------------------------------------- #
# Scenario building and solving                                                 #
# --------------------------------------------------------------------------- #


def build_scenario(config: SidebarConfig) -> tuple[ProblemInstance | None, list[str], dict]:
    """Parse inputs and assemble a problem instance.

    Returns the instance (or ``None`` if it could not be built), a list of
    user-facing parse/build error messages, and a small summary dict for the UI.
    """
    errors: list[str] = []

    reefer = helpers.parse_reefer_slots(config.reefer_text)
    errors.extend(reefer.errors)

    route_result = helpers.parse_route_ports(config.route_text)
    errors.extend(route_result.errors)

    if config.uploaded_csv_error is not None:
        containers = ()
        errors.append(config.uploaded_csv_error)
        container_source = f"Uploaded file: {config.uploaded_name}"
    elif config.uploaded_csv_text is not None:
        parsed = helpers.parse_containers_csv(config.uploaded_csv_text)
        errors.extend(parsed.errors)
        containers = parsed.containers
        if config.uploaded_name == IMPORTED_SCENARIO_SOURCE:
            container_source = config.uploaded_name
        else:
            container_source = f"Uploaded file: {config.uploaded_name}"
    else:
        containers = create_small_example_instance().containers
        container_source = "Built-in example (no file uploaded)"

    if not config.algorithms:
        errors.append("Select at least one algorithm to run.")

    summary = {
        "container_source": container_source,
        "container_count": len(containers),
        "reefer_slot_count": len(reefer.positions),
        "ports": ", ".join(route_result.ports) if route_result.ports else "—",
    }

    if errors:
        return None, errors, summary

    try:
        ship = Ship(
            bays=config.bays,
            rows=config.rows,
            tiers=config.tiers,
            reefer_slots=reefer.positions,
        )
        route = Route(route_result.ports)
        instance = ProblemInstance(ship=ship, containers=containers, route=route)
    except ValueError as exc:
        errors.append(f"Could not build the scenario: {exc}")
        return None, errors, summary

    return instance, errors, summary


def run_solvers(instance: ProblemInstance, config: SidebarConfig) -> list[dict]:
    """Run every selected solver, capturing failures gracefully."""
    results: list[dict] = []
    for algorithm in config.algorithms:
        entry: dict = {
            "algorithm": algorithm,
            "result": None,
            "error": None,
            "traceback": None,
            "skipped": None,
        }
        if algorithm == "MILP":
            skip_reason = helpers.milp_size_guard_message(instance)
            if skip_reason is not None:
                entry["skipped"] = skip_reason
                results.append(entry)
                continue

        try:
            solver = helpers.build_solver(algorithm, config.params)
            entry["result"] = solver.solve(instance)
        except Exception as exc:  # noqa: BLE001 - surfaced safely in the UI.
            entry["error"] = f"{type(exc).__name__}: {exc}"
            entry["traceback"] = traceback.format_exc()
        results.append(entry)
    return results


def execute_run(config: SidebarConfig) -> None:
    """Build the scenario, validate it, run solvers, and store the payload."""
    instance, parse_errors, summary = build_scenario(config)

    payload: dict = {
        "summary": summary,
        "params": config.params,
        "parse_errors": parse_errors,
        "validation_errors": [],
        "validation_warnings": [],
        "results": [],
    }

    if instance is None:
        st.session_state["last_run"] = payload
        return

    validation = validate_instance(instance)
    payload["validation_errors"] = [issue.message for issue in validation.errors]
    payload["validation_warnings"] = [issue.message for issue in validation.warnings]

    if not validation.is_valid:
        st.session_state["last_run"] = payload
        return

    with st.spinner("Running optimization…"):
        payload["results"] = run_solvers(instance, config)
        payload["instance"] = instance

    st.session_state["last_run"] = payload


# --------------------------------------------------------------------------- #
# Results rendering                                                             #
# --------------------------------------------------------------------------- #


def render_summary(summary: dict) -> None:
    columns = st.columns(4)
    columns[0].metric("Containers", summary["container_count"])
    columns[1].metric("Reefer slots", summary["reefer_slot_count"])
    columns[2].metric("Ports", summary["ports"])
    columns[3].metric("Source", summary["container_source"])


def render_kpis(result) -> None:
    metrics = result.metrics

    top = st.columns(4)
    top[0].metric("Status", str(result.status))
    top[1].metric("Runtime (s)", f"{result.runtime_seconds:.4f}")
    top[2].metric("Utilization", f"{metrics.slot_utilization:.1%}")
    top[3].metric("Total weight (t)", f"{metrics.total_weight:.1f}")

    bottom = st.columns(4)
    bottom[0].metric("CG x", f"{metrics.cg_x:.3f}")
    bottom[1].metric("CG y", f"{metrics.cg_y:.3f}")
    bottom[2].metric("CG z (norm)", f"{metrics.cg_z_normalized:.3f}")
    bottom[3].metric("Real rehandling", metrics.real_rehandling)

    extra = st.columns(4)
    extra[0].metric("Constraint violations", metrics.constraint_violations)
    extra[1].metric("Unassigned", metrics.unassigned_container_count)
    if result.objective_value is not None:
        extra[2].metric("Objective", f"{result.objective_value:.4f}")
    if result.solver_status_detail:
        extra[3].metric("Solver detail", result.solver_status_detail)


def render_result_detail(
    entry: dict,
    instance: ProblemInstance,
    params: helpers.SolverParams,
    balance_weight_range: tuple[float, float] | None = None,
) -> None:
    if entry.get("skipped") is not None:
        st.warning(entry["skipped"])
        return

    if entry["error"] is not None:
        st.error(f"{entry['algorithm']} failed: {entry['error']}")
        return

    result = entry["result"]
    level, message = helpers.result_status_message(entry["algorithm"], result)
    if level == "success":
        st.success(message)
    else:
        st.warning(message)

    render_kpis(result)
    if entry["algorithm"] in ("Greedy", "Genetic Algorithm"):
        st.markdown("**Local search**")
        st.dataframe(
            pd.DataFrame(helpers.local_search_summary_rows(result)),
            use_container_width=True,
            hide_index=True,
        )

    download_key_prefix = _streamlit_key("download", entry["algorithm"])
    file_prefix = _streamlit_key(entry["algorithm"]).strip("_")

    st.markdown("**Common metrics**")
    metrics_df = pd.DataFrame(helpers.metrics_table_rows(result.metrics.as_dict()))
    st.dataframe(metrics_df, use_container_width=True, hide_index=True)
    st.download_button(
        "Download metrics CSV",
        data=helpers.metrics_csv(result.metrics.as_dict()),
        file_name=f"{file_prefix}_metrics.csv",
        mime="text/csv",
        key=f"{download_key_prefix}_metrics_csv",
    )

    st.markdown("**Final stowage plan**")
    rows = helpers.assignment_rows(instance, result.solution)
    if rows:
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    else:
        st.info("No containers were assigned, so the stowage plan is empty.")
    st.download_button(
        "Download final stowage plan CSV",
        data=helpers.stowage_plan_csv(instance, result.solution),
        file_name=f"{file_prefix}_stowage_plan.csv",
        mime="text/csv",
        key=f"{download_key_prefix}_plan_csv",
    )

    render_diagnostics_section(
        entry["algorithm"],
        instance,
        result,
        params,
        balance_weight_range,
    )
    render_visualization_section(entry["algorithm"], instance, result, params)


def render_diagnostics_section(
    algorithm_label: str,
    instance: ProblemInstance,
    result,
    params: helpers.SolverParams,
    balance_weight_range: tuple[float, float] | None = None,
) -> None:
    """Render the Phase 12 visual diagnostics for a single solver result.

    Combines a bay-row balance map, a center-of-gravity diagnostic against the
    ideal point, and readable violation explanations derived from the shared
    final metrics.
    """
    st.markdown("**Visual diagnostics**")

    columns = st.columns(2)

    balance_rows = helpers.bay_row_balance_rows(instance, result.solution)
    balance_figure = build_bay_row_balance_figure(
        instance,
        balance_rows,
        title=f"{algorithm_label}: bay-row weight balance",
        weight_range=balance_weight_range,
    )
    diag_key_prefix = _streamlit_key("diagnostics", algorithm_label)
    columns[0].plotly_chart(
        balance_figure,
        use_container_width=True,
        key=f"{diag_key_prefix}_balance",
    )

    diagnostic = helpers.cg_diagnostic(result.metrics, params)
    cg_figure = build_cg_diagnostic_figure(
        diagnostic.cg_x,
        diagnostic.cg_y,
        diagnostic.tolerance_lon,
        diagnostic.tolerance_lat,
        title=f"{algorithm_label}: center of gravity vs. ideal",
    )
    columns[1].plotly_chart(
        cg_figure,
        use_container_width=True,
        key=f"{diag_key_prefix}_cg",
    )
    if diagnostic.within_tolerance:
        columns[1].success(
            f"CG within tolerance — x={diagnostic.cg_x:.3f}, y={diagnostic.cg_y:.3f} "
            f"(tau_lon={diagnostic.tolerance_lon:.2f}, tau_lat={diagnostic.tolerance_lat:.2f})."
        )
    else:
        columns[1].warning(
            f"CG outside tolerance — x={diagnostic.cg_x:.3f}, y={diagnostic.cg_y:.3f} "
            f"(tau_lon={diagnostic.tolerance_lon:.2f}, tau_lat={diagnostic.tolerance_lat:.2f})."
        )

    st.markdown("_Constraint diagnostics_")
    for explanation in helpers.violation_explanations(result):
        _render_violation_explanation(explanation)


def _render_violation_explanation(explanation: helpers.ViolationExplanation) -> None:
    """Render one violation explanation using a severity-appropriate callout."""
    if explanation.severity == "ok":
        st.success(explanation.message)
        return
    text = f"**{explanation.title}** ({explanation.count}): {explanation.message}"
    if explanation.severity == "error":
        st.error(text)
    else:
        st.warning(text)


def render_diagnostics_comparison(
    successful: list[dict],
    instance: ProblemInstance,
    params: helpers.SolverParams,
    balance_weight_range: tuple[float, float],
) -> None:
    """Render a side-by-side visual diagnostics comparison across algorithms."""
    st.subheader("Diagnostics comparison")

    diagnostic_rows = [
        helpers.algorithm_diagnostic_row(entry["algorithm"], entry["result"])
        for entry in successful
    ]
    st.dataframe(
        pd.DataFrame(diagnostic_rows),
        use_container_width=True,
        hide_index=True,
    )

    st.markdown("**Center of gravity by algorithm**")
    cg_columns = st.columns(len(successful))
    for column, entry in zip(cg_columns, successful):
        diagnostic = helpers.cg_diagnostic(entry["result"].metrics, params)
        column.plotly_chart(
            build_cg_diagnostic_figure(
                diagnostic.cg_x,
                diagnostic.cg_y,
                diagnostic.tolerance_lon,
                diagnostic.tolerance_lat,
                title=f"{entry['algorithm']} CG",
            ),
            use_container_width=True,
            key=f"{_streamlit_key('comparison', entry['algorithm'])}_cg",
        )

    st.markdown("**Bay-row balance by algorithm**")
    balance_row_sets = [
        helpers.bay_row_balance_rows(instance, entry["result"].solution)
        for entry in successful
    ]
    balance_columns = st.columns(len(successful))
    for column, entry, balance_rows in zip(balance_columns, successful, balance_row_sets):
        column.plotly_chart(
            build_bay_row_balance_figure(
                instance,
                balance_rows,
                title=f"{entry['algorithm']} balance",
                weight_range=balance_weight_range,
            ),
            use_container_width=True,
            key=f"{_streamlit_key('comparison', entry['algorithm'])}_balance",
        )


def _shared_balance_weight_range(
    balance_row_sets: list[list[dict[str, object]]],
) -> tuple[float, float]:
    """Return one heatmap color range for side-by-side balance comparisons."""
    max_weight = max(
        (
            float(row["total_weight"])
            for balance_rows in balance_row_sets
            for row in balance_rows
        ),
        default=0.0,
    )
    return (0.0, max(max_weight, 1.0))


def render_visualization_section(
    algorithm_label: str,
    instance: ProblemInstance,
    result,
    params: helpers.SolverParams,
) -> None:
    """Render the Phase 7 3D figure and port-by-port unloading simulation."""
    key_prefix = _streamlit_key("viz", algorithm_label)

    st.markdown("**3D visualization**")
    color_label = st.selectbox(
        "Color containers by",
        options=list(COLOR_BY_OPTIONS),
        key=f"{key_prefix}_color_by",
    )
    color_by = COLOR_BY_OPTIONS[color_label]

    figure = build_stowage_figure(
        instance,
        result.solution,
        color_by=color_by,
        title=f"{algorithm_label} stowage plan",
    )
    st.plotly_chart(
        figure,
        use_container_width=True,
        key=f"{key_prefix}_stowage",
    )

    st.markdown("**Unloading simulation**")
    steps = simulate_unloading_events(instance, result.solution)
    if not steps:
        st.info("No route ports are available for unloading simulation.")
        return

    selected_port = st.selectbox(
        "Simulation port",
        options=[step.port for step in steps],
        key=f"{key_prefix}_simulation_port",
    )
    selected_step = next(step for step in steps if step.port == selected_port)

    simulation_metrics = evaluate_solution(
        instance,
        selected_step.remaining_assignment,
        cg_tolerance_lon=params.cg_tolerance_lon,
        cg_tolerance_lat=params.cg_tolerance_lat,
        min_incompatible_bay_distance=params.min_incompatible_bay_distance,
    )
    remaining_count = len(selected_step.remaining_assignment.assignments)

    top = st.columns(6)
    top[0].metric("Utilization", f"{simulation_metrics.slot_utilization:.1%}")
    top[1].metric("CG x", f"{simulation_metrics.cg_x:.3f}")
    top[2].metric("CG y", f"{simulation_metrics.cg_y:.3f}")
    top[3].metric("CG z", f"{simulation_metrics.cg_z_normalized:.3f}")
    top[4].metric("Remaining", remaining_count)
    top[5].metric("Rehandles", selected_step.rehandle_count)

    movement_columns = st.columns(2)
    _render_container_id_table(
        movement_columns[0],
        "Removed containers",
        selected_step.removed_container_ids,
        instance,
    )
    _render_container_id_table(
        movement_columns[1],
        "Rehandled containers",
        selected_step.rehandled_container_ids,
        instance,
    )

    remaining_figure = build_stowage_figure(
        instance,
        selected_step.remaining_assignment,
        color_by=color_by,
        highlighted_container_ids=selected_step.rehandled_container_ids,
        title=f"After unloading {selected_step.port}",
    )
    st.plotly_chart(
        remaining_figure,
        use_container_width=True,
        key=f"{key_prefix}_remaining_{_streamlit_key(selected_step.port)}",
    )


def _render_container_id_table(
    container,
    title: str,
    container_ids: tuple[str, ...],
    instance: ProblemInstance,
) -> None:
    container.markdown(f"**{title}**")
    rows = _container_rows(instance, container_ids)
    if not rows:
        container.caption("None.")
        return
    container.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def _container_rows(
    instance: ProblemInstance,
    container_ids: tuple[str, ...],
) -> list[dict[str, object]]:
    containers_by_id = {container.id: container for container in instance.containers}
    rows: list[dict[str, object]] = []
    for container_id in container_ids:
        item = containers_by_id.get(container_id)
        if item is None:
            raise ValueError(
                "Unloading simulation referenced an unknown container ID: "
                f"{container_id}."
            )
        rows.append(
            {
                "container_id": container_id,
                "weight": item.weight,
                "destination_port": item.destination_port,
                "type": str(item.type),
            }
        )
    return rows


def _streamlit_key(*parts: str) -> str:
    raw = "_".join(parts)
    return "".join(character.lower() if character.isalnum() else "_" for character in raw)


def render_results() -> None:
    payload = st.session_state.get("last_run")
    if payload is None:
        st.info(
            "Configure the scenario in the sidebar and press **Run optimization**. "
            "With the default values you can run Greedy on the built-in example "
            "without uploading anything."
        )
        return

    render_summary(payload["summary"])
    st.divider()

    if payload["parse_errors"]:
        st.error("The scenario could not be parsed:")
        for message in payload["parse_errors"]:
            st.markdown(f"- {message}")
        return

    if payload["validation_warnings"]:
        st.warning("Validation warnings:")
        for message in payload["validation_warnings"]:
            st.markdown(f"- {message}")

    if payload["validation_errors"]:
        st.error("Validation failed — the solver was not run:")
        for message in payload["validation_errors"]:
            st.markdown(f"- {message}")
        return

    results = payload["results"]
    instance = payload["instance"]
    params = payload.get("params", helpers.SolverParams())

    successful = [entry for entry in results if entry["result"] is not None]
    balance_weight_range = _shared_balance_weight_range(
        [
            helpers.bay_row_balance_rows(instance, entry["result"].solution)
            for entry in successful
        ]
    )
    if len(successful) > 1:
        st.subheader("Algorithm comparison")
        comparison_rows = [
            helpers.comparison_row(entry["algorithm"], entry["result"]) for entry in successful
        ]
        comparison = pd.DataFrame(comparison_rows)
        st.dataframe(comparison, use_container_width=True, hide_index=True)
        st.download_button(
            "Download algorithm comparison CSV",
            data=helpers.comparison_csv(comparison_rows),
            file_name="algorithm_comparison.csv",
            mime="text/csv",
            key="download_algorithm_comparison_csv",
        )
        st.caption(
            "Comparison uses shared final metrics. Raw objective values are not "
            "comparable across algorithms with different internal proxies."
        )
        render_diagnostics_comparison(successful, instance, params, balance_weight_range)

    st.subheader("Results")
    if len(results) == 1:
        render_result_detail(results[0], instance, params, balance_weight_range)
    else:
        tabs = st.tabs([entry["algorithm"] for entry in results])
        for tab, entry in zip(tabs, results):
            with tab:
                render_result_detail(entry, instance, params, balance_weight_range)

    _render_debug_expander(results)


def _render_debug_expander(results: list[dict]) -> None:
    failures = [entry for entry in results if entry["traceback"] is not None]
    if not failures:
        return
    with st.expander("Debug details (tracebacks)"):
        for entry in failures:
            st.markdown(f"**{entry['algorithm']}**")
            st.code(entry["traceback"], language="text")


# --------------------------------------------------------------------------- #
# Entry point                                                                   #
# --------------------------------------------------------------------------- #


def main() -> None:
    st.set_page_config(page_title="Container Ship Stowage Optimizer", layout="wide")
    st.title("Container Ship Stowage Optimizer")
    st.caption(
        "Configure a scenario, run Greedy / MILP / Genetic solvers, and compare "
        "their stowage plans, KPIs, 3D layout, and unloading simulation."
    )

    config = render_sidebar()
    _render_current_scenario_download(config)
    _render_example_dataset_downloads()
    if config.run:
        execute_run(config)

    render_results()


if __name__ == "__main__":
    main()
