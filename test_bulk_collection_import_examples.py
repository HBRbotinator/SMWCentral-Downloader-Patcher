"""Validate documented bulk Collection import examples."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from bulk_collection_import import (
    BULK_COLLECTION_IMPORT_FORBIDDEN_ATTRIBUTE_KEYS,
    bulk_collection_import_to_document,
)
from bulk_collection_import_apply import (
    confirm_bulk_collection_import_apply_session,
    create_bulk_collection_import_apply_session,
    execute_bulk_collection_import_apply_session,
)
from bulk_collection_import_application_preview import (
    build_v5_1_bulk_collection_import_application_preview,
)
from bulk_collection_import_hack_data_store import (
    BulkCollectionImportHackDataStore,
)
from bulk_collection_import_json import (
    MAX_IMPORT_JSON_BYTES,
    load_bulk_collection_import_json,
)
from bulk_collection_import_review_form import (
    build_bulk_collection_import_review_document,
    build_bulk_collection_import_review_form,
)
from bulk_collection_import_workflow_preview import (
    plan_v5_1_bulk_collection_import_workflow_preview,
)
from bulk_collection_import_workflow_resolution import (
    resolve_v5_1_bulk_collection_import_review,
)
from hack_data_manager import HackDataManager


ROOT = Path(__file__).resolve().parent
DOC_PATH = ROOT / "BULK_COLLECTION_IMPORT.md"
EXAMPLE_DIRECTORY = ROOT / "examples" / "bulk_collection_import"
BASIC_PATH = EXAMPLE_DIRECTORY / "basic-smwc.json"
HYBRID_PATH = EXAMPLE_DIRECTORY / "hybrid.json"


class BulkCollectionImportExamplesTest(unittest.TestCase):
    """Keep public docs/examples aligned with the production contracts."""

    def _empty_manager(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        processed = Path(temporary.name) / "processed.json"
        processed.write_text("{}\n", encoding="utf-8")
        manager = HackDataManager(str(processed))
        manager._schedule_delayed_save = lambda: None
        return processed, manager

    def _resolve_review_free_example(self, example_path, manager):
        preview = plan_v5_1_bulk_collection_import_workflow_preview(
            str(example_path),
            manager,
        )
        form = build_bulk_collection_import_review_form(preview)
        self.assertEqual(form.items, ())

        review_document = build_bulk_collection_import_review_document(
            form,
            {},
        )
        resolution = resolve_v5_1_bulk_collection_import_review(
            str(example_path),
            manager,
            review_document,
        )
        self.assertEqual(resolution.summary["review_required"], 0)
        return preview, resolution

    def _apply_example(self, example_path):
        processed, manager = self._empty_manager()
        _preview, resolution = self._resolve_review_free_example(
            example_path,
            manager,
        )
        application = (
            build_v5_1_bulk_collection_import_application_preview(
                resolution,
                manager,
            )
        )
        session = create_bulk_collection_import_apply_session(
            application
        )
        confirm_bulk_collection_import_apply_session(
            session,
            session.application_plan_sha256,
        )
        result = execute_bulk_collection_import_apply_session(
            session,
            BulkCollectionImportHackDataStore(manager),
        )
        persisted = json.loads(
            processed.read_text(encoding="utf-8")
        )
        return application, result, persisted

    def test_documented_examples_load_through_bounded_json_adapter(self):
        for path in (BASIC_PATH, HYBRID_PATH):
            with self.subTest(path=path.name):
                self.assertTrue(path.is_file())
                self.assertLessEqual(
                    path.stat().st_size,
                    MAX_IMPORT_JSON_BYTES,
                )

                loaded = load_bulk_collection_import_json(path)
                projected = bulk_collection_import_to_document(
                    loaded.document
                )

                self.assertEqual(
                    projected,
                    json.loads(path.read_text(encoding="utf-8")),
                )
                self.assertEqual(loaded.source_name, path.name)
                self.assertEqual(len(loaded.sha256), 64)

    def test_basic_example_is_end_to_end_valid_against_empty_collection(self):
        application, result, persisted = self._apply_example(
            BASIC_PATH
        )

        self.assertEqual(
            tuple(
                operation.collection_key
                for operation in application.operations
            ),
            ("12345", "67890"),
        )
        self.assertEqual(
            dict(result.summary),
            {
                "total": 2,
                "created": 2,
                "updated": 0,
                "unchanged": 0,
                "skipped": 0,
            },
        )
        self.assertEqual(
            set(persisted),
            {"12345", "67890"},
        )

    def test_hybrid_example_keeps_source_neutral_and_custom_metadata(self):
        application, result, persisted = self._apply_example(
            HYBRID_PATH
        )

        keys = {
            operation.entry_key: operation.collection_key
            for operation in application.operations
        }
        self.assertEqual(
            keys["hybrid-smwc-kaizoff"],
            "54321",
        )
        self.assertTrue(
            keys["kaizoff-only"].startswith("usr_import_")
        )
        self.assertTrue(
            keys["source-less-local"].startswith("usr_import_")
        )
        self.assertNotEqual(
            keys["kaizoff-only"],
            keys["source-less-local"],
        )
        self.assertEqual(result.summary["created"], 3)

        hybrid = persisted["54321"]
        extension = hybrid["bulk_collection_import"]
        self.assertEqual(
            extension["source_references"],
            [
                {
                    "source": "smwc",
                    "external_id": "54321",
                },
                {
                    "source": "kaizoff",
                    "external_id": "hybrid-example",
                },
            ],
        )
        self.assertEqual(
            extension["attributes"]["tags"],
            ["short", "vanilla"],
        )
        self.assertEqual(
            extension["attributes"]["source_note"],
            "Example custom shared metadata",
        )

    def test_docs_cover_exact_schema_and_safety_boundaries(self):
        source = DOC_PATH.read_text(encoding="utf-8")

        for required in (
            "smwc-bulk-collection-import",
            "16 MiB",
            "entry_key",
            "source_references",
            "attributes",
            "group_key",
            "positive decimal",
            "usr_import_",
            "authors",
            "difficulty",
            "exit_count",
            "release_date",
            "application-plan SHA-256",
            "Bulk Import Preview",
            "Apply Import",
            "does not modify Planner state",
        ):
            self.assertIn(required, source)

        for forbidden in BULK_COLLECTION_IMPORT_FORBIDDEN_ATTRIBUTE_KEYS:
            with self.subTest(forbidden=forbidden):
                self.assertIn(f"`{forbidden}`", source)

    def test_examples_use_only_exact_version_one_shapes(self):
        for path in (BASIC_PATH, HYBRID_PATH):
            document = json.loads(path.read_text(encoding="utf-8"))
            with self.subTest(path=path.name):
                self.assertEqual(
                    set(document),
                    {
                        "schema",
                        "version",
                        "import_id",
                        "title",
                        "entries",
                        "groups",
                    },
                )
                for entry in document["entries"]:
                    self.assertEqual(
                        set(entry),
                        {
                            "entry_key",
                            "title",
                            "source_references",
                            "attributes",
                        },
                    )
                    for reference in entry["source_references"]:
                        self.assertEqual(
                            set(reference),
                            {"source", "external_id"},
                        )
                for group in document["groups"]:
                    self.assertEqual(
                        set(group),
                        {"group_key", "title", "entry_keys"},
                    )


if __name__ == "__main__":
    unittest.main(verbosity=2)
