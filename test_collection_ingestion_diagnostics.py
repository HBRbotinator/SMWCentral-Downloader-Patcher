"""Regression coverage for privacy-safe Collection import diagnostics."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from collection_ingestion import CollectionCandidate, IngestionSource, RomFileEvidence
from collection_ingestion_diagnostics import build_diagnostic_report, write_diagnostic_report
from collection_ingestion_session import CandidateReviewEntry, CollectionIngestionSession
from collection_reconciliation import (
    LocalRecordMetadataDecision,
    CandidateResolution,
    MatchBasis,
    ReconciliationGroup,
    ReviewAction,
    ReviewDecision,
    ReviewIssue,
    ReviewState,
)


class CollectionIngestionDiagnosticsTest(unittest.TestCase):
    def _session(self):
        rom = RomFileEvidence(
            path="C:/Private/User/ROMs/Bui Bui World.sfc",
            filename="Bui Bui World.sfc",
            sha256="a" * 64,
            size_bytes=1234,
            title_hint="Bui Bui World",
        )
        candidate = CollectionCandidate(
            source=IngestionSource.ROM_SCAN,
            title_hints=("Bui Bui World",),
            rom_files=(rom,),
            allow_local_only=True,
        )
        resolution = CandidateResolution(
            candidate_id="rom:0",
            candidate=candidate,
            match_basis=MatchBasis.SUGGESTED_TITLE,
            target_key="20177",
            reason="guarded title suggestion",
        )
        group = ReconciliationGroup(
            group_id="review-sha256:" + "a" * 64,
            members=(resolution,),
            proposed_target_key="20177",
            issues=(ReviewIssue(ReviewState.AMBIGUOUS, "Review weak title evidence"),),
            rom_hashes=("a" * 64,),
        )
        review = CandidateReviewEntry(
            candidate_id="rom:0",
            source=IngestionSource.ROM_SCAN,
            classification="Ambiguous",
            confidence=0.63,
            suggestions=(),
            reason="Weak suggestion retained for review only",
        )
        return CollectionIngestionSession(
            catalogue_fetched_at=1.0,
            catalogue_source="disk_cache",
            catalogue_stale=False,
            catalogue_entries=(),
            existing_collection_keys=(),
            preconditions=(),
            resolutions=(resolution,),
            groups=(group,),
            review_entries=(review,),
            suppressed_roms=(),
        )

    def test_report_omits_absolute_paths_but_keeps_filename_hash_and_match_context(self):
        session = self._session()
        decision = ReviewDecision(
            group_id=session.groups[0].group_id,
            action=ReviewAction.IMPORT_LOCAL,
        )
        report = build_diagnostic_report(
            session,
            {decision.group_id: decision},
            finalization_error=(
                "Conflicting ROM asset operations for '18612' at "
                "C:/Private/User/ROMs/Bui Bui World.sfc."
            ),
        )
        text = json.dumps(report)
        self.assertNotIn("C:/Private/User/ROMs", text)
        self.assertIn("Bui Bui World.sfc", text)
        self.assertIn("a" * 64, text)
        self.assertIn("Ambiguous", text)
        self.assertIn("Conflicting ROM asset operations", text)
        self.assertFalse(report["privacy"]["absolute_paths_included"])

    def test_write_report_is_json_and_does_not_need_rom_bytes(self):
        session = self._session()
        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / "diagnostics.json"
            written = write_diagnostic_report(destination, session)
            payload = json.loads(Path(written).read_text(encoding="utf-8"))
        self.assertEqual(payload["report"], "smwc_collection_ingestion")
        self.assertEqual(payload["summary"]["group_count"], 1)
        self.assertFalse(payload["privacy"]["raw_rom_bytes_included"])

    def test_report_includes_explicit_local_metadata_without_paths(self):
        group = self._session().groups[0]
        decision = ReviewDecision(
            group_id=group.group_id,
            action=ReviewAction.IMPORT_LOCAL,
            local_metadata=LocalRecordMetadataDecision(
                title="Local Hack",
                difficulty="Expert",
                hack_types=("kaizo",),
                exits=12,
            ),
        )
        report = build_diagnostic_report(
            self._session(), {group.group_id: decision}
        )
        metadata = report["groups"][0]["decision"]["local_metadata"]
        self.assertEqual("Local Hack", metadata["title"])
        self.assertEqual("Expert", metadata["difficulty"])
        self.assertEqual(["kaizo"], metadata["type"])
        self.assertEqual(12, metadata["exits"])



if __name__ == "__main__":
    unittest.main(verbosity=2)
