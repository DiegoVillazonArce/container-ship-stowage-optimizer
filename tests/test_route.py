import pytest

from stowage_optimizer.core import Route


def test_route_preserves_order_and_reports_one_based_port_order() -> None:
    route = Route((" Panama ", "Brazil", "Spain"))

    assert route.ports == ("Panama", "Brazil", "Spain")
    assert route.contains(" Brazil ")
    assert route.order_of("Spain") == 3


def test_route_rejects_empty_and_blank_ports() -> None:
    with pytest.raises(ValueError, match="at least one"):
        Route(())

    with pytest.raises(ValueError, match="must not be blank"):
        Route(("Panama", " "))


def test_route_rejects_duplicate_ports() -> None:
    with pytest.raises(ValueError, match="must be unique"):
        Route(("Panama", "Brazil", "Panama"))
