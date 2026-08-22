"""Specification for second-round bulk-import metadata review."""

from __future__ import annotations

import json
import unittest
from copy import deepcopy
from types import MappingProxyType

from bulk_collection_import_second_review import (
    SECOND_REVIEW_ACTIONS as PRODUCTION_SECOND_REVIEW_ACTIONS,
    SECOND_REVIEW_CONFLICT_CHOICES as PRODUCTION_CONFLICT_CHOICES,
    SECOND_REVIEW_DECISION_SCHEMA as PRODUCTION_DECISION_SCHEMA,
    SECOND_REVIEW_DECISION_VERSION as PRODUCTION_DECISION_VERSION,
    SECOND_REVIEW_FORM_SCHEMA as PRODUCTION_FORM_SCHEMA,
    SECOND_REVIEW_FORM_VERSION as PRODUCTION_FORM_VERSION,
    BulkCollectionImportSecondReviewError,
    build_bulk_collection_import_second_review_document,
    build_bulk_collection_import_second_review_form,
    bulk_collection_import_second_review_form_to_document,
    refine_bulk_collection_import_resolution_plan,
    serialize_bulk_collection_import_second_review_document,
)

from bulk_collection_import_resolution import (
    BulkCollectionImportResolutionAttributeChange,
    BulkCollectionImportResolutionConflict,
    BulkCollectionImportResolutionGroup,
    BulkCollectionImportResolutionItem,
    BulkCollectionImportResolutionPlan,
    BulkCollectionImportResolutionSourceReference,
)


SECOND_REVIEW_FORM_SCHEMA = (
    "smwc-bulk-collection-second-review-form"
)
SECOND_REVIEW_FORM_VERSION = 1
SECOND_REVIEW_DECISION_SCHEMA = (
    "smwc-bulk-collection-second-review-decisions"
)
SECOND_REVIEW_DECISION_VERSION = 1

SECOND_REVIEW_ACTIONS = (
    "resolve_metadata",
    "skip",
)
SECOND_REVIEW_CONFLICT_CHOICES = (
    "keep_existing",
    "use_imported",
)

SOURCE_SHA256 = "a" * 64


def _resolution_plan():
    items = (
        BulkCollectionImportResolutionItem(
            entry_key="safe-add",
            action="create_record",
            collection_key=None,
            title_value="Safe Add",
            source_reference_additions=(),
            attributes=MappingProxyType(
                {"authors": ("Author One",)}
            ),
            attribute_changes=(),
            conflicts=(),
            warnings=(),
        ),
        BulkCollectionImportResolutionItem(
            entry_key="selected",
            action="review_required",
            collection_key="usr_7",
            title_value=None,
            source_reference_additions=(
                BulkCollectionImportResolutionSourceReference(
                    source="kaizoff",
                    external_id="ko-7",
                ),
            ),
            attributes=MappingProxyType({}),
            attribute_changes=(
                BulkCollectionImportResolutionAttributeChange(
                    field="release_date",
                    value="2025-04-03",
                ),
            ),
            conflicts=(
                BulkCollectionImportResolutionConflict(
                    field="title",
                    existing_value="Existing Candidate",
                    imported_value="Imported Candidate",
                ),
                BulkCollectionImportResolutionConflict(
                    field="exit_count",
                    existing_value=14,
                    imported_value=15,
                ),
            ),
            warnings=("metadata_conflict",),
        ),
        BulkCollectionImportResolutionItem(
            entry_key="safe-update",
            action="update_record",
            collection_key="200",
            title_value=None,
            source_reference_additions=(),
            attributes=MappingProxyType({}),
            attribute_changes=(
                BulkCollectionImportResolutionAttributeChange(
                    field="difficulty",
                    value="Expert",
                ),
            ),
            conflicts=(),
            warnings=(),
        ),
        BulkCollectionImportResolutionItem(
            entry_key="skipped",
            action="skip",
            collection_key=None,
            title_value=None,
            source_reference_additions=(),
            attributes=MappingProxyType({}),
            attribute_changes=(),
            conflicts=(),
            warnings=("source_identity_conflict",),
        ),
    )

    return BulkCollectionImportResolutionPlan(
        schema="smwc-bulk-collection-resolution-plan",
        version=1,
        import_id="second-review-suite",
        source_sha256=SOURCE_SHA256,
        summary=MappingProxyType(
            {
                "total": 4,
                "create_record": 1,
                "update_record": 1,
                "no_change": 0,
                "review_required": 1,
                "skip": 1,
            }
        ),
        items=items,
        groups=(
            BulkCollectionImportResolutionGroup(
                group_key="all",
                title="All",
                entry_keys=tuple(
                    item.entry_key for item in items
                ),
            ),
        ),
    )


class BulkCollectionImportSecondReviewContractMixin:
    """Reusable contract for follow-up metadata decisions."""

    def build_form(self, resolution_plan):
        raise NotImplementedError

    def form_to_document(self, form):
        raise NotImplementedError

    def build_decision_document(self, form, selections):
        raise NotImplementedError

    def refine_resolution(self, resolution_plan, decisions):
        raise NotImplementedError

    def serialize_decisions(self, document):
        raise NotImplementedError

    def assert_form_error(self, resolution_plan):
        raise NotImplementedError

    def assert_selection_error(self, form, selections):
        raise NotImplementedError

    def assert_refinement_error(self, resolution_plan, decisions):
        raise NotImplementedError

    def test_form_contains_only_newly_blocked_resolution_rows(self):
        form = self.build_form(_resolution_plan())

        self.assertEqual(
            tuple(item.entry_key for item in form.items),
            ("selected",),
        )

    def test_form_is_bound_to_import_source_and_resolution_state(self):
        form = self.build_form(_resolution_plan())

        self.assertEqual(form.import_id, "second-review-suite")
        self.assertEqual(form.source_sha256, SOURCE_SHA256)
        self.assertEqual(
            len(form.resolution_review_sha256),
            64,
        )
        self.assertEqual(
            form.resolution_review_sha256,
            form.resolution_review_sha256.lower(),
        )

    def test_second_review_is_metadata_only(self):
        item = self.build_form(_resolution_plan()).items[0]

        self.assertEqual(
            item.allowed_actions,
            ("resolve_metadata", "skip"),
        )
        self.assertEqual(item.collection_key, "usr_7")
        self.assertEqual(
            tuple(conflict.field for conflict in item.conflicts),
            ("title", "exit_count"),
        )

    def test_form_preserves_safe_pending_changes_as_context(self):
        item = self.build_form(_resolution_plan()).items[0]

        self.assertEqual(
            tuple(
                (
                    reference.source,
                    reference.external_id,
                )
                for reference
                in item.source_reference_additions
            ),
            (("kaizoff", "ko-7"),),
        )
        self.assertEqual(
            tuple(
                (change.field, change.value)
                for change in item.attribute_changes
            ),
            (("release_date", "2025-04-03"),),
        )

    def test_no_second_round_choice_is_preselected(self):
        document = self.form_to_document(
            self.build_form(_resolution_plan())
        )
        item = document["items"][0]

        self.assertIsNone(item["selected_action"])
        for conflict in item["conflicts"]:
            self.assertIsNone(conflict["selected_choice"])

    def test_second_review_never_offers_identity_actions(self):
        form = self.build_form(_resolution_plan())
        item = form.items[0]

        self.assertNotIn("select_existing", item.allowed_actions)
        self.assertNotIn("create_new", item.allowed_actions)

    def test_metadata_resolution_requires_every_conflict(self):
        form = self.build_form(_resolution_plan())

        self.assert_selection_error(
            form,
            {
                "selected": {
                    "action": "resolve_metadata",
                    "choices": {
                        "title": "use_imported",
                    },
                }
            },
        )

    def test_metadata_resolution_emits_exact_second_review_document(self):
        form = self.build_form(_resolution_plan())
        document = self.build_decision_document(
            form,
            {
                "selected": {
                    "action": "resolve_metadata",
                    "choices": {
                        "title": "use_imported",
                        "exit_count": "keep_existing",
                    },
                }
            },
        )

        self.assertEqual(
            document["schema"],
            SECOND_REVIEW_DECISION_SCHEMA,
        )
        self.assertEqual(
            document["version"],
            SECOND_REVIEW_DECISION_VERSION,
        )
        self.assertEqual(
            document["import_id"],
            "second-review-suite",
        )
        self.assertEqual(
            document["source_sha256"],
            SOURCE_SHA256,
        )
        self.assertEqual(
            document["resolution_review_sha256"],
            form.resolution_review_sha256,
        )
        self.assertEqual(
            document["decisions"],
            [
                {
                    "entry_key": "selected",
                    "action": "resolve_metadata",
                    "collection_key": "usr_7",
                    "title_choice": "use_imported",
                    "attribute_choices": [
                        {
                            "field": "exit_count",
                            "choice": "keep_existing",
                        }
                    ],
                }
            ],
        )

    def test_skip_is_explicit_and_carries_no_metadata_choices(self):
        form = self.build_form(_resolution_plan())
        document = self.build_decision_document(
            form,
            {
                "selected": {
                    "action": "skip",
                }
            },
        )

        self.assertEqual(
            document["decisions"],
            [
                {
                    "entry_key": "selected",
                    "action": "skip",
                    "collection_key": "usr_7",
                    "title_choice": None,
                    "attribute_choices": [],
                }
            ],
        )

    def test_skip_rejects_extra_choice_state(self):
        form = self.build_form(_resolution_plan())

        self.assert_selection_error(
            form,
            {
                "selected": {
                    "action": "skip",
                    "choices": {
                        "title": "keep_existing",
                        "exit_count": "keep_existing",
                    },
                }
            },
        )

    def test_every_newly_blocked_row_requires_decision(self):
        form = self.build_form(_resolution_plan())

        self.assert_selection_error(form, {})

    def test_unknown_second_review_row_fails_closed(self):
        form = self.build_form(_resolution_plan())

        self.assert_selection_error(
            form,
            {
                "selected": {"action": "skip"},
                "unknown": {"action": "skip"},
            },
        )

    def test_conflict_choices_reuse_existing_metadata_vocabulary(self):
        form = self.build_form(_resolution_plan())

        self.assert_selection_error(
            form,
            {
                "selected": {
                    "action": "resolve_metadata",
                    "choices": {
                        "title": "merge_both",
                        "exit_count": "keep_existing",
                    },
                }
            },
        )

    def test_refinement_preserves_first_round_safe_changes(self):
        plan = _resolution_plan()
        form = self.build_form(plan)
        decisions = self.build_decision_document(
            form,
            {
                "selected": {
                    "action": "resolve_metadata",
                    "choices": {
                        "title": "use_imported",
                        "exit_count": "keep_existing",
                    },
                }
            },
        )

        refined = self.refine_resolution(plan, decisions)
        item = refined.items[1]

        self.assertEqual(item.action, "update_record")
        self.assertEqual(item.collection_key, "usr_7")
        self.assertEqual(
            item.title_value,
            "Imported Candidate",
        )
        self.assertEqual(
            tuple(
                (
                    reference.source,
                    reference.external_id,
                )
                for reference
                in item.source_reference_additions
            ),
            (("kaizoff", "ko-7"),),
        )
        self.assertEqual(
            tuple(
                (change.field, change.value)
                for change in item.attribute_changes
            ),
            (("release_date", "2025-04-03"),),
        )
        self.assertEqual(item.conflicts, ())
        self.assertEqual(item.warnings, ())

    def test_refinement_can_apply_imported_attribute_conflict(self):
        plan = _resolution_plan()
        form = self.build_form(plan)
        decisions = self.build_decision_document(
            form,
            {
                "selected": {
                    "action": "resolve_metadata",
                    "choices": {
                        "title": "keep_existing",
                        "exit_count": "use_imported",
                    },
                }
            },
        )

        refined = self.refine_resolution(plan, decisions)
        item = refined.items[1]

        self.assertIsNone(item.title_value)
        self.assertEqual(
            tuple(
                (change.field, change.value)
                for change in item.attribute_changes
            ),
            (
                ("release_date", "2025-04-03"),
                ("exit_count", 15),
            ),
        )

    def test_skip_discards_pending_changes_for_that_row(self):
        plan = _resolution_plan()
        form = self.build_form(plan)
        decisions = self.build_decision_document(
            form,
            {
                "selected": {"action": "skip"},
            },
        )

        refined = self.refine_resolution(plan, decisions)
        item = refined.items[1]

        self.assertEqual(item.action, "skip")
        self.assertEqual(item.collection_key, "usr_7")
        self.assertEqual(item.title_value, None)
        self.assertEqual(item.source_reference_additions, ())
        self.assertEqual(item.attribute_changes, ())
        self.assertEqual(item.conflicts, ())

    def test_refinement_preserves_unrelated_resolution_rows_and_groups(self):
        plan = _resolution_plan()
        form = self.build_form(plan)
        decisions = self.build_decision_document(
            form,
            {
                "selected": {"action": "skip"},
            },
        )

        refined = self.refine_resolution(plan, decisions)

        self.assertEqual(refined.items[0], plan.items[0])
        self.assertEqual(refined.items[2], plan.items[2])
        self.assertEqual(refined.items[3], plan.items[3])
        self.assertEqual(refined.groups, plan.groups)

    def test_refinement_recalculates_summary_and_clears_review(self):
        plan = _resolution_plan()
        form = self.build_form(plan)
        decisions = self.build_decision_document(
            form,
            {
                "selected": {
                    "action": "resolve_metadata",
                    "choices": {
                        "title": "keep_existing",
                        "exit_count": "keep_existing",
                    },
                }
            },
        )

        refined = self.refine_resolution(plan, decisions)

        self.assertEqual(
            dict(refined.summary),
            {
                "total": 4,
                "create_record": 1,
                "update_record": 2,
                "no_change": 0,
                "review_required": 0,
                "skip": 1,
            },
        )

    def test_resolution_review_fingerprint_changes_with_conflict_state(self):
        original = _resolution_plan()
        changed_items = list(original.items)
        row = changed_items[1]
        changed_items[1] = BulkCollectionImportResolutionItem(
            entry_key=row.entry_key,
            action=row.action,
            collection_key=row.collection_key,
            title_value=row.title_value,
            source_reference_additions=(
                row.source_reference_additions
            ),
            attributes=row.attributes,
            attribute_changes=row.attribute_changes,
            conflicts=(
                BulkCollectionImportResolutionConflict(
                    field="title",
                    existing_value="Different Existing Title",
                    imported_value="Imported Candidate",
                ),
                row.conflicts[1],
            ),
            warnings=row.warnings,
        )
        changed = BulkCollectionImportResolutionPlan(
            schema=original.schema,
            version=original.version,
            import_id=original.import_id,
            source_sha256=original.source_sha256,
            summary=original.summary,
            items=tuple(changed_items),
            groups=original.groups,
        )

        self.assertNotEqual(
            self.build_form(original).resolution_review_sha256,
            self.build_form(changed).resolution_review_sha256,
        )

    def test_stale_second_review_decisions_fail_against_changed_resolution(self):
        plan = _resolution_plan()
        form = self.build_form(plan)
        decisions = self.build_decision_document(
            form,
            {
                "selected": {"action": "skip"},
            },
        )

        changed_items = list(plan.items)
        row = changed_items[1]
        changed_items[1] = BulkCollectionImportResolutionItem(
            entry_key=row.entry_key,
            action=row.action,
            collection_key="usr_8",
            title_value=row.title_value,
            source_reference_additions=(
                row.source_reference_additions
            ),
            attributes=row.attributes,
            attribute_changes=row.attribute_changes,
            conflicts=row.conflicts,
            warnings=row.warnings,
        )
        changed = BulkCollectionImportResolutionPlan(
            schema=plan.schema,
            version=plan.version,
            import_id=plan.import_id,
            source_sha256=plan.source_sha256,
            summary=plan.summary,
            items=tuple(changed_items),
            groups=plan.groups,
        )

        self.assert_refinement_error(changed, decisions)

    def test_malformed_second_review_row_fails_closed(self):
        plan = _resolution_plan()
        items = list(plan.items)
        row = items[1]
        items[1] = BulkCollectionImportResolutionItem(
            entry_key=row.entry_key,
            action="review_required",
            collection_key=row.collection_key,
            title_value=row.title_value,
            source_reference_additions=(
                row.source_reference_additions
            ),
            attributes=row.attributes,
            attribute_changes=row.attribute_changes,
            conflicts=(),
            warnings=("metadata_conflict",),
        )
        malformed = BulkCollectionImportResolutionPlan(
            schema=plan.schema,
            version=plan.version,
            import_id=plan.import_id,
            source_sha256=plan.source_sha256,
            summary=plan.summary,
            items=tuple(items),
            groups=plan.groups,
        )

        self.assert_form_error(malformed)

    def test_second_review_form_is_immutable_and_projection_detached(self):
        form = self.build_form(_resolution_plan())

        with self.assertRaises((AttributeError, TypeError)):
            form.items[0].allowed_actions += ("unsafe",)

        document = self.form_to_document(form)
        document["items"][0]["conflicts"][0][
            "selected_choice"
        ] = "use_imported"

        clean = self.form_to_document(form)
        self.assertIsNone(
            clean["items"][0]["conflicts"][0][
                "selected_choice"
            ]
        )

    def test_second_review_serialization_is_stable_compact_json(self):
        form = self.build_form(_resolution_plan())
        document = self.build_decision_document(
            form,
            {
                "selected": {"action": "skip"},
            },
        )
        serialized = self.serialize_decisions(document)

        self.assertEqual(
            serialized,
            json.dumps(
                json.loads(serialized),
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            ),
        )


class BulkCollectionImportSecondReviewSpecificationTest(
    unittest.TestCase
):
    """Lock the second-round boundary before production/UI code."""

    def test_second_round_is_metadata_only(self):
        self.assertEqual(
            SECOND_REVIEW_ACTIONS,
            ("resolve_metadata", "skip"),
        )
        self.assertEqual(
            SECOND_REVIEW_CONFLICT_CHOICES,
            ("keep_existing", "use_imported"),
        )

    def test_second_round_has_its_own_bound_decision_schema(self):
        self.assertEqual(
            SECOND_REVIEW_DECISION_SCHEMA,
            "smwc-bulk-collection-second-review-decisions",
        )
        self.assertEqual(
            SECOND_REVIEW_DECISION_VERSION,
            1,
        )

    def test_second_round_contains_no_identity_or_apply_actions(self):
        self.assertNotIn(
            "select_existing",
            SECOND_REVIEW_ACTIONS,
        )
        self.assertNotIn("create_new", SECOND_REVIEW_ACTIONS)
        self.assertNotIn("apply", SECOND_REVIEW_ACTIONS)
        self.assertNotIn("save", SECOND_REVIEW_ACTIONS)


class BulkCollectionImportSecondReviewImplementationTest(
    BulkCollectionImportSecondReviewContractMixin,
    unittest.TestCase,
):
    """Run the Commit 120 contract against production."""

    def build_form(self, resolution_plan):
        return build_bulk_collection_import_second_review_form(
            resolution_plan
        )

    def form_to_document(self, form):
        return bulk_collection_import_second_review_form_to_document(
            form
        )

    def build_decision_document(self, form, selections):
        return build_bulk_collection_import_second_review_document(
            form,
            selections,
        )

    def refine_resolution(self, resolution_plan, decisions):
        return refine_bulk_collection_import_resolution_plan(
            resolution_plan,
            decisions,
        )

    def serialize_decisions(self, document):
        return serialize_bulk_collection_import_second_review_document(
            document
        )

    def assert_form_error(self, resolution_plan):
        with self.assertRaises(BulkCollectionImportSecondReviewError):
            build_bulk_collection_import_second_review_form(
                resolution_plan
            )

    def assert_selection_error(self, form, selections):
        with self.assertRaises(BulkCollectionImportSecondReviewError):
            build_bulk_collection_import_second_review_document(
                form,
                selections,
            )

    def assert_refinement_error(self, resolution_plan, decisions):
        with self.assertRaises(BulkCollectionImportSecondReviewError):
            refine_bulk_collection_import_resolution_plan(
                resolution_plan,
                decisions,
            )

    def test_production_constants_match_specification(self):
        self.assertEqual(
            PRODUCTION_FORM_SCHEMA,
            SECOND_REVIEW_FORM_SCHEMA,
        )
        self.assertEqual(
            PRODUCTION_FORM_VERSION,
            SECOND_REVIEW_FORM_VERSION,
        )
        self.assertEqual(
            PRODUCTION_DECISION_SCHEMA,
            SECOND_REVIEW_DECISION_SCHEMA,
        )
        self.assertEqual(
            PRODUCTION_DECISION_VERSION,
            SECOND_REVIEW_DECISION_VERSION,
        )
        self.assertEqual(
            PRODUCTION_SECOND_REVIEW_ACTIONS,
            SECOND_REVIEW_ACTIONS,
        )
        self.assertEqual(
            PRODUCTION_CONFLICT_CHOICES,
            SECOND_REVIEW_CONFLICT_CHOICES,
        )

    def test_all_keep_can_become_no_change_without_safe_pending_work(self):
        plan = _resolution_plan()
        items = list(plan.items)
        row = items[1]
        items[1] = BulkCollectionImportResolutionItem(
            entry_key=row.entry_key,
            action=row.action,
            collection_key=row.collection_key,
            title_value=row.title_value,
            source_reference_additions=(),
            attributes=row.attributes,
            attribute_changes=(),
            conflicts=row.conflicts,
            warnings=row.warnings,
        )
        stripped = BulkCollectionImportResolutionPlan(
            schema=plan.schema,
            version=plan.version,
            import_id=plan.import_id,
            source_sha256=plan.source_sha256,
            summary=plan.summary,
            items=tuple(items),
            groups=plan.groups,
        )

        form = build_bulk_collection_import_second_review_form(
            stripped
        )
        decisions = build_bulk_collection_import_second_review_document(
            form,
            {
                "selected": {
                    "action": "resolve_metadata",
                    "choices": {
                        "title": "keep_existing",
                        "exit_count": "keep_existing",
                    },
                }
            },
        )
        refined = refine_bulk_collection_import_resolution_plan(
            stripped,
            decisions,
        )

        self.assertEqual(refined.items[1].action, "no_change")
        self.assertEqual(
            dict(refined.summary),
            {
                "total": 4,
                "create_record": 1,
                "update_record": 1,
                "no_change": 1,
                "review_required": 0,
                "skip": 1,
            },
        )

    def test_second_review_document_rejects_changed_target(self):
        plan = _resolution_plan()
        form = build_bulk_collection_import_second_review_form(plan)
        decisions = build_bulk_collection_import_second_review_document(
            form,
            {"selected": {"action": "skip"}},
        )
        decisions["decisions"][0]["collection_key"] = "usr_other"

        with self.assertRaises(BulkCollectionImportSecondReviewError):
            refine_bulk_collection_import_resolution_plan(
                plan,
                decisions,
            )



if __name__ == "__main__":
    unittest.main(verbosity=2)
