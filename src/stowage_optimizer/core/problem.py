"""Problem instance model."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from stowage_optimizer.core.container import Container
from stowage_optimizer.core.route import Route
from stowage_optimizer.core.ship import Ship


@dataclass(frozen=True, slots=True)
class ProblemInstance:
    """Complete input data required by future solvers."""

    ship: Ship
    containers: Sequence[Container]
    route: Route

    def __post_init__(self) -> None:
        object.__setattr__(self, "containers", tuple(self.containers))
