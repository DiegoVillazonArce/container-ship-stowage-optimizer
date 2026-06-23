# Benchmarking and Reproducibility

This document describes the Phase 8 benchmark scenarios and runner. The goal is
to compare Greedy, MILP, and Genetic Algorithm results with common final
metrics, not to claim that their internal objective values are equivalent.

## How to Run

Run the full test suite:

```bash
python -m pytest
```

Run a quick benchmark smoke table:

```bash
python -m stowage_optimizer.benchmarks.runner --quick
```

Run one scenario and write CSV:

```bash
python -m stowage_optimizer.benchmarks.runner --scenario small_base --format csv --output benchmark_results.csv
```

After installing the project, the console script is also available:

```bash
stowage-benchmark --quick
```

If you run directly from a source checkout before `pip install -e ".[dev]"`,
set `PYTHONPATH=src` for the `python -m` command.

Use repeated flags to filter:

```bash
python -m stowage_optimizer.benchmarks.runner --scenario reefer_focus --solver greedy --solver milp
```

## Scenarios

| Scenario | Purpose | Size |
| --- | --- | --- |
| `small_base` | Hand-checkable base instance with normal, reefer, flammable, and oxidizer cargo. | 4 containers, 96 slots |
| `reefer_focus` | Limited reefer-capable slots with multiple reefer containers. | 5 containers, 12 slots |
| `incompatible_cargo` | Strict Flammable/Oxidizer bay separation. | 4 containers, 8 slots |
| `multi_port_rehandling` | Three-port unloading sequence where real rehandling is meaningful. | 6 containers, 12 slots |
| `medium_scalability` | Moderate mixed scenario for manual scaling comparison. | 18 containers, 60 slots |

The first four scenarios are small enough for fast smoke tests. The medium
scenario is available for manual comparison, but timing claims should not be
used as brittle pytest assertions.

## Output Metrics

Benchmark records include:

- `runtime_seconds`
- solver `status`
- operational `feasible`
- `structural_feasible` (hard constraints satisfied, ignoring CG tolerance)
- `cg_within_tolerance` (horizontal CG inside the scenario tolerance)
- `utilization`
- `cg_x`, `cg_y`, and `cg_z_normalized`
- `real_rehandling`
- total structural `violations`
- `objective_value` and `gap` when a solver exposes them
- backend `detail`, such as CBC status or GA generation count

Interpretation notes:

- Compare algorithms through shared final metrics.
- Do not compare raw Greedy, MILP, and GA objective values as equivalent.
- CBC does not expose a MIP gap through PuLP's public API in this project, so
  `gap` is usually blank.
- Runtime depends on Python version, machine load, operating system, and CBC
  behavior.
- GA runs are reproducible when `ga_random_seed` or `--ga-seed` is fixed.

## Assumptions and Limitations

The benchmark results inherit the academic model limitations:

- Rectangular vessel grid.
- One-slot containers only.
- Normalized CG proxy, not full naval stability.
- Simplified Flammable/Oxidizer separation.
- Simplified real rehandling simulation.
- No crane scheduling.
- No structural stack-weight model.
- Not certified industrial stowage software.

## Future Optimization Opportunities

Safe model-preserving optimizations:

- Candidate-slot pruning for assignments impossible by hard constraints.
- MILP preprocessing for reefers, invalid slots, and fixed impossible pairs.
- Symmetry-breaking constraints that preserve the feasible region.
- Warm starts from Greedy or GA layouts where supported by the backend.
- Caching repeated metric and fitness computations in the GA.
- Faster stack-index data structures for rehandling simulation.

Higher-risk heuristic reductions:

- Search-space pruning based on cargo priority or destination groups.
- Limiting candidate bays for medium and large GA instances.
- Hybrid Greedy plus local search.
- Rolling-horizon or decomposition strategies for larger MILP experiments.

Safe optimizations should preserve the model's feasible region. Heuristic
reductions may improve runtime but can hide feasible or high-quality solutions,
so they should be documented and benchmarked separately.
