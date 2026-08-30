"""Cross-source reconciliation tests for opaque local Collection entries."""
from __future__ import annotations

from pathlib import Path
import unittest

from collection_change_plan import PlanFinalizationError, RecordIntentKind, finalize_collection_change_plan
from collection_ingestion import CollectionCandidate, IngestionSource, RomFileEvidence
from collection_ingestion_review_model import CollectionIngestionReviewModel
from collection_ingestion_session import CollectionIngestionSession
from collection_reconciliation import (
    CandidateResolution,
    MatchBasis,
    ReviewAction,
    ReviewDecision,
    build_reconciliation_groups,
)
from local_collection_matching import (
    find_local_collection_matches,
    snapshot_local_collection_entries,
)
import save_sync


LOCAL_ID = "usr_0123456789abcdef"
OTHER_LOCAL_ID = "usr_fedcba9876543210"


def _rom(title="Grand Poo World 3"):
    return RomFileEvidence(
        path=f"C:/ROMs/{title.replace(' ', '_')}.sfc",
        filename=f"{title.replace(' ', '_')}.sfc",
        sha256="a" * 64,
        size_bytes=4194304,
        title_hint=title,
    )


def _group(title="Grand Poo World 3"):
    candidate = CollectionCandidate(
        source=IngestionSource.ROM_SCAN,
        title_hints=(title,),
        rom_files=(_rom(title),),
        allow_local_only=True,
    )
    resolution = CandidateResolution(
        candidate_id="rom:local",
        candidate=candidate,
        match_basis=MatchBasis.UNMATCHED,
        reason="No catalogue identity established.",
    )
    groups = build_reconciliation_groups((resolution,))
    assert len(groups) == 1
    return groups[0], resolution


class LocalCollectionMatchingTest(unittest.TestCase):
    def test_local_records_are_ranked_for_review_without_deriving_identity(self):
        entries = snapshot_local_collection_entries(
            {
                LOCAL_ID: {
                    "title": "Grand Poo World 3",
                    "current_difficulty": "No Difficulty",
                    "hack_types": ["standard"],
                    "exits": 41,
                },
                OTHER_LOCAL_ID: {
                    "title": "Super Bui Bui World",
                    "current_difficulty": "Unknown",
                    "hack_types": ["unknown"],
                    "exits": 0,
                },
                "17289": {"title": "Grand Poo World"},
            }
        )

        exact = find_local_collection_matches("Grand_Poo_World_3.sfc", entries)
        self.assertEqual(LOCAL_ID, exact[0].target_key)
        self.assertEqual(1.0, exact[0].confidence)

        guarded = find_local_collection_matches("Bui Bui World", entries)
        self.assertEqual(OTHER_LOCAL_ID, guarded[0].target_key)
        self.assertGreaterEqual(guarded[0].confidence, 0.68)
        self.assertLess(guarded[0].confidence, 1.0)

    def test_review_model_surfaces_frozen_existing_local_candidate(self):
        group, resolution = _group()
        session = CollectionIngestionSession(
            catalogue_fetched_at=1.0,
            catalogue_source="test",
            catalogue_stale=False,
            catalogue_entries=(),
            existing_collection_keys=(LOCAL_ID,),
            preconditions=(),
            resolutions=(resolution,),
            groups=(group,),
            review_entries=(),
            suppressed_roms=(),
            local_collection_entries=snapshot_local_collection_entries(
                {LOCAL_ID: {"title": "Grand Poo World 3", "exits": 41}}
            ),
        )
        context = CollectionIngestionReviewModel(session).context(group.group_id)
        self.assertEqual(1, len(context.local_suggestions))
        self.assertEqual(LOCAL_ID, context.local_suggestions[0].target_key)


class LocalCollectionPlanTest(unittest.TestCase):
    def test_explicit_local_attachment_updates_existing_record_without_new_seed(self):
        group, _resolution = _group()
        decision = ReviewDecision(
            group_id=group.group_id,
            action=ReviewAction.ATTACH_LOCAL,
            target_key=LOCAL_ID,
        )
        plan = finalize_collection_change_plan(
            (group,),
            {group.group_id: decision},
            existing_collection_keys=(LOCAL_ID,),
        )

        self.assertEqual(RecordIntentKind.UPDATE, plan.record_intents[0].kind)
        self.assertEqual(LOCAL_ID, plan.record_intents[0].target_key)
        self.assertEqual((), plan.local_record_seeds)
        self.assertEqual(LOCAL_ID, plan.rom_updates[0].target_key)

    def test_local_attachment_cannot_create_an_unreviewed_usr_target(self):
        group, _resolution = _group()
        decision = ReviewDecision(
            group_id=group.group_id,
            action=ReviewAction.ATTACH_LOCAL,
            target_key=LOCAL_ID,
        )
        with self.assertRaisesRegex(
            PlanFinalizationError,
            "Local attachment target is not in the reviewed Collection state",
        ):
            finalize_collection_change_plan(
                (group,),
                {group.group_id: decision},
                existing_collection_keys=(),
            )


class SaveSyncLocalAttachmentTest(unittest.TestCase):
    def test_save_can_explicitly_attach_to_existing_local_record(self):
        records = {
            LOCAL_ID: {
                "title": "Grand Poo World 3",
                "exits": 41,
                "completed": False,
            }
        }
        matches = save_sync.local_collection_matches(records, "Grand_Poo_World_3.srm")
        self.assertEqual(LOCAL_ID, matches[0].target_key)

        resolution = save_sync.resolution_for_existing_local_entry(LOCAL_ID, records)
        self.assertEqual(save_sync.RESOLUTION_EXISTS, resolution["status"])
        self.assertEqual(LOCAL_ID, resolution["hack_id"])

    def test_save_local_attachment_rejects_nonlocal_or_missing_target(self):
        records = {"17289": {"title": "Grand Poo World"}}
        resolution = save_sync.resolution_for_existing_local_entry("17289", records)
        self.assertEqual(save_sync.RESOLUTION_NO_MATCH, resolution["status"])
        resolution = save_sync.resolution_for_existing_local_entry(LOCAL_ID, records)
        self.assertEqual(save_sync.RESOLUTION_NO_MATCH, resolution["status"])

    def test_ui_wires_explicit_attach_vs_create_choices(self):
        review_source = Path("ui/collection_ingestion_review_dialog.py").read_text(encoding="utf-8")
        save_source = Path("ui/save_sync_dialog.py").read_text(encoding="utf-8")
        self.assertIn("ReviewAction.ATTACH_LOCAL", review_source)
        self.assertIn("Attach to selected existing local Collection entry", review_source)
        self.assertIn("Attach this save to the selected existing local entry", save_source)
        self.assertIn("Create a separate local Collection entry", save_source)


if __name__ == "__main__":
    unittest.main()
