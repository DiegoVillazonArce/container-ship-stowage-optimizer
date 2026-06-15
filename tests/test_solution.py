import pytest

from stowage_optimizer.core import StowageAssignment, StowageSolution


def test_stowage_solution_builds_from_mapping() -> None:
    solution = StowageSolution.from_mapping(
        {
            " C001 ": (1, 1, 1),
            "C002": (1, 2, 1),
        }
    )

    assert solution.assigned_container_ids == ("C001", "C002")
    assert solution.slot_for(" C001 ") == (1, 1, 1)
    assert solution.assignment_map == {"C001": (1, 1, 1), "C002": (1, 2, 1)}


def test_stowage_solution_rejects_duplicate_container_assignments() -> None:
    with pytest.raises(ValueError, match="Duplicate assignment"):
        StowageSolution(
            (
                StowageAssignment("C001", (1, 1, 1)),
                StowageAssignment("C001", (1, 2, 1)),
            )
        )


def test_stowage_assignment_rejects_invalid_slot_position() -> None:
    with pytest.raises(ValueError, match="slot position"):
        StowageAssignment("C001", (1, 1))
