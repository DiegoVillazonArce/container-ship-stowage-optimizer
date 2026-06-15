# Container Ship Stowage Optimizer Design Document

## 1. Purpose of the Design Document

This document describes the technical and mathematical design of the **Container Ship Stowage Optimizer**. It complements the README by going deeper into the model structure, assumptions, constraints, objective function, solver strategy, evaluation metrics, and known limitations.

The project is an academic optimization system inspired by container ship stowage planning. It is not intended to be certified maritime software or a replacement for industrial stowage systems. The design favors rigor, clarity, and implementability within a simplified setting.

## 2. Problem Definition

Given:

- A simplified container ship represented as a finite set of slots.
- A list of containers with weight, destination port, and cargo type.
- A route sequence defining the order in which ports are visited.
- Operational restrictions such as stack continuity, reefer compatibility, incompatible cargo separation, and horizontal balance.

The problem is to assign each container to exactly one vessel slot:

```text
slot = (bay, row, tier)
```

while satisfying hard constraints and optimizing a weighted objective that considers:

- Horizontal center-of-gravity deviation.
- Vertical center-of-gravity proxy.
- Rehandling cost or rehandling proxy.

The primary assignment decision is:

```text
x[c, p] = 1 if container c is assigned to slot p
x[c, p] = 0 otherwise
```

where `c` belongs to the container set `C` and `p` belongs to the slot set `P`.

## 3. Modeling Assumptions

The design uses the following assumptions:

- The vessel is represented as a discrete three-dimensional grid `(bay, row, tier)`.
- Every slot can hold at most one container.
- Every container must be assigned exactly once in the main formulation.
- The vessel shape is simplified as a rectangular grid.
- Each slot maps to normalized physical coordinates `x`, `y`, and `z`.
- `x` represents longitudinal position.
- `y` represents lateral position.
- `z` represents vertical height.
- The academic reference point for horizontal balance is the vessel geometric center:

```text
x_ref = 0
y_ref = 0
```

- Horizontal center of gravity is controlled using weight moments.
- Port-side/starboard-side and bow/stern balance are reported as visual metrics, not used as the main balance constraint.
- Full naval stability is not modeled.
- Normalized `CG_z` is used as a soft penalty to encourage heavy containers in lower tiers.
- Reefer containers may only be assigned to slots with electrical connection.
- `Flammable` and `Oxidizer` cargo are separated using aggregated bay-level binary variables.
- MILP uses a linear proxy for rehandling.
- Greedy and Genetic Algorithm solvers may evaluate real rehandling through unloading simulation.
- Internal objective values should not be compared directly across algorithms when their proxies differ.

## 4. Vessel Model

The vessel is modeled as a set of discrete slots:

```text
P = B x R x T
```

where:

- `B` is the set of bays.
- `R` is the set of rows.
- `T` is the set of tiers.

Each position is identified as:

```text
p = (b, r, t)
```

with:

- `b`: bay index, representing longitudinal position.
- `r`: row index, representing lateral position.
- `t`: tier index, representing vertical position in a stack.

A `(bay, row)` pair defines one vertical stack. Containers are stacked along the `tier` axis.

The recommended initial test size is:

```text
6 bays x 4 rows x 4 tiers = 96 slots
```

This size is small enough for hand-checking and suitable for early MILP experiments.

## 5. Coordinate System

The discrete grid is mapped to normalized physical coordinates:

```text
x_p in [-1, 1]
y_p in [-1, 1]
z_p in [0, 1]
```

Interpretation:

- `x_p`: longitudinal coordinate of slot `p`.
- `y_p`: lateral coordinate of slot `p`.
- `z_p`: vertical coordinate of slot `p`.

Notation convention:

```text
x axis -> longitudinal direction -> CG_x -> Moment_lon -> tau_lon -> d_lon
y axis -> lateral direction      -> CG_y -> Moment_lat -> tau_lat -> d_lat
z axis -> vertical direction     -> CG_z
```

The geometric center of the vessel is used as the academic reference:

```text
x_ref = 0
y_ref = 0
```

This allows horizontal center-of-gravity calculations to be expressed as deviations from the normalized center. In a real vessel, ideal trim and stability references depend on hull form, loading condition, ballast, and hydrostatic data. Those effects are outside the scope of this academic model.

## 6. Input Data Model

### Vessel Configuration

The vessel input should include:

| Field | Description |
| --- | --- |
| `bays` | Number of longitudinal positions |
| `rows` | Number of lateral positions |
| `tiers` | Number of vertical levels |
| `reefer_slots` | Slots or bays with electrical connection |
| `cg_tolerance_lon` | Allowed longitudinal CG deviation |
| `cg_tolerance_lat` | Allowed lateral CG deviation |

### Container Data

Each container should include:

| Field | Description | Example |
| --- | --- | --- |
| `id` | Unique container identifier | `C001` |
| `weight` | Container weight in tons | `28.5` |
| `destination_port` | Port where the container is unloaded | `Panama` |
| `type` | Cargo type | `Normal`, `Reefer`, `Flammable`, `Oxidizer` |

### Route Data

The route is an ordered list of ports:

```text
route = [Port_1, Port_2, ..., Port_K]
```

Each container destination must appear in the route. The route order is used to evaluate unloading sequence and rehandling.

## 7. Decision Variables

### Main Assignment Variable

```text
x[c, p] in {0, 1}
```

Meaning:

```text
x[c, p] = 1 if container c is assigned to slot p
x[c, p] = 0 otherwise
```

The number of main binary variables grows as:

```text
number_of_containers * number_of_slots
```

This growth is the main scalability challenge for the MILP formulation.

### Auxiliary Variables

The MILP may also use:

```text
F[b] in {0, 1}
O[b] in {0, 1}
d_lon >= 0
d_lat >= 0
```

where:

- `F[b]` indicates whether bay `b` contains at least one flammable container.
- `O[b]` indicates whether bay `b` contains at least one oxidizer container.
- `d_lon` represents absolute longitudinal moment deviation.
- `d_lat` represents absolute lateral moment deviation.

## 8. Hard Constraints

### Unique Assignment

Each container must be assigned exactly once:

```text
sum over p in P of x[c, p] = 1
for every container c
```

### Slot Capacity

Each slot can hold at most one container:

```text
sum over c in C of x[c, p] <= 1
for every slot p
```

### Stack Continuity

A container cannot float above an empty slot:

```text
sum over c of x[c, (b, r, t)]
<=
sum over c of x[c, (b, r, t - 1)]

for every bay b, row r, and tier t > 1
```

### Reefer Compatibility

Reefer containers can only be assigned to slots with electrical connection:

```text
x[c, p] = 0
for every reefer container c
and every non-reefer slot p
```

### Horizontal Center-of-Gravity Limits

Horizontal center of gravity is constrained through moments:

```text
-tau_lon * W <= Moment_lon <= tau_lon * W
-tau_lat * W <= Moment_lat <= tau_lat * W
```

where:

```text
W = total container weight
```

and the moments are:

```text
Moment_lon = sum over c,p of weight[c] * x_coord[p] * x[c, p]
Moment_lat = sum over c,p of weight[c] * y_coord[p] * x[c, p]
```

This is equivalent to bounding:

```text
CG_x = Moment_lon / W
CG_y = Moment_lat / W
```

The model uses moment-based CG control instead of only comparing total weight by side or by vessel half.

### Structural Stack Weight

The model may include a simplified structural stack weight constraint. For each stack `(b, r)` and tier `t`, the total weight above a container should not exceed a maximum supported weight `M`:

```text
sum over t' > t, c of weight[c] * x[c, (b, r, t')]
<=
M * sum over c of x[c, (b, r, t)]
```

This constraint complements stack continuity. It is an academic approximation and does not model real structural forces, lashing forces, or vessel-class-specific loading rules. Its purpose is to avoid unrealistic patterns where a light lower container supports too much weight above it.

## 9. Incompatible Cargo Separation

The project includes a simplified dangerous cargo separation rule between:

- `Flammable`
- `Oxidizer`

A direct pairwise formulation can grow quickly because it may require constraints across many container-position pairs. Instead, the design uses bay-level aggregation.

### Bay-Level Variables

```text
F[b] = 1 if bay b contains at least one Flammable container
O[b] = 1 if bay b contains at least one Oxidizer container
```

Activation constraints:

```text
F[b] >= x[c, p]
for every flammable container c
and every slot p with bay(p) = b
```

```text
O[b] >= x[c, p]
for every oxidizer container c
and every slot p with bay(p) = b
```

Technical note:

```text
The lower-bound activation constraints are sufficient for the current hard-constraint use case, because F[b] and O[b] only need to activate when incompatible cargo is present. Upper-bound constraints may be added later if exact reporting of bay-level cargo presence is required.
```

Minimum separation:

```text
F[b] + O[b2] <= 1
for every pair of bays b, b2 where abs(b - b2) < d_min
```

This is an academic simplification. It captures the concept of incompatible cargo separation without modeling full dangerous goods regulations.

## 10. Horizontal Center of Gravity Model

The horizontal center of gravity is computed from weight moments.

For the longitudinal axis:

```text
Moment_lon = sum over c,p of weight[c] * x_coord[p] * x[c, p]
CG_x = Moment_lon / W
```

For the lateral axis:

```text
Moment_lat = sum over c,p of weight[c] * y_coord[p] * x[c, p]
CG_y = Moment_lat / W
```

The reference point is:

```text
x_ref = 0
y_ref = 0
```

The hard constraints are:

```text
abs(CG_x) <= tau_lon
abs(CG_y) <= tau_lat
```

In linear MILP form:

```text
-tau_lon * W <= Moment_lon <= tau_lon * W
-tau_lat * W <= Moment_lat <= tau_lat * W
```

For objective minimization, absolute deviations can be linearized:

```text
d_lon >= Moment_lon
d_lon >= -Moment_lon

d_lat >= Moment_lat
d_lat >= -Moment_lat
```

Then:

```text
d_lon / W approximates abs(CG_x)
d_lat / W approximates abs(CG_y)
```

Balance by port-side/starboard-side and bow/stern remains useful for reporting:

```text
port_side_weight
starboard_side_weight
bow_weight
stern_weight
```

However, these are dashboard metrics rather than the main mathematical balance constraints.

## 11. Vertical Center of Gravity Proxy

The project does not model full naval vertical stability. It does not calculate:

- Metacentric height.
- Hydrostatic curves.
- Hull-specific stability.
- Ballast effects.
- Dynamic sea-state behavior.

Instead, the model uses normalized vertical center of gravity as a soft penalty:

```text
VerticalPenalty = sum over c,p of weight[c] * z_coord[p] * x[c, p]
```

The corresponding vertical center of gravity is:

```text
CG_z = VerticalPenalty / W
```

If `z_coord[p]` is normalized to `[0, 1]`, then `CG_z` is already normalized:

```text
CG_z_normalized = CG_z
```

This encourages heavy containers to be placed in lower tiers:

```text
heavy container in low tier  -> lower CG_z
heavy container in high tier -> higher CG_z
```

This is a practical academic proxy, not a complete naval stability model.

## 12. Rehandling Model

Rehandling occurs when a container that must be unloaded earlier is blocked by containers above it that are unloaded later.

Example:

```text
Tier 2: Later destination
Tier 1: Earlier destination
```

The lower container cannot be removed without first moving the upper container.

### MILP Linear Proxy

An exact pairwise rehandling formulation can become large. The MILP therefore uses a linear proxy:

```text
RehandlingProxy = sum over c,p of phi[c, p] * x[c, p]
```

where `phi[c, p]` penalizes assigning early-destination containers to deeper positions in a stack.

A simple proxy is:

```text
phi[c, p] = Early(c) * Depth(p)
```

with:

```text
Early(c) = (o_max - o_c) / (o_max - 1)
```

and:

```text
Depth(p) = (H[b, r] - t) / (H[b, r] - 1)
```

This formula assumes that tier indexing starts at 1 for the bottom tier and increases upward.

where:

- `o_c` is the destination order of container `c`.
- `o_max` is the last route order.
- `H[b, r]` is the maximum stack height at `(b, r)`.
- `t` is the tier index of slot `p`.

If there is only one port, define:

```text
Early(c) = 0
```

If a stack has height one, define:

```text
Depth(p) = 0
```

### Real Rehandling by Simulation

Greedy and Genetic Algorithm solvers can evaluate real rehandling by simulating port-by-port unloading after a full assignment is available.

This is also the recommended final comparison metric:

```text
RehandlingReal = number of extra blocking moves during simulated unloading
```

The MILP proxy and real rehandling count are not the same quantity. They should be reported separately when needed.

### Rehandling Normalization

The MILP proxy and the real rehandling count do not have the same unit, so they should be normalized separately.

For MILP:

```text
ProxyMax = sum over c of max over p of phi[c, p]

RehandlingProxyNormalized = RehandlingProxy / ProxyMax
```

If `ProxyMax = 0`, define:

```text
RehandlingProxyNormalized = 0
```

For Greedy and Genetic Algorithm:

```text
RehandlingRealMax =
sum over stacks (b, r) of H[b, r] * (H[b, r] - 1) / 2

RehandlingRealNormalized = RehandlingReal / RehandlingRealMax
```

If `RehandlingRealMax = 0`, define:

```text
RehandlingRealNormalized = 0
```

`RehandlingProxyNormalized` is used inside the MILP objective. `RehandlingRealNormalized` is used to evaluate complete Greedy and Genetic Algorithm solutions. Final algorithm comparison should rely on shared metrics, especially real rehandling, rather than raw objective values.

## 13. Objective Function

The MILP objective combines horizontal centering, vertical loading quality, and a rehandling proxy:

```text
minimize
  alpha_lon * (d_lon / W)
+ alpha_lat * (d_lat / W)
+ lambda    * CG_z_normalized
+ delta     * RehandlingProxyNormalized
```

where:

- `alpha_lon` weights longitudinal centering.
- `alpha_lat` weights lateral centering.
- `lambda` weights vertical loading quality.
- `delta` weights unloading-sequence quality.

For Greedy and Genetic Algorithm solvers, an evaluation score may use real rehandling:

```text
Score =
  alpha_lon * abs(CG_x)
+ alpha_lat * abs(CG_y)
+ lambda    * CG_z_normalized
+ delta     * RehandlingRealNormalized
+ rho       * ConstraintViolations
```

where `rho` is a large penalty for infeasibility.

Important comparison rule:

```text
Do not compare raw internal objective values directly across algorithms
when they use different rehandling proxies or penalty structures.
```

Algorithm comparison should use common final metrics:

- Feasibility.
- Runtime.
- Horizontal CG.
- Normalized `CG_z`.
- Real rehandling.
- Utilization.
- Constraint violations.
- MILP optimality gap, when available.

## 14. Infeasibility Handling

The main formulation treats complete assignment as a hard requirement. If the model is infeasible, the system should return useful diagnostics instead of a generic failure.

Common causes include:

- More containers than available slots.
- More reefers than reefer-capable slots.
- CG tolerances that are too strict.
- Incompatible cargo separation that removes too much usable space.
- Stack continuity interacting with other constraints.
- Structural stack weight limits, if enabled.

Recommended behavior:

- Run pre-solve validation before optimization.
- Report clear validation errors.
- Preserve solver status and diagnostic messages.
- Suggest which parameters may need relaxation.
- For heuristic solvers, report violated constraints explicitly.

An optional future extension is partial assignment:

```text
sum over p of x[c, p] + u[c] = 1
```

where `u[c] = 1` means container `c` is unassigned. A large penalty would discourage unassigned containers:

```text
Omega * sum over c of u[c]
```

This is not part of the main formulation.

## 15. Solver Strategy

The project compares three solver families.

### Greedy Solver

Role:

- Fast baseline.
- Easy to explain.
- Useful for all instance sizes.

Expected behavior:

- Sort containers by weight, restrictions, or destination priority.
- Assign each container to the best currently feasible slot.
- Use repair or swaps when possible.
- Report violations if it cannot produce a feasible solution.

### MILP Solver

Role:

- Exact reference for small instances.
- Provides optimal or near-optimal solutions when tractable.
- Can report solver gap and infeasibility.

Expected behavior:

- Enforce hard constraints exactly.
- Use linear objective components.
- Start with small instances, such as `6 x 4 x 4`.

### Genetic Algorithm

Role:

- Search method for medium or large instances.
- Useful when MILP becomes computationally expensive.

Expected behavior:

- Encode complete assignments as chromosomes.
- Use mutation, crossover, selection, and repair.
- Penalize infeasibility.
- Evaluate real rehandling through simulation when feasible.

## 16. Metrics and Evaluation

Every solver should be evaluated with the same final metrics:

| Metric | Purpose |
| --- | --- |
| Feasibility | Indicates whether all hard constraints are satisfied |
| Runtime | Measures computational cost |
| `CG_x` | Longitudinal center-of-gravity deviation |
| `CG_y` | Lateral center-of-gravity deviation |
| `CG_z_normalized` | Vertical loading quality proxy |
| Real rehandling | Operational unloading inefficiency |
| Slot utilization | Percentage of occupied vessel slots |
| Constraint violations | Diagnostic count for heuristics |
| Port-side/starboard-side weight | Intuitive lateral balance reporting |
| Bow/stern weight | Intuitive longitudinal balance reporting |
| MILP optimality gap | Exact solver quality indicator when available |

The final benchmark table should compare these metrics directly. It should not claim that different solver objective values are equivalent when their internal scoring functions differ.

## 17. Scalability Considerations

The primary MILP variable count is:

```text
|C| * |P|
```

For example:

```text
800 containers * 1,600 slots = 1,280,000 binary variables
```

This can make MILP intractable without decomposition, simplification, or strong time limits.

The recommended scaling path is:

1. Validate all logic on very small hand-checkable instances.
2. Use `6 x 4 x 4` as an early benchmark size.
3. Increase grid and container counts gradually.
4. Use MILP as a small-instance reference.
5. Use Greedy and Genetic Algorithm solvers for larger instances.

Additional constraints also affect scalability:

- Incompatible cargo constraints add bay-level binary variables and bay-pair constraints.
- Rehandling exact formulations can grow pairwise and should be avoided in the first MILP.
- Genetic Algorithm evaluation can become expensive if rehandling simulation is not optimized.

## 18. Testing Strategy

The test suite should cover the system at several levels.

### Domain Model Tests

- Slot creation.
- Vessel grid generation.
- Coordinate normalization.
- Reefer slot marking.
- Container type validation.

### Input Validation Tests

- Duplicate container IDs.
- Invalid weights.
- Unknown cargo types.
- Destination ports not in route.
- Too many containers for available slots.
- Too many reefers for reefer slots.

### Metrics Tests

- Total weight.
- Utilization.
- `CG_x`.
- `CG_y`.
- `CG_z_normalized`.
- Port-side/starboard-side weight.
- Bow/stern weight.
- Real rehandling count.
- Constraint violation counts.

### Solver Tests

- Greedy solves simple feasible instances.
- MILP returns feasible solutions for known small cases.
- MILP reports infeasibility for impossible cases.
- GA encoding and decoding preserve container uniqueness.
- Repair logic removes duplicate slot assignments when possible.

### Integration Tests

- Load a small dataset.
- Build a vessel.
- Run a solver.
- Validate the returned solution.
- Compute common metrics.

## 19. Design Limitations

This design intentionally excludes several real-world complexities:

- It does not model full naval architecture stability.
- It does not calculate metacentric height.
- It does not model hydrostatics.
- It does not model ballast, fuel, or dynamic sea conditions.
- It does not model crane scheduling.
- It does not model certified dangerous goods segregation.
- It does not model container dimensions beyond a simplified one-slot assumption.
- It does not model hatch covers, lashing forces, or industrial-grade vessel-specific rules.
- It does not guarantee industrial-grade operational validity.

These limitations are acceptable for the academic goal: build a rigorous, explainable, and testable optimization model that captures key ideas of container stowage without exceeding the project scope.

## 20. Future Design Extensions

Possible extensions include:

- Configurable vessel templates with non-rectangular slot availability.
- Partial assignment with high-penalty unassigned containers.
- Exact pairwise rehandling model for small instances.
- More detailed stack weight and structural constraints.
- Multiple dangerous cargo classes and richer separation rules.
- Scenario export and import.
- Sensitivity analysis for objective weights.
- Local search improvement after Greedy construction.
- Hybrid GA with repair and local optimization.
- Decomposition methods for large MILP instances.
- Parallel fitness evaluation for the Genetic Algorithm.
- More detailed unloading simulation.
- Optional persistence using SQLite.
- More advanced dashboard reporting for benchmark experiments.
