"""Tests for the Phase 12 diagnostic figure builders in ``viz/diagnostics``."""

import plotly.graph_objects as go

from stowage_optimizer.core import ProblemInstance, Route, Ship
from stowage_optimizer.viz import build_bay_row_balance_figure, build_cg_diagnostic_figure

_WITHIN_TOLERANCE_COLOR = "#16a34a"
_OUT_OF_TOLERANCE_COLOR = "#dc2626"


def _instance() -> ProblemInstance:
    return ProblemInstance(
        ship=Ship(bays=2, rows=2, tiers=1),
        route=Route(("Panama",)),
        containers=(),
    )


def _balance_rows() -> list[dict[str, object]]:
    return [
        {"bay": 1, "row": 1, "total_weight": 10.0, "container_count": 1},
        {"bay": 1, "row": 2, "total_weight": 0.0, "container_count": 0},
        {"bay": 2, "row": 1, "total_weight": 5.0, "container_count": 2},
        {"bay": 2, "row": 2, "total_weight": 0.0, "container_count": 0},
    ]


def _cg_marker_color(figure: go.Figure) -> str:
    trace = next(trace for trace in figure.data if trace.name == "Computed CG")
    return trace.marker.color


def test_balance_figure_builds_weight_grid() -> None:
    figure = build_bay_row_balance_figure(_instance(), _balance_rows())

    assert isinstance(figure, go.Figure)
    heatmap = figure.data[0]
    assert isinstance(heatmap, go.Heatmap)
    # z is indexed [row - 1][bay - 1].
    assert heatmap.z[0][0] == 10.0
    assert heatmap.z[0][1] == 5.0
    assert heatmap.z[1][0] == 0.0
    assert heatmap.customdata[0][1] == 2
    assert figure.layout.xaxis.title.text == "Bay (longitudinal)"
    assert figure.layout.yaxis.title.text == "Row (lateral)"


def test_balance_figure_handles_empty_grid() -> None:
    rows = [
        {"bay": bay, "row": row, "total_weight": 0.0, "container_count": 0}
        for bay in (1, 2)
        for row in (1, 2)
    ]

    figure = build_bay_row_balance_figure(_instance(), rows, title="Empty")

    assert figure.layout.title.text == "Empty"
    assert all(value == 0.0 for line in figure.data[0].z for value in line)


def test_balance_figure_can_use_shared_weight_range() -> None:
    figure = build_bay_row_balance_figure(
        _instance(),
        _balance_rows(),
        weight_range=(0.0, 120.0),
    )

    heatmap = figure.data[0]

    assert heatmap.zmin == 0.0
    assert heatmap.zmax == 120.0


def test_cg_figure_marks_within_tolerance_green() -> None:
    figure = build_cg_diagnostic_figure(0.1, -0.1, 0.25, 0.25)

    assert isinstance(figure, go.Figure)
    assert _cg_marker_color(figure) == _WITHIN_TOLERANCE_COLOR
    assert figure.layout.xaxis.title.text == "CG x (longitudinal)"
    assert figure.layout.yaxis.title.text == "CG y (lateral)"
    # The tolerance box is drawn as a rectangle shape.
    assert any(shape.type == "rect" for shape in figure.layout.shapes)


def test_cg_figure_marks_out_of_tolerance_red() -> None:
    figure = build_cg_diagnostic_figure(0.9, 0.0, 0.25, 0.25)

    assert _cg_marker_color(figure) == _OUT_OF_TOLERANCE_COLOR
    # The axis range expands to keep the out-of-range CG marker visible.
    assert figure.layout.xaxis.range[1] >= 0.9
