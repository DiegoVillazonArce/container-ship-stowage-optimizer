# Metrics and Constraints

This document explains the hard constraints and final metrics used throughout
the project. Every solver output is evaluated by the shared metrics engine.

For implementation details, see [DESIGN.md](./DESIGN.md).

## Hard Constraints

Hard constraints define structural validity. A plan with structural violations
is not a valid stowage plan, even if some metrics look good.

### Unique Assignment

Every container must be assigned exactly once:

```text
sum_p x[c, p] = 1 for every container c
```

### Slot Capacity

Each slot can hold at most one container:

```text
sum_c x[c, p] <= 1 for every slot p
```

### Stack Continuity

An upper-tier slot can only be occupied if the slot directly below is occupied.
This prevents floating containers.

### Reefer Compatibility

Reefer containers require reefer-capable slots with power support.

### Incompatible Cargo Separation

The model includes two simplified incompatible cargo classes:

- `Flammable`;
- `Oxidizer`.

They must be separated by a configurable minimum bay distance. The MILP uses
bay-level indicators to keep this formulation compact.

### Horizontal CG Tolerance

The app checks whether horizontal center of gravity stays within configured
tolerances:

```text
abs(CG_x) <= tau_lon
abs(CG_y) <= tau_lat
```

This is treated separately from structural feasibility. A plan can be
structurally valid but still outside CG tolerance.

## Feasibility Flags

| Flag | Meaning |
| --- | --- |
| `is_structurally_feasible` | No structural hard-constraint violations. |
| `cg_within_tolerance` | `CG_x` and `CG_y` are inside configured tolerance. |
| `operationally_feasible` | Structurally feasible and within horizontal CG tolerance. |
| `is_feasible` | Alias for operational feasibility. |

## Final Metrics

| Metric | Meaning | Desired direction |
| --- | --- | --- |
| `total_weight` | Total assigned container weight. | Informational |
| `slot_utilization` | Occupied slots divided by total slots. | Context dependent |
| `CG_x` | Longitudinal center of gravity. | Close to 0 |
| `CG_y` | Lateral center of gravity. | Close to 0 |
| `CG_z_normalized` | Normalized vertical center of gravity. | Lower is usually better |
| `real_rehandling` | Blocking moves during unloading simulation. | Lower is better |
| `constraint_violations` | Count of structural rule violations. | 0 |
| `unassigned_container_count` | Containers missing from the plan. | 0 |

## Center of Gravity

Horizontal CG is computed from weight moments, not simple side totals:

```text
CG_x = sum_i(w_i * x_i) / W
CG_y = sum_i(w_i * y_i) / W
W    = sum_i(w_i)
```

This accounts for both weight and distance from the vessel center.

Vertical CG is normalized:

```text
CG_z = sum_i(w_i * z_i) / W
```

The project uses `CG_z` as a simplified heavy-low proxy. It does not compute
full naval stability, metacentric height, ballast, hydrostatics, or lashing
forces.

## Real Rehandling

Real rehandling is computed by simulating unloading in route order. If a
container that should unload now is blocked by containers above it, those
blocking containers are counted as rehandled.

This is different from the MILP rehandling proxy, which is linear and easier to
optimize but not identical to the simulated final metric.

## Why Shared Metrics Matter

Greedy, MILP, GA, and Local Search do not optimize identical internal objective
functions. Therefore, raw objective values are not directly comparable.

Final comparison should use:

- feasibility;
- `CG_x`;
- `CG_y`;
- `CG_z_normalized`;
- real rehandling;
- utilization;
- runtime;
- diagnostics.

