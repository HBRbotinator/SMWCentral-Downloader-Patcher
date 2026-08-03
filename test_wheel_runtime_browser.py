"""Contracts for the self-contained Wheel browser preview."""

from __future__ import annotations

import unittest

from wheel_runtime_browser import (
    WHEEL_RUNTIME_BROWSER_PATH,
    WHEEL_RUNTIME_BROWSER_SCRIPT_PATH,
    WHEEL_RUNTIME_BROWSER_STYLE_PATH,
    get_wheel_runtime_browser_asset,
)


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

    def test_html_uses_only_local_external_assets(self):
        html = get_wheel_runtime_browser_asset(
            WHEEL_RUNTIME_BROWSER_PATH
        ).payload.decode("utf-8")

        self.assertIn('href="./style.css"', html)
        self.assertIn('src="./app.js"', html)
        self.assertNotIn("<style", html)
        self.assertNotIn("<script>", html)
        self.assertNotIn("http://", html)
        self.assertNotIn("https://", html)
        self.assertIn('id="wheel-segments"', html)
        self.assertIn('aria-live="polite"', html)

    def test_javascript_reads_only_versioned_runtime_routes(self):
        script = get_wheel_runtime_browser_asset(
            WHEEL_RUNTIME_BROWSER_SCRIPT_PATH
        ).payload.decode("utf-8")

        self.assertIn('const HEALTH_PATH = "/api/v1/health"', script)
        self.assertIn(
            'const SNAPSHOT_PATH = "/api/v1/snapshot"',
            script,
        )
        self.assertIn("fetch(path", script)
        self.assertNotIn('method: "POST"', script)
        self.assertNotIn("WebSocket", script)
        self.assertNotIn("EventSource", script)
        self.assertNotIn("localStorage", script)
        self.assertNotIn("sessionStorage", script)
        self.assertNotIn("innerHTML", script)
        self.assertIn("createElementNS", script)
        self.assertIn("setInterval", script)

    def test_preview_represents_all_candidates_and_limits_only_labels(self):
        script = get_wheel_runtime_browser_asset(
            WHEEL_RUNTIME_BROWSER_SCRIPT_PATH
        ).payload.decode("utf-8")

        self.assertIn("safeCandidates.forEach", script)
        self.assertIn("count <= MAX_VISIBLE_LABELS", script)
        self.assertIn("shape.dataset.candidateId", script)
        self.assertIn("countElement.textContent", script)

    def test_css_is_obs_friendly_and_responsive(self):
        css = get_wheel_runtime_browser_asset(
            WHEEL_RUNTIME_BROWSER_STYLE_PATH
        ).payload.decode("utf-8")

        self.assertIn("background: transparent", css)
        self.assertIn("aspect-ratio: 1", css)
        self.assertIn("@media (max-width: 620px)", css)


if __name__ == "__main__":
    unittest.main(verbosity=2)
