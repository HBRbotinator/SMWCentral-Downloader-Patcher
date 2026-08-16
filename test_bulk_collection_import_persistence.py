"""Specification tests for atomic bulk Collection import persistence."""

from __future__ import annotations

import json
import unittest
from copy import deepcopy

from bulk_collection_import_persistence import (
    BULK_COLLECTION_IMPORT_PERSISTENCE_RESULT_SCHEMA,
    BULK_COLLECTION_IMPORT_PERSISTENCE_RESULT_VERSION,
    BULK_COLLECTION_IMPORT_PERSISTENCE_OUTCOMES,
    BulkCollectionImportPersistenceError,
    bulk_collection_import_persistence_result_to_document,
    execute_bulk_collection_import_application_plan,
    serialize_bulk_collection_import_persistence_result,
)


PERSISTENCE_RESULT_SCHEMA = "smwc-bulk-collection-persistence-result"
PERSISTENCE_RESULT_VERSION = 1
PERSISTENCE_OUTCOMES = ("created", "updated", "unchanged", "skipped")
SOURCE_SHA256 = "e" * 64

APPLICATION_PLAN = {
    "schema": "smwc-bulk-collection-application-plan",
    "version": 1,
    "import_id": "persistence-suite",
    "source_sha256": SOURCE_SHA256,
    "summary": {
        "total": 5,
        "create_record": 1,
        "update_record": 2,
        "no_change": 1,
        "skip": 1,
    },
    "operations": [
        {
            "entry_key": "new-entry",
            "action": "create_record",
            "collection_key": "collection-new",
            "expected_shared_sha256": None,
            "title_value": "New Entry",
            "source_references": [
                {"source": "kaizoff", "external_id": "new-entry"}
            ],
            "source_reference_additions": [],
            "attributes": {"authors": ["Author One"]},
            "attribute_changes": [],
            "warnings": [],
        },
        {
            "entry_key": "source-update",
            "action": "update_record",
            "collection_key": "collection-source-update",
            "expected_shared_sha256": "1" * 64,
            "title_value": None,
            "source_references": [],
            "source_reference_additions": [
                {"source": "kaizoff", "external_id": "source-update"}
            ],
            "attributes": {},
            "attribute_changes": [
                {"field": "difficulty", "value": "Kaizo: Intermediate"}
            ],
            "warnings": [],
        },
        {
            "entry_key": "metadata-update",
            "action": "update_record",
            "collection_key": "collection-metadata-update",
            "expected_shared_sha256": "2" * 64,
            "title_value": "Updated Title",
            "source_references": [],
            "source_reference_additions": [],
            "attributes": {},
            "attribute_changes": [{"field": "exit_count", "value": 12}],
            "warnings": [],
        },
        {
            "entry_key": "unchanged",
            "action": "no_change",
            "collection_key": "collection-unchanged",
            "expected_shared_sha256": "3" * 64,
            "title_value": None,
            "source_references": [],
            "source_reference_additions": [],
            "attributes": {},
            "attribute_changes": [],
            "warnings": [],
        },
        {
            "entry_key": "skipped",
            "action": "skip",
            "collection_key": None,
            "expected_shared_sha256": None,
            "title_value": None,
            "source_references": [],
            "source_reference_additions": [],
            "attributes": {},
            "attribute_changes": [],
            "warnings": [
                "identity_review_required",
                "identity_conflict",
                "source_identity_conflict",
            ],
        },
    ],
    "groups": [
        {
            "group_key": "all",
            "title": "All",
            "entry_keys": [
                "new-entry", "source-update", "metadata-update",
                "unchanged", "skipped",
            ],
        }
    ],
}

INITIAL_RECORDS = {
    "collection-source-update": {
        "collection_key": "collection-source-update",
        "title": "Source Update",
        "source_references": [{"source": "smwc", "external_id": "100"}],
        "attributes": {"authors": ["Author Two"]},
        "user_state": {
            "completed": True,
            "personal_rating": 5,
            "notes": "keep me",
            "save_paths": ["C:/saves/source.srm"],
        },
    },
    "collection-metadata-update": {
        "collection_key": "collection-metadata-update",
        "title": "Old Title",
        "source_references": [{"source": "smwc", "external_id": "200"}],
        "attributes": {"authors": ["Author Three"], "exit_count": 10},
        "user_state": {"completed": False, "planner_state": "playing"},
    },
    "collection-unchanged": {
        "collection_key": "collection-unchanged",
        "title": "Unchanged",
        "source_references": [{"source": "smwc", "external_id": "300"}],
        "attributes": {"authors": ["Author Four"]},
        "user_state": {"notes": "unchanged user state"},
    },
}


class BulkCollectionImportPersistenceContractMixin:
    """Reusable behavior suite for an atomic persistence executor."""

    def execute_application_plan(self, application_plan, store):
        raise NotImplementedError

    def make_store(self, records, fingerprints):
        raise NotImplementedError

    def result_to_document(self, result):
        raise NotImplementedError

    def serialize_result(self, result):
        raise NotImplementedError

    def assert_persistence_error(self, application_plan, store):
        raise NotImplementedError

    def _fingerprints(self):
        return {
            "collection-source-update": "1" * 64,
            "collection-metadata-update": "2" * 64,
            "collection-unchanged": "3" * 64,
        }

    def _store(self):
        return self.make_store(deepcopy(INITIAL_RECORDS), self._fingerprints())

    def test_successful_apply_is_atomic_and_ordered(self):
        store = self._store()
        result = self.execute_application_plan(deepcopy(APPLICATION_PLAN), store)
        self.assertEqual(
            tuple(item.outcome for item in result.items),
            ("created", "updated", "updated", "unchanged", "skipped"),
        )
        self.assertEqual(store.commit_count, 1)

    def test_create_initializes_empty_user_state(self):
        store = self._store()
        self.execute_application_plan(deepcopy(APPLICATION_PLAN), store)
        created = store.records["collection-new"]
        self.assertEqual(created["title"], "New Entry")
        self.assertEqual(created["user_state"], {})

    def test_updates_preserve_user_owned_state_exactly(self):
        store = self._store()
        source_state = deepcopy(store.records["collection-source-update"]["user_state"])
        metadata_state = deepcopy(store.records["collection-metadata-update"]["user_state"])
        self.execute_application_plan(deepcopy(APPLICATION_PLAN), store)
        self.assertEqual(
            store.records["collection-source-update"]["user_state"], source_state
        )
        self.assertEqual(
            store.records["collection-metadata-update"]["user_state"], metadata_state
        )

    def test_update_applies_only_explicit_shared_changes(self):
        store = self._store()
        self.execute_application_plan(deepcopy(APPLICATION_PLAN), store)
        source = store.records["collection-source-update"]
        self.assertEqual(source["title"], "Source Update")
        self.assertEqual(source["attributes"]["authors"], ["Author Two"])
        self.assertEqual(source["attributes"]["difficulty"], "Kaizo: Intermediate")
        self.assertEqual(len(source["source_references"]), 2)
        metadata = store.records["collection-metadata-update"]
        self.assertEqual(metadata["title"], "Updated Title")
        self.assertEqual(metadata["attributes"]["exit_count"], 12)
        self.assertEqual(metadata["attributes"]["authors"], ["Author Three"])

    def test_no_change_and_skip_are_true_non_writes(self):
        store = self._store()
        unchanged = deepcopy(store.records["collection-unchanged"])
        self.execute_application_plan(deepcopy(APPLICATION_PLAN), store)
        self.assertEqual(store.records["collection-unchanged"], unchanged)
        self.assertEqual(store.write_counts["collection-unchanged"], 0)

    def test_all_fingerprints_are_preflighted_before_first_write(self):
        store = self._store()
        store.fingerprints["collection-metadata-update"] = "f" * 64
        before = deepcopy(store.records)
        self.assert_persistence_error(deepcopy(APPLICATION_PLAN), store)
        self.assertEqual(store.records, before)
        self.assertEqual(store.total_write_count, 0)
        self.assertEqual(store.commit_count, 0)

    def test_no_change_fingerprint_is_also_preflighted(self):
        store = self._store()
        store.fingerprints["collection-unchanged"] = "f" * 64
        self.assert_persistence_error(deepcopy(APPLICATION_PLAN), store)
        self.assertEqual(store.total_write_count, 0)

    def test_create_collision_is_preflighted_before_writes(self):
        store = self._store()
        store.records["collection-new"] = {
            "collection_key": "collection-new",
            "title": "Already Exists",
            "source_references": [],
            "attributes": {},
            "user_state": {},
        }
        before = deepcopy(store.records)
        self.assert_persistence_error(deepcopy(APPLICATION_PLAN), store)
        self.assertEqual(store.records, before)
        self.assertEqual(store.total_write_count, 0)

    def test_staged_failure_rolls_back_everything(self):
        store = self._store()
        store.fail_on_write_number = 2
        before = deepcopy(store.records)
        self.assert_persistence_error(deepcopy(APPLICATION_PLAN), store)
        self.assertEqual(store.records, before)
        self.assertEqual(store.commit_count, 0)
        self.assertGreaterEqual(store.rollback_count, 1)

    def test_application_plan_is_not_mutated(self):
        plan = deepcopy(APPLICATION_PLAN)
        original = deepcopy(plan)
        self.execute_application_plan(plan, self._store())
        self.assertEqual(plan, original)

    def test_result_is_bound_to_source_and_contains_no_user_state(self):
        result = self.execute_application_plan(deepcopy(APPLICATION_PLAN), self._store())
        self.assertEqual(result.import_id, "persistence-suite")
        self.assertEqual(result.source_sha256, SOURCE_SHA256)
        serialized = self.serialize_result(result)
        for forbidden in (
            "completed", "personal_rating", "notes", "save_paths",
            "rom_paths", "planner_state",
        ):
            self.assertNotIn(forbidden, serialized)

    def test_result_is_immutable_and_projection_detached(self):
        result = self.execute_application_plan(deepcopy(APPLICATION_PLAN), self._store())
        with self.assertRaises((AttributeError, TypeError)):
            result.import_id = "changed"
        document = self.result_to_document(result)
        document["summary"]["updated"] = 99
        self.assertEqual(self.result_to_document(result)["summary"]["updated"], 2)

    def test_result_summary_and_serialization_are_deterministic(self):
        result = self.execute_application_plan(deepcopy(APPLICATION_PLAN), self._store())
        self.assertEqual(
            dict(result.summary),
            {"total": 5, "created": 1, "updated": 2, "unchanged": 1, "skipped": 1},
        )
        serialized = self.serialize_result(result)
        self.assertEqual(
            serialized,
            json.dumps(json.loads(serialized), ensure_ascii=False, allow_nan=False, separators=(",", ":")),
        )


class BulkCollectionImportPersistenceSpecificationTest(unittest.TestCase):
    """Validate the persistence boundary itself."""

    def test_schema_version_and_outcomes_are_fixed(self):
        self.assertEqual(PERSISTENCE_RESULT_SCHEMA, "smwc-bulk-collection-persistence-result")
        self.assertEqual(PERSISTENCE_RESULT_VERSION, 1)
        self.assertEqual(PERSISTENCE_OUTCOMES, ("created", "updated", "unchanged", "skipped"))

    def test_application_plan_contains_no_review_required(self):
        self.assertNotIn(
            "review_required",
            tuple(item["action"] for item in APPLICATION_PLAN["operations"]),
        )

    def test_existing_targets_have_fingerprints_and_nonwrites_are_explicit(self):
        for item in APPLICATION_PLAN["operations"]:
            if item["action"] in ("update_record", "no_change"):
                self.assertEqual(len(item["expected_shared_sha256"]), 64)
            if item["action"] in ("create_record", "skip"):
                self.assertIsNone(item["expected_shared_sha256"])

    def test_contract_is_storage_neutral(self):
        serialized = json.dumps(APPLICATION_PLAN)
        for forbidden in ("database_path", "sqlite", "json_path", "planner", "wheel"):
            self.assertNotIn(forbidden, serialized)


class _InMemoryPersistenceStore:
    def __init__(self, records, fingerprints):
        self.records = deepcopy(records)
        self.fingerprints = dict(fingerprints)
        self.commit_count = 0
        self.rollback_count = 0
        self.total_write_count = 0
        self.write_counts = {
            key: 0
            for key in self.records
        }
        self.fail_on_write_number = None

    def record_exists(self, collection_key):
        return collection_key in self.records

    def shared_sha256(self, collection_key):
        if collection_key not in self.records:
            return None
        return self.fingerprints.get(collection_key)

    def begin_transaction(self):
        return _InMemoryPersistenceTransaction(self)


class _InMemoryPersistenceTransaction:
    def __init__(self, store):
        self.store = store
        self.records = deepcopy(store.records)
        self.write_counts = dict(store.write_counts)
        self.write_number = 0
        self.finished = False

    def _before_write(self, collection_key):
        self.write_number += 1
        self.store.total_write_count += 1
        if (
            self.store.fail_on_write_number is not None
            and self.write_number
            == self.store.fail_on_write_number
        ):
            raise RuntimeError("injected staged write failure")
        self.write_counts.setdefault(collection_key, 0)
        self.write_counts[collection_key] += 1

    def create_record(
        self,
        *,
        collection_key,
        title,
        source_references,
        attributes,
        user_state,
    ):
        self._before_write(collection_key)
        if collection_key in self.records:
            raise RuntimeError("create collision")
        self.records[collection_key] = {
            "collection_key": collection_key,
            "title": title,
            "source_references": deepcopy(source_references),
            "attributes": deepcopy(attributes),
            "user_state": deepcopy(user_state),
        }

    def update_record(
        self,
        *,
        collection_key,
        title_value,
        source_reference_additions,
        attribute_changes,
    ):
        self._before_write(collection_key)
        record = self.records[collection_key]

        if title_value is not None:
            record["title"] = title_value

        existing_references = {
            (value["source"], value["external_id"])
            for value in record["source_references"]
        }
        for reference in source_reference_additions:
            key = (
                reference["source"],
                reference["external_id"],
            )
            if key not in existing_references:
                record["source_references"].append(
                    deepcopy(reference)
                )
                existing_references.add(key)

        for change in attribute_changes:
            record["attributes"][change["field"]] = deepcopy(
                change["value"]
            )

    def commit(self):
        if self.finished:
            raise RuntimeError("transaction already finished")
        self.store.records = self.records
        self.store.write_counts = self.write_counts
        self.store.commit_count += 1
        self.finished = True

    def rollback(self):
        if self.finished:
            return
        self.store.rollback_count += 1
        self.finished = True


class BulkCollectionImportPersistenceImplementationTest(
    BulkCollectionImportPersistenceContractMixin,
    unittest.TestCase,
):
    """Run the persistence contract against production code."""

    def execute_application_plan(self, application_plan, store):
        return execute_bulk_collection_import_application_plan(
            application_plan,
            store,
        )

    def make_store(self, records, fingerprints):
        return _InMemoryPersistenceStore(
            records,
            fingerprints,
        )

    def result_to_document(self, result):
        return bulk_collection_import_persistence_result_to_document(
            result
        )

    def serialize_result(self, result):
        return serialize_bulk_collection_import_persistence_result(
            result
        )

    def assert_persistence_error(self, application_plan, store):
        with self.assertRaises(BulkCollectionImportPersistenceError):
            execute_bulk_collection_import_application_plan(
                application_plan,
                store,
            )

    def test_production_constants_match_specification(self):
        self.assertEqual(
            BULK_COLLECTION_IMPORT_PERSISTENCE_RESULT_SCHEMA,
            PERSISTENCE_RESULT_SCHEMA,
        )
        self.assertEqual(
            BULK_COLLECTION_IMPORT_PERSISTENCE_RESULT_VERSION,
            PERSISTENCE_RESULT_VERSION,
        )
        self.assertEqual(
            BULK_COLLECTION_IMPORT_PERSISTENCE_OUTCOMES,
            PERSISTENCE_OUTCOMES,
        )

    def test_preflight_does_not_open_transaction_on_stale_state(self):
        store = self._store()
        store.fingerprints["collection-source-update"] = "f" * 64
        transaction_calls = []
        original = store.begin_transaction

        def tracked_begin_transaction():
            transaction_calls.append(True)
            return original()

        store.begin_transaction = tracked_begin_transaction

        self.assert_persistence_error(
            deepcopy(APPLICATION_PLAN),
            store,
        )
        self.assertEqual(transaction_calls, [])

    def test_success_commits_exactly_create_and_update_writes(self):
        store = self._store()

        self.execute_application_plan(
            deepcopy(APPLICATION_PLAN),
            store,
        )

        self.assertEqual(store.total_write_count, 3)
        self.assertEqual(
            store.write_counts["collection-source-update"],
            1,
        )
        self.assertEqual(
            store.write_counts["collection-metadata-update"],
            1,
        )
        self.assertEqual(
            store.write_counts["collection-unchanged"],
            0,
        )

    def test_duplicate_source_addition_is_idempotent_in_store_adapter(self):
        store = self._store()
        store.records["collection-source-update"][
            "source_references"
        ].append(
            {
                "source": "kaizoff",
                "external_id": "source-update",
            }
        )

        self.execute_application_plan(
            deepcopy(APPLICATION_PLAN),
            store,
        )

        references = store.records["collection-source-update"][
            "source_references"
        ]
        matches = [
            value
            for value in references
            if (
                value["source"],
                value["external_id"],
            )
            == ("kaizoff", "source-update")
        ]
        self.assertEqual(len(matches), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
