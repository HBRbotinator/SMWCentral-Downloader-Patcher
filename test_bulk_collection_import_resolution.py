"""Specification tests for post-review bulk Collection resolution planning."""

from __future__ import annotations

import json
import unittest


RESOLUTION_PLAN_SCHEMA = "smwc-bulk-collection-resolution-plan"
RESOLUTION_PLAN_VERSION = 1
RESOLUTION_ACTIONS = (
    "create_record",
    "update_record",
    "no_change",
    "review_required",
    "skip",
)
SOURCE_SHA256 = "c" * 64

IMPORT_ENTRIES = {
    "safe-update": {
        "entry_key": "safe-update",
        "title": "Safe Update",
        "source_references": [
            {"source": "smwc", "external_id": "100"},
            {"source": "kaizoff", "external_id": "safe-update"},
        ],
        "attributes": {
            "authors": ["Author One"],
            "difficulty": "Kaizo: Beginner",
        },
    },
    "safe-create": {
        "entry_key": "safe-create",
        "title": "Safe Create",
        "source_references": [
            {"source": "kaizoff", "external_id": "safe-create"}
        ],
        "attributes": {"authors": ["Author Two"]},
    },
    "safe-no-change": {
        "entry_key": "safe-no-change",
        "title": "No Change",
        "source_references": [
            {"source": "smwc", "external_id": "200"}
        ],
        "attributes": {"authors": ["Author Three"]},
    },
    "metadata-review": {
        "entry_key": "metadata-review",
        "title": "Metadata Review",
        "source_references": [
            {"source": "smwc", "external_id": "300"}
        ],
        "attributes": {
            "authors": ["Author Four"],
            "exit_count": 12,
            "difficulty": "Kaizo: Intermediate",
        },
    },
    "ambiguous-select": {
        "entry_key": "ambiguous-select",
        "title": "Ambiguous Select",
        "source_references": [],
        "attributes": {
            "authors": ["Author Five"],
            "exit_count": 15,
        },
    },
    "ambiguous-create": {
        "entry_key": "ambiguous-create",
        "title": "Ambiguous Create",
        "source_references": [],
        "attributes": {"authors": ["Author Six"]},
    },
    "hard-conflict": {
        "entry_key": "hard-conflict",
        "title": "Hard Conflict",
        "source_references": [
            {"source": "smwc", "external_id": "400"},
            {"source": "kaizoff", "external_id": "hard-conflict"},
        ],
        "attributes": {"authors": ["Author Seven"]},
    },
}

MERGE_ITEMS = (
    {
        "entry_key": "safe-update",
        "action": "update_record",
        "collection_keys": ["collection-safe-update"],
        "title_decision": {
            "field": "title",
            "action": "unchanged",
            "existing_value": "Safe Update",
            "imported_value": "Safe Update",
        },
        "source_reference_additions": [
            {"source": "kaizoff", "external_id": "safe-update"}
        ],
        "attribute_decisions": [
            {
                "field": "authors",
                "action": "unchanged",
                "existing_value": ["Author One"],
                "imported_value": ["Author One"],
            },
            {
                "field": "difficulty",
                "action": "add_missing",
                "existing_value": None,
                "imported_value": "Kaizo: Beginner",
            },
        ],
        "warnings": [],
    },
    {
        "entry_key": "safe-create",
        "action": "create_record",
        "collection_keys": [],
        "title_decision": {
            "field": "title",
            "action": "set_new",
            "existing_value": None,
            "imported_value": "Safe Create",
        },
        "source_reference_additions": [
            {"source": "kaizoff", "external_id": "safe-create"}
        ],
        "attribute_decisions": [
            {
                "field": "authors",
                "action": "set_new",
                "existing_value": None,
                "imported_value": ["Author Two"],
            }
        ],
        "warnings": [],
    },
    {
        "entry_key": "safe-no-change",
        "action": "no_change",
        "collection_keys": ["collection-no-change"],
        "title_decision": {
            "field": "title",
            "action": "unchanged",
            "existing_value": "No Change",
            "imported_value": "No Change",
        },
        "source_reference_additions": [],
        "attribute_decisions": [
            {
                "field": "authors",
                "action": "unchanged",
                "existing_value": ["Author Three"],
                "imported_value": ["Author Three"],
            }
        ],
        "warnings": [],
    },
    {
        "entry_key": "metadata-review",
        "action": "review_required",
        "collection_keys": ["collection-metadata"],
        "title_decision": {
            "field": "title",
            "action": "unchanged",
            "existing_value": "Metadata Review",
            "imported_value": "Metadata Review",
        },
        "source_reference_additions": [],
        "attribute_decisions": [
            {
                "field": "authors",
                "action": "unchanged",
                "existing_value": ["Author Four"],
                "imported_value": ["Author Four"],
            },
            {
                "field": "exit_count",
                "action": "review_conflict",
                "existing_value": 10,
                "imported_value": 12,
            },
            {
                "field": "difficulty",
                "action": "add_missing",
                "existing_value": None,
                "imported_value": "Kaizo: Intermediate",
            },
        ],
        "warnings": ["metadata_conflict"],
    },
    {
        "entry_key": "ambiguous-select",
        "action": "review_required",
        "collection_keys": ["collection-select-a", "collection-select-b"],
        "title_decision": None,
        "source_reference_additions": [],
        "attribute_decisions": [],
        "warnings": ["identity_review_required", "identity_ambiguous"],
    },
    {
        "entry_key": "ambiguous-create",
        "action": "review_required",
        "collection_keys": ["collection-create-a", "collection-create-b"],
        "title_decision": None,
        "source_reference_additions": [],
        "attribute_decisions": [],
        "warnings": ["identity_review_required", "identity_ambiguous"],
    },
    {
        "entry_key": "hard-conflict",
        "action": "review_required",
        "collection_keys": ["collection-hard-a", "collection-hard-b"],
        "title_decision": None,
        "source_reference_additions": [],
        "attribute_decisions": [],
        "warnings": [
            "identity_review_required",
            "identity_conflict",
            "source_identity_conflict",
        ],
    },
)

REVIEW_DECISIONS = (
    {
        "entry_key": "metadata-review",
        "action": "resolve_metadata",
        "selected_collection_key": "collection-metadata",
        "title_choice": None,
        "attribute_choices": [
            {"field": "exit_count", "choice": "use_imported"}
        ],
    },
    {
        "entry_key": "ambiguous-select",
        "action": "select_existing",
        "selected_collection_key": "collection-select-b",
        "title_choice": None,
        "attribute_choices": [],
    },
    {
        "entry_key": "ambiguous-create",
        "action": "create_new",
        "selected_collection_key": None,
        "title_choice": None,
        "attribute_choices": [],
    },
    {
        "entry_key": "hard-conflict",
        "action": "skip",
        "selected_collection_key": None,
        "title_choice": None,
        "attribute_choices": [],
    },
)

COLLECTION_RECORDS = (
    {
        "collection_key": "collection-safe-update",
        "title": "Safe Update",
        "source_references": [{"source": "smwc", "external_id": "100"}],
        "attributes": {"authors": ["Author One"]},
        "user_state": {"completed": True, "notes": "never import"},
    },
    {
        "collection_key": "collection-no-change",
        "title": "No Change",
        "source_references": [{"source": "smwc", "external_id": "200"}],
        "attributes": {"authors": ["Author Three"]},
        "user_state": {"personal_rating": 5},
    },
    {
        "collection_key": "collection-metadata",
        "title": "Metadata Review",
        "source_references": [{"source": "smwc", "external_id": "300"}],
        "attributes": {"authors": ["Author Four"], "exit_count": 10},
        "user_state": {"completed": False},
    },
    {
        "collection_key": "collection-select-a",
        "title": "Ambiguous Select",
        "source_references": [],
        "attributes": {"authors": ["Author Five"], "exit_count": 15},
        "user_state": {},
    },
    {
        "collection_key": "collection-select-b",
        "title": "Ambiguous Select",
        "source_references": [],
        "attributes": {"authors": ["Author Five"], "exit_count": 14},
        "user_state": {"notes": "selection can expose conflict"},
    },
)

GROUPS = (
    {
        "group_key": "first",
        "title": "First",
        "entry_keys": [
            "safe-update",
            "safe-create",
            "safe-no-change",
            "metadata-review",
        ],
    },
    {
        "group_key": "reviewed",
        "title": "Reviewed",
        "entry_keys": [
            "ambiguous-select",
            "ambiguous-create",
            "hard-conflict",
        ],
    },
)


class BulkCollectionImportResolutionContractMixin:
    """Reusable behavior suite for the production resolution planner."""

    def build_resolution_plan(
        self,
        import_entries,
        merge_items,
        review_decisions,
        collection_records,
        groups,
        import_id,
        source_sha256,
    ):
        raise NotImplementedError

    def resolution_to_document(self, plan):
        raise NotImplementedError

    def serialize_resolution(self, plan):
        raise NotImplementedError

    def assert_resolution_error(self, **kwargs):
        raise NotImplementedError

    def _build(self, **overrides):
        values = {
            "import_entries": IMPORT_ENTRIES,
            "merge_items": MERGE_ITEMS,
            "review_decisions": REVIEW_DECISIONS,
            "collection_records": COLLECTION_RECORDS,
            "groups": GROUPS,
            "import_id": "resolution-suite",
            "source_sha256": SOURCE_SHA256,
        }
        values.update(overrides)
        return self.build_resolution_plan(**values)

    def test_resolution_preserves_import_order_and_groups(self):
        plan = self._build()
        self.assertEqual(
            tuple(item.entry_key for item in plan.items),
            tuple(IMPORT_ENTRIES),
        )
        self.assertEqual(
            tuple((group.group_key, group.entry_keys) for group in plan.groups),
            tuple(
                (group["group_key"], tuple(group["entry_keys"]))
                for group in GROUPS
            ),
        )

    def test_safe_merge_actions_flow_through_unchanged(self):
        plan = self._build()
        self.assertEqual(
            tuple(item.action for item in plan.items[:3]),
            ("update_record", "create_record", "no_change"),
        )

    def test_metadata_review_choice_resolves_to_safe_update(self):
        plan = self._build()
        item = next(
            value for value in plan.items
            if value.entry_key == "metadata-review"
        )
        self.assertEqual(item.action, "update_record")
        self.assertEqual(item.collection_key, "collection-metadata")
        self.assertEqual(
            tuple(
                (change.field, change.value)
                for change in item.attribute_changes
            ),
            (
                ("exit_count", 12),
                ("difficulty", "Kaizo: Intermediate"),
            ),
        )

    def test_keep_existing_conflict_choice_emits_no_change_for_field(self):
        decisions = list(REVIEW_DECISIONS)
        metadata = dict(decisions[0])
        metadata["attribute_choices"] = [
            {"field": "exit_count", "choice": "keep_existing"}
        ]
        decisions[0] = metadata
        plan = self._build(review_decisions=tuple(decisions))
        item = next(
            value for value in plan.items
            if value.entry_key == "metadata-review"
        )
        self.assertEqual(
            tuple(change.field for change in item.attribute_changes),
            ("difficulty",),
        )

    def test_ambiguous_create_new_becomes_create_record(self):
        plan = self._build()
        item = next(
            value for value in plan.items
            if value.entry_key == "ambiguous-create"
        )
        self.assertEqual(item.action, "create_record")
        self.assertIsNone(item.collection_key)
        self.assertEqual(item.title_value, "Ambiguous Create")
        self.assertEqual(
            dict(item.attributes),
            {"authors": ("Author Six",)},
        )

    def test_hard_conflict_skip_becomes_explicit_skip(self):
        plan = self._build()
        item = next(
            value for value in plan.items
            if value.entry_key == "hard-conflict"
        )
        self.assertEqual(item.action, "skip")
        self.assertIsNone(item.collection_key)
        self.assertEqual(
            item.warnings,
            (
                "identity_review_required",
                "identity_conflict",
                "source_identity_conflict",
            ),
        )

    def test_selected_ambiguous_record_is_conservatively_replanned(self):
        plan = self._build()
        item = next(
            value for value in plan.items
            if value.entry_key == "ambiguous-select"
        )
        self.assertEqual(item.action, "review_required")
        self.assertEqual(item.collection_key, "collection-select-b")
        self.assertEqual(item.warnings, ("metadata_conflict",))
        self.assertEqual(
            tuple(
                (
                    conflict.field,
                    conflict.existing_value,
                    conflict.imported_value,
                )
                for conflict in item.conflicts
            ),
            (("exit_count", 14, 15),),
        )

    def test_selected_record_without_conflicts_can_finish_immediately(self):
        records = list(COLLECTION_RECORDS)
        records[-1] = {
            **records[-1],
            "attributes": {
                "authors": ["Author Five"],
                "exit_count": 15,
            },
        }
        plan = self._build(collection_records=tuple(records))
        item = next(
            value for value in plan.items
            if value.entry_key == "ambiguous-select"
        )
        self.assertEqual(item.action, "no_change")
        self.assertEqual(item.collection_key, "collection-select-b")
        self.assertEqual(item.conflicts, ())

    def test_missing_or_duplicate_selected_record_is_rejected(self):
        missing = tuple(
            record for record in COLLECTION_RECORDS
            if record["collection_key"] != "collection-select-b"
        )
        base = {
            "import_entries": IMPORT_ENTRIES,
            "merge_items": MERGE_ITEMS,
            "review_decisions": REVIEW_DECISIONS,
            "groups": GROUPS,
            "import_id": "resolution-suite",
            "source_sha256": SOURCE_SHA256,
        }
        self.assert_resolution_error(
            collection_records=missing,
            **base,
        )
        self.assert_resolution_error(
            collection_records=COLLECTION_RECORDS + (COLLECTION_RECORDS[-1],),
            **base,
        )

    def test_review_decisions_must_cover_review_rows_in_order(self):
        base = {
            "import_entries": IMPORT_ENTRIES,
            "merge_items": MERGE_ITEMS,
            "collection_records": COLLECTION_RECORDS,
            "groups": GROUPS,
            "import_id": "resolution-suite",
            "source_sha256": SOURCE_SHA256,
        }
        self.assert_resolution_error(
            review_decisions=REVIEW_DECISIONS[:-1],
            **base,
        )
        reordered = list(REVIEW_DECISIONS)
        reordered[-1], reordered[-2] = reordered[-2], reordered[-1]
        self.assert_resolution_error(
            review_decisions=tuple(reordered),
            **base,
        )

    def test_resolution_is_bound_to_exact_source_hash(self):
        plan = self._build()
        self.assertEqual(plan.source_sha256, SOURCE_SHA256)
        self.assert_resolution_error(
            import_entries=IMPORT_ENTRIES,
            merge_items=MERGE_ITEMS,
            review_decisions=REVIEW_DECISIONS,
            collection_records=COLLECTION_RECORDS,
            groups=GROUPS,
            import_id="resolution-suite",
            source_sha256="invalid",
        )

    def test_user_owned_state_never_enters_resolution_plan(self):
        serialized = self.serialize_resolution(self._build())
        for forbidden in (
            "completed",
            "personal_rating",
            "notes",
            "save_paths",
            "rom_paths",
            "planner_state",
        ):
            self.assertNotIn(forbidden, serialized)

    def test_resolution_plan_is_immutable_and_projection_detached(self):
        plan = self._build()
        with self.assertRaises((AttributeError, TypeError)):
            plan.import_id = "changed"
        with self.assertRaises((AttributeError, TypeError)):
            plan.items[0].action = "skip"

        projected = self.resolution_to_document(plan)
        projected["summary"]["skip"] = 999
        projected["items"][0]["warnings"].append("changed")
        clean = self.resolution_to_document(plan)
        self.assertNotEqual(clean["summary"]["skip"], 999)
        self.assertNotIn("changed", clean["items"][0]["warnings"])

    def test_summary_is_derived_from_final_actions(self):
        plan = self._build()
        self.assertEqual(
            dict(plan.summary),
            {
                "total": 7,
                "create_record": 2,
                "update_record": 2,
                "no_change": 1,
                "review_required": 1,
                "skip": 1,
            },
        )

    def test_serialization_is_stable_compact_json(self):
        serialized = self.serialize_resolution(self._build())
        self.assertEqual(
            serialized,
            json.dumps(
                json.loads(serialized),
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            ),
        )


class BulkCollectionImportResolutionSpecificationTest(unittest.TestCase):
    """Validate the resolution-plan contract itself."""

    def test_schema_version_and_actions_are_fixed(self):
        self.assertEqual(
            RESOLUTION_PLAN_SCHEMA,
            "smwc-bulk-collection-resolution-plan",
        )
        self.assertEqual(RESOLUTION_PLAN_VERSION, 1)
        self.assertEqual(
            RESOLUTION_ACTIONS,
            (
                "create_record",
                "update_record",
                "no_change",
                "review_required",
                "skip",
            ),
        )

    def test_selected_identity_can_require_a_second_review_round(self):
        self.assertEqual(
            IMPORT_ENTRIES["ambiguous-select"]["attributes"]["exit_count"],
            15,
        )
        selected = next(
            record for record in COLLECTION_RECORDS
            if record["collection_key"] == "collection-select-b"
        )
        self.assertEqual(selected["attributes"]["exit_count"], 14)

    def test_hard_conflict_fixture_is_skip_only(self):
        self.assertEqual(REVIEW_DECISIONS[-1]["action"], "skip")
        self.assertIn("identity_conflict", MERGE_ITEMS[-1]["warnings"])
        self.assertIn(
            "source_identity_conflict",
            MERGE_ITEMS[-1]["warnings"],
        )

    def test_contract_contains_no_collection_write_operation(self):
        for name in ("apply", "save", "persist", "delete", "overwrite"):
            self.assertNotIn(name, RESOLUTION_ACTIONS)

    def test_groups_are_still_destination_neutral(self):
        serialized = json.dumps(GROUPS)
        for forbidden in (
            "destination",
            "planner",
            "wheel",
            "collection_position",
        ):
            self.assertNotIn(forbidden, serialized)


if __name__ == "__main__":
    unittest.main(verbosity=2)
