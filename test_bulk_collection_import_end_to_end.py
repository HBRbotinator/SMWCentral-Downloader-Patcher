"""End-to-end hardening for confirmed bulk Collection import persistence."""

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from bulk_collection_import_apply import (
    BulkCollectionImportApplyError,
    confirm_bulk_collection_import_apply_session,
    create_bulk_collection_import_apply_session,
    execute_bulk_collection_import_apply_session,
)
from bulk_collection_import_application_preview import (
    build_v5_1_bulk_collection_import_application_preview,
)
from bulk_collection_import_hack_data_store import (
    BULK_IMPORT_TEMP_SUFFIX,
    BulkCollectionImportHackDataStore,
)
from bulk_collection_import_review_form import (
    REVIEW_KIND_AMBIGUOUS_IDENTITY,
    REVIEW_KIND_HARD_IDENTITY_CONFLICT,
    REVIEW_KIND_METADATA,
    build_bulk_collection_import_review_document,
    build_bulk_collection_import_review_form,
)
from bulk_collection_import_second_review import (
    build_bulk_collection_import_second_review_document,
    build_bulk_collection_import_second_review_form,
    refine_bulk_collection_import_resolution_plan,
)
from bulk_collection_import_workflow_preview import (
    plan_v5_1_bulk_collection_import_workflow_preview,
)
from bulk_collection_import_workflow_resolution import (
    resolve_v5_1_bulk_collection_import_review,
)
from hack_data_manager import HackDataManager


def _initial_collection():
    return {
        "100": {
            "title": "Already Current",
            "current_difficulty": "Intermediate",
            "authors": ["Exact Author"],
            "exits": 10,
            "date": "2025-01-01",
            "completed": True,
            "completed_date": "2026-01-15",
            "personal_rating": 5,
            "notes": "exact user note",
            "file_path": "C:/roms/exact.sfc",
            "additional_paths": ["C:/saves/exact.srm"],
        },
        "300": {
            "title": "Old Metadata Title",
            "current_difficulty": "Advanced",
            "authors": ["Metadata Author"],
            "exits": 14,
            "date": "2025-03-01",
            "completed": True,
            "completed_date": "2026-02-10",
            "personal_rating": 4,
            "notes": "preserve metadata user note",
            "file_path": "C:/roms/metadata.sfc",
            "additional_paths": [],
        },
        "usr_1": {
            "title": "Duplicate Candidate",
            "current_difficulty": "Advanced",
            "authors": ["Ambiguous Author"],
            "exits": 5,
            "date": "",
            "completed": True,
            "completed_date": "2026-03-01",
            "personal_rating": 5,
            "notes": "selected candidate user note",
            "file_path": "C:/roms/usr1.sfc",
            "additional_paths": [],
        },
        "usr_2": {
            "title": "Duplicate Candidate",
            "current_difficulty": "Advanced",
            "authors": ["Ambiguous Author"],
            "exits": 6,
            "date": "",
            "completed": False,
            "completed_date": "",
            "personal_rating": 2,
            "notes": "other candidate must remain untouched",
            "file_path": "C:/roms/usr2.sfc",
            "additional_paths": [],
        },
    }


def _import_document():
    return {
        "schema": "smwc-bulk-collection-import",
        "version": 1,
        "import_id": "end-to-end-hardening",
        "title": "End-to-end Hardening",
        "entries": [
            {
                "entry_key": "unchanged",
                "title": "Already Current",
                "source_references": [
                    {
                        "source": "smwc",
                        "external_id": "100",
                    }
                ],
                "attributes": {
                    "authors": ["Exact Author"],
                    "difficulty": "Intermediate",
                    "exit_count": 10,
                    "release_date": "2025-01-01",
                },
            },
            {
                "entry_key": "new-smwc",
                "title": "Brand New Hack",
                "source_references": [
                    {
                        "source": "smwc",
                        "external_id": "500",
                    }
                ],
                "attributes": {
                    "authors": ["New Author"],
                    "difficulty": "Kaizo: Beginner",
                    "exit_count": 12,
                    "release_date": "2026-08-20",
                },
            },
            {
                "entry_key": "metadata",
                "title": "Metadata Updated Title",
                "source_references": [
                    {
                        "source": "smwc",
                        "external_id": "300",
                    }
                ],
                "attributes": {
                    "authors": ["Metadata Author"],
                    "difficulty": "Advanced",
                    "exit_count": 15,
                    "release_date": "2025-03-01",
                },
            },
            {
                "entry_key": "ambiguous",
                "title": "Duplicate Candidate",
                "source_references": [],
                "attributes": {
                    "authors": ["Ambiguous Author"],
                    "difficulty": "Advanced",
                    "exit_count": 7,
                },
            },
        ],
        "groups": [
            {
                "group_key": "all",
                "title": "All",
                "entry_keys": [
                    "unchanged",
                    "new-smwc",
                    "metadata",
                    "ambiguous",
                ],
            }
        ],
    }


class BulkCollectionImportEndToEndHardeningTest(unittest.TestCase):
    """Exercise the assembled v5.1 import path against real temp files."""

    def _fixture(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)

        processed = root / "processed.json"
        processed.write_text(
            json.dumps(
                _initial_collection(),
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        import_path = root / "bulk-import.json"
        import_path.write_text(
            json.dumps(
                _import_document(),
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        manager = HackDataManager(str(processed))
        manager._schedule_delayed_save = lambda: None
        return root, processed, import_path, manager

    @staticmethod
    def _first_round_selections(form):
        selections = {}

        for item in form.items:
            if item.review_kind == REVIEW_KIND_AMBIGUOUS_IDENTITY:
                candidate_keys = tuple(
                    candidate.collection_key
                    for candidate in item.candidates
                )
                if "usr_1" not in candidate_keys:
                    raise AssertionError(
                        "Expected usr_1 in ambiguous candidates: "
                        f"{candidate_keys}"
                    )
                selections[item.entry_key] = {
                    "action": "select_existing",
                    "selected_collection_key": "usr_1",
                }
            elif item.review_kind == REVIEW_KIND_METADATA:
                selections[item.entry_key] = {
                    "action": "resolve_metadata",
                    "choices": {
                        conflict.field: "use_imported"
                        for conflict in item.conflicts
                    },
                }
            elif (
                item.review_kind
                == REVIEW_KIND_HARD_IDENTITY_CONFLICT
            ):
                selections[item.entry_key] = {
                    "action": "skip",
                }
            else:
                raise AssertionError(
                    f"Unexpected review kind: {item.review_kind}"
                )

        return selections

    @staticmethod
    def _second_round_selections(form):
        return {
            item.entry_key: {
                "action": "resolve_metadata",
                "choices": {
                    conflict.field: "use_imported"
                    for conflict in item.conflicts
                },
            }
            for item in form.items
        }

    def _build_fully_resolved_plan(
        self,
        import_path,
        manager,
    ):
        preview = plan_v5_1_bulk_collection_import_workflow_preview(
            str(import_path),
            manager,
        )

        form = build_bulk_collection_import_review_form(preview)
        review_document = build_bulk_collection_import_review_document(
            form,
            self._first_round_selections(form),
        )

        resolution = resolve_v5_1_bulk_collection_import_review(
            str(import_path),
            manager,
            review_document,
        )

        if resolution.summary["review_required"]:
            second_form = (
                build_bulk_collection_import_second_review_form(
                    resolution
                )
            )
            second_document = (
                build_bulk_collection_import_second_review_document(
                    second_form,
                    self._second_round_selections(second_form),
                )
            )
            resolution = refine_bulk_collection_import_resolution_plan(
                resolution,
                second_document,
            )

        self.assertEqual(
            resolution.summary["review_required"],
            0,
        )
        return preview, form, resolution

    def test_full_review_to_confirmed_atomic_persistence(self):
        root, processed, import_path, manager = self._fixture()
        original_bytes = processed.read_bytes()
        original = copy.deepcopy(manager.data)

        preview, form, resolution = self._build_fully_resolved_plan(
            import_path,
            manager,
        )

        self.assertEqual(preview.import_id, "end-to-end-hardening")
        self.assertEqual(
            {item.review_kind for item in form.items},
            {
                REVIEW_KIND_AMBIGUOUS_IDENTITY,
                REVIEW_KIND_METADATA,
            },
        )
        self.assertEqual(
            dict(resolution.summary),
            {
                "total": 4,
                "create_record": 1,
                "update_record": 2,
                "no_change": 1,
                "review_required": 0,
                "skip": 0,
            },
        )

        application = (
            build_v5_1_bulk_collection_import_application_preview(
                resolution,
                manager,
            )
        )
        self.assertEqual(
            tuple(
                (
                    operation.entry_key,
                    operation.action,
                    operation.collection_key,
                )
                for operation in application.operations
            ),
            (
                ("unchanged", "no_change", "100"),
                ("new-smwc", "create_record", "500"),
                ("metadata", "update_record", "300"),
                ("ambiguous", "update_record", "usr_1"),
            ),
        )

        session = create_bulk_collection_import_apply_session(
            application
        )
        self.assertEqual(
            session.state,
            "awaiting_confirmation",
        )
        confirmation = confirm_bulk_collection_import_apply_session(
            session,
            session.application_plan_sha256,
        )
        self.assertTrue(confirmation["confirmed"])
        self.assertEqual(session.state, "confirmed")

        store = BulkCollectionImportHackDataStore(manager)
        result = execute_bulk_collection_import_apply_session(
            session,
            store,
        )

        self.assertEqual(session.state, "succeeded")
        self.assertIs(session.result, result)
        self.assertEqual(
            dict(result.summary),
            {
                "total": 4,
                "created": 1,
                "updated": 2,
                "unchanged": 1,
                "skipped": 0,
            },
        )

        self.assertTrue(processed.exists())
        backup = root / "processed.json.backup"
        self.assertTrue(backup.exists())
        self.assertEqual(backup.read_bytes(), original_bytes)
        self.assertFalse(
            (
                root
                / f"processed.json{BULK_IMPORT_TEMP_SUFFIX}"
            ).exists()
        )
        self.assertFalse(manager.unsaved_changes)

        persisted = json.loads(
            processed.read_text(encoding="utf-8")
        )
        self.assertEqual(persisted, manager.data)

        # Existing no-change record retains user-owned state.
        self.assertEqual(
            persisted["100"]["notes"],
            original["100"]["notes"],
        )
        self.assertEqual(
            persisted["100"]["personal_rating"],
            5,
        )

        # First-round metadata review updates shared state only.
        self.assertEqual(
            persisted["300"]["title"],
            "Metadata Updated Title",
        )
        self.assertEqual(persisted["300"]["exits"], 15)
        self.assertEqual(
            persisted["300"]["notes"],
            "preserve metadata user note",
        )
        self.assertTrue(persisted["300"]["completed"])

        # Ambiguous selection + second-round review updates only usr_1.
        self.assertEqual(persisted["usr_1"]["exits"], 7)
        self.assertEqual(
            persisted["usr_1"]["notes"],
            "selected candidate user note",
        )
        self.assertEqual(
            persisted["usr_2"],
            original["usr_2"],
        )

        # Canonical SMWC create receives final key 500 and empty user state.
        created = persisted["500"]
        self.assertEqual(created["title"], "Brand New Hack")
        self.assertEqual(created["authors"], ["New Author"])
        self.assertEqual(
            created["current_difficulty"],
            "Kaizo: Beginner",
        )
        self.assertEqual(created["exits"], 12)
        self.assertEqual(created["date"], "2026-08-20")
        self.assertFalse(created["completed"])
        self.assertEqual(created["personal_rating"], 0)
        self.assertEqual(created["notes"], "")

        # The same confirmed session is one-shot.
        after_success = processed.read_bytes()
        with self.assertRaises(BulkCollectionImportApplyError):
            execute_bulk_collection_import_apply_session(
                session,
                BulkCollectionImportHackDataStore(manager),
            )
        self.assertEqual(processed.read_bytes(), after_success)

    def test_shared_change_after_preview_fails_before_atomic_write(self):
        root, processed, import_path, manager = self._fixture()

        _preview, _form, resolution = self._build_fully_resolved_plan(
            import_path,
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

        original_disk = processed.read_bytes()

        # A shared-state mutation invalidates the preview freshness hash.
        manager.data["300"]["exits"] = 99
        manager.unsaved_changes = True
        changed_manager = copy.deepcopy(manager.data)

        with self.assertRaises(BulkCollectionImportApplyError):
            execute_bulk_collection_import_apply_session(
                session,
                BulkCollectionImportHackDataStore(manager),
            )

        self.assertEqual(session.state, "failed")
        self.assertIsNone(session.result)
        self.assertEqual(manager.data, changed_manager)
        self.assertTrue(manager.unsaved_changes)
        self.assertEqual(processed.read_bytes(), original_disk)
        self.assertFalse(
            (root / "processed.json.backup").exists()
        )
        self.assertFalse(
            (
                root
                / f"processed.json{BULK_IMPORT_TEMP_SUFFIX}"
            ).exists()
        )

        # Failure is terminal: no hidden retry/store write is possible.
        with self.assertRaises(BulkCollectionImportApplyError):
            execute_bulk_collection_import_apply_session(
                session,
                BulkCollectionImportHackDataStore(manager),
            )
        self.assertEqual(processed.read_bytes(), original_disk)


if __name__ == "__main__":
    unittest.main(verbosity=2)
