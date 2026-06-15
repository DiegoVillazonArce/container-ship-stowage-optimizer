"""Vessel grid and slot coordinate models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable


@dataclass(frozen=True, slots=True)
class Slot:
    """A discrete vessel position and its normalized physical coordinates."""

    bay: int
    row: int
    tier: int
    x: float
    y: float
    z: float
    is_reefer: bool = False

    @property
    def position(self) -> tuple[int, int, int]:
        """Return the discrete `(bay, row, tier)` position."""
        return (self.bay, self.row, self.tier)


@dataclass(frozen=True, slots=True)
class Ship:
    """Simplified container ship represented as a bay-row-tier grid."""

    bays: int
    rows: int
    tiers: int
    reefer_slots: Iterable[tuple[int, int, int]] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        self._validate_dimensions()
        reefer_slot_set = frozenset(self.reefer_slots)
        self._validate_reefer_slots(reefer_slot_set)
        object.__setattr__(self, "reefer_slots", reefer_slot_set)

    @property
    def slots(self) -> tuple[Slot, ...]:
        """Generate all vessel slots with normalized coordinates."""
        return tuple(
            Slot(
                bay=bay,
                row=row,
                tier=tier,
                x=self._normalize_symmetric(bay, self.bays),
                y=self._normalize_symmetric(row, self.rows),
                z=self._normalize_vertical(tier, self.tiers),
                is_reefer=(bay, row, tier) in self.reefer_slots,
            )
            for bay in range(1, self.bays + 1)
            for row in range(1, self.rows + 1)
            for tier in range(1, self.tiers + 1)
        )

    @property
    def slot_count(self) -> int:
        """Return the total number of available slots."""
        return self.bays * self.rows * self.tiers

    @property
    def reefer_slot_count(self) -> int:
        """Return the number of slots with reefer capability."""
        return len(self.reefer_slots)

    def get_slot(self, bay: int, row: int, tier: int) -> Slot:
        """Return one generated slot by discrete position."""
        self._validate_position((bay, row, tier))
        return Slot(
            bay=bay,
            row=row,
            tier=tier,
            x=self._normalize_symmetric(bay, self.bays),
            y=self._normalize_symmetric(row, self.rows),
            z=self._normalize_vertical(tier, self.tiers),
            is_reefer=(bay, row, tier) in self.reefer_slots,
        )

    def _validate_dimensions(self) -> None:
        for name, value in (("bays", self.bays), ("rows", self.rows), ("tiers", self.tiers)):
            if not isinstance(value, int) or value <= 0:
                raise ValueError(f"`{name}` must be a positive integer.")

    def _validate_reefer_slots(self, reefer_slots: frozenset[tuple[int, int, int]]) -> None:
        for position in reefer_slots:
            self._validate_position(position)

    def _validate_position(self, position: tuple[int, int, int]) -> None:
        if len(position) != 3:
            raise ValueError("Slot position must be a `(bay, row, tier)` tuple.")

        bay, row, tier = position
        if not (1 <= bay <= self.bays and 1 <= row <= self.rows and 1 <= tier <= self.tiers):
            raise ValueError(
                f"Slot position {position} is outside the ship grid "
                f"({self.bays} bays, {self.rows} rows, {self.tiers} tiers)."
            )

    @staticmethod
    def _normalize_symmetric(index: int, size: int) -> float:
        if size == 1:
            return 0.0
        return -1.0 + (2.0 * (index - 1) / (size - 1))

    @staticmethod
    def _normalize_vertical(tier: int, tiers: int) -> float:
        if tiers == 1:
            return 0.0
        return (tier - 1) / (tiers - 1)
