"""Specification tests for atomic bulk Collection import persistence."""

from __future__ import annotations

import json
import unittest
from copy import deepcopy


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


if __name__ == "__main__":
    unittest.main(verbosity=2)
