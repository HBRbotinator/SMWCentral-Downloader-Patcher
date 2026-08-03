"""Detailed documentation contract for the Browser / OBS Wheel."""

from __future__ import annotations

import unittest
from pathlib import Path


class WheelRuntimeDocumentationTest(unittest.TestCase):
    def setUp(self):
        self.path = Path("docs/WHEEL_BROWSER_RUNTIME.md")
        self.text = self.path.read_text(encoding="utf-8")
        self.normalized = " ".join(self.text.split())

    def test_documents_obs_setup_and_managed_lifecycle(self):
        for required in (
            "Start the managed runtime",
            "Collection → Open Wheel",
            "Start Browser Wheel",
            "Configure OBS",
            "Add a **Browser** source",
            "Copy OBS URL",
            "Keep the application and Collection Wheel dialog open",
            "Runtime lifecycle",
            "Closing the Collection Wheel dialog",
        ):
            self.assertIn(required, self.normalized)

    def test_documents_exact_pool_and_predetermined_winner_flow(self):
        for required in (
            "exact active pool",
            "does not expose the complete Collection",
            "exact current eligible pool",
            "exact reroll pool",
            "native Collection Wheel model selects the winner",
            "Python publishes a versioned spin instruction",
            "same result",
            "does not reroll, replace, or invalidate the native result",
        ):
            self.assertIn(required, self.normalized)

    def test_documents_spin_validation_contract(self):
        for required in (
            "Predetermined spin validation",
            "monotonic sequence",
            "opaque spin ID",
            "snapshot generation time",
            "source revision",
            "candidate count",
            "winner ID",
            "winner index",
            "animation duration",
            "landing offset",
            "browser contains no random source",
        ):
            self.assertIn(required, self.normalized)

    def test_documents_read_only_routes(self):
        for route in (
            "/api/v1/health",
            "/api/v1/snapshot",
            "/api/v1/spin",
            "/wheel/",
            "/wheel/style.css",
            "/wheel/app.js",
        ):
            self.assertIn(route, self.text)

        for required in (
            "GET / HEAD",
            "Mutating methods are rejected",
            "no browser or HTTP command that starts a spin",
        ):
            self.assertIn(required, self.normalized)

    def test_documents_security_and_privacy_boundaries(self):
        for required in (
            "127.0.0.1",
            "localhost",
            "not exposed to the LAN",
            "Content Security Policy",
            "embedded local assets",
            "versioned, validated JSON",
            "local ROM paths",
            "save paths",
            "download URLs",
            "Personal Rating",
            "Loopback-only and read-only behavior",
        ):
            self.assertIn(required, self.normalized)

    def test_documents_troubleshooting_and_current_limitations(self):
        for required in (
            "Troubleshooting",
            "runtime does not start",
            "OBS shows a connection error",
            "waiting for a snapshot",
            "spin does not animate",
            "Current limitations and future boundary",
            "standalone or tray-hosted process",
            "Streamer.bot control",
            "authenticated command API",
            "LAN or remote access",
            "persistent spin history",
        ):
            self.assertIn(required, self.normalized)

    def test_does_not_claim_unimplemented_advanced_controls(self):
        for unsupported_claim in (
            "Streamer.bot can trigger",
            "works while the main application is closed",
            "available over your LAN",
            "POST /api/v1/spin",
            "WebSocket command endpoint",
        ):
            self.assertNotIn(unsupported_claim, self.text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
