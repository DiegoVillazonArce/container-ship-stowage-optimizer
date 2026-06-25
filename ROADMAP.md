# Container Ship Stowage Optimizer Roadmap

## Purpose

This roadmap defines a lightweight Scrum-style development plan for the **Container Ship Stowage Optimizer**. It is intended for an individual academic project, so it avoids heavy process overhead while still organizing the work into clear, testable increments.

The goal is to move from a small correct optimization core to comparable algorithms, then to an interactive Streamlit application with 3D visualization, unloading simulation, reproducible exports, public deployment readiness, richer diagnostics, and academic explanation.

## Development Philosophy

- Build the smallest correct domain model first.
- Validate all constraints on small, hand-checkable instances before scaling.
- Keep the mathematical model explainable and aligned with the academic scope.
- Compare algorithms using common final metrics, not raw internal objective values.
- Treat the MILP solver as an exact reference for small instances.
- Treat the Greedy solver as a fast baseline.
- Treat the Genetic Algorithm as a scalable search method for medium or large instances.
- Keep the interface simple until the optimization and metrics layers are reliable.

## Phase 1 — Core Domain Model

### Goal

Create the foundational Python data model for vessels, slots, containers, routes, and problem instances.

### User Stories

- As a developer, I want to represent vessel slots as `(bay, row, tier)`, so that all solvers can work with the same discrete grid.
- As a developer, I want to map each slot to normalized coordinates, so that center-of-gravity metrics can be computed consistently.
- As a developer, I want to validate container and vessel inputs early, so that invalid instances fail before reaching a solver.
- As a developer, I want to load small example datasets, so that the model can be tested with repeatable scenarios.

### Tasks

- [x] Create `Slot` model.
- [x] Create `Ship` model.
- [x] Create `Container` model.
- [x] Create `Route` or port sequence model.
- [x] Create `ProblemInstance` model.
- [x] Generate bay-row-tier grid.
- [x] Add normalized coordinates `x`, `y`, and `z`.
- [x] Add reefer-capable slot metadata.
- [x] Add container fields: `id`, `weight`, `destination_port`, and `type`.
- [x] Add supported container types: `Normal`, `Reefer`, `Flammable`, and `Oxidizer`.
- [x] Add input validation for duplicate IDs.
- [x] Add input validation for missing or invalid weights.
- [x] Add input validation for unknown container types.
- [x] Add input validation for destination ports missing from the route.
- [x] Add input validation for more containers than available slots.
- [x] Add input validation for more reefer containers than reefer-capable slots.
- [x] Create small sample instance, such as `6 x 4 x 4`.
- [x] Add unit tests.

### Definition of Done

- A small vessel grid can be generated programmatically.
- Each slot has discrete indices and normalized physical coordinates.
- Container data can be represented in memory.
- Invalid input data produces clear validation errors.
- The test suite covers the basic domain objects and validation rules.

## Phase 2 — Metrics Engine

### Goal

Implement common metrics that every solver can use for evaluation and comparison.

### User Stories

- As a developer, I want to compute horizontal center of gravity using weight moments, so that balance is measured more rigorously than simple side weights.
- As a developer, I want to compute normalized `CG_z`, so that vertical loading quality can be compared between solutions.
- As a developer, I want to compute real rehandling by simulation, so that heuristic solutions can be evaluated operationally.
- As a developer, I want to report common metrics for all algorithms, so that comparisons are fair and interpretable.

### Tasks

- [x] Create `metrics.py`.
- [x] Implement total weight calculation.
- [x] Implement slot utilization calculation.
- [x] Implement lateral moment calculation.
- [x] Implement longitudinal moment calculation.
- [x] Implement `CG_y`.
- [x] Implement `CG_x`.
- [x] Implement normalized `CG_z`.
- [x] Implement port-side and starboard-side weight reporting.
- [x] Implement bow and stern weight reporting.
- [x] Implement horizontal CG tolerance checks.
- [x] Implement reefer violation checks.
- [x] Implement stack continuity violation checks.
- [x] Implement incompatible cargo violation checks.
- [x] Implement real rehandling simulation by route order.
- [x] Implement final metrics object or dictionary.
- [x] Add unit tests for hand-checkable layouts.

### Definition of Done

- A complete assignment can be evaluated without calling any solver.
- Metrics are deterministic and covered by unit tests.
- Horizontal CG is computed from moments.
- Port-side/starboard-side and bow/stern balances are reported as visual metrics, not treated as the primary mathematical balance constraint.
- Real rehandling can be computed through unloading simulation.

## Phase 3 — Greedy Baseline Solver

### Goal

Create a fast constructive solver that produces an initial baseline solution and supports later comparison.

### User Stories

- As a developer, I want to assign containers greedily to feasible slots, so that the project has an early working solver.
- As a developer, I want to prioritize constrained containers, so that reefers and dangerous cargo are less likely to become impossible to place.
- As a developer, I want the greedy solver to report violations clearly, so that infeasible heuristic outputs can still be analyzed.
- As a developer, I want a repair step, so that simple greedy mistakes can be corrected when possible.

### Tasks

- [x] Create common solver interface.
- [x] Create `GreedySolver`.
- [x] Sort containers by weight and constraint priority.
- [x] Generate candidate slots for each container.
- [x] Enforce slot capacity during construction.
- [x] Enforce stack continuity during construction.
- [x] Enforce reefer compatibility during construction.
- [x] Add scoring for horizontal CG impact.
- [x] Add scoring for vertical placement.
- [x] Add scoring for rehandling risk.
- [x] Add simplified incompatible cargo checks.
- [x] Add optional swap-based repair.
- [x] Return solution status: feasible, repaired, or infeasible.
- [x] Report runtime.
- [x] Add unit tests with small instances.

### Definition of Done

- The greedy solver can solve simple valid instances.
- The solver returns a complete assignment when feasible.
- Violations are counted and reported when the solution is not feasible.
- Runtime and final metrics are available through the common evaluation layer.

## Phase 4 — MILP Solver

### Goal

Implement the exact optimization reference for small instances using a Mixed Integer Linear Programming formulation.

### User Stories

- As a developer, I want to define binary assignment variables, so that each container-slot decision is explicit.
- As a developer, I want to enforce hard constraints in the MILP model, so that feasible MILP solutions are mathematically valid.
- As a developer, I want to use a linear rehandling proxy, so that multi-port unloading effects can be included without making the model too large.
- As a developer, I want to retrieve solver status and optimality gap, so that MILP results can be interpreted correctly.

### Tasks

- [x] Choose MILP library, such as OR-Tools, PuLP, or Pyomo.
- [x] Create `MILPSolver`.
- [x] Define binary variables `x[c, p]`.
- [x] Add unique assignment constraints.
- [x] Add slot capacity constraints.
- [x] Add stack continuity constraints.
- [x] Add reefer compatibility constraints.
- [x] Add bay-level binary variables for flammable cargo.
- [x] Add bay-level binary variables for oxidizer cargo.
- [x] Add minimum bay-distance separation constraints.
- [x] Add horizontal CG moment constraints.
- [x] Add auxiliary variables for absolute lateral CG deviation.
- [x] Add auxiliary variables for absolute longitudinal CG deviation.
- [x] Add normalized vertical CG penalty.
- [x] Add linear rehandling proxy.
- [x] Add objective weights.
- [x] Add solver time limit configuration.
- [x] Return status, objective value, runtime, and gap when available.
- [x] Add tests for infeasible and feasible small instances.

### Definition of Done

- The MILP solver works on small instances, such as `6 x 4 x 4`.
- Hard constraints are enforced by the model.
- Horizontal CG is controlled through weight moments.
- The MILP can report infeasibility clearly.
- The solver output can be evaluated with the same metrics engine used by other algorithms.

## Phase 5 — Genetic Algorithm

### Goal

Create a metaheuristic solver for larger instances where MILP may become too expensive.

### User Stories

- As a developer, I want to encode a stowage plan as a chromosome, so that candidate solutions can be evolved.
- As a developer, I want crossover and mutation operators, so that the search can explore alternative assignments.
- As a developer, I want repair mechanisms, so that invalid individuals can be improved instead of discarded immediately.
- As a developer, I want the fitness function to use common metrics, so that GA results are comparable with Greedy and MILP outputs.

### Tasks

- [x] Create `GeneticSolver`.
- [x] Define chromosome representation.
- [x] Generate initial population.
- [x] Add feasibility-aware initialization when possible.
- [x] Implement fitness evaluation.
- [x] Include horizontal CG deviation in fitness.
- [x] Include normalized `CG_z` in fitness.
- [x] Include real rehandling simulation in fitness.
- [x] Include penalty for constraint violations.
- [x] Implement selection.
- [x] Implement crossover.
- [x] Implement mutation.
- [x] Implement repair for duplicate slots and missing containers.
- [x] Implement stopping criteria.
- [x] Report best solution, runtime, and generation count.
- [x] Add reproducible random seed configuration.
- [x] Add tests for encoding, decoding, and repair logic.

### Definition of Done

- The GA can produce valid or clearly diagnosed solutions on small and medium instances.
- The fitness function uses the same final metrics as the rest of the system.
- Constraint violations are penalized and reported.
- Results are reproducible when a random seed is provided.

## Phase 6 — Streamlit Interface

### Goal

Build a simple interactive interface for configuring scenarios, running solvers, and viewing results.

### User Stories

- As a developer, I want users to configure vessel dimensions, so that scenarios can be created without editing code.
- As a developer, I want users to upload container data, so that external datasets can be tested.
- As a developer, I want users to select an algorithm, so that Greedy, MILP, and GA can be compared from one interface.
- As a developer, I want results to appear as tables and metrics, so that solution quality is easy to inspect.

### Tasks

- [x] Create `app/main.py`.
- [x] Add Streamlit sidebar.
- [x] Add vessel dimension inputs.
- [x] Add reefer slot or reefer bay configuration.
- [x] Add CSV upload.
- [x] Add route sequence input.
- [x] Add algorithm selector.
- [x] Add CG tolerance controls.
- [x] Add objective weight controls.
- [x] Add solver time limit controls.
- [x] Add run optimization button.
- [x] Display validation errors.
- [x] Display solution status.
- [x] Display common KPI metrics.
- [x] Display final stowage plan table.
- [x] Display algorithm comparison table.
- [x] Add session state for latest scenario and solution.

### Definition of Done

- A user can configure a small instance from the Streamlit interface.
- A user can run at least one solver from the interface.
- Validation errors are visible and understandable.
- Final metrics and stowage table are displayed after solving.

## Phase 7 — 3D Visualization and Unloading Simulation

### Goal

Add Plotly-based 3D visualization and port-by-port unloading analysis.

### User Stories

- As a developer, I want to visualize the vessel in 3D, so that the stowage plan can be inspected spatially.
- As a developer, I want containers colored by destination port or cargo type, so that patterns are easier to understand.
- As a developer, I want to simulate unloading by port, so that real rehandling can be explained and measured.
- As a developer, I want metrics to update during unloading simulation, so that operational effects are visible.

### Tasks

- [x] Create `viz/plot3d.py`.
- [x] Generate Plotly 3D container blocks or markers.
- [x] Color containers by destination port.
- [x] Add hover details for container ID, weight, port, type, and slot.
- [x] Add visual distinction for reefer containers.
- [x] Add visual distinction for dangerous cargo classes.
- [x] Add selected-port unloading simulation.
- [x] Identify containers removed at each port.
- [x] Identify temporary rehandling moves.
- [x] Recompute metrics after simulated unloading.
- [x] Display updated utilization.
- [x] Display updated CG metrics.
- [x] Add tests for unloading sequence logic.

### Definition of Done

- A solved stowage plan can be displayed in 3D.
- Users can inspect container metadata from the visualization.
- Port-by-port unloading produces rehandling counts.
- Metrics can be recalculated after simulated unloading steps.

## Phase 8 — Testing, Benchmarking, and Documentation

### Goal

Finalize the academic project by strengthening tests, creating benchmark scenarios,
documenting design decisions, and identifying evidence-based optimization
opportunities without changing the solver formulations in this phase.

**Status:** Completed. Shared benchmark scenarios and a benchmark runner now live
under `stowage_optimizer.benchmarks`; final documentation is linked from the
README, DESIGN document, and benchmark guide.

### User Stories

- As a developer, I want known small test cases, so that solver correctness can be checked manually.
- As a developer, I want benchmark instances, so that algorithm behavior can be compared empirically.
- As a developer, I want documented limitations, so that the project scope is clear and academically honest.
- As a developer, I want reproducible result tables, so that the final analysis can be defended.
- As a developer, I want a benchmark-driven scalability review, so that future optimization work targets real bottlenecks instead of guesses.

### Tasks

- [x] Add unit tests for domain models.
- [x] Add unit tests for validation.
- [x] Add unit tests for metrics.
- [x] Add unit tests for solver interfaces.
- [x] Add integration tests for small scenarios.
- [x] Create benchmark datasets.
- [x] Benchmark Greedy, MILP, and GA on shared instances.
- [x] Record runtime, feasibility, CG metrics, `CG_z`, rehandling, utilization, and violations.
- [x] Analyze benchmark results to identify solver and model bottlenecks.
- [x] Document safe optimization opportunities, such as valid candidate-slot pruning or repeated-computation caching.
- [x] Document higher-risk heuristic optimization opportunities separately from safe model-preserving changes.
- [x] Document solver assumptions.
- [x] Document known limitations.
- [x] Update README links to design, roadmap, and benchmark documents.
- [x] Add reproducibility notes.

Optional README screenshots remain a future presentation enhancement rather than
a Phase 8 correctness requirement; Streamlit is covered through its pure helper
tests instead of visual UI assertions.

### Definition of Done

- Core behavior is covered by automated tests.
- Benchmark scenarios can be rerun.
- Algorithm comparison uses common final metrics.
- Documentation explains the mathematical model, implementation plan, assumptions, limitations, and future optimization opportunities.

## Phase 9 — Project Quality, Reproducibility & Deployment

### Goal

Add project quality tooling, repeatable local entry points, and deployment readiness so tests, linting, coverage, and the Streamlit app can be run consistently in local development, continuous integration, and a public hosted environment.

**Status:** Completed. Ruff, coverage reporting, PowerShell helper scripts, GitHub Actions CI, Streamlit Community Cloud deployment readiness, operational deployment notes, and the public hosted app URL are implemented and documented.

### User Stories

- As a developer, I want Ruff linting, so that style and simple correctness issues are caught before review.
- As a developer, I want GitHub Actions to run tests and linting, so that regressions are detected automatically.
- As a developer, I want test coverage reporting, so that weakly tested areas are visible.
- As a developer, I want PowerShell startup scripts, so that the app and tests can be launched consistently on Windows.
- As a developer, I want the Streamlit app prepared for hosted deployment, so that the project can be shared through a public link.

### Tasks

- [x] Add Ruff linting configuration.
- [x] Add a GitHub Actions workflow that runs `pytest`.
- [x] Add a GitHub Actions workflow step that runs `ruff`.
- [x] Add test coverage reporting.
- [x] Add `run_app.ps1` for launching the Streamlit app.
- [x] Add `run_tests.ps1` for running the test suite.
- [x] Verify Streamlit Community Cloud deployment prerequisites, including app entry point, declared dependencies, and repository file layout.
- [x] Add deployment notes for publishing the Streamlit app.
- [x] Document operational limits for hosted runs, especially MILP size and time-limit behavior.
- [x] Publish the Streamlit app and add the public app URL to the README.

### Definition of Done

- Ruff can be run locally and in continuous integration.
- GitHub Actions runs tests and linting for the project.
- Test coverage can be generated and reviewed.
- PowerShell scripts provide repeatable app and test entry points.
- The repository is ready for Streamlit Community Cloud deployment and documents the deployment process.
- The public Streamlit app URL is documented after deployment.

## Phase 10 — MILP Incumbent Recovery

### Goal

Recover feasible MILP incumbent solutions when CBC reaches the time limit before proving optimality, so that useful assignments are reported instead of being replaced by an empty solution.

### User Stories

- As a developer, I want the MILP solver to keep feasible incumbents found under a time limit, so that large runs can still return usable plans.
- As a developer, I want non-optimal incumbents to be reported as `FEASIBLE`, so that solver status remains academically honest.
- As a developer, I want recovered incumbents to include `objective_value`, so that comparisons remain meaningful.
- As a developer, I want tests around low time limits and partially certified variables, so that the recovery path is reliable.

### Tasks

- [ ] Update the MILP solve flow to extract incumbent assignments when CBC reports an integer-feasible solution.
- [ ] Use the existing `_classify_backend_status` distinction between `LpSolutionIntegerFeasible` and `LpSolutionOptimal`.
- [ ] Report recovered incumbents with status `FEASIBLE`, not `OPTIMAL`.
- [ ] Populate `objective_value` for recovered feasible incumbents.
- [ ] Avoid returning an empty assignment when variable values define a feasible incumbent.
- [ ] Make solution extraction tolerate variables without certified values.
- [ ] Add a regression test for CBC's integer-feasible, non-certified incumbent path.
- [ ] Verify that the recovered time-limited solution is non-empty and feasible when an incumbent exists.
- [ ] Verify that variables without certified values do not break solution extraction.

### Definition of Done

- The MILP solver can return a feasible incumbent when CBC stops at the time limit.
- Time-limited feasible incumbents are marked `FEASIBLE`.
- Optimal solutions remain marked `OPTIMAL`.
- Recovered incumbents include an objective value when the backend provides one.
- Tests cover incumbent recovery and uncertified variable extraction behavior.

## Phase 11 — Scenario & Result Export/Import

### Goal

Add Streamlit export and import features for complete scenarios and downloadable result tables, making app experiments reproducible outside the interactive session.

### User Stories

- As a developer, I want to export a complete scenario as JSON, so that a configured instance can be reproduced later.
- As a developer, I want to import a scenario JSON file, so that saved experiments can be rerun without manual setup.
- As a developer, I want to download the final stowage plan as CSV, so that results can be inspected in external tools.
- As a developer, I want to download metrics and algorithm comparisons as CSV, so that benchmark evidence can be shared and archived.
- As a developer, I want downloadable example datasets, so that larger test scenarios can be tried without leaving the app.

### Tasks

- [ ] Define a JSON representation for the complete Streamlit scenario.
- [ ] Include vessel dimensions, route, containers, reefer configuration, objective weights, tolerances, and solver settings in the scenario export.
- [ ] Add a scenario JSON download control.
- [ ] Add a scenario JSON upload and import path.
- [ ] Validate imported scenarios before creating a `ProblemInstance`.
- [ ] Add round-trip tests for scenario export and import.
- [ ] Add CSV download for the final stowage plan.
- [ ] Add CSV download for final metrics.
- [ ] Add CSV download for the algorithm comparison table.
- [ ] Add downloadable example container CSVs for 20, 40, 60, and 80 containers.
- [ ] Add short descriptions for the bundled example datasets in the Streamlit UI.
- [ ] Use stable column names for exported result tables.

### Definition of Done

- A Streamlit scenario can be exported to JSON and imported back into the app.
- Scenario round-trips reproduce the same problem instance.
- The final stowage plan can be downloaded as CSV.
- Final metrics can be downloaded as CSV.
- Algorithm comparison results can be downloaded as CSV.
- Bundled example datasets can be downloaded from the Streamlit interface.

## Phase 12 — Visual Diagnostics

### Goal

Enrich the Streamlit diagnostics layer with structured visual explanations of balance, center of gravity, constraint violations, and algorithm differences.

### User Stories

- As a developer, I want a bay-row balance map, so that weight distribution issues are visible at a glance.
- As a developer, I want the center of gravity marked visually, so that balance quality is easier to interpret.
- As a developer, I want readable violation explanations, so that infeasible or repaired solutions can be understood.
- As a developer, I want side-by-side algorithm diagnostics, so that solver tradeoffs are easier to compare.

### Tasks

- [ ] Build a bay-row balance map from structured result data.
- [ ] Mark the computed center of gravity in the visual diagnostics.
- [ ] Add readable explanations for reefer, stack continuity, incompatible cargo, and CG violations.
- [ ] Link violation explanations to affected containers, slots, or aggregate metrics when available.
- [ ] Add side-by-side comparison between algorithm results.
- [ ] Reuse the structured scenario and result data from Phase 11.
- [ ] Add tests for diagnostic data preparation helpers.

### Definition of Done

- Streamlit can display a bay-row balance diagnostic.
- The computed center of gravity is visible in the diagnostics.
- Constraint violations are explained in readable terms.
- Algorithm outputs can be compared side by side.
- Diagnostic data preparation is covered by automated tests.

## Phase 13 — Local Search after Greedy/GA

### Goal

Add a hard-constraint-preserving local search step after Greedy or GA, using container swaps to improve horizontal CG and rehandling without changing the core solver formulations.

### User Stories

- As a developer, I want swap-based local search after Greedy or GA, so that constructive and evolutionary solutions can be improved.
- As a developer, I want local search to rebalance horizontal CG even when structural constraints are already feasible, so that the documented Greedy limitation is addressed.
- As a developer, I want every accepted move to preserve hard constraints, so that post-processing cannot invalidate a solution.
- As a developer, I want clear acceptance and stopping criteria, so that local search behavior is reproducible.

### Tasks

- [ ] Review the documented Greedy limitation around repair not rebalancing solutions that only fail horizontal CG.
- [ ] Define a swap neighborhood for assigned containers.
- [ ] Add hard-constraint checks for candidate swaps.
- [ ] Score candidate swaps using horizontal CG deviation and rehandling impact.
- [ ] Define an acceptance criterion for improving or controlled non-worsening swaps.
- [ ] Define stopping criteria based on iterations, lack of improvement, and optional runtime.
- [ ] Integrate local search as optional post-processing after Greedy.
- [ ] Integrate local search as optional post-processing after GA.
- [ ] Report local-search runtime, iteration count, and improvement metrics.
- [ ] Add tests showing that local search preserves hard constraints.
- [ ] Add tests showing that local search can improve CG or rehandling on hand-checkable instances.

### Definition of Done

- Greedy and GA can optionally run a local search post-processing step.
- Accepted swaps preserve hard constraints.
- Local search uses clear acceptance and stopping criteria.
- Improvement in CG or rehandling is reported when it occurs.
- Tests cover constraint preservation and measurable improvement cases.

## Phase 14 — Academic Explanation & Learning Mode

### Goal

Add a dedicated Streamlit learning layer that explains the stowage problem, the optimization model, the implemented algorithms, and the academic assumptions from simple concepts through more technical details.

### User Stories

- As a developer, I want the app to explain the container stowage problem in plain language, so that non-specialist users can understand what the project solves.
- As a developer, I want the app to explain constraints, objectives, and metrics, so that the optimization results are interpretable.
- As a developer, I want Greedy, MILP, and Genetic Algorithm behavior described at different levels of detail, so that users can connect solver outputs to the underlying methods.
- As a developer, I want assumptions and limitations presented clearly, so that the academic scope is honest and defensible.

### Tasks

- [ ] Add a dedicated Streamlit tab or page for project explanation.
- [ ] Explain the stowage problem from simple terminology to the formal optimization view.
- [ ] Describe vessel slots, containers, route order, and unloading pressure with small examples.
- [ ] Explain hard constraints, objective terms, and final metrics using readable text and compact formulas.
- [ ] Explain Greedy, MILP, and Genetic Algorithm approaches and when each is useful.
- [ ] Include academic assumptions, simplifications, and limitations.
- [ ] Add diagrams, tables, or small visual examples where they make the explanation easier to follow.
- [ ] Keep explanatory content separate from solver logic so it can be tested and maintained independently.
- [ ] Add tests for any structured content helpers used by the learning layer.

### Definition of Done

- The Streamlit app includes a dedicated explanation tab or page.
- Users can understand the problem, constraints, objective terms, algorithms, metrics, assumptions, and limitations without reading the source code.
- The explanation supports both plain-language and more technical reading paths.
- Academic assumptions are presented clearly and consistently with README and DESIGN documentation.
- Any reusable explanation helpers are covered by automated tests.

## Suggested GitHub Issues

- Create core `Slot`, `Ship`, and `Container` models.
- Generate normalized vessel coordinates.
- Implement CSV container loader.
- Add pre-solve validation checks.
- Implement common solution object.
- Implement metrics engine.
- Implement real rehandling simulation.
- Implement Greedy baseline solver.
- Add Greedy repair phase.
- Implement MILP assignment variables and hard constraints.
- Add bay-level incompatible cargo separation to MILP.
- Add horizontal CG moment constraints to MILP.
- Add vertical `CG_z` penalty.
- Add MILP rehandling proxy.
- Implement Genetic Algorithm encoding and decoding.
- Add GA mutation, crossover, and repair.
- Build Streamlit sidebar inputs.
- Add solver selection in Streamlit.
- Add KPI dashboard.
- Add Plotly 3D vessel visualization.
- Add unloading simulation view.
- Create small benchmark instances.
- Add solver comparison report.
- Write scalability and optimization-opportunity notes.
- Write final academic limitations section.

## Definition of Done for MVP

The MVP is complete when:

- A small vessel instance can be created, preferably starting with `6 x 4 x 4`.
- Containers can be loaded from a structured dataset.
- Input validation catches common invalid cases.
- At least one solver can produce a complete stowage plan.
- The solution enforces unique assignment, slot capacity, stack continuity, and reefer compatibility.
- Horizontal CG is computed using weight moments.
- Normalized `CG_z` is reported.
- Utilization and rehandling metrics are reported.
- The output can be inspected in a table.
- Automated tests cover the main domain model and metrics behavior.

## Future Enhancements

- Add partial assignment with high-penalty unassigned variables.
- Add configurable vessel templates.
- Add richer dangerous cargo classes beyond `Flammable` and `Oxidizer`.
- Add stack weight limits by container type or tier.
- Add sensitivity analysis for objective weights.
- Add decomposition or rolling-horizon methods for larger instances.
- Migrate the MILP implementation to the PuLP 4 API and replace deprecated CBC command usage.
- Add optional persistence with SQLite.
- Add optional static type checking with mypy.

### Scalability and Solver Optimization

- Add safe candidate-slot pruning for assignments that are impossible by hard constraints.
- Add MILP symmetry-breaking constraints where they preserve the feasible region.
- Add stronger MILP bounds or preprocessing to reduce model size.
- Add warm-start support for MILP from Greedy or GA solutions.
- Cache repeated metric and fitness computations in the Genetic Algorithm.
- Optimize real rehandling simulation for larger instances.
- Explore broader hybrid approaches beyond the planned swap-based local search.
- Separate safe model-preserving optimizations from heuristic search-space reductions.
