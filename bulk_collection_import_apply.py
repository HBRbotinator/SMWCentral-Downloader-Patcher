"""One-shot confirmed execution boundary for bulk Collection imports."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping

from bulk_collection_import_application import (
    BULK_COLLECTION_IMPORT_APPLICATION_SCHEMA,
    BULK_COLLECTION_IMPORT_APPLICATION_VERSION,
    BulkCollectionImportApplicationPlan,
    serialize_bulk_collection_import_application_plan,
)
from bulk_collection_import_persistence import (
    BulkCollectionImportPersistenceResult,
    execute_bulk_collection_import_application_plan,
)


BULK_COLLECTION_IMPORT_APPLY_CONFIRMATION_SCHEMA = (
    "smwc-bulk-collection-apply-confirmation"
)
BULK_COLLECTION_IMPORT_APPLY_CONFIRMATION_VERSION = 1

BULK_COLLECTION_IMPORT_APPLY_SESSION_STATES = (
    "awaiting_confirmation",
    "confirmed",
    "succeeded",
    "failed",
)
BULK_COLLECTION_IMPORT_APPLY_TERMINAL_STATES = (
    "succeeded",
    "failed",
)

_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_CONFIRMATION_KEYS = (
    "schema",
    "version",
    "import_id",
    "source_sha256",
    "application_plan_sha256",
    "confirmed",
)


class BulkCollectionImportApplyError(RuntimeError):
    """Raised when one confirmed Apply session cannot proceed safely."""


class BulkCollectionImportApplySession:
    """One-shot state machine bound to one exact application preview."""

    __slots__ = (
        "_application_plan_json",
        "_application_plan_sha256",
        "_import_id",
        "_source_sha256",
        "_state",
        "_confirmation",
        "_result",
    )

    def __init__(
        self,
        application_plan: BulkCollectionImportApplicationPlan,
    ):
        if not isinstance(
            application_plan,
            BulkCollectionImportApplicationPlan,
        ):
            raise TypeError(
                "application_plan must be "
                "BulkCollectionImportApplicationPlan"
            )
        if (
            application_plan.schema
            != BULK_COLLECTION_IMPORT_APPLICATION_SCHEMA
        ):
            raise BulkCollectionImportApplyError(
                "Application plan schema is not supported."
            )
        if (
            application_plan.version
            != BULK_COLLECTION_IMPORT_APPLICATION_VERSION
        ):
            raise BulkCollectionImportApplyError(
                "Application plan version is not supported."
            )

        try:
            serialized = (
                serialize_bulk_collection_import_application_plan(
                    application_plan
                )
            )
            document = json.loads(serialized)
        except Exception as error:
            raise BulkCollectionImportApplyError(
                "Application plan cannot be frozen for Apply."
            ) from error

        import_id = _require_text(
            document.get("import_id"),
            "application import_id",
        )
        source_sha256 = _require_sha256(
            document.get("source_sha256"),
            "application source_sha256",
        )

        self._application_plan_json = serialized
        self._application_plan_sha256 = hashlib.sha256(
            serialized.encode("utf-8")
        ).hexdigest()
        self._import_id = import_id
        self._source_sha256 = source_sha256
        self._state = "awaiting_confirmation"
        self._confirmation = None
        self._result = None

    @property
    def state(self) -> str:
        return self._state

    @property
    def application_plan_sha256(self) -> str:
        return self._application_plan_sha256

    @property
    def result(
        self,
    ) -> BulkCollectionImportPersistenceResult | None:
        return self._result

    def confirmation_document(self) -> dict[str, Any] | None:
        """Return detached confirmation state, if explicitly confirmed."""

        if self._confirmation is None:
            return None
        return dict(self._confirmation)

    def confirm(
        self,
        application_plan_sha256: str,
    ) -> dict[str, Any]:
        """Explicitly confirm the exact frozen application preview once."""

        if self._state != "awaiting_confirmation":
            raise BulkCollectionImportApplyError(
                "Apply confirmation is allowed only once while "
                "awaiting confirmation."
            )

        supplied = _require_sha256(
            application_plan_sha256,
            "application_plan_sha256",
        )
        if supplied != self._application_plan_sha256:
            raise BulkCollectionImportApplyError(
                "Apply confirmation does not match the exact "
                "application preview."
            )

        confirmation = {
            "schema": (
                BULK_COLLECTION_IMPORT_APPLY_CONFIRMATION_SCHEMA
            ),
            "version": (
                BULK_COLLECTION_IMPORT_APPLY_CONFIRMATION_VERSION
            ),
            "import_id": self._import_id,
            "source_sha256": self._source_sha256,
            "application_plan_sha256": (
                self._application_plan_sha256
            ),
            "confirmed": True,
        }

        self._confirmation = confirmation
        self._state = "confirmed"
        return dict(confirmation)

    def execute(
        self,
        store: Any,
    ) -> BulkCollectionImportPersistenceResult:
        """Execute the exact confirmed plan once through the atomic executor."""

        if self._state != "confirmed":
            raise BulkCollectionImportApplyError(
                "Apply execution requires one confirmed, nonterminal "
                "session."
            )

        try:
            application_document = json.loads(
                self._application_plan_json
            )
            result = execute_bulk_collection_import_application_plan(
                application_document,
                store,
            )
        except Exception as error:
            self._state = "failed"
            self._result = None
            raise BulkCollectionImportApplyError(
                "Confirmed bulk Collection import Apply failed. "
                "A fresh preview and confirmation are required "
                "before another attempt."
            ) from error

        self._result = result
        self._state = "succeeded"
        return result


def create_bulk_collection_import_apply_session(
    application_plan: BulkCollectionImportApplicationPlan,
) -> BulkCollectionImportApplySession:
    """Create an inert session from one exact final application preview."""

    return BulkCollectionImportApplySession(application_plan)


def confirm_bulk_collection_import_apply_session(
    session: BulkCollectionImportApplySession,
    application_plan_sha256: str,
) -> dict[str, Any]:
    """Confirm one session against the exact displayed plan fingerprint."""

    return _require_session(session).confirm(
        application_plan_sha256
    )


def execute_bulk_collection_import_apply_session(
    session: BulkCollectionImportApplySession,
    store: Any,
) -> BulkCollectionImportPersistenceResult:
    """Execute one explicitly confirmed session exactly once."""

    return _require_session(session).execute(store)


def bulk_collection_import_apply_confirmation_to_document(
    session: BulkCollectionImportApplySession,
) -> dict[str, Any] | None:
    """Return detached confirmation state for one Apply session."""

    return _require_session(session).confirmation_document()


def serialize_bulk_collection_import_apply_confirmation(
    confirmation: Mapping[str, Any],
) -> str:
    """Validate and serialize one explicit Apply confirmation."""

    document = _parse_confirmation_document(confirmation)
    return json.dumps(
        document,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    )


def _parse_confirmation_document(
    value: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise BulkCollectionImportApplyError(
            "Apply confirmation must be a mapping."
        )
    if set(value) != set(_CONFIRMATION_KEYS):
        raise BulkCollectionImportApplyError(
            "Apply confirmation fields do not match the contract."
        )
    if (
        value["schema"]
        != BULK_COLLECTION_IMPORT_APPLY_CONFIRMATION_SCHEMA
    ):
        raise BulkCollectionImportApplyError(
            "Apply confirmation schema is not supported."
        )
    if (
        type(value["version"]) is not int
        or value["version"]
        != BULK_COLLECTION_IMPORT_APPLY_CONFIRMATION_VERSION
    ):
        raise BulkCollectionImportApplyError(
            "Apply confirmation version is not supported."
        )
    if value["confirmed"] is not True:
        raise BulkCollectionImportApplyError(
            "Apply confirmation must be explicitly true."
        )

    return {
        "schema": value["schema"],
        "version": value["version"],
        "import_id": _require_text(
            value["import_id"],
            "confirmation import_id",
        ),
        "source_sha256": _require_sha256(
            value["source_sha256"],
            "confirmation source_sha256",
        ),
        "application_plan_sha256": _require_sha256(
            value["application_plan_sha256"],
            "confirmation application_plan_sha256",
        ),
        "confirmed": True,
    }


def _require_session(
    value: Any,
) -> BulkCollectionImportApplySession:
    if not isinstance(value, BulkCollectionImportApplySession):
        raise TypeError(
            "session must be BulkCollectionImportApplySession"
        )
    return value


def _require_text(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
    ):
        raise BulkCollectionImportApplyError(
            f"{label} must be a non-empty trimmed string."
        )
    return value


def _require_sha256(value: Any, label: str) -> str:
    text = _require_text(value, label)
    if not _SHA256_PATTERN.fullmatch(text):
        raise BulkCollectionImportApplyError(
            f"{label} must be a lowercase 64-character SHA-256."
        )
    return text


__all__ = [
    "BULK_COLLECTION_IMPORT_APPLY_CONFIRMATION_SCHEMA",
    "BULK_COLLECTION_IMPORT_APPLY_CONFIRMATION_VERSION",
    "BULK_COLLECTION_IMPORT_APPLY_SESSION_STATES",
    "BULK_COLLECTION_IMPORT_APPLY_TERMINAL_STATES",
    "BulkCollectionImportApplyError",
    "BulkCollectionImportApplySession",
    "create_bulk_collection_import_apply_session",
    "confirm_bulk_collection_import_apply_session",
    "execute_bulk_collection_import_apply_session",
    "bulk_collection_import_apply_confirmation_to_document",
    "serialize_bulk_collection_import_apply_confirmation",
]
