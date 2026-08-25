import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from collection_plan_apply import (
    COLLECTION_APPLY_JOURNAL_FILENAME,
    COLLECTION_APPLY_TEMP_MARKER,
    CollectionApplyRecoveryInfo,
    CollectionPlanRecoveryError,
    inspect_interrupted_collection_apply,
)
from collection_startup_recovery import (
    ensure_collection_startup_recovery,
    inspect_collection_startup_recovery,
)


class CollectionStartupRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.processed = self.root / "processed.json"
        self.processed.write_text('{"1":{"title":"Original"}}\n', encoding="utf-8")

    def _journal(self, *, state="prepared", target="processed.json", rollback=None, staged=None):
        document = {
            "schema_version": 1,
            "transaction_id": "startup-test",
            "state": state,
            "entries": [
                {
                    "target": target,
                    "staged": staged or "",
                    "rollback": rollback or "",
                    "original_exists": True,
                }
            ],
        }
        path = self.root / COLLECTION_APPLY_JOURNAL_FILENAME
        path.write_text(json.dumps(document), encoding="utf-8")
        return path

    def test_inspection_is_read_only_and_reports_validated_state(self):
        rollback = self.root / f"processed.json{COLLECTION_APPLY_TEMP_MARKER}rollback.test.tmp"
        rollback.write_text("original", encoding="utf-8")
        journal = self._journal(state="prepared", rollback=rollback.name)
        before = journal.read_bytes()

        info = inspect_collection_startup_recovery(self.processed)

        self.assertEqual(
            info,
            CollectionApplyRecoveryInfo(
                state="prepared",
                affected_targets=("processed.json",),
            ),
        )
        self.assertEqual(journal.read_bytes(), before)
        self.assertTrue(rollback.exists())

    def test_committed_inspection_reports_cleanup_only_state(self):
        rollback = self.root / f"processed.json{COLLECTION_APPLY_TEMP_MARKER}rollback.test.tmp"
        rollback.write_text("old", encoding="utf-8")
        self._journal(state="committed", rollback=rollback.name)

        info = inspect_interrupted_collection_apply(self.root)

        self.assertIsNotNone(info)
        self.assertEqual(info.state, "committed")
        self.assertEqual(info.affected_targets, ("processed.json",))

    def test_no_journal_starts_without_confirmation(self):
        confirm = mock.Mock(side_effect=AssertionError("confirmation should not be requested"))

        self.assertTrue(
            ensure_collection_startup_recovery(
                self.processed,
                confirm_recovery=confirm,
            )
        )
        confirm.assert_not_called()

    def test_declining_recovery_leaves_everything_untouched(self):
        original = self.processed.read_bytes()
        rollback = self.root / f"processed.json{COLLECTION_APPLY_TEMP_MARKER}rollback.test.tmp"
        rollback.write_bytes(original)
        staged = self.root / f"processed.json{COLLECTION_APPLY_TEMP_MARKER}staged.test.tmp"
        staged.write_bytes(b"new")
        self.processed.write_bytes(b"partially replaced")
        journal = self._journal(
            state="prepared",
            rollback=rollback.name,
            staged=staged.name,
        )
        before_journal = journal.read_bytes()
        before_processed = self.processed.read_bytes()

        ready = ensure_collection_startup_recovery(
            self.processed,
            confirm_recovery=lambda info: False,
        )

        self.assertFalse(ready)
        self.assertEqual(journal.read_bytes(), before_journal)
        self.assertEqual(self.processed.read_bytes(), before_processed)
        self.assertTrue(rollback.exists())
        self.assertTrue(staged.exists())

    def test_confirmed_prepared_recovery_rolls_back_before_startup(self):
        original = self.processed.read_bytes()
        rollback = self.root / f"processed.json{COLLECTION_APPLY_TEMP_MARKER}rollback.test.tmp"
        rollback.write_bytes(original)
        staged = self.root / f"processed.json{COLLECTION_APPLY_TEMP_MARKER}staged.test.tmp"
        staged.write_bytes(b"new")
        self.processed.write_bytes(b"partially replaced")
        self._journal(
            state="prepared",
            rollback=rollback.name,
            staged=staged.name,
        )
        seen = []

        ready = ensure_collection_startup_recovery(
            self.processed,
            confirm_recovery=lambda info: seen.append(info) or True,
        )

        self.assertTrue(ready)
        self.assertEqual(self.processed.read_bytes(), original)
        self.assertFalse((self.root / COLLECTION_APPLY_JOURNAL_FILENAME).exists())
        self.assertFalse(rollback.exists())
        self.assertFalse(staged.exists())
        self.assertEqual(seen[0].state, "prepared")

    def test_invalid_journal_blocks_startup_without_mutation(self):
        journal = self.root / COLLECTION_APPLY_JOURNAL_FILENAME
        journal.write_text('{"schema_version":999,"state":"prepared","entries":[]}', encoding="utf-8")
        before = journal.read_bytes()
        confirm = mock.Mock()

        with self.assertRaises(CollectionPlanRecoveryError):
            ensure_collection_startup_recovery(
                self.processed,
                confirm_recovery=confirm,
            )

        confirm.assert_not_called()
        self.assertEqual(journal.read_bytes(), before)

    def test_main_gates_recovery_before_config_and_collection_ui_construction(self):
        source = Path("main.py").read_text(encoding="utf-8")
        recovery_call = source.index("startup_ready = ensure_collection_startup_recovery(")
        config_init = source.index("config_manager = ConfigManager()")
        ui_setup = source.index("download_button = setup_ui(")

        self.assertLess(recovery_call, config_init)
        self.assertLess(recovery_call, ui_setup)
        self.assertIn("default=messagebox.NO", source)
        self.assertIn("Choose No to exit", source)
        self.assertIn("Close every other", source)


if __name__ == "__main__":
    unittest.main()
