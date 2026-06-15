# Container Ship Stowage Optimizer Roadmap

## Purpose

This roadmap defines a lightweight Scrum-style development plan for the **Container Ship Stowage Optimizer**. It is intended for an individual academic project, so it avoids heavy process overhead while still organizing the work into clear, testable increments.

The goal is to move from a small correct optimization core to comparable algorithms, then to an interactive Streamlit application with 3D visualization and unloading simulation.

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

- [ ] Create `metrics.py`.
- [ ] Implement total weight calculation.
- [ ] Implement slot utilization calculation.
- [ ] Implement lateral moment calculation.
- [ ] Implement longitudinal moment calculation.
- [ ] Implement `CG_y`.
- [ ] Implement `CG_x`.
- [ ] Implement normalized `CG_z`.
- [ ] Implement port-side and starboard-side weight reporting.
- [ ] Implement bow and stern weight reporting.
- [ ] Implement horizontal CG tolerance checks.
- [ ] Implement reefer violation checks.
- [ ] Implement stack continuity violation checks.
- [ ] Implement incompatible cargo violation checks.
- [ ] Implement real rehandling simulation by route order.
- [ ] Implement final metrics object or dictionary.
- [ ] Add unit tests for hand-checkable layouts.

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

- [ ] Create common solver interface.
- [ ] Create `GreedySolver`.
- [ ] Sort containers by weight and constraint priority.
- [ ] Generate candidate slots for each container.
- [ ] Enforce slot capacity during construction.
- [ ] Enforce stack continuity during construction.
- [ ] Enforce reefer compatibility during construction.
- [ ] Add scoring for horizontal CG impact.
- [ ] Add scoring for vertical placement.
- [ ] Add scoring for rehandling risk.
- [ ] Add simplified incompatible cargo checks.
- [ ] Add optional swap-based repair.
- [ ] Return solution status: feasible, repaired, or infeasible.
- [ ] Report runtime.
- [ ] Add unit tests with small instances.

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

- [ ] Choose MILP library, such as OR-Tools, PuLP, or Pyomo.
- [ ] Create `MILPSolver`.
- [ ] Define binary variables `x[c, p]`.
- [ ] Add unique assignment constraints.
- [ ] Add slot capacity constraints.
- [ ] Add stack continuity constraints.
- [ ] Add reefer compatibility constraints.
- [ ] Add bay-level binary variables for flammable cargo.
- [ ] Add bay-level binary variables for oxidizer cargo.
- [ ] Add minimum bay-distance separation constraints.
- [ ] Add horizontal CG moment constraints.
- [ ] Add auxiliary variables for absolute lateral CG deviation.
- [ ] Add auxiliary variables for absolute longitudinal CG deviation.
- [ ] Add normalized vertical CG penalty.
- [ ] Add linear rehandling proxy.
- [ ] Add objective weights.
- [ ] Add solver time limit configuration.
- [ ] Return status, objective value, runtime, and gap when available.
- [ ] Add tests for infeasible and feasible small instances.

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

- [ ] Create `GeneticSolver`.
- [ ] Define chromosome representation.
- [ ] Generate initial population.
- [ ] Add feasibility-aware initialization when possible.
- [ ] Implement fitness evaluation.
- [ ] Include horizontal CG deviation in fitness.
- [ ] Include normalized `CG_z` in fitness.
- [ ] Include real rehandling simulation in fitness.
- [ ] Include penalty for constraint violations.
- [ ] Implement selection.
- [ ] Implement crossover.
- [ ] Implement mutation.
- [ ] Implement repair for duplicate slots and missing containers.
- [ ] Implement stopping criteria.
- [ ] Report best solution, runtime, and generation count.
- [ ] Add reproducible random seed configuration.
- [ ] Add tests for encoding, decoding, and repair logic.

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

- [ ] Create `app/main.py`.
- [ ] Add Streamlit sidebar.
- [ ] Add vessel dimension inputs.
- [ ] Add reefer slot or reefer bay configuration.
- [ ] Add CSV upload.
- [ ] Add route sequence input.
- [ ] Add algorithm selector.
- [ ] Add CG tolerance controls.
- [ ] Add objective weight controls.
- [ ] Add solver time limit controls.
- [ ] Add run optimization button.
- [ ] Display validation errors.
- [ ] Display solution status.
- [ ] Display common KPI metrics.
- [ ] Display final stowage plan table.
- [ ] Display algorithm comparison table.
- [ ] Add session state for latest scenario and solution.

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

- [ ] Create `viz/plot3d.py`.
- [ ] Generate Plotly 3D container blocks or markers.
- [ ] Color containers by destination port.
- [ ] Add hover details for container ID, weight, port, type, and slot.
- [ ] Add visual distinction for reefer containers.
- [ ] Add visual distinction for dangerous cargo classes.
- [ ] Add selected-port unloading simulation.
- [ ] Identify containers removed at each port.
- [ ] Identify temporary rehandling moves.
- [ ] Recompute metrics after simulated unloading.
- [ ] Display updated utilization.
- [ ] Display updated CG metrics.
- [ ] Add tests for unloading sequence logic.

### Definition of Done

- A solved stowage plan can be displayed in 3D.
- Users can inspect container metadata from the visualization.
- Port-by-port unloading produces rehandling counts.
- Metrics can be recalculated after simulated unloading steps.

## Phase 8 — Testing, Benchmarking, and Documentation

### Goal

Finalize the academic project by strengthening tests, creating benchmark scenarios, and documenting design decisions.

### User Stories

- As a developer, I want known small test cases, so that solver correctness can be checked manually.
- As a developer, I want benchmark instances, so that algorithm behavior can be compared empirically.
- As a developer, I want documented limitations, so that the project scope is clear and academically honest.
- As a developer, I want reproducible result tables, so that the final analysis can be defended.

### Tasks

- [ ] Add unit tests for domain models.
- [ ] Add unit tests for validation.
- [ ] Add unit tests for metrics.
- [ ] Add unit tests for solver interfaces.
- [ ] Add integration tests for small scenarios.
- [ ] Create benchmark datasets.
- [ ] Benchmark Greedy, MILP, and GA on shared instances.
- [ ] Record runtime, feasibility, CG metrics, `CG_z`, rehandling, utilization, and violations.
- [ ] Document solver assumptions.
- [ ] Document known limitations.
- [ ] Update README links to design and roadmap documents.
- [ ] Add example screenshots after the interface exists.
- [ ] Add reproducibility notes.

### Definition of Done

- Core behavior is covered by automated tests.
- Benchmark scenarios can be rerun.
- Algorithm comparison uses common final metrics.
- Documentation explains the mathematical model, implementation plan, assumptions, and limitations.

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
- Add scenario export to JSON or CSV.
- Add benchmark result export.
- Add sensitivity analysis for objective weights.
- Add decomposition or rolling-horizon methods for larger instances.
- Add more advanced local search after Greedy or GA.
- Add richer Streamlit visual diagnostics.
- Add optional persistence with SQLite.
- Add documentation comparing academic assumptions with real maritime planning constraints.
