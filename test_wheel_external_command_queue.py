"""Tests for the external Wheel command queue."""

from __future__ import annotations

import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError

from wheel_external_command import parse_wheel_external_command
from wheel_external_command_queue import (
    WHEEL_EXTERNAL_COMMAND_QUEUE_STATUSES,
    WheelExternalCommandQueue,
    WheelExternalCommandQueueError,
)


def command(command_id: str, action: str = "spin"):
    return parse_wheel_external_command(
        {
            "schema": "smwc-wheel-command",
            "version": 1,
            "command_id": command_id,
            "action": action,
        }
    )


class WheelExternalCommandQueueTest(unittest.TestCase):
    def test_defaults_and_status_vocabulary_are_fixed(self):
        queue = WheelExternalCommandQueue()

        self.assertEqual(queue.capacity, 32)
        self.assertEqual(queue.remembered_ids, 256)
        self.assertEqual(queue.pending_count, 0)
        self.assertFalse(queue.closed)
        self.assertEqual(
            WHEEL_EXTERNAL_COMMAND_QUEUE_STATUSES,
            ("accepted", "duplicate", "full", "closed"),
        )

    def test_configuration_is_strict_and_history_covers_capacity(self):
        invalid = (
            {"capacity": 0},
            {"capacity": -1},
            {"capacity": True},
            {"capacity": 1.5},
            {"remembered_ids": 0},
            {"remembered_ids": False},
            {"capacity": 4, "remembered_ids": 3},
        )
        for kwargs in invalid:
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(
                    WheelExternalCommandQueueError
                ):
                    WheelExternalCommandQueue(**kwargs)

    def test_submit_requires_production_command_type(self):
        queue = WheelExternalCommandQueue()
        with self.assertRaises(TypeError):
            queue.submit({"command_id": "raw"})

    def test_commands_are_fifo_and_submission_is_immutable(self):
        queue = WheelExternalCommandQueue(capacity=3)
        first = queue.submit(command("first", "spin"))
        second = queue.submit(command("second", "reroll"))

        self.assertTrue(first.accepted)
        self.assertEqual(first.pending_count, 1)
        self.assertEqual(second.pending_count, 2)
        with self.assertRaises(FrozenInstanceError):
            first.status = "duplicate"

        self.assertEqual(queue.take_next().command_id, "first")
        self.assertEqual(queue.take_next().command_id, "second")
        self.assertIsNone(queue.take_next())

    def test_snapshot_is_an_immutable_fifo_view(self):
        queue = WheelExternalCommandQueue(capacity=3)
        queue.submit(command("first"))
        queue.submit(command("second"))
        snapshot = queue.snapshot()

        self.assertIsInstance(snapshot, tuple)
        self.assertEqual(
            [item.command_id for item in snapshot],
            ["first", "second"],
        )
        queue.take_next()
        self.assertEqual(
            [item.command_id for item in snapshot],
            ["first", "second"],
        )

    def test_duplicate_is_not_enqueued_and_remains_known_after_take(self):
        queue = WheelExternalCommandQueue(capacity=2)
        original = command("same-command")

        accepted = queue.submit(original)
        duplicate_pending = queue.submit(original)
        taken = queue.take_next()
        duplicate_after = queue.submit(original)

        self.assertEqual(accepted.status, "accepted")
        self.assertEqual(duplicate_pending.status, "duplicate")
        self.assertEqual(duplicate_pending.pending_count, 1)
        self.assertEqual(taken, original)
        self.assertEqual(duplicate_after.status, "duplicate")
        self.assertEqual(duplicate_after.pending_count, 0)

    def test_full_queue_does_not_consume_rejected_command_id(self):
        queue = WheelExternalCommandQueue(
            capacity=1,
            remembered_ids=2,
        )
        queue.submit(command("first"))
        full = queue.submit(command("retry-me"))
        queue.take_next()
        retried = queue.submit(command("retry-me"))

        self.assertEqual(full.status, "full")
        self.assertEqual(retried.status, "accepted")

    def test_history_window_eventually_allows_expired_id(self):
        queue = WheelExternalCommandQueue(
            capacity=1,
            remembered_ids=2,
        )
        for command_id in ("old", "middle", "new"):
            queue.submit(command(command_id))
            queue.take_next()

        self.assertEqual(queue.submit(command("old")).status, "accepted")

    def test_close_is_repeatable_clears_pending_and_rejects_new(self):
        queue = WheelExternalCommandQueue(capacity=3)
        queue.submit(command("first"))
        queue.submit(command("second"))

        self.assertEqual(queue.close(), 2)
        self.assertEqual(queue.close(), 0)
        rejected = queue.submit(command("third"))

        self.assertTrue(queue.closed)
        self.assertEqual(queue.pending_count, 0)
        self.assertEqual(queue.snapshot(), ())
        self.assertIsNone(queue.take_next())
        self.assertEqual(rejected.status, "closed")

    def test_known_duplicate_remains_duplicate_after_close(self):
        queue = WheelExternalCommandQueue(capacity=2)
        original = command("known")
        queue.submit(original)
        queue.close()

        self.assertEqual(queue.submit(original).status, "duplicate")

    def test_concurrent_duplicate_submission_accepts_exactly_once(self):
        queue = WheelExternalCommandQueue(capacity=8)
        duplicate = command("shared-id")
        with ThreadPoolExecutor(max_workers=12) as executor:
            results = tuple(
                executor.map(
                    lambda _index: queue.submit(duplicate),
                    range(48),
                )
            )

        statuses = [result.status for result in results]
        self.assertEqual(statuses.count("accepted"), 1)
        self.assertEqual(statuses.count("duplicate"), 47)
        self.assertEqual(queue.pending_count, 1)

    def test_concurrent_unique_submission_is_lossless_with_capacity(self):
        queue = WheelExternalCommandQueue(
            capacity=64,
            remembered_ids=64,
        )
        commands = tuple(
            command(f"unique-{index:02d}")
            for index in range(40)
        )
        with ThreadPoolExecutor(max_workers=12) as executor:
            results = tuple(executor.map(queue.submit, commands))

        self.assertTrue(all(result.accepted for result in results))
        self.assertEqual(queue.pending_count, 40)
        self.assertEqual(
            {item.command_id for item in queue.snapshot()},
            {item.command_id for item in commands},
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
