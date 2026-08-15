"""Safety specification for bulk Collection identity review."""

from __future__ import annotations

import json
import unittest


IDENTITY_REVIEW_REQUIRED_WARNING = "identity_review_required"
IDENTITY_AMBIGUOUS_WARNING = "identity_ambiguous"
IDENTITY_CONFLICT_WARNING = "identity_conflict"

HARD_IDENTITY_CONFLICT_WARNINGS = (
    "source_identity_conflict",
    "duplicate_import_target",
)

AMBIGUOUS_IDENTITY_ACTIONS = (
    "select_existing",
    "create_new",
    "skip",
)
HARD_IDENTITY_CONFLICT_ACTIONS = ("skip",)
METADATA_REVIEW_ACTIONS = (
    "resolve_metadata",
    "skip",
)

AMBIGUOUS_REVIEW_ITEM = {
    "entry_key": "ambiguous-entry",
    "action": "review_required",
    "collection_keys": [
        "collection-a",
        "collection-b",
    ],
    "warnings": [
        IDENTITY_REVIEW_REQUIRED_WARNING,
        IDENTITY_AMBIGUOUS_WARNING,
    ],
}

SOURCE_CONFLICT_REVIEW_ITEM = {
    "entry_key": "source-conflict-entry",
    "action": "review_required",
    "collection_keys": [
        "collection-a",
        "collection-b",
    ],
    "warnings": [
        IDENTITY_REVIEW_REQUIRED_WARNING,
        IDENTITY_CONFLICT_WARNING,
        "source_identity_conflict",
    ],
}

DUPLICATE_TARGET_REVIEW_ITEM = {
    "entry_key": "duplicate-target-entry",
    "action": "review_required",
    "collection_keys": ["collection-a"],
    "warnings": [
        IDENTITY_REVIEW_REQUIRED_WARNING,
        IDENTITY_CONFLICT_WARNING,
        "duplicate_import_target",
    ],
}

METADATA_REVIEW_ITEM = {
    "entry_key": "metadata-entry",
    "action": "review_required",
    "collection_keys": ["collection-a"],
    "warnings": ["metadata_conflict"],
}


class BulkCollectionIdentityReviewSafetyContractMixin:
    """Reusable policy suite for production identity-review handling."""

    def identity_review_warnings(
        self,
        resolution_status,
        preview_warnings,
    ):
        raise NotImplementedError

    def allowed_review_actions(self, merge_item):
        raise NotImplementedError

    def assert_invalid_review_item(self, merge_item):
        raise NotImplementedError

    def test_ambiguous_identity_is_explicitly_identified(self):
        warnings = self.identity_review_warnings(
            "ambiguous",
            (),
        )

        self.assertEqual(
            warnings,
            (
                IDENTITY_REVIEW_REQUIRED_WARNING,
                IDENTITY_AMBIGUOUS_WARNING,
            ),
        )

    def test_source_identity_conflict_is_preserved(self):
        warnings = self.identity_review_warnings(
            "conflict",
            ("source_identity_conflict",),
        )

        self.assertEqual(
            warnings,
            (
                IDENTITY_REVIEW_REQUIRED_WARNING,
                IDENTITY_CONFLICT_WARNING,
                "source_identity_conflict",
            ),
        )

    def test_duplicate_import_target_conflict_is_preserved(self):
        warnings = self.identity_review_warnings(
            "conflict",
            ("duplicate_import_target",),
        )

        self.assertEqual(
            warnings,
            (
                IDENTITY_REVIEW_REQUIRED_WARNING,
                IDENTITY_CONFLICT_WARNING,
                "duplicate_import_target",
            ),
        )

    def test_identity_warning_projection_is_deterministic_and_unique(
        self,
    ):
        warnings = self.identity_review_warnings(
            "conflict",
            (
                "source_identity_conflict",
                "source_identity_conflict",
            ),
        )

        self.assertEqual(
            warnings,
            (
                IDENTITY_REVIEW_REQUIRED_WARNING,
                IDENTITY_CONFLICT_WARNING,
                "source_identity_conflict",
            ),
        )

    def test_ambiguous_identity_keeps_interactive_resolution_actions(
        self,
    ):
        self.assertEqual(
            self.allowed_review_actions(
                AMBIGUOUS_REVIEW_ITEM
            ),
            AMBIGUOUS_IDENTITY_ACTIONS,
        )

    def test_source_identity_conflict_is_skip_only(self):
        self.assertEqual(
            self.allowed_review_actions(
                SOURCE_CONFLICT_REVIEW_ITEM
            ),
            HARD_IDENTITY_CONFLICT_ACTIONS,
        )

    def test_duplicate_import_target_conflict_is_skip_only(self):
        self.assertEqual(
            self.allowed_review_actions(
                DUPLICATE_TARGET_REVIEW_ITEM
            ),
            HARD_IDENTITY_CONFLICT_ACTIONS,
        )

    def test_metadata_review_policy_is_unchanged(self):
        self.assertEqual(
            self.allowed_review_actions(
                METADATA_REVIEW_ITEM
            ),
            METADATA_REVIEW_ACTIONS,
        )

    def test_identity_review_without_reason_is_invalid(self):
        item = {
            "entry_key": "legacy-identity-review",
            "action": "review_required",
            "collection_keys": ["collection-a"],
            "warnings": [IDENTITY_REVIEW_REQUIRED_WARNING],
        }

        self.assert_invalid_review_item(item)

    def test_identity_review_cannot_claim_both_ambiguous_and_conflict(
        self,
    ):
        item = {
            "entry_key": "contradictory-review",
            "action": "review_required",
            "collection_keys": [
                "collection-a",
                "collection-b",
            ],
            "warnings": [
                IDENTITY_REVIEW_REQUIRED_WARNING,
                IDENTITY_AMBIGUOUS_WARNING,
                IDENTITY_CONFLICT_WARNING,
                "source_identity_conflict",
            ],
        }

        self.assert_invalid_review_item(item)

    def test_conflict_marker_requires_a_known_hard_conflict_reason(
        self,
    ):
        item = {
            "entry_key": "unknown-conflict",
            "action": "review_required",
            "collection_keys": ["collection-a"],
            "warnings": [
                IDENTITY_REVIEW_REQUIRED_WARNING,
                IDENTITY_CONFLICT_WARNING,
            ],
        }

        self.assert_invalid_review_item(item)


class BulkCollectionIdentityReviewSafetySpecificationTest(
    unittest.TestCase
):
    """Validate the intended safety policy itself."""

    def test_hard_conflict_reasons_are_fixed(self):
        self.assertEqual(
            HARD_IDENTITY_CONFLICT_WARNINGS,
            (
                "source_identity_conflict",
                "duplicate_import_target",
            ),
        )

    def test_hard_conflicts_never_offer_destructive_resolution(self):
        for action in (
            "select_existing",
            "create_new",
            "resolve_metadata",
        ):
            self.assertNotIn(
                action,
                HARD_IDENTITY_CONFLICT_ACTIONS,
            )

        self.assertEqual(
            HARD_IDENTITY_CONFLICT_ACTIONS,
            ("skip",),
        )

    def test_ordinary_ambiguity_remains_user_resolvable(self):
        self.assertEqual(
            AMBIGUOUS_IDENTITY_ACTIONS,
            (
                "select_existing",
                "create_new",
                "skip",
            ),
        )

    def test_metadata_conflict_policy_remains_separate(self):
        self.assertEqual(
            METADATA_REVIEW_ACTIONS,
            (
                "resolve_metadata",
                "skip",
            ),
        )
        self.assertNotIn(
            "select_existing",
            METADATA_REVIEW_ACTIONS,
        )
        self.assertNotIn(
            "create_new",
            METADATA_REVIEW_ACTIONS,
        )

    def test_warning_examples_preserve_review_reason(self):
        examples = (
            AMBIGUOUS_REVIEW_ITEM,
            SOURCE_CONFLICT_REVIEW_ITEM,
            DUPLICATE_TARGET_REVIEW_ITEM,
        )

        for item in examples:
            with self.subTest(entry_key=item["entry_key"]):
                self.assertIn(
                    IDENTITY_REVIEW_REQUIRED_WARNING,
                    item["warnings"],
                )
                reason_count = sum(
                    warning
                    in (
                        IDENTITY_AMBIGUOUS_WARNING,
                        IDENTITY_CONFLICT_WARNING,
                    )
                    for warning in item["warnings"]
                )
                self.assertEqual(reason_count, 1)

    def test_policy_contains_no_apply_or_destination_behavior(self):
        serialized = json.dumps(
            {
                "ambiguous": AMBIGUOUS_REVIEW_ITEM,
                "source_conflict": SOURCE_CONFLICT_REVIEW_ITEM,
                "duplicate_target": DUPLICATE_TARGET_REVIEW_ITEM,
                "metadata": METADATA_REVIEW_ITEM,
            },
            sort_keys=True,
        )

        for forbidden in (
            "destination",
            "planner",
            "wheel",
            "collection_position",
            "write",
            "apply",
            "persist",
            "delete",
            "overwrite",
        ):
            self.assertNotIn(forbidden, serialized)

    def test_contract_mixin_exposes_required_tests(self):
        names = {
            name
            for name in dir(
                BulkCollectionIdentityReviewSafetyContractMixin
            )
            if name.startswith("test_")
        }

        self.assertEqual(
            names,
            {
                "test_ambiguous_identity_is_explicitly_identified",
                "test_ambiguous_identity_keeps_interactive_resolution_actions",
                "test_conflict_marker_requires_a_known_hard_conflict_reason",
                "test_duplicate_import_target_conflict_is_preserved",
                "test_duplicate_import_target_conflict_is_skip_only",
                "test_identity_review_cannot_claim_both_ambiguous_and_conflict",
                "test_identity_review_without_reason_is_invalid",
                "test_identity_warning_projection_is_deterministic_and_unique",
                "test_metadata_review_policy_is_unchanged",
                "test_source_identity_conflict_is_preserved",
                "test_source_identity_conflict_is_skip_only",
            },
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
