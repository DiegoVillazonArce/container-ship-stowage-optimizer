"""Shared benchmark scenarios and lightweight benchmark smoke tests."""

import pytest

from stowage_optimizer.benchmarks import (
    BENCHMARK_SCENARIOS,
    BenchmarkConfig,
    get_benchmark_scenario,
    records_to_csv,
    records_to_markdown,
    run_benchmarks,
)
from stowage_optimizer.core import ContainerType, evaluate_solution, validate_instance


def test_phase8_benchmark_scenarios_are_registered() -> None:
    names = [scenario.name for scenario in BENCHMARK_SCENARIOS]

    assert names == [
        "small_base",
        "reefer_focus",
        "incompatible_cargo",
        "multi_port_rehandling",
        "medium_scalability",
    ]


def test_phase8_benchmark_scenarios_are_valid_inputs() -> None:
    for scenario in BENCHMARK_SCENARIOS:
        validation = validate_instance(scenario.instance)
        assert validation.is_valid, (
            f"{scenario.name} is not a valid benchmark input: {validation.errors}"
        )
        assert scenario.container_count <= scenario.slot_count


def test_reefer_benchmark_contains_reefer_pressure() -> None:
    scenario = get_benchmark_scenario("reefer_focus")

    reefer_count = sum(
        1 for container in scenario.instance.containers if container.type == ContainerType.REEFER
    )

    assert reefer_count >= 2
    assert scenario.instance.ship.reefer_slot_count >= reefer_count


def test_incompatible_benchmark_contains_strict_separation_rule() -> None:
    scenario = get_benchmark_scenario("incompatible_cargo")
    types = {container.type for container in scenario.instance.containers}

    assert ContainerType.FLAMMABLE in types
    assert ContainerType.OXIDIZER in types
    assert scenario.min_incompatible_bay_distance == 2


def test_multi_port_benchmark_reference_layout_has_real_rehandling() -> None:
    scenario = get_benchmark_scenario("multi_port_rehandling")
    assert scenario.reference_solution is not None

    metrics = evaluate_solution(
        scenario.instance,
        scenario.reference_solution,
        cg_tolerance_lon=scenario.cg_tolerance_lon,
        cg_tolerance_lat=scenario.cg_tolerance_lat,
        min_incompatible_bay_distance=scenario.min_incompatible_bay_distance,
    )

    assert metrics.real_rehandling > 0


@pytest.mark.parametrize(
    "scenario_name",
    ["small_base", "reefer_focus", "incompatible_cargo", "multi_port_rehandling"],
)
def test_small_benchmark_scenarios_are_solved_by_all_solvers(scenario_name: str) -> None:
    scenario = get_benchmark_scenario(scenario_name)

    records = run_benchmarks(
        (scenario,),
        config=BenchmarkConfig(ga_population_size=16, ga_max_generations=12, ga_random_seed=17),
    )

    assert len(records) == 3
    for record in records:
        assert record.feasible, (
            f"{record.solver} failed {scenario.name}: "
            f"status={record.status}, detail={record.detail}"
        )


def test_benchmark_runner_outputs_markdown_and_csv() -> None:
    scenario = get_benchmark_scenario("small_base")

    records = run_benchmarks(
        (scenario,),
        solver_names=("greedy", "milp", "genetic"),
        config=BenchmarkConfig(ga_population_size=8, ga_max_generations=4, ga_random_seed=7),
    )
    markdown = records_to_markdown(records)
    csv_text = records_to_csv(records)

    assert "| scenario | solver | status |" in markdown
    assert "small_base" in markdown
    assert "scenario,solver,status" in csv_text
    assert "Greedy" in csv_text
    assert "MILP" in csv_text
    assert "Genetic" in csv_text
    assert next(record for record in records if record.solver == "MILP").objective_value is not None
    assert next(record for record in records if record.solver == "Greedy").objective_value is None
