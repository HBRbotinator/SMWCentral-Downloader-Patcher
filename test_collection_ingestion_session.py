"""Tests for real-source Collection ingestion session orchestration."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from collection_identity_hints import CollectionIdentityHintsStore
from collection_ingestion import IngestionSource, RomFileEvidence
from collection_ingestion_session import (
    MissingCatalogueDetailError,
    build_collection_ingestion_session,
    finalize_ingestion_session_plan,
    required_catalogue_detail_ids,
)
from collection_reconciliation import (
    FirstClearDecision,
    MatchBasis,
    ReviewAction,
    ReviewDecision,
    ReviewState,
    RomSelectionDecision,
)
from giganticbucket_ingestion import parse_giganticbucket_export
from hack_data_manager import HackDataManager
from kaizoff_provider import KaizOffHackMetadata, KaizOffIndexSnapshot
from rom_ingestion import RomLibraryScan
from rom_title_matching import CatalogueEntry


def _entry(identifier: int, title: str, difficulty: str = "Expert") -> CatalogueEntry:
    return CatalogueEntry(
        smwc_submission_id=identifier,
        title=title,
        difficulty=difficulty,
        hack_type="Kaizo",
        exits=20,
    )


def _index(*entries: CatalogueEntry, stale: bool = False) -> KaizOffIndexSnapshot:
    return KaizOffIndexSnapshot(
        entries=tuple(entries),
        fetched_at=12345.0,
        source="stale-cache" if stale else "cache",
        stale=stale,
    )


def _rom(path: str, sha: str, title: str, *, smwc_id=None, base=False) -> RomFileEvidence:
    return RomFileEvidence(
        path=path,
        filename=Path(path).name,
        sha256=sha,
        size_bytes=1024,
        title_hint=title,
        embedded_smwc_submission_id=smwc_id,
        probable_base_rom=base,
    )


def _detail(identifier: int, title: str) -> KaizOffHackMetadata:
    return KaizOffHackMetadata(
        smwc_submission_id=identifier,
        title=title,
        authors=("Author",),
        tags=("tag",),
        image_urls=(),
        rating=4.5,
        size_bytes=100,
        downloads=10,
        download_url=f"https://dl.smwcentral.net/{identifier}/example.zip",
        release_timestamp=1700000000,
        difficulty="Expert",
        hack_types=("Kaizo",),
        exits=20,
        demo=False,
        hall_of_fame=False,
        sa1_compatible=True,
        collaboration=False,
        description="Rich provider-only description",
        active=True,
        last_fetched="2026-08-23T00:00:00Z",
        obsoleted_by_submission_id=None,
    )


class _Fixture:
    def __init__(self, initial=None, hints=None):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.processed = self.root / "processed.json"
        self.processed.write_text(json.dumps(initial or {}, indent=2), encoding="utf-8")
        self.manager = HackDataManager(str(self.processed))
        self.hints_store = CollectionIdentityHintsStore.beside_processed_json(self.processed)
        if hints is not None:
            self.hints_store.path.write_text(json.dumps(hints, indent=2), encoding="utf-8")

    def close(self):
        self.temporary.cleanup()


class CollectionIngestionSessionTest(unittest.TestCase):
    def test_known_rom_hash_anchors_existing_collection_before_title_matching(self):
        sha = "a" * 64
        fixture = _Fixture(
            {
                "19279": {
                    "title": "Quickie World 2",
                    "files": [{"path": "D:/Old/QW2.sfc", "sha256": sha, "primary": True}],
                }
            }
        )
        self.addCleanup(fixture.close)
        scan = RomLibraryScan(
            root="C:/ROMs",
            roms=(_rom("C:/ROMs/weird personal name.sfc", sha, "weird personal name"),),
            duplicate_groups=(),
        )

        session = build_collection_ingestion_session(
            fixture.manager,
            fixture.hints_store,
            _index(_entry(19279, "Quickie World 2")),
            rom_scan=scan,
        )

        resolution = session.resolutions[0]
        self.assertEqual(MatchBasis.DIRECT, resolution.match_basis)
        self.assertEqual("19279", resolution.target_key)
        self.assertEqual("19279", resolution.existing_collection_key)
        self.assertEqual((ReviewState.READY,), session.groups[0].review_states)

    def test_remembered_rom_alias_is_source_scoped_direct_evidence(self):
        fixture = _Fixture(
            {"19279": {"title": "Quickie World 2"}},
            hints={
                "schema_version": 1,
                "remembered_associations": [
                    {"source": "rom_scan", "value": "QW2", "target_key": "19279"},
                    {"source": "giganticbucket", "value": "QW2", "target_key": "12345"},
                ],
                "ignored_roms": [],
            },
        )
        self.addCleanup(fixture.close)
        scan = RomLibraryScan(
            root="C:/ROMs",
            roms=(_rom("C:/ROMs/QW2.sfc", "b" * 64, "QW2"),),
            duplicate_groups=(),
        )

        session = build_collection_ingestion_session(
            fixture.manager,
            fixture.hints_store,
            _index(_entry(19279, "Quickie World 2"), _entry(12345, "Other")),
            rom_scan=scan,
        )

        self.assertEqual("19279", session.resolutions[0].target_key)
        self.assertEqual(MatchBasis.DIRECT, session.resolutions[0].match_basis)

    def test_conflicting_hash_and_explicit_filename_id_never_pick_a_winner(self):
        sha = "c" * 64
        fixture = _Fixture(
            {
                "19279": {
                    "title": "Quickie World 2",
                    "files": [{"path": "D:/QW2.sfc", "sha256": sha, "primary": True}],
                }
            }
        )
        self.addCleanup(fixture.close)
        scan = RomLibraryScan(
            root="C:/ROMs",
            roms=(_rom("C:/ROMs/QW2.sfc", sha, "Quickie World 2", smwc_id=41022),),
            duplicate_groups=(),
        )

        session = build_collection_ingestion_session(
            fixture.manager,
            fixture.hints_store,
            _index(_entry(19279, "Quickie World 2"), _entry(41022, "Super Dram World 3")),
            rom_scan=scan,
        )

        resolution = session.resolutions[0]
        self.assertEqual(MatchBasis.CONFLICT, resolution.match_basis)
        self.assertEqual({"19279", "41022"}, set(resolution.alternative_target_keys[:2]))
        self.assertIn(ReviewState.IDENTITY_CONFLICT, session.groups[0].review_states)

    def test_missing_explicit_rom_id_is_reviewed_without_title_reidentity(self):
        fixture = _Fixture()
        self.addCleanup(fixture.close)
        scan = RomLibraryScan(
            root="C:/ROMs",
            roms=(
                _rom(
                    "C:/ROMs/Quickie World 2 [SMWC-ID-99999].sfc",
                    "8" * 64,
                    "Quickie World 2",
                    smwc_id=99999,
                ),
            ),
            duplicate_groups=(),
        )

        session = build_collection_ingestion_session(
            fixture.manager,
            fixture.hints_store,
            _index(_entry(19279, "Quickie World 2")),
            rom_scan=scan,
        )

        resolution = session.resolutions[0]
        self.assertEqual(MatchBasis.SUGGESTED_TITLE, resolution.match_basis)
        self.assertEqual("99999", resolution.target_key)
        self.assertNotEqual("19279", resolution.target_key)
        self.assertIn(ReviewState.NEEDS_CONFIRMATION, session.groups[0].review_states)

    def test_title_matched_different_rom_hashes_share_review_group_but_require_selection(self):
        fixture = _Fixture()
        self.addCleanup(fixture.close)
        scan = RomLibraryScan(
            root="C:/ROMs",
            roms=(
                _rom("C:/ROMs/Quickie World 2.sfc", "d" * 64, "Quickie World 2"),
                _rom("C:/ROMs/Quickie World 2 v2.sfc", "e" * 64, "Quickie World 2"),
            ),
            duplicate_groups=(),
        )

        session = build_collection_ingestion_session(
            fixture.manager,
            fixture.hints_store,
            _index(_entry(19279, "Quickie World 2")),
            rom_scan=scan,
        )

        self.assertEqual(1, len(session.groups))
        self.assertIn(ReviewState.ROM_SELECTION_REQUIRED, session.groups[0].review_states)

    def test_ignored_exact_rom_and_probable_base_are_surfaced_but_not_reconciled(self):
        ignored_sha = "f" * 64
        fixture = _Fixture(
            hints={
                "schema_version": 1,
                "remembered_associations": [],
                "ignored_roms": [
                    {"path": "C:/ROMs/Ignore.sfc", "sha256": ignored_sha}
                ],
            }
        )
        self.addCleanup(fixture.close)
        scan = RomLibraryScan(
            root="C:/ROMs",
            roms=(
                _rom("C:/ROMs/Ignore.sfc", ignored_sha, "Ignore"),
                _rom("C:/ROMs/Super Mario World.sfc", "1" * 64, "Super Mario World", base=True),
            ),
            duplicate_groups=(),
        )

        session = build_collection_ingestion_session(
            fixture.manager,
            fixture.hints_store,
            _index(_entry(19279, "Quickie World 2")),
            rom_scan=scan,
        )

        self.assertEqual((), session.resolutions)
        self.assertEqual(2, len(session.suppressed_roms))
        self.assertIn("ignore", session.suppressed_roms[0].reason.lower())
        self.assertIn("base", session.suppressed_roms[1].reason.lower())

    def test_giganticbucket_direct_id_adds_completion_proposals_without_using_link_id_for_external(self):
        fixture = _Fixture({"19279": {"title": "Quickie World 2", "completed": False}})
        self.addCleanup(fixture.close)
        imported = parse_giganticbucket_export(
            {
                "serializationVersion": 1,
                "playedHacks": [
                    {
                        "hackId": 1,
                        "title": "Quickie World 2",
                        "link_Id": 19279,
                        "source": "SMWCHack",
                        "creators": [],
                        "playthroughs": [
                            {
                                "category": "100%",
                                "playKind": "First Play",
                                "icon": "Playthrough",
                                "time": "2:00:00",
                                "version": None,
                                "date_Completed": "Jan 2, 2020",
                                "notes": None,
                                "countsAsHack": False,
                                "exitCount": None,
                                "durationMilliseconds": None,
                                "durationPrecision": None,
                            }
                        ],
                    },
                    {
                        "hackId": 2,
                        "title": "Unknown Friend Hack",
                        "link_Id": 19279,
                        "source": "External",
                        "creators": [],
                        "playthroughs": [],
                    },
                ],
            }
        )

        session = build_collection_ingestion_session(
            fixture.manager,
            fixture.hints_store,
            _index(_entry(19279, "Quickie World 2")),
            giganticbucket=imported,
        )

        by_id = {item.candidate_id: item for item in session.resolutions}
        direct = by_id["giganticbucket:1"]
        external = by_id["giganticbucket:2"]
        self.assertEqual(MatchBasis.DIRECT, direct.match_basis)
        self.assertEqual("19279", direct.target_key)
        self.assertEqual(
            {"completed", "completed_date"},
            {item.field for item in direct.user_field_proposals},
        )
        self.assertNotEqual("19279", external.target_key)

    def test_giganticbucket_direct_id_title_conflict_is_not_silently_attached(self):
        fixture = _Fixture()
        self.addCleanup(fixture.close)
        imported = parse_giganticbucket_export(
            {
                "serializationVersion": 1,
                "playedHacks": [
                    {
                        "hackId": 1,
                        "title": "Quickie World 2",
                        "link_Id": 41022,
                        "source": "SMWCHack",
                        "creators": [],
                        "playthroughs": [],
                    }
                ],
            }
        )

        session = build_collection_ingestion_session(
            fixture.manager,
            fixture.hints_store,
            _index(_entry(19279, "Quickie World 2"), _entry(41022, "Super Dram World 3")),
            giganticbucket=imported,
        )

        resolution = session.resolutions[0]
        self.assertEqual(MatchBasis.CONFLICT, resolution.match_basis)
        self.assertIn("41022", resolution.alternative_target_keys)
        self.assertIn("19279", resolution.alternative_target_keys)
        self.assertIn(ReviewState.IDENTITY_CONFLICT, session.groups[0].review_states)

    def test_multiple_giganticbucket_runs_require_first_clear_verification(self):
        fixture = _Fixture({"19279": {"title": "Quickie World 2"}})
        self.addCleanup(fixture.close)
        runs = []
        for kind, time in (("First Play", "2:00:00"), ("Any% PB", "0:40:00")):
            runs.append(
                {
                    "category": "100%",
                    "playKind": kind,
                    "icon": "Playthrough",
                    "time": time,
                    "version": None,
                    "date_Completed": "Jan 2, 2020",
                    "notes": None,
                    "countsAsHack": False,
                    "exitCount": None,
                    "durationMilliseconds": None,
                    "durationPrecision": None,
                }
            )
        imported = parse_giganticbucket_export(
            {
                "serializationVersion": 1,
                "playedHacks": [
                    {
                        "hackId": 1,
                        "title": "Quickie World 2",
                        "link_Id": 19279,
                        "source": "SMWCHack",
                        "creators": [],
                        "playthroughs": runs,
                    }
                ],
            }
        )

        session = build_collection_ingestion_session(
            fixture.manager,
            fixture.hints_store,
            _index(_entry(19279, "Quickie World 2")),
            giganticbucket=imported,
        )

        self.assertIn(ReviewState.FIRST_CLEAR_VERIFICATION, session.groups[0].review_states)

    def test_new_numeric_target_requires_rich_detail_only_after_identity_is_resolved(self):
        fixture = _Fixture()
        self.addCleanup(fixture.close)
        scan = RomLibraryScan(
            root="C:/ROMs",
            roms=(_rom("C:/ROMs/Quickie World 2.sfc", "2" * 64, "Quickie World 2"),),
            duplicate_groups=(),
        )
        session = build_collection_ingestion_session(
            fixture.manager,
            fixture.hints_store,
            _index(_entry(19279, "Quickie World 2")),
            rom_scan=scan,
        )

        self.assertEqual((19279,), required_catalogue_detail_ids(session))
        with self.assertRaises(MissingCatalogueDetailError):
            finalize_ingestion_session_plan(session)

        plan = finalize_ingestion_session_plan(
            session,
            catalogue_details=(_detail(19279, "Quickie World 2"),),
        )
        self.assertEqual("19279", plan.record_intents[0].target_key)
        self.assertEqual("Quickie World 2", plan.catalogue_updates[0].metadata.title)
        self.assertEqual(session.preconditions, plan.preconditions)

    def test_existing_numeric_target_does_not_require_detail_just_to_add_history(self):
        fixture = _Fixture({"19279": {"title": "Quickie World 2"}})
        self.addCleanup(fixture.close)
        imported = parse_giganticbucket_export(
            {
                "serializationVersion": 1,
                "playedHacks": [
                    {
                        "hackId": 1,
                        "title": "Quickie World 2",
                        "link_Id": 19279,
                        "source": "SMWCHack",
                        "creators": [],
                        "playthroughs": [
                            {
                                "category": "100%",
                                "playKind": "First Play",
                                "icon": "Playthrough",
                                "time": "2:00:00",
                                "version": None,
                                "date_Completed": "Jan 2, 2020",
                                "notes": None,
                                "countsAsHack": False,
                                "exitCount": None,
                                "durationMilliseconds": None,
                                "durationPrecision": None,
                            }
                        ],
                    }
                ],
            }
        )
        session = build_collection_ingestion_session(
            fixture.manager,
            fixture.hints_store,
            _index(_entry(19279, "Quickie World 2")),
            giganticbucket=imported,
        )

        self.assertEqual((), required_catalogue_detail_ids(session))
        plan = finalize_ingestion_session_plan(session)
        self.assertEqual("19279", plan.user_history_updates[0].target_key)

    def test_review_decision_can_skip_new_numeric_target_without_fetching_detail(self):
        fixture = _Fixture()
        self.addCleanup(fixture.close)
        scan = RomLibraryScan(
            root="C:/ROMs",
            roms=(_rom("C:/ROMs/Quickie World 2.sfc", "3" * 64, "Quickie World 2"),),
            duplicate_groups=(),
        )
        session = build_collection_ingestion_session(
            fixture.manager,
            fixture.hints_store,
            _index(_entry(19279, "Quickie World 2")),
            rom_scan=scan,
        )
        group = session.groups[0]
        decision = ReviewDecision(group_id=group.group_id, action=ReviewAction.SKIP)

        self.assertEqual((), required_catalogue_detail_ids(session, {group.group_id: decision}))
        plan = finalize_ingestion_session_plan(session, {group.group_id: decision})
        self.assertEqual((session.resolutions[0].candidate_id,), plan.skipped_candidate_ids)

    def test_different_hash_review_finalizes_with_selected_primary_and_detail(self):
        fixture = _Fixture()
        self.addCleanup(fixture.close)
        scan = RomLibraryScan(
            root="C:/ROMs",
            roms=(
                _rom("C:/ROMs/Quickie World 2.sfc", "4" * 64, "Quickie World 2"),
                _rom("C:/ROMs/Quickie World 2 Alt.sfc", "5" * 64, "Quickie World 2"),
            ),
            duplicate_groups=(),
        )
        session = build_collection_ingestion_session(
            fixture.manager,
            fixture.hints_store,
            _index(_entry(19279, "Quickie World 2")),
            rom_scan=scan,
        )
        group = session.groups[0]
        paths = tuple(rom.path for rom in group.rom_files)
        decision = ReviewDecision(
            group_id=group.group_id,
            action=ReviewAction.ACCEPT,
            rom_selection=RomSelectionDecision(kept_paths=paths, primary_path=paths[1]),
        )

        plan = finalize_ingestion_session_plan(
            session,
            {group.group_id: decision},
            catalogue_details=(_detail(19279, "Quickie World 2"),),
        )
        self.assertEqual(paths[1], plan.rom_updates[0].primary_path)

    def test_stale_catalogue_state_is_preserved_for_ui_visibility(self):
        fixture = _Fixture()
        self.addCleanup(fixture.close)
        scan = RomLibraryScan(
            root="C:/ROMs",
            roms=(_rom("C:/ROMs/Unknown.sfc", "6" * 64, "Unknown"),),
            duplicate_groups=(),
        )
        session = build_collection_ingestion_session(
            fixture.manager,
            fixture.hints_store,
            _index(_entry(19279, "Quickie World 2"), stale=True),
            rom_scan=scan,
        )
        self.assertTrue(session.catalogue_stale)
        self.assertEqual("stale-cache", session.catalogue_source)

    def test_building_session_does_not_write_processed_or_create_hint_sidecar(self):
        fixture = _Fixture({"19279": {"title": "Quickie World 2"}})
        self.addCleanup(fixture.close)
        before = fixture.processed.read_bytes()
        scan = RomLibraryScan(
            root="C:/ROMs",
            roms=(_rom("C:/ROMs/Quickie World 2.sfc", "7" * 64, "Quickie World 2"),),
            duplicate_groups=(),
        )

        build_collection_ingestion_session(
            fixture.manager,
            fixture.hints_store,
            _index(_entry(19279, "Quickie World 2")),
            rom_scan=scan,
        )

        self.assertEqual(before, fixture.processed.read_bytes())
        self.assertFalse(fixture.hints_store.path.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
