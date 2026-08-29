import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import save_sync
from kaizoff_provider import KaizOffHackMetadata, KaizOffProviderError
from rom_title_matching import CatalogueEntry
from save_sync_catalogue import SaveSyncCatalogueLookup


def _metadata(identifier, title, *, active=True, difficulty="Advanced", difficulty_id="diff_4"):
    return KaizOffHackMetadata(
        smwc_submission_id=identifier,
        title=title,
        authors=("Author",),
        tags=(),
        image_urls=(),
        rating=4.5,
        size_bytes=100,
        downloads=10,
        download_url=f"https://dl.smwcentral.net/{identifier}/hack.zip",
        release_timestamp=1704067200,
        difficulty=difficulty,
        hack_types=("kaizo",),
        exits=12,
        demo=False,
        hall_of_fame=False,
        sa1_compatible=False,
        collaboration=False,
        description="",
        active=active,
        last_fetched="2026-08-28T00:00:00Z",
        obsoleted_by_submission_id=None if active else identifier + 1,
        difficulty_id=difficulty_id,
    )


class FakeProvider:
    def __init__(self, entries, metadata=None):
        self.entries = tuple(entries)
        self.metadata = dict(metadata or {})
        self.index_calls = 0
        self.detail_calls = []
        self.index_error = None
        self.detail_error_ids = set()

    def get_index(self):
        self.index_calls += 1
        if self.index_error:
            raise self.index_error
        return SimpleNamespace(
            entries=self.entries,
            source="network",
            stale=False,
        )

    def get_hack(self, identifier):
        self.detail_calls.append(identifier)
        if identifier in self.detail_error_ids:
            raise KaizOffProviderError("detail unavailable")
        return SimpleNamespace(metadata=self.metadata[identifier])


def _fallback_hack(identifier, name):
    return {
        "id": str(identifier),
        "name": name,
        "time": 1704067200,
        "authors": ["Fallback"],
        "raw_fields": {
            "difficulty": "diff_4",
            "type": "kaizo",
            "length": 12,
            "hof": False,
            "sa1": False,
            "collab": False,
            "demo": False,
            "obsolete": False,
        },
    }


class KaizOffFirstAutomaticLookupTest(unittest.TestCase):
    def test_checked_lookup_reuses_one_index_and_hydrates_only_exact_matches(self):
        entries = (
            CatalogueEntry(100, "Alpha Hack", "Advanced", "Kaizo", 12),
            CatalogueEntry(200, "Beta Hack", "Expert", "Kaizo", 20),
        )
        provider = FakeProvider(
            entries,
            {100: _metadata(100, "Alpha Hack"), 200: _metadata(200, "Beta Hack")},
        )
        fallback_calls = []

        def fallback(*args, **kwargs):
            fallback_calls.append((args, kwargs))
            raise AssertionError("automatic lookup must not use direct SMWC fallback")

        lookup = SaveSyncCatalogueLookup(provider=provider, fallback_fetch_fn=fallback)

        alpha = lookup.resolve_automatic("Alpha_Hack_v1.0.srm", set())
        missing = lookup.resolve_automatic("No Such Hack.srm", set())
        beta = lookup.resolve_automatic("Beta Hack.srm", {"200"})

        self.assertEqual(save_sync.RESOLUTION_RESOLVED, alpha["status"])
        self.assertEqual("100", alpha["hack_id"])
        self.assertEqual("diff_4", alpha["hack"]["raw_fields"]["difficulty"])
        self.assertEqual(save_sync.RESOLUTION_NO_MATCH, missing["status"])
        self.assertEqual(save_sync.RESOLUTION_EXISTS, beta["status"])
        self.assertEqual(1, provider.index_calls)
        self.assertEqual([100, 200], provider.detail_calls)
        self.assertEqual([], fallback_calls)

    def test_bulk_lookup_does_not_fall_back_to_direct_smwc_when_index_is_unavailable(self):
        provider = FakeProvider(())
        provider.index_error = KaizOffProviderError("offline")
        fallback_calls = []

        def fallback(*args, **kwargs):
            fallback_calls.append((args, kwargs))
            return {"data": []}

        lookup = SaveSyncCatalogueLookup(provider=provider, fallback_fetch_fn=fallback)
        first = lookup.resolve_automatic("Alpha.srm", set())
        second = lookup.resolve_automatic("Beta.srm", set())

        self.assertEqual(save_sync.RESOLUTION_ERROR, first["status"])
        self.assertTrue(first["catalogue_unavailable"])
        self.assertEqual(save_sync.RESOLUTION_ERROR, second["status"])
        self.assertEqual(1, provider.index_calls)
        self.assertEqual([], fallback_calls)

    def test_duplicate_exact_titles_use_rich_status_to_prefer_one_live_submission(self):
        entries = (
            CatalogueEntry(100, "Colors"),
            CatalogueEntry(200, "Colors"),
        )
        provider = FakeProvider(
            entries,
            {
                100: _metadata(100, "Colors", active=False),
                200: _metadata(200, "Colors", active=True),
            },
        )
        lookup = SaveSyncCatalogueLookup(provider=provider)

        resolution = lookup.resolve_automatic("Colors.srm", set())

        self.assertEqual(save_sync.RESOLUTION_RESOLVED, resolution["status"])
        self.assertEqual("200", resolution["hack_id"])
        self.assertEqual([100, 200], provider.detail_calls)


class KaizOffFirstManualLookupTest(unittest.TestCase):
    def test_manual_search_is_local_and_detail_is_lazy_until_selection(self):
        entries = (
            CatalogueEntry(100, "Alpha Hack", "Advanced", "Kaizo", 12),
            CatalogueEntry(200, "Alpha Adventure", "Expert", "Kaizo", 20),
            CatalogueEntry(300, "Unrelated", "Casual", "Standard", 4),
        )
        provider = FakeProvider(
            entries,
            {100: _metadata(100, "Alpha Hack"), 200: _metadata(200, "Alpha Adventure")},
        )
        lookup = SaveSyncCatalogueLookup(provider=provider)

        result = lookup.search_manual("Alpha", set())

        self.assertEqual(save_sync.SEARCH_RESULTS, result["status"])
        self.assertEqual("kaizoff", result["lookup_source"])
        self.assertGreaterEqual(len(result["options"]), 2)
        self.assertEqual([], provider.detail_calls)

        selected = next(option for option in result["options"] if option["hack_id"] == "100")
        resolution = lookup.resolve_selected_option(selected, set())

        self.assertEqual(save_sync.RESOLUTION_RESOLVED, resolution["status"])
        self.assertEqual("100", resolution["hack_id"])
        self.assertEqual([100], provider.detail_calls)

    def test_manual_search_uses_one_direct_smwc_fallback_when_kaizoff_is_unavailable(self):
        provider = FakeProvider(())
        provider.index_error = KaizOffProviderError("offline")
        calls = []

        def fallback(config, page=1, waiting_mode=False, log=None):
            calls.append(dict(config))
            return {"data": [_fallback_hack(100, "Alpha Hack")], "last_page": 1}

        lookup = SaveSyncCatalogueLookup(provider=provider, fallback_fetch_fn=fallback)
        result = lookup.search_manual("Alpha Hack", set())

        self.assertEqual(save_sync.SEARCH_RESULTS, result["status"])
        self.assertEqual("smwc_fallback", result["lookup_source"])
        self.assertEqual(1, len(calls))
        self.assertEqual("Alpha Hack", calls[0]["name"])
        self.assertEqual("smwc_fallback", result["options"][0]["lookup_source"])

    def test_selected_detail_failure_falls_back_to_same_smwc_submission_id(self):
        entry = CatalogueEntry(100, "Alpha Hack", "Advanced", "Kaizo", 12)
        provider = FakeProvider((entry,), {100: _metadata(100, "Alpha Hack")})
        provider.detail_error_ids.add(100)
        calls = []

        def fallback(config, page=1, waiting_mode=False, log=None):
            calls.append(dict(config))
            return {"data": [_fallback_hack(100, "Alpha Hack")], "last_page": 1}

        lookup = SaveSyncCatalogueLookup(provider=provider, fallback_fetch_fn=fallback)
        option = lookup.search_manual("Alpha Hack", set())["options"][0]
        resolution = lookup.resolve_selected_option(option, set())

        self.assertEqual(save_sync.RESOLUTION_RESOLVED, resolution["status"])
        self.assertEqual("100", resolution["hack_id"])
        self.assertEqual(1, len(calls))


class SaveSyncKaizOffUiContractTest(unittest.TestCase):
    def test_dialog_keeps_smwc_user_wording_but_routes_production_lookup_through_shared_service(self):
        source = Path("ui/save_sync_dialog.py").read_text(encoding="utf-8")
        self.assertIn('text="Look up checked on SMWC"', source)
        self.assertIn("SaveSyncCatalogueLookup", source)
        self.assertIn("lookup.resolve_automatic", source)
        self.assertIn("lookup_service.search_manual", source)
        self.assertIn("lookup_service.resolve_selected_option", source)
        self.assertIn("manual search can use SMWC fallback", source)


if __name__ == "__main__":
    unittest.main()
