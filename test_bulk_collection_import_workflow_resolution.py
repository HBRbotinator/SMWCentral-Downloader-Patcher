"""Fresh v5.1 post-review bulk-import resolution tests."""

from __future__ import annotations

import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from bulk_collection_import_review_form import (
    build_bulk_collection_import_review_document,
    build_bulk_collection_import_review_form,
)
from bulk_collection_import_workflow_preview import (
    plan_v5_1_bulk_collection_import_workflow_preview,
)
from bulk_collection_import_workflow_resolution import (
    BulkCollectionImportWorkflowResolutionError,
    resolve_v5_1_bulk_collection_import_review,
)
from hack_data_manager import HackDataManager


def _import_document():
    return {
        "schema": "smwc-bulk-collection-import",
        "version": 1,
        "import_id": "resolution-preview-suite",
        "title": "Resolution Preview Suite",
        "entries": [
            {
                "entry_key": "metadata",
                "title": "Existing Hack",
                "source_references": [
                    {
                        "source": "smwc",
                        "external_id": "100",
                    }
                ],
                "attributes": {
                    "authors": ["Author One"],
                    "exit_count": 15,
                },
            }
        ],
        "groups": [
            {
                "group_key": "all",
                "title": "All",
                "entry_keys": ["metadata"],
            }
        ],
    }


def _collection_document():
    return {
        "100": {
            "title": "Existing Hack",
            "current_difficulty": "Advanced",
            "authors": ["Author One"],
            "exits": 14,
            "date": "",
            "completed": True,
            "completed_date": "2026-08-01",
            "personal_rating": 5,
            "notes": "private user note",
            "file_path": "C:/ROMs/Existing Hack.sfc",
            "additional_paths": [],
        }
    }


class BulkCollectionImportWorkflowResolutionTest(unittest.TestCase):
    def _fixture(self):
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name)
        processed = root / "processed.json"
        import_path = root / "review.json"

        processed.write_text(
            json.dumps(
                _collection_document(),
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        import_path.write_text(
            json.dumps(
                _import_document(),
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        manager = HackDataManager(str(processed))
        return temporary, processed, import_path, manager

    def _review_document(self, import_path, manager):
        preview = plan_v5_1_bulk_collection_import_workflow_preview(
            str(import_path),
            manager,
        )
        form = build_bulk_collection_import_review_form(preview)
        self.assertEqual(
            tuple(item.entry_key for item in form.items),
            ("metadata",),
        )
        return build_bulk_collection_import_review_document(
            form,
            {
                "metadata": {
                    "action": "resolve_metadata",
                    "choices": {
                        "exit_count": "use_imported",
                    },
                }
            },
        )

    def test_review_resolves_against_fresh_live_collection(self):
        temporary, processed, import_path, manager = self._fixture()
        self.addCleanup(temporary.cleanup)

        review = self._review_document(import_path, manager)
        before_manager = deepcopy(manager.data)
        before_file = processed.read_bytes()

        plan = resolve_v5_1_bulk_collection_import_review(
            str(import_path),
            manager,
            review,
        )

        self.assertEqual(
            dict(plan.summary),
            {
                "total": 1,
                "create_record": 0,
                "update_record": 1,
                "no_change": 0,
                "review_required": 0,
                "skip": 0,
            },
        )
        self.assertEqual(plan.items[0].entry_key, "metadata")
        self.assertEqual(plan.items[0].action, "update_record")
        self.assertEqual(plan.items[0].collection_key, "100")
        self.assertEqual(
            tuple(
                (change.field, change.value)
                for change in plan.items[0].attribute_changes
            ),
            (("exit_count", 15),),
        )

        self.assertEqual(manager.data, before_manager)
        self.assertEqual(processed.read_bytes(), before_file)

    def test_source_change_after_review_fails_closed(self):
        temporary, _processed, import_path, manager = self._fixture()
        self.addCleanup(temporary.cleanup)

        review = self._review_document(import_path, manager)

        changed = _import_document()
        changed["title"] = "Changed after review"
        import_path.write_text(
            json.dumps(changed, ensure_ascii=False),
            encoding="utf-8",
        )

        with self.assertRaises(
            BulkCollectionImportWorkflowResolutionError
        ):
            resolve_v5_1_bulk_collection_import_review(
                str(import_path),
                manager,
                review,
            )

    def test_collection_change_after_review_is_replanned(self):
        temporary, processed, import_path, manager = self._fixture()
        self.addCleanup(temporary.cleanup)

        review = self._review_document(import_path, manager)

        manager.data["100"]["exits"] = 15
        manager.unsaved_changes = True
        before_manager = deepcopy(manager.data)
        before_file = processed.read_bytes()

        with self.assertRaises(
            BulkCollectionImportWorkflowResolutionError
        ):
            resolve_v5_1_bulk_collection_import_review(
                str(import_path),
                manager,
                review,
            )

        self.assertEqual(manager.data, before_manager)
        self.assertEqual(processed.read_bytes(), before_file)

    def test_review_document_shape_is_fail_closed(self):
        temporary, _processed, import_path, manager = self._fixture()
        self.addCleanup(temporary.cleanup)

        review = self._review_document(import_path, manager)

        malformed = dict(review)
        malformed["unexpected"] = True

        with self.assertRaises(
            BulkCollectionImportWorkflowResolutionError
        ):
            resolve_v5_1_bulk_collection_import_review(
                str(import_path),
                manager,
                malformed,
            )

    def test_wrong_manager_type_is_rejected(self):
        with self.assertRaises(TypeError):
            resolve_v5_1_bulk_collection_import_review(
                "unused.json",
                object(),
                {
                    "schema": "smwc-bulk-collection-review-decisions",
                    "version": 1,
                    "import_id": "x",
                    "source_sha256": "a" * 64,
                    "decisions": [],
                },
            )

    def test_module_has_no_write_or_application_boundary(self):
        source = Path(
            "bulk_collection_import_workflow_resolution.py"
        ).read_text(encoding="utf-8")

        for forbidden in (
            "build_v5_1_bulk_collection_import_application_plan",
            "allocate_bulk_collection_import_keys",
            "execute_bulk_collection_import",
            "BulkCollectionImportHackDataStore",
            ".save_data(",
            ".force_save(",
            ".update_hack(",
            ".add_user_hack(",
            "planner_store",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
