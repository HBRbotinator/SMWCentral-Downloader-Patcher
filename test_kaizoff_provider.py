"""Tests for the KaizOFF public catalogue provider."""
from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path

from collection_ingestion import (
    EvidenceStrength,
    IdentityEvidenceKind,
    IngestionSource,
)
from kaizoff_provider import (
    KAIZOFF_DETAIL_URL_TEMPLATE,
    KAIZOFF_INDEX_URL,
    KaizOffCatalogueProvider,
    KaizOffProviderError,
)


INDEX_PAYLOAD = {
    "data": [
        {
            "id": 41022,
            "name": "Super Dram World 3",
            "difficulty": "Grandmaster",
            "type": "Kaizo",
            "exits": 28,
        },
        {
            "id": 19279,
            "name": "Quickie World 2",
            "difficulty": "Intermediate",
            "type": "Kaizo",
            "exits": 22,
        },
    ],
    "count": 2,
}

DETAIL_PAYLOAD = {
    "data": {
        "id": 41022,
        "name": "Super Dram World 3",
        "section": "smwhacks",
        "time": 1765752399,
        "moderated": True,
        "authors": [{"id": 3491, "name": "PangaeaPanga"}],
        "tags": ["bosses", "chocolate", "custom music", "traditional"],
        "custom_tags": None,
        "images": ["https://dl.smwcentral.net/image/119519.png"],
        "rating": 4.625,
        "size": 1505095,
        "downloads": 3497,
        "download_url": (
            "https://dl.smwcentral.net/41022/"
            "Super%20Dram%20World%203%20v1.3.zip"
        ),
        "obsoleted_by": None,
        "fields": {
            "hof": "Yes",
            "sa1": "No",
            "demo": "No",
            "type": "Kaizo",
            "collab": "No",
            "length": "28 exit(s)",
            "version": "",
            "warnings": "",
            "changelog": "",
            "difficulty": "Grandmaster",
            "description": "Version 1.3 appears in descriptive text.",
        },
        "raw_fields": {
            "hof": True,
            "sa1": False,
            "demo": False,
            "type": ["kaizo"],
            "collab": False,
            "length": 28,
            "version": "",
            "warnings": [],
            "changelog": "",
            "difficulty": "diff_7",
            "description": "Version 1.3 appears in descriptive text.",
        },
        "difficulty": "Grandmaster",
        "type": "Kaizo",
        "exits": 28,
        "length": "28 exit(s)",
        "demo": False,
        "hof": True,
        "sa1": False,
        "collab": False,
        "description": "Version 1.3 appears in descriptive text.",
        "featured": None,
        "active": True,
        "last_fetched": "2026-07-22T13:04:29.448Z",
    }
}


class FakeFetch:
    def __init__(self):
        self.calls = []
        self.fail = False

    def __call__(self, url, timeout):
        self.calls.append((url, timeout))
        if self.fail:
            raise OSError("offline")
        if url == KAIZOFF_INDEX_URL:
            return json.loads(json.dumps(INDEX_PAYLOAD))
        if url == KAIZOFF_DETAIL_URL_TEMPLATE.format(id=41022):
            return json.loads(json.dumps(DETAIL_PAYLOAD))
        raise AssertionError(f"Unexpected URL: {url}")


class KaizOffProviderTest(unittest.TestCase):
    def test_index_is_one_lightweight_fetch_and_maps_directly_to_matcher_rows(self):
        fetch = FakeFetch()
        provider = KaizOffCatalogueProvider(fetch_json=fetch)

        snapshot = provider.get_index()

        self.assertEqual(2, len(snapshot.entries))
        self.assertEqual(41022, snapshot.entries[0].smwc_submission_id)
        self.assertEqual("Super Dram World 3", snapshot.entries[0].title)
        self.assertEqual([(KAIZOFF_INDEX_URL, 20.0)], fetch.calls)
        self.assertEqual("network", snapshot.source)
        self.assertFalse(snapshot.stale)

    def test_detail_is_fetched_lazily_by_confirmed_submission_id(self):
        fetch = FakeFetch()
        provider = KaizOffCatalogueProvider(fetch_json=fetch)

        detail = provider.get_hack(41022)
        metadata = detail.metadata

        self.assertEqual(41022, metadata.smwc_submission_id)
        self.assertEqual(("PangaeaPanga",), metadata.authors)
        self.assertEqual(("kaizo",), metadata.hack_types)
        self.assertEqual(28, metadata.exits)
        self.assertEqual(4.625, metadata.rating)
        self.assertTrue(metadata.hall_of_fame)
        self.assertTrue(metadata.active)
        self.assertIsNone(metadata.obsoleted_by_submission_id)
        self.assertEqual(
            [(KAIZOFF_DETAIL_URL_TEMPLATE.format(id=41022), 20.0)],
            fetch.calls,
        )

    def test_detail_candidate_has_exact_submission_identity_but_no_local_path(self):
        provider = KaizOffCatalogueProvider(fetch_json=FakeFetch())

        candidate = provider.get_hack(41022).metadata.as_candidate()

        self.assertEqual(IngestionSource.KAIZOFF, candidate.source)
        self.assertEqual(1, len(candidate.identity_evidence))
        identity = candidate.identity_evidence[0]
        self.assertEqual(IdentityEvidenceKind.SMWC_SUBMISSION_ID, identity.kind)
        self.assertEqual(EvidenceStrength.EXACT, identity.strength)
        self.assertEqual("41022", identity.value)
        self.assertEqual((), candidate.rom_files)
        self.assertEqual(1, len(candidate.shared_metadata))

    def test_obsoleted_by_is_preserved_only_as_metadata_not_version_inference(self):
        payload = json.loads(json.dumps(DETAIL_PAYLOAD))
        payload["data"]["obsoleted_by"] = 49999

        def fetch(_url, _timeout):
            return payload

        metadata = KaizOffCatalogueProvider(fetch_json=fetch).get_hack(41022).metadata

        self.assertEqual(49999, metadata.obsoleted_by_submission_id)
        self.assertFalse(hasattr(metadata, "latest_submission_id"))
        self.assertFalse(hasattr(metadata, "version"))

    def test_fresh_disk_index_cache_avoids_network(self):
        with tempfile.TemporaryDirectory() as temporary:
            cache = Path(temporary)
            cache_file = cache / "kaizoff_hacks_index.json"
            cache_file.write_text(json.dumps(INDEX_PAYLOAD), encoding="utf-8")

            def fail_fetch(_url, _timeout):
                raise AssertionError("network should not be used")

            provider = KaizOffCatalogueProvider(
                cache_dir=cache,
                fetch_json=fail_fetch,
                index_max_age_seconds=3600,
            )
            snapshot = provider.get_index()

            self.assertEqual("disk_cache", snapshot.source)
            self.assertFalse(snapshot.stale)
            self.assertEqual(2, len(snapshot.entries))

    def test_stale_valid_cache_is_used_only_when_refresh_fails(self):
        with tempfile.TemporaryDirectory() as temporary:
            cache = Path(temporary)
            cache_file = cache / "kaizoff_hacks_index.json"
            cache_file.write_text(json.dumps(INDEX_PAYLOAD), encoding="utf-8")
            old = time.time() - 7200
            os.utime(cache_file, (old, old))

            fetch = FakeFetch()
            fetch.fail = True
            provider = KaizOffCatalogueProvider(
                cache_dir=cache,
                fetch_json=fetch,
                index_max_age_seconds=1,
            )
            snapshot = provider.get_index()

            self.assertTrue(snapshot.stale)
            self.assertEqual("disk_cache", snapshot.source)
            self.assertEqual(2, len(snapshot.entries))
            self.assertEqual(1, len(fetch.calls))

    def test_invalid_network_payload_never_replaces_valid_stale_cache(self):
        with tempfile.TemporaryDirectory() as temporary:
            cache = Path(temporary)
            cache_file = cache / "kaizoff_hacks_index.json"
            original = json.dumps(INDEX_PAYLOAD)
            cache_file.write_text(original, encoding="utf-8")
            old = time.time() - 7200
            os.utime(cache_file, (old, old))

            def bad_fetch(_url, _timeout):
                return {"data": [{"id": 1, "name": "Only One"}], "count": 2}

            provider = KaizOffCatalogueProvider(
                cache_dir=cache,
                fetch_json=bad_fetch,
                index_max_age_seconds=1,
            )
            snapshot = provider.get_index()

            self.assertTrue(snapshot.stale)
            self.assertEqual(original, cache_file.read_text(encoding="utf-8"))

    def test_response_id_mismatch_fails_closed(self):
        payload = json.loads(json.dumps(DETAIL_PAYLOAD))
        payload["data"]["id"] = 12345

        with self.assertRaises(KaizOffProviderError):
            KaizOffCatalogueProvider(
                fetch_json=lambda _url, _timeout: payload
            ).get_hack(41022)

    def test_unexpected_download_host_is_rejected(self):
        payload = json.loads(json.dumps(DETAIL_PAYLOAD))
        payload["data"]["download_url"] = "https://example.test/file.zip"

        with self.assertRaises(KaizOffProviderError):
            KaizOffCatalogueProvider(
                fetch_json=lambda _url, _timeout: payload
            ).get_hack(41022)


if __name__ == "__main__":
    unittest.main(verbosity=2)
