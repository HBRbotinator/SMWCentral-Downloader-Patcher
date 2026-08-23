"""Tests for the internal source/evidence model."""
from __future__ import annotations

import unittest

from collection_ingestion import (
    EvidenceStrength,
    IdentityEvidenceKind,
    IngestionSource,
    RomFileEvidence,
    SOURCE_CAPABILITIES,
)


class CollectionIngestionModelTest(unittest.TestCase):
    def test_source_capabilities_keep_remote_providers_off_local_paths(self):
        kaizoff = SOURCE_CAPABILITIES[IngestionSource.KAIZOFF]
        self.assertTrue(kaizoff.shared_metadata)
        self.assertFalse(kaizoff.rom_paths)
        self.assertFalse(kaizoff.save_paths)

        giganticbucket = SOURCE_CAPABILITIES[IngestionSource.GIGANTIC_BUCKET]
        self.assertTrue(giganticbucket.user_history)
        self.assertFalse(giganticbucket.rom_paths)
        self.assertFalse(giganticbucket.save_paths)

        rom_scan = SOURCE_CAPABILITIES[IngestionSource.ROM_SCAN]
        self.assertTrue(rom_scan.rom_paths)
        self.assertFalse(rom_scan.shared_metadata)

    def test_rom_hash_is_exact_local_identity_but_filename_id_is_strong(self):
        rom = RomFileEvidence(
            path="C:/ROMs/Super Dram World 3.sfc",
            filename="Super Dram World 3.sfc",
            sha256="a" * 64,
            size_bytes=1024,
            title_hint="Super Dram World 3",
            embedded_smwc_submission_id=41022,
        )

        evidence = rom.identity_evidence()
        by_kind = {item.kind: item for item in evidence}

        self.assertEqual(
            EvidenceStrength.EXACT,
            by_kind[IdentityEvidenceKind.ROM_SHA256].strength,
        )
        self.assertEqual(
            EvidenceStrength.STRONG,
            by_kind[IdentityEvidenceKind.SMWC_SUBMISSION_ID].strength,
        )
        self.assertEqual(
            "41022",
            by_kind[IdentityEvidenceKind.SMWC_SUBMISSION_ID].value,
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
