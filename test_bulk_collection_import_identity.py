"""Specification tests for bulk Collection identity resolution."""

from __future__ import annotations

import json
import unittest
from copy import deepcopy


IDENTITY_PLAN_SCHEMA = "smwc-bulk-collection-identity-plan"
IDENTITY_PLAN_VERSION = 1

RESOLUTION_STATUSES = (
    "matched_source",
    "matched_metadata",
    "new",
    "ambiguous",
    "conflict",
)

PLAN_KEYS = (
    "schema",
    "version",
    "import_id",
    "resolutions",
)
RESOLUTION_KEYS = (
    "entry_key",
    "status",
    "collection_keys",
    "matched_source_references",
    "proposed_source_references",
    "warnings",
)

IMPORT_DOCUMENT = {
    "schema": "smwc-bulk-collection-import",
    "version": 1,
    "import_id": "identity-resolution-suite",
    "title": "Identity resolution suite",
    "entries": [
        {
            "entry_key": "hybrid-match",
            "title": "Hybrid Hack",
            "source_references": [
                {
                    "source": "smwc",
                    "external_id": "100",
                },
                {
                    "source": "kaizoff",
                    "external_id": "hybrid-hack",
                },
            ],
            "attributes": {
                "authors": ["Author One"],
            },
        },
        {
            "entry_key": "metadata-match",
            "title": "Metadata Match!",
            "source_references": [],
            "attributes": {
                "authors": ["Author Two"],
            },
        },
        {
            "entry_key": "new-entry",
            "title": "Brand New Hack",
            "source_references": [],
            "attributes": {
                "authors": ["New Author"],
            },
        },
        {
            "entry_key": "ambiguous-entry",
            "title": "Shared Title",
            "source_references": [],
            "attributes": {
                "authors": ["Shared Author"],
            },
        },
    ],
    "groups": [
        {
            "group_key": "all",
            "title": "All",
            "entry_keys": [
                "hybrid-match",
                "metadata-match",
                "new-entry",
                "ambiguous-entry",
            ],
        }
    ],
}

COLLECTION_IDENTITIES = (
    {
        "collection_key": "collection-smwc-100",
        "title": "Hybrid Hack Legacy Title",
        "aliases": [],
        "source_references": [
            {
                "source": "smwc",
                "external_id": "100",
            }
        ],
        "attributes": {
            "authors": ["Author One"],
        },
    },
    {
        "collection_key": "collection-metadata",
        "title": "metadata match",
        "aliases": ["Metadata Match v1.0"],
        "source_references": [],
        "attributes": {
            "authors": ["AUTHOR TWO"],
        },
    },
    {
        "collection_key": "collection-shared-a",
        "title": "Shared Title",
        "aliases": [],
        "source_references": [],
        "attributes": {
            "authors": ["Shared Author"],
        },
    },
    {
        "collection_key": "collection-shared-b",
        "title": "Shared-Title",
        "aliases": [],
        "source_references": [],
        "attributes": {
            "authors": ["Shared Author"],
        },
    },
)

EXPECTED_PLAN_DOCUMENT = {
    "schema": IDENTITY_PLAN_SCHEMA,
    "version": IDENTITY_PLAN_VERSION,
    "import_id": "identity-resolution-suite",
    "resolutions": [
        {
            "entry_key": "hybrid-match",
            "status": "matched_source",
            "collection_keys": ["collection-smwc-100"],
            "matched_source_references": [
                {
                    "source": "smwc",
                    "external_id": "100",
                }
            ],
            "proposed_source_references": [
                {
                    "source": "kaizoff",
                    "external_id": "hybrid-hack",
                }
            ],
            "warnings": ["title_mismatch"],
        },
        {
            "entry_key": "metadata-match",
            "status": "matched_metadata",
            "collection_keys": ["collection-metadata"],
            "matched_source_references": [],
            "proposed_source_references": [],
            "warnings": [],
        },
        {
            "entry_key": "new-entry",
            "status": "new",
            "collection_keys": [],
            "matched_source_references": [],
            "proposed_source_references": [],
            "warnings": [],
        },
        {
            "entry_key": "ambiguous-entry",
            "status": "ambiguous",
            "collection_keys": [
                "collection-shared-a",
                "collection-shared-b",
            ],
            "matched_source_references": [],
            "proposed_source_references": [],
            "warnings": [],
        },
    ],
}


class BulkCollectionIdentityResolutionContractMixin:
    """Reusable behavior suite for the production identity resolver."""

    def parse_import(self, document):
        raise NotImplementedError

    def resolve_identities(
        self,
        import_document,
        collection_identities,
    ):
        raise NotImplementedError

    def plan_to_document(self, plan):
        raise NotImplementedError

    def serialize_plan(self, plan):
        raise NotImplementedError

    def assert_resolution_error(
        self,
        import_document,
        collection_identities,
    ):
        raise NotImplementedError

    def test_source_metadata_new_and_ambiguous_results_are_ordered(self):
        parsed = self.parse_import(deepcopy(IMPORT_DOCUMENT))

        plan = self.resolve_identities(
            parsed,
            deepcopy(COLLECTION_IDENTITIES),
        )

        self.assertEqual(
            self.plan_to_document(plan),
            EXPECTED_PLAN_DOCUMENT,
        )

    def test_source_match_is_authoritative_and_proposes_missing_links(self):
        parsed = self.parse_import(deepcopy(IMPORT_DOCUMENT))
        plan = self.resolve_identities(
            parsed,
            deepcopy(COLLECTION_IDENTITIES),
        )
        resolution = plan.resolutions[0]

        self.assertEqual(resolution.status, "matched_source")
        self.assertEqual(
            resolution.collection_keys,
            ("collection-smwc-100",),
        )
        self.assertEqual(
            [
                (
                    item.source,
                    item.external_id,
                )
                for item in resolution.matched_source_references
            ],
            [("smwc", "100")],
        )
        self.assertEqual(
            [
                (
                    item.source,
                    item.external_id,
                )
                for item in resolution.proposed_source_references
            ],
            [("kaizoff", "hybrid-hack")],
        )
        self.assertEqual(
            resolution.warnings,
            ("title_mismatch",),
        )

    def test_title_only_match_is_not_silently_accepted(self):
        document = deepcopy(IMPORT_DOCUMENT)
        document["entries"] = [
            {
                "entry_key": "title-only",
                "title": "Metadata Match",
                "source_references": [],
                "attributes": {},
            }
        ]
        document["groups"][0]["entry_keys"] = ["title-only"]
        parsed = self.parse_import(document)

        plan = self.resolve_identities(
            parsed,
            deepcopy(COLLECTION_IDENTITIES),
        )

        resolution = plan.resolutions[0]
        self.assertEqual(resolution.status, "ambiguous")
        self.assertEqual(
            resolution.collection_keys,
            ("collection-metadata",),
        )

    def test_alias_plus_author_can_form_unique_metadata_match(self):
        document = deepcopy(IMPORT_DOCUMENT)
        document["entries"] = [
            {
                "entry_key": "alias-match",
                "title": "Metadata Match v1.0",
                "source_references": [],
                "attributes": {
                    "authors": ["author two"],
                },
            }
        ]
        document["groups"][0]["entry_keys"] = ["alias-match"]
        parsed = self.parse_import(document)

        plan = self.resolve_identities(
            parsed,
            deepcopy(COLLECTION_IDENTITIES),
        )

        resolution = plan.resolutions[0]
        self.assertEqual(resolution.status, "matched_metadata")
        self.assertEqual(
            resolution.collection_keys,
            ("collection-metadata",),
        )

    def test_conflicting_hybrid_source_references_require_review(self):
        document = deepcopy(IMPORT_DOCUMENT)
        document["entries"] = [
            {
                "entry_key": "conflicting-source",
                "title": "Conflicting Source",
                "source_references": [
                    {
                        "source": "smwc",
                        "external_id": "100",
                    },
                    {
                        "source": "kaizoff",
                        "external_id": "other-record",
                    },
                ],
                "attributes": {
                    "authors": ["Author One"],
                },
            }
        ]
        document["groups"][0]["entry_keys"] = [
            "conflicting-source"
        ]
        identities = list(deepcopy(COLLECTION_IDENTITIES))
        identities.append(
            {
                "collection_key": "collection-kaizoff-other",
                "title": "Other Record",
                "aliases": [],
                "source_references": [
                    {
                        "source": "kaizoff",
                        "external_id": "other-record",
                    }
                ],
                "attributes": {
                    "authors": ["Different Author"],
                },
            }
        )
        parsed = self.parse_import(document)

        plan = self.resolve_identities(parsed, identities)

        resolution = plan.resolutions[0]
        self.assertEqual(resolution.status, "conflict")
        self.assertEqual(
            resolution.collection_keys,
            (
                "collection-smwc-100",
                "collection-kaizoff-other",
            ),
        )
        self.assertEqual(
            resolution.warnings,
            ("source_identity_conflict",),
        )

    def test_duplicate_collection_source_identity_is_invalid_input(self):
        identities = list(deepcopy(COLLECTION_IDENTITIES))
        identities.append(
            {
                "collection_key": "duplicate-smwc-owner",
                "title": "Duplicate",
                "aliases": [],
                "source_references": [
                    {
                        "source": "smwc",
                        "external_id": "100",
                    }
                ],
                "attributes": {},
            }
        )

        self.assert_resolution_error(
            self.parse_import(deepcopy(IMPORT_DOCUMENT)),
            identities,
        )

    def test_two_import_entries_cannot_silently_target_same_record(self):
        document = deepcopy(IMPORT_DOCUMENT)
        document["entries"] = [
            {
                "entry_key": "first",
                "title": "Hybrid Hack",
                "source_references": [
                    {
                        "source": "smwc",
                        "external_id": "100",
                    }
                ],
                "attributes": {
                    "authors": ["Author One"],
                },
            },
            {
                "entry_key": "second",
                "title": "Hybrid Hack",
                "source_references": [
                    {
                        "source": "smwc",
                        "external_id": "100",
                    }
                ],
                "attributes": {
                    "authors": ["Author One"],
                },
            },
        ]
        document["groups"][0]["entry_keys"] = [
            "first",
            "second",
        ]
        parsed = self.parse_import(document)

        plan = self.resolve_identities(
            parsed,
            deepcopy(COLLECTION_IDENTITIES),
        )

        self.assertEqual(
            [item.status for item in plan.resolutions],
            ["conflict", "conflict"],
        )
        self.assertTrue(
            all(
                item.warnings
                == ("duplicate_import_target",)
                for item in plan.resolutions
            )
        )

    def test_inputs_and_projected_plan_are_detached(self):
        document = deepcopy(IMPORT_DOCUMENT)
        identities = deepcopy(COLLECTION_IDENTITIES)
        parsed = self.parse_import(document)
        plan = self.resolve_identities(parsed, identities)

        document["entries"][0]["title"] = "Changed input"
        identities[0]["title"] = "Changed collection"
        projected = self.plan_to_document(plan)
        projected["resolutions"][0]["collection_keys"].append(
            "changed"
        )
        projected["resolutions"][0][
            "proposed_source_references"
        ][0]["external_id"] = "changed"

        clean = self.plan_to_document(plan)
        self.assertEqual(
            clean,
            EXPECTED_PLAN_DOCUMENT,
        )

    def test_resolution_plan_is_immutable(self):
        parsed = self.parse_import(deepcopy(IMPORT_DOCUMENT))
        plan = self.resolve_identities(
            parsed,
            deepcopy(COLLECTION_IDENTITIES),
        )

        with self.assertRaises((AttributeError, TypeError)):
            plan.import_id = "changed"
        with self.assertRaises((AttributeError, TypeError)):
            plan.resolutions[0].status = "new"
        with self.assertRaises((AttributeError, TypeError)):
            plan.resolutions[0].collection_keys += ("changed",)

    def test_serialization_is_stable_compact_json(self):
        parsed = self.parse_import(deepcopy(IMPORT_DOCUMENT))
        plan = self.resolve_identities(
            parsed,
            deepcopy(COLLECTION_IDENTITIES),
        )

        serialized = self.serialize_plan(plan)

        self.assertEqual(
            json.loads(serialized),
            EXPECTED_PLAN_DOCUMENT,
        )
        self.assertEqual(
            serialized,
            json.dumps(
                json.loads(serialized),
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            ),
        )
        self.assertEqual(
            serialized,
            self.serialize_plan(
                self.resolve_identities(
                    self.parse_import(
                        deepcopy(IMPORT_DOCUMENT)
                    ),
                    deepcopy(COLLECTION_IDENTITIES),
                )
            ),
        )

    def test_resolution_never_mutates_import_or_collection_inputs(self):
        document = deepcopy(IMPORT_DOCUMENT)
        identities = deepcopy(COLLECTION_IDENTITIES)
        original_document = deepcopy(document)
        original_identities = deepcopy(identities)
        parsed = self.parse_import(document)

        self.resolve_identities(parsed, identities)

        self.assertEqual(document, original_document)
        self.assertEqual(identities, original_identities)


class BulkCollectionIdentityResolutionSpecificationTest(
    unittest.TestCase
):
    """Validate the source-neutral identity-resolution specification."""

    def test_plan_schema_version_and_statuses_are_fixed(self):
        self.assertEqual(
            IDENTITY_PLAN_SCHEMA,
            "smwc-bulk-collection-identity-plan",
        )
        self.assertEqual(IDENTITY_PLAN_VERSION, 1)
        self.assertEqual(
            RESOLUTION_STATUSES,
            (
                "matched_source",
                "matched_metadata",
                "new",
                "ambiguous",
                "conflict",
            ),
        )

    def test_plan_and_resolution_shapes_are_minimal(self):
        self.assertEqual(
            PLAN_KEYS,
            (
                "schema",
                "version",
                "import_id",
                "resolutions",
            ),
        )
        self.assertEqual(
            RESOLUTION_KEYS,
            (
                "entry_key",
                "status",
                "collection_keys",
                "matched_source_references",
                "proposed_source_references",
                "warnings",
            ),
        )

    def test_expected_plan_covers_every_status_except_conflict(self):
        statuses = {
            item["status"]
            for item in EXPECTED_PLAN_DOCUMENT["resolutions"]
        }

        self.assertEqual(
            statuses,
            {
                "matched_source",
                "matched_metadata",
                "new",
                "ambiguous",
            },
        )

    def test_hybrid_source_match_proposes_only_missing_identity(self):
        resolution = EXPECTED_PLAN_DOCUMENT["resolutions"][0]

        self.assertEqual(
            resolution["matched_source_references"],
            [
                {
                    "source": "smwc",
                    "external_id": "100",
                }
            ],
        )
        self.assertEqual(
            resolution["proposed_source_references"],
            [
                {
                    "source": "kaizoff",
                    "external_id": "hybrid-hack",
                }
            ],
        )

    def test_metadata_match_requires_title_and_author_evidence(self):
        imported = IMPORT_DOCUMENT["entries"][1]
        existing = COLLECTION_IDENTITIES[1]

        self.assertEqual(imported["title"], "Metadata Match!")
        self.assertEqual(
            imported["attributes"]["authors"],
            ["Author Two"],
        )
        self.assertEqual(existing["title"], "metadata match")
        self.assertEqual(
            existing["attributes"]["authors"],
            ["AUTHOR TWO"],
        )

    def test_order_is_preserved_from_import_entries(self):
        self.assertEqual(
            [
                item["entry_key"]
                for item in EXPECTED_PLAN_DOCUMENT["resolutions"]
            ],
            [
                item["entry_key"]
                for item in IMPORT_DOCUMENT["entries"]
            ],
        )

    def test_plan_contains_no_collection_mutation_or_user_state(self):
        serialized = json.dumps(
            EXPECTED_PLAN_DOCUMENT,
            sort_keys=True,
        )
        for forbidden in (
            "completed",
            "notes",
            "personal_rating",
            "planner",
            "rom_paths",
            "save_paths",
            "write",
            "apply",
        ):
            self.assertNotIn(forbidden, serialized)

    def test_contract_mixin_exposes_required_implementation_tests(self):
        names = {
            name
            for name in dir(
                BulkCollectionIdentityResolutionContractMixin
            )
            if name.startswith("test_")
        }

        self.assertEqual(
            names,
            {
                "test_alias_plus_author_can_form_unique_metadata_match",
                "test_conflicting_hybrid_source_references_require_review",
                "test_duplicate_collection_source_identity_is_invalid_input",
                "test_inputs_and_projected_plan_are_detached",
                "test_resolution_never_mutates_import_or_collection_inputs",
                "test_resolution_plan_is_immutable",
                "test_serialization_is_stable_compact_json",
                "test_source_match_is_authoritative_and_proposes_missing_links",
                "test_source_metadata_new_and_ambiguous_results_are_ordered",
                "test_title_only_match_is_not_silently_accepted",
                "test_two_import_entries_cannot_silently_target_same_record",
            },
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
