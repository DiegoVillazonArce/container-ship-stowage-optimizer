"""Pre-solve validation for stowage problem instances."""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field
from numbers import Real

from stowage_optimizer.core.container import ContainerType
from stowage_optimizer.core.problem import ProblemInstance


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    """A validation issue that can be shown to users or tests."""

    code: str
    message: str


@dataclass(frozen=True, slots=True)
class ValidationResult:
    """Validation output with errors and warnings."""

    errors: tuple[ValidationIssue, ...] = field(default_factory=tuple)
    warnings: tuple[ValidationIssue, ...] = field(default_factory=tuple)

    @property
    def is_valid(self) -> bool:
        """Return whether the instance can proceed to optimization."""
        return not self.errors

    def raise_for_errors(self) -> None:
        """Raise a ValueError containing all validation errors."""
        if self.errors:
            messages = "; ".join(issue.message for issue in self.errors)
            raise ValueError(messages)


def validate_instance(instance: ProblemInstance) -> ValidationResult:
    """Validate an instance before any solver is executed."""
    errors: list[ValidationIssue] = []

    _validate_container_ids(instance, errors)
    _validate_container_weights(instance, errors)
    _validate_container_types(instance, errors)
    _validate_destinations(instance, errors)
    _validate_capacity(instance, errors)
    _validate_reefer_capacity(instance, errors)

    return ValidationResult(errors=tuple(errors), warnings=())


def _validate_container_ids(instance: ProblemInstance, errors: list[ValidationIssue]) -> None:
    ids = [container.id for container in instance.containers]
    for container in instance.containers:
        if not container.id:
            errors.append(
                ValidationIssue(
                    code="blank_container_id",
                    message="Container ID must not be blank.",
                )
            )

    duplicate_ids = sorted(container_id for container_id, count in Counter(ids).items() if count > 1)
    for container_id in duplicate_ids:
        errors.append(
            ValidationIssue(
                code="duplicate_container_id",
                message=f"Duplicate container ID: {container_id}.",
            )
        )


def _validate_container_weights(instance: ProblemInstance, errors: list[ValidationIssue]) -> None:
    for container in instance.containers:
        if isinstance(container.weight, bool) or not isinstance(container.weight, Real):
            errors.append(
                ValidationIssue(
                    code="invalid_container_weight",
                    message=f"Container {container.id} has a non-numeric weight.",
                )
            )
            continue

        if not math.isfinite(container.weight):
            errors.append(
                ValidationIssue(
                    code="invalid_container_weight",
                    message=f"Container {container.id} must have a finite weight.",
                )
            )
            continue

        if container.weight <= 0:
            errors.append(
                ValidationIssue(
                    code="invalid_container_weight",
                    message=f"Container {container.id} must have a positive weight.",
                )
            )


def _validate_container_types(instance: ProblemInstance, errors: list[ValidationIssue]) -> None:
    for container in instance.containers:
        if not isinstance(container.type, ContainerType):
            errors.append(
                ValidationIssue(
                    code="unknown_container_type",
                    message=f"Container {container.id} has unknown type `{container.type}`.",
                )
            )


def _validate_destinations(instance: ProblemInstance, errors: list[ValidationIssue]) -> None:
    for container in instance.containers:
        if not container.destination_port:
            errors.append(
                ValidationIssue(
                    code="blank_destination_port",
                    message=f"Container {container.id} must have a destination port.",
                )
            )
            continue

        if not instance.route.contains(container.destination_port):
            errors.append(
                ValidationIssue(
                    code="destination_not_in_route",
                    message=(
                        f"Container {container.id} has destination `{container.destination_port}`, "
                        "which is not included in the route."
                    ),
                )
            )


def _validate_capacity(instance: ProblemInstance, errors: list[ValidationIssue]) -> None:
    container_count = len(instance.containers)
    slot_count = instance.ship.slot_count
    if container_count > slot_count:
        excess = container_count - slot_count
        errors.append(
            ValidationIssue(
                code="vessel_capacity_exceeded",
                message=(
                    f"Vessel capacity exceeded: {container_count} containers for {slot_count} slots. "
                    f"Remove at least {excess} container(s) before optimization."
                ),
            )
        )


def _validate_reefer_capacity(instance: ProblemInstance, errors: list[ValidationIssue]) -> None:
    reefer_count = sum(1 for container in instance.containers if container.is_reefer)
    reefer_slot_count = instance.ship.reefer_slot_count
    if reefer_count > reefer_slot_count:
        excess = reefer_count - reefer_slot_count
        errors.append(
            ValidationIssue(
                code="reefer_capacity_exceeded",
                message=(
                    f"Reefer capacity exceeded: {reefer_count} reefer containers for "
                    f"{reefer_slot_count} reefer-capable slots. Remove at least {excess} "
                    "reefer container(s) or increase reefer-capable slots."
                ),
            )
        )
