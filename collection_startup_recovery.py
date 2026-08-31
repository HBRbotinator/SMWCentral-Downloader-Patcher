"""Safe startup gate for interrupted coordinated Collection transactions.

A transaction journal can belong to another still-running application instance, so this
module never treats a journal as abandoned automatically. It first performs a read-only
validation/inspection and only calls recovery after the UI has obtained explicit user
confirmation that all other application instances are closed.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from collection_plan_apply import (
    CollectionApplyRecoveryInfo,
    CollectionPlanRecoveryError,
    inspect_interrupted_collection_apply,
    recover_interrupted_collection_apply,
)
from collection_update_current_rom_replace_apply import (
    CollectionCurrentRomReplaceRecoveryInfo,
    inspect_interrupted_current_rom_replacement,
    recover_interrupted_current_rom_replacement,
)
from collection_rom_organization_apply import (
    CollectionRomOrganizationRecoveryError,
    CollectionRomOrganizationRecoveryInfo,
    inspect_interrupted_collection_rom_organization,
    recover_interrupted_collection_rom_organization,
)


class CollectionStartupRecoveryError(CollectionPlanRecoveryError):
    """Raised when startup cannot establish a safe Collection transaction state."""


RecoveryInfo = (
    CollectionApplyRecoveryInfo
    | CollectionRomOrganizationRecoveryInfo
    | CollectionCurrentRomReplaceRecoveryInfo
)


def _pending_recovery(
    processed_json_path: str | Path,
) -> tuple[str, RecoveryInfo] | None:
    processed = Path(processed_json_path).expanduser().resolve()
    collection_info = inspect_interrupted_collection_apply(processed.parent)
    organization_info = inspect_interrupted_collection_rom_organization(processed.parent)
    current_rom_info = inspect_interrupted_current_rom_replacement(processed.parent)
    pending = tuple(
        (kind, info)
        for kind, info in (
            ("collection", collection_info),
            ("organization", organization_info),
            ("current_rom", current_rom_info),
        )
        if info is not None
    )
    if len(pending) > 1:
        raise CollectionStartupRecoveryError(
            "Multiple Collection transaction journals exist. Startup cannot choose a recovery "
            "order safely. Back up the data directory and resolve the transaction state before "
            "opening Collection-dependent features."
        )
    return pending[0] if pending else None


def inspect_collection_startup_recovery(
    processed_json_path: str | Path,
) -> RecoveryInfo | None:
    """Inspect one pending coordinated transaction beside ``processed.json`` read-only."""

    pending = _pending_recovery(processed_json_path)
    return pending[1] if pending is not None else None


def ensure_collection_startup_recovery(
    processed_json_path: str | Path,
    *,
    confirm_recovery: Callable[[RecoveryInfo], bool],
) -> bool:
    """Establish safe startup state or return ``False`` when the user chooses to exit.

    ``confirm_recovery`` is invoked only when one valid journal exists. Returning ``False``
    leaves every journal/store/filesystem target untouched. Returning ``True`` asserts that
    the caller has confirmed no other application instance still owns the transaction.
    """

    processed = Path(processed_json_path).expanduser().resolve()
    pending = _pending_recovery(processed)
    if pending is None:
        return True
    kind, info = pending

    if not confirm_recovery(info):
        return False

    if kind == "collection":
        recovered = recover_interrupted_collection_apply(processed.parent)
    elif kind == "organization":
        recovered = recover_interrupted_collection_rom_organization(processed.parent)
    else:
        recovered = recover_interrupted_current_rom_replacement(processed.parent)
    if not recovered:
        raise CollectionStartupRecoveryError(
            "Collection transaction journal disappeared before recovery completed."
        )
    if _pending_recovery(processed) is not None:
        raise CollectionStartupRecoveryError(
            "Collection transaction journal still exists after recovery."
        )
    return True


__all__ = [
    "CollectionStartupRecoveryError",
    "ensure_collection_startup_recovery",
    "inspect_collection_startup_recovery",
]
