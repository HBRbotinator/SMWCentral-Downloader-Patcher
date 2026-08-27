import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from collection_plan_apply import collection_revision_token
from collection_rom_organization_apply import (
    COLLECTION_ROM_ORGANIZATION_JOURNAL_FILENAME,
    CollectionRomOrganizationRecoveryRequiredError,
    apply_collection_rom_organization_execution_plan,
)
from collection_rom_organization_execution_plan import CollectionRomOrganizationExecutionPlan
from collection_rom_organization_plan import CollectionRomMoveOperation
from collection_startup_recovery import (
    CollectionStartupRecoveryError,
    ensure_collection_startup_recovery,
    inspect_collection_startup_recovery,
)
from hack_data_manager import HackDataManager


class CollectionRomOrganizationStartupRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data_root = self.root / "Data"
        self.data_root.mkdir()
        self.output = self.root / "Library"
        self.source_dir = self.root / "Loose"
        self.source_dir.mkdir()
        self.source = self.source_dir / "Hack.sfc"
        self.source.write_bytes(b"rom")
        stat = self.source.stat()
        self.processed = self.data_root / "processed.json"
        sha = hashlib.sha256(b"rom").hexdigest()
        self.processed.write_text(
            json.dumps(
                {
                    "123": {
                        "title": "Hack",
                        "file_path": str(self.source.resolve()),
                        "files": [
                            {
                                "path": str(self.source.resolve()),
                                "name": "Hack.sfc",
                                "sha256": sha,
                                "size_bytes": 3,
                                "primary": True,
                                "smwc_submission_id": 123,
                            }
                        ],
                    }
                }
            )
            + "\n",
            encoding="utf-8",
        )
        self.manager = HackDataManager(str(self.processed))
        self.target = self.output / "Kaizo" / "04 - Advanced" / "Hack.sfc"
        self.plan = CollectionRomOrganizationExecutionPlan(
            output_dir=str(self.output.resolve()),
            collection_revision_token=collection_revision_token(self.manager),
            save_review_fingerprint="sha256:" + "a" * 64,
            rom_moves=(
                CollectionRomMoveOperation(
                    collection_id="123",
                    title="Hack",
                    asset_name="Hack.sfc",
                    source_path=str(self.source.resolve()),
                    target_path=str(self.target.resolve()),
                    sha256=sha,
                    size_bytes=3,
                    source_mtime_ns=stat.st_mtime_ns,
                    primary=True,
                    smwc_submission_id=123,
                ),
            ),
            save_moves=(),
            save_leaves=(),
            blocked_move_count=0,
            external_save_evidence_count=0,
            rom_only_acknowledgement_count=1,
        )

    def _leave_committed_journal(self):
        with self.assertRaises(CollectionRomOrganizationRecoveryRequiredError):
            apply_collection_rom_organization_execution_plan(
                self.plan,
                self.manager,
                fail_after_commit=True,
            )

    def test_startup_inspection_reports_rom_organization_journal_read_only(self):
        self._leave_committed_journal()
        journal = self.data_root / COLLECTION_ROM_ORGANIZATION_JOURNAL_FILENAME
        before = journal.read_bytes()

        info = inspect_collection_startup_recovery(self.processed)

        self.assertEqual("committed", info.state)
        self.assertEqual("ROM organization", info.transaction_kind)
        self.assertEqual(before, journal.read_bytes())
        self.assertTrue(self.source.exists())
        self.assertTrue(self.target.exists())

    def test_confirmed_startup_recovery_finishes_committed_source_cleanup(self):
        self._leave_committed_journal()
        seen = []

        ready = ensure_collection_startup_recovery(
            self.processed,
            confirm_recovery=lambda info: seen.append(info) or True,
        )

        self.assertTrue(ready)
        self.assertFalse(self.source.exists())
        self.assertTrue(self.target.exists())
        self.assertFalse((self.data_root / COLLECTION_ROM_ORGANIZATION_JOURNAL_FILENAME).exists())
        self.assertEqual("ROM organization", seen[0].transaction_kind)

    def test_declining_startup_recovery_leaves_committed_cleanup_untouched(self):
        self._leave_committed_journal()

        ready = ensure_collection_startup_recovery(
            self.processed,
            confirm_recovery=lambda info: False,
        )

        self.assertFalse(ready)
        self.assertTrue(self.source.exists())
        self.assertTrue(self.target.exists())
        self.assertTrue((self.data_root / COLLECTION_ROM_ORGANIZATION_JOURNAL_FILENAME).exists())

    def test_two_transaction_journals_block_startup_without_guessing_order(self):
        self._leave_committed_journal()
        (self.data_root / ".collection-plan-apply.journal.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "transaction_id": "other",
                    "state": "committed",
                    "entries": [
                        {
                            "target": "processed.json",
                            "staged": "",
                            "rollback": None,
                            "original_exists": True,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(CollectionStartupRecoveryError, "Both"):
            inspect_collection_startup_recovery(self.processed)


if __name__ == "__main__":
    unittest.main()
