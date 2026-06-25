# Container Ship Stowage Optimizer

**Status:** Phases 1 through 9 completed. Phases 10 through 14 are planned roadmap extensions covering incumbent recovery, scenario/result export, visual diagnostics, local search, and an academic explanation layer. Core domain models, validation, a small example instance, the common metrics engine, the greedy baseline solver, the exact MILP reference solver, the genetic algorithm solver, the Streamlit interface, Plotly 3D visualization, port-by-port unloading simulation, reproducible benchmark scenarios, benchmark runner helpers, project quality tooling, CI, coverage reporting, deployment readiness, and final academic documentation are implemented. The core package, solvers, benchmark helpers, Streamlit-independent app helpers, and visualization helpers are unit-tested.

**Live app:** [container-ship-stowage-optimizer.streamlit.app](https://container-ship-stowage-optimizer.streamlit.app/)

## Current Repository State

This repository contains the project planning documentation plus the completed implementation increments. The current Python package includes vessel slots and normalized coordinates, container and route models, problem instances, pre-solver validation, a small hand-checkable example, a common metrics engine (weight, utilization, center-of-gravity moments, side and end balance, constraint-violation counts, and real rehandling by simulated unloading), a common solver interface, the greedy baseline solver with optional swap-based repair, the MILP exact reference solver (PuLP/CBC) enforcing the hard constraints and minimizing the linear objective, the genetic algorithm metaheuristic solver, the Streamlit interface with Plotly 3D visualization and unloading simulation, reproducible benchmark scenarios, benchmark table exporters, and automated tests.

The detailed implementation plan is maintained in [ROADMAP.md](./ROADMAP.md). The roadmap is the source of truth for phase boundaries. Technical model details are documented in [docs/DESIGN.md](./docs/DESIGN.md), and benchmark reproduction notes are documented in [docs/BENCHMARKS.md](./docs/BENCHMARKS.md).

## 1. Executive Summary

Container Ship Stowage Optimizer is a Python-based optimization project for generating feasible and operationally efficient container loading plans for simplified container ships.

The system takes a list of containers, a vessel slot configuration, and a route sequence, then assigns each container to a valid `(bay, row, tier)` position while respecting physical, operational, and cargo-specific constraints. The project is designed as an academic optimization system inspired by real maritime logistics, with emphasis on rigorous mathematical formulation, explainable modeling choices, and empirical comparison between exact and heuristic algorithms.

The goal is not to replicate industrial stowage planning software. Instead, the project builds a practical, defensible version of the problem that can be implemented, tested, visualized, and analyzed within a limited academic scope.

---

## 2. Scope and Modeling Philosophy

This is an academic project with an incremental delivery strategy. Each phase should produce a functional and demonstrable system before adding more complex constraints, algorithms, or interface features.

The guiding principle is:

> Build a correct optimization core for small instances first, then scale and refine, and only then expand the interface and visualization layer.

The model intentionally favors clarity, mathematical rigor, and implementability over full industrial realism. A simple model that converges, can be explained, and produces measurable results is preferred over an ambitious model that is difficult to solve or validate.

---

## 3. Core Optimization Problem

The optimization engine makes binary assignment decisions around the following statement:

> "Container C is assigned to vessel slot P, where P is defined by bay, row, and tier."

The main decision variable is:

```text
x[c, p] = 1 if container c is assigned to slot p
x[c, p] = 0 otherwise
```

Each slot represents a discrete position inside a simplified three-dimensional ship grid:

```text
Position = (Bay, Row, Tier)
```

- **Bay:** longitudinal position, from bow to stern.
- **Row:** lateral position, from port side to starboard side.
- **Tier:** vertical level in a container stack.

This discrete model supports combinatorial assignment constraints, while normalized physical coordinates support center-of-gravity and moment calculations.

### Physical Coordinate System

Each discrete slot is mapped to simplified physical coordinates:

- `x`: longitudinal coordinate relative to the vessel center.
- `y`: lateral coordinate relative to the centerline.
- `z`: vertical coordinate of the tier.

The recommended normalized ranges are:

```text
x, y in [-1, 1]
z    in [0, 1]
```

For the academic model, the ideal reference point is the geometric center of the vessel:

```text
x_ref = 0
y_ref = 0
```

This assumption is a simplification. Real vessels may have trim and stability references that depend on hull design and operating conditions, but a normalized geometric reference is appropriate for the intended scope.

---

## 4. System Objectives

The system aims to generate loading plans that:

- Assign every container to exactly one valid slot.
- Prevent more than one container from occupying the same slot.
- Avoid floating containers by enforcing valid stack continuity.
- Keep the horizontal center of gravity within configurable safety tolerances.
- Encourage heavier containers to remain in lower tiers.
- Assign refrigerated containers only to reefer-capable positions.
- Separate incompatible dangerous cargo classes using a simplified bay-distance rule.
- Reduce unnecessary unloading movements across multiple destination ports.
- Compare exact and heuristic optimization approaches using common final metrics.

---

## 5. Hard Constraints

Hard constraints define the feasibility boundary of the loading plan. A valid solution must satisfy all of them.

### 5.1 Unique Assignment

Every container must be placed exactly once:

```text
sum(x[c, p] for p in positions) = 1
```

### 5.2 Slot Capacity

Each vessel slot can contain at most one container:

```text
sum(x[c, p] for c in containers) <= 1
```

### 5.3 Stack Continuity

A container may only be placed in an upper tier if the slot directly below it is already occupied. This prevents physically impossible stack configurations such as a container floating above an empty slot.

### 5.4 Reefer Compatibility

Refrigerated containers can only be assigned to positions with electrical connection support.

### 5.5 Incompatible Cargo Separation

The model includes simplified dangerous cargo segregation between:

- `Flammable`
- `Oxidizer`

Instead of generating pairwise constraints for every incompatible container-position combination, the model uses aggregated bay-level binary variables to identify whether a bay contains each cargo type. Bays containing incompatible cargo must be separated by at least a configurable minimum distance.

This keeps the MILP formulation more scalable while preserving the core operational idea of incompatible cargo separation.

### 5.6 Horizontal Center of Gravity

The model controls horizontal stability through weight moments around the vessel's geometric center.

The lateral and longitudinal moments are constrained so that:

```text
-tau_lat <= CG_y <= tau_lat
-tau_lon <= CG_x <= tau_lon
```

where `tau_lat` and `tau_lon` are configurable tolerances.

This is more rigorous than simply comparing total weight on each side of the vessel, because it accounts for both weight and distance from the centerline.

### 5.7 Structural Stack Weight

An optional future structural constraint could limit the total weight supported above each container in a stack. This would provide a simplified approximation of stack strength and help avoid unrealistic loading patterns.

This optional constraint is not implemented in the current completed Phases 1-8 codebase; it remains a future extension rather than one of the implemented hard constraints.

---

## 6. Objective Function

The objective function optimizes quality inside the feasible region defined by the hard constraints.

The MILP objective combines:

- Longitudinal center-of-gravity deviation.
- Lateral center-of-gravity deviation.
- Vertical center-of-gravity penalty.
- Linear proxy for rehandling cost.

Conceptually:

```text
minimize
  alpha_lon * longitudinal_CG_deviation
+ alpha_lat * lateral_CG_deviation
+ lambda    * vertical_CG_penalty
+ delta     * rehandling_proxy
```

The coefficients allow experiments with different operational priorities.

### Vertical Stability Proxy

The project does not attempt to model full naval stability, metacentric height, hydrostatics, or hull-specific stability curves. Instead, it uses normalized vertical center of gravity as a soft penalty:

```text
VerticalPenalty = sum(container_weight * slot_z_coordinate)
```

This encourages heavy containers to be placed lower in the vessel without claiming to solve the complete naval architecture problem.

### Rehandling Cost

Rehandling occurs when a container that must be unloaded earlier is placed below a container that will be unloaded later. The MILP model uses a linear proxy that penalizes early-destination containers placed deep in stacks.

For heuristic algorithms, the system can evaluate actual rehandling by simulating the unloading sequence port by port.

The MILP proxy and the real rehandling count should be normalized separately because they are not the same unit of measurement. Therefore, algorithm comparison should rely on shared final dashboard metrics, not on raw internal objective values.

---

## 7. Algorithms

The project is designed to compare multiple optimization approaches over the same input instances.

| Algorithm | Role | Strength | Expected Scale |
| --- | --- | --- | --- |
| Greedy Heuristic | Baseline constructor | Very fast and easy to explain | Small to large |
| MILP | Exact optimization reference | High-quality solutions and optimality gap | Small instances |
| Genetic Algorithm | Metaheuristic search | Better scalability than MILP | Medium to large |

### Greedy Heuristic

The greedy solver provides a fast baseline. It can prioritize containers by weight, cargo restrictions, or destination port, then assign each container to the best currently feasible slot according to the scoring function.

A repair phase may be added to improve feasibility after the initial constructive pass.

### Mixed Integer Linear Programming

The MILP solver is intended as the quality reference for small problem instances. It provides a mathematically rigorous formulation and can return optimal or near-optimal solutions depending on solver limits.

Candidate libraries:

- OR-Tools
- PuLP
- Pyomo

### Genetic Algorithm

The genetic algorithm is implemented for larger instances where MILP becomes computationally expensive. Its main challenges are solution encoding, feasibility-preserving mutation and crossover, efficient evaluation, and repair mechanisms for invalid assignments.

---

## 8. Input Data

### Vessel Configuration

The vessel is represented by a configurable grid:

```text
Bays:  number of longitudinal positions
Rows:  number of lateral positions
Tiers: number of vertical stack levels
```

Certain positions or bays may be marked as reefer-capable.

### Container Dataset

Containers are expected to be loaded from CSV or Excel files.

| Field | Description | Example |
| --- | --- | --- |
| `id` | Unique container identifier | `C001` |
| `weight` | Container weight in tons | `28.5` |
| `destination_port` | Port where the container must be unloaded | `Panama` |
| `type` | Cargo category | `Normal`, `Reefer`, `Flammable`, `Oxidizer` |

### Container Types

- `Normal`: no additional cargo-specific restrictions.
- `Reefer`: must be assigned to a reefer-capable slot.
- `Flammable`: must be separated from oxidizer cargo.
- `Oxidizer`: must be separated from flammable cargo.

### Pre-Solve Validation

Before invoking an optimizer, the system should validate obvious infeasibilities:

- Duplicate container IDs.
- Missing or invalid weights.
- Unknown container types.
- Destination ports not included in the route.
- More containers than available vessel slots.
- More reefer containers than reefer-capable positions.
- Invalid vessel dimensions or empty route definitions.

These checks do not prove full feasibility, but they prevent unnecessary solver runs for clearly invalid instances.

---

## 9. Interface Architecture

The user interface is built with Streamlit to keep the project fully Python-based.

### Sidebar Inputs

- Vessel dimensions.
- Reefer bay or slot configuration.
- Container file upload.
- Port sequence.
- Algorithm selection.
- Horizontal CG tolerances.
- Objective function weights.
- Solver time limits and optional advanced settings.

### Main Output Area

- Operational KPIs.
- Final stowage plan table.
- 3D vessel visualization.
- Port-by-port unloading simulation.
- Algorithm comparison report.
- Feasibility and constraint violation diagnostics.

Plotly powers the 3D visualization layer.

### Streamlit Components

The interface is expected to use standard Streamlit controls:

| Need | Component |
| --- | --- |
| File upload | `st.file_uploader` |
| Vessel parameters | `st.number_input`, `st.slider` |
| Objective weights | `st.slider` |
| Optimization trigger | `st.button`, `st.spinner` |
| KPI reporting | `st.metric`, `st.columns` |
| Stowage table | `st.dataframe` |
| 3D visualization | `st.plotly_chart` |
| State persistence | `st.session_state` |

---

## 10. Output Metrics

The dashboard should report common metrics for all algorithms, including:

| Metric | Purpose |
| --- | --- |
| Total assigned containers | Confirms coverage |
| Slot utilization | Measures vessel space usage |
| Lateral CG | Validates port-side/starboard-side balance |
| Longitudinal CG | Validates bow-stern balance |
| Normalized vertical CG | Measures vertical loading quality |
| Port-side and starboard-side weight | Provides intuitive balance reporting |
| Bow and stern weight | Provides longitudinal distribution reporting |
| Rehandling count | Estimates unloading inefficiency |
| Solver runtime | Supports algorithm comparison |
| MILP optimality gap | Reports exact solver quality when available |
| Constraint violations | Especially useful for heuristic diagnostics |

Algorithm objective values should not be compared directly when algorithms optimize different internal proxies. Final comparison should be based on shared operational metrics.

---

## 11. Unloading Simulation

The application should support a port-by-port unloading simulation. For a selected destination port, the system should report:

- Containers removed.
- Extra rehandling movements required.
- Updated horizontal center of gravity.
- Updated port-side/starboard-side and bow-stern balance.
- Updated space utilization.
- Visual changes in the vessel layout.

This makes it possible to evaluate the operational quality of a stowage plan beyond the initial static assignment.

---

## 12. Infeasibility Handling

If the model cannot find a feasible complete assignment, the system should return clear diagnostics instead of a generic solver failure.

Possible causes include:

- Center-of-gravity tolerances are too strict.
- Reefer demand exceeds available reefer slots.
- Incompatible cargo separation leaves insufficient usable space.
- Stack weight restrictions are too tight.
- The vessel has insufficient total capacity.

Future versions may support partial assignment through high-penalty slack variables, but the main academic formulation treats complete assignment as a hard requirement.

---

## 13. Scalability Notes

The number of main binary decision variables grows as:

```text
number_of_containers * number_of_slots
```

For example:

```text
800 containers * 1,600 slots = 1,280,000 binary variables
```

This can become impractical for exact MILP optimization without decomposition or additional simplifications. The recommended implementation strategy is to validate the MILP on small instances first, such as:

```text
6 bays * 4 rows * 4 tiers = 96 slots
```

Larger scenarios should be handled with greedy construction, repair heuristics, genetic search, or other metaheuristic approaches.

---

## 14. Roadmap

The detailed phase plan is maintained in [ROADMAP.md](./ROADMAP.md).

Current roadmap status:

| Phase | Name | Status |
| --- | --- | --- |
| Phase 1 | Core Domain Model | Completed |
| Phase 2 | Metrics Engine | Completed |
| Phase 3 | Greedy Baseline Solver | Completed |
| Phase 4 | MILP Solver | Completed |
| Phase 5 | Genetic Algorithm | Completed |
| Phase 6 | Streamlit Interface | Completed |
| Phase 7 | 3D Visualization and Unloading Simulation | Completed |
| Phase 8 | Testing, Benchmarking, and Documentation | Completed |
| Phase 9 | Project Quality, Reproducibility & Deployment | Completed |
| Phase 10 | MILP Incumbent Recovery | Planned |
| Phase 11 | Scenario & Result Export/Import | Planned |
| Phase 12 | Visual Diagnostics | Planned |
| Phase 13 | Local Search after Greedy/GA | Planned |
| Phase 14 | Academic Explanation & Learning Mode | Planned |

The implemented benchmark layer compares algorithms through shared final metrics. Raw internal objective values are reported when available, but they should not be interpreted as equivalent across Greedy, MILP, and Genetic Algorithm runs.

---

## 15. Technology Stack

The stack is intentionally Python-centered:

| Technology | Role |
| --- | --- |
| Python | Core implementation language |
| Streamlit | Web application interface |
| PuLP / CBC | MILP optimization |
| NumPy / Pandas | Data handling and numerical calculations |
| Plotly | 3D visualization |
| pytest | Automated testing |

Optional persistence may be added through JSON, CSV, or SQLite. PostgreSQL is not required unless the project scope expands significantly.

The current MILP implementation targets PuLP 3.x. Migration to PuLP 4.x and
its updated CBC API is planned as future maintenance work.

---

## 16. Suggested Project Structure

```text
container-ship-stowage-optimizer/
|-- app/
|   `-- main.py                 # Streamlit entry point
|-- data/
|   `-- examples/               # Sample container datasets
|-- src/
|   `-- stowage_optimizer/
|       |-- core/
|       |   |-- ship.py         # Vessel grid and coordinates
|       |   |-- container.py    # Container model and loading logic
|       |   |-- validation.py   # Input and feasibility pre-checks
|       |   |-- solution.py     # Common stowage assignment contract
|       |   `-- metrics.py      # CG, balance, utilization, rehandling
|       |-- solvers/
|       |   |-- base.py         # Common solver interface
|       |   |-- greedy.py       # Greedy constructive heuristic
|       |   |-- milp.py         # MILP formulation
|       |   `-- genetic.py      # Genetic algorithm
|       `-- viz/
|           `-- plot3d.py       # Plotly visualization helpers
|-- tests/
|   `-- test_*.py
|-- pyproject.toml
|-- requirements.txt            # Runtime dependencies for Streamlit Cloud
|-- LICENSE
`-- README.md
```

The solver interface should allow algorithms to be swapped without changing the Streamlit layer:

```python
result = solver.solve(instance)
solution = result.solution
metrics = result.metrics
```

---

## 17. Testing Strategy

The test suite should cover the optimization model, data validation, metrics, and algorithm comparison.

### Feasibility Tests

Solutions produced by exact solvers must satisfy:

- Unique assignment.
- Slot capacity.
- Stack continuity.
- Reefer compatibility.
- Incompatible cargo separation.
- Horizontal CG limits.
- Structural stack weight limits, when enabled.

Heuristic solvers should explicitly report whether the final solution is feasible, repaired, or infeasible.

### Known Small Instances

Small hand-checkable cases should be used to validate the MILP formulation and ensure that each constraint behaves as expected.

### Metric Regression Tests

Metrics should be tested for consistency:

- Lateral CG.
- Longitudinal CG.
- Normalized vertical CG.
- Port-side/starboard-side balance.
- Bow-stern balance.
- Vertical penalty.
- Rehandling proxy.
- Real rehandling count.

### Input Validation Tests

Invalid data should fail with clear messages, including incomplete files, duplicate IDs, invalid weights, excessive reefer demand, and ports missing from the route.

---

## 18. Development Setup

The project uses a local Python virtual environment and installs dependencies from `pyproject.toml`.

The `.venv/` directory is intentionally ignored by Git. Each developer creates their own local environment after cloning the repository.

### Prerequisites

- Python 3.11+
- `pip`

### 1. Clone the repository

```bash
git clone https://github.com/DiegoVillazonArce/container-ship-stowage-optimizer.git
cd container-ship-stowage-optimizer
```

### 2. Create a virtual environment

```bash
python -m venv .venv
```

### 3. Activate the virtual environment

Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

Windows Command Prompt:

```cmd
.venv\Scripts\activate.bat
```

macOS / Linux:

```bash
source .venv/bin/activate
```

After activation, the terminal prompt usually displays `(.venv)`.

### 4. Install the project and development dependencies

Upgrade `pip` inside the virtual environment:

```bash
python -m pip install --upgrade pip
```

Install the package in editable mode with development tools:

```bash
pip install -e ".[dev]"
```

This installs:

- the local `stowage_optimizer` package in editable mode;
- development dependencies such as `pytest`, `pytest-cov`, and `ruff`.

Editable mode means source changes under `src/` are immediately reflected without reinstalling the package.

### 5. Run tests

```bash
python -m pytest
```

Windows PowerShell helper:

```powershell
.\run_tests.ps1
```

The helper runs the test suite with coverage reporting.
If PowerShell blocks local scripts on your machine, run:

```powershell
powershell -ExecutionPolicy Bypass -File .\run_tests.ps1
```

### 6. Run linting and coverage

Run Ruff:

```bash
python -m ruff check .
```

Run tests with terminal coverage:

```bash
python -m pytest --cov=stowage_optimizer --cov=app --cov-report=term-missing
```

GitHub Actions runs both Ruff and the coverage-enabled test suite on pushes,
pull requests, and manual workflow dispatches.

### 7. Run reproducible benchmarks

Quick smoke benchmark:

```bash
python -m stowage_optimizer.benchmarks.runner --quick
```

Write a CSV table for one scenario:

```bash
python -m stowage_optimizer.benchmarks.runner --scenario small_base --format csv --output benchmark_results.csv
```

After installing the project, the console script is also available:

```bash
stowage-benchmark --quick
```

Benchmark runtimes depend on the machine, Python version, operating system,
and CBC behavior. Use fixed GA seeds for reproducible assignments.
If you run from a source checkout before installing editable mode, set
`PYTHONPATH=src` for `python -m stowage_optimizer.benchmarks.runner`.

### 8. Deactivate the virtual environment

```bash
deactivate
```

### Notes for contributors

- Do not commit `.venv/`; it is a local machine-specific environment.
- If new runtime dependencies are added, declare them in `pyproject.toml`.
- If new development-only tools are added, declare them under `[project.optional-dependencies]` in the `dev` extra.
- Contributors may install dependencies globally, but using a virtual environment is recommended to avoid conflicts between projects.

### Streamlit app

```bash
streamlit run app/main.py
```

Windows PowerShell helper:

```powershell
.\run_app.ps1
```

If PowerShell blocks local scripts, run:

```powershell
powershell -ExecutionPolicy Bypass -File .\run_app.ps1
```

The interface lets you configure the vessel grid, reefer slots, route,
and objective weights, upload a container CSV (columns `id`, `weight`,
`destination_port`, `type`) or use the built-in example, run the Greedy, MILP,
and Genetic solvers, and inspect KPIs, the final stowage plan, a Plotly 3D
stowage view, port-by-port unloading simulation, and an algorithm comparison
table. Validation errors are reported before any solver runs.

The CSV `type` column accepts `Normal`, `Reefer`, `Flammable`, or `Oxidizer`.

### Streamlit Community Cloud deployment

The app is deployed at:

[https://container-ship-stowage-optimizer.streamlit.app/](https://container-ship-stowage-optimizer.streamlit.app/)

Deployment configuration:

- Repository: `DiegoVillazonArce/container-ship-stowage-optimizer`
- Branch: the branch you want to publish
- Main file path: `app/main.py`
- Python version: `3.11`
- Secrets: none required

`requirements.txt` mirrors the runtime dependencies from `pyproject.toml`
because Streamlit Community Cloud uses dependency files to build the hosted
environment. Development-only tools such as `pytest`, `pytest-cov`, and `ruff`
remain in the `dev` extra in `pyproject.toml`.

For hosted runs, prefer Greedy or Genetic Algorithm on medium examples. MILP is
kept available for small and moderate scenarios, but exact optimization can be
slow or skipped by the app's size guard when the container-slot assignment model
would be too large for an interactive cloud session.

---

## 19. Benchmarking and Reproducibility

Phase 8 adds shared benchmark scenarios in `stowage_optimizer.benchmarks`.
They are deterministic and can be reused by tests, scripts, notebooks, or the
CLI runner.

| Scenario | Purpose |
| --- | --- |
| `small_base` | Hand-checkable base case with normal, reefer, flammable, and oxidizer cargo. |
| `reefer_focus` | Limited reefer-capable slots with multiple reefer containers. |
| `incompatible_cargo` | Strict Flammable/Oxidizer bay separation. |
| `multi_port_rehandling` | Three-port route where real rehandling is meaningful. |
| `medium_scalability` | Moderate mixed case for manual runtime comparison. |

Benchmark tables report common final metrics:

- solver status and runtime;
- feasibility, utilization, and structural violations;
- `CG_x`, `CG_y`, and normalized `CG_z`;
- real rehandling count;
- objective value and gap only when the solver exposes them.

Raw objective values are not comparable across algorithms because Greedy, MILP,
and GA use different construction logic, proxies, and penalty structures. Use
the shared final metrics for interpretation.

Detailed benchmark instructions are in [docs/BENCHMARKS.md](./docs/BENCHMARKS.md).

---

## 20. Assumptions and Limitations

The project intentionally remains an academic model:

- the vessel is a simplified rectangular grid;
- each container occupies one slot;
- center of gravity is normalized and does not represent complete naval stability;
- Flammable/Oxidizer separation is a simplified bay-distance rule;
- rehandling is simulated with a simplified stack model;
- crane scheduling is not modeled;
- structural stack-weight limits are not implemented;
- the software is not certified industrial stowage planning software.

These limitations keep the model explainable, testable, and suitable for
comparing exact and heuristic approaches within a bounded academic scope.

---

## 21. Future Optimization Opportunities

Safe optimizations that preserve the current model:

- candidate-slot pruning for assignments made impossible by hard constraints;
- MILP preprocessing for reefers, invalid slot pairs, and fixed impossible cases;
- symmetry-breaking constraints that do not remove feasible unique solutions;
- warm starts from Greedy or GA plans when supported by the solver backend;
- caching repeated GA fitness and metrics computations;
- faster stack indexing for real rehandling simulation.

Near-term product, presentation, and reproducibility work is tracked in
ROADMAP phases 9-14, including hosted Streamlit deployment readiness, scenario
and result exports, downloadable example datasets, richer visual diagnostics,
local search post-processing, and an academic explanation tab.

Higher-risk heuristic reductions should be documented separately because they
can change the explored search space:

- pruning candidate bays by destination or cargo priority;
- limiting GA candidates for medium and large scenarios;
- hybrid solver workflows beyond the planned swap-based local search;
- decomposition or rolling-horizon methods for larger MILP experiments.

---

## 22. Academic Value

This project combines:

- Mathematical optimization.
- Mixed Integer Linear Programming.
- Operations research.
- Maritime logistics.
- Heuristic and metaheuristic algorithms.
- Simulation of unloading operations.
- 3D data visualization.
- Python application development.

Its main value is translating a real industrial logistics problem into an implementable academic model that remains rigorous, explainable, and suitable for experimental algorithm comparison.

---

## 23. CV Description

**Container Ship Stowage Optimization System**

Developed a Python-based optimization system for container ship stowage using MILP, greedy heuristics, and genetic algorithms. The system incorporates horizontal center-of-gravity constraints, stacking rules, reefer slot requirements, compact incompatible cargo separation, vertical center-of-gravity penalties, and multi-port unloading costs, with an interactive Streamlit dashboard, Plotly 3D stowage visualization, and port-by-port unloading simulation.

---

## 24. License

This project is licensed under the MIT License. See [LICENSE](./LICENSE) for details.
