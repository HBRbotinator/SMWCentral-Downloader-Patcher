"""Contracts for browser rendering and predetermined spin animation."""

from __future__ import annotations

import re
import unittest

from wheel_runtime_browser import (
    WHEEL_RUNTIME_BROWSER_PATH,
    WHEEL_RUNTIME_BROWSER_SCRIPT_PATH,
    WHEEL_RUNTIME_BROWSER_STYLE_PATH,
    get_wheel_runtime_browser_asset,
)


def asset_text(path):
    asset = get_wheel_runtime_browser_asset(path)
    if asset is None:
        raise AssertionError(f"Missing browser asset: {path}")
    return asset.payload.decode("utf-8")


class WheelRuntimeBrowserAssetTest(unittest.TestCase):
    def test_exact_browser_routes_return_embedded_assets(self):
        expected_types = {
            WHEEL_RUNTIME_BROWSER_PATH: "text/html; charset=utf-8",
            WHEEL_RUNTIME_BROWSER_STYLE_PATH: "text/css; charset=utf-8",
            WHEEL_RUNTIME_BROWSER_SCRIPT_PATH: (
                "text/javascript; charset=utf-8"
            ),
        }

        for path, content_type in expected_types.items():
            with self.subTest(path=path):
                asset = get_wheel_runtime_browser_asset(path)
                self.assertIsNotNone(asset)
                self.assertEqual(asset.content_type, content_type)
                self.assertGreater(len(asset.payload), 100)

    def test_unknown_or_near_match_routes_are_not_served(self):
        for path in (
            "/",
            "/wheel",
            "/wheel/index.html",
            "/wheel/app.js/",
            "/WHEEL/",
        ):
            with self.subTest(path=path):
                self.assertIsNone(
                    get_wheel_runtime_browser_asset(path)
                )

    def test_html_uses_local_assets_and_accessible_result_status(self):
        html = asset_text(WHEEL_RUNTIME_BROWSER_PATH)

        self.assertIn('href="./style.css"', html)
        self.assertIn('src="./app.js"', html)
        self.assertNotIn("<style", html)
        self.assertNotIn("<script>", html)
        self.assertNotIn("http://", html)
        self.assertNotIn("https://", html)
        self.assertIn('id="wheel-segments"', html)
        self.assertIn('id="spin-result"', html)
        self.assertIn('id="spin-winner"', html)
        self.assertIn('aria-live="polite"', html)

    def test_javascript_reads_all_runtime_state_with_get_only(self):
        script = asset_text(WHEEL_RUNTIME_BROWSER_SCRIPT_PATH)

        self.assertIn('const HEALTH_PATH = "/api/v1/health"', script)
        self.assertIn(
            'const SNAPSHOT_PATH = "/api/v1/snapshot"',
            script,
        )
        self.assertIn('const SPIN_PATH = "/api/v1/spin"', script)
        self.assertIn("fetch(path", script)
        self.assertNotIn('method: "POST"', script)
        self.assertNotIn('method: "PUT"', script)
        self.assertNotIn('method: "DELETE"', script)
        self.assertNotIn("WebSocket", script)
        self.assertNotIn("EventSource", script)

    def test_browser_contains_no_winner_selection_or_randomness(self):
        script = asset_text(WHEEL_RUNTIME_BROWSER_SCRIPT_PATH)

        for forbidden in (
            "Math.random",
            "crypto.getRandomValues",
            "randomChoice",
            "selectWinner",
            "chooseWinner",
            "winnerPool",
            ".sort(() =>",
        ):
            self.assertNotIn(forbidden, script)

        self.assertIn("spin.winner.index", script)
        self.assertIn("spin.winner?.id", script)
        self.assertIn("spin.winner.title", script)

    def test_spin_is_bound_to_exact_snapshot_and_candidate_index(self):
        script = asset_text(WHEEL_RUNTIME_BROWSER_SCRIPT_PATH)

        self.assertIn("spinMatchesSnapshot", script)
        self.assertIn(
            "spin.snapshot?.generated_at === snapshot.generated_at",
            script,
        )
        self.assertIn(
            "spin.snapshot?.candidate_count === candidates.length",
            script,
        )
        self.assertIn(
            'String(winner?.id || "") === String(spin.winner?.id || "")',
            script,
        )
        self.assertIn(
            "Waiting for the snapshot used by the latest spin.",
            script,
        )

    def test_observed_spin_is_animated_at_most_once_per_page(self):
        script = asset_text(WHEEL_RUNTIME_BROWSER_SCRIPT_PATH)

        self.assertIn("lastObservedSpinSequence", script)
        self.assertIn("lastObservedSpinId", script)
        self.assertIn("sequence <= lastObservedSpinSequence", script)
        self.assertIn("spinId === lastObservedSpinId", script)
        self.assertLess(
            script.index(
                "lastObservedSpinSequence = Number(spin.sequence)"
            ),
            script.index("animateSpin(spin, snapshot);"),
        )

    def test_landing_rotation_uses_python_animation_parameters(self):
        script = asset_text(WHEEL_RUNTIME_BROWSER_SCRIPT_PATH)

        self.assertIn("targetRotationForSpin", script)
        self.assertIn("spin.winner.index", script)
        self.assertIn("spin.animation.landing_offset", script)
        self.assertIn("spin.animation.turns", script)
        self.assertIn("spin.animation.duration_ms", script)
        self.assertIn("currentRotation", script)
        self.assertIn("requestAnimationFrame", script)
        self.assertIn("cubic-bezier", script)

    def test_rotation_formula_lands_requested_segment_under_pointer(self):
        script = asset_text(WHEEL_RUNTIME_BROWSER_SCRIPT_PATH)

        self.assertRegex(
            script,
            re.compile(
                r"const winnerAngle = \(.*?"
                r"Number\(spin\.winner\.index\).*?"
                r"Number\(spin\.animation\.landing_offset\).*?"
                r"\) \* angle;",
                re.DOTALL,
            ),
        )
        self.assertIn(
            "const targetModulo = (360 - winnerAngle) % 360",
            script,
        )
        self.assertIn(
            "Number(spin.animation.turns) * 360",
            script,
        )

    def test_snapshot_change_resets_visual_rotation_safely(self):
        script = asset_text(WHEEL_RUNTIME_BROWSER_SCRIPT_PATH)

        self.assertIn("function resetWheelRotation()", script)
        self.assertIn(
            'segmentsElement.style.transition = "none"',
            script,
        )
        self.assertIn(
            'segmentsElement.style.transform = "rotate(0deg)"',
            script,
        )
        self.assertIn("renderWheel(snapshot.candidates)", script)

    def test_refresh_loop_prevents_overlapping_requests(self):
        script = asset_text(WHEEL_RUNTIME_BROWSER_SCRIPT_PATH)

        self.assertIn("let refreshInProgress = false", script)
        self.assertIn("if (refreshInProgress)", script)
        self.assertIn("refreshInProgress = true", script)
        self.assertIn("refreshInProgress = false", script)
        self.assertIn(
            "window.setInterval(refreshRuntime, POLL_INTERVAL_MS)",
            script,
        )

    def test_preview_represents_all_candidates_and_limits_only_labels(self):
        script = asset_text(WHEEL_RUNTIME_BROWSER_SCRIPT_PATH)

        self.assertIn("safeCandidates.forEach", script)
        self.assertIn("count <= MAX_VISIBLE_LABELS", script)
        self.assertIn("shape.dataset.candidateId", script)
        self.assertIn("countElement.textContent", script)

    def test_browser_avoids_mutable_local_client_storage(self):
        script = asset_text(WHEEL_RUNTIME_BROWSER_SCRIPT_PATH)

        for forbidden in (
            "localStorage",
            "sessionStorage",
            "indexedDB",
            "document.cookie",
            "innerHTML",
        ):
            self.assertNotIn(forbidden, script)

    def test_css_supports_rotation_result_and_obs_transparency(self):
        css = asset_text(WHEEL_RUNTIME_BROWSER_STYLE_PATH)

        self.assertIn("background: transparent", css)
        self.assertIn("transform-origin: 400px 400px", css)
        self.assertIn("will-change: transform", css)
        self.assertIn(".spin-result", css)
        self.assertIn(".spin-result[hidden]", css)
        self.assertIn("aspect-ratio: 1", css)
        self.assertIn("@media (max-width: 620px)", css)


if __name__ == "__main__":
    unittest.main(verbosity=2)
