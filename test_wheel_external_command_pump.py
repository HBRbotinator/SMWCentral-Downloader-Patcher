"""Tests for desktop-thread external Wheel command dispatch."""

from __future__ import annotations

import threading
import unittest

from wheel_external_command import parse_wheel_external_command
from wheel_external_command_pump import (
    WheelExternalCommandPump,
    WheelExternalCommandPumpError,
)
from wheel_external_command_queue import WheelExternalCommandQueue


def command(command_id: str, action: str = "spin"):
    return parse_wheel_external_command(
        {
            "schema": "smwc-wheel-command",
            "version": 1,
            "command_id": command_id,
            "action": action,
        }
    )


class FakeScheduler:
    def __init__(self):
        self.calls = []
        self.cancelled = []
        self._next_id = 1

    def schedule(self, delay_ms, callback):
        scheduled_id = f"after-{self._next_id}"
        self._next_id += 1
        self.calls.append((scheduled_id, delay_ms, callback))
        return scheduled_id

    def cancel(self, scheduled_id):
        self.cancelled.append(scheduled_id)

    def run_latest(self):
        _scheduled_id, _delay_ms, callback = self.calls[-1]
        return callback()


class WheelExternalCommandPumpTest(unittest.TestCase):
    def build_pump(
        self,
        *,
        queue=None,
        scheduler=None,
        dispatched=None,
        busy=None,
        errors=None,
        poll_interval_ms=100,
    ):
        queue = queue or WheelExternalCommandQueue()
        scheduler = scheduler or FakeScheduler()
        dispatched = dispatched if dispatched is not None else []
        errors = errors if errors is not None else []
        busy = busy or (lambda: False)
        pump = WheelExternalCommandPump(
            command_queue=queue,
            schedule=scheduler.schedule,
            cancel=scheduler.cancel,
            dispatch=dispatched.append,
            busy=busy,
            on_error=lambda item, error: errors.append(
                (item, error)
            ),
            poll_interval_ms=poll_interval_ms,
        )
        return pump, queue, scheduler, dispatched, errors

    def test_configuration_is_strict(self):
        queue = WheelExternalCommandQueue()
        scheduler = FakeScheduler()

        for value in (0, -1, True, 1.5):
            with self.subTest(poll_interval_ms=value):
                with self.assertRaises(
                    WheelExternalCommandPumpError
                ):
                    WheelExternalCommandPump(
                        command_queue=queue,
                        schedule=scheduler.schedule,
                        cancel=scheduler.cancel,
                        dispatch=lambda _command: None,
                        busy=lambda: False,
                        poll_interval_ms=value,
                    )

        with self.assertRaises(TypeError):
            WheelExternalCommandPump(
                command_queue=object(),
                schedule=scheduler.schedule,
                cancel=scheduler.cancel,
                dispatch=lambda _command: None,
                busy=lambda: False,
            )

    def test_start_only_schedules_and_is_idempotent(self):
        pump, queue, scheduler, dispatched, _errors = (
            self.build_pump()
        )
        queue.submit(command("queued"))

        self.assertTrue(pump.start())
        self.assertFalse(pump.start())

        self.assertEqual(dispatched, [])
        self.assertEqual(queue.pending_count, 1)
        self.assertEqual(len(scheduler.calls), 1)
        self.assertEqual(scheduler.calls[0][1], 100)

    def test_scheduled_poll_dispatches_on_callback_thread(self):
        scheduler = FakeScheduler()
        queue = WheelExternalCommandQueue()
        callback_thread_ids = []
        queue.submit(command("thread-check"))
        pump = WheelExternalCommandPump(
            command_queue=queue,
            schedule=scheduler.schedule,
            cancel=scheduler.cancel,
            dispatch=lambda _command: callback_thread_ids.append(
                threading.get_ident()
            ),
            busy=lambda: False,
        )
        submit_thread_id = threading.get_ident()
        pump.start()

        worker = threading.Thread(target=scheduler.run_latest)
        worker.start()
        worker.join()

        self.assertEqual(len(callback_thread_ids), 1)
        self.assertNotEqual(callback_thread_ids[0], submit_thread_id)
        self.assertEqual(queue.pending_count, 0)

    def test_busy_state_defers_command_without_dequeueing(self):
        state = {"busy": True}
        pump, queue, scheduler, dispatched, _errors = (
            self.build_pump(busy=lambda: state["busy"])
        )
        queue.submit(command("deferred"))
        pump.start()

        self.assertIsNone(scheduler.run_latest())
        self.assertEqual(queue.pending_count, 1)
        self.assertEqual(dispatched, [])

        state["busy"] = False
        dispatched_command = scheduler.run_latest()

        self.assertEqual(dispatched_command.command_id, "deferred")
        self.assertEqual(queue.pending_count, 0)
        self.assertEqual(
            [item.command_id for item in dispatched],
            ["deferred"],
        )

    def test_each_poll_dispatches_at_most_one_fifo_command(self):
        pump, queue, scheduler, dispatched, _errors = (
            self.build_pump()
        )
        queue.submit(command("first"))
        queue.submit(command("second", "reroll"))
        pump.start()

        first = scheduler.run_latest()

        self.assertEqual(first.command_id, "first")
        self.assertEqual(queue.pending_count, 1)
        self.assertEqual(
            [item.command_id for item in dispatched],
            ["first"],
        )

        second = scheduler.run_latest()

        self.assertEqual(second.command_id, "second")
        self.assertEqual(queue.pending_count, 0)
        self.assertEqual(
            [item.command_id for item in dispatched],
            ["first", "second"],
        )

    def test_dispatch_error_is_reported_and_does_not_stop_polling(self):
        queue = WheelExternalCommandQueue()
        scheduler = FakeScheduler()
        errors = []

        def fail(_command):
            raise RuntimeError("desktop dispatch failed")

        pump = WheelExternalCommandPump(
            command_queue=queue,
            schedule=scheduler.schedule,
            cancel=scheduler.cancel,
            dispatch=fail,
            busy=lambda: False,
            on_error=lambda item, error: errors.append(
                (item.command_id, str(error))
            ),
        )
        queue.submit(command("failing"))
        pump.start()

        dispatched = scheduler.run_latest()

        self.assertEqual(dispatched.command_id, "failing")
        self.assertEqual(
            errors,
            [("failing", "desktop dispatch failed")],
        )
        self.assertTrue(pump.running)
        self.assertEqual(len(scheduler.calls), 2)

    def test_stop_cancels_callback_and_prevents_dispatch(self):
        pump, queue, scheduler, dispatched, _errors = (
            self.build_pump()
        )
        queue.submit(command("still-pending"))
        pump.start()
        scheduled_id = scheduler.calls[-1][0]

        self.assertTrue(pump.stop())
        self.assertFalse(pump.stop())
        result = scheduler.run_latest()

        self.assertIsNone(result)
        self.assertEqual(scheduler.cancelled, [scheduled_id])
        self.assertEqual(queue.pending_count, 1)
        self.assertEqual(dispatched, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
