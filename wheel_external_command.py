"""Immutable versioned contract for external Wheel commands."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any


WHEEL_EXTERNAL_COMMAND_SCHEMA = "smwc-wheel-command"
WHEEL_EXTERNAL_COMMAND_VERSION = 1
WHEEL_EXTERNAL_COMMAND_ACTIONS = ("spin", "reroll")
WHEEL_EXTERNAL_COMMAND_KEYS = (
    "schema",
    "version",
    "command_id",
    "action",
)
WHEEL_EXTERNAL_COMMAND_ID_PATTERN = re.compile(
    r"^[A-Za-z0-9._:-]{1,128}$"
)


class WheelExternalCommandError(ValueError):
    """Raised when an external Wheel command violates its contract."""


@dataclass(frozen=True, slots=True)
class WheelExternalCommand:
    """Detached immutable intent to spin or reroll the Python-owned Wheel."""

    schema: str
    version: int
    command_id: str
    action: str


def parse_wheel_external_command(
    document: Any,
) -> WheelExternalCommand:
    """Validate and detach one external Wheel command document."""

    if not isinstance(document, dict):
        raise WheelExternalCommandError(
            "Wheel command must be a JSON object."
        )

    actual_keys = set(document)
    expected_keys = set(WHEEL_EXTERNAL_COMMAND_KEYS)
    if actual_keys != expected_keys:
        missing = sorted(expected_keys - actual_keys)
        unexpected = sorted(actual_keys - expected_keys)
        details = []
        if missing:
            details.append("missing: " + ", ".join(missing))
        if unexpected:
            details.append("unexpected: " + ", ".join(unexpected))
        raise WheelExternalCommandError(
            "Wheel command fields must match the versioned contract"
            + (f" ({'; '.join(details)})" if details else ".")
        )

    schema = document["schema"]
    if schema != WHEEL_EXTERNAL_COMMAND_SCHEMA:
        raise WheelExternalCommandError(
            "Unsupported Wheel command schema."
        )

    version = document["version"]
    if (
        isinstance(version, bool)
        or not isinstance(version, int)
        or version != WHEEL_EXTERNAL_COMMAND_VERSION
    ):
        raise WheelExternalCommandError(
            "Unsupported Wheel command version."
        )

    command_id = document["command_id"]
    if (
        not isinstance(command_id, str)
        or WHEEL_EXTERNAL_COMMAND_ID_PATTERN.fullmatch(command_id)
        is None
    ):
        raise WheelExternalCommandError(
            "command_id must contain 1-128 letters, digits, "
            "periods, underscores, colons, or hyphens."
        )

    action = document["action"]
    if (
        not isinstance(action, str)
        or action not in WHEEL_EXTERNAL_COMMAND_ACTIONS
    ):
        raise WheelExternalCommandError(
            "action must be exactly 'spin' or 'reroll'."
        )

    return WheelExternalCommand(
        schema=schema,
        version=version,
        command_id=command_id,
        action=action,
    )


def wheel_external_command_to_document(
    command: WheelExternalCommand,
) -> dict[str, Any]:
    """Return a detached canonical command document."""

    if not isinstance(command, WheelExternalCommand):
        raise TypeError("command must be a WheelExternalCommand")

    return {
        "schema": command.schema,
        "version": command.version,
        "command_id": command.command_id,
        "action": command.action,
    }


def serialize_wheel_external_command(
    command: WheelExternalCommand,
) -> str:
    """Serialize a command as deterministic compact JSON."""

    return json.dumps(
        wheel_external_command_to_document(command),
        ensure_ascii=False,
        separators=(",", ":"),
    )


__all__ = [
    "WHEEL_EXTERNAL_COMMAND_SCHEMA",
    "WHEEL_EXTERNAL_COMMAND_VERSION",
    "WHEEL_EXTERNAL_COMMAND_ACTIONS",
    "WHEEL_EXTERNAL_COMMAND_KEYS",
    "WHEEL_EXTERNAL_COMMAND_ID_PATTERN",
    "WheelExternalCommandError",
    "WheelExternalCommand",
    "parse_wheel_external_command",
    "wheel_external_command_to_document",
    "serialize_wheel_external_command",
]
