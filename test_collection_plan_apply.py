"""Tests for transactional application of finalized Collection change plans."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from collection_change_plan import (
    CatalogueMetadataOperation,
    CatalogueMetadataSnapshot,
    CollectionChangePlan,
    IdentityMigrationOperation,
    IgnoredRomOperation,
    LocalRecordSeedOperation,
    PlannedRomAsset,
    RecordIntent,
    RecordIntentKind,
    ReferenceMigrationOperation,
    RememberedAssociationOperation,
    RomAssetsOperation,
    UserHistoryOperation,
    UserStateOperation,
)
from collection_identity_hints import CollectionIdentityHintsStore
from collection_ingestion import IngestionSource, UserPlaythroughEvidence
from collection_plan_apply import (
    COLLECTION_APPLY_JOURNAL_FILENAME,
    COLLECTION_APPLY_TEMP_MARKER,
    CollectionPlanApplyError,
    CollectionPlanStaleStateError,
    PreparedFileWrite,
    PreparedReferenceMutation,
    apply_collection_change_plan,
    collect_store_preconditions,
    recover_interrupted_collection_apply,
)
from collection_reconciliation import IdentityMigrationKind
from hack_data_manager import HackDataManager


INITIAL = {
    "100": {
        "title": "Existing Hack",
        "authors": ["Old Author"],
        "current_difficulty": "Expert",
        "hack_type": "Kaizo",
        "hack_types": ["Kaizo"],
        "exits": 10,
        "completed": True,
        "completed_date": "2025-04-10",
        "personal_rating": 5,
        "notes": "keep personal note",
        "time_to_beat": 777,
        "file_path": "C:/ROMs/existing.sfc",
        "files": [
            {
                "path": "C:/ROMs/existing.sfc",
                "name": "existing.sfc",
                "primary": True,
                "sha256": "1" * 64,
            }
        ],
        "custom_unknown": {"keep": True},
    },
    "usr_1111111111111111": {
        "title": "Local Name",
        "authors": ["Local Author"],
        "current_difficulty": "Unknown",
        "exits": 0,
        "completed": True,
        "completed_date": "2024-01-02",
        "personal_rating": 4,
        "notes": "local notes",
        "time_to_beat": 1234,
        "file_path": "D:/ROMs/local.sfc",
        "files": [
            {
                "path": "D:/ROMs/local.sfc",
                "name": "local.sfc",
                "primary": True,
                "sha256": "2" * 64,
            }
        ],
    },
}


def _file_token(path: Path) -> str:
    if not path.exists():
        return "missing"
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


class JsonReferenceParticipant:
    def __init__(self, path: Path, store_name: str = "save_associations"):
        self.path = path
        self.store_name = store_name
        self.prepare_calls = 0

    def revision_token(self) -> str:
        return _file_token(self.path)

    def prepare_reference_migrations(self, migrations):
        self.prepare_calls += 1
        expected = self.revision_token()
        data = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {"refs": []}
        refs = list(data.get("refs", []))
        for migration in migrations:
            refs = [migration.target_key if value == migration.source_key else value for value in refs]
        data["refs"] = refs
        content = (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        return PreparedReferenceMutation(
            store_name=self.store_name,
            expected_revision_token=expected,
            writes=(PreparedFileWrite(self.path, content),),
        )


class CollectionPlanApplyTest(unittest.TestCase):
    def _fixture(self, initial=None):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        processed = root / "processed.json"
        processed.write_text(
            json.dumps(initial if initial is not None else INITIAL, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        manager = HackDataManager(str(processed))
        manager._schedule_delayed_save = lambda: None
        manager._save_timer = None
        hints = CollectionIdentityHintsStore.beside_processed_json(processed)
        return root, processed, manager, hints

    @staticmethod
    def _plan(preconditions, **changes):
        values = {
            "preconditions": tuple(preconditions),
            "record_intents": (),
            "catalogue_updates": (),
            "local_record_seeds": (),
            "rom_updates": (),
            "user_history_updates": (),
            "user_state_updates": (),
            "identity_migrations": (),
            "reference_migrations": (),
            "ignored_roms": (),
            "remembered_associations": (),
            "skipped_candidate_ids": (),
            "ignored_candidate_ids": (),
        }
        values.update(changes)
        return CollectionChangePlan(**values)

    def test_preconditions_bind_manager_disk_and_hints(self):
        _, processed, manager, hints = self._fixture()

        conditions = collect_store_preconditions(manager, hints)
        names = {item.store_name for item in conditions}

        self.assertEqual(names, {"collection", "collection_identity_hints"})
        before = {item.store_name: item.revision_token for item in conditions}
        manager.data["100"]["notes"] = "pending edit"
        after_manager = {
            item.store_name: item.revision_token
            for item in collect_store_preconditions(manager, hints)
        }
        self.assertNotEqual(before["collection"], after_manager["collection"])

        manager.reload_data()
        processed.write_text(processed.read_text(encoding="utf-8") + " ", encoding="utf-8")
        after_disk = {
            item.store_name: item.revision_token
            for item in collect_store_preconditions(manager, hints)
        }
        self.assertNotEqual(before["collection"], after_disk["collection"])

    def test_new_local_record_applies_seed_rom_user_state_history_and_hints(self):
        root, processed, manager, hints = self._fixture()
        preconditions = collect_store_preconditions(manager, hints)
        history = UserPlaythroughEvidence(
            source=IngestionSource.GIGANTIC_BUCKET,
            source_record_id="gb:1:0",
            category="100%",
            play_kind="First Play",
            elapsed_text="2:03:04",
            elapsed_seconds=7384,
            completed_date_text="Jan 2, 2024",
            completed_date_iso="2024-01-02",
            notes="playthrough note",
        )
        plan = self._plan(
            preconditions,
            record_intents=(RecordIntent("usr_2222222222222222", RecordIntentKind.CREATE),),
            local_record_seeds=(
                LocalRecordSeedOperation(
                    target_key="usr_2222222222222222",
                    title="Super Bui Bui World",
                    authors=("Example",),
                    source_candidate_ids=("candidate-local",),
                ),
            ),
            rom_updates=(
                RomAssetsOperation(
                    target_key="usr_2222222222222222",
                    assets=(
                        PlannedRomAsset(
                            path="E:/ROMs/Super Bui Bui World.sfc",
                            filename="Super Bui Bui World.sfc",
                            sha256="a" * 64,
                            size_bytes=1024,
                            sources=(IngestionSource.ROM_SCAN,),
                            source_candidate_ids=("candidate-local",),
                        ),
                    ),
                    primary_path="E:/ROMs/Super Bui Bui World.sfc",
                ),
            ),
            user_history_updates=(
                UserHistoryOperation(
                    target_key="usr_2222222222222222",
                    playthroughs=(history,),
                    first_clear_decided=True,
                    first_clear_source=IngestionSource.GIGANTIC_BUCKET,
                    first_clear_source_record_id="gb:1:0",
                ),
            ),
            user_state_updates=(
                UserStateOperation(
                    target_key="usr_2222222222222222",
                    field="completed",
                    value=True,
                    source=IngestionSource.GIGANTIC_BUCKET,
                    reason="verified imported clear",
                ),
            ),
            remembered_associations=(
                RememberedAssociationOperation(
                    source=IngestionSource.ROM_SCAN,
                    value="SBBW",
                    target_key="usr_2222222222222222",
                ),
            ),
            ignored_roms=(
                IgnoredRomOperation(
                    path="E:/Backups/SBBW.sfc",
                    sha256="b" * 64,
                ),
            ),
        )

        result = apply_collection_change_plan(plan, manager, hints)

        persisted = json.loads(processed.read_text(encoding="utf-8"))
        record = persisted["usr_2222222222222222"]
        self.assertEqual(record["title"], "Super Bui Bui World")
        self.assertTrue(record["completed"])
        self.assertEqual(record["file_path"], "E:/ROMs/Super Bui Bui World.sfc")
        self.assertTrue(record["files"][0]["primary"])
        self.assertEqual(record["playthroughs"][0]["source_record_id"], "gb:1:0")
        self.assertEqual(
            record["first_clear_playthrough"],
            {"source": "giganticbucket", "source_record_id": "gb:1:0"},
        )
        hints_doc = json.loads(hints.path.read_text(encoding="utf-8"))
        self.assertEqual(hints_doc["remembered_associations"][0]["target_key"], "usr_2222222222222222")
        self.assertEqual(hints_doc["ignored_roms"][0]["sha256"], "b" * 64)
        self.assertEqual(manager.data, persisted)
        self.assertFalse((root / COLLECTION_APPLY_JOURNAL_FILENAME).exists())
        self.assertEqual(result.identity_migration_count, 0)

    def test_catalogue_refresh_owns_catalogue_fields_but_preserves_user_state(self):
        _, processed, manager, hints = self._fixture()
        preconditions = collect_store_preconditions(manager, hints)
        snapshot = CatalogueMetadataSnapshot(
            submission_id=100,
            title="Canonical Title",
            authors=("Canonical Author",),
            difficulty="Grandmaster",
            hack_types=("Kaizo",),
            exits=28,
            release_timestamp=1765752399,
            rating=4.625,
            hall_of_fame=True,
            sa1_compatible=False,
            collaboration=False,
            demo=False,
        )
        plan = self._plan(
            preconditions,
            record_intents=(RecordIntent("100", RecordIntentKind.UPDATE),),
            catalogue_updates=(
                CatalogueMetadataOperation(
                    target_key="100",
                    metadata=snapshot,
                    source=IngestionSource.KAIZOFF,
                    source_candidate_ids=("kaizoff:100",),
                ),
            ),
        )

        apply_collection_change_plan(plan, manager, hints)

        record = json.loads(processed.read_text(encoding="utf-8"))["100"]
        self.assertEqual(record["title"], "Canonical Title")
        self.assertEqual(record["current_difficulty"], "Grandmaster")
        self.assertEqual(record["exits"], 28)
        self.assertEqual(record["authors"], ["Canonical Author"])
        self.assertEqual(record["rating"], 4.625)
        self.assertNotIn("smwc_rating", record)
        self.assertEqual(record["personal_rating"], 5)
        self.assertEqual(record["notes"], "keep personal note")
        self.assertEqual(record["time_to_beat"], 777)
        self.assertEqual(record["custom_unknown"], {"keep": True})

    def test_local_promotion_migrates_collection_hints_and_registered_reference_store(self):
        root, processed, manager, hints = self._fixture()
        hints.path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "remembered_associations": [
                        {"source": "rom_scan", "value": "LocalName", "target_key": "usr_1111111111111111"}
                    ],
                    "ignored_roms": [],
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        references = root / "save_associations.json"
        references.write_text(json.dumps({"refs": ["usr_1111111111111111", "100"]}) + "\n", encoding="utf-8")
        participant = JsonReferenceParticipant(references)
        preconditions = collect_store_preconditions(manager, hints, (participant,))
        migration = IdentityMigrationOperation(
            source_key="usr_1111111111111111",
            target_key="43123",
            kind=IdentityMigrationKind.LOCAL_PROMOTION,
            merge_existing_target=False,
            prior_submission_ids=(),
            provenance=("user confirmed KaizOFF identity",),
        )
        plan = self._plan(
            preconditions,
            record_intents=(RecordIntent("43123", RecordIntentKind.CREATE),),
            identity_migrations=(migration,),
            reference_migrations=(ReferenceMigrationOperation("usr_1111111111111111", "43123"),),
        )
        original_processed = processed.read_bytes()

        result = apply_collection_change_plan(
            plan,
            manager,
            hints,
            reference_participants=(participant,),
        )

        persisted = json.loads(processed.read_text(encoding="utf-8"))
        self.assertNotIn("usr_1111111111111111", persisted)
        self.assertIn("43123", persisted)
        self.assertTrue(persisted["43123"]["completed"])
        self.assertEqual(persisted["43123"]["notes"], "local notes")
        self.assertEqual(
            persisted["43123"]["identity_migration_history"][0]["kind"],
            "local_promotion",
        )
        hints_doc = json.loads(hints.path.read_text(encoding="utf-8"))
        self.assertEqual(hints_doc["remembered_associations"][0]["target_key"], "43123")
        self.assertEqual(json.loads(references.read_text(encoding="utf-8"))["refs"], ["43123", "100"])
        self.assertEqual((root / "processed.json.backup").read_bytes(), original_processed)
        self.assertEqual(result.reference_participant_count, 1)

    def test_numeric_replacement_retains_previous_submission_provenance(self):
        initial = {
            "41022": {
                "title": "Super Dram World 3",
                "completed": True,
                "completed_date": "2025-01-01",
                "personal_rating": 5,
                "notes": "keep",
                "time_to_beat": 999,
                "file_path": "D:/ROMs/Dram.sfc",
                "files": [],
            }
        }
        _, processed, manager, hints = self._fixture(initial)
        preconditions = collect_store_preconditions(manager, hints)
        plan = self._plan(
            preconditions,
            record_intents=(RecordIntent("43123", RecordIntentKind.CREATE),),
            identity_migrations=(
                IdentityMigrationOperation(
                    source_key="41022",
                    target_key="43123",
                    kind=IdentityMigrationKind.SUBMISSION_REPLACEMENT,
                    merge_existing_target=False,
                    prior_submission_ids=(41022,),
                    provenance=("user confirmed replacement",),
                ),
            ),
            reference_migrations=(ReferenceMigrationOperation("41022", "43123"),),
        )

        apply_collection_change_plan(plan, manager, hints)

        record = json.loads(processed.read_text(encoding="utf-8"))["43123"]
        self.assertEqual(record["prior_smwc_submission_ids"], [41022])
        self.assertEqual(record["identity_migration_history"][0]["source_key"], "41022")
        self.assertEqual(record["notes"], "keep")

    def test_merge_into_existing_target_preserves_target_conflicts_and_unions_roms(self):
        initial = {
            "usr_1111111111111111": INITIAL["usr_1111111111111111"],
            "43123": {
                "title": "Canonical",
                "completed": False,
                "completed_date": "",
                "personal_rating": 5,
                "notes": "target note",
                "time_to_beat": 0,
                "file_path": "C:/ROMs/canonical.sfc",
                "files": [
                    {
                        "path": "C:/ROMs/canonical.sfc",
                        "name": "canonical.sfc",
                        "primary": True,
                        "sha256": "3" * 64,
                    }
                ],
            },
        }
        _, processed, manager, hints = self._fixture(initial)
        preconditions = collect_store_preconditions(manager, hints)
        plan = self._plan(
            preconditions,
            record_intents=(RecordIntent("43123", RecordIntentKind.UPDATE),),
            identity_migrations=(
                IdentityMigrationOperation(
                    source_key="usr_1111111111111111",
                    target_key="43123",
                    kind=IdentityMigrationKind.LOCAL_PROMOTION,
                    merge_existing_target=True,
                    prior_submission_ids=(),
                    provenance=("confirmed",),
                ),
            ),
            reference_migrations=(ReferenceMigrationOperation("usr_1111111111111111", "43123"),),
        )

        apply_collection_change_plan(plan, manager, hints)

        record = json.loads(processed.read_text(encoding="utf-8"))["43123"]
        self.assertTrue(record["completed"])
        self.assertEqual(record["completed_date"], "2024-01-02")
        self.assertEqual(record["personal_rating"], 5)
        self.assertEqual(record["notes"], "target note")
        self.assertEqual(record["time_to_beat"], 1234)
        self.assertEqual(len(record["files"]), 2)
        primaries = [item["path"] for item in record["files"] if item.get("primary")]
        self.assertEqual(primaries, ["C:/ROMs/canonical.sfc"])
        self.assertEqual(record["file_path"], "C:/ROMs/canonical.sfc")

    def test_stale_precondition_fails_without_any_write(self):
        _, processed, manager, hints = self._fixture()
        preconditions = collect_store_preconditions(manager, hints)
        plan = self._plan(
            preconditions,
            record_intents=(RecordIntent("100", RecordIntentKind.UPDATE),),
            user_state_updates=(
                UserStateOperation(
                    target_key="100",
                    field="notes",
                    value="new",
                    source=IngestionSource.MANUAL,
                    reason="reviewed",
                ),
            ),
        )
        before = processed.read_bytes()
        manager.data["100"]["notes"] = "changed after review"

        with self.assertRaises(CollectionPlanStaleStateError):
            apply_collection_change_plan(plan, manager, hints)

        self.assertEqual(processed.read_bytes(), before)
        self.assertFalse(hints.path.exists())

    def test_missing_reference_participant_precondition_fails_closed(self):
        root, _, manager, hints = self._fixture()
        participant = JsonReferenceParticipant(root / "save_associations.json")
        participant.path.write_text('{"refs":["usr_1111111111111111"]}\n', encoding="utf-8")
        preconditions = collect_store_preconditions(manager, hints)
        plan = self._plan(
            preconditions,
            record_intents=(RecordIntent("43123", RecordIntentKind.CREATE),),
            identity_migrations=(
                IdentityMigrationOperation(
                    source_key="usr_1111111111111111",
                    target_key="43123",
                    kind=IdentityMigrationKind.LOCAL_PROMOTION,
                    merge_existing_target=False,
                    prior_submission_ids=(),
                    provenance=("confirmed",),
                ),
            ),
            reference_migrations=(ReferenceMigrationOperation("usr_1111111111111111", "43123"),),
        )

        with self.assertRaises(CollectionPlanApplyError):
            apply_collection_change_plan(
                plan,
                manager,
                hints,
                reference_participants=(participant,),
            )

    def test_injected_cross_store_failure_rolls_everything_back(self):
        root, processed, manager, hints = self._fixture()
        hints.path.write_text(
            '{"schema_version":1,"remembered_associations":[],"ignored_roms":[]}\n',
            encoding="utf-8",
        )
        references = root / "save_associations.json"
        references.write_text('{"refs":["usr_1111111111111111"]}\n', encoding="utf-8")
        participant = JsonReferenceParticipant(references)
        preconditions = collect_store_preconditions(manager, hints, (participant,))
        plan = self._plan(
            preconditions,
            record_intents=(RecordIntent("43123", RecordIntentKind.CREATE),),
            identity_migrations=(
                IdentityMigrationOperation(
                    source_key="usr_1111111111111111",
                    target_key="43123",
                    kind=IdentityMigrationKind.LOCAL_PROMOTION,
                    merge_existing_target=False,
                    prior_submission_ids=(),
                    provenance=("confirmed",),
                ),
            ),
            reference_migrations=(ReferenceMigrationOperation("usr_1111111111111111", "43123"),),
            ignored_roms=(IgnoredRomOperation("D:/skip.sfc", "f" * 64),),
        )
        original_processed = processed.read_bytes()
        original_hints = hints.path.read_bytes()
        original_refs = references.read_bytes()
        original_manager = json.loads(json.dumps(manager.data))

        with self.assertRaises(CollectionPlanApplyError):
            apply_collection_change_plan(
                plan,
                manager,
                hints,
                reference_participants=(participant,),
                fail_after_replace=2,
            )

        self.assertEqual(processed.read_bytes(), original_processed)
        self.assertEqual(hints.path.read_bytes(), original_hints)
        self.assertEqual(references.read_bytes(), original_refs)
        self.assertEqual(manager.data, original_manager)
        self.assertFalse((root / COLLECTION_APPLY_JOURNAL_FILENAME).exists())
        self.assertEqual(
            tuple(path for path in root.iterdir() if COLLECTION_APPLY_TEMP_MARKER in path.name),
            (),
        )

    def test_apply_never_assumes_existing_prepared_journal_is_abandoned(self):
        root, _, manager, hints = self._fixture()
        preconditions = collect_store_preconditions(manager, hints)
        plan = self._plan(preconditions)
        (root / COLLECTION_APPLY_JOURNAL_FILENAME).write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "transaction_id": "possibly-active",
                    "state": "prepared",
                    "entries": [
                        {
                            "target": "processed.json",
                            "staged": "processed.json.collection-plan-apply.staged.x.tmp",
                            "rollback": "processed.json.collection-plan-apply.rollback.x.tmp",
                            "original_exists": True,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        with self.assertRaises(CollectionPlanApplyError):
            apply_collection_change_plan(plan, manager, hints)


    def test_recovery_rolls_back_prepared_journal_and_cleans_artifacts(self):
        root, processed, _, _ = self._fixture()
        original = processed.read_bytes()
        rollback = root / f"processed.json{COLLECTION_APPLY_TEMP_MARKER}rollback.test.tmp"
        rollback.write_bytes(original)
        staged = root / f"processed.json{COLLECTION_APPLY_TEMP_MARKER}staged.test.tmp"
        staged.write_bytes(b"new")
        processed.write_bytes(b"partially committed")
        journal = {
            "schema_version": 1,
            "transaction_id": "abc",
            "state": "prepared",
            "entries": [
                {
                    "target": "processed.json",
                    "staged": staged.name,
                    "rollback": rollback.name,
                    "original_exists": True,
                }
            ],
        }
        (root / COLLECTION_APPLY_JOURNAL_FILENAME).write_text(
            json.dumps(journal),
            encoding="utf-8",
        )

        self.assertTrue(recover_interrupted_collection_apply(root))

        self.assertEqual(processed.read_bytes(), original)
        self.assertFalse((root / COLLECTION_APPLY_JOURNAL_FILENAME).exists())
        self.assertFalse(staged.exists())
        self.assertFalse(rollback.exists())

    def test_recovery_of_committed_journal_keeps_committed_target(self):
        root, processed, _, _ = self._fixture()
        processed.write_bytes(b"committed")
        rollback = root / f"processed.json{COLLECTION_APPLY_TEMP_MARKER}rollback.test.tmp"
        rollback.write_bytes(b"old")
        journal = {
            "schema_version": 1,
            "transaction_id": "abc",
            "state": "committed",
            "entries": [
                {
                    "target": "processed.json",
                    "staged": "",
                    "rollback": rollback.name,
                    "original_exists": True,
                }
            ],
        }
        (root / COLLECTION_APPLY_JOURNAL_FILENAME).write_text(
            json.dumps(journal),
            encoding="utf-8",
        )

        self.assertTrue(recover_interrupted_collection_apply(root))

        self.assertEqual(processed.read_bytes(), b"committed")
        self.assertFalse(rollback.exists())

    def test_participant_cannot_write_outside_collection_data_directory(self):
        root, _, manager, hints = self._fixture()
        outside_dir = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(outside_dir, ignore_errors=True))

        class OutsideParticipant(JsonReferenceParticipant):
            def prepare_reference_migrations(self, migrations):
                expected = self.revision_token()
                return PreparedReferenceMutation(
                    self.store_name,
                    expected,
                    (PreparedFileWrite(outside_dir / "refs.json", b"{}\n"),),
                )

        participant = OutsideParticipant(root / "save_associations.json")
        participant.path.write_text('{"refs":[]}\n', encoding="utf-8")
        preconditions = collect_store_preconditions(manager, hints, (participant,))
        plan = self._plan(
            preconditions,
            record_intents=(RecordIntent("43123", RecordIntentKind.CREATE),),
            identity_migrations=(
                IdentityMigrationOperation(
                    source_key="usr_1111111111111111",
                    target_key="43123",
                    kind=IdentityMigrationKind.LOCAL_PROMOTION,
                    merge_existing_target=False,
                    prior_submission_ids=(),
                    provenance=("confirmed",),
                ),
            ),
            reference_migrations=(ReferenceMigrationOperation("usr_1111111111111111", "43123"),),
        )

        with self.assertRaises(CollectionPlanApplyError):
            apply_collection_change_plan(
                plan,
                manager,
                hints,
                reference_participants=(participant,),
            )
        self.assertFalse((outside_dir / "refs.json").exists())

    def test_collection_apply_refuses_pending_rom_organization_journal(self):
        root, _, manager, hints = self._fixture()
        plan = self._plan(collect_store_preconditions(manager, hints))
        (root / ".collection-rom-organization.journal.json").write_text(
            "{}",
            encoding="utf-8",
        )

        with self.assertRaisesRegex(
            CollectionPlanApplyError,
            "ROM organization transaction journal",
        ):
            apply_collection_change_plan(plan, manager, hints)



if __name__ == "__main__":
    unittest.main()
