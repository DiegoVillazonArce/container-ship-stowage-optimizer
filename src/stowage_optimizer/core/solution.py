"""Stowage solution contract shared by metrics and future solvers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

SlotPosition = tuple[int, int, int]


@dataclass(frozen=True, slots=True)
class StowageAssignment:
    """Assignment of one container to one vessel slot position."""

    container_id: str
    slot_position: SlotPosition

    def __post_init__(self) -> None:
        container_id = str(self.container_id).strip()
        if not container_id:
            raise ValueError("Assignment container ID must not be blank.")

        slot_position = tuple(self.slot_position)
        if len(slot_position) != 3:
            raise ValueError("Assignment slot position must be a `(bay, row, tier)` tuple.")
        if any(isinstance(value, bool) or not isinstance(value, int) for value in slot_position):
            raise ValueError("Assignment slot position values must be integers.")

        object.__setattr__(self, "container_id", container_id)
        object.__setattr__(self, "slot_position", slot_position)


@dataclass(frozen=True, slots=True)
class StowageSolution:
    """Container-to-slot assignments produced by a solver or hand-built scenario."""

    assignments: tuple[StowageAssignment, ...]
    _assignment_map: dict[str, SlotPosition] = field(init=False, repr=False, compare=False)

    def __init__(self, assignments: tuple[StowageAssignment, ...]) -> None:
        normalized_assignments = tuple(assignments)
        assignment_map: dict[str, SlotPosition] = {}

        for assignment in normalized_assignments:
            if assignment.container_id in assignment_map:
                raise ValueError(f"Duplicate assignment for container ID: {assignment.container_id}.")
            assignment_map[assignment.container_id] = assignment.slot_position

        object.__setattr__(self, "assignments", normalized_assignments)
        object.__setattr__(self, "_assignment_map", assignment_map)

    @classmethod
    def from_mapping(cls, assignments: Mapping[str, SlotPosition]) -> StowageSolution:
        """Build a solution from a container-to-position mapping."""
        return cls(
            tuple(
                StowageAssignment(container_id=container_id, slot_position=slot_position)
                for container_id, slot_position in assignments.items()
            )
        )

    @property
    def assignment_map(self) -> dict[str, SlotPosition]:
        """Return a copy of the container-to-position mapping."""
        return dict(self._assignment_map)

    @property
    def assigned_container_ids(self) -> tuple[str, ...]:
        """Return assigned container IDs in solution order."""
        return tuple(assignment.container_id for assignment in self.assignments)

    def slot_for(self, container_id: str) -> SlotPosition | None:
        """Return the assigned slot position for one container ID, if present."""
        return self._assignment_map.get(str(container_id).strip())
