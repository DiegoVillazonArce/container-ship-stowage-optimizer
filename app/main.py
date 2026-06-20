"""Streamlit interface for the Container Ship Stowage Optimizer (Phase 6).

Run with::

    streamlit run app/main.py

This is a deliberately simple, functional UI for configuring a scenario,
loading or generating containers, running the Greedy / MILP / Genetic
solvers, and inspecting tabular results and KPIs. It is a thin layer over the
existing domain model and solvers; all reusable, testable logic lives in
``app/app_helpers.py``.

Scope note: 3D Plotly visualization and the port-by-port unloading simulation
belong to Phase 7 and are intentionally **not** implemented here. The displayed
``within tolerance`` flags for the Greedy solver use the metrics-engine default
tolerances, because the greedy constructor does not take CG tolerances as input
(they only affect MILP feasibility and the GA penalty term).
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
)

# Defaults match ``create_small_example_instance`` so the internal example runs
# cleanly with the form's initial values and no uploaded file.
DEFAULT_BAYS = 6
DEFAULT_ROWS = 4
DEFAULT_TIERS = 4
DEFAULT_REEFER_TEXT = "(1, 1, 1)\n(1, 2, 1)\n(2, 1, 1)\n(2, 2, 1)"
DEFAULT_ROUTE_TEXT = "Panama, Brazil, Spain"

CSV_TEMPLATE = (
    "id,weight,destination_port,type\n"
    "C001,28.5,Panama,Normal\n"
    "C002,18.0,Brazil,Reefer\n"
    "C003,24.0,Spain,Flammable\n"
    "C004,16.5,Spain,Oxidizer\n"
)


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


def render_sidebar() -> SidebarConfig:
    """Render every input control and return the collected configuration."""
    st.sidebar.header("Scenario configuration")

    st.sidebar.subheader("Vessel dimensions")
    bays = st.sidebar.number_input("Bays", min_value=1, max_value=50, value=DEFAULT_BAYS, step=1)
    rows = st.sidebar.number_input("Rows", min_value=1, max_value=50, value=DEFAULT_ROWS, step=1)
    tiers = st.sidebar.number_input("Tiers", min_value=1, max_value=50, value=DEFAULT_TIERS, step=1)

    st.sidebar.subheader("Reefer-capable slots")
    reefer_text = st.sidebar.text_area(
        "Positions as `(bay, row, tier)`",
        value=DEFAULT_REEFER_TEXT,
        help="One slot per line (or separated by `;`). Leave empty for no reefer slots.",
        height=110,
    )

    st.sidebar.subheader("Route (port sequence)")
    route_text = st.sidebar.text_area(
        "Ports in unloading order",
        value=DEFAULT_ROUTE_TEXT,
        help="Separate ports with commas or new lines. Order matters for rehandling.",
        height=80,
    )

    st.sidebar.subheader("Containers")
    uploaded = st.sidebar.file_uploader(
        "Upload container CSV",
        type=["csv"],
        help="Columns: id, weight, destination_port, type. "
        "If omitted, a built-in example is used.",
    )
    uploaded_csv_text: str | None = None
    uploaded_csv_error: str | None = None
    uploaded_name: str | None = None
    if uploaded is not None:
        decoded = helpers.decode_csv_upload(uploaded.getvalue())
        uploaded_csv_text = decoded.text
        uploaded_csv_error = decoded.error
        uploaded_name = uploaded.name
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
        default=["Greedy"],
        help="Selecting several runs them all and shows a comparison table.",
    )

    st.sidebar.subheader("Center-of-gravity tolerances")
    cg_tolerance_lon = st.sidebar.slider(
        "Longitudinal tolerance (τ_lon)", 0.0, 1.0, value=DEFAULT_CG_TOLERANCE_LON, step=0.05
    )
    cg_tolerance_lat = st.sidebar.slider(
        "Lateral tolerance (τ_lat)", 0.0, 1.0, value=DEFAULT_CG_TOLERANCE_LAT, step=0.05
    )

    st.sidebar.subheader("Objective weights")
    cg_lon = st.sidebar.number_input("Longitudinal CG weight", 0.0, 100.0, value=1.0, step=0.5)
    cg_lat = st.sidebar.number_input("Lateral CG weight", 0.0, 100.0, value=1.0, step=0.5)
    vertical = st.sidebar.number_input("Vertical CG weight", 0.0, 100.0, value=1.0, step=0.5)
    rehandling = st.sidebar.number_input("Rehandling weight", 0.0, 100.0, value=1.0, step=0.5)

    with st.sidebar.expander("Advanced constraints"):
        min_distance = st.number_input(
            "Min. incompatible-cargo bay distance",
            min_value=0,
            max_value=50,
            value=DEFAULT_MIN_INCOMPATIBLE_BAY_DISTANCE,
            step=1,
            help="Minimum bay separation between Flammable and Oxidizer cargo.",
        )

    milp_time_limit: float | None = None
    if "MILP" in algorithms:
        with st.sidebar.expander("MILP settings", expanded=True):
            limit = st.number_input(
                "Time limit (seconds, 0 = no limit)",
                min_value=0.0,
                max_value=3600.0,
                value=10.0,
                step=1.0,
            )
            milp_time_limit = limit if limit > 0 else None

    ga_population = helpers.GA_PRESETS["Balanced"]["population_size"]
    ga_generations = helpers.GA_PRESETS["Balanced"]["max_generations"]
    ga_mutation = 0.05
    ga_crossover = 0.80
    ga_seed: int | None = 42
    if "Genetic Algorithm" in algorithms:
        with st.sidebar.expander("Genetic algorithm settings", expanded=True):
            preset = st.selectbox(
                "Search preset", options=list(helpers.GA_PRESETS), index=1
            )
            ga_population = helpers.GA_PRESETS[preset]["population_size"]
            ga_generations = helpers.GA_PRESETS[preset]["max_generations"]
            st.caption(
                f"Population {ga_population}, up to {ga_generations} generations."
            )
            ga_mutation = st.slider("Mutation probability", 0.0, 1.0, value=0.05, step=0.01)
            ga_crossover = st.slider("Crossover probability", 0.0, 1.0, value=0.80, step=0.05)
            use_seed = st.checkbox("Use fixed random seed (reproducible)", value=True)
            seed_value = st.number_input("Random seed", min_value=0, value=42, step=1)
            ga_seed = int(seed_value) if use_seed else None

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
    )

    run = st.sidebar.button("Run optimization", type="primary", use_container_width=True)

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
        entry: dict = {"algorithm": algorithm, "result": None, "error": None, "traceback": None}
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


def render_result_detail(entry: dict, instance: ProblemInstance) -> None:
    if entry["error"] is not None:
        st.error(f"{entry['algorithm']} failed: {entry['error']}")
        return

    result = entry["result"]
    if result.is_feasible:
        st.success(f"Feasible solution ({result.status}).")
    else:
        st.warning(
            f"No feasible solution ({result.status}). "
            "Check the violation counts and consider relaxing tolerances or "
            "adding capacity."
        )

    render_kpis(result)

    st.markdown("**Common metrics**")
    metrics_df = pd.DataFrame(helpers.metrics_table_rows(result.metrics.as_dict()))
    st.dataframe(metrics_df, use_container_width=True, hide_index=True)

    st.markdown("**Final stowage plan**")
    rows = helpers.assignment_rows(instance, result.solution)
    if rows:
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    else:
        st.info("No containers were assigned, so the stowage plan is empty.")


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

    successful = [entry for entry in results if entry["result"] is not None]
    if len(successful) > 1:
        st.subheader("Algorithm comparison")
        comparison = pd.DataFrame(
            helpers.comparison_row(entry["algorithm"], entry["result"]) for entry in successful
        )
        st.dataframe(comparison, use_container_width=True, hide_index=True)
        st.caption(
            "Comparison uses shared final metrics. Raw objective values are not "
            "comparable across algorithms with different internal proxies."
        )

    st.subheader("Results")
    if len(results) == 1:
        render_result_detail(results[0], instance)
    else:
        tabs = st.tabs([entry["algorithm"] for entry in results])
        for tab, entry in zip(tabs, results):
            with tab:
                render_result_detail(entry, instance)

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
        "their stowage plans and KPIs. (Phase 6 — tabular results only.)"
    )

    config = render_sidebar()
    if config.run:
        execute_run(config)

    render_results()


if __name__ == "__main__":
    main()
