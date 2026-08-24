"""Tests for optional Planner Collection-ID reference migration."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from collection_change_plan import (
    CollectionChangePlan,
    IdentityMigrationOperation,
    RecordIntent,
    RecordIntentKind,
    ReferenceMigrationOperation,
)
from collection_identity_hints import CollectionIdentityHintsStore
from collection_plan_apply import apply_collection_change_plan, collect_store_preconditions
from collection_reconciliation import IdentityMigrationKind
from hack_data_manager import HackDataManager
from planner_reference_participant import (
    PLANNER_REFERENCE_STORE_NAME,
    PlannerCollectionReferenceParticipant,
    PlannerReferenceError,
)


LOCAL_ID = "usr_1111111111111111"
TARGET_ID = "43123"


def _json_bytes(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


class PlannerCollectionReferenceParticipantTest(unittest.TestCase):
    def _fixture(self):
        temporary = tempfile.TemporaryDirectory(prefix="planner_reference_")
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        path = root / "planner_state.json"
        path.write_bytes(
            _json_bytes(
                {
                    "schema_version": 1,
                    "entries": {
                        "100": {"planning_horizon": "Someday"},
                        LOCAL_ID: {
                            "lifecycle_status": "Playing",
                            "planning_horizon": "Next",
                            "future_entry_field": {"keep": True},
                        },
                    },
                    "lists": [{"id": "stream", "name": "Stream"}],
                    "next_queue": ["100", LOCAL_ID],
                    "future_root_field": {"preserve": True},
                }
            )
        )
        return root, path, PlannerCollectionReferenceParticipant(path)

    def test_factory_uses_planner_state_beside_processed_json(self):
        participant = PlannerCollectionReferenceParticipant.beside_processed_json(
            "C:/AppData/processed.json"
        )

        self.assertEqual(Path("C:/AppData/planner_state.json"), participant.path)
        self.assertEqual(PLANNER_REFERENCE_STORE_NAME, participant.store_name)

    def test_missing_optional_store_is_stable_and_prepares_no_write(self):
        with tempfile.TemporaryDirectory() as temporary:
            participant = PlannerCollectionReferenceParticipant(
                Path(temporary) / "planner_state.json"
            )

            self.assertEqual("missing", participant.revision_token())
            prepared = participant.prepare_reference_migrations(
                (ReferenceMigrationOperation(LOCAL_ID, TARGET_ID),)
            )

            self.assertEqual("missing", prepared.expected_revision_token)
            self.assertEqual((), prepared.writes)
            self.assertFalse(participant.path.exists())

    def test_prepare_moves_entry_and_queue_without_touching_other_planner_state(self):
        _, path, participant = self._fixture()
        expected = participant.revision_token()

        prepared = participant.prepare_reference_migrations(
            (ReferenceMigrationOperation(LOCAL_ID, TARGET_ID),)
        )

        self.assertEqual(expected, prepared.expected_revision_token)
        self.assertEqual(1, len(prepared.writes))
        self.assertEqual(path, prepared.writes[0].path)
        self.assertEqual(expected, participant.revision_token())
        document = json.loads(prepared.writes[0].content_bytes.decode("utf-8"))
        self.assertNotIn(LOCAL_ID, document["entries"])
        self.assertEqual(
            {
                "lifecycle_status": "Playing",
                "planning_horizon": "Next",
                "future_entry_field": {"keep": True},
            },
            document["entries"][TARGET_ID],
        )
        self.assertEqual(["100", TARGET_ID], document["next_queue"])
        self.assertEqual([{"id": "stream", "name": "Stream"}], document["lists"])
        self.assertEqual({"preserve": True}, document["future_root_field"])

    def test_existing_equal_target_collapses_source_and_deduplicates_queue(self):
        _, path, participant = self._fixture()
        document = json.loads(path.read_text(encoding="utf-8"))
        document["entries"][TARGET_ID] = document["entries"][LOCAL_ID]
        document["next_queue"] = [LOCAL_ID, TARGET_ID, "100"]
        path.write_bytes(_json_bytes(document))

        prepared = participant.prepare_reference_migrations(
            (ReferenceMigrationOperation(LOCAL_ID, TARGET_ID),)
        )
        updated = json.loads(prepared.writes[0].content_bytes.decode("utf-8"))

        self.assertNotIn(LOCAL_ID, updated["entries"])
        self.assertEqual([TARGET_ID, "100"], updated["next_queue"])

    def test_different_source_and_target_planner_state_fails_closed(self):
        _, path, participant = self._fixture()
        document = json.loads(path.read_text(encoding="utf-8"))
        document["entries"][TARGET_ID] = {
            "lifecycle_status": "Completed",
            "planning_horizon": "Someday",
        }
        path.write_bytes(_json_bytes(document))

        with self.assertRaisesRegex(PlannerReferenceError, "different planning state"):
            participant.prepare_reference_migrations(
                (ReferenceMigrationOperation(LOCAL_ID, TARGET_ID),)
            )

    def test_invalid_or_future_planner_document_fails_closed(self):
        _, path, participant = self._fixture()
        path.write_text('{"schema_version":1,"entries":{},"entries":{}}', encoding="utf-8")
        with self.assertRaises(PlannerReferenceError):
            participant.prepare_reference_migrations(
                (ReferenceMigrationOperation(LOCAL_ID, TARGET_ID),)
            )

        path.write_bytes(
            _json_bytes(
                {
                    "schema_version": 2,
                    "entries": {},
                    "lists": [],
                    "next_queue": [],
                }
            )
        )
        with self.assertRaisesRegex(PlannerReferenceError, "Unsupported Planner schema"):
            participant.prepare_reference_migrations(
                (ReferenceMigrationOperation(LOCAL_ID, TARGET_ID),)
            )

        path.write_bytes(
            _json_bytes(
                {
                    "schema_version": 1,
                    "entries": [],
                    "lists": [],
                    "next_queue": [],
                }
            )
        )
        with self.assertRaisesRegex(PlannerReferenceError, "entries"):
            participant.prepare_reference_migrations(
                (ReferenceMigrationOperation(LOCAL_ID, TARGET_ID),)
            )

    def test_multiple_sources_to_one_target_are_rejected(self):
        _, _, participant = self._fixture()

        with self.assertRaisesRegex(PlannerReferenceError, "Multiple Collection identities"):
            participant.prepare_reference_migrations(
                (
                    ReferenceMigrationOperation(LOCAL_ID, TARGET_ID),
                    ReferenceMigrationOperation("usr_2222222222222222", TARGET_ID),
                )
            )


class PlannerReferenceTransactionalIntegrationTest(unittest.TestCase):
    def test_collection_and_planner_identity_move_commit_together(self):
        with tempfile.TemporaryDirectory(prefix="planner_reference_apply_") as temporary:
            root = Path(temporary)
            processed = root / "processed.json"
            processed.write_bytes(
                _json_bytes(
                    {
                        LOCAL_ID: {
                            "title": "Local Hack",
                            "authors": [],
                            "current_difficulty": "No Difficulty",
                            "hack_type": "standard",
                            "hack_types": ["standard"],
                            "exits": 10,
                            "completed": False,
                            "file_path": "",
                            "files": [],
                            "local_save_entry": True,
                        }
                    }
                )
            )
            planner = root / "planner_state.json"
            planner.write_bytes(
                _json_bytes(
                    {
                        "schema_version": 1,
                        "entries": {
                            LOCAL_ID: {
                                "lifecycle_status": "Playing",
                                "planning_horizon": "Next",
                            }
                        },
                        "lists": [],
                        "next_queue": [LOCAL_ID],
                    }
                )
            )
            manager = HackDataManager(str(processed))
            manager._schedule_delayed_save = lambda: None
            manager._save_timer = None
            hints = CollectionIdentityHintsStore.beside_processed_json(processed)
            participant = PlannerCollectionReferenceParticipant(planner)
            preconditions = collect_store_preconditions(manager, hints, (participant,))
            plan = CollectionChangePlan(
                preconditions=preconditions,
                record_intents=(RecordIntent(TARGET_ID, RecordIntentKind.CREATE),),
                catalogue_updates=(),
                local_record_seeds=(),
                rom_updates=(),
                user_history_updates=(),
                user_state_updates=(),
                identity_migrations=(
                    IdentityMigrationOperation(
                        source_key=LOCAL_ID,
                        target_key=TARGET_ID,
                        kind=IdentityMigrationKind.LOCAL_PROMOTION,
                        merge_existing_target=False,
                        prior_submission_ids=(),
                        provenance=("user confirmed",),
                    ),
                ),
                reference_migrations=(
                    ReferenceMigrationOperation(LOCAL_ID, TARGET_ID),
                ),
                ignored_roms=(),
                remembered_associations=(),
                skipped_candidate_ids=(),
                ignored_candidate_ids=(),
            )

            apply_collection_change_plan(
                plan,
                manager,
                hints,
                reference_participants=(participant,),
            )

            collection = json.loads(processed.read_text(encoding="utf-8"))
            planner_state = json.loads(planner.read_text(encoding="utf-8"))
            self.assertNotIn(LOCAL_ID, collection)
            self.assertIn(TARGET_ID, collection)
            self.assertNotIn(LOCAL_ID, planner_state["entries"])
            self.assertIn(TARGET_ID, planner_state["entries"])
            self.assertEqual([TARGET_ID], planner_state["next_queue"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
