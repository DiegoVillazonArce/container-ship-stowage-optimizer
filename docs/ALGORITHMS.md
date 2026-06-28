# Algorithms

This document summarizes the optimization approaches implemented in the project.
All algorithms return a `SolverResult` and are evaluated with the same final
metrics engine.

For mathematical details, see [DESIGN.md](./DESIGN.md).

## Overview

| Algorithm | Role | Best for | Optimality guarantee |
| --- | --- | --- | --- |
| Greedy | Fast constructive baseline | Quick plans and large scenarios | No |
| MILP | Exact mathematical reference | Small instances | Yes, for its formulation |
| Genetic Algorithm | Metaheuristic search | Medium/larger scenarios | No |
| Local Search | Post-processing by swaps | Improving Greedy/GA outputs | No |

## Greedy Solver

The Greedy solver constructs a complete plan by assigning containers one at a
time. It prioritizes constrained or important containers, evaluates feasible
candidate slots, and chooses the best slot according to a local scoring rule.

It is useful because it is fast, deterministic, and easy to explain. Its main
limitation is that it does not look globally across all assignments, so a local
choice can block a better later layout.

Implemented behavior includes:

- unique assignment;
- slot capacity;
- stack continuity;
- reefer compatibility;
- simplified incompatible cargo checks;
- horizontal CG-aware slot scoring;
- rehandling-aware scoring;
- optional repair;
- optional Local Search post-processing.

## MILP Solver

The MILP solver models the problem with binary assignment variables:

```text
x[c, p] = 1 if container c is assigned to slot p
x[c, p] = 0 otherwise
```

It enforces hard constraints directly in a PuLP/CBC model and optimizes a
weighted linear objective. The objective includes:

- horizontal CG deviation;
- normalized vertical CG proxy;
- linear rehandling proxy.

MILP is the exact reference for small scenarios. When it reports `optimal`, that
means optimal for the implemented MILP formulation, not automatically best on
every final dashboard metric.

Important interpretation notes:

- the MILP rehandling proxy is not the same as simulated real rehandling;
- objective values are not comparable across Greedy, MILP, and GA;
- time-limited MILP can return a feasible incumbent without proving optimality;
- large instances may become expensive because variables scale with
  containers x slots.

## Genetic Algorithm

The Genetic Algorithm evolves a population of complete stowage plans. It uses:

- chromosome encoding of assignments;
- initialization with feasibility-aware candidates;
- selection;
- crossover;
- mutation;
- repair;
- fitness evaluation using shared final metrics;
- optional random seed for reproducibility;
- optional Local Search post-processing.

GA is useful when MILP becomes too expensive but a broader search than Greedy is
desired. It does not prove optimality, so its results should be interpreted
through the shared final metrics and diagnostics.

## Local Search Post-processing

Local Search runs after Greedy or GA when enabled. It starts from an existing
complete solution and tries pairwise swaps between assigned containers.

A candidate swap is evaluated with the common metrics engine and is rejected if
it breaks structural hard constraints:

- unique assignment;
- slot capacity;
- stack continuity;
- reefer compatibility;
- incompatible cargo separation.

Accepted swaps must improve the local-search score, which emphasizes:

- reduced horizontal CG deviation;
- reduced CG tolerance excess;
- reduced real rehandling;
- limited vertical CG worsening.

Stopping criteria:

- max evaluated swaps;
- max rounds without improvement;
- optional time limit.

Local Search is deterministic unless randomness is explicitly introduced by the
starting solver.

## How to Compare Algorithms

Compare algorithms with final shared metrics, not raw internal objective values.
The canonical comparison order is documented in
[Metrics and Constraints](./METRICS_AND_CONSTRAINTS.md#why-shared-metrics-matter).
This is especially important for MILP because its certified optimum is relative
to a linear formulation that uses a rehandling proxy.
