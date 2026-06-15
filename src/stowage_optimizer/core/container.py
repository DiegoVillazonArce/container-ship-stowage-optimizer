"""Container domain model."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class ContainerType(StrEnum):
    """Supported simplified cargo categories."""

    NORMAL = "Normal"
    REEFER = "Reefer"
    FLAMMABLE = "Flammable"
    OXIDIZER = "Oxidizer"

    @classmethod
    def from_value(cls, value: Any) -> ContainerType | str:
        """Normalize a raw cargo type while preserving unknown values for validation."""
        if isinstance(value, cls):
            return value

        normalized = str(value).strip().lower()
        for member in cls:
            if normalized == member.value.lower():
                return member

        return str(value).strip()


@dataclass(frozen=True, slots=True)
class Container:
    """A single container to be assigned to a vessel slot."""

    id: str
    weight: float
    destination_port: str
    type: ContainerType | str = ContainerType.NORMAL

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", str(self.id).strip())
        object.__setattr__(self, "destination_port", str(self.destination_port).strip())
        object.__setattr__(self, "type", ContainerType.from_value(self.type))

    @property
    def is_reefer(self) -> bool:
        """Return whether this container requires a reefer-capable slot."""
        return self.type == ContainerType.REEFER
