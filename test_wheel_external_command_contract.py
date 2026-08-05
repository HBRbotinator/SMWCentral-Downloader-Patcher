"""Specification tests for the external Wheel command contract."""

from __future__ import annotations

import json
import re
import unittest
from copy import deepcopy


COMMAND_SCHEMA = "smwc-wheel-command"
COMMAND_VERSION = 1
COMMAND_ACTIONS = ("spin", "reroll")
COMMAND_ID_MIN_LENGTH = 1
COMMAND_ID_MAX_LENGTH = 128
COMMAND_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
COMMAND_KEYS = (
    "schema",
    "version",
    "command_id",
    "action",
)
FORBIDDEN_COMMAND_KEYS = (
    "api_key",
    "authorization",
    "candidate",
    "candidate_id",
    "filters",
    "landing_offset",
    "password",
    "pool",
    "snapshot",
    "token",
    "winner",
    "winner_id",
)

VALID_COMMAND_DOCUMENTS = (
    {
        "schema": COMMAND_SCHEMA,
        "version": COMMAND_VERSION,
        "command_id": "streamerbot:wheel:0001",
        "action": "spin",
    },
    {
        "schema": COMMAND_SCHEMA,
        "version": COMMAND_VERSION,
        "command_id": "0fcb65f2-2298-4f84-b23a-46f2f9020b7a",
        "action": "reroll",
    },
)

INVALID_COMMAND_DOCUMENTS = (
    None,
    [],
    "spin",
    {},
    {
        "version": COMMAND_VERSION,
        "command_id": "command-1",
        "action": "spin",
    },
    {
        "schema": COMMAND_SCHEMA,
        "command_id": "command-1",
        "action": "spin",
    },
    {
        "schema": COMMAND_SCHEMA,
        "version": COMMAND_VERSION,
        "action": "spin",
    },
    {
        "schema": COMMAND_SCHEMA,
        "version": COMMAND_VERSION,
        "command_id": "command-1",
    },
    {
        "schema": "other-wheel-command",
        "version": COMMAND_VERSION,
        "command_id": "command-1",
        "action": "spin",
    },
    {
        "schema": COMMAND_SCHEMA,
        "version": 2,
        "command_id": "command-1",
        "action": "spin",
    },
    {
        "schema": COMMAND_SCHEMA,
        "version": True,
        "command_id": "command-1",
        "action": "spin",
    },
    {
        "schema": COMMAND_SCHEMA,
        "version": COMMAND_VERSION,
        "command_id": "",
        "action": "spin",
    },
    {
        "schema": COMMAND_SCHEMA,
        "version": COMMAND_VERSION,
        "command_id": " " * 4,
        "action": "spin",
    },
    {
        "schema": COMMAND_SCHEMA,
        "version": COMMAND_VERSION,
        "command_id": "x" * (COMMAND_ID_MAX_LENGTH + 1),
        "action": "spin",
    },
    {
        "schema": COMMAND_SCHEMA,
        "version": COMMAND_VERSION,
        "command_id": "command with spaces",
        "action": "spin",
    },
    {
        "schema": COMMAND_SCHEMA,
        "version": COMMAND_VERSION,
        "command_id": "command/with/slashes",
        "action": "spin",
    },
    {
        "schema": COMMAND_SCHEMA,
        "version": COMMAND_VERSION,
        "command_id": "command-1",
        "action": "SPIN",
    },
    {
        "schema": COMMAND_SCHEMA,
        "version": COMMAND_VERSION,
        "command_id": "command-1",
        "action": "clear",
    },
    {
        "schema": COMMAND_SCHEMA,
        "version": COMMAND_VERSION,
        "command_id": "command-1",
        "action": "spin",
        "winner_id": "hack-1",
    },
    {
        "schema": COMMAND_SCHEMA,
        "version": COMMAND_VERSION,
        "command_id": "command-1",
        "action": "spin",
        "token": "secret",
    },
)


class WheelExternalCommandContractMixin:
    """Reusable behavior suite for the production command implementation."""

    def parse_command(self, document):
        raise NotImplementedError

    def command_to_document(self, command):
        raise NotImplementedError

    def serialize_command(self, command):
        raise NotImplementedError

    def assert_contract_error(self, document):
        raise NotImplementedError

    def test_valid_spin_command_is_parsed_exactly(self):
        document = deepcopy(VALID_COMMAND_DOCUMENTS[0])

        command = self.parse_command(document)

        self.assertEqual(command.schema, COMMAND_SCHEMA)
        self.assertEqual(command.version, COMMAND_VERSION)
        self.assertEqual(command.command_id, "streamerbot:wheel:0001")
        self.assertEqual(command.action, "spin")
        self.assertEqual(
            self.command_to_document(command),
            VALID_COMMAND_DOCUMENTS[0],
        )

    def test_valid_reroll_command_is_parsed_exactly(self):
        document = deepcopy(VALID_COMMAND_DOCUMENTS[1])

        command = self.parse_command(document)

        self.assertEqual(command.action, "reroll")
        self.assertEqual(
            self.command_to_document(command),
            VALID_COMMAND_DOCUMENTS[1],
        )

    def test_input_and_returned_documents_are_detached(self):
        document = deepcopy(VALID_COMMAND_DOCUMENTS[0])
        command = self.parse_command(document)

        document["action"] = "reroll"
        projected = self.command_to_document(command)
        projected["action"] = "reroll"

        self.assertEqual(command.action, "spin")
        self.assertEqual(
            self.command_to_document(command)["action"],
            "spin",
        )

    def test_parsed_command_is_immutable(self):
        command = self.parse_command(VALID_COMMAND_DOCUMENTS[0])

        with self.assertRaises((AttributeError, TypeError)):
            command.action = "reroll"

    def test_serialization_is_stable_compact_json(self):
        command = self.parse_command(VALID_COMMAND_DOCUMENTS[0])

        serialized = self.serialize_command(command)

        self.assertEqual(
            serialized,
            (
                '{"schema":"smwc-wheel-command","version":1,'
                '"command_id":"streamerbot:wheel:0001",'
                '"action":"spin"}'
            ),
        )
        self.assertEqual(
            json.loads(serialized),
            VALID_COMMAND_DOCUMENTS[0],
        )

    def test_invalid_documents_are_rejected(self):
        for document in INVALID_COMMAND_DOCUMENTS:
            with self.subTest(document=document):
                self.assert_contract_error(deepcopy(document))

    def test_every_forbidden_authority_field_is_rejected(self):
        base = deepcopy(VALID_COMMAND_DOCUMENTS[0])
        for key in FORBIDDEN_COMMAND_KEYS:
            document = deepcopy(base)
            document[key] = "not-allowed"
            with self.subTest(key=key):
                self.assert_contract_error(document)

    def test_command_contract_contains_no_selection_authority(self):
        command = self.parse_command(VALID_COMMAND_DOCUMENTS[0])
        projected = self.command_to_document(command)

        self.assertEqual(tuple(projected), COMMAND_KEYS)
        self.assertTrue(
            set(projected).isdisjoint(FORBIDDEN_COMMAND_KEYS)
        )


class WheelExternalCommandContractSpecificationTest(
    unittest.TestCase
):
    """Validate the reusable contract vectors before implementation."""

    def test_schema_version_and_actions_are_fixed(self):
        self.assertEqual(COMMAND_SCHEMA, "smwc-wheel-command")
        self.assertEqual(COMMAND_VERSION, 1)
        self.assertEqual(COMMAND_ACTIONS, ("spin", "reroll"))

    def test_command_document_has_exact_minimal_keys(self):
        self.assertEqual(
            COMMAND_KEYS,
            ("schema", "version", "command_id", "action"),
        )
        self.assertTrue(
            set(COMMAND_KEYS).isdisjoint(FORBIDDEN_COMMAND_KEYS)
        )

    def test_command_id_format_supports_opaque_idempotency_keys(self):
        valid_ids = (
            "1",
            "command-0001",
            "streamerbot:wheel:0001",
            "0fcb65f2-2298-4f84-b23a-46f2f9020b7a",
            "client.instance_1:sequence-42",
        )
        for command_id in valid_ids:
            with self.subTest(command_id=command_id):
                self.assertIsNotNone(
                    COMMAND_ID_PATTERN.fullmatch(command_id)
                )

        self.assertEqual(COMMAND_ID_MIN_LENGTH, 1)
        self.assertEqual(COMMAND_ID_MAX_LENGTH, 128)

    def test_command_id_format_rejects_ambiguous_transport_text(self):
        invalid_ids = (
            "",
            "contains spaces",
            "contains/slashes",
            "contains\\backslashes",
            "contains?query",
            "contains#fragment",
            "line\nbreak",
            "tab\tcharacter",
            "x" * 129,
        )
        for command_id in invalid_ids:
            with self.subTest(command_id=command_id):
                self.assertIsNone(
                    COMMAND_ID_PATTERN.fullmatch(command_id)
                )

    def test_valid_vectors_cover_both_supported_actions(self):
        self.assertEqual(
            {
                document["action"]
                for document in VALID_COMMAND_DOCUMENTS
            },
            set(COMMAND_ACTIONS),
        )
        for document in VALID_COMMAND_DOCUMENTS:
            self.assertEqual(tuple(document), COMMAND_KEYS)
            self.assertIsNotNone(
                COMMAND_ID_PATTERN.fullmatch(
                    document["command_id"]
                )
            )

    def test_invalid_vectors_cover_version_action_and_authority(self):
        serialized = json.dumps(
            INVALID_COMMAND_DOCUMENTS,
            sort_keys=True,
        )

        for required in (
            '"version": 2',
            '"version": true',
            '"action": "SPIN"',
            '"action": "clear"',
            '"winner_id": "hack-1"',
            '"token": "secret"',
        ):
            self.assertIn(required, serialized)

    def test_contract_mixin_exposes_required_implementation_tests(self):
        names = {
            name
            for name in dir(WheelExternalCommandContractMixin)
            if name.startswith("test_")
        }

        self.assertEqual(
            names,
            {
                "test_command_contract_contains_no_selection_authority",
                "test_every_forbidden_authority_field_is_rejected",
                "test_input_and_returned_documents_are_detached",
                "test_invalid_documents_are_rejected",
                "test_parsed_command_is_immutable",
                "test_serialization_is_stable_compact_json",
                "test_valid_reroll_command_is_parsed_exactly",
                "test_valid_spin_command_is_parsed_exactly",
            },
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
