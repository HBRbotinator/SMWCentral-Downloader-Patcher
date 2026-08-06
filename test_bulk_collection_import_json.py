"""Specification tests for the local bulk-import JSON adapter."""

from __future__ import annotations

import hashlib
import json
import unittest
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory


MAX_IMPORT_JSON_BYTES = 16 * 1024 * 1024

VALID_IMPORT_DOCUMENT = {
    "schema": "smwc-bulk-collection-import",
    "version": 1,
    "import_id": "local-json-suite",
    "title": "Local JSON suite",
    "entries": [
        {
            "entry_key": "hybrid-entry",
            "title": "Hybrid Entry",
            "source_references": [
                {"source": "smwc", "external_id": "12345"},
                {
                    "source": "kaizoff",
                    "external_id": "hybrid-entry",
                },
            ],
            "attributes": {
                "authors": ["Example Author"],
                "difficulty": "Kaizo: Beginner",
            },
        }
    ],
    "groups": [
        {
            "group_key": "all",
            "title": "All",
            "entry_keys": ["hybrid-entry"],
        }
    ],
}


class BulkCollectionImportJsonAdapterContractMixin:
    """Reusable behavior suite for the production JSON adapter."""

    def load_import_json(self, path):
        raise NotImplementedError

    def import_to_document(self, import_document):
        raise NotImplementedError

    def assert_adapter_error(self, path):
        raise NotImplementedError

    def _write_bytes(self, directory, name, payload):
        path = Path(directory) / name
        path.write_bytes(payload)
        return path

    def _canonical_bytes(self):
        return json.dumps(
            VALID_IMPORT_DOCUMENT,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")

    def test_valid_utf8_json_loads_with_source_metadata(self):
        with TemporaryDirectory() as directory:
            payload = self._canonical_bytes()
            path = self._write_bytes(
                directory, "community-list.json", payload
            )
            loaded = self.load_import_json(path)

            self.assertEqual(loaded.source_name, "community-list.json")
            self.assertEqual(loaded.byte_count, len(payload))
            self.assertEqual(
                loaded.sha256,
                hashlib.sha256(payload).hexdigest(),
            )
            self.assertEqual(
                self.import_to_document(loaded.document),
                VALID_IMPORT_DOCUMENT,
            )

    def test_utf8_bom_is_supported_and_hashed_exactly(self):
        with TemporaryDirectory() as directory:
            payload = b"\xef\xbb\xbf" + self._canonical_bytes()
            path = self._write_bytes(directory, "bom.JSON", payload)
            loaded = self.load_import_json(path)

            self.assertEqual(loaded.byte_count, len(payload))
            self.assertEqual(
                loaded.sha256,
                hashlib.sha256(payload).hexdigest(),
            )
            self.assertEqual(
                self.import_to_document(loaded.document),
                VALID_IMPORT_DOCUMENT,
            )

    def test_loaded_result_and_document_are_immutable(self):
        with TemporaryDirectory() as directory:
            path = self._write_bytes(
                directory,
                "immutable.json",
                self._canonical_bytes(),
            )
            loaded = self.load_import_json(path)

            with self.assertRaises((AttributeError, TypeError)):
                loaded.source_name = "changed.json"
            with self.assertRaises((AttributeError, TypeError)):
                loaded.document.title = "Changed"
            with self.assertRaises((AttributeError, TypeError)):
                loaded.document.entries[0].attributes[
                    "difficulty"
                ] = "Changed"

    def test_source_metadata_is_detached_from_later_file_changes(self):
        with TemporaryDirectory() as directory:
            payload = self._canonical_bytes()
            path = self._write_bytes(
                directory,
                "detached.json",
                payload,
            )
            loaded = self.load_import_json(path)
            path.write_text("{}", encoding="utf-8")

            self.assertEqual(loaded.byte_count, len(payload))
            self.assertEqual(
                loaded.sha256,
                hashlib.sha256(payload).hexdigest(),
            )
            self.assertEqual(
                loaded.document.import_id,
                "local-json-suite",
            )

    def test_only_regular_json_files_are_accepted(self):
        with TemporaryDirectory() as directory:
            wrong_extension = self._write_bytes(
                directory,
                "import.txt",
                self._canonical_bytes(),
            )
            missing = Path(directory) / "missing.json"
            folder = Path(directory) / "folder.json"
            folder.mkdir()

            for path in (wrong_extension, missing, folder):
                with self.subTest(path=path):
                    self.assert_adapter_error(path)

    def test_empty_invalid_utf8_and_malformed_json_are_rejected(self):
        with TemporaryDirectory() as directory:
            cases = (
                ("empty.json", b""),
                ("invalid-utf8.json", b"\xff\xfe\x00"),
                ("malformed.json", b'{"schema":'),
                ("trailing.json", b'{} trailing'),
            )
            for name, payload in cases:
                path = self._write_bytes(directory, name, payload)
                with self.subTest(name=name):
                    self.assert_adapter_error(path)

    def test_duplicate_object_keys_are_rejected_at_any_depth(self):
        with TemporaryDirectory() as directory:
            top_level = (
                b'{"schema":"smwc-bulk-collection-import",'
                b'"schema":"duplicate","version":1,'
                b'"import_id":"duplicate","title":"Duplicate",'
                b'"entries":[],"groups":[]}'
            )
            nested = (
                b'{"schema":"smwc-bulk-collection-import",'
                b'"version":1,"import_id":"duplicate",'
                b'"title":"Duplicate","entries":[{'
                b'"entry_key":"entry","title":"Entry",'
                b'"source_references":[],"attributes":{'
                b'"difficulty":"One","difficulty":"Two"}}],'
                b'"groups":[{"group_key":"all","title":"All",'
                b'"entry_keys":["entry"]}]}'
            )

            for name, payload in (
                ("duplicate-top.json", top_level),
                ("duplicate-nested.json", nested),
            ):
                path = self._write_bytes(directory, name, payload)
                with self.subTest(name=name):
                    self.assert_adapter_error(path)

    def test_oversized_input_is_rejected_before_contract_parsing(self):
        with TemporaryDirectory() as directory:
            path = self._write_bytes(
                directory,
                "oversized.json",
                b" " * (MAX_IMPORT_JSON_BYTES + 1),
            )
            self.assert_adapter_error(path)

    def test_valid_json_with_invalid_import_contract_is_rejected(self):
        invalid_documents = (
            {},
            [],
            {
                **deepcopy(VALID_IMPORT_DOCUMENT),
                "schema": "different-schema",
            },
            {
                **deepcopy(VALID_IMPORT_DOCUMENT),
                "unexpected": True,
            },
        )
        with TemporaryDirectory() as directory:
            for index, document in enumerate(invalid_documents):
                path = self._write_bytes(
                    directory,
                    f"invalid-contract-{index}.json",
                    json.dumps(document).encode("utf-8"),
                )
                with self.subTest(document=document):
                    self.assert_adapter_error(path)

    def test_adapter_never_changes_the_source_file(self):
        with TemporaryDirectory() as directory:
            payload = self._canonical_bytes()
            path = self._write_bytes(
                directory,
                "read-only.json",
                payload,
            )
            before_stat = path.stat()

            self.load_import_json(path)

            after_stat = path.stat()
            self.assertEqual(path.read_bytes(), payload)
            self.assertEqual(after_stat.st_size, before_stat.st_size)
            self.assertEqual(
                after_stat.st_mtime_ns,
                before_stat.st_mtime_ns,
            )


class BulkCollectionImportJsonAdapterSpecificationTest(
    unittest.TestCase
):
    """Validate the local JSON adapter specification itself."""

    def test_maximum_file_size_is_fixed(self):
        self.assertEqual(
            MAX_IMPORT_JSON_BYTES,
            16 * 1024 * 1024,
        )

    def test_source_metadata_is_content_based(self):
        payload = json.dumps(
            VALID_IMPORT_DOCUMENT,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        self.assertEqual(
            hashlib.sha256(payload).hexdigest(),
            hashlib.sha256(bytes(payload)).hexdigest(),
        )
        self.assertEqual(len(payload), len(bytes(payload)))

    def test_adapter_preserves_source_neutral_hybrid_identity(self):
        references = VALID_IMPORT_DOCUMENT["entries"][0][
            "source_references"
        ]
        self.assertEqual(
            {
                (item["source"], item["external_id"])
                for item in references
            },
            {
                ("smwc", "12345"),
                ("kaizoff", "hybrid-entry"),
            },
        )

    def test_contract_mixin_exposes_required_implementation_tests(self):
        names = {
            name
            for name in dir(
                BulkCollectionImportJsonAdapterContractMixin
            )
            if name.startswith("test_")
        }
        self.assertEqual(
            names,
            {
                "test_adapter_never_changes_the_source_file",
                "test_duplicate_object_keys_are_rejected_at_any_depth",
                "test_empty_invalid_utf8_and_malformed_json_are_rejected",
                "test_loaded_result_and_document_are_immutable",
                "test_only_regular_json_files_are_accepted",
                "test_oversized_input_is_rejected_before_contract_parsing",
                "test_source_metadata_is_detached_from_later_file_changes",
                "test_utf8_bom_is_supported_and_hashed_exactly",
                "test_valid_json_with_invalid_import_contract_is_rejected",
                "test_valid_utf8_json_loads_with_source_metadata",
            },
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
