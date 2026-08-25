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


class CollectionStartupRecoveryError(CollectionPlanRecoveryError):
    """Raised when startup cannot establish a safe Collection transaction state."""


def inspect_collection_startup_recovery(
    processed_json_path: str | Path,
) -> CollectionApplyRecoveryInfo | None:
    """Inspect a pending coordinated transaction beside ``processed.json`` read-only."""

    processed = Path(processed_json_path).expanduser().resolve()
    return inspect_interrupted_collection_apply(processed.parent)


def ensure_collection_startup_recovery(
    processed_json_path: str | Path,
    *,
    confirm_recovery: Callable[[CollectionApplyRecoveryInfo], bool],
) -> bool:
    """Establish safe startup state or return ``False`` when the user chooses to exit.

    ``confirm_recovery`` is invoked only when a valid journal exists. Returning ``False``
    leaves every journal/store file untouched. Returning ``True`` asserts that the caller
    has confirmed no other application instance is still applying Collection changes.
    """

    processed = Path(processed_json_path).expanduser().resolve()
    info = inspect_interrupted_collection_apply(processed.parent)
    if info is None:
        return True

    if not confirm_recovery(info):
        return False

    recovered = recover_interrupted_collection_apply(processed.parent)
    if not recovered:
        raise CollectionStartupRecoveryError(
            "Collection transaction journal disappeared before recovery completed."
        )
    if inspect_interrupted_collection_apply(processed.parent) is not None:
        raise CollectionStartupRecoveryError(
            "Collection transaction journal still exists after recovery."
        )
    return True


__all__ = [
    "CollectionStartupRecoveryError",
    "ensure_collection_startup_recovery",
    "inspect_collection_startup_recovery",
]
