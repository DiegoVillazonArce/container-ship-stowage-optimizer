"""Tests for the Streamlit-free helpers in ``app/app_helpers.py``.

These cover the pure parsing, solver-wiring, and table-shaping logic only. The
Streamlit UI in ``app/main.py`` is a thin layer over these functions and is not
unit-tested here.
"""

import pytest

import app_helpers as helpers
from stowage_optimizer.core import Container, ContainerType, ProblemInstance, Route, Ship
from stowage_optimizer.core.examples import create_small_example_instance
from stowage_optimizer.solvers import GeneticSolver, GreedySolver, MILPSolver, SolverStatus

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
