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
            "/wheel/?mode=overlay",
            "base `/wheel/` URL remains a full preview",
            "fully hidden while idle",
            "eight seconds",
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

    def test_documents_final_overlay_presentation(self):
        for required in (
            "Browser animation and result presentation",
            "10.5 seconds total duration",
            "nine full turns",
            "continuous `requestAnimationFrame`-driven motion curve",
            "high-speed middle through 27%",
            "continuous deceleration over the final 73%",
            "tapering smoothly to zero",
            "nine weighted bands",
            "Hairline early",
            "`0.025–0.055`",
            "Hairline late",
            "`0.945–0.975`",
            "each receive 47% total probability",
            "Center",
            "6%",
            "flips it by 180 degrees",
            "complete title",
            "responsive size tiers",
            "`WINNER!`",
            "eight seconds",
            "celebration rings",
            "spark rays",
            "immutable Python-authored spin ID",
            "no browser entropy source",
        ):
            self.assertIn(required, self.normalized)

    def test_rejects_superseded_presentation_numbers(self):
        for stale in (
            "five seconds",
            "nine seconds total duration",
            "eight full turns",
            "18% segment margin",
            "browser contains no random source",
        ):
            self.assertNotIn(stale, self.normalized)

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
            "no entropy source",
            "Presentation variation is deterministically derived",
        ):
            self.assertIn(required, self.normalized)

    def test_documents_read_only_routes(self):
        for route in (
            "/api/v1/health",
            "/api/v1/snapshot",
            "/api/v1/spin",
            "/wheel/",
            "/wheel/?mode=overlay",
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
            "overlay appears empty between spins",
            "intended OBS behavior",
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
