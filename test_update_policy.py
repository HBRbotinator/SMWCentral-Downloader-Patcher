from __future__ import annotations

import contextlib
import io
import unittest
from pathlib import Path
from unittest import mock

import standalone_updater
import updater
from update_policy import (
    UpdatePolicyError,
    current_update_policy,
    evaluate_update_policy,
    require_in_place_updates_enabled,
    require_update_checks_enabled,
)


class UpdatePolicyTests(unittest.TestCase):
    def test_current_development_manifest_disables_updates(self):
        policy = current_update_policy()
        self.assertEqual(policy.release_channel, "development")
        self.assertFalse(policy.checks_enabled)
        self.assertFalse(policy.in_place_updates_enabled)
        self.assertIn("5.1.0-dev.1", policy.reason or "")

    def test_stable_and_release_channels_enable_updates(self):
        for channel in ("stable", "release", " RELEASE "):
            with self.subTest(channel=channel):
                policy = evaluate_update_policy(channel, "5.1.0")
                self.assertTrue(policy.checks_enabled)
                self.assertTrue(policy.in_place_updates_enabled)
                self.assertIsNone(policy.reason)

    def test_unknown_channel_fails_closed(self):
        policy = evaluate_update_policy("preview", "5.1.0-rc.1")
        self.assertFalse(policy.checks_enabled)
        self.assertFalse(policy.in_place_updates_enabled)
        self.assertIn("unrecognized", policy.reason or "")

    def test_policy_guards_raise_before_disabled_operations(self):
        policy = evaluate_update_policy("development", "5.1.0-dev.1")
        with self.assertRaises(UpdatePolicyError):
            require_update_checks_enabled(policy)
        with self.assertRaises(UpdatePolicyError) as raised:
            require_in_place_updates_enabled("download an update", policy)
        self.assertIn("download an update", str(raised.exception))

    def test_update_check_does_not_call_github_for_development_build(self):
        client = updater.Updater("5.1.0-dev.1")
        with mock.patch.object(updater.requests, "get") as request:
            self.assertIsNone(client.check_for_updates(silent=True))
        request.assert_not_called()

    def test_download_and_apply_paths_fail_before_side_effects(self):
        client = updater.Updater("5.1.0-dev.1")
        with self.assertRaises(UpdatePolicyError):
            client.download_update(
                {"download_url": "https://example.invalid/update.zip"}
            )
        with self.assertRaises(UpdatePolicyError):
            client.apply_update("missing.zip", {"version": "5.1.0"})
        with self.assertRaises(UpdatePolicyError):
            client.apply_update_silent("missing.zip", {"version": "5.1.0"})

    def test_background_check_does_not_start_a_thread(self):
        with mock.patch.object(updater, "Thread") as thread:
            result = updater.check_for_updates_background("5.1.0-dev.1")
        self.assertIsNone(result)
        thread.assert_not_called()

    def test_standalone_updater_refuses_development_build(self):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            self.assertEqual(standalone_updater.main(), 2)
        self.assertIn("disabled for development build", stderr.getvalue())

    def test_startup_and_settings_surface_the_same_policy(self):
        main_source = Path("main.py").read_text(encoding="utf-8")
        settings_source = Path("ui/pages/settings_page.py").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "if not current_update_policy().checks_enabled:", main_source
        )
        self.assertIn(
            "Updates Disabled for Development Builds", settings_source
        )
        self.assertIn(
            "if not self.update_policy.checks_enabled:", settings_source
        )


if __name__ == "__main__":
    unittest.main()
