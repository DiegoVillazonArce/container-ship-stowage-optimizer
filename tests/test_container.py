from stowage_optimizer.core import Container, ContainerType


def test_container_normalizes_type_from_string() -> None:
    container = Container(
        id=" C001 ",
        weight=20.0,
        destination_port=" Panama ",
        type="reefer",
    )

    assert container.id == "C001"
    assert container.destination_port == "Panama"
    assert container.type == ContainerType.REEFER
    assert container.is_reefer


def test_container_preserves_unknown_type_for_validation() -> None:
    container = Container("C001", 20.0, "Panama", "Unknown")

    assert container.type == "Unknown"
