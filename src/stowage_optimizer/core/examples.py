"""Small hand-checkable instances for early development and tests."""

from __future__ import annotations

from stowage_optimizer.core.container import Container, ContainerType
from stowage_optimizer.core.problem import ProblemInstance
from stowage_optimizer.core.route import Route
from stowage_optimizer.core.ship import Ship


def create_small_example_instance() -> ProblemInstance:
    """Return a valid small instance using a 6 x 4 x 4 vessel grid."""
    ship = Ship(
        bays=6,
        rows=4,
        tiers=4,
        reefer_slots=((1, 1, 1), (1, 2, 1), (2, 1, 1), (2, 2, 1)),
    )
    route = Route(("Panama", "Brazil", "Spain"))
    containers = (
        Container("C001", 28.5, "Panama", ContainerType.NORMAL),
        Container("C002", 18.0, "Brazil", ContainerType.REEFER),
        Container("C003", 24.0, "Spain", ContainerType.FLAMMABLE),
        Container("C004", 16.5, "Spain", ContainerType.OXIDIZER),
    )
    return ProblemInstance(ship=ship, containers=containers, route=route)
