"""Route model for ordered unloading ports."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True, slots=True)
class Route:
    """Ordered list of destination ports visited by the vessel."""

    ports: tuple[str, ...]

    def __init__(self, ports: Iterable[str]) -> None:
        normalized_ports = tuple(str(port).strip() for port in ports)
        if not normalized_ports:
            raise ValueError("Route must contain at least one port.")
        if any(not port for port in normalized_ports):
            raise ValueError("Route ports must not be blank.")
        if len(set(normalized_ports)) != len(normalized_ports):
            raise ValueError("Route ports must be unique.")

        object.__setattr__(self, "ports", normalized_ports)

    def contains(self, port: str) -> bool:
        """Return whether a destination port belongs to the route."""
        return str(port).strip() in self.ports

    def order_of(self, port: str) -> int:
        """Return one-based unloading order for a port."""
        return self.ports.index(str(port).strip()) + 1
