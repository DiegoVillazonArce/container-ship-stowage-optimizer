from stowage_optimizer.core import (
    Container,
    ContainerType,
    ProblemInstance,
    Route,
    Ship,
    validate_instance,
)
from stowage_optimizer.core.examples import create_small_example_instance


def test_small_example_instance_is_valid() -> None:
    instance = create_small_example_instance()

    result = validate_instance(instance)

    assert result.is_valid
    assert result.errors == ()


def test_validation_rejects_duplicate_container_ids() -> None:
    instance = ProblemInstance(
        ship=Ship(bays=1, rows=1, tiers=2),
        route=Route(("Panama",)),
        containers=(
            Container("C001", 10.0, "Panama", ContainerType.NORMAL),
            Container("C001", 12.0, "Panama", ContainerType.NORMAL),
        ),
    )

    result = validate_instance(instance)

    assert not result.is_valid
    assert "duplicate_container_id" in _codes(result)


def test_validation_rejects_invalid_weights() -> None:
    instance = ProblemInstance(
        ship=Ship(bays=1, rows=1, tiers=1),
        route=Route(("Panama",)),
        containers=(Container("C001", -10.0, "Panama", ContainerType.NORMAL),),
    )

    result = validate_instance(instance)

    assert not result.is_valid
    assert "invalid_container_weight" in _codes(result)


def test_validation_rejects_non_finite_weights() -> None:
    instance = ProblemInstance(
        ship=Ship(bays=1, rows=3, tiers=1),
        route=Route(("Panama",)),
        containers=(
            Container("NAN", float("nan"), "Panama", ContainerType.NORMAL),
            Container("INF", float("inf"), "Panama", ContainerType.NORMAL),
            Container("NINF", float("-inf"), "Panama", ContainerType.NORMAL),
        ),
    )

    result = validate_instance(instance)

    assert not result.is_valid
    assert [issue.code for issue in result.errors].count("invalid_container_weight") == 3
    assert all("finite" in issue.message for issue in result.errors)


def test_validation_rejects_unknown_container_type() -> None:
    instance = ProblemInstance(
        ship=Ship(bays=1, rows=1, tiers=1),
        route=Route(("Panama",)),
        containers=(Container("C001", 10.0, "Panama", "Mystery"),),
    )

    result = validate_instance(instance)

    assert not result.is_valid
    assert "unknown_container_type" in _codes(result)


def test_validation_rejects_destination_not_in_route() -> None:
    instance = ProblemInstance(
        ship=Ship(bays=1, rows=1, tiers=1),
        route=Route(("Panama",)),
        containers=(Container("C001", 10.0, "Spain", ContainerType.NORMAL),),
    )

    result = validate_instance(instance)

    assert not result.is_valid
    assert "destination_not_in_route" in _codes(result)


def test_validation_rejects_more_containers_than_slots() -> None:
    instance = ProblemInstance(
        ship=Ship(bays=1, rows=1, tiers=1),
        route=Route(("Panama",)),
        containers=(
            Container("C001", 10.0, "Panama", ContainerType.NORMAL),
            Container("C002", 12.0, "Panama", ContainerType.NORMAL),
        ),
    )

    result = validate_instance(instance)

    assert not result.is_valid
    assert "vessel_capacity_exceeded" in _codes(result)
    assert "Remove at least 1" in result.errors[-1].message


def test_validation_rejects_more_reefers_than_reefer_slots() -> None:
    instance = ProblemInstance(
        ship=Ship(bays=1, rows=1, tiers=2, reefer_slots=((1, 1, 1),)),
        route=Route(("Panama",)),
        containers=(
            Container("C001", 10.0, "Panama", ContainerType.REEFER),
            Container("C002", 12.0, "Panama", ContainerType.REEFER),
        ),
    )

    result = validate_instance(instance)

    assert not result.is_valid
    assert "reefer_capacity_exceeded" in _codes(result)


def _codes(result):
    return {issue.code for issue in result.errors}
