"""Specification for the final read-only bulk-import application preview."""

from __future__ import annotations

import copy
import hashlib
import json
import unittest
from types import MappingProxyType

from bulk_collection_import_resolution import (
    BulkCollectionImportResolutionAttributeChange,
    BulkCollectionImportResolutionGroup,
    BulkCollectionImportResolutionItem,
    BulkCollectionImportResolutionPlan,
    BulkCollectionImportResolutionSourceReference,
)


APPLICATION_PREVIEW_SCHEMA = "smwc-bulk-collection-application-plan"
APPLICATION_PREVIEW_VERSION = 1
APPLICATION_PREVIEW_ACTIONS = (
    "create_record",
    "update_record",
    "no_change",
    "skip",
)

LOCAL_KEY_PREFIX = "usr_import_"
LOCAL_KEY_HEX_LENGTH = 16
SOURCE_SHA256 = "b" * 64


def _resolution_plan(*, include_review=False):
    review_action = (
        "review_required"
        if include_review
        else "skip"
    )
    items = (
        BulkCollectionImportResolutionItem(
            entry_key="new-smwc",
            action="create_record",
            collection_key=None,
            title_value="New SMWC Hack",
            source_reference_additions=(
                BulkCollectionImportResolutionSourceReference(
                    source="smwc",
                    external_id="500",
                ),
                BulkCollectionImportResolutionSourceReference(
                    source="kaizoff",
                    external_id="mirror-500",
                ),
            ),
            attributes=MappingProxyType(
                {
                    "authors": ("Author One",),
                    "difficulty": "Kaizo: Beginner",
                }
            ),
            attribute_changes=(),
            conflicts=(),
            warnings=(),
        ),
        BulkCollectionImportResolutionItem(
            entry_key="new-external",
            action="create_record",
            collection_key=None,
            title_value="External Only",
            source_reference_additions=(
                BulkCollectionImportResolutionSourceReference(
                    source="kaizoff",
                    external_id="external-only",
                ),
            ),
            attributes=MappingProxyType(
                {
                    "authors": ("Author Two",),
                }
            ),
            attribute_changes=(),
            conflicts=(),
            warnings=(),
        ),
        BulkCollectionImportResolutionItem(
            entry_key="safe-update",
            action="update_record",
            collection_key="200",
            title_value=None,
            source_reference_additions=(
                BulkCollectionImportResolutionSourceReference(
                    source="kaizoff",
                    external_id="mirror-200",
                ),
            ),
            attributes=MappingProxyType({}),
            attribute_changes=(
                BulkCollectionImportResolutionAttributeChange(
                    field="difficulty",
                    value="Kaizo: Intermediate",
                ),
            ),
            conflicts=(),
            warnings=(),
        ),
        BulkCollectionImportResolutionItem(
            entry_key="unchanged",
            action="no_change",
            collection_key="300",
            title_value=None,
            source_reference_additions=(),
            attributes=MappingProxyType({}),
            attribute_changes=(),
            conflicts=(),
            warnings=(),
        ),
        BulkCollectionImportResolutionItem(
            entry_key="skipped",
            action=review_action,
            collection_key=None,
            title_value=None,
            source_reference_additions=(),
            attributes=MappingProxyType({}),
            attribute_changes=(),
            conflicts=(
                ()
                if not include_review
                else ()
            ),
            warnings=(
                "source_identity_conflict",
            ),
        ),
    )

    summary = {
        "total": 5,
        "create_record": 2,
        "update_record": 1,
        "no_change": 1,
        "review_required": 1 if include_review else 0,
        "skip": 0 if include_review else 1,
    }

    return BulkCollectionImportResolutionPlan(
        schema="smwc-bulk-collection-resolution-plan",
        version=1,
        import_id="application-preview-suite",
        source_sha256=SOURCE_SHA256,
        summary=MappingProxyType(summary),
        items=items,
        groups=(
            BulkCollectionImportResolutionGroup(
                group_key="first",
                title="First",
                entry_keys=(
                    "new-smwc",
                    "new-external",
                    "safe-update",
                ),
            ),
            BulkCollectionImportResolutionGroup(
                group_key="second",
                title="Second",
                entry_keys=(
                    "unchanged",
                    "skipped",
                ),
            ),
        ),
    )


def _collection_data():
    return {
        "200": {
            "title": "Safe Update",
            "authors": ["Author Three"],
            "current_difficulty": "Kaizo: Beginner",
            "exits": 12,
            "date": "2025-01-01",
            "completed": True,
            "completed_date": "2026-08-01",
            "personal_rating": 5,
            "notes": "private note must stay outside preview",
            "file_path": "C:/ROMs/safe-update.sfc",
            "additional_paths": ["D:/Archive/safe-update.sfc"],
        },
        "300": {
            "title": "Unchanged",
            "authors": ["Author Four"],
            "current_difficulty": "Standard: Hard",
            "exits": 8,
            "date": "2024-12-01",
            "completed": False,
            "personal_rating": 3,
            "notes": "another private note",
            "time_to_beat": "03:14:15",
        },
    }


class BulkCollectionImportApplicationPreviewContractMixin:
    """Reusable requirements for the final no-write application preview."""

    def build_preview(self, resolution_plan, collection_data):
        raise NotImplementedError

    def preview_to_document(self, preview):
        raise NotImplementedError

    def serialize_preview(self, preview):
        raise NotImplementedError

    def assert_preview_error(self, resolution_plan, collection_data):
        raise NotImplementedError

    def test_preview_reuses_existing_application_plan_contract(self):
        preview = self.build_preview(
            _resolution_plan(),
            _collection_data(),
        )

        self.assertEqual(preview.schema, APPLICATION_PREVIEW_SCHEMA)
        self.assertEqual(preview.version, APPLICATION_PREVIEW_VERSION)
        self.assertEqual(
            preview.import_id,
            "application-preview-suite",
        )
        self.assertEqual(preview.source_sha256, SOURCE_SHA256)

    def test_preview_requires_fully_resolved_resolution_plan(self):
        self.assert_preview_error(
            _resolution_plan(include_review=True),
            _collection_data(),
        )

    def test_preview_allocates_canonical_smwc_key_for_create(self):
        preview = self.build_preview(
            _resolution_plan(),
            _collection_data(),
        )
        operation = preview.operations[0]

        self.assertEqual(operation.entry_key, "new-smwc")
        self.assertEqual(operation.action, "create_record")
        self.assertEqual(operation.collection_key, "500")
        self.assertIsNone(operation.expected_shared_sha256)

    def test_preview_allocates_deterministic_local_key_for_external_create(self):
        first = self.build_preview(
            _resolution_plan(),
            _collection_data(),
        )
        second = self.build_preview(
            _resolution_plan(),
            _collection_data(),
        )

        first_key = first.operations[1].collection_key
        second_key = second.operations[1].collection_key

        self.assertEqual(first_key, second_key)
        self.assertTrue(first_key.startswith(LOCAL_KEY_PREFIX))
        suffix = first_key[len(LOCAL_KEY_PREFIX):]
        self.assertEqual(len(suffix), LOCAL_KEY_HEX_LENGTH)
        self.assertTrue(
            all(character in "0123456789abcdef" for character in suffix)
        )

    def test_allocated_create_key_must_not_collide_with_live_collection(self):
        collection = _collection_data()
        collection["500"] = {
            "title": "Already Existing",
            "authors": ["Someone"],
            "current_difficulty": "Standard: Normal",
            "exits": 5,
            "date": "2020-01-01",
        }

        self.assert_preview_error(
            _resolution_plan(),
            collection,
        )

    def test_update_is_bound_to_fresh_shared_collection_state(self):
        preview = self.build_preview(
            _resolution_plan(),
            _collection_data(),
        )
        update = preview.operations[2]

        self.assertEqual(update.action, "update_record")
        self.assertEqual(update.collection_key, "200")
        self.assertEqual(len(update.expected_shared_sha256), 64)
        self.assertEqual(
            update.expected_shared_sha256,
            update.expected_shared_sha256.lower(),
        )

    def test_no_change_is_also_bound_to_fresh_shared_state(self):
        preview = self.build_preview(
            _resolution_plan(),
            _collection_data(),
        )
        unchanged = preview.operations[3]

        self.assertEqual(unchanged.action, "no_change")
        self.assertEqual(unchanged.collection_key, "300")
        self.assertEqual(len(unchanged.expected_shared_sha256), 64)

    def test_shared_collection_change_changes_application_fingerprint(self):
        before = self.build_preview(
            _resolution_plan(),
            _collection_data(),
        )

        changed = _collection_data()
        changed["200"]["exits"] = 13
        after = self.build_preview(
            _resolution_plan(),
            changed,
        )

        self.assertNotEqual(
            before.operations[2].expected_shared_sha256,
            after.operations[2].expected_shared_sha256,
        )

    def test_user_owned_state_does_not_change_application_fingerprint(self):
        before = self.build_preview(
            _resolution_plan(),
            _collection_data(),
        )

        changed = _collection_data()
        changed["200"]["completed"] = False
        changed["200"]["completed_date"] = "2026-08-22"
        changed["200"]["personal_rating"] = 1
        changed["200"]["notes"] = "changed private note"
        changed["200"]["file_path"] = "Z:/Different/private.sfc"
        changed["200"]["additional_paths"] = []
        after = self.build_preview(
            _resolution_plan(),
            changed,
        )

        self.assertEqual(
            before.operations[2].expected_shared_sha256,
            after.operations[2].expected_shared_sha256,
        )

    def test_missing_existing_target_fails_closed(self):
        collection = _collection_data()
        collection.pop("200")

        self.assert_preview_error(
            _resolution_plan(),
            collection,
        )

    def test_preview_summary_matches_exact_final_actions(self):
        preview = self.build_preview(
            _resolution_plan(),
            _collection_data(),
        )

        self.assertEqual(
            dict(preview.summary),
            {
                "total": 5,
                "create_record": 2,
                "update_record": 1,
                "no_change": 1,
                "skip": 1,
            },
        )

    def test_operation_and_group_order_are_preserved(self):
        plan = _resolution_plan()
        preview = self.build_preview(
            plan,
            _collection_data(),
        )

        self.assertEqual(
            tuple(operation.entry_key for operation in preview.operations),
            tuple(item.entry_key for item in plan.items),
        )
        self.assertEqual(
            tuple(
                (group.group_key, group.entry_keys)
                for group in preview.groups
            ),
            tuple(
                (group.group_key, group.entry_keys)
                for group in plan.groups
            ),
        )

    def test_create_preview_contains_shared_import_data_only(self):
        preview = self.build_preview(
            _resolution_plan(),
            _collection_data(),
        )
        create = preview.operations[0]

        self.assertEqual(create.title_value, "New SMWC Hack")
        self.assertEqual(
            tuple(
                (reference.source, reference.external_id)
                for reference in create.source_references
            ),
            (
                ("smwc", "500"),
                ("kaizoff", "mirror-500"),
            ),
        )
        self.assertEqual(
            dict(create.attributes),
            {
                "authors": ("Author One",),
                "difficulty": "Kaizo: Beginner",
            },
        )

    def test_update_preview_contains_only_explicit_shared_changes(self):
        preview = self.build_preview(
            _resolution_plan(),
            _collection_data(),
        )
        update = preview.operations[2]

        self.assertEqual(update.title_value, None)
        self.assertEqual(
            tuple(
                (reference.source, reference.external_id)
                for reference in update.source_reference_additions
            ),
            (("kaizoff", "mirror-200"),),
        )
        self.assertEqual(
            tuple(
                (change.field, change.value)
                for change in update.attribute_changes
            ),
            (("difficulty", "Kaizo: Intermediate"),),
        )

    def test_skip_has_no_write_target_or_fingerprint(self):
        preview = self.build_preview(
            _resolution_plan(),
            _collection_data(),
        )
        skipped = preview.operations[4]

        self.assertEqual(skipped.action, "skip")
        self.assertIsNone(skipped.collection_key)
        self.assertIsNone(skipped.expected_shared_sha256)
        self.assertIsNone(skipped.title_value)
        self.assertEqual(skipped.source_references, ())
        self.assertEqual(skipped.source_reference_additions, ())
        self.assertEqual(skipped.attribute_changes, ())

    def test_preview_document_never_contains_user_owned_collection_state(self):
        preview = self.build_preview(
            _resolution_plan(),
            _collection_data(),
        )
        document = self.preview_to_document(preview)
        encoded = json.dumps(document, ensure_ascii=False)

        for forbidden in (
            "completed_date",
            "personal_rating",
            "private note",
            "file_path",
            "additional_paths",
            "time_to_beat",
            "C:/ROMs/",
            "Z:/Different/",
        ):
            self.assertNotIn(forbidden, encoded)

    def test_preview_projection_is_detached_from_live_collection(self):
        collection = _collection_data()
        preview = self.build_preview(
            _resolution_plan(),
            collection,
        )
        document = self.preview_to_document(preview)

        collection["200"]["title"] = "Mutated Later"
        document["operations"][0]["title_value"] = "UI Mutation"

        clean = self.preview_to_document(preview)

        self.assertEqual(
            clean["operations"][0]["title_value"],
            "New SMWC Hack",
        )
        self.assertEqual(
            preview.operations[2].collection_key,
            "200",
        )

    def test_serialization_is_stable_compact_json(self):
        preview = self.build_preview(
            _resolution_plan(),
            _collection_data(),
        )
        serialized = self.serialize_preview(preview)

        self.assertEqual(
            serialized,
            json.dumps(
                json.loads(serialized),
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            ),
        )


class BulkCollectionImportApplicationPreviewSpecificationTest(
    unittest.TestCase
):
    """Lock the final preview boundary before production/UI wiring."""

    def test_final_preview_reuses_existing_application_schema(self):
        self.assertEqual(
            APPLICATION_PREVIEW_SCHEMA,
            "smwc-bulk-collection-application-plan",
        )
        self.assertEqual(APPLICATION_PREVIEW_VERSION, 1)
        self.assertEqual(
            APPLICATION_PREVIEW_ACTIONS,
            (
                "create_record",
                "update_record",
                "no_change",
                "skip",
            ),
        )

    def test_final_preview_is_after_all_review_rounds(self):
        self.assertNotIn(
            "review_required",
            APPLICATION_PREVIEW_ACTIONS,
        )

    def test_final_preview_allocates_real_keys_but_does_not_apply(self):
        self.assertEqual(LOCAL_KEY_PREFIX, "usr_import_")
        self.assertEqual(LOCAL_KEY_HEX_LENGTH, 16)
        self.assertNotIn("apply", APPLICATION_PREVIEW_ACTIONS)
        self.assertNotIn("save", APPLICATION_PREVIEW_ACTIONS)

    def test_shared_fingerprint_is_sha256_not_user_state(self):
        canonical = {
            "collection_key": "200",
            "title": "Example",
            "source_references": [
                {"source": "smwc", "external_id": "200"}
            ],
            "attributes": {
                "authors": ["Author"],
                "exit_count": 12,
            },
        }
        payload = json.dumps(
            canonical,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        fingerprint = hashlib.sha256(payload).hexdigest()

        self.assertEqual(len(fingerprint), 64)
        self.assertNotIn("completed", canonical)
        self.assertNotIn("notes", canonical)


if __name__ == "__main__":
    unittest.main(verbosity=2)
