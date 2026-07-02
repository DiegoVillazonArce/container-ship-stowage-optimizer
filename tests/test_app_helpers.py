"""Tests for the Streamlit-free helpers in ``app/app_helpers.py``.

These cover the pure parsing, solver-wiring, and table-shaping logic only. The
Streamlit UI in ``app/main.py`` is a thin layer over these functions and is not
unit-tested here.
"""

import csv
import io
import json

import pytest

import app_helpers as helpers
from stowage_optimizer.core import (
    Container,
    ContainerType,
    ProblemInstance,
    Route,
    Ship,
    StowageSolution,
    validate_instance,
)
from stowage_optimizer.core.examples import create_small_example_instance
from stowage_optimizer.core.metrics import evaluate_solution
from stowage_optimizer.solvers import (
    GeneticSolver,
    GreedySolver,
    MILPSolver,
    SolverResult,
    SolverStatus,
)

VALID_CSV = (
    "id,weight,destination_port,type\n"
    "C001,28.5,Panama,Normal\n"
    "C002,18.0,Brazil,Reefer\n"
    "C003,24,Spain,Flammable\n"
)


# -- CSV parsing -------------------------------------------------------------


def test_decode_csv_upload_accepts_utf8_bom() -> None:
    result = helpers.decode_csv_upload(
        "\ufeffid,weight,destination_port,type\nC1,10,Panama,Normal\n".encode(
            "utf-8"
        )
    )

    assert result.ok
    assert result.text is not None
    assert result.text.startswith("id,weight")


def test_decode_csv_upload_accepts_windows_1252() -> None:
    result = helpers.decode_csv_upload(
        "id,weight,destination_port,type\nC1,10,España,Normal\n".encode("cp1252")
    )

    assert result.ok
    assert result.text is not None
    assert "España" in result.text


def test_decode_csv_upload_reports_unknown_encoding() -> None:
    result = helpers.decode_csv_upload(b"\x81\x8d\x8f\x90\x9d")

    assert not result.ok
    assert result.text is None
    assert result.error is not None
    assert "Could not decode" in result.error


def test_parse_valid_csv_returns_containers() -> None:
    result = helpers.parse_containers_csv(VALID_CSV)

    assert result.ok
    assert result.errors == ()
    assert [c.id for c in result.containers] == ["C001", "C002", "C003"]
    assert result.containers[0].weight == 28.5
    assert result.containers[1].type == ContainerType.REEFER


def test_parse_csv_tolerates_header_case_whitespace_and_bom() -> None:
    text = "﻿ID , Weight , Destination_Port , Type\nC1,10,Panama,Normal\n"

    result = helpers.parse_containers_csv(text)

    assert result.ok
    assert result.containers[0].id == "C1"
    assert result.containers[0].destination_port == "Panama"


def test_parse_csv_reports_missing_columns() -> None:
    result = helpers.parse_containers_csv("id,weight,type\nC1,10,Normal\n")

    assert not result.ok
    assert result.containers == ()
    assert "destination_port" in result.errors[0]


def test_parse_csv_reports_non_numeric_weight_with_row_number() -> None:
    text = "id,weight,destination_port,type\nC1,heavy,Panama,Normal\n"

    result = helpers.parse_containers_csv(text)

    assert not result.ok
    assert any("Row 2" in error and "not a number" in error for error in result.errors)


def test_parse_csv_reports_non_finite_weights_with_row_number() -> None:
    text = (
        "id,weight,destination_port,type\n"
        "C1,nan,Panama,Normal\n"
        "C2,inf,Panama,Normal\n"
        "C3,-inf,Panama,Normal\n"
    )

    result = helpers.parse_containers_csv(text)

    assert not result.ok
    assert result.containers == ()
    assert len(result.errors) == 3
    assert all("must be finite" in error for error in result.errors)
    assert any("Row 2" in error for error in result.errors)


def test_parse_csv_reports_missing_required_cells() -> None:
    text = "id,weight,destination_port,type\n,10,Panama,Normal\nC2,,Brazil,Normal\n"

    result = helpers.parse_containers_csv(text)

    assert not result.ok
    assert any("Row 2" in error and "container id" in error for error in result.errors)
    assert any("Row 3" in error and "weight" in error for error in result.errors)


def test_parse_csv_skips_blank_trailing_lines() -> None:
    result = helpers.parse_containers_csv(VALID_CSV + "\n\n")

    assert result.ok
    assert len(result.containers) == 3


def test_parse_empty_csv_reports_error() -> None:
    assert not helpers.parse_containers_csv("").ok
    assert not helpers.parse_containers_csv("id,weight,destination_port,type\n").ok


# -- Reefer-slot parsing -----------------------------------------------------


def test_parse_reefer_slots_accepts_mixed_separators_and_parens() -> None:
    result = helpers.parse_reefer_slots("(1,1,1)\n2,2,1 ; (3, 1, 1)")

    assert result.ok
    assert result.positions == ((1, 1, 1), (2, 2, 1), (3, 1, 1))


def test_parse_reefer_slots_empty_is_valid_and_empty() -> None:
    result = helpers.parse_reefer_slots("   ")

    assert result.ok
    assert result.positions == ()


def test_parse_reefer_slots_reports_bad_triples() -> None:
    result = helpers.parse_reefer_slots("(1,1)\n(a,b,c)")

    assert not result.ok
    assert len(result.errors) == 2


def test_parse_reefer_slots_deduplicates() -> None:
    result = helpers.parse_reefer_slots("(1,1,1)\n(1,1,1)")

    assert result.positions == ((1, 1, 1),)


# -- Route parsing -----------------------------------------------------------


def test_parse_route_accepts_commas_and_newlines() -> None:
    result = helpers.parse_route_ports("Panama, Brazil\nSpain")

    assert result.ok
    assert result.ports == ("Panama", "Brazil", "Spain")


def test_parse_route_reports_empty() -> None:
    assert not helpers.parse_route_ports("   ").ok


def test_parse_route_reports_duplicates() -> None:
    result = helpers.parse_route_ports("Panama, Brazil, Panama")

    assert not result.ok
    assert any("Panama" in error for error in result.errors)


# -- Solver wiring -----------------------------------------------------------


def test_build_solver_returns_expected_types() -> None:
    params = helpers.SolverParams()

    assert isinstance(helpers.build_solver("Greedy", params), GreedySolver)
    assert isinstance(helpers.build_solver("MILP", params), MILPSolver)
    assert isinstance(helpers.build_solver("Genetic Algorithm", params), GeneticSolver)


def test_build_solver_rejects_unknown_algorithm() -> None:
    with pytest.raises(ValueError):
        helpers.build_solver("Simulated Annealing", helpers.SolverParams())


def test_built_greedy_solver_solves_example_instance() -> None:
    instance = create_small_example_instance()

    result = helpers.build_solver("Greedy", helpers.SolverParams()).solve(instance)

    assert result.status == SolverStatus.FEASIBLE
    assert result.is_feasible


def test_solver_params_propagate_to_genetic_solver() -> None:
    params = helpers.SolverParams(ga_population_size=12, ga_max_generations=5, ga_random_seed=7)

    solver = helpers.build_solver("Genetic Algorithm", params)

    # The GA stores its resolved configuration; confirm overrides took effect.
    assert solver._config.population_size == 12
    assert solver._config.max_generations == 5
    assert solver._config.random_seed == 7


def test_solver_params_propagate_to_local_search_config() -> None:
    params = helpers.SolverParams(
        greedy_local_search_enabled=True,
        ga_local_search_enabled=True,
        local_search_max_iterations=25,
        local_search_max_rounds_without_improvement=3,
        local_search_time_limit_seconds=1.5,
        cg_tolerance_lon=0.20,
        cg_tolerance_lat=0.30,
        min_incompatible_bay_distance=2,
    )

    config = helpers.local_search_config_from_params(params)
    greedy = helpers.build_solver("Greedy", params)
    genetic = helpers.build_solver("Genetic Algorithm", params)

    assert config.max_iterations == 25
    assert config.max_rounds_without_improvement == 3
    assert config.time_limit_seconds == 1.5
    assert config.cg_tolerance_lon == 0.20
    assert config.cg_tolerance_lat == 0.30
    assert config.min_incompatible_bay_distance == 2
    assert greedy._enable_local_search is True
    assert greedy._local_search_config.max_iterations == 25
    assert genetic._config.enable_local_search is True
    assert genetic._local_search_config.max_rounds_without_improvement == 3


def test_milp_size_guard_allows_small_ui_instances() -> None:
    instance = create_small_example_instance()

    assert helpers.milp_assignment_variable_upper_bound(instance) == 384
    assert helpers.milp_size_guard_message(instance) is None


def test_milp_size_guard_skips_oversized_ui_instances() -> None:
    instance = ProblemInstance(
        ship=Ship(bays=50, rows=50, tiers=50),
        containers=(Container("C1", 10.0, "Panama", "Normal"),),
        route=Route(("Panama",)),
    )

    message = helpers.milp_size_guard_message(instance)

    assert helpers.milp_assignment_variable_upper_bound(instance) == 125_000
    assert message is not None
    assert "MILP was skipped" in message
    assert "125,000" in message


def test_heuristic_advisory_is_silent_for_small_instances() -> None:
    instance = create_small_example_instance()

    assert helpers.heuristic_size_advisory_message(instance) is None


def test_heuristic_advisory_warns_for_oversized_grids_without_skipping() -> None:
    instance = ProblemInstance(
        ship=Ship(bays=50, rows=50, tiers=50),
        containers=(Container("C1", 10.0, "Panama", "Normal"),),
        route=Route(("Panama",)),
    )

    message = helpers.heuristic_size_advisory_message(instance)

    assert message is not None
    assert "125,000" in message
    assert "still execute" in message


# -- Table shaping -----------------------------------------------------------


def test_assignment_rows_carry_required_fields_sorted() -> None:
    instance = create_small_example_instance()
    result = helpers.build_solver("Greedy", helpers.SolverParams()).solve(instance)

    rows = helpers.assignment_rows(instance, result.solution)

    assert len(rows) == len(instance.containers)
    for row in rows:
        assert {"container_id", "bay", "row", "tier"} <= row.keys()
    positions = [(row["bay"], row["row"], row["tier"]) for row in rows]
    assert positions == sorted(positions)


def test_metrics_table_rows_use_labels() -> None:
    instance = create_small_example_instance()
    result = helpers.build_solver("Greedy", helpers.SolverParams()).solve(instance)

    rows = helpers.metrics_table_rows(result.metrics.as_dict())

    labels = [row["metric"] for row in rows]
    assert "Slot utilization" in labels
    assert "Total constraint violations" in labels
    assert "Structurally feasible" in labels
    assert "CG within tolerance" in labels
    assert labels.count("Operationally feasible") == 1
    assert len(rows) == len(result.metrics.as_dict()) - 1


def test_comparison_row_exposes_shared_metrics() -> None:
    instance = create_small_example_instance()
    result = helpers.build_solver("Greedy", helpers.SolverParams()).solve(instance)

    row = helpers.comparison_row("Greedy", result)

    assert row["algorithm"] == "Greedy"
    assert row["structural_feasible"] is True
    assert row["cg_ok"] is True
    assert row["operational_feasible"] is True
    assert "runtime_s" in row
    assert "real_rehandling" in row
    # Heuristic solvers expose no comparable objective value.
    assert row["objective"] is None


def test_comparison_row_distinguishes_cg_tolerance_failure() -> None:
    instance = create_small_example_instance()
    result = helpers.build_solver(
        "Greedy",
        helpers.SolverParams(cg_tolerance_lon=0.0, cg_tolerance_lat=0.0),
    ).solve(instance)

    row = helpers.comparison_row("Greedy", result)

    assert row["structural_feasible"] is True
    assert row["cg_ok"] is False
    assert row["operational_feasible"] is False


def test_local_search_summary_rows_report_disabled_and_enabled_runs() -> None:
    instance = ProblemInstance(
        ship=Ship(bays=3, rows=1, tiers=1),
        route=Route(("Panama",)),
        containers=(
            Container("H", 30.0, "Panama", ContainerType.NORMAL),
            Container("M", 29.0, "Panama", ContainerType.NORMAL),
            Container("L", 1.0, "Panama", ContainerType.NORMAL),
        ),
    )

    disabled = helpers.build_solver("Greedy", helpers.SolverParams()).solve(instance)
    enabled = helpers.build_solver(
        "Greedy",
        helpers.SolverParams(
            greedy_local_search_enabled=True,
            local_search_max_iterations=10,
        ),
    ).solve(instance)

    assert helpers.local_search_summary_rows(disabled) == [
        {"metric": "Local search", "value": "Disabled"}
    ]

    rows = helpers.local_search_summary_rows(enabled)
    labels = {row["metric"] for row in rows}
    assert "Evaluated swaps" in labels
    assert "Accepted swaps" in labels
    assert "abs(CG x) before" in labels
    assert "Real rehandling after" in labels
    assert all(isinstance(row["value"], str) for row in rows)
    assert enabled.local_search_result is not None


def test_result_status_message_explains_uncertified_milp_incumbent() -> None:
    instance = create_small_example_instance()
    result = helpers.build_solver("Greedy", helpers.SolverParams()).solve(instance)
    incumbent_result = type(result)(
        solution=result.solution,
        status=SolverStatus.FEASIBLE,
        runtime_seconds=result.runtime_seconds,
        metrics=result.metrics,
        objective_value=1.23,
        solver_status_detail="Solution Found (time limit incumbent; optimality not certified)",
    )

    level, message = helpers.result_status_message("MILP", incumbent_result)

    assert level == "warning"
    assert "feasible incumbent" in message
    assert "not proven optimal" in message


def test_result_status_message_keeps_regular_feasible_solution_success() -> None:
    instance = create_small_example_instance()
    result = helpers.build_solver("Greedy", helpers.SolverParams()).solve(instance)

    level, message = helpers.result_status_message("Greedy", result)

    assert level == "success"
    assert "Feasible solution" in message


def test_result_status_message_distinguishes_not_solved_without_incumbent() -> None:
    instance = create_small_example_instance()
    result = helpers.build_solver("MILP", helpers.SolverParams(milp_time_limit_seconds=0.0)).solve(
        instance
    )

    level, message = helpers.result_status_message("MILP", result)

    assert level == "warning"
    assert "no certified or feasible incumbent plan" in message


# -- Phase 11 scenario and result export/import ------------------------------


def test_scenario_export_json_contains_complete_payload() -> None:
    instance = create_small_example_instance()
    params = helpers.SolverParams(
        cg_lon=2.0,
        cg_lat=3.0,
        vertical=4.0,
        rehandling=5.0,
        cg_tolerance_lon=0.35,
        cg_tolerance_lat=0.45,
        min_incompatible_bay_distance=2,
        milp_time_limit_seconds=12.5,
        ga_population_size=24,
        ga_max_generations=30,
        ga_mutation_probability=0.10,
        ga_crossover_probability=0.70,
        ga_random_seed=99,
        greedy_local_search_enabled=True,
        ga_local_search_enabled=True,
        local_search_max_iterations=123,
        local_search_max_rounds_without_improvement=4,
        local_search_time_limit_seconds=2.5,
    )

    payload = json.loads(
        helpers.scenario_to_json(instance, params, ("Greedy", "Genetic Algorithm"))
    )

    assert payload["schema_version"] == helpers.SCENARIO_SCHEMA_VERSION
    assert payload["vessel"] == {"bays": 6, "rows": 4, "tiers": 4}
    assert payload["route"] == ["Panama", "Brazil", "Spain"]
    assert payload["containers"][0] == {
        "id": "C001",
        "weight": 28.5,
        "destination_port": "Panama",
        "type": "Normal",
    }
    assert payload["reefer"]["slots"][0] == {"bay": 1, "row": 1, "tier": 1}
    assert payload["cg_tolerances"] == {"longitudinal": 0.35, "lateral": 0.45}
    assert payload["objective_weights"] == {
        "cg_lon": 2.0,
        "cg_lat": 3.0,
        "vertical": 4.0,
        "rehandling": 5.0,
    }
    assert payload["solver_settings"]["selected_algorithms"] == [
        "Greedy",
        "Genetic Algorithm",
    ]
    assert payload["solver_settings"]["milp_time_limit_seconds"] == 12.5
    assert payload["solver_settings"]["ga_random_seed"] == 99
    assert payload["solver_settings"]["greedy_local_search_enabled"] is True
    assert payload["solver_settings"]["ga_local_search_enabled"] is True
    assert payload["solver_settings"]["local_search_max_iterations"] == 123
    assert payload["solver_settings"]["local_search_max_rounds_without_improvement"] == 4
    assert payload["solver_settings"]["local_search_time_limit_seconds"] == 2.5


def test_import_scenario_json_round_trip_reproduces_payload() -> None:
    instance = create_small_example_instance()
    params = helpers.SolverParams(
        cg_tolerance_lon=0.15,
        cg_tolerance_lat=0.20,
        milp_time_limit_seconds=None,
        ga_random_seed=None,
    )
    original = helpers.scenario_to_json(instance, params, ("Greedy", "MILP"))

    imported = helpers.import_scenario_json(original)

    assert imported.ok
    assert imported.instance is not None
    assert imported.params == params
    assert imported.algorithms == ("Greedy", "MILP")
    assert helpers.scenario_to_dict(
        imported.instance, imported.params, imported.algorithms
    ) == json.loads(original)


def test_import_scenario_json_accepts_missing_local_search_settings() -> None:
    instance = create_small_example_instance()
    payload = helpers.scenario_to_dict(instance, helpers.SolverParams(), ("Greedy",))
    settings = payload["solver_settings"]
    for key in (
        "greedy_local_search_enabled",
        "ga_local_search_enabled",
        "local_search_max_iterations",
        "local_search_max_rounds_without_improvement",
        "local_search_time_limit_seconds",
    ):
        settings.pop(key)

    imported = helpers.import_scenario_json(json.dumps(payload))

    assert imported.ok
    assert imported.params.greedy_local_search_enabled is False
    assert imported.params.ga_local_search_enabled is False
    assert imported.params.local_search_max_iterations == (
        helpers.DEFAULT_LOCAL_SEARCH_MAX_ITERATIONS
    )
    assert imported.params.local_search_max_rounds_without_improvement == (
        helpers.DEFAULT_LOCAL_SEARCH_MAX_ROUNDS_WITHOUT_IMPROVEMENT
    )
    assert imported.params.local_search_time_limit_seconds is None


def test_import_scenario_json_reports_invalid_domain_data() -> None:
    instance = create_small_example_instance()
    payload = helpers.scenario_to_dict(instance, helpers.SolverParams(), ("Greedy",))
    payload["containers"][0]["destination_port"] = "Atlantis"

    imported = helpers.import_scenario_json(json.dumps(payload))

    assert not imported.ok
    assert imported.instance is None
    assert any("not included in the route" in error for error in imported.errors)


def test_stowage_plan_csv_uses_stable_columns() -> None:
    instance = create_small_example_instance()
    result = helpers.build_solver("Greedy", helpers.SolverParams()).solve(instance)

    csv_text = helpers.stowage_plan_csv(instance, result.solution)
    reader = csv.DictReader(io.StringIO(csv_text))
    rows = list(reader)

    assert reader.fieldnames == list(helpers.PLAN_CSV_COLUMNS)
    assert len(rows) == len(instance.containers)
    assert rows[0]["container_id"]
    assert rows[0]["bay"]
    assert rows[0]["destination_port"] in instance.route.ports


def test_metrics_csv_uses_stable_columns_and_metric_keys() -> None:
    instance = create_small_example_instance()
    result = helpers.build_solver("Greedy", helpers.SolverParams()).solve(instance)

    csv_text = helpers.metrics_csv(result.metrics.as_dict())
    reader = csv.DictReader(io.StringIO(csv_text))
    rows = list(reader)
    metrics = {row["metric"]: row["value"] for row in rows}

    assert reader.fieldnames == list(helpers.METRICS_CSV_COLUMNS)
    assert "total_weight" in metrics
    assert "slot_utilization" in metrics
    assert "is_feasible" in metrics


def test_comparison_csv_uses_stable_columns() -> None:
    instance = create_small_example_instance()
    result = helpers.build_solver("Greedy", helpers.SolverParams()).solve(instance)
    row = helpers.comparison_row("Greedy", result)

    csv_text = helpers.comparison_csv([row])
    reader = csv.DictReader(io.StringIO(csv_text))
    rows = list(reader)

    assert reader.fieldnames == list(helpers.COMPARISON_CSV_COLUMNS)
    assert len(rows) == 1
    assert rows[0]["algorithm"] == "Greedy"
    assert rows[0]["status"] == "feasible"


def test_bundled_example_datasets_are_available_with_current_schema() -> None:
    datasets = helpers.example_dataset_catalog()

    assert tuple(dataset.size for dataset in datasets) == helpers.EXAMPLE_DATASET_SIZES
    for dataset in datasets:
        reader = csv.DictReader(io.StringIO(dataset.csv_text))
        rows = list(reader)
        parsed = helpers.parse_containers_csv(dataset.csv_text)

        assert dataset.file_name == f"containers_{dataset.size}.csv"
        assert dataset.description
        assert reader.fieldnames == list(helpers.REQUIRED_CONTAINER_COLUMNS)
        assert len(rows) == dataset.size
        assert parsed.ok
        assert len(parsed.containers) == dataset.size


def test_bundled_example_datasets_validate_with_default_scenario() -> None:
    ship = Ship(
        bays=6,
        rows=4,
        tiers=4,
        reefer_slots=((1, 1, 1), (1, 2, 1), (2, 1, 1), (2, 2, 1)),
    )
    route = Route(("Panama", "Brazil", "Spain"))

    for dataset in helpers.example_dataset_catalog():
        parsed = helpers.parse_containers_csv(dataset.csv_text)
        assert parsed.ok

        instance = ProblemInstance(
            ship=ship,
            containers=parsed.containers,
            route=route,
        )
        validation = validate_instance(instance)

        assert validation.is_valid, (
            f"{dataset.file_name} should validate with the default app scenario: "
            f"{[issue.message for issue in validation.errors]}"
        )


# -- Phase 12 visual diagnostics ---------------------------------------------


def _result_for(
    instance: ProblemInstance,
    solution: StowageSolution,
    params: helpers.SolverParams | None = None,
) -> SolverResult:
    """Wrap a hand-built solution in a feasible-status result for diagnostics."""
    params = params or helpers.SolverParams()
    metrics = evaluate_solution(
        instance,
        solution,
        cg_tolerance_lon=params.cg_tolerance_lon,
        cg_tolerance_lat=params.cg_tolerance_lat,
        min_incompatible_bay_distance=params.min_incompatible_bay_distance,
    )
    return SolverResult(
        solution=solution,
        status=SolverStatus.FEASIBLE,
        runtime_seconds=0.0,
        metrics=metrics,
    )


def _lateral_imbalance_case() -> tuple[ProblemInstance, StowageSolution]:
    """Return an instance whose only container sits on the far starboard row."""
    instance = ProblemInstance(
        ship=Ship(bays=1, rows=3, tiers=1),
        route=Route(("Panama",)),
        containers=(Container("A", 10.0, "Panama", "Normal"),),
    )
    solution = StowageSolution.from_mapping({"A": (1, 3, 1)})
    return instance, solution


def test_bay_row_balance_rows_cover_full_grid_with_totals() -> None:
    instance = create_small_example_instance()
    result = helpers.build_solver("Greedy", helpers.SolverParams()).solve(instance)

    rows = helpers.bay_row_balance_rows(instance, result.solution)

    assert len(rows) == instance.ship.bays * instance.ship.rows
    positions = [(row["bay"], row["row"]) for row in rows]
    assert positions == sorted(positions)
    assert sum(row["total_weight"] for row in rows) == pytest.approx(
        result.metrics.total_weight
    )
    assert sum(row["container_count"] for row in rows) == len(result.solution.assignments)


def test_bay_row_balance_rows_aggregate_per_stack() -> None:
    instance = ProblemInstance(
        ship=Ship(bays=2, rows=1, tiers=2),
        route=Route(("Panama",)),
        containers=(
            Container("A", 10.0, "Panama", "Normal"),
            Container("B", 5.0, "Panama", "Normal"),
        ),
    )
    solution = StowageSolution.from_mapping({"A": (1, 1, 1), "B": (1, 1, 2)})

    rows = {(row["bay"], row["row"]): row for row in helpers.bay_row_balance_rows(instance, solution)}

    assert rows[(1, 1)]["total_weight"] == 15.0
    assert rows[(1, 1)]["container_count"] == 2
    assert rows[(2, 1)]["total_weight"] == 0.0
    assert rows[(2, 1)]["container_count"] == 0


def test_bay_row_balance_rows_handle_empty_solution() -> None:
    instance = create_small_example_instance()

    rows = helpers.bay_row_balance_rows(instance, StowageSolution(()))

    assert len(rows) == instance.ship.bays * instance.ship.rows
    assert all(row["total_weight"] == 0.0 for row in rows)
    assert all(row["container_count"] == 0 for row in rows)


def test_bay_row_balance_rows_skip_unknown_containers() -> None:
    instance = ProblemInstance(
        ship=Ship(bays=1, rows=1, tiers=1),
        route=Route(("Panama",)),
        containers=(Container("KNOWN", 12.0, "Panama", "Normal"),),
    )
    solution = StowageSolution.from_mapping(
        {"KNOWN": (1, 1, 1), "UNKNOWN": (1, 1, 1)}
    )

    rows = helpers.bay_row_balance_rows(instance, solution)

    assert rows == [
        {"bay": 1, "row": 1, "total_weight": 12.0, "container_count": 1}
    ]


def test_cg_diagnostic_reports_within_tolerance() -> None:
    instance = create_small_example_instance()
    params = helpers.SolverParams()
    result = helpers.build_solver("Greedy", params).solve(instance)

    diagnostic = helpers.cg_diagnostic(result.metrics, params)

    assert diagnostic.ideal_x == 0.0
    assert diagnostic.ideal_y == 0.0
    assert diagnostic.tolerance_lon == params.cg_tolerance_lon
    assert diagnostic.tolerance_lat == params.cg_tolerance_lat
    assert diagnostic.within_tolerance == result.metrics.cg_within_tolerance
    assert diagnostic.lon_deviation == abs(result.metrics.cg_x)
    assert diagnostic.lat_deviation == abs(result.metrics.cg_y)


def test_cg_diagnostic_flags_out_of_tolerance() -> None:
    instance, solution = _lateral_imbalance_case()
    params = helpers.SolverParams()
    metrics = evaluate_solution(
        instance,
        solution,
        cg_tolerance_lon=params.cg_tolerance_lon,
        cg_tolerance_lat=params.cg_tolerance_lat,
    )

    diagnostic = helpers.cg_diagnostic(metrics, params)

    assert diagnostic.cg_y == pytest.approx(1.0)
    assert diagnostic.within_lat_tolerance is False
    assert diagnostic.within_tolerance is False
    assert diagnostic.lat_deviation == pytest.approx(1.0)


def test_violation_explanations_report_clean_solution() -> None:
    instance = create_small_example_instance()
    result = helpers.build_solver("Greedy", helpers.SolverParams()).solve(instance)

    explanations = helpers.violation_explanations(result)

    assert len(explanations) == 1
    assert explanations[0].code == "none"
    assert explanations[0].severity == "ok"


def test_violation_explanations_explain_cg_out_of_tolerance() -> None:
    instance, solution = _lateral_imbalance_case()
    result = _result_for(instance, solution)

    by_code = {item.code: item for item in helpers.violation_explanations(result)}

    assert "cg_lat" in by_code
    assert by_code["cg_lat"].severity == "warning"
    assert "starboard-heavy" in by_code["cg_lat"].message
    assert "cg_lon" not in by_code


def test_violation_explanations_explain_structural_violations() -> None:
    instance = ProblemInstance(
        ship=Ship(bays=3, rows=1, tiers=2),
        route=Route(("Panama",)),
        containers=(
            Container("R", 10.0, "Panama", "Reefer"),
            Container("F", 10.0, "Panama", "Flammable"),
            Container("O", 10.0, "Panama", "Oxidizer"),
            Container("MISSING", 10.0, "Panama", "Normal"),
        ),
    )
    solution = StowageSolution.from_mapping(
        {"R": (1, 1, 1), "F": (2, 1, 1), "O": (2, 1, 2)}
    )

    by_code = {item.code: item for item in helpers.violation_explanations(_result_for(instance, solution))}

    assert by_code["reefer"].severity == "error"
    assert by_code["reefer"].count == 1
    assert by_code["incompatible_cargo"].count == 1
    assert by_code["unassigned"].count == 1


def test_violation_explanations_explain_stack_continuity() -> None:
    instance = ProblemInstance(
        ship=Ship(bays=1, rows=1, tiers=2),
        route=Route(("Panama",)),
        containers=(Container("TOP", 10.0, "Panama", "Normal"),),
    )
    solution = StowageSolution.from_mapping({"TOP": (1, 1, 2)})

    by_code = {item.code: item for item in helpers.violation_explanations(_result_for(instance, solution))}

    assert "stack_continuity" in by_code
    assert by_code["stack_continuity"].count == 1


def test_violation_explanations_explain_duplicate_slot() -> None:
    instance = ProblemInstance(
        ship=Ship(bays=2, rows=1, tiers=1),
        route=Route(("Panama",)),
        containers=(
            Container("A", 10.0, "Panama", "Normal"),
            Container("B", 10.0, "Panama", "Normal"),
        ),
    )
    solution = StowageSolution.from_mapping({"A": (1, 1, 1), "B": (1, 1, 1)})

    by_code = {item.code: item for item in helpers.violation_explanations(_result_for(instance, solution))}

    assert "duplicate_slot" in by_code
    assert by_code["duplicate_slot"].count == 1


def test_algorithm_diagnostic_row_exposes_per_rule_counts() -> None:
    instance = create_small_example_instance()
    result = helpers.build_solver("Greedy", helpers.SolverParams()).solve(instance)

    row = helpers.algorithm_diagnostic_row("Greedy", result)

    assert row["algorithm"] == "Greedy"
    assert row["operational_feasible"] is True
    assert row["total_violations"] == 0
    for key in (
        "cg_x",
        "cg_y",
        "utilization",
        "real_rehandling",
        "unassigned",
        "reefer_violations",
        "stack_continuity_violations",
        "incompatible_cargo_violations",
        "duplicate_slots",
    ):
        assert key in row


def test_algorithm_diagnostic_rows_compare_feasible_and_imbalanced() -> None:
    instance = create_small_example_instance()
    feasible = helpers.build_solver("Greedy", helpers.SolverParams()).solve(instance)
    imbalance_instance, imbalance_solution = _lateral_imbalance_case()
    imbalanced = _result_for(imbalance_instance, imbalance_solution)

    rows = [
        helpers.algorithm_diagnostic_row("Greedy", feasible),
        helpers.algorithm_diagnostic_row("Imbalanced", imbalanced),
    ]

    assert [row["algorithm"] for row in rows] == ["Greedy", "Imbalanced"]
    assert rows[0]["cg_ok"] is True
    assert rows[1]["cg_ok"] is False
    assert rows[1]["cg_y"] == pytest.approx(1.0)
