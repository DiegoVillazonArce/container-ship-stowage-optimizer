# Future Notes / Backlog

Out-of-scope ideas captured during development. This file is a lightweight
scratch backlog; [ROADMAP.md](../ROADMAP.md) remains authoritative for
committed scope.

## Migrate to PuLP 4.x

PuLP 3.x deprecates direct `LpVariable(...)` construction (in favor of
`prob.add_variable(...)`) and the `PULP_CBC_CMD` backend (in favor of
`COIN_CMD` with `pip install pulp[cbc]`). The `pulp>=3,<4` pin in
`pyproject.toml` keeps the current API valid, and the matching
`filterwarnings` entries in `[tool.pytest.ini_options]` silence the migration
notices in test output. When adopting PuLP 4:

- update `src/stowage_optimizer/solvers/milp.py` to the new variable and
  backend APIs;
- remove the two PuLP filters from `pyproject.toml`;
- re-verify the certified-optimum vs. time-limit-incumbent status handling,
  since it depends on backend status reporting.

## Incremental local-search evaluation

`SwapLocalSearch` re-runs the full metrics evaluation — including the
port-by-port unloading simulation — for every candidate swap, making each
round O(n^2) full evaluations. This is fine at the current instance sizes and
default `max_iterations=500`, but a classic incremental evaluation (updating
only the two affected stacks and the running moments per swap) would be the
next step if larger instances or higher iteration limits are ever needed.

## Expose GA mutation shape in the UI

`GeneticConfig` now carries `swap_mutation_probability` and
`drop_mutation_probability` (previously hardcoded inside `_mutate`). They are
deliberately not exposed in the Streamlit sidebar to keep the GA settings
approachable; add them (and scenario JSON round-tripping) only if GA tuning
becomes a documented workflow.
