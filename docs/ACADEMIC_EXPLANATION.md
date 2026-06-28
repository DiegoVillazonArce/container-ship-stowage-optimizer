# Academic Explanation

This document frames the project as an academic optimization system. It explains
the modeling choices, assumptions, limitations, and interpretation boundaries
that make the project defensible.

## Problem Statement

The container stowage problem asks where each container should be placed on a
ship. In this simplified project, the ship is a discrete grid of slots:

```text
(bay, row, tier)
```

The optimizer assigns containers to slots while respecting physical and
operational rules. The resulting plan is evaluated by center-of-gravity,
rehandling, utilization, and violation metrics.

## Why This Is an Optimization Problem

Each container-slot assignment is a decision. A small vessel can already produce
many possible layouts, and each layout has tradeoffs:

- good balance may conflict with easy unloading;
- low vertical CG may conflict with destination order;
- cargo compatibility can reduce available slots;
- exact optimization can become expensive as the instance grows.

This makes the problem a good setting for comparing exact and heuristic methods.

## Modeling Scope

The project intentionally models a simplified version of real stowage planning.
It is designed to be:

- implementable in a compact academic codebase;
- mathematically explainable;
- testable on hand-checkable instances;
- interactive through Streamlit;
- honest about what it does not model.

It is not certified industrial stowage software.

## Core Assumptions

| Area | Assumption | Limitation |
| --- | --- | --- |
| Vessel geometry | Rectangular `(bay, row, tier)` grid. | No hull shape or hatch-cover details. |
| Container size | One container occupies one slot. | No mixed sizes or over-slot cargo. |
| Balance | CG uses normalized coordinates around geometric center. | No trim, ballast, or hydrostatics. |
| Vertical stability | `CG_z` is a soft heavy-low proxy. | No metacentric height or stability curves. |
| Dangerous cargo | Flammable/Oxidizer bay separation. | Not full IMO dangerous-goods segregation. |
| Rehandling | Simulated stack unloading for final metrics. | No crane scheduling. |
| Structural strength | Stack-weight limits are not modeled. | No lashing or structural force analysis. |

## Exact vs Heuristic Methods

The project compares:

- Greedy as a fast constructive baseline;
- MILP as an exact reference for small instances;
- Genetic Algorithm as a scalable metaheuristic;
- Local Search as post-processing for Greedy/GA.

This comparison is academically useful because it shows the tradeoff between
proof quality, runtime, scalability, and final operational metrics.

## What MILP "Optimal" Means

When MILP reports `optimal`, it means optimal for the implemented MILP
formulation and objective. It does not mean the plan is best on every dashboard
metric.

In particular:

- MILP uses a linear rehandling proxy;
- final results report simulated real rehandling;
- Greedy/GA with Local Search can outperform MILP on some final metrics while
  MILP remains mathematically optimal for its own formulation.

This distinction is important for academic honesty.

## Interpreting Results

For the canonical result-reading order, see
[Metrics and Constraints](./METRICS_AND_CONSTRAINTS.md#why-shared-metrics-matter).
The academic point is that feasibility, shared final metrics, and diagnostics
should be interpreted before making claims about which algorithm is "better."

## Academic Value

The project demonstrates:

- domain modeling from logistics requirements;
- exact optimization with MILP;
- heuristic optimization with Greedy and GA;
- hybrid improvement with Local Search;
- shared metrics for fair comparison;
- diagnostic visualization;
- reproducible experiments;
- test-driven validation of constraints and metrics;
- public deployment through Streamlit.

## Suggested Defense Points

- The model is intentionally simplified but internally consistent.
- Hard constraints are separated from soft optimization goals.
- MILP optimality is formulation-specific.
- Shared final metrics prevent unfair algorithm comparison.
- Local Search improves heuristic outputs without changing solver formulations.
- The app exposes assumptions and limitations directly through the Academic guide.
