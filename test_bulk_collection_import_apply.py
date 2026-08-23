"""Specification for the explicit bulk-import Apply boundary."""

from __future__ import annotations

import hashlib
import json
import unittest
from types import MappingProxyType

from bulk_collection_import_apply import (
    BULK_COLLECTION_IMPORT_APPLY_CONFIRMATION_SCHEMA,
    BULK_COLLECTION_IMPORT_APPLY_CONFIRMATION_VERSION,
    BULK_COLLECTION_IMPORT_APPLY_SESSION_STATES,
    BULK_COLLECTION_IMPORT_APPLY_TERMINAL_STATES,
    BulkCollectionImportApplyError,
    bulk_collection_import_apply_confirmation_to_document,
    confirm_bulk_collection_import_apply_session,
    create_bulk_collection_import_apply_session,
    execute_bulk_collection_import_apply_session,
    serialize_bulk_collection_import_apply_confirmation,
)

from bulk_collection_import_application import (
    BulkCollectionImportApplicationAttributeChange,
    BulkCollectionImportApplicationGroup,
    BulkCollectionImportApplicationOperation,
    BulkCollectionImportApplicationPlan,
    BulkCollectionImportApplicationSourceReference,
    serialize_bulk_collection_import_application_plan,
)


APPLY_CONFIRMATION_SCHEMA = (
    "smwc-bulk-collection-apply-confirmation"
)
APPLY_CONFIRMATION_VERSION = 1
APPLY_SESSION_STATES = (
    "awaiting_confirmation",
    "confirmed",
    "succeeded",
    "failed",
)
APPLY_TERMINAL_STATES = (
    "succeeded",
    "failed",
)
APPLY_RETRY_REQUIRES_NEW_SESSION = True

SOURCE_SHA256 = "a" * 64
UPDATE_SHARED_SHA256 = "b" * 64
UNCHANGED_SHARED_SHA256 = "c" * 64


def _application_plan(
    *,
    update_sha256=UPDATE_SHARED_SHA256,
    create_title="Create Me",
):
    operations = (
        BulkCollectionImportApplicationOperation(
            entry_key="create",
            action="create_record",
            collection_key="500",
            expected_shared_sha256=None,
            title_value=create_title,
            source_references=(
                BulkCollectionImportApplicationSourceReference(
                    source="smwc",
                    external_id="500",
                ),
            ),
            source_reference_additions=(),
            attributes=MappingProxyType(
                {
                    "authors": ("Creator",),
                    "exit_count": 12,
                }
            ),
            attribute_changes=(),
            warnings=(),
        ),
        BulkCollectionImportApplicationOperation(
            entry_key="update",
            action="update_record",
            collection_key="200",
            expected_shared_sha256=update_sha256,
            title_value=None,
            source_references=(),
            source_reference_additions=(
                BulkCollectionImportApplicationSourceReference(
                    source="kaizoff",
                    external_id="mirror-200",
                ),
            ),
            attributes=MappingProxyType({}),
            attribute_changes=(
                BulkCollectionImportApplicationAttributeChange(
                    field="difficulty",
                    value="Kaizo: Intermediate",
                ),
            ),
            warnings=(),
        ),
        BulkCollectionImportApplicationOperation(
            entry_key="unchanged",
            action="no_change",
            collection_key="300",
            expected_shared_sha256=UNCHANGED_SHARED_SHA256,
            title_value=None,
            source_references=(),
            source_reference_additions=(),
            attributes=MappingProxyType({}),
            attribute_changes=(),
            warnings=(),
        ),
        BulkCollectionImportApplicationOperation(
            entry_key="skip",
            action="skip",
            collection_key=None,
            expected_shared_sha256=None,
            title_value=None,
            source_references=(),
            source_reference_additions=(),
            attributes=MappingProxyType({}),
            attribute_changes=(),
            warnings=("source_identity_conflict",),
        ),
    )

    return BulkCollectionImportApplicationPlan(
        schema="smwc-bulk-collection-application-plan",
        version=1,
        import_id="apply-contract-suite",
        source_sha256=SOURCE_SHA256,
        summary=MappingProxyType(
            {
                "total": 4,
                "create_record": 1,
                "update_record": 1,
                "no_change": 1,
                "skip": 1,
            }
        ),
        operations=operations,
        groups=(
            BulkCollectionImportApplicationGroup(
                group_key="all",
                title="All",
                entry_keys=tuple(
                    operation.entry_key
                    for operation in operations
                ),
            ),
        ),
    )


def _canonical_plan_sha256(plan):
    serialized = serialize_bulk_collection_import_application_plan(
        plan
    )
    return hashlib.sha256(
        serialized.encode("utf-8")
    ).hexdigest()


class _ApplyContractStore:
    """In-memory Commit 105 store seam for future contract tests."""

    def __init__(
        self,
        *,
        update_sha256=UPDATE_SHARED_SHA256,
        unchanged_sha256=UNCHANGED_SHARED_SHA256,
        create_exists=False,
        fail_commit=False,
    ):
        self.shared = {
            "200": update_sha256,
            "300": unchanged_sha256,
        }
        self.create_exists = create_exists
        self.fail_commit = fail_commit

        self.record_exists_calls = []
        self.shared_sha256_calls = []
        self.begin_count = 0
        self.transactions = []

    def record_exists(self, collection_key):
        self.record_exists_calls.append(collection_key)
        return self.create_exists

    def shared_sha256(self, collection_key):
        self.shared_sha256_calls.append(collection_key)
        return self.shared.get(collection_key)

    def begin_transaction(self):
        self.begin_count += 1
        transaction = _ApplyContractTransaction(
            fail_commit=self.fail_commit
        )
        self.transactions.append(transaction)
        return transaction


class _ApplyContractTransaction:
    def __init__(self, *, fail_commit=False):
        self.fail_commit = fail_commit
        self.created = []
        self.updated = []
        self.commit_count = 0
        self.rollback_count = 0

    def create_record(self, **kwargs):
        self.created.append(kwargs)

    def update_record(self, **kwargs):
        self.updated.append(kwargs)

    def commit(self):
        self.commit_count += 1
        if self.fail_commit:
            raise RuntimeError("commit failure seam")

    def rollback(self):
        self.rollback_count += 1


class BulkCollectionImportApplyContractMixin:
    """Reusable contract for the future production Apply session."""

    def create_session(self, application_plan):
        raise NotImplementedError

    def session_state(self, session):
        raise NotImplementedError

    def session_plan_sha256(self, session):
        raise NotImplementedError

    def confirmation_document(self, session):
        raise NotImplementedError

    def confirm(self, session, application_plan_sha256):
        raise NotImplementedError

    def execute(self, session, store):
        raise NotImplementedError

    def session_result(self, session):
        raise NotImplementedError

    def serialize_confirmation(self, confirmation):
        raise NotImplementedError

    def assert_apply_error(self, callback):
        raise NotImplementedError

    def test_new_session_is_inert_until_explicit_confirmation(self):
        store = _ApplyContractStore()
        session = self.create_session(_application_plan())

        self.assertEqual(
            self.session_state(session),
            "awaiting_confirmation",
        )
        self.assertIsNone(self.confirmation_document(session))
        self.assertIsNone(self.session_result(session))
        self.assertEqual(store.begin_count, 0)
        self.assertEqual(store.record_exists_calls, [])
        self.assertEqual(store.shared_sha256_calls, [])

    def test_plan_sha256_is_canonical_application_document_hash(self):
        plan = _application_plan()
        session = self.create_session(plan)

        self.assertEqual(
            self.session_plan_sha256(session),
            _canonical_plan_sha256(plan),
        )
        self.assertEqual(
            len(self.session_plan_sha256(session)),
            64,
        )

    def test_plan_sha256_changes_when_previewed_write_changes(self):
        first = self.create_session(_application_plan())
        changed_title = self.create_session(
            _application_plan(create_title="Different title")
        )
        changed_freshness = self.create_session(
            _application_plan(update_sha256="d" * 64)
        )

        self.assertNotEqual(
            self.session_plan_sha256(first),
            self.session_plan_sha256(changed_title),
        )
        self.assertNotEqual(
            self.session_plan_sha256(first),
            self.session_plan_sha256(changed_freshness),
        )

    def test_execute_before_confirmation_has_no_store_side_effects(self):
        store = _ApplyContractStore()
        session = self.create_session(_application_plan())

        self.assert_apply_error(
            lambda: self.execute(session, store)
        )

        self.assertEqual(
            self.session_state(session),
            "awaiting_confirmation",
        )
        self.assertEqual(store.record_exists_calls, [])
        self.assertEqual(store.shared_sha256_calls, [])
        self.assertEqual(store.begin_count, 0)

    def test_confirmation_requires_exact_displayed_plan_fingerprint(self):
        session = self.create_session(_application_plan())

        self.assert_apply_error(
            lambda: self.confirm(session, "0" * 64)
        )

        self.assertEqual(
            self.session_state(session),
            "awaiting_confirmation",
        )
        self.assertIsNone(self.confirmation_document(session))

    def test_explicit_confirmation_binds_exact_plan_identity(self):
        session = self.create_session(_application_plan())
        fingerprint = self.session_plan_sha256(session)

        confirmation = self.confirm(session, fingerprint)

        self.assertEqual(
            self.session_state(session),
            "confirmed",
        )
        self.assertEqual(
            confirmation,
            {
                "schema": APPLY_CONFIRMATION_SCHEMA,
                "version": APPLY_CONFIRMATION_VERSION,
                "import_id": "apply-contract-suite",
                "source_sha256": SOURCE_SHA256,
                "application_plan_sha256": fingerprint,
                "confirmed": True,
            },
        )
        self.assertEqual(
            self.confirmation_document(session),
            confirmation,
        )

    def test_confirmation_is_itself_one_way(self):
        session = self.create_session(_application_plan())
        fingerprint = self.session_plan_sha256(session)

        self.confirm(session, fingerprint)

        self.assert_apply_error(
            lambda: self.confirm(session, fingerprint)
        )
        self.assertEqual(
            self.session_state(session),
            "confirmed",
        )

    def test_confirmation_projection_is_detached(self):
        session = self.create_session(_application_plan())
        fingerprint = self.session_plan_sha256(session)
        self.confirm(session, fingerprint)

        document = self.confirmation_document(session)
        document["confirmed"] = False
        document["application_plan_sha256"] = "0" * 64

        clean = self.confirmation_document(session)
        self.assertTrue(clean["confirmed"])
        self.assertEqual(
            clean["application_plan_sha256"],
            fingerprint,
        )

    def test_confirmation_serialization_is_stable_compact_json(self):
        session = self.create_session(_application_plan())
        self.confirm(
            session,
            self.session_plan_sha256(session),
        )
        confirmation = self.confirmation_document(session)

        serialized = self.serialize_confirmation(confirmation)

        self.assertEqual(
            serialized,
            json.dumps(
                json.loads(serialized),
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            ),
        )

    def test_success_executes_exact_plan_once(self):
        store = _ApplyContractStore()
        session = self.create_session(_application_plan())
        self.confirm(
            session,
            self.session_plan_sha256(session),
        )

        result = self.execute(session, store)

        self.assertEqual(
            self.session_state(session),
            "succeeded",
        )
        self.assertIs(self.session_result(session), result)
        self.assertEqual(store.record_exists_calls, ["500"])
        self.assertEqual(
            store.shared_sha256_calls,
            ["200", "300"],
        )
        self.assertEqual(store.begin_count, 1)

        transaction = store.transactions[0]
        self.assertEqual(len(transaction.created), 1)
        self.assertEqual(len(transaction.updated), 1)
        self.assertEqual(transaction.commit_count, 1)
        self.assertEqual(transaction.rollback_count, 0)

        self.assertEqual(
            dict(result.summary),
            {
                "total": 4,
                "created": 1,
                "updated": 1,
                "unchanged": 1,
                "skipped": 1,
            },
        )

    def test_successful_session_cannot_execute_twice(self):
        store = _ApplyContractStore()
        session = self.create_session(_application_plan())
        self.confirm(
            session,
            self.session_plan_sha256(session),
        )
        self.execute(session, store)

        first_begin_count = store.begin_count
        first_preflight = (
            tuple(store.record_exists_calls),
            tuple(store.shared_sha256_calls),
        )

        self.assert_apply_error(
            lambda: self.execute(session, store)
        )

        self.assertEqual(
            self.session_state(session),
            "succeeded",
        )
        self.assertEqual(store.begin_count, first_begin_count)
        self.assertEqual(
            (
                tuple(store.record_exists_calls),
                tuple(store.shared_sha256_calls),
            ),
            first_preflight,
        )

    def test_stale_shared_state_fails_before_transaction_and_is_terminal(self):
        store = _ApplyContractStore(
            update_sha256="e" * 64
        )
        session = self.create_session(_application_plan())
        self.confirm(
            session,
            self.session_plan_sha256(session),
        )

        self.assert_apply_error(
            lambda: self.execute(session, store)
        )

        self.assertEqual(
            self.session_state(session),
            "failed",
        )
        self.assertIsNone(self.session_result(session))
        self.assertEqual(store.begin_count, 0)

        preflight_calls = (
            tuple(store.record_exists_calls),
            tuple(store.shared_sha256_calls),
        )
        self.assert_apply_error(
            lambda: self.execute(session, store)
        )
        self.assertEqual(store.begin_count, 0)
        self.assertEqual(
            (
                tuple(store.record_exists_calls),
                tuple(store.shared_sha256_calls),
            ),
            preflight_calls,
        )

    def test_create_collision_fails_before_transaction_and_is_terminal(self):
        store = _ApplyContractStore(create_exists=True)
        session = self.create_session(_application_plan())
        self.confirm(
            session,
            self.session_plan_sha256(session),
        )

        self.assert_apply_error(
            lambda: self.execute(session, store)
        )

        self.assertEqual(
            self.session_state(session),
            "failed",
        )
        self.assertEqual(store.begin_count, 0)

    def test_atomic_transaction_failure_rolls_back_and_cannot_retry(self):
        store = _ApplyContractStore(fail_commit=True)
        session = self.create_session(_application_plan())
        self.confirm(
            session,
            self.session_plan_sha256(session),
        )

        self.assert_apply_error(
            lambda: self.execute(session, store)
        )

        self.assertEqual(
            self.session_state(session),
            "failed",
        )
        self.assertEqual(store.begin_count, 1)
        transaction = store.transactions[0]
        self.assertEqual(transaction.commit_count, 1)
        self.assertEqual(transaction.rollback_count, 1)

        self.assert_apply_error(
            lambda: self.execute(session, store)
        )
        self.assertEqual(store.begin_count, 1)

    def test_no_change_and_skip_are_not_staged_as_writes(self):
        store = _ApplyContractStore()
        session = self.create_session(_application_plan())
        self.confirm(
            session,
            self.session_plan_sha256(session),
        )

        self.execute(session, store)

        transaction = store.transactions[0]
        self.assertEqual(
            [record["collection_key"] for record in transaction.created],
            ["500"],
        )
        self.assertEqual(
            [record["collection_key"] for record in transaction.updated],
            ["200"],
        )

    def test_failure_requires_new_preview_session_and_confirmation(self):
        failed_store = _ApplyContractStore(
            update_sha256="f" * 64
        )
        failed = self.create_session(_application_plan())
        self.confirm(
            failed,
            self.session_plan_sha256(failed),
        )

        self.assert_apply_error(
            lambda: self.execute(failed, failed_store)
        )
        self.assertEqual(
            self.session_state(failed),
            "failed",
        )

        fresh_plan = _application_plan(update_sha256="f" * 64)
        fresh = self.create_session(fresh_plan)

        self.assertEqual(
            self.session_state(fresh),
            "awaiting_confirmation",
        )
        self.assertNotEqual(
            self.session_plan_sha256(failed),
            self.session_plan_sha256(fresh),
        )

        fresh_store = _ApplyContractStore(
            update_sha256="f" * 64
        )
        self.assert_apply_error(
            lambda: self.execute(fresh, fresh_store)
        )
        self.assertEqual(fresh_store.begin_count, 0)

        self.confirm(
            fresh,
            self.session_plan_sha256(fresh),
        )
        self.execute(fresh, fresh_store)
        self.assertEqual(
            self.session_state(fresh),
            "succeeded",
        )


class BulkCollectionImportApplySpecificationTest(unittest.TestCase):
    """Lock the write boundary before production or UI Apply code."""

    def test_confirmation_has_distinct_bound_schema(self):
        self.assertEqual(
            APPLY_CONFIRMATION_SCHEMA,
            "smwc-bulk-collection-apply-confirmation",
        )
        self.assertEqual(APPLY_CONFIRMATION_VERSION, 1)

    def test_apply_session_has_explicit_nonterminal_and_terminal_states(self):
        self.assertEqual(
            APPLY_SESSION_STATES,
            (
                "awaiting_confirmation",
                "confirmed",
                "succeeded",
                "failed",
            ),
        )
        self.assertEqual(
            APPLY_TERMINAL_STATES,
            ("succeeded", "failed"),
        )

    def test_failed_apply_requires_new_session(self):
        self.assertTrue(APPLY_RETRY_REQUIRES_NEW_SESSION)

    def test_confirmation_fingerprint_is_sha256_of_exact_application_plan(self):
        plan = _application_plan()
        fingerprint = _canonical_plan_sha256(plan)

        self.assertEqual(len(fingerprint), 64)
        self.assertTrue(
            all(
                character in "0123456789abcdef"
                for character in fingerprint
            )
        )

    def test_confirmation_is_not_an_application_action(self):
        self.assertNotIn(
            "apply",
            _application_plan().summary,
        )
        self.assertNotIn(
            "confirm",
            _application_plan().summary,
        )

    def test_write_boundary_reuses_atomic_persistence_executor_contract(self):
        expected_store_methods = (
            "record_exists",
            "shared_sha256",
            "begin_transaction",
        )
        transaction_methods = (
            "create_record",
            "update_record",
            "commit",
            "rollback",
        )

        self.assertEqual(
            expected_store_methods,
            (
                "record_exists",
                "shared_sha256",
                "begin_transaction",
            ),
        )
        self.assertEqual(
            transaction_methods,
            (
                "create_record",
                "update_record",
                "commit",
                "rollback",
            ),
        )


class BulkCollectionImportApplyImplementationTest(
    BulkCollectionImportApplyContractMixin,
    unittest.TestCase,
):
    """Run Commit 126's one-shot Apply contract against production."""

    def create_session(self, application_plan):
        return create_bulk_collection_import_apply_session(
            application_plan
        )

    def session_state(self, session):
        return session.state

    def session_plan_sha256(self, session):
        return session.application_plan_sha256

    def confirmation_document(self, session):
        return bulk_collection_import_apply_confirmation_to_document(
            session
        )

    def confirm(self, session, application_plan_sha256):
        return confirm_bulk_collection_import_apply_session(
            session,
            application_plan_sha256,
        )

    def execute(self, session, store):
        return execute_bulk_collection_import_apply_session(
            session,
            store,
        )

    def session_result(self, session):
        return session.result

    def serialize_confirmation(self, confirmation):
        return serialize_bulk_collection_import_apply_confirmation(
            confirmation
        )

    def assert_apply_error(self, callback):
        with self.assertRaises(BulkCollectionImportApplyError):
            callback()

    def test_production_constants_match_apply_contract(self):
        self.assertEqual(
            BULK_COLLECTION_IMPORT_APPLY_CONFIRMATION_SCHEMA,
            APPLY_CONFIRMATION_SCHEMA,
        )
        self.assertEqual(
            BULK_COLLECTION_IMPORT_APPLY_CONFIRMATION_VERSION,
            APPLY_CONFIRMATION_VERSION,
        )
        self.assertEqual(
            BULK_COLLECTION_IMPORT_APPLY_SESSION_STATES,
            APPLY_SESSION_STATES,
        )
        self.assertEqual(
            BULK_COLLECTION_IMPORT_APPLY_TERMINAL_STATES,
            APPLY_TERMINAL_STATES,
        )

    def test_session_freezes_plan_used_for_execution(self):
        plan = _application_plan()
        session = create_bulk_collection_import_apply_session(plan)
        fingerprint = session.application_plan_sha256

        # The exact canonical plan fingerprint was frozen at session creation.
        self.assertEqual(
            fingerprint,
            _canonical_plan_sha256(plan),
        )

        confirm_bulk_collection_import_apply_session(
            session,
            fingerprint,
        )
        store = _ApplyContractStore()
        result = execute_bulk_collection_import_apply_session(
            session,
            store,
        )

        self.assertEqual(result.import_id, plan.import_id)
        self.assertEqual(store.begin_count, 1)

    def test_malformed_confirmation_serialization_fails_closed(self):
        with self.assertRaises(BulkCollectionImportApplyError):
            serialize_bulk_collection_import_apply_confirmation(
                {
                    "schema": APPLY_CONFIRMATION_SCHEMA,
                    "version": APPLY_CONFIRMATION_VERSION,
                    "import_id": "apply-contract-suite",
                    "source_sha256": SOURCE_SHA256,
                    "application_plan_sha256": "0" * 64,
                    "confirmed": False,
                }
            )

    def test_terminal_failure_keeps_explicit_confirmation_for_audit(self):
        session = create_bulk_collection_import_apply_session(
            _application_plan()
        )
        confirm_bulk_collection_import_apply_session(
            session,
            session.application_plan_sha256,
        )
        store = _ApplyContractStore(
            update_sha256="e" * 64
        )

        with self.assertRaises(BulkCollectionImportApplyError):
            execute_bulk_collection_import_apply_session(
                session,
                store,
            )

        self.assertEqual(session.state, "failed")
        confirmation = (
            bulk_collection_import_apply_confirmation_to_document(
                session
            )
        )
        self.assertTrue(confirmation["confirmed"])
        self.assertEqual(
            confirmation["application_plan_sha256"],
            session.application_plan_sha256,
        )



if __name__ == "__main__":
    unittest.main(verbosity=2)
