from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from collection_identity_hints import CollectionIdentityHintsStore
from collection_plan_apply import apply_collection_change_plan
from collection_reconciliation import IdentityMigrationKind
from collection_update_discovery import CollectionUpdateSelection
from collection_update_plan import (
    CollectionUpdateExistingTargetError,
    CollectionUpdatePlanError,
    CollectionUpdatePlanStaleStateError,
    finalize_collection_update_replacement_plan,
)
from hack_data_manager import HackDataManager
from kaizoff_provider import (
    KaizOffCatalogueProvider,
    KaizOffDetailSnapshot,
    KaizOffHackMetadata,
)
from planner_reference_participant import PlannerCollectionReferenceParticipant
from rom_title_matching import CatalogueEntry


SOURCE_ID = "41022"
TARGET_ID = "43123"


def _detail(identifier=int(TARGET_ID), title="Super Dram World 3 Updated"):
    return KaizOffDetailSnapshot(
        metadata=KaizOffHackMetadata(
            smwc_submission_id=identifier,
            title=title,
            authors=("PangaeaPanga",),
            tags=("kaizo",),
            image_urls=(),
            rating=4.75,
            size_bytes=123456,
            downloads=99,
            download_url=f"https://dl.smwcentral.net/{identifier}/hack.zip",
            release_timestamp=1800000000,
            difficulty="Grandmaster",
            hack_types=("kaizo",),
            exits=30,
            demo=False,
            hall_of_fame=True,
            sa1_compatible=False,
            collaboration=False,
            description="Rich target detail",
            active=True,
            last_fetched="2026-08-25T00:00:00Z",
            obsoleted_by_submission_id=None,
        ),
        fetched_at=2222.0,
        source="network",
        stale=False,
    )


class _Provider(KaizOffCatalogueProvider):
    def __init__(self, detail, hook=None):
        self.detail = detail
        self.hook = hook
        self.calls = []

    def get_hack(self, smwc_submission_id, *, force_refresh=False):
        self.calls.append((smwc_submission_id, force_refresh))
        if self.hook:
            self.hook()
        return self.detail


def _selection(*, target_already_in_collection=False):
    return CollectionUpdateSelection(
        source_collection_key=SOURCE_ID,
        source_entry=CatalogueEntry(
            int(SOURCE_ID),
            "Super Dram World 3",
            difficulty="Grandmaster",
            hack_type="Kaizo",
            exits=28,
        ),
        target_entry=CatalogueEntry(
            int(TARGET_ID),
            "Super Dram World 3 Updated",
            difficulty="Grandmaster",
            hack_type="Kaizo",
            exits=30,
        ),
        target_already_in_collection=target_already_in_collection,
        catalogue_fetched_at=1111.0,
        catalogue_source="network",
        catalogue_stale=False,
    )


class _Fixture:
    def __init__(self, records=None):
        self.temporary = tempfile.TemporaryDirectory(prefix="collection_update_plan_")
        self.root = Path(self.temporary.name)
        self.processed = self.root / "processed.json"
        default = {
            SOURCE_ID: {
                "title": "Super Dram World 3",
                "authors": ["PangaeaPanga"],
                "current_difficulty": "Grandmaster",
                "hack_type": "kaizo",
                "hack_types": ["kaizo"],
                "exits": 28,
                "completed": True,
                "notes": "keep me",
                "personal_rating": 5,
                "prior_smwc_submission_ids": [39000],
                "file_path": "C:/ROMs/Super Dram World 3.sfc",
                "files": [
                    {
                        "path": "C:/ROMs/Super Dram World 3.sfc",
                        "name": "Super Dram World 3.sfc",
                        "sha256": "a" * 64,
                        "size_bytes": 100,
                        "primary": True,
                    }
                ],
            }
        }
        self.processed.write_text(json.dumps(records or default, indent=2), encoding="utf-8")
        self.manager = HackDataManager(str(self.processed))
        self.hints = CollectionIdentityHintsStore.beside_processed_json(self.processed)

    def close(self):
        self.temporary.cleanup()


class CollectionUpdatePlanTests(unittest.TestCase):
    def setUp(self):
        self.fixture = _Fixture()
        self.addCleanup(self.fixture.close)

    def test_explicit_selection_becomes_one_immutable_submission_replacement_plan(self):
        provider = _Provider(_detail())

        finalized = finalize_collection_update_replacement_plan(
            _selection(),
            self.fixture.manager,
            self.fixture.hints,
            provider,
            participants=(),
        )

        self.assertEqual([(int(TARGET_ID), True)], provider.calls)
        self.assertEqual(1, len(finalized.plan.identity_migrations))
        migration = finalized.plan.identity_migrations[0]
        self.assertEqual(SOURCE_ID, migration.source_key)
        self.assertEqual(TARGET_ID, migration.target_key)
        self.assertEqual(IdentityMigrationKind.SUBMISSION_REPLACEMENT, migration.kind)
        self.assertFalse(migration.merge_existing_target)
        self.assertEqual((int(SOURCE_ID), 39000), migration.prior_submission_ids)
        self.assertIn("explicitly confirmed", migration.provenance[0])
        self.assertEqual(1, len(finalized.plan.reference_migrations))
        self.assertEqual(1, len(finalized.plan.catalogue_updates))
        self.assertEqual("Super Dram World 3 Updated", finalized.plan.catalogue_updates[0].metadata.title)
        self.assertEqual((), finalized.plan.rom_updates)
        self.assertEqual("network", finalized.detail_source)
        self.assertFalse(finalized.detail_stale)

    def test_finalized_plan_is_compatible_with_transactional_apply_without_losing_user_state(self):
        finalized = finalize_collection_update_replacement_plan(
            _selection(),
            self.fixture.manager,
            self.fixture.hints,
            _Provider(_detail()),
            participants=(),
        )

        apply_collection_change_plan(
            finalized.plan,
            self.fixture.manager,
            self.fixture.hints,
            reference_participants=(),
        )

        self.assertNotIn(SOURCE_ID, self.fixture.manager.data)
        record = self.fixture.manager.data[TARGET_ID]
        self.assertEqual("Super Dram World 3 Updated", record["title"])
        self.assertTrue(record["completed"])
        self.assertEqual("keep me", record["notes"])
        self.assertEqual(5, record["personal_rating"])
        self.assertEqual("C:/ROMs/Super Dram World 3.sfc", record["file_path"])
        self.assertEqual([39000, int(SOURCE_ID)], record["prior_smwc_submission_ids"])
        self.assertEqual(SOURCE_ID, record["identity_migration_history"][-1]["source_key"])
        self.assertEqual(TARGET_ID, record["identity_migration_history"][-1]["target_key"])

    def test_finalization_is_read_only_and_does_not_touch_collection_or_roms(self):
        before = self.fixture.processed.read_bytes()
        manager_before = json.loads(json.dumps(self.fixture.manager.data))

        finalized = finalize_collection_update_replacement_plan(
            _selection(),
            self.fixture.manager,
            self.fixture.hints,
            _Provider(_detail()),
            participants=(),
        )

        self.assertEqual(before, self.fixture.processed.read_bytes())
        self.assertEqual(manager_before, self.fixture.manager.data)
        self.assertFalse(self.fixture.hints.path.exists())
        self.assertEqual(0, sum(len(item.assets) for item in finalized.plan.rom_updates))

    def test_existing_numeric_target_fails_closed_until_user_state_merge_review_exists(self):
        target = {
            "title": "Existing Target",
            "completed": False,
            "notes": "independent target notes",
            "file_path": "",
            "files": [],
        }
        records = dict(self.fixture.manager.data)
        records[TARGET_ID] = target
        self.fixture.close()
        self.fixture = _Fixture(records)
        self.addCleanup(self.fixture.close)

        with self.assertRaisesRegex(CollectionUpdateExistingTargetError, "explicit review"):
            finalize_collection_update_replacement_plan(
                _selection(target_already_in_collection=True),
                self.fixture.manager,
                self.fixture.hints,
                _Provider(_detail()),
                participants=(),
            )

    def test_prior_submission_target_is_rejected_as_a_cycle(self):
        self.fixture.manager.data[SOURCE_ID]["prior_smwc_submission_ids"] = [int(TARGET_ID)]

        with self.assertRaisesRegex(CollectionUpdatePlanError, "replacement cycle"):
            finalize_collection_update_replacement_plan(
                _selection(),
                self.fixture.manager,
                self.fixture.hints,
                _Provider(_detail()),
                participants=(),
            )

    def test_user_owned_store_change_during_detail_fetch_stales_finalization(self):
        def mutate_collection():
            self.fixture.manager.data[SOURCE_ID]["notes"] = "changed during fetch"

        with self.assertRaisesRegex(CollectionUpdatePlanStaleStateError, "state changed"):
            finalize_collection_update_replacement_plan(
                _selection(),
                self.fixture.manager,
                self.fixture.hints,
                _Provider(_detail(), mutate_collection),
                participants=(),
            )

    def test_planner_reference_conflict_is_preflighted_before_preview(self):
        planner_path = self.fixture.root / "planner_state.json"
        planner_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "entries": {
                        SOURCE_ID: {"planning_horizon": "Next"},
                        TARGET_ID: {"planning_horizon": "Someday"},
                    },
                    "lists": [],
                    "next_queue": [SOURCE_ID, TARGET_ID],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        participant = PlannerCollectionReferenceParticipant(planner_path)

        with self.assertRaisesRegex(CollectionUpdatePlanError, "cannot safely follow"):
            finalize_collection_update_replacement_plan(
                _selection(),
                self.fixture.manager,
                self.fixture.hints,
                _Provider(_detail()),
                participants=(participant,),
            )

    def test_hydrated_detail_must_match_the_explicit_selected_target_id(self):
        with self.assertRaisesRegex(CollectionUpdatePlanError, "does not match"):
            finalize_collection_update_replacement_plan(
                _selection(),
                self.fixture.manager,
                self.fixture.hints,
                _Provider(_detail(identifier=99999)),
                participants=(),
            )


if __name__ == "__main__":
    unittest.main()
