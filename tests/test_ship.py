import pytest

from stowage_optimizer.core import Ship


def test_ship_generates_bay_row_tier_grid() -> None:
    ship = Ship(bays=6, rows=4, tiers=4)

    assert ship.slot_count == 96
    assert len(ship.slots) == 96
    assert ship.slots[0].position == (1, 1, 1)
    assert ship.slots[-1].position == (6, 4, 4)


def test_ship_adds_normalized_coordinates() -> None:
    ship = Ship(bays=3, rows=3, tiers=3)

    first = ship.get_slot(1, 1, 1)
    middle = ship.get_slot(2, 2, 2)
    last = ship.get_slot(3, 3, 3)

    assert (first.x, first.y, first.z) == (-1.0, -1.0, 0.0)
    assert (middle.x, middle.y, middle.z) == (0.0, 0.0, 0.5)
    assert (last.x, last.y, last.z) == (1.0, 1.0, 1.0)


def test_ship_caches_generated_slots() -> None:
    ship = Ship(bays=2, rows=2, tiers=2)

    # The grid is generated once and reused; solvers iterate it heavily.
    assert ship.slots is ship.slots


def test_ship_equality_ignores_slot_cache_state() -> None:
    warm = Ship(bays=2, rows=2, tiers=2)
    cold = Ship(bays=2, rows=2, tiers=2)
    _ = warm.slots  # Populate one cache only.

    assert warm == cold


def test_ship_marks_reefer_slots() -> None:
    ship = Ship(bays=2, rows=2, tiers=2, reefer_slots=((1, 1, 1),))

    assert ship.reefer_slot_count == 1
    assert ship.get_slot(1, 1, 1).is_reefer
    assert not ship.get_slot(1, 1, 2).is_reefer


def test_ship_rejects_invalid_dimensions() -> None:
    with pytest.raises(ValueError, match="bays"):
        Ship(bays=0, rows=2, tiers=2)


def test_ship_rejects_boolean_dimensions() -> None:
    with pytest.raises(ValueError, match="bays"):
        Ship(bays=True, rows=2, tiers=2)


def test_ship_rejects_reefer_slots_outside_grid() -> None:
    with pytest.raises(ValueError, match="outside the ship grid"):
        Ship(bays=2, rows=2, tiers=2, reefer_slots=((3, 1, 1),))


def test_ship_rejects_boolean_reefer_slot_coordinates() -> None:
    with pytest.raises(ValueError, match="values must be integers"):
        Ship(bays=2, rows=2, tiers=2, reefer_slots=((True, 1, 1),))
