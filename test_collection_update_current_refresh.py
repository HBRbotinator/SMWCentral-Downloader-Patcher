import json
from pathlib import Path
import tempfile
import unittest

from collection_identity_hints import CollectionIdentityHintsStore
from collection_update_current_refresh import (
    CollectionCurrentRefreshStaleStateError,
    finalize_current_submission_refresh_plan,
)
from collection_update_current_refresh_apply import (
    apply_finalized_current_submission_refresh,
)
from hack_data_manager import HackDataManager
from kaizoff_provider import (
    KaizOffCatalogueProvider,
    KaizOffDetailSnapshot,
    KaizOffHackMetadata,
)


SOURCE_ID = "12345"


def _detail(title="Quickie World"):
    return KaizOffDetailSnapshot(
        metadata=KaizOffHackMetadata(
            smwc_submission_id=int(SOURCE_ID),
            title=title,
            authors=("Author",),
            tags=("kaizo",),
            image_urls=(),
            rating=4.5,
            size_bytes=1000,
            downloads=10,
            download_url=f"https://dl.smwcentral.net/{SOURCE_ID}/hack.zip",
            release_timestamp=1800000000,
            difficulty="Expert",
            hack_types=("kaizo",),
            exits=14,
            demo=False,
            hall_of_fame=False,
            sa1_compatible=True,
            collaboration=False,
            description="Current detail",
            active=True,
            last_fetched="2026-08-30T00:00:00Z",
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


class CurrentSubmissionRefreshTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="current_refresh_")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.processed = self.root / "processed.json"
        self.processed.write_text(
            json.dumps(
                {
                    SOURCE_ID: {
                        "title": "Quickie World",
                        "authors": ["Old Author"],
                        "current_difficulty": "Intermediate",
                        "hack_type": "kaizo",
                        "hack_types": ["kaizo"],
                        "exits": 12,
                        "completed": True,
                        "notes": "keep me",
                        "personal_rating": 5,
                        "file_path": "C:/ROMs/Quickie World old.sfc",
                        "files": [
                            {
                                "path": "C:/ROMs/Quickie World old.sfc",
                                "name": "Quickie World old.sfc",
                                "sha256": "a" * 64,
                                "size_bytes": 100,
                                "primary": True,
                                "smwc_submission_id": int(SOURCE_ID),
                                "future_asset_field": {"keep": True},
                            }
                        ],
                        "future_record_field": [1, 2, 3],
                    }
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        self.manager = HackDataManager(str(self.processed))
        self.hints = CollectionIdentityHintsStore.beside_processed_json(self.processed)

    def _finalized(self, provider=None):
        return finalize_current_submission_refresh_plan(
            self.processed,
            SOURCE_ID,
            provider=provider or _Provider(_detail()),
            manager=self.manager,
            identity_hints=self.hints,
            participants=(),
        )

    def test_same_id_refresh_plan_has_no_identity_or_reference_migration(self):
        provider = _Provider(_detail())
        finalized = self._finalized(provider)

        self.assertEqual([(int(SOURCE_ID), True)], provider.calls)
        self.assertEqual(SOURCE_ID, finalized.source_collection_key)
        self.assertEqual((), finalized.plan.identity_migrations)
        self.assertEqual((), finalized.plan.reference_migrations)
        self.assertEqual(1, len(finalized.plan.record_intents))
        self.assertEqual(SOURCE_ID, finalized.plan.record_intents[0].target_key)
        self.assertEqual(1, len(finalized.plan.catalogue_updates))
        self.assertEqual(int(SOURCE_ID), finalized.plan.catalogue_updates[0].metadata.submission_id)
        self.assertEqual("Quickie World", finalized.plan.catalogue_updates[0].metadata.title)
        self.assertEqual((), finalized.plan.rom_updates)

    def test_metadata_only_apply_preserves_identity_user_state_and_roms(self):
        finalized = self._finalized()
        result = apply_finalized_current_submission_refresh(
            self.processed,
            finalized,
            manager=self.manager,
            identity_hints=self.hints,
            participants=(),
        )

        self.assertEqual(0, result.identity_migration_count)
        self.assertEqual([SOURCE_ID], list(self.manager.data))
        record = self.manager.data[SOURCE_ID]
        self.assertEqual("Quickie World", record["title"])
        self.assertEqual(["Author"], record["authors"])
        self.assertEqual("Expert", record["current_difficulty"])
        self.assertEqual(14, record["exits"])
        self.assertTrue(record["completed"])
        self.assertEqual("keep me", record["notes"])
        self.assertEqual(5, record["personal_rating"])
        self.assertEqual("C:/ROMs/Quickie World old.sfc", record["file_path"])
        self.assertEqual("a" * 64, record["files"][0]["sha256"])
        self.assertEqual({"keep": True}, record["files"][0]["future_asset_field"])
        self.assertEqual([1, 2, 3], record["future_record_field"])

    def test_refresh_plan_is_read_only(self):
        before_disk = self.processed.read_bytes()
        before_live = json.loads(json.dumps(self.manager.data))
        self._finalized()
        self.assertEqual(before_disk, self.processed.read_bytes())
        self.assertEqual(before_live, self.manager.data)

    def test_refresh_rejects_state_change_during_detail_hydration(self):
        def mutate():
            self.manager.data[SOURCE_ID]["notes"] = "changed"

        with self.assertRaisesRegex(CollectionCurrentRefreshStaleStateError, "changed while"):
            self._finalized(_Provider(_detail(), hook=mutate))

    def test_refresh_rejects_local_collection_identity(self):
        with self.assertRaisesRegex(Exception, "positive numeric"):
            finalize_current_submission_refresh_plan(
                self.processed,
                "usr_0123456789abcdef",
                provider=_Provider(_detail()),
                manager=self.manager,
                identity_hints=self.hints,
                participants=(),
            )


if __name__ == "__main__":
    unittest.main()
