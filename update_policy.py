"""Central policy for checking and applying application updates.

Development and other non-release builds must never replace themselves in
place. The policy is deliberately independent from Tk so startup code,
settings, the updater implementation, and the standalone replacement helper
all make the same fail-closed decision.
"""
from __future__ import annotations

from dataclasses import dataclass

from product_identity import PRODUCT_VERSION, RELEASE_CHANNEL

_RELEASE_CHANNELS = frozenset({"release", "stable"})


class UpdatePolicyError(RuntimeError):
    """Raised when disabled update functionality is invoked directly."""


@dataclass(frozen=True)
class UpdatePolicy:
    """Resolved update behavior for one product build."""

    release_channel: str
    current_version: str
    checks_enabled: bool
    in_place_updates_enabled: bool
    reason: str | None


def evaluate_update_policy(release_channel: str, current_version: str) -> UpdatePolicy:
    """Resolve update behavior from explicit manifest-owned identity values."""

    normalized_channel = release_channel.strip().casefold()
    normalized_version = current_version.strip()
    if normalized_channel in _RELEASE_CHANNELS:
        return UpdatePolicy(
            release_channel=normalized_channel,
            current_version=normalized_version,
            checks_enabled=True,
            in_place_updates_enabled=True,
            reason=None,
        )

    if normalized_channel == "development":
        reason = (
            f"In-place updates are disabled for development build "
            f"{normalized_version}. Install a newer development candidate "
            "manually instead."
        )
    else:
        display_channel = normalized_channel or "unspecified"
        reason = (
            f"In-place updates are disabled for the unrecognized "
            f"{display_channel!r} release channel."
        )

    return UpdatePolicy(
        release_channel=normalized_channel,
        current_version=normalized_version,
        checks_enabled=False,
        in_place_updates_enabled=False,
        reason=reason,
    )


def current_update_policy() -> UpdatePolicy:
    """Return the policy for the authoritative runtime product identity."""

    return evaluate_update_policy(RELEASE_CHANNEL, PRODUCT_VERSION)


def require_update_checks_enabled(
    policy: UpdatePolicy | None = None,
) -> UpdatePolicy:
    """Fail closed when update discovery is unavailable for this build."""

    resolved = policy or current_update_policy()
    if not resolved.checks_enabled:
        raise UpdatePolicyError(resolved.reason or "Update checks are disabled.")
    return resolved


def require_in_place_updates_enabled(
    operation: str = "perform an in-place update",
    policy: UpdatePolicy | None = None,
) -> UpdatePolicy:
    """Fail closed before any download, replacement, or restart is attempted."""

    resolved = policy or current_update_policy()
    if not resolved.in_place_updates_enabled:
        reason = resolved.reason or "In-place updates are disabled."
        raise UpdatePolicyError(f"Cannot {operation}: {reason}")
    return resolved
