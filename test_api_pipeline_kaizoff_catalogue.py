from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import patch

try:
    import patch_handler  # noqa: F401
except ModuleNotFoundError as error:
    if error.name not in {"ips_util", "bps", "bps_util"}:
        raise
    sys.modules.pop("patch_handler", None)
    patch_handler_stub = types.ModuleType("patch_handler")

    class _PatchHandler:
        @staticmethod
        def apply_patch(*_args, **_kwargs):
            raise AssertionError("Patch handler should not run in catalogue tests")

    patch_handler_stub.PatchHandler = _PatchHandler
    sys.modules["patch_handler"] = patch_handler_stub

import api_pipeline
from kaizoff_provider import (
    KaizOffCatalogueSnapshot,
    KaizOffDetailSnapshot,
    KaizOffHackMetadata,
    KaizOffIndexSnapshot,
    KaizOffProviderError,
)
from rom_title_matching import CatalogueEntry


def meta(
    identifier,
    title,
    *,
    difficulty_id="diff_3",
    difficulty="Intermediate",
    authors=("Author",),
    tags=("tag",),
    release=100,
    hof=False,
    sa1=False,
    collab=False,
    demo=False,
    hack_types=("kaizo",),
):
    return KaizOffHackMetadata(
        smwc_submission_id=identifier,
        title=title,
        authors=authors,
        tags=tags,
        image_urls=(),
        rating=4.5,
        size_bytes=123,
        downloads=99,
        download_url=f"https://dl.smwcentral.net/{identifier}/hack.zip",
        release_timestamp=release,
        difficulty=difficulty,
        hack_types=hack_types,
        exits=12,
        demo=demo,
        hall_of_fame=hof,
        sa1_compatible=sa1,
        collaboration=collab,
        description="Chocolate description",
        active=True,
        last_fetched="2026-08-29T00:00:00Z",
        obsoleted_by_submission_id=None,
        difficulty_id=difficulty_id,
        moderated=True,
    )


def index_entry(metadata):
    return CatalogueEntry(
        smwc_submission_id=metadata.smwc_submission_id,
        title=metadata.title,
        difficulty=metadata.difficulty,
        hack_type=", ".join(metadata.hack_types),
        exits=metadata.exits,
    )


class FakeProvider:
    def __init__(
        self,
        records=(),
        *,
        index_records=None,
        index_error=None,
        catalogue_error=None,
        detail_error=None,
    ):
        self.records = tuple(records)
        self.index_records = tuple(
            index_records
            if index_records is not None
            else (index_entry(row) for row in self.records)
        )
        self.index_error = index_error
        self.catalogue_error = catalogue_error
        self.detail_error = detail_error
        self.index_calls = 0
        self.catalogue_calls = 0
        self.detail_calls = []

    def get_index(self):
        self.index_calls += 1
        if self.index_error:
            raise self.index_error
        return KaizOffIndexSnapshot(self.index_records, 1.0, "memory", False)

    def get_catalogue(self):
        self.catalogue_calls += 1
        if self.catalogue_error:
            raise self.catalogue_error
        return KaizOffCatalogueSnapshot(self.records, 2.0, "memory", False)

    def get_hack(self, identifier):
        self.detail_calls.append(identifier)
        if self.detail_error:
            raise self.detail_error
        row = next(
            value for value in self.records if value.smwc_submission_id == identifier
        )
        return KaizOffDetailSnapshot(row, 3.0, "memory", False)


class CoreKaizOffCatalogueTest(unittest.TestCase):
    def setUp(self):
        api_pipeline._CORE_KAIZOFF_PROVIDER = None
        api_pipeline._CORE_KAIZOFF_QUERY_CACHE = None

    def test_sparse_name_search_uses_index_then_only_matching_detail(self):
        provider = FakeProvider(
            [meta(1, "Alpha Hack"), meta(2, "Beta Hack"), meta(3, "Alphabet")]
        )
        with patch(
            "api_pipeline._get_core_kaizoff_provider", return_value=provider
        ), patch("api_pipeline._fetch_hack_list_smwc") as smwc:
            result = api_pipeline.fetch_hack_list({"name": "alpha"}, page=1)

        self.assertEqual("kaizoff_index_detail", result["lookup_source"])
        self.assertEqual(["1", "3"], [row["id"] for row in result["data"]])
        self.assertEqual(1, provider.index_calls)
        self.assertEqual(0, provider.catalogue_calls)
        self.assertEqual([1, 3], provider.detail_calls)
        smwc.assert_not_called()

    def test_sparse_name_and_type_search_stays_on_index_path(self):
        provider = FakeProvider(
            [
                meta(1, "Alpha Standard", hack_types=("standard",)),
                meta(2, "Alpha Kaizo", hack_types=("kaizo",)),
            ]
        )
        with patch("api_pipeline._get_core_kaizoff_provider", return_value=provider):
            result = api_pipeline.fetch_hack_list(
                {"name": "alpha", "type": ["kaizo"]}, page=1
            )
        self.assertEqual(["2"], [row["id"] for row in result["data"]])
        self.assertEqual([2], provider.detail_calls)
        self.assertEqual(0, provider.catalogue_calls)

    def test_broad_index_result_switches_to_paginated_rich_catalogue(self):
        rows = [meta(i, f"Alpha {i}") for i in range(1, 31)]
        provider = FakeProvider(rows)
        with patch("api_pipeline._get_core_kaizoff_provider", return_value=provider):
            result = api_pipeline.fetch_hack_list({"name": "alpha"}, page=1)
        self.assertEqual("kaizoff_catalogue", result["lookup_source"])
        self.assertEqual(30, len(result["data"]))
        self.assertEqual(1, provider.index_calls)
        self.assertEqual(1, provider.catalogue_calls)
        self.assertEqual([], provider.detail_calls)

    def test_bulk_no_filter_uses_paginated_rich_catalogue_without_index_or_details(self):
        rows = [meta(i, f"Hack {i}") for i in range(1, 53)]
        provider = FakeProvider(rows)
        with patch("api_pipeline._get_core_kaizoff_provider", return_value=provider):
            first = api_pipeline.fetch_hack_list({}, page=1)
            second = api_pipeline.fetch_hack_list({}, page=2)
        self.assertEqual("kaizoff_catalogue", first["lookup_source"])
        self.assertEqual(50, len(first["data"]))
        self.assertEqual(["51", "52"], [row["id"] for row in second["data"]])
        self.assertEqual(0, provider.index_calls)
        self.assertEqual(2, provider.catalogue_calls)
        self.assertEqual([], provider.detail_calls)

    def test_rich_filters_use_full_catalogue_locally(self):
        provider = FakeProvider(
            [
                meta(
                    1,
                    "Alpha Hack",
                    authors=("Alice",),
                    tags=("bosses", "chocolate"),
                    hof=True,
                ),
                meta(2, "Beta Hack", authors=("Bob",), tags=("vanilla",)),
            ]
        )
        with patch("api_pipeline._get_core_kaizoff_provider", return_value=provider):
            result = api_pipeline.fetch_hack_list(
                {
                    "name": "alpha",
                    "author": "ali",
                    "tags": "bosses, chocolate",
                    "hof": "1",
                    "type": ["kaizo"],
                    "difficulties": ["intermediate"],
                },
                page=1,
            )
        self.assertEqual("kaizoff_catalogue", result["lookup_source"])
        self.assertEqual(["1"], [row["id"] for row in result["data"]])
        self.assertEqual(0, provider.index_calls)
        self.assertEqual(1, provider.catalogue_calls)

    def test_date_order_uses_rich_catalogue_before_local_pagination(self):
        rows = [meta(i, f"Hack {i}", release=i) for i in range(1, 53)]
        provider = FakeProvider(rows)
        with patch("api_pipeline._get_core_kaizoff_provider", return_value=provider):
            first = api_pipeline.fetch_hack_list({"order": "date"}, page=1)
            second = api_pipeline.fetch_hack_list({"order": "date"}, page=2)
        self.assertEqual(2, first["last_page"])
        self.assertEqual("52", first["data"][0]["id"])
        self.assertEqual(["2", "1"], [row["id"] for row in second["data"]])

    def test_index_failure_tries_kaizoff_rich_catalogue_before_smwc(self):
        provider = FakeProvider(
            [meta(1, "Alpha")],
            index_error=KaizOffProviderError("index offline"),
        )
        with patch(
            "api_pipeline._get_core_kaizoff_provider", return_value=provider
        ), patch("api_pipeline._fetch_hack_list_smwc") as smwc:
            result = api_pipeline.fetch_hack_list({"name": "alpha"}, page=1)
        self.assertEqual("kaizoff_catalogue", result["lookup_source"])
        self.assertEqual(["1"], [row["id"] for row in result["data"]])
        self.assertEqual(1, provider.index_calls)
        self.assertEqual(1, provider.catalogue_calls)
        smwc.assert_not_called()

    def test_kaizoff_paths_fall_back_once_to_smwc_when_both_fail(self):
        provider = FakeProvider(
            [meta(1, "Alpha")],
            index_error=KaizOffProviderError("index offline"),
            catalogue_error=KaizOffProviderError("catalogue offline"),
        )
        fallback = {"data": [{"id": "7"}], "last_page": 1, "current_page": 1}
        with patch(
            "api_pipeline._get_core_kaizoff_provider", return_value=provider
        ), patch(
            "api_pipeline._fetch_hack_list_smwc", return_value=fallback
        ) as smwc:
            result = api_pipeline.fetch_hack_list({"name": "alpha"}, page=1)
        self.assertEqual("smwc_fallback", result["lookup_source"])
        smwc.assert_called_once_with(
            {"name": "alpha"}, page=1, waiting_mode=False, log=None
        )

    def test_waiting_search_uses_direct_smwc_exception_without_kaizoff(self):
        provider = FakeProvider([meta(1, "Alpha")])
        fallback = {"data": [{"id": "9"}], "last_page": 1, "current_page": 1}
        with patch(
            "api_pipeline._get_core_kaizoff_provider", return_value=provider
        ), patch(
            "api_pipeline._fetch_hack_list_smwc", return_value=fallback
        ) as smwc:
            result = api_pipeline.fetch_hack_list({}, page=1, waiting_mode=True)
        self.assertEqual(fallback, result)
        self.assertEqual(0, provider.index_calls)
        self.assertEqual(0, provider.catalogue_calls)
        smwc.assert_called_once()

    def test_unknown_future_filter_falls_back_instead_of_being_ignored(self):
        provider = FakeProvider([meta(1, "Alpha")])
        fallback = {"data": [{"id": "8"}], "last_page": 1, "current_page": 1}
        with patch(
            "api_pipeline._get_core_kaizoff_provider", return_value=provider
        ), patch(
            "api_pipeline._fetch_hack_list_smwc", return_value=fallback
        ) as smwc:
            result = api_pipeline.fetch_hack_list({"future_filter": "x"}, page=1)
        self.assertEqual("smwc_fallback", result["lookup_source"])
        self.assertEqual(0, provider.index_calls)
        self.assertEqual(0, provider.catalogue_calls)
        smwc.assert_called_once()

    def test_file_metadata_uses_kaizoff_detail_and_preserves_legacy_shape(self):
        provider = FakeProvider(
            [
                meta(
                    123,
                    "Detail Hack",
                    difficulty_id="diff_7",
                    difficulty="Grandmaster",
                    authors=("A", "B"),
                    tags=("bosses",),
                    hof=True,
                    sa1=True,
                )
            ]
        )
        with patch(
            "api_pipeline._get_core_kaizoff_provider", return_value=provider
        ), patch("api_pipeline._fetch_file_metadata_smwc") as smwc:
            result = api_pipeline.fetch_file_metadata("123")
        row = result["data"]
        self.assertEqual("kaizoff", result["lookup_source"])
        self.assertEqual("123", row["id"])
        self.assertEqual("diff_7", row["raw_fields"]["difficulty"])
        self.assertEqual(["kaizo"], row["raw_fields"]["type"])
        self.assertEqual([{"name": "A"}, {"name": "B"}], row["authors"])
        smwc.assert_not_called()

    def test_file_metadata_falls_back_to_smwc_when_detail_fails(self):
        provider = FakeProvider(
            [meta(55, "Missing")], detail_error=KaizOffProviderError("missing")
        )
        with patch(
            "api_pipeline._get_core_kaizoff_provider", return_value=provider
        ), patch(
            "api_pipeline._fetch_file_metadata_smwc", return_value={"data": {"id": 55}}
        ) as smwc:
            result = api_pipeline.fetch_file_metadata(55)
        self.assertEqual("smwc_fallback", result["lookup_source"])
        self.assertEqual(55, result["data"]["id"])
        smwc.assert_called_once_with(55, log=None)


if __name__ == "__main__":
    unittest.main()
