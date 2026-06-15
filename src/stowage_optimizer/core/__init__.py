"""Core domain models for the stowage optimizer."""

from stowage_optimizer.core.container import Container, ContainerType
from stowage_optimizer.core.problem import ProblemInstance
from stowage_optimizer.core.route import Route
from stowage_optimizer.core.ship import Ship, Slot
from stowage_optimizer.core.solution import SlotPosition, StowageAssignment, StowageSolution
from stowage_optimizer.core.validation import ValidationIssue, ValidationResult, validate_instance

__all__ = [
    "Container",
    "ContainerType",
    "ProblemInstance",
    "Route",
    "Ship",
    "Slot",
    "SlotPosition",
    "StowageAssignment",
    "StowageSolution",
    "ValidationIssue",
    "ValidationResult",
    "validate_instance",
]
