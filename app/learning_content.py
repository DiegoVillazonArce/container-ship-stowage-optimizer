"""Structured academic explanation content for the Streamlit learning layer.

Phase 14 adds a dedicated learning / academic guide to the app. This module
holds the explanatory content as plain data so it can be unit-tested and
maintained independently of the Streamlit UI and of the solver logic. It is
deliberately free of any ``streamlit`` import; :mod:`main` renders the
structures returned here with tabs, expanders, and tables.

The content has two reading paths:

- a plain-language explanation for non-specialist users
  (:attr:`LearningTopic.simple`);
- a more technical / academic reading
  (:attr:`LearningTopic.technical`).

It must stay academically honest and consistent with ``README.md`` and
``docs/DESIGN.md``: the model is a simplified, discrete, academic optimizer,
not certified industrial stowage software.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LearningTopic:
    """One explained concept with a plain-language and a technical reading.

    ``simple`` is markdown aimed at a non-specialist. ``technical`` is markdown
    with the more formal / academic view (compact formulas, model details). Both
    are kept short and scannable so a single screen never becomes a wall of
    text.

    ``formula`` optionally carries a single centerpiece equation as a LaTeX
    string (no surrounding ``$``). The UI renders it with ``st.latex`` below the
    technical prose so math-heavy topics read like an academic reference instead
    of inline ASCII. It is empty for topics that have no clean single formula.
    """

    id: str
    title: str
    simple: str
    technical: str = ""
    formula: str = ""


@dataclass(frozen=True)
class LearningSection:
    """A group of related topics rendered as one tab in the learning guide.

    ``table`` optionally names a compact reference table the UI should render
    alongside the topics (for example the constraint, metric, algorithm, or
    assumption tables). It is a stable string key, not Streamlit state.

    ``diagram`` and ``example`` are stable keys for an optional inline visual: a
    ``diagram`` resolves to an SVG builder in :data:`LEARNING_DIAGRAMS` (rendered
    before the topics), and an ``example`` is one of :data:`LEARNING_EXAMPLE_KEYS`
    that the UI renders after the topics (currently the plotly CG figure). Both
    are declared here, beside the content, so the UI never has to branch on a
    section's ``id`` to decide what extra visual to show.
    """

    id: str
    title: str
    summary: str
    topics: tuple[LearningTopic, ...]
    table: str | None = None
    diagram: str | None = None
    example: str | None = None


# --------------------------------------------------------------------------- #
# Compact reference tables                                                      #
# --------------------------------------------------------------------------- #


def constraint_explanation_rows() -> list[dict[str, str]]:
    """Return the hard/operational constraint reference rows.

    Covers the structural feasibility rules from DESIGN.md sections 8 and 9 plus
    the configurable horizontal CG tolerance, which is reported separately
    because a structurally valid plan may still be deliberately unbalanced.
    """
    return [
        {
            "constraint": "Unique assignment",
            "plain_language": "Every container is placed exactly once.",
            "technical": "sum over p of x[c, p] = 1 for every container c.",
            "feasibility": "Structural",
        },
        {
            "constraint": "Slot capacity (single slot)",
            "plain_language": "Each (bay, row, tier) position holds at most one container.",
            "technical": "sum over c of x[c, p] <= 1 for every slot p.",
            "feasibility": "Structural",
        },
        {
            "constraint": "Stack continuity",
            "plain_language": (
                "No floating containers: a tier can only be used when the slot "
                "directly below it is filled."
            ),
            "technical": (
                "sum_c x[c, (b, r, t)] <= sum_c x[c, (b, r, t-1)] for every tier t > 1."
            ),
            "feasibility": "Structural",
        },
        {
            "constraint": "Reefer compatibility",
            "plain_language": (
                "Refrigerated containers may only go in reefer-capable (powered) slots."
            ),
            "technical": "x[c, p] = 0 for every reefer container c and non-reefer slot p.",
            "feasibility": "Structural",
        },
        {
            "constraint": "Incompatible cargo separation",
            "plain_language": (
                "Flammable and Oxidizer cargo must sit in bays kept a minimum distance apart."
            ),
            "technical": (
                "Bay-level F[b], O[b]; F[b] + O[b2] <= 1 when abs(b - b2) < d_min."
            ),
            "feasibility": "Structural",
        },
        {
            "constraint": "Horizontal CG tolerance",
            "plain_language": (
                "The horizontal balance point must stay near the vessel center."
            ),
            "technical": "abs(CG_x) <= tau_lon and abs(CG_y) <= tau_lat.",
            "feasibility": "Operational (configurable bound)",
        },
    ]


def constraint_symbol_legend() -> list[dict[str, str]]:
    """Return short definitions for the shorthand symbols in the constraint table.

    The compact ``technical`` cells lean on a few symbols (tolerances, minimum
    bay distance, bay-level indicators). They are spelled out here so the table
    can stay terse without leaving a non-specialist guessing what each symbol
    means. The UI renders these under the constraint reference table.
    """
    return [
        {
            "symbol": "x[c, p]",
            "meaning": "1 if container c is placed in slot p, otherwise 0.",
        },
        {
            "symbol": "tau_lon / tau_lat",
            "meaning": "configurable longitudinal / lateral CG tolerance.",
        },
        {
            "symbol": "d_min",
            "meaning": "minimum bay distance required between incompatible cargo.",
        },
        {
            "symbol": "F[b] / O[b]",
            "meaning": "1 if bay b holds Flammable / Oxidizer cargo.",
        },
    ]


def metric_explanation_rows() -> list[dict[str, str]]:
    """Return the common final-metric reference rows.

    These are the shared metrics used to compare every solver (DESIGN.md
    section 16). Raw internal objective values are intentionally excluded
    because they are not comparable across algorithms.
    """
    return [
        {
            "metric": "CG_x",
            "plain_language": "Longitudinal (bow-stern) balance point.",
            "good_values": "Close to 0; within +/- tau_lon.",
            "technical": "CG_x = longitudinal_moment / W = (sum wi * xi) / W.",
        },
        {
            "metric": "CG_y",
            "plain_language": "Lateral (port-starboard) balance point.",
            "good_values": "Close to 0; within +/- tau_lat.",
            "technical": "CG_y = lateral_moment / W = (sum wi * yi) / W.",
        },
        {
            "metric": "CG_z",
            "plain_language": "Vertical loading quality; lower means heavy cargo sits lower.",
            "good_values": "Lower is usually better (more stable).",
            "technical": "CG_z = (sum wi * zi) / W, normalized with zi in [0, 1].",
        },
        {
            "metric": "Slot utilization",
            "plain_language": "Share of vessel slots that are occupied.",
            "good_values": "Context dependent; confirms coverage, not quality.",
            "technical": "occupied_slots / total_slots.",
        },
        {
            "metric": "Real rehandling",
            "plain_language": "Extra container moves needed during unloading.",
            "good_values": "Lower is better (fewer wasted moves).",
            "technical": "Blocking moves counted by simulating port-by-port unloading.",
        },
        {
            "metric": "Constraint violations",
            "plain_language": "How many structural rules a plan breaks.",
            "good_values": "0 for a structurally valid plan.",
            "technical": (
                "Sum of unassigned, duplicate-slot, reefer, stack-continuity, and "
                "incompatible-cargo violations."
            ),
        },
        {
            "metric": "Operational feasibility",
            "plain_language": "Whether the plan is both valid and balanced.",
            "good_values": "True is desired.",
            "technical": "is_structurally_feasible AND CG within tolerance.",
        },
    ]


def algorithm_explanation_rows() -> list[dict[str, str]]:
    """Return the solver-comparison reference rows.

    Describes each approach, what it is good for, and its limitations so users
    can connect solver outputs to the underlying method (DESIGN.md section 15).
    """
    return [
        {
            "algorithm": "Greedy",
            "role": "Fast constructive baseline.",
            "strengths": "Very fast, easy to explain, deterministic.",
            "limitations": (
                "No optimality guarantee; may leave horizontal CG unbalanced."
            ),
            "good_for": "A quick first plan on small to large instances.",
        },
        {
            "algorithm": "MILP",
            "role": "Exact reference for small instances.",
            "strengths": (
                "Provably optimal for its own formulation; reports gap and infeasibility."
            ),
            "limitations": (
                "Variables grow as containers x slots; uses a linear rehandling proxy, "
                "not the real rehandling count."
            ),
            "good_for": "Small instances as a quality reference.",
        },
        {
            "algorithm": "Genetic Algorithm",
            "role": "Scalable population-based metaheuristic.",
            "strengths": (
                "Handles larger instances; evaluates real rehandling; reproducible with a seed."
            ),
            "limitations": "No optimality guarantee; quality depends on parameters and seed.",
            "good_for": "Medium to large instances where MILP is too expensive.",
        },
        {
            "algorithm": "Local Search",
            "role": "Swap-based post-processing after Greedy or GA.",
            "strengths": (
                "Improves horizontal CG and rehandling while preserving hard constraints."
            ),
            "limitations": (
                "Only local pairwise swaps; skipped if the starting plan is structurally "
                "infeasible."
            ),
            "good_for": "Polishing a feasible Greedy or GA solution.",
        },
    ]


def setting_explanation_rows() -> list[dict[str, str]]:
    """Return compact rows explaining configurable solver settings.

    These rows focus on interpretation rather than implementation details: they
    help a user understand what changes when they adjust objective weights,
    solver limits, GA controls, or local-search stopping criteria.
    """
    return [
        {
            "setting": "Objective weights",
            "plain_language": (
                "Weights express priorities, not absolute truths. Increasing one "
                "weight asks the solver to care more about that term."
            ),
            "technical": (
                "The MILP objective is a weighted sum of horizontal CG deviation, "
                "CG_z, and a linear rehandling proxy. Changing weights changes the "
                "tradeoff, not the hard constraints."
            ),
        },
        {
            "setting": "MILP time limit",
            "plain_language": (
                "A longer time limit can help MILP prove optimality, but small gains "
                "may cost much more runtime."
            ),
            "technical": (
                "CBC may return OPTIMAL, INFEASIBLE, or a feasible incumbent before "
                "optimality is certified. The gap/objective describe the MILP model, "
                "not a universal score across all algorithms."
            ),
        },
        {
            "setting": "GA population, generations, and seed",
            "plain_language": (
                "Bigger GA runs search more alternatives. A seed makes the run "
                "repeatable."
            ),
            "technical": (
                "Population size controls breadth, generations control search depth, "
                "and mutation/crossover explore new assignments. Fixed seeds make "
                "random choices deterministic for reproducible experiments."
            ),
        },
        {
            "setting": "Local search iterations",
            "plain_language": (
                "More swap attempts can improve a Greedy or GA plan, but eventually "
                "the search may stop finding useful changes."
            ),
            "technical": (
                "The post-processing step stops by max evaluated swaps, rounds "
                "without improvement, or an optional time limit. Accepted swaps must "
                "improve the local-search score and preserve structural constraints."
            ),
        },
    ]


def assumption_rows() -> list[dict[str, str]]:
    """Return the academic assumption / limitation reference rows.

    Kept consistent with the limitations documented in README.md section 20 and
    DESIGN.md section 20.
    """
    return [
        {
            "area": "Vessel geometry",
            "assumption": "The ship is a rectangular discrete grid of (bay, row, tier) slots.",
            "limitation": "No hull shape, hatch covers, or non-rectangular slot availability.",
        },
        {
            "area": "Container size",
            "assumption": "Each container occupies exactly one slot.",
            "limitation": "No mixed container sizes or over-slot cargo.",
        },
        {
            "area": "Horizontal balance",
            "assumption": "CG is controlled by weight moments around the geometric center (0, 0).",
            "limitation": "No trim references, ballast, or hydrostatics.",
        },
        {
            "area": "Vertical stability",
            "assumption": "Normalized CG_z is a soft penalty for heavy-low loading.",
            "limitation": "No metacentric height or full naval stability curves.",
        },
        {
            "area": "Dangerous cargo",
            "assumption": "Flammable/Oxidizer separation uses a simplified bay-distance rule.",
            "limitation": "Not certified IMO segregation or full dangerous-goods classes.",
        },
        {
            "area": "Rehandling",
            "assumption": "Real rehandling is a simplified stack simulation; MILP uses a proxy.",
            "limitation": "No crane scheduling; the proxy is not the real rehandling count.",
        },
        {
            "area": "Structural strength",
            "assumption": "Stack-weight limits are not modeled.",
            "limitation": "No lashing forces or stack weight limits.",
        },
        {
            "area": "Scope",
            "assumption": "An academic tool for comparing exact and heuristic approaches.",
            "limitation": "Not certified industrial stowage planning software.",
        },
    ]


# --------------------------------------------------------------------------- #
# Inline diagrams                                                               #
# --------------------------------------------------------------------------- #
#
# These return small self-contained SVG strings (no solver run, no Plotly) that
# the UI renders with ``st.markdown(..., unsafe_allow_html=True)``. They live
# here, as plain data, so they stay Streamlit-free and unit-testable. Text and
# outlines use ``currentColor`` so the figure inherits the active theme's text
# colour; only cargo blocks and pass/fail markers use explicit colours that read
# on both light and dark backgrounds.


def bay_row_tier_svg() -> str:
    """Return a small inline SVG of the ``(bay, row, tier)`` slot grid.

    A front cross-section (rows across, tiers up) with labelled axes plus a note
    that the bay axis runs into the page, so a non-specialist can connect the
    three slot indices to physical directions.
    """
    rows, tiers = 4, 3
    cell_w, cell_h = 55, 45
    x0, y_bottom = 95, 205
    cells: list[str] = []
    for r in range(rows):
        for t in range(tiers):
            x = x0 + r * cell_w
            y = y_bottom - (t + 1) * cell_h
            fill = "rgba(79, 142, 247, 0.35)" if t == 0 else "none"
            cells.append(
                f'<rect x="{x}" y="{y}" width="{cell_w}" height="{cell_h}" rx="3" '
                f'fill="{fill}" stroke="currentColor" stroke-width="1.5" />'
            )
    grid = "\n  ".join(cells)
    x_right = x0 + rows * cell_w
    y_top = y_bottom - tiers * cell_h
    y_mid = (y_bottom + y_top) // 2
    return f"""<div style="text-align:center">
<svg viewBox="0 0 460 270" xmlns="http://www.w3.org/2000/svg" role="img"
     aria-label="bay row tier grid" style="width:100%;max-width:460px;height:auto">
  <text x="230" y="28" text-anchor="middle" fill="currentColor" font-size="14"
        font-weight="bold">bay = position bow &#8596; stern (into the page)</text>
  {grid}
  <line x1="{x0 - 12}" y1="{y_bottom}" x2="{x0 - 12}" y2="{y_top}"
        stroke="currentColor" stroke-width="1.5" />
  <text x="{x0 - 45}" y="{y_mid}" fill="currentColor" font-size="13"
        text-anchor="middle"
        transform="rotate(-90 {x0 - 45} {y_mid})">tier (height &#8593;)</text>
  <line x1="{x0}" y1="{y_bottom + 18}" x2="{x_right}" y2="{y_bottom + 18}"
        stroke="currentColor" stroke-width="1.5" />
  <text x="{(x0 + x_right) // 2}" y="{y_bottom + 40}" text-anchor="middle"
        fill="currentColor" font-size="13">row (port &#8596; starboard)</text>
</svg>
</div>"""


def stack_continuity_svg() -> str:
    """Return a small inline SVG contrasting an invalid and a valid stack.

    The left stack has a gap below a filled top tier (a floating container, which
    is invalid); the right stack is filled from the bottom up (valid). Red and
    green markers flag each case.
    """
    cell_w, cell_h = 90, 45
    y_bottom = 195
    blue = "rgba(79, 142, 247, 0.35)"
    red = "#e8553c"
    green = "#2ca06a"

    def stack(x: int, filled: tuple[bool, bool, bool], empty_color: str) -> str:
        parts: list[str] = []
        for t in range(3):
            y = y_bottom - (t + 1) * cell_h
            if filled[t]:
                parts.append(
                    f'<rect x="{x}" y="{y}" width="{cell_w}" height="{cell_h}" rx="3" '
                    f'fill="{blue}" stroke="currentColor" stroke-width="1.5" />'
                )
            else:
                parts.append(
                    f'<rect x="{x}" y="{y}" width="{cell_w}" height="{cell_h}" rx="3" '
                    f'fill="none" stroke="{empty_color}" stroke-width="1.5" '
                    f'stroke-dasharray="6 4" />'
                )
        return "\n  ".join(parts)

    left = stack(60, (True, False, True), red)  # gap below a filled top -> floating
    right = stack(310, (True, True, False), green)  # continuous from the bottom
    marker_y = y_bottom - cell_h - 8
    return f"""<div style="text-align:center">
<svg viewBox="0 0 460 240" xmlns="http://www.w3.org/2000/svg" role="img"
     aria-label="stack continuity example" style="width:100%;max-width:460px;height:auto">
  <text x="105" y="28" text-anchor="middle" fill="{red}" font-size="13"
        font-weight="bold">Invalid: floating</text>
  <text x="355" y="28" text-anchor="middle" fill="{green}" font-size="13"
        font-weight="bold">Valid: continuous</text>
  {left}
  {right}
  <text x="105" y="{marker_y}" text-anchor="middle" fill="{red}" font-size="22"
        font-weight="bold">&#10007;</text>
  <text x="355" y="{marker_y}" text-anchor="middle" fill="{green}" font-size="22"
        font-weight="bold">&#10003;</text>
</svg>
</div>"""


# --------------------------------------------------------------------------- #
# Sections                                                                      #
# --------------------------------------------------------------------------- #


def _problem_overview_section() -> LearningSection:
    return LearningSection(
        id="problem_overview",
        title="Problem overview",
        summary="What the optimizer solves and why it matters.",
        topics=(
            LearningTopic(
                id="what_we_solve",
                title="What are we solving?",
                simple=(
                    "Given a list of containers and a ship made of stacking positions, "
                    "the optimizer decides **where each container goes**. Every container "
                    "gets exactly one position, and the plan must respect safety and "
                    "stacking rules."
                ),
                technical=(
                    "It is a binary assignment problem. The decision variable "
                    "`x[c, p] = 1` means container `c` is assigned to slot `p = (bay, row, "
                    "tier)`. Hard constraints define the feasible region; a weighted "
                    "objective ranks feasible plans by horizontal/vertical balance and "
                    "rehandling."
                ),
                formula=r"x_{c,p} \in \{0, 1\}, \qquad \sum_{p} x_{c,p} = 1 \quad \forall c",
            ),
            LearningTopic(
                id="why_it_matters",
                title="Why balance, safety, and unloading matter",
                simple=(
                    "A badly balanced ship is unsafe. Dangerous cargo must be kept apart. "
                    "And if early-port containers are buried under later-port ones, the "
                    "crew wastes time digging them out at each port (rehandling)."
                ),
                technical=(
                    "The model captures three operational concerns: horizontal center of "
                    "gravity (balance), a vertical CG proxy (keep weight low), and "
                    "multi-port rehandling. These are balanced against hard feasibility "
                    "rules such as reefer compatibility and incompatible-cargo separation."
                ),
            ),
        ),
    )


def _data_model_section() -> LearningSection:
    return LearningSection(
        id="data_model",
        title="Data model",
        summary="The ship grid, slots, containers, and the route.",
        diagram="grid",
        topics=(
            LearningTopic(
                id="vessel_as_grid",
                title="The ship as a grid",
                simple=(
                    "The ship is modeled as a simple 3D grid of boxes. Think of a "
                    "rectangular block of storage positions you can stack into."
                ),
                technical=(
                    "The slot set is `P = Bays x Rows x Tiers`. A small hand-checkable "
                    "reference size is `6 x 4 x 4 = 96` slots, used for early MILP "
                    "validation."
                ),
            ),
            LearningTopic(
                id="slots_bay_row_tier",
                title="Slots: (bay, row, tier)",
                simple=(
                    "Each position has three numbers: **bay** (front-to-back), **row** "
                    "(left-to-right), and **tier** (how high in the stack)."
                ),
                technical=(
                    "Bay is the longitudinal axis (bow<->stern), row the lateral axis "
                    "(port<->starboard), tier the vertical axis. Each slot maps to "
                    "normalized coordinates `x, y in [-1, 1]` and `z in [0, 1]`, with the "
                    "geometric center `(0, 0)` as the balance reference."
                ),
            ),
            LearningTopic(
                id="containers",
                title="Containers",
                simple=(
                    "Each container has a weight, a destination port, and a type "
                    "(Normal, Reefer, Flammable, or Oxidizer)."
                ),
                technical=(
                    "Reefer containers require powered slots. Flammable and Oxidizer are "
                    "incompatible cargo classes subject to bay-distance separation. Weight "
                    "drives all moment and balance calculations."
                ),
            ),
            LearningTopic(
                id="route_and_unloading_pressure",
                title="Route and unloading pressure",
                simple=(
                    "The route is the ordered list of ports the ship visits. Containers "
                    "leaving at the first port should sit on top so they are easy to reach."
                ),
                technical=(
                    "Route order defines unloading order. 'Unloading pressure' is the idea "
                    "that early-destination containers placed deep in a stack force later "
                    "containers to be moved aside first, which is counted as rehandling."
                ),
            ),
        ),
    )


def _constraints_section() -> LearningSection:
    return LearningSection(
        id="constraints",
        title="Constraints",
        summary="Hard rules, and structural vs operational feasibility.",
        diagram="stack_continuity",
        topics=(
            LearningTopic(
                id="hard_constraints",
                title="What makes a plan invalid",
                simple=(
                    "Some rules cannot be broken: every container placed once, one "
                    "container per slot, no floating stacks, reefers in powered slots, and "
                    "dangerous cargo kept apart. Breaking any of these makes the plan "
                    "structurally invalid."
                ),
                technical=(
                    "Structural hard constraints: unique assignment, slot capacity, stack "
                    "continuity, reefer compatibility, and incompatible-cargo separation. "
                    "See the table below for compact formulas."
                ),
            ),
            LearningTopic(
                id="structural_vs_operational",
                title="Structural vs operational feasibility",
                simple=(
                    "A plan can be physically valid (everything stacked legally) but still "
                    "be poorly balanced. We separate 'is it valid?' from 'is it also within "
                    "the balance tolerances?'"
                ),
                technical=(
                    "`is_structurally_feasible` is true when there are zero structural "
                    "violations. `operationally_feasible` additionally requires the "
                    "horizontal CG to be within tolerance. The CG tolerance is a "
                    "configurable bound, so it is reported as a warning rather than a "
                    "structural error."
                ),
            ),
        ),
        table="constraints",
    )


def _metrics_section() -> LearningSection:
    return LearningSection(
        id="metrics",
        title="Metrics",
        summary="How to read CG, utilization, rehandling, and feasibility.",
        example="cg",
        topics=(
            LearningTopic(
                id="horizontal_cg",
                title="Horizontal CG (CG_x, CG_y)",
                simple=(
                    "These tell you if the ship leans front/back (CG_x) or left/right "
                    "(CG_y). Values near 0 mean well balanced."
                ),
                technical=(
                    "Computed from weight moments around the geometric center, not from "
                    "raw side weights, so distance from the centerline matters. `W` is the "
                    "total loaded weight and `x_i, y_i` are the normalized slot coordinates."
                ),
                formula=r"CG_x = \frac{\sum_i w_i\, x_i}{W}, \qquad CG_y = \frac{\sum_i w_i\, y_i}{W}, \qquad W = \sum_i w_i",
            ),
            LearningTopic(
                id="vertical_cg",
                title="Why low CG_z is usually desirable",
                simple=(
                    "CG_z measures how high the weight sits. Keeping heavy containers low "
                    "(lower CG_z) generally makes the ship more stable."
                ),
                technical=(
                    "It is a normalized soft penalty with `z_i` in `[0, 1]`, not a full "
                    "naval-stability calculation (no metacentric height or hydrostatics)."
                ),
                formula=r"CG_z = \frac{\sum_i w_i\, z_i}{W}, \qquad z_i \in [0, 1]",
            ),
            LearningTopic(
                id="real_rehandling",
                title="What real rehandling means",
                simple=(
                    "Real rehandling counts the extra moves needed to dig out a container "
                    "that is buried under containers leaving at a later port."
                ),
                technical=(
                    "It is measured by simulating port-by-port unloading and counting "
                    "blocking moves. It is the recommended operational comparison metric "
                    "and differs from the MILP linear rehandling proxy."
                ),
            ),
            LearningTopic(
                id="common_metrics",
                title="Why compare with common metrics",
                simple=(
                    "Different algorithms score themselves differently inside. To compare "
                    "fairly, we always re-evaluate every plan with the same shared metrics."
                ),
                technical=(
                    "Each solver optimizes a different internal objective/proxy, so raw "
                    "objective values are not comparable. Final comparison relies on shared "
                    "metrics: feasibility, CG, CG_z, real rehandling, utilization, and "
                    "violations."
                ),
            ),
        ),
        table="metrics",
    )


def _algorithms_section() -> LearningSection:
    return LearningSection(
        id="algorithms",
        title="Algorithms",
        summary="Greedy, MILP, Genetic Algorithm, and Local Search.",
        topics=(
            LearningTopic(
                id="greedy",
                title="Greedy: fast baseline",
                simple=(
                    "Greedy places containers one at a time, each in the best slot "
                    "available at that moment. It is very fast but does not look ahead, so "
                    "it can miss better global plans."
                ),
                technical=(
                    "A constructive heuristic: it sorts containers by constraint priority "
                    "and weight, then assigns each to the best currently feasible slot by a "
                    "scoring function. An optional repair step fixes simple violations."
                ),
            ),
            LearningTopic(
                id="milp",
                title="MILP: exact reference",
                simple=(
                    "MILP searches mathematically for the best plan it can prove is best, "
                    "for its own definition of 'best'. It is reliable on small ships but "
                    "becomes slow as the problem grows."
                ),
                technical=(
                    "A Mixed Integer Linear Program over `x[c, p]` binaries enforcing the "
                    "hard constraints and minimizing a weighted linear objective. It is the "
                    "exact reference for small instances and can recover feasible "
                    "incumbents under a time limit."
                ),
            ),
            LearningTopic(
                id="genetic_algorithm",
                title="Genetic Algorithm: scalable search",
                simple=(
                    "The Genetic Algorithm evolves a population of candidate plans using "
                    "selection, crossover, and mutation. It scales to larger ships where "
                    "MILP would be too slow."
                ),
                technical=(
                    "Chromosomes encode complete assignments. Fitness uses the shared "
                    "metrics (horizontal CG, CG_z, real rehandling) plus a penalty for "
                    "violations. Results are reproducible when a random seed is fixed."
                ),
            ),
            LearningTopic(
                id="local_search",
                title="Local Search: swap-based polishing",
                simple=(
                    "After Greedy or GA, Local Search tries swapping pairs of containers to "
                    "improve balance and reduce rehandling, without ever breaking the hard "
                    "rules."
                ),
                technical=(
                    "A deterministic pairwise-swap neighborhood. Each candidate is "
                    "re-evaluated with the common metrics; swaps that introduce structural "
                    "violations are rejected, and only score-improving moves are accepted. "
                    "It is skipped if the starting plan is structurally infeasible."
                ),
            ),
        ),
        table="algorithms",
    )


def _solver_settings_section() -> LearningSection:
    return LearningSection(
        id="solver_settings",
        title="Solver settings and tradeoffs",
        summary="How to interpret weights, solver status, search limits, and swaps.",
        topics=(
            LearningTopic(
                id="objective_weights_as_priorities",
                title="Objective weights are priorities",
                simple=(
                    "Changing an objective weight is like telling the solver what you "
                    "care about more: balance, low vertical weight, or fewer unloading "
                    "moves. It does not make one metric universally more correct; it "
                    "changes the tradeoff the solver is asked to prefer."
                ),
                technical=(
                    "For MILP, weights multiply objective components inside one linear "
                    "formulation. Larger weights increase the penalty for that component "
                    "relative to the others, while hard constraints still define which "
                    "plans are allowed. Greedy, GA, and Local Search are still compared "
                    "through the shared final metrics."
                ),
            ),
            LearningTopic(
                id="solver_status_meaning",
                title="Solver status and optimality",
                simple=(
                    "`Optimal` means the solver proved the best plan for its own model. "
                    "`Feasible` means the returned plan is usable but not necessarily "
                    "proven best. `Infeasible` means the solver could not satisfy the "
                    "rules for that scenario."
                ),
                technical=(
                    "MILP can certify OPTIMAL or INFEASIBLE, and may also return a "
                    "time-limited feasible incumbent. Heuristics usually report feasible "
                    "or infeasible evaluated plans, but they do not provide a mathematical "
                    "optimality proof."
                ),
            ),
            LearningTopic(
                id="local_search_limits",
                title="Local Search limits",
                simple=(
                    "Local Search tries small swaps after Greedy or GA. More iterations "
                    "give it more chances to improve, but once good easy swaps are gone, "
                    "extra attempts often add runtime without much benefit."
                ),
                technical=(
                    "The swap search stops by maximum evaluated swaps, rounds without "
                    "improvement, or an optional time limit. It keeps the best accepted "
                    "solution found and rejects candidates that introduce structural "
                    "constraint violations."
                ),
            ),
            LearningTopic(
                id="simple_swap_example",
                title="A small swap example",
                simple=(
                    "If a heavy container is far to port and a lighter one is far to "
                    "starboard, swapping them can move CG_y closer to zero. If that swap "
                    "also keeps reefer, stacking, and dangerous-cargo rules valid, Local "
                    "Search may accept it."
                ),
                technical=(
                    "A candidate swap exchanges two assigned slot positions, then the "
                    "common metrics engine recomputes CG_x, CG_y, CG_z, violations, and "
                    "real rehandling. The move is accepted only when its score improves "
                    "and structural feasibility remains intact."
                ),
            ),
        ),
        table="settings",
    )


def _assumptions_section() -> LearningSection:
    return LearningSection(
        id="assumptions",
        title="Academic assumptions",
        summary="Simplifications and limitations that bound the scope.",
        topics=(
            LearningTopic(
                id="discrete_model",
                title="A simplified discrete model",
                simple=(
                    "The ship is a tidy rectangular grid and each container fills exactly "
                    "one box. Real ships are messier; this keeps the model explainable and "
                    "testable."
                ),
                technical=(
                    "The discrete `(bay, row, tier)` grid supports clean combinatorial "
                    "constraints and normalized coordinates for moment calculations, at the "
                    "cost of real hull geometry and mixed container sizes."
                ),
            ),
            LearningTopic(
                id="rehandling_real_vs_proxy",
                title="Real rehandling vs MILP proxy",
                simple=(
                    "Greedy and GA measure rehandling by actually simulating unloading. "
                    "MILP instead uses a simpler linear estimate so the math stays solvable."
                ),
                technical=(
                    "The MILP linear proxy penalizes early-destination containers placed "
                    "deep in stacks. It is normalized separately from the real rehandling "
                    "count and the two are not the same unit, so they are reported "
                    "separately."
                ),
            ),
            LearningTopic(
                id="no_full_naval_stability",
                title="No full naval stability or advanced rules",
                simple=(
                    "This is not certified ship software. It does not compute real "
                    "stability physics, and it leaves out advanced rules like stack weight "
                    "limits and full dangerous-goods regulations."
                ),
                technical=(
                    "Excluded: metacentric height, hydrostatics, ballast, crane scheduling, "
                    "lashing forces, stack-weight limits, and full IMO segregation. CG_z is "
                    "only a normalized proxy and Flammable/Oxidizer use a bay-distance rule."
                ),
            ),
        ),
        table="assumptions",
    )


def _interpretation_section() -> LearningSection:
    return LearningSection(
        id="interpretation",
        title="How to interpret results",
        summary="What to look at first and how to read the dashboard.",
        topics=(
            LearningTopic(
                id="what_first",
                title="What to look at first",
                simple=(
                    "Start with feasibility. If a plan is not feasible, look at the "
                    "violation explanations before anything else. Only then compare CG, "
                    "rehandling, and utilization."
                ),
                technical=(
                    "Check `operationally_feasible` (structural validity plus CG within "
                    "tolerance). Then read CG_x/CG_y vs the tolerance box, real rehandling, "
                    "and utilization. Use the shared comparison table across algorithms."
                ),
            ),
            LearningTopic(
                id="why_converge",
                title="Why two algorithms can give the same plan",
                simple=(
                    "On small, tightly constrained instances there may be only a few good "
                    "plans, so different algorithms can land on the same one."
                ),
                technical=(
                    "When the feasible region is small or strongly constrained, distinct "
                    "search strategies can converge to the same or equivalent assignments, "
                    "especially after local search polishing."
                ),
            ),
            LearningTopic(
                id="milp_not_dominant",
                title="Why MILP can be optimal yet not dominate",
                simple=(
                    "MILP is optimal for its own scoring, which uses an approximate "
                    "rehandling estimate. So another algorithm might still look better on "
                    "the real rehandling metric."
                ),
                technical=(
                    "MILP optimality is relative to its linear objective and rehandling "
                    "proxy. Since final metrics use real rehandling and equal objective "
                    "weights are not enforced across solvers, an optimal MILP plan may not "
                    "be best on every dashboard metric."
                ),
            ),
            LearningTopic(
                id="reading_dashboard",
                title="Reading feasibility, CG, rehandling, and violations",
                simple=(
                    "Green feasibility means a valid, balanced plan. CG near the center is "
                    "good. Lower rehandling is better. Any non-zero violation count points "
                    "to a rule that was broken."
                ),
                technical=(
                    "Violations break down into unassigned, duplicate-slot, reefer, "
                    "stack-continuity, and incompatible-cargo counts. A horizontal CG breach "
                    "is shown as a warning because a structurally valid plan can still be "
                    "deliberately unbalanced."
                ),
            ),
        ),
    )


def get_learning_sections() -> tuple[LearningSection, ...]:
    """Return the ordered academic learning sections for the Streamlit guide.

    Each section bundles a short summary, two-level topics (plain language and
    technical), and an optional compact reference table key.
    """
    return (
        _problem_overview_section(),
        _data_model_section(),
        _constraints_section(),
        _metrics_section(),
        _algorithms_section(),
        _solver_settings_section(),
        _assumptions_section(),
        _interpretation_section(),
    )


# Maps a section ``table`` key to the function that builds its rows. The UI uses
# this so it does not need to know each table's shape, and tests can assert the
# mapping stays in sync with the sections.
LEARNING_TABLES = {
    "constraints": constraint_explanation_rows,
    "metrics": metric_explanation_rows,
    "algorithms": algorithm_explanation_rows,
    "settings": setting_explanation_rows,
    "assumptions": assumption_rows,
}

# Maps a section ``diagram`` key to its inline SVG builder. The UI renders the
# returned markup directly, so it never branches on a section ``id`` to pick a
# figure. Tests assert this stays in sync with the sections that declare one.
LEARNING_DIAGRAMS = {
    "grid": bay_row_tier_svg,
    "stack_continuity": stack_continuity_svg,
}

# Stable keys for the post-topic ``example`` visuals. The example itself is a
# plotly figure the Streamlit layer builds (it is not Streamlit-free), so only
# the key is registered here for validation and to keep the UI off section ids.
LEARNING_EXAMPLE_KEYS = frozenset({"cg"})
