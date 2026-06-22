import plotly.graph_objects as go
import pytest

from stowage_optimizer.core import (
    Container,
    ContainerType,
    ProblemInstance,
    Route,
    Ship,
    StowageSolution,
)
from stowage_optimizer.viz import build_stowage_figure


def _visual_instance() -> ProblemInstance:
    return ProblemInstance(
        ship=Ship(bays=2, rows=2, tiers=2, reefer_slots=((1, 1, 1),)),
        route=Route(("Panama", "Brazil")),
        containers=(
            Container("NORM", 10.0, "Panama", ContainerType.NORMAL),
            Container("REEF", 12.5, "Brazil", ContainerType.REEFER),
            Container("FLAM", 8.0, "Brazil", ContainerType.FLAMMABLE),
            Container("OXID", 9.0, "Panama", ContainerType.OXIDIZER),
        ),
    )


def _solution() -> StowageSolution:
    return StowageSolution.from_mapping(
        {
            "NORM": (1, 1, 1),
            "REEF": (1, 1, 2),
            "FLAM": (2, 1, 1),
            "OXID": (2, 2, 1),
        }
    )


def _container_customdata(figure: go.Figure) -> list[list[object]]:
    rows: list[list[object]] = []
    for trace in figure.data:
        customdata = getattr(trace, "customdata", None)
        if customdata is None:
            continue
        rows.extend(list(row) for row in customdata)
    return rows


def test_build_stowage_figure_returns_plotly_figure() -> None:
    figure = build_stowage_figure(_visual_instance(), _solution())

    assert isinstance(figure, go.Figure)
    assert figure.layout.scene.xaxis.title.text == "Bay"
    assert figure.layout.scene.yaxis.title.text == "Row"
    assert figure.layout.scene.zaxis.title.text == "Tier"


def test_build_stowage_figure_handles_empty_solution() -> None:
    figure = build_stowage_figure(
        _visual_instance(),
        StowageSolution(()),
        title="Empty plan",
    )

    assert isinstance(figure, go.Figure)
    assert figure.layout.title.text == "Empty plan"
    assert _container_customdata(figure) == []


def test_build_stowage_figure_includes_container_hover_metadata() -> None:
    figure = build_stowage_figure(_visual_instance(), _solution())

    hover_templates = [
        trace.hovertemplate
        for trace in figure.data
        if getattr(trace, "hovertemplate", None)
    ]
    customdata = _container_customdata(figure)

    assert any("Weight" in template for template in hover_templates)
    assert any("Destination" in template for template in hover_templates)
    assert any(row[:7] == ["REEF", 12.5, "Brazil", "Reefer", 1, 1, 2] for row in customdata)


def test_build_stowage_figure_respects_highlighted_container_ids() -> None:
    figure = build_stowage_figure(
        _visual_instance(),
        _solution(),
        highlighted_container_ids=("REEF",),
    )

    highlighted_traces = [
        trace
        for trace in figure.data
        if trace.name == "Highlighted / rehandled" and trace.customdata is not None
    ]

    assert len(highlighted_traces) == 1
    highlighted_data = list(highlighted_traces[0].customdata)
    assert highlighted_data[0][0] == "REEF"
    assert highlighted_data[0][8] is True


def test_build_stowage_figure_can_color_by_cargo_type() -> None:
    figure = build_stowage_figure(
        _visual_instance(),
        _solution(),
        color_by="cargo_type",
    )

    trace_names = {trace.name for trace in figure.data}
    assert {"Normal", "Reefer", "Flammable", "Oxidizer"} <= trace_names


def test_build_stowage_figure_keeps_destination_legend_compact() -> None:
    figure = build_stowage_figure(
        _visual_instance(),
        _solution(),
        color_by="destination_port",
    )

    color_legend_names = {
        trace.name
        for trace in figure.data
        if trace.showlegend is True and trace.legendgroup == "legend-color"
    }
    shape_legend_names = {
        trace.name
        for trace in figure.data
        if trace.showlegend is True and trace.legendgroup == "legend-shape"
    }
    legend_group_titles = [
        trace.legendgrouptitle.text
        for trace in figure.data
        if trace.showlegend is True and trace.legendgrouptitle.text
    ]

    assert color_legend_names == {"Panama", "Brazil"}
    assert {"Normal", "Reefer", "Flammable", "Oxidizer"} <= shape_legend_names
    assert all("/" not in name for name in color_legend_names | shape_legend_names)
    assert "Color: destination port" in legend_group_titles
    assert "Shape" in legend_group_titles
    assert figure.layout.legend.orientation == "v"


def test_build_stowage_figure_uses_smaller_flammable_marker() -> None:
    figure = build_stowage_figure(_visual_instance(), _solution())

    flammable_trace = next(
        trace
        for trace in figure.data
        if trace.customdata is not None and trace.customdata[0][0] == "FLAM"
    )
    normal_trace = next(
        trace
        for trace in figure.data
        if trace.customdata is not None and trace.customdata[0][0] == "NORM"
    )

    assert flammable_trace.marker.symbol == "x"
    assert flammable_trace.marker.size < normal_trace.marker.size
    assert flammable_trace.marker.line.width < normal_trace.marker.line.width


def test_build_stowage_figure_rejects_unknown_color_mode() -> None:
    with pytest.raises(ValueError, match="color_by"):
        build_stowage_figure(_visual_instance(), _solution(), color_by="weight")
