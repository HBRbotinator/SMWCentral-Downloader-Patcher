"""Specification tests for bulk Collection import orchestration."""

from __future__ import annotations

import hashlib
import json
import unittest
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory

from bulk_collection_import import (
    bulk_collection_import_to_document,
)
from bulk_collection_import_identity import (
    bulk_collection_identity_plan_to_document,
)
from bulk_collection_import_merge import (
    bulk_collection_import_merge_plan_to_document,
)
from bulk_collection_import_planning import (
    BULK_COLLECTION_IMPORT_PLANNING_STAGES,
    BulkCollectionImportPlanningError,
    plan_bulk_collection_import_file,
)
from bulk_collection_import_preview import (
    bulk_collection_import_preview_to_document,
)


PLANNING_STAGES = ("load", "identity", "preview", "merge")

IMPORT_DOCUMENT = {
    "schema": "smwc-bulk-collection-import",
    "version": 1,
    "import_id": "planning-session-suite",
    "title": "Planning session suite",
    "entries": [
        {
            "entry_key": "hybrid-match",
            "title": "Hybrid Match",
            "source_references": [
                {"source": "smwc", "external_id": "500"},
                {
                    "source": "kaizoff",
                    "external_id": "hybrid-match",
                },
            ],
            "attributes": {
                "authors": ["Author One"],
                "difficulty": "Kaizo: Beginner",
            },
        },
        {
            "entry_key": "brand-new",
            "title": "Brand New",
            "source_references": [
                {
                    "source": "kaizoff",
                    "external_id": "brand-new",
                }
            ],
            "attributes": {"authors": ["Author Two"]},
        },
        {
            "entry_key": "needs-review",
            "title": "Shared Name",
            "source_references": [],
            "attributes": {"authors": ["Shared Author"]},
        },
    ],
    "groups": [
        {
            "group_key": "ready",
            "title": "Ready",
            "entry_keys": ["hybrid-match", "brand-new"],
        },
        {
            "group_key": "review",
            "title": "Review",
            "entry_keys": ["needs-review"],
        },
    ],
}

COLLECTION_IDENTITIES = (
    {
        "collection_key": "collection-hybrid",
        "title": "Hybrid Match",
        "aliases": [],
        "attributes": {"authors": ["Author One"]},
        "source_references": [
            {"source": "smwc", "external_id": "500"}
        ],
    },
    {
        "collection_key": "collection-review-a",
        "title": "Shared Name",
        "aliases": [],
        "attributes": {"authors": ["Shared Author"]},
        "source_references": [],
    },
    {
        "collection_key": "collection-review-b",
        "title": "Shared Name",
        "aliases": [],
        "attributes": {"authors": ["Shared Author"]},
        "source_references": [],
    },
    {
        "collection_key": "collection-unrelated",
        "title": "Unrelated",
        "aliases": [],
        "attributes": {"authors": ["Someone Else"]},
        "source_references": [
            {"source": "smwc", "external_id": "999"}
        ],
    },
)

COLLECTION_RECORDS = (
    {
        "collection_key": "collection-hybrid",
        "title": "Hybrid Match",
        "source_references": [
            {"source": "smwc", "external_id": "500"}
        ],
        "attributes": {"authors": ["Author One"]},
        "user_state": {
            "completed": True,
            "personal_rating": 5,
            "notes": "Must never enter the merge plan",
        },
    },
    {
        "collection_key": "collection-review-a",
        "title": "Shared Name",
        "source_references": [],
        "attributes": {"authors": ["Shared Author"]},
        "user_state": {"completed": False},
    },
    {
        "collection_key": "collection-review-b",
        "title": "Shared Name",
        "source_references": [],
        "attributes": {"authors": ["Shared Author"]},
        "user_state": {"completed": False},
    },
    {
        "collection_key": "collection-unrelated",
        "title": "Unrelated",
        "source_references": [
            {"source": "smwc", "external_id": "999"}
        ],
        "attributes": {},
        "user_state": {},
    },
)


class BulkCollectionImportPlanningContractMixin:
    """Reusable behavior suite for the production planning coordinator."""

    def plan_import_file(
        self,
        path,
        collection_identities,
        collection_records,
    ):
        raise NotImplementedError

    def import_to_document(self, import_document):
        raise NotImplementedError

    def identity_to_document(self, identity_plan):
        raise NotImplementedError

    def preview_to_document(self, preview_plan):
        raise NotImplementedError

    def merge_to_document(self, merge_plan):
        raise NotImplementedError

    def assert_planning_error(
        self,
        expected_stage,
        path,
        collection_identities,
        collection_records,
    ):
        raise NotImplementedError

    def _write_import(self, directory):
        payload = json.dumps(
            IMPORT_DOCUMENT,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        path = Path(directory) / "bulk-import.json"
        path.write_bytes(payload)
        return path, payload

    def _plan(self, directory):
        path, payload = self._write_import(directory)
        session = self.plan_import_file(
            path,
            deepcopy(COLLECTION_IDENTITIES),
            deepcopy(COLLECTION_RECORDS),
        )
        return session, path, payload

    def test_valid_file_builds_complete_read_only_session(self):
        with TemporaryDirectory() as directory:
            session, _, payload = self._plan(directory)
            self.assertEqual(session.source_name, "bulk-import.json")
            self.assertEqual(session.byte_count, len(payload))
            self.assertEqual(
                session.sha256,
                hashlib.sha256(payload).hexdigest(),
            )
            for value in (
                session.document.import_id,
                session.identity_plan.import_id,
                session.preview_plan.import_id,
                session.merge_plan.import_id,
            ):
                self.assertEqual(value, "planning-session-suite")

    def test_pipeline_preserves_entry_order_across_all_stages(self):
        with TemporaryDirectory() as directory:
            session, _, _ = self._plan(directory)
            expected = (
                "hybrid-match",
                "brand-new",
                "needs-review",
            )
            self.assertEqual(
                tuple(e.entry_key for e in session.document.entries),
                expected,
            )
            self.assertEqual(
                tuple(
                    r.entry_key
                    for r in session.identity_plan.resolutions
                ),
                expected,
            )
            self.assertEqual(
                tuple(i.entry_key for i in session.preview_plan.items),
                expected,
            )
            self.assertEqual(
                tuple(i.entry_key for i in session.merge_plan.items),
                expected,
            )

    def test_hybrid_match_new_and_review_paths_are_preserved(self):
        with TemporaryDirectory() as directory:
            session, _, _ = self._plan(directory)
            self.assertEqual(
                tuple(
                    i.status
                    for i in session.identity_plan.resolutions
                ),
                ("matched_source", "new", "ambiguous"),
            )
            self.assertEqual(
                tuple(i.outcome for i in session.preview_plan.items),
                (
                    "match_existing",
                    "add_new",
                    "review_required",
                ),
            )
            self.assertEqual(
                tuple(i.action for i in session.merge_plan.items),
                (
                    "update_record",
                    "create_record",
                    "review_required",
                ),
            )

    def test_only_matched_records_are_forwarded_to_merge_planning(self):
        with TemporaryDirectory() as directory:
            session, _, _ = self._plan(directory)
            self.assertEqual(
                session.merge_plan.items[0].collection_keys,
                ("collection-hybrid",),
            )
            self.assertEqual(
                session.merge_plan.items[2].collection_keys,
                (
                    "collection-review-a",
                    "collection-review-b",
                ),
            )

    def test_proposed_hybrid_link_survives_to_merge_plan(self):
        with TemporaryDirectory() as directory:
            session, _, _ = self._plan(directory)
            item = session.merge_plan.items[0]
            self.assertEqual(item.action, "update_record")
            self.assertEqual(
                tuple(
                    (r.source, r.external_id)
                    for r in item.source_reference_additions
                ),
                (("kaizoff", "hybrid-match"),),
            )

    def test_user_owned_state_never_enters_any_output_plan(self):
        with TemporaryDirectory() as directory:
            session, _, _ = self._plan(directory)
            serialized = json.dumps(
                {
                    "identity": self.identity_to_document(
                        session.identity_plan
                    ),
                    "preview": self.preview_to_document(
                        session.preview_plan
                    ),
                    "merge": self.merge_to_document(
                        session.merge_plan
                    ),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
            for forbidden in (
                "completed",
                "personal_rating",
                "notes",
                "save_paths",
                "rom_paths",
                "planner_state",
            ):
                self.assertNotIn(forbidden, serialized)

    def test_session_and_all_nested_plans_are_immutable(self):
        with TemporaryDirectory() as directory:
            session, _, _ = self._plan(directory)
            with self.assertRaises((AttributeError, TypeError)):
                session.source_name = "changed.json"
            with self.assertRaises((AttributeError, TypeError)):
                session.document.title = "Changed"
            with self.assertRaises((AttributeError, TypeError)):
                session.identity_plan.import_id = "changed"
            with self.assertRaises((AttributeError, TypeError)):
                session.preview_plan.summary["total"] = 0
            with self.assertRaises((AttributeError, TypeError)):
                session.merge_plan.summary["total"] = 0

    def test_session_is_detached_from_source_and_input_snapshots(self):
        with TemporaryDirectory() as directory:
            identities = deepcopy(COLLECTION_IDENTITIES)
            records = deepcopy(COLLECTION_RECORDS)
            path, payload = self._write_import(directory)
            session = self.plan_import_file(
                path,
                identities,
                records,
            )
            path.write_text("{}", encoding="utf-8")
            identities[0]["title"] = "Changed"
            records[0]["attributes"]["authors"][0] = "Changed"
            self.assertEqual(session.byte_count, len(payload))
            self.assertEqual(
                session.document.entries[0].title,
                "Hybrid Match",
            )
            self.assertEqual(
                session.merge_plan.items[0]
                .attribute_decisions[0].imported_value,
                ("Author One",),
            )

    def test_planning_does_not_mutate_input_snapshots(self):
        with TemporaryDirectory() as directory:
            identities = deepcopy(COLLECTION_IDENTITIES)
            records = deepcopy(COLLECTION_RECORDS)
            original_identities = deepcopy(identities)
            original_records = deepcopy(records)
            path, _ = self._write_import(directory)
            self.plan_import_file(path, identities, records)
            self.assertEqual(identities, original_identities)
            self.assertEqual(records, original_records)

    def test_load_failures_report_load_stage(self):
        with TemporaryDirectory() as directory:
            self.assert_planning_error(
                "load",
                Path(directory) / "missing.json",
                deepcopy(COLLECTION_IDENTITIES),
                deepcopy(COLLECTION_RECORDS),
            )

    def test_identity_failures_report_identity_stage(self):
        with TemporaryDirectory() as directory:
            path, _ = self._write_import(directory)
            identities = list(deepcopy(COLLECTION_IDENTITIES))
            duplicate = deepcopy(identities[0])
            duplicate["collection_key"] = "collection-duplicate"
            identities.append(duplicate)
            self.assert_planning_error(
                "identity",
                path,
                identities,
                deepcopy(COLLECTION_RECORDS),
            )

    def test_merge_failures_report_merge_stage(self):
        with TemporaryDirectory() as directory:
            path, _ = self._write_import(directory)
            records = tuple(
                r
                for r in deepcopy(COLLECTION_RECORDS)
                if r["collection_key"] != "collection-hybrid"
            )
            self.assert_planning_error(
                "merge",
                path,
                deepcopy(COLLECTION_IDENTITIES),
                records,
            )

    def test_source_file_is_never_modified(self):
        with TemporaryDirectory() as directory:
            path, payload = self._write_import(directory)
            before = path.stat()
            self.plan_import_file(
                path,
                deepcopy(COLLECTION_IDENTITIES),
                deepcopy(COLLECTION_RECORDS),
            )
            after = path.stat()
            self.assertEqual(path.read_bytes(), payload)
            self.assertEqual(after.st_size, before.st_size)
            self.assertEqual(after.st_mtime_ns, before.st_mtime_ns)


class BulkCollectionImportPlanningSpecificationTest(
    unittest.TestCase
):
    """Validate the orchestration contract itself."""

    def test_stage_names_are_fixed(self):
        self.assertEqual(
            PLANNING_STAGES,
            ("load", "identity", "preview", "merge"),
        )

    def test_fixture_contains_hybrid_source_identity(self):
        references = IMPORT_DOCUMENT["entries"][0][
            "source_references"
        ]
        self.assertEqual(
            {
                (item["source"], item["external_id"])
                for item in references
            },
            {
                ("smwc", "500"),
                ("kaizoff", "hybrid-match"),
            },
        )

    def test_groups_remain_destination_neutral(self):
        serialized = json.dumps(IMPORT_DOCUMENT["groups"])
        for forbidden in (
            "destination",
            "planner",
            "wheel",
            "collection_position",
        ):
            self.assertNotIn(forbidden, serialized)

    def test_contract_exposes_required_implementation_tests(self):
        names = {
            name
            for name in dir(
                BulkCollectionImportPlanningContractMixin
            )
            if name.startswith("test_")
        }
        self.assertEqual(
            names,
            {
                "test_hybrid_match_new_and_review_paths_are_preserved",
                "test_identity_failures_report_identity_stage",
                "test_load_failures_report_load_stage",
                "test_merge_failures_report_merge_stage",
                "test_only_matched_records_are_forwarded_to_merge_planning",
                "test_pipeline_preserves_entry_order_across_all_stages",
                "test_planning_does_not_mutate_input_snapshots",
                "test_proposed_hybrid_link_survives_to_merge_plan",
                "test_session_and_all_nested_plans_are_immutable",
                "test_session_is_detached_from_source_and_input_snapshots",
                "test_source_file_is_never_modified",
                "test_user_owned_state_never_enters_any_output_plan",
                "test_valid_file_builds_complete_read_only_session",
            },
        )


class BulkCollectionImportPlanningImplementationTest(
    BulkCollectionImportPlanningContractMixin,
    unittest.TestCase,
):
    """Run the orchestration contract against production code."""

    def plan_import_file(
        self,
        path,
        collection_identities,
        collection_records,
    ):
        return plan_bulk_collection_import_file(
            path,
            collection_identities,
            collection_records,
        )

    def import_to_document(self, import_document):
        return bulk_collection_import_to_document(import_document)

    def identity_to_document(self, identity_plan):
        return bulk_collection_identity_plan_to_document(
            identity_plan
        )

    def preview_to_document(self, preview_plan):
        return bulk_collection_import_preview_to_document(
            preview_plan
        )

    def merge_to_document(self, merge_plan):
        return bulk_collection_import_merge_plan_to_document(
            merge_plan
        )

    def assert_planning_error(
        self,
        expected_stage,
        path,
        collection_identities,
        collection_records,
    ):
        with self.assertRaises(
            BulkCollectionImportPlanningError
        ) as context:
            plan_bulk_collection_import_file(
                path,
                collection_identities,
                collection_records,
            )
        self.assertEqual(
            context.exception.stage,
            expected_stage,
        )
        self.assertIsNotNone(context.exception.__cause__)

    def test_production_stage_names_match_specification(self):
        self.assertEqual(
            BULK_COLLECTION_IMPORT_PLANNING_STAGES,
            PLANNING_STAGES,
        )

    def test_unrelated_records_are_not_required_by_merge_planner(self):
        with TemporaryDirectory() as directory:
            path, _ = self._write_import(directory)
            records = [
                deepcopy(COLLECTION_RECORDS[0]),
                {
                    "collection_key": "unrelated-minimal",
                    "this": "record is deliberately not merge-shaped",
                },
            ]

            session = plan_bulk_collection_import_file(
                path,
                deepcopy(COLLECTION_IDENTITIES),
                records,
            )

            self.assertEqual(
                session.merge_plan.items[0].collection_keys,
                ("collection-hybrid",),
            )

    def test_duplicate_matched_records_fail_in_merge_stage(self):
        with TemporaryDirectory() as directory:
            path, _ = self._write_import(directory)
            matched = deepcopy(COLLECTION_RECORDS[0])
            records = [matched, deepcopy(matched)]

            self.assert_planning_error(
                "merge",
                path,
                deepcopy(COLLECTION_IDENTITIES),
                records,
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
