"""Plotly 3D visualization helpers for stowage assignments."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Literal

import plotly.graph_objects as go

from stowage_optimizer.core.container import Container, ContainerType
from stowage_optimizer.core.problem import ProblemInstance
from stowage_optimizer.core.ship import Slot
from stowage_optimizer.core.solution import StowageSolution

ColorBy = Literal["destination_port", "cargo_type"]

_PALETTE: tuple[str, ...] = (
    "#2563eb",
    "#16a34a",
    "#f97316",
    "#9333ea",
    "#dc2626",
    "#0891b2",
    "#ca8a04",
    "#4f46e5",
    "#be123c",
    "#15803d",
)

_TYPE_SYMBOLS: dict[str, str] = {
    ContainerType.NORMAL.value: "square",
    ContainerType.REEFER.value: "diamond",
    ContainerType.FLAMMABLE.value: "x",
    ContainerType.OXIDIZER.value: "cross",
}

_TYPE_LINE_COLORS: dict[str, str] = {
    ContainerType.NORMAL.value: "#374151",
    ContainerType.REEFER.value: "#0284c7",
    ContainerType.FLAMMABLE.value: "#b91c1c",
    ContainerType.OXIDIZER.value: "#d97706",
}

_TYPE_MARKER_SIZES: dict[str, int] = {
    ContainerType.NORMAL.value: 8,
    ContainerType.REEFER.value: 8,
    ContainerType.FLAMMABLE.value: 6,
    ContainerType.OXIDIZER.value: 8,
}

_TYPE_LINE_WIDTHS: dict[str, int] = {
    ContainerType.NORMAL.value: 2,
    ContainerType.REEFER.value: 2,
    ContainerType.FLAMMABLE.value: 1,
    ContainerType.OXIDIZER.value: 2,
}

_SHAPE_LEGEND_COLOR = "#9ca3af"
_SHAPE_LEGEND_LINE_COLOR = "#e5e7eb"

_HOVER_TEMPLATE = (
    "<b>%{customdata[0]}</b><br>"
    "Weight: %{customdata[1]:.1f} t<br>"
    "Destination: %{customdata[2]}<br>"
    "Type: %{customdata[3]}<br>"
    "Bay: %{customdata[4]}<br>"
    "Row: %{customdata[5]}<br>"
    "Tier: %{customdata[6]}<br>"
    "Flags: %{customdata[7]}"
    "<extra></extra>"
)


@dataclass(frozen=True, slots=True)
class _VisualContainer:
    container: Container
    slot: Slot
    color_group: str
    color: str
    highlighted: bool

    @property
    def cargo_type(self) -> str:
        return str(self.container.type)

    @property
    def symbol(self) -> str:
        return _TYPE_SYMBOLS.get(self.cargo_type, "circle")

    @property
    def line_color(self) -> str:
        return _TYPE_LINE_COLORS.get(self.cargo_type, "#374151")

    @property
    def marker_size(self) -> int:
        return _TYPE_MARKER_SIZES.get(self.cargo_type, 8)

    @property
    def line_width(self) -> int:
        return _TYPE_LINE_WIDTHS.get(self.cargo_type, 2)

    @property
    def flags(self) -> str:
        flags: list[str] = []
        if self.container.is_reefer:
            flags.append("reefer")
        if self.container.type == ContainerType.FLAMMABLE:
            flags.append("flammable")
        if self.container.type == ContainerType.OXIDIZER:
            flags.append("oxidizer")
        if self.highlighted:
            flags.append("highlighted")
        return ", ".join(flags) if flags else "none"

    @property
    def customdata(self) -> list[object]:
        return [
            self.container.id,
            self.container.weight,
            self.container.destination_port,
            self.cargo_type,
            self.slot.bay,
            self.slot.row,
            self.slot.tier,
            self.flags,
            # Kept as structured metadata for tests and overlay checks; the
            # hover text already exposes this state through ``flags``.
            self.highlighted,
        ]


def build_stowage_figure(
    instance: ProblemInstance,
    solution: StowageSolution,
    *,
    color_by: str = "destination_port",
    highlighted_container_ids: Iterable[str] = (),
    title: str | None = None,
) -> go.Figure:
    """Build a Plotly 3D figure for a stowage solution.

    Containers are plotted at their discrete ``(bay, row, tier)`` positions.
    Color can represent destination port or cargo type, while marker symbols
    distinguish reefers and simplified dangerous cargo classes. Highlighted
    containers are overlaid with larger open markers, which is useful for
    showing rehandled containers in the unloading simulation.
    """
    normalized_color_by = _normalize_color_by(color_by)
    highlighted_ids = {
        str(container_id).strip()
        for container_id in highlighted_container_ids
        if str(container_id).strip()
    }
    containers = _resolve_visual_containers(
        instance,
        solution,
        color_by=normalized_color_by,
        highlighted_container_ids=highlighted_ids,
    )

    figure = go.Figure()
    _add_ship_outline(figure, instance)

    for group_key, group in _group_containers(containers).items():
        color_group, cargo_type = group_key
        figure.add_trace(
            go.Scatter3d(
                x=[item.slot.bay for item in group],
                y=[item.slot.row for item in group],
                z=[item.slot.tier for item in group],
                mode="markers",
                name=_trace_name(color_group, cargo_type, normalized_color_by),
                customdata=[item.customdata for item in group],
                hovertemplate=_HOVER_TEMPLATE,
                marker={
                    "color": group[0].color,
                    "line": {
                        "color": group[0].line_color,
                        "width": group[0].line_width,
                    },
                    "opacity": 0.88,
                    "size": group[0].marker_size,
                    "symbol": group[0].symbol,
                },
                legendgroup=color_group,
                showlegend=False,
            )
        )

    highlighted = [item for item in containers if item.highlighted]
    if highlighted:
        figure.add_trace(
            go.Scatter3d(
                x=[item.slot.bay for item in highlighted],
                y=[item.slot.row for item in highlighted],
                z=[item.slot.tier for item in highlighted],
                mode="markers",
                name="Highlighted / rehandled",
                customdata=[item.customdata for item in highlighted],
                hovertemplate=_HOVER_TEMPLATE,
                marker={
                    "color": "#111827",
                    "opacity": 1.0,
                    "size": 14,
                    "symbol": "circle-open",
                    "line": {"color": "#111827", "width": 5},
                },
                showlegend=False,
            )
        )

    _add_color_legend_entries(figure, instance, solution, normalized_color_by)
    _add_shape_legend_entries(figure, include_highlighted=bool(highlighted))

    figure.update_layout(
        title={"text": title or "3D stowage plan", "x": 0.42, "xanchor": "center"},
        height=620,
        margin={"l": 0, "r": 260, "t": 70, "b": 24},
        legend={
            "orientation": "v",
            "yanchor": "top",
            "y": 0.98,
            "xanchor": "left",
            "x": 1.02,
            "font": {"size": 11},
            "itemsizing": "constant",
            "tracegroupgap": 12,
        },
        scene={
            "domain": {"x": [0.0, 0.78], "y": [0.0, 1.0]},
            "xaxis": {
                "title": "Bay",
                "tickmode": "linear",
                "dtick": 1,
                "range": [0.5, instance.ship.bays + 0.5],
            },
            "yaxis": {
                "title": "Row",
                "tickmode": "linear",
                "dtick": 1,
                "range": [0.5, instance.ship.rows + 0.5],
            },
            "zaxis": {
                "title": "Tier",
                "tickmode": "linear",
                "dtick": 1,
                "range": [0.5, instance.ship.tiers + 0.5],
            },
            "aspectmode": "data",
            "camera": {"eye": {"x": 1.6, "y": -1.8, "z": 1.25}},
        },
    )
    return figure


def _normalize_color_by(color_by: str) -> ColorBy:
    normalized = color_by.strip().lower().replace(" ", "_")
    if normalized in {"destination", "destination_port", "port"}:
        return "destination_port"
    if normalized in {"cargo", "cargo_type", "container_type", "type"}:
        return "cargo_type"
    raise ValueError(
        "color_by must be 'destination_port' or 'cargo_type' "
        f"(got {color_by!r})."
    )


def _resolve_visual_containers(
    instance: ProblemInstance,
    solution: StowageSolution,
    *,
    color_by: ColorBy,
    highlighted_container_ids: set[str],
) -> tuple[_VisualContainer, ...]:
    containers_by_id = {container.id: container for container in instance.containers}
    category_colors = _category_colors(instance, solution, color_by=color_by)

    visual_containers: list[_VisualContainer] = []
    for assignment in solution.assignments:
        container = containers_by_id.get(assignment.container_id)
        if container is None:
            raise ValueError(
                f"Solution references unknown container ID: {assignment.container_id}."
            )
        bay, row, tier = assignment.slot_position
        slot = instance.ship.get_slot(bay, row, tier)
        color_group = _category_value(container, color_by)
        visual_containers.append(
            _VisualContainer(
                container=container,
                slot=slot,
                color_group=color_group,
                color=category_colors[color_group],
                highlighted=container.id in highlighted_container_ids,
            )
        )

    return tuple(
        sorted(
            visual_containers,
            key=lambda item: (item.slot.bay, item.slot.row, item.slot.tier, item.container.id),
        )
    )


def _category_colors(
    instance: ProblemInstance,
    solution: StowageSolution,
    *,
    color_by: ColorBy,
) -> dict[str, str]:
    containers_by_id = {container.id: container for container in instance.containers}
    assigned_containers = [
        containers_by_id[assignment.container_id]
        for assignment in solution.assignments
        if assignment.container_id in containers_by_id
    ]

    if color_by == "destination_port":
        categories = list(instance.route.ports)
    else:
        categories = [container_type.value for container_type in ContainerType]

    for container in assigned_containers:
        value = _category_value(container, color_by)
        if value not in categories:
            categories.append(value)

    return {
        category: _PALETTE[index % len(_PALETTE)]
        for index, category in enumerate(categories)
    }


def _category_value(container: Container, color_by: ColorBy) -> str:
    if color_by == "destination_port":
        return container.destination_port
    return str(container.type)


def _group_containers(
    containers: tuple[_VisualContainer, ...]
) -> dict[tuple[str, str], list[_VisualContainer]]:
    groups: dict[tuple[str, str], list[_VisualContainer]] = {}
    for container in containers:
        groups.setdefault((container.color_group, container.cargo_type), []).append(container)
    return groups


def _trace_name(color_group: str, cargo_type: str, color_by: ColorBy) -> str:
    if color_by == "cargo_type":
        return cargo_type
    return color_group


def _legend_color_title(color_by: ColorBy) -> str:
    if color_by == "cargo_type":
        return "Color: cargo type"
    return "Color: destination port"


def _add_color_legend_entries(
    figure: go.Figure,
    instance: ProblemInstance,
    solution: StowageSolution,
    color_by: ColorBy,
) -> None:
    for index, (label, color) in enumerate(
        _category_colors(instance, solution, color_by=color_by).items()
    ):
        figure.add_trace(
            go.Scatter3d(
                x=[None],
                y=[None],
                z=[None],
                mode="markers",
                name=label,
                marker={
                    "color": color,
                    "size": 8,
                    "symbol": "circle",
                    "line": {"color": color, "width": 2},
                },
                hoverinfo="skip",
                legendgroup="legend-color",
                legendgrouptitle_text=_legend_color_title(color_by)
                if index == 0
                else None,
                showlegend=True,
            )
        )


def _add_shape_legend_entries(
    figure: go.Figure,
    *,
    include_highlighted: bool,
) -> None:
    shape_entries = [
        (ContainerType.NORMAL.value, "Normal"),
        (ContainerType.REEFER.value, "Reefer"),
        (ContainerType.FLAMMABLE.value, "Flammable"),
        (ContainerType.OXIDIZER.value, "Oxidizer"),
    ]
    if include_highlighted:
        shape_entries.append(("Highlighted", "Highlighted / rehandled"))

    for index, (cargo_type, label) in enumerate(shape_entries):
        if cargo_type == "Highlighted":
            symbol = "circle-open"
            size = 12
            line_width = 4
        else:
            symbol = _TYPE_SYMBOLS[cargo_type]
            size = _TYPE_MARKER_SIZES[cargo_type]
            line_width = _TYPE_LINE_WIDTHS[cargo_type]

        figure.add_trace(
            go.Scatter3d(
                x=[None],
                y=[None],
                z=[None],
                mode="markers",
                name=label,
                marker={
                    "color": _SHAPE_LEGEND_COLOR,
                    "size": size,
                    "symbol": symbol,
                    "line": {
                        "color": _SHAPE_LEGEND_LINE_COLOR,
                        "width": line_width,
                    },
                },
                hoverinfo="skip",
                legendgroup="legend-shape",
                legendgrouptitle_text="Shape" if index == 0 else None,
                showlegend=True,
            )
        )


def _add_ship_outline(figure: go.Figure, instance: ProblemInstance) -> None:
    """Add a light bounding-box outline so empty solutions still have context."""
    min_bay, max_bay = 1, instance.ship.bays
    min_row, max_row = 1, instance.ship.rows
    min_tier, max_tier = 1, instance.ship.tiers

    corners = {
        "a": (min_bay, min_row, min_tier),
        "b": (max_bay, min_row, min_tier),
        "c": (max_bay, max_row, min_tier),
        "d": (min_bay, max_row, min_tier),
        "e": (min_bay, min_row, max_tier),
        "f": (max_bay, min_row, max_tier),
        "g": (max_bay, max_row, max_tier),
        "h": (min_bay, max_row, max_tier),
    }
    edges = (
        ("a", "b"),
        ("b", "c"),
        ("c", "d"),
        ("d", "a"),
        ("e", "f"),
        ("f", "g"),
        ("g", "h"),
        ("h", "e"),
        ("a", "e"),
        ("b", "f"),
        ("c", "g"),
        ("d", "h"),
    )

    x: list[int | None] = []
    y: list[int | None] = []
    z: list[int | None] = []
    for start, end in edges:
        for point in (corners[start], corners[end]):
            bay, row, tier = point
            x.append(bay)
            y.append(row)
            z.append(tier)
        x.append(None)
        y.append(None)
        z.append(None)

    figure.add_trace(
        go.Scatter3d(
            x=x,
            y=y,
            z=z,
            mode="lines",
            name="Ship outline",
            line={"color": "rgba(75, 85, 99, 0.35)", "width": 3},
            hoverinfo="skip",
            showlegend=False,
        )
    )
