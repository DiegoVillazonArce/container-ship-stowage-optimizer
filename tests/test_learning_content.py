"""Tests for the Phase 14 structured academic learning content.

These cover only the Streamlit-free content helpers in
``app/learning_content.py``. The Streamlit UI in ``app/main.py`` is a thin layer
over these structures and is not unit-tested here.
"""

import learning_content as content

from stowage_optimizer.core.metrics import StowageMetrics
from stowage_optimizer.solvers import GeneticSolver, GreedySolver, MILPSolver


# -- Sections ----------------------------------------------------------------


def test_get_learning_sections_is_not_empty() -> None:
    sections = content.get_learning_sections()

    assert sections
    for section in sections:
        assert section.id
        assert section.title
        assert section.summary
        assert section.topics  # every section has at least one topic


def test_expected_sections_are_present() -> None:
    section_ids = {section.id for section in content.get_learning_sections()}

    expected = {
        "problem_overview",
        "data_model",
        "constraints",
        "metrics",
        "algorithms",
        "solver_settings",
        "assumptions",
        "interpretation",
    }
    assert expected <= section_ids


def test_section_ids_are_unique() -> None:
    section_ids = [section.id for section in content.get_learning_sections()]

    assert len(section_ids) == len(set(section_ids))


def test_topic_ids_are_globally_unique() -> None:
    topic_ids = [
        topic.id
        for section in content.get_learning_sections()
        for topic in section.topics
    ]

    assert topic_ids  # there is explanatory content to read
    assert len(topic_ids) == len(set(topic_ids))


def test_every_topic_has_both_reading_levels() -> None:
    for section in content.get_learning_sections():
        for topic in section.topics:
            assert topic.title
            assert topic.simple.strip(), f"{topic.id} is missing plain-language text"
            assert topic.technical.strip(), f"{topic.id} is missing technical text"


def test_topics_with_a_formula_expose_nonempty_latex() -> None:
    topics_with_formula = [
        topic
        for section in content.get_learning_sections()
        for topic in section.topics
        if topic.formula
    ]

    # The math-heavy topics expose a LaTeX centerpiece formula; when present it
    # must be non-empty and accompany (not replace) the technical prose.
    assert topics_with_formula
    for topic in topics_with_formula:
        assert topic.formula.strip(), f"{topic.id} has a blank formula"
        assert topic.technical.strip(), f"{topic.id} has a formula but no technical text"


# -- Constraint table --------------------------------------------------------


def test_constraint_rows_cover_main_constraints() -> None:
    rows = content.constraint_explanation_rows()
    names = " ".join(row["constraint"].lower() for row in rows)

    for needle in (
        "unique assignment",
        "slot capacity",
        "stack continuity",
        "reefer",
        "incompatible cargo",
        "horizontal cg",
    ):
        assert needle in names

    for row in rows:
        assert row["plain_language"].strip()
        assert row["technical"].strip()
        assert row["feasibility"].strip()


def test_constraint_rows_have_unique_names() -> None:
    names = [row["constraint"] for row in content.constraint_explanation_rows()]

    assert len(names) == len(set(names))


def test_constraint_symbol_legend_defines_table_shorthands() -> None:
    legend = content.constraint_symbol_legend()

    assert legend
    for row in legend:
        assert row["symbol"].strip()
        assert row["meaning"].strip()

    symbols = " ".join(row["symbol"].lower() for row in legend)
    # The shorthand symbols used in the constraint table must be explained.
    assert "tau_lon" in symbols
    assert "tau_lat" in symbols
    assert "d_min" in symbols


# -- Metric table ------------------------------------------------------------


def test_metric_rows_cover_required_metrics() -> None:
    rows = content.metric_explanation_rows()
    names = {row["metric"] for row in rows}

    assert {"CG_x", "CG_y", "CG_z"} <= names
    assert any("utilization" in name.lower() for name in names)
    assert any("rehandling" in name.lower() for name in names)


def test_metric_rows_have_unique_names() -> None:
    names = [row["metric"] for row in content.metric_explanation_rows()]

    assert len(names) == len(set(names))


# -- Algorithm table ---------------------------------------------------------


def test_algorithm_rows_cover_all_solvers() -> None:
    rows = content.algorithm_explanation_rows()
    names = {row["algorithm"] for row in rows}

    assert {"Greedy", "MILP", "Genetic Algorithm", "Local Search"} <= names

    for row in rows:
        assert row["role"].strip()
        assert row["strengths"].strip()
        assert row["limitations"].strip()


def test_algorithm_rows_have_unique_names() -> None:
    names = [row["algorithm"] for row in content.algorithm_explanation_rows()]

    assert len(names) == len(set(names))


# -- Solver settings table ---------------------------------------------------


def test_setting_rows_cover_practical_controls() -> None:
    rows = content.setting_explanation_rows()
    text = " ".join(
        f"{row['setting']} {row['plain_language']} {row['technical']}".lower()
        for row in rows
    )

    for needle in ("objective weights", "milp time limit", "ga", "local search"):
        assert needle in text

    for row in rows:
        assert row["setting"].strip()
        assert row["plain_language"].strip()
        assert row["technical"].strip()


def test_setting_rows_have_unique_names() -> None:
    names = [row["setting"] for row in content.setting_explanation_rows()]

    assert len(names) == len(set(names))


# -- Assumption table --------------------------------------------------------


def test_assumption_rows_are_present_and_honest() -> None:
    rows = content.assumption_rows()

    assert rows
    text = " ".join(
        f"{row['area']} {row['assumption']} {row['limitation']}".lower() for row in rows
    )
    # Key academic limitations from README/DESIGN must be acknowledged.
    assert "rehandling" in text
    assert "stability" in text or "metacentric" in text
    assert any(row["limitation"].strip() for row in rows)


# -- Table wiring ------------------------------------------------------------


def test_learning_tables_keys_match_section_table_references() -> None:
    referenced = {
        section.table
        for section in content.get_learning_sections()
        if section.table is not None
    }

    # Every section table reference resolves to a builder, and every builder is
    # actually referenced by a section.
    assert referenced <= set(content.LEARNING_TABLES)
    assert set(content.LEARNING_TABLES) == referenced


def test_learning_table_builders_return_rows() -> None:
    for builder in content.LEARNING_TABLES.values():
        rows = builder()
        assert rows
        assert all(isinstance(row, dict) and row for row in rows)


def test_section_diagram_keys_resolve_to_builders() -> None:
    declared = {
        section.diagram
        for section in content.get_learning_sections()
        if section.diagram is not None
    }

    # Every diagram a section declares resolves to a builder, and every builder
    # is actually used by some section (no dead diagram keys). This is what keeps
    # the UI from having to branch on a section id to pick a figure.
    assert declared <= set(content.LEARNING_DIAGRAMS)
    assert set(content.LEARNING_DIAGRAMS) == declared


def test_section_diagram_builders_are_well_formed_svg() -> None:
    for builder in content.LEARNING_DIAGRAMS.values():
        svg = builder()
        assert "<svg" in svg and "</svg>" in svg


def test_section_example_keys_are_known() -> None:
    declared = {
        section.example
        for section in content.get_learning_sections()
        if section.example is not None
    }

    # Example keys are validated against the registered set so a section cannot
    # silently request a visual the UI does not know how to render.
    assert declared <= content.LEARNING_EXAMPLE_KEYS
    assert content.LEARNING_EXAMPLE_KEYS == declared


# -- Anti-drift guards against the codebase ----------------------------------
#
# The learning content is plain prose, so nothing stops it from drifting out of
# sync with the code it describes. These tests tie the load-bearing names the
# guide leans on back to the real solvers and metrics, so renaming a solver or a
# feasibility flag fails here instead of silently leaving the guide wrong.


def _all_content_text() -> str:
    """Concatenate every rendered string in the guide for substring checks."""
    parts: list[str] = []
    for section in content.get_learning_sections():
        parts.append(section.summary)
        for topic in section.topics:
            parts.extend((topic.title, topic.simple, topic.technical, topic.formula))
    for builder in content.LEARNING_TABLES.values():
        for row in builder():
            parts.extend(row.values())
    return " ".join(parts)


def test_algorithm_table_covers_every_real_solver() -> None:
    table_text = " ".join(
        row["algorithm"].lower() for row in content.algorithm_explanation_rows()
    )

    # Every solver class that exists in the codebase must be described in the
    # guide. Adding or renaming a solver without updating the guide fails here.
    for solver in (GreedySolver, MILPSolver, GeneticSolver):
        assert solver.name.lower() in table_text, (
            f"{solver.__name__} (name={solver.name!r}) is not described in the "
            "learning algorithm table"
        )


def test_referenced_feasibility_flags_stay_in_sync_with_metrics() -> None:
    text = _all_content_text()

    # Identifiers the guide names explicitly; each must (a) still exist on
    # StowageMetrics and (b) actually appear in the guide. Part (a) fails if the
    # metric is renamed in code; part (b) fails if the guide stops referencing it
    # (a prompt to update this contract, not to silently diverge).
    referenced_metric_attrs = ("is_structurally_feasible", "operationally_feasible")
    for attr in referenced_metric_attrs:
        assert hasattr(StowageMetrics, attr), (
            f"learning content references metric attribute {attr!r} that no longer "
            "exists on StowageMetrics"
        )
        assert attr in text, (
            f"{attr!r} is expected in the learning guide but was not found; update "
            "referenced_metric_attrs if the guide intentionally stopped using it"
        )


# -- Inline diagrams ---------------------------------------------------------


def test_bay_row_tier_svg_is_well_formed() -> None:
    svg = content.bay_row_tier_svg()

    assert "<svg" in svg and "</svg>" in svg
    # Labels the three slot axes so the figure is self-explanatory.
    for axis in ("bay", "row", "tier"):
        assert axis in svg


def test_stack_continuity_svg_contrasts_valid_and_invalid() -> None:
    svg = content.stack_continuity_svg()

    assert "<svg" in svg and "</svg>" in svg
    assert "Invalid" in svg
    assert "Valid" in svg
