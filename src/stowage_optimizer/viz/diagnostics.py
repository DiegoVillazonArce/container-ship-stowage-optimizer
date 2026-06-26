"""Plotly figure builders for the Phase 12 visual diagnostics layer.

These helpers turn already-prepared diagnostic data into compact figures:

- :func:`build_bay_row_balance_figure` renders a bay-row weight heatmap so weight
  distribution issues are visible at a glance.
- :func:`build_cg_diagnostic_figure` marks the computed center of gravity against
  the ideal point ``(0, 0)`` and the configured tolerance box.

They are intentionally independent of the Streamlit app layer: the balance map
consumes the plain ``(bay, row)`` aggregate rows produced by the app helper, and
the center-of-gravity figure consumes primitive values. This keeps the
visualization package free of any dependency on ``app``.
"""

from __future__ import annotations

from typing import Mapping, Sequence

import plotly.graph_objects as go

from stowage_optimizer.core.problem import ProblemInstance

_BALANCE_COLORSCALE = "YlOrRd"
_WITHIN_TOLERANCE_COLOR = "#16a34a"
_OUT_OF_TOLERANCE_COLOR = "#dc2626"
_IDEAL_COLOR = "#2563eb"
_TOLERANCE_FILL = "rgba(37, 99, 235, 0.08)"
_TOLERANCE_LINE = "rgba(37, 99, 235, 0.55)"


def build_bay_row_balance_figure(
    instance: ProblemInstance,
    balance_rows: Sequence[Mapping[str, object]],
    *,
    title: str | None = None,
    weight_range: tuple[float, float] | None = None,
) -> go.Figure:
    """Build a bay-row aggregated-weight heatmap.

    ``balance_rows`` is the structured output of the app's
    ``bay_row_balance_rows`` helper: one mapping per ``(bay, row)`` stack with
    ``total_weight`` and ``container_count``. Bays are placed on the x-axis and
    rows on the y-axis; color intensity encodes aggregated weight, and each cell
    shows its weight with the container count available on hover. Pass
    ``weight_range`` to reuse the same color scale across several figures.
    """
    bays = instance.ship.bays
    rows = instance.ship.rows

    weight_grid = [[0.0] * bays for _ in range(rows)]
    count_grid = [[0] * bays for _ in range(rows)]
    for cell in balance_rows:
        bay = int(cell["bay"])
        row = int(cell["row"])
        if not (1 <= bay <= bays and 1 <= row <= rows):
            continue
        weight_grid[row - 1][bay - 1] = float(cell["total_weight"])
        count_grid[row - 1][bay - 1] = int(cell["container_count"])

    heatmap_args = {
        "x": list(range(1, bays + 1)),
        "y": list(range(1, rows + 1)),
        "z": weight_grid,
        "customdata": count_grid,
        "colorscale": _BALANCE_COLORSCALE,
        "colorbar": {"title": "Weight (t)"},
        "hovertemplate": (
            "Bay %{x}<br>Row %{y}<br>"
            "Weight: %{z:.1f} t<br>"
            "Containers: %{customdata}<extra></extra>"
        ),
        "text": weight_grid,
        "texttemplate": "%{text:.0f}",
        "xgap": 2,
        "ygap": 2,
    }
    if weight_range is not None:
        zmin, zmax = _valid_weight_range(weight_range)
        heatmap_args["zmin"] = zmin
        heatmap_args["zmax"] = zmax

    figure = go.Figure(
        data=go.Heatmap(**heatmap_args)
    )
    figure.update_layout(
        title={"text": title or "Bay-row balance map", "x": 0.5, "xanchor": "center"},
        height=360,
        margin={"l": 0, "r": 0, "t": 60, "b": 0},
        xaxis={
            "title": "Bay (longitudinal)",
            "tickmode": "linear",
            "dtick": 1,
            "constrain": "domain",
        },
        yaxis={
            "title": "Row (lateral)",
            "tickmode": "linear",
            "dtick": 1,
            "scaleanchor": "x",
            "constrain": "domain",
        },
    )
    return figure


def _valid_weight_range(weight_range: tuple[float, float]) -> tuple[float, float]:
    zmin, zmax = weight_range
    if zmax <= zmin:
        zmax = zmin + 1.0
    return zmin, zmax


def build_cg_diagnostic_figure(
    cg_x: float,
    cg_y: float,
    tolerance_lon: float,
    tolerance_lat: float,
    *,
    ideal_x: float = 0.0,
    ideal_y: float = 0.0,
    title: str | None = None,
) -> go.Figure:
    """Mark the computed center of gravity against the ideal point and tolerances.

    The longitudinal CG (``cg_x``) is on the x-axis and the lateral CG (``cg_y``)
    on the y-axis, matching the normalized ``[-1, 1]`` coordinate convention. A
    shaded rectangle shows the configured tolerance box around the ideal point
    ``(ideal_x, ideal_y)``; the actual CG marker is green when both axes are
    within tolerance and red otherwise.
    """
    within_tolerance = (
        abs(cg_x - ideal_x) <= tolerance_lon and abs(cg_y - ideal_y) <= tolerance_lat
    )
    marker_color = _WITHIN_TOLERANCE_COLOR if within_tolerance else _OUT_OF_TOLERANCE_COLOR

    figure = go.Figure()
    figure.add_shape(
        type="rect",
        x0=ideal_x - tolerance_lon,
        x1=ideal_x + tolerance_lon,
        y0=ideal_y - tolerance_lat,
        y1=ideal_y + tolerance_lat,
        line={"color": _TOLERANCE_LINE, "width": 1},
        fillcolor=_TOLERANCE_FILL,
        layer="below",
    )
    figure.add_trace(
        go.Scatter(
            x=[ideal_x],
            y=[ideal_y],
            mode="markers",
            name="Ideal (0, 0)",
            marker={"color": _IDEAL_COLOR, "size": 12, "symbol": "x"},
            hovertemplate="Ideal CG (0, 0)<extra></extra>",
        )
    )
    figure.add_trace(
        go.Scatter(
            x=[cg_x],
            y=[cg_y],
            mode="markers",
            name="Computed CG",
            marker={
                "color": marker_color,
                "size": 16,
                "symbol": "circle",
                "line": {"color": "#111827", "width": 1},
            },
            hovertemplate=(
                f"Computed CG<br>CG x: {cg_x:.3f}<br>CG y: {cg_y:.3f}<extra></extra>"
            ),
        )
    )

    axis_limit = max(1.0, abs(cg_x) + 0.05, abs(cg_y) + 0.05)
    figure.update_layout(
        title={
            "text": title or "Center-of-gravity diagnostic",
            "x": 0.5,
            "xanchor": "center",
        },
        height=360,
        margin={"l": 0, "r": 0, "t": 60, "b": 0},
        xaxis={
            "title": "CG x (longitudinal)",
            "range": [-axis_limit, axis_limit],
            "zeroline": True,
        },
        yaxis={
            "title": "CG y (lateral)",
            "range": [-axis_limit, axis_limit],
            "zeroline": True,
            "scaleanchor": "x",
        },
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.0, "x": 0.0},
    )
    return figure
