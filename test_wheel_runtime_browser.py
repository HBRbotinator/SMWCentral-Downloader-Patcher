"""Contracts for browser preview and idle-hidden OBS overlay modes."""

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

        self.assertIn('id="runtime-root"', html)
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

    def test_query_parameter_selects_overlay_or_preview_mode(self):
        script = asset_text(WHEEL_RUNTIME_BROWSER_SCRIPT_PATH)

        self.assertIn("new URLSearchParams(window.location.search)", script)
        self.assertIn('.get("mode") === "overlay"', script)
        self.assertIn('? "overlay"', script)
        self.assertIn(': "preview"', script)
        self.assertIn(
            "document.body.dataset.mode = DISPLAY_MODE",
            script,
        )

    def test_overlay_stays_hidden_until_a_spin_is_animated(self):
        script = asset_text(WHEEL_RUNTIME_BROWSER_SCRIPT_PATH)

        self.assertIn("function showOverlay()", script)
        self.assertIn("function hideOverlay()", script)
        self.assertIn(
            'document.body.classList.add("overlay-active")',
            script,
        )
        self.assertIn(
            'document.body.classList.remove("overlay-active")',
            script,
        )
        self.assertLess(
            script.index("showOverlay();"),
            script.index('setStatus("Spinning…", "ready")'),
        )
        self.assertIn("renderEmptyWheel();\nhideOverlay();", script)

    def test_overlay_holds_result_then_returns_to_hidden_idle(self):
        script = asset_text(WHEEL_RUNTIME_BROWSER_SCRIPT_PATH)

        self.assertIn("const OVERLAY_RESULT_HOLD_MS = 8000", script)
        self.assertIn("function scheduleOverlayHide()", script)
        self.assertIn(
            "overlayHideTimer = window.setTimeout(",
            script,
        )
        self.assertIn(
            "OVERLAY_RESULT_HOLD_MS",
            script,
        )
        self.assertLess(
            script.index("showResult(spin.winner.title, spin.winner.id);"),
            script.index("scheduleOverlayHide();"),
        )

    def test_overlay_css_removes_preview_chrome_and_background(self):
        css = asset_text(WHEEL_RUNTIME_BROWSER_STYLE_PATH)

        self.assertIn('body[data-mode="overlay"] .runtime__header', css)
        self.assertIn('body[data-mode="overlay"] .runtime__footer', css)
        self.assertIn("display: none", css)
        self.assertIn('body[data-mode="overlay"] .runtime {', css)
        self.assertIn("background: transparent", css)
        self.assertIn("box-shadow: none", css)
        self.assertIn(
            'body[data-mode="overlay"]:not(.overlay-active) .runtime',
            css,
        )
        self.assertIn("visibility: hidden", css)
        self.assertIn("opacity: 0", css)

    def test_preview_mode_retains_full_runtime_chrome(self):
        css = asset_text(WHEEL_RUNTIME_BROWSER_STYLE_PATH)
        html = asset_text(WHEEL_RUNTIME_BROWSER_PATH)

        self.assertIn('class="runtime__header"', html)
        self.assertIn('class="runtime__footer"', html)
        self.assertIn("Wheel Runtime", html)
        self.assertIn("Read-only preview", html)
        self.assertNotIn(
            'body[data-mode="preview"] .runtime__header',
            css,
        )

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
        self.assertIn("naturalSpinProgress", script)

    def test_spin_uses_one_continuous_frame_driven_curve(self):
        script = asset_text(WHEEL_RUNTIME_BROWSER_SCRIPT_PATH)

        for required in (
            "function smoothStep(value)",
            "function smoothStepIntegral(value)",
            "function naturalSpinProgress(elapsedShare)",
            "function animateSpinFrame(",
            "function finishSpin(generation, plan, spin)",
            "SPIN_ACCELERATION_END = 0.12",
            "SPIN_DECELERATION_START = 0.22",
            "currentRotation = plan.start + plan.distance * progress",
        ):
            self.assertIn(required, script)

        animation = script.split(
            "function animateSpin(spin, snapshot) {",
            1,
        )[1].split(
            "function spinWasAlreadyObserved",
            1,
        )[0]
        self.assertNotIn("setTimeout", animation)
        self.assertNotIn("applySpinPhase", animation)
        self.assertIn("requestAnimationFrame", animation)

    def test_velocity_curve_tapers_continuously_to_zero(self):
        script = asset_text(WHEEL_RUNTIME_BROWSER_SCRIPT_PATH)

        progress = script.split(
            "function naturalSpinProgress(elapsedShare) {",
            1,
        )[1].split(
            "function buildSpinMotionPlan",
            1,
        )[0]
        for required in (
            "smoothStepIntegral(local)",
            "accelerationDuration * 0.5",
            "decelerationDuration * 0.5",
            "local - smoothStepIntegral(local)",
            "return traveledArea / totalVelocityArea",
        ):
            self.assertIn(required, progress)

    def test_long_deceleration_begins_early_in_total_duration(self):
        script = asset_text(WHEEL_RUNTIME_BROWSER_SCRIPT_PATH)

        self.assertIn("SPIN_DECELERATION_START = 0.22", script)
        self.assertNotIn("SPIN_LAUNCH_EASING", script)
        self.assertNotIn("SPIN_CRUISE_EASING", script)
        self.assertNotIn("SPIN_ANTICIPATION_EASING", script)
        self.assertNotIn("const cruiseTarget =", script)

    def test_label_orientation_updates_on_each_animation_frame(self):
        script = asset_text(WHEEL_RUNTIME_BROWSER_SCRIPT_PATH)

        frame = script.split(
            "function animateSpinFrame(",
            1,
        )[1].split(
            "function animateSpin(",
            1,
        )[0]
        self.assertIn(
            "updateWheelLabelOrientation(currentRotation)",
            frame,
        )
        self.assertIn(
            "segmentsElement.style.transform",
            frame,
        )

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

    def test_labels_use_radial_angles_and_flip_when_inverted(self):
        script = asset_text(WHEEL_RUNTIME_BROWSER_SCRIPT_PATH)

        for required in (
            "function signedDegrees(angle)",
            "function labelFlipForRotation(baseAngle, wheelRotation)",
            "function updateWheelLabelOrientation(wheelRotation)",
            'segmentsElement.querySelectorAll(".wheel__label")',
            "screenAngle > 90 || screenAngle < -90 ? 180 : 0",
            "label.dataset.baseAngle = String(midpoint)",
            "label.dataset.labelX = position.x.toFixed(3)",
            "label.dataset.labelY = position.y.toFixed(3)",
            "`rotate(${baseAngle + flip} ${x} ${y})`",
        ):
            self.assertIn(required, script)

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
        self.assertIn("hideOverlay();", script)

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

    def test_result_title_is_never_ellipsized_or_single_line(self):
        css = asset_text(WHEEL_RUNTIME_BROWSER_STYLE_PATH)

        result_css = css.split(
            ".spin-result strong {",
            1,
        )[1].split("}", 1)[0]
        self.assertIn("overflow-wrap: anywhere", result_css)
        self.assertIn("text-wrap: balance", result_css)
        self.assertIn("white-space: normal", result_css)
        self.assertNotIn("text-overflow: ellipsis", result_css)
        self.assertNotIn("white-space: nowrap", result_css)

    def test_result_title_uses_length_aware_responsive_sizes(self):
        script = asset_text(WHEEL_RUNTIME_BROWSER_SCRIPT_PATH)
        css = asset_text(WHEEL_RUNTIME_BROWSER_STYLE_PATH)

        for required in (
            "function resultTitleSize(title)",
            'return "extra-long"',
            'return "long"',
            'return "medium"',
            'return "short"',
            "resultElement.dataset.titleSize = resultTitleSize(fullTitle)",
        ):
            self.assertIn(required, script)

        for selector in (
            '.spin-result[data-title-size="medium"] strong',
            '.spin-result[data-title-size="long"] strong',
            '.spin-result[data-title-size="extra-long"] strong',
        ):
            self.assertIn(selector, css)

    def test_show_result_preserves_complete_title_text(self):
        script = asset_text(WHEEL_RUNTIME_BROWSER_SCRIPT_PATH)

        show_method = script.split(
            "function showResult(title, candidateId) {",
            1,
        )[1].split(
            "function resetWheelRotation()",
            1,
        )[0]
        self.assertIn(
            'const fullTitle = String(title || "").trim()',
            show_method,
        )
        self.assertIn(
            "winnerElement.textContent = fullTitle",
            show_method,
        )
        self.assertNotIn("truncate(", show_method)
        self.assertNotIn("slice(", show_method)

    def test_result_card_and_winning_segment_receive_celebration(self):
        script = asset_text(WHEEL_RUNTIME_BROWSER_SCRIPT_PATH)
        css = asset_text(WHEEL_RUNTIME_BROWSER_STYLE_PATH)

        for required in (
            "function clearWinnerHighlight()",
            "function highlightWinner(candidateId)",
            "wheel__segment--winner",
            "wheel__label--winner",
            'resultElement.classList.add("spin-result--visible")',
            "highlightWinner(candidateId)",
            "showResult(spin.winner.title, spin.winner.id)",
        ):
            self.assertIn(required, script)

        for required in (
            ".spin-result--visible",
            "@keyframes winner-card-reveal",
            "@keyframes winner-title-reveal",
            "@keyframes winner-segment-pulse",
            ".wheel__segment--winner",
            ".wheel__label--winner",
        ):
            self.assertIn(required, css)

    def test_hiding_result_clears_all_celebration_state(self):
        script = asset_text(WHEEL_RUNTIME_BROWSER_SCRIPT_PATH)

        hide_method = script.split(
            "function hideResult() {",
            1,
        )[1].split(
            "function showResult(",
            1,
        )[0]
        self.assertIn(
            'resultElement.classList.remove("spin-result--visible")',
            hide_method,
        )
        self.assertIn(
            'resultElement.removeAttribute("data-title-size")',
            hide_method,
        )
        self.assertIn("clearWinnerHighlight()", hide_method)

    def test_winner_reveal_uses_rings_sparks_and_overlay_label(self):
        html = asset_text(WHEEL_RUNTIME_BROWSER_PATH)
        css = asset_text(WHEEL_RUNTIME_BROWSER_STYLE_PATH)
        script = asset_text(WHEEL_RUNTIME_BROWSER_SCRIPT_PATH)

        self.assertIn('id="winner-burst"', html)
        self.assertIn('id="spin-result-label"', html)

        for required in (
            ".wheel-stage--winner::before",
            ".wheel-stage--winner::after",
            ".winner-burst__spark",
            "@keyframes winner-ring-burst",
            "@keyframes winner-spark-burst",
        ):
            self.assertIn(required, css)

        for required in (
            "const WINNER_SPARK_COUNT = 20",
            "function prepareWinnerBurst()",
            "function showWinnerCelebration()",
            'isOverlayMode() ? "WINNER!" : "Selected"',
            "showWinnerCelebration()",
            "prepareWinnerBurst();",
        ):
            self.assertIn(required, script)

    def test_sparks_are_deterministic_and_not_browser_random(self):
        script = asset_text(WHEEL_RUNTIME_BROWSER_SCRIPT_PATH)

        prepare = script.split(
            "function prepareWinnerBurst() {",
            1,
        )[1].split(
            "function clearWinnerCelebration()",
            1,
        )[0]
        self.assertIn(
            "index * 360 / WINNER_SPARK_COUNT",
            prepare,
        )
        self.assertIn("245 + (index % 5) * 18", prepare)
        self.assertNotIn("Math.random", prepare)

    def test_winner_hold_and_celebration_are_longer(self):
        css = asset_text(WHEEL_RUNTIME_BROWSER_STYLE_PATH)
        script = asset_text(WHEEL_RUNTIME_BROWSER_SCRIPT_PATH)

        self.assertIn("const OVERLAY_RESULT_HOLD_MS = 8000", script)
        self.assertIn("winner-card-reveal 1050ms", css)
        self.assertIn("winner-title-reveal 1350ms", css)
        self.assertIn("winner-segment-pulse 1100ms ease-in-out 3", css)

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
