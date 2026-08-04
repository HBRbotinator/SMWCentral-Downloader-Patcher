"""Self-contained browser assets for the Wheel runtime preview."""

from __future__ import annotations

from dataclasses import dataclass


WHEEL_RUNTIME_BROWSER_PATH = "/wheel/"
WHEEL_RUNTIME_BROWSER_REDIRECT_PATH = "/wheel"
WHEEL_RUNTIME_BROWSER_SCRIPT_PATH = "/wheel/app.js"
WHEEL_RUNTIME_BROWSER_STYLE_PATH = "/wheel/style.css"


@dataclass(frozen=True)
class WheelRuntimeBrowserAsset:
    content_type: str
    payload: bytes


_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="color-scheme" content="dark">
  <title>SMWC Wheel Runtime</title>
  <link rel="stylesheet" href="./style.css">
</head>
<body>
  <main
    id="runtime-root"
    class="runtime"
    aria-labelledby="runtime-title"
  >
    <header class="runtime__header">
      <div>
        <p class="runtime__eyebrow">SMWC Downloader &amp; Patcher</p>
        <h1 id="runtime-title">Wheel Runtime</h1>
      </div>
      <div id="runtime-status" class="status" role="status" aria-live="polite">
        Connecting…
      </div>
    </header>

    <section class="wheel-stage" aria-label="Collection wheel preview">
      <svg
        id="wheel"
        class="wheel"
        viewBox="0 0 800 800"
        role="img"
        aria-labelledby="wheel-title wheel-description"
      >
        <title id="wheel-title">Collection wheel preview</title>
        <desc id="wheel-description">
          A read-only preview generated from the current Collection snapshot.
        </desc>
        <g
          id="wheel-segments"
          class="wheel__segments"
        ></g>
        <circle class="wheel__hub" cx="400" cy="400" r="92"></circle>
        <text
          id="wheel-count"
          class="wheel__count"
          x="400"
          y="392"
          text-anchor="middle"
        >0</text>
        <text
          class="wheel__caption"
          x="400"
          y="432"
          text-anchor="middle"
        >candidates</text>
      </svg>
      <div class="pointer" aria-hidden="true"></div>
      <div
        id="spin-result"
        class="spin-result"
        role="status"
        aria-live="polite"
        hidden
      >
        <span>Selected</span>
        <strong id="spin-winner"></strong>
      </div>
    </section>

    <footer class="runtime__footer">
      <span id="snapshot-detail">Waiting for a runtime snapshot.</span>
      <span>Read-only preview</span>
    </footer>
  </main>

  <script src="./app.js" defer></script>
</body>
</html>
"""

_CSS = """:root {
  color-scheme: dark;
  font-family:
    Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont,
    "Segoe UI", sans-serif;
  background: transparent;
}

* {
  box-sizing: border-box;
}

html,
body {
  min-height: 100%;
  margin: 0;
  background: transparent;
}

body {
  display: grid;
  place-items: center;
  padding: 24px;
  overflow: hidden;
  color: #f7f7fb;
}

body:not([data-mode]) .runtime {
  visibility: hidden;
}

.runtime {
  width: min(94vw, 920px);
  padding: clamp(18px, 3vw, 34px);
  border: 1px solid rgba(255, 255, 255, 0.14);
  border-radius: 28px;
  background:
    linear-gradient(145deg, rgba(24, 25, 35, 0.96), rgba(9, 10, 16, 0.94));
  box-shadow: 0 24px 70px rgba(0, 0, 0, 0.42);
  opacity: 1;
  visibility: visible;
  transform: scale(1);
  transition:
    opacity 180ms ease,
    transform 180ms ease,
    visibility 180ms step-start;
  backdrop-filter: blur(14px);
}

body[data-mode="overlay"] {
  padding: 0;
}

body[data-mode="overlay"] .runtime {
  width: min(96vw, 940px);
  padding: 0;
  border: 0;
  border-radius: 0;
  background: transparent;
  box-shadow: none;
  backdrop-filter: none;
}

body[data-mode="overlay"]:not(.overlay-active) .runtime {
  opacity: 0;
  visibility: hidden;
  pointer-events: none;
  transform: scale(0.985);
  transition:
    opacity 180ms ease,
    transform 180ms ease,
    visibility 180ms step-end;
}

body[data-mode="overlay"].overlay-active .runtime {
  opacity: 1;
  visibility: visible;
  transform: scale(1);
}

.runtime__header,
.runtime__footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
}

.runtime__header h1 {
  margin: 2px 0 0;
  font-size: clamp(1.7rem, 4vw, 2.6rem);
  line-height: 1;
}

.runtime__eyebrow {
  margin: 0;
  color: rgba(255, 255, 255, 0.58);
  font-size: 0.76rem;
  font-weight: 700;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

.status {
  padding: 8px 13px;
  border: 1px solid rgba(255, 255, 255, 0.14);
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.07);
  font-size: 0.82rem;
  font-weight: 700;
  white-space: nowrap;
}

.status[data-state="ready"] {
  border-color: rgba(119, 241, 177, 0.36);
  background: rgba(63, 180, 119, 0.16);
}

.status[data-state="waiting"] {
  border-color: rgba(255, 205, 105, 0.35);
  background: rgba(202, 143, 39, 0.15);
}

.status[data-state="error"] {
  border-color: rgba(255, 115, 125, 0.38);
  background: rgba(198, 54, 66, 0.17);
}

.wheel-stage {
  position: relative;
  display: grid;
  place-items: center;
  width: min(100%, 760px);
  margin: 22px auto;
  aspect-ratio: 1;
}

body[data-mode="overlay"] .runtime__header,
body[data-mode="overlay"] .runtime__footer {
  display: none;
}

body[data-mode="overlay"] .wheel-stage {
  width: min(94vmin, 900px);
  margin: 0 auto;
}

body[data-mode="overlay"] .wheel__count,
body[data-mode="overlay"] .wheel__caption {
  display: none;
}

.wheel {
  width: 100%;
  height: 100%;
  overflow: visible;
  filter: drop-shadow(0 20px 30px rgba(0, 0, 0, 0.28));
}

.wheel__segments {
  transform-box: view-box;
  transform-origin: 400px 400px;
  will-change: transform;
}

.wheel__segment {
  stroke: rgba(255, 255, 255, 0.22);
  stroke-width: 2;
}

.wheel__label {
  fill: rgba(255, 255, 255, 0.96);
  font-size: 16px;
  font-weight: 700;
  paint-order: stroke;
  stroke: rgba(0, 0, 0, 0.48);
  stroke-width: 4px;
  stroke-linejoin: round;
}

.wheel__empty {
  fill: rgba(255, 255, 255, 0.07);
  stroke: rgba(255, 255, 255, 0.2);
  stroke-width: 3;
}

.wheel__hub {
  fill: rgba(16, 17, 24, 0.96);
  stroke: rgba(255, 255, 255, 0.22);
  stroke-width: 4;
}

.wheel__count {
  fill: #ffffff;
  font-size: 54px;
  font-weight: 800;
}

.wheel__caption {
  fill: rgba(255, 255, 255, 0.6);
  font-size: 17px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.pointer {
  position: absolute;
  top: -4px;
  width: 0;
  height: 0;
  border-right: 20px solid transparent;
  border-left: 20px solid transparent;
  border-top: 44px solid #f5f5f7;
  filter: drop-shadow(0 5px 5px rgba(0, 0, 0, 0.35));
}

.spin-result {
  position: absolute;
  left: 50%;
  bottom: 5%;
  display: grid;
  width: min(88%, 720px);
  gap: 7px;
  padding: 15px 24px 18px;
  border: 1px solid rgba(255, 255, 255, 0.24);
  border-radius: 18px;
  background: rgba(12, 13, 20, 0.9);
  box-shadow: 0 14px 32px rgba(0, 0, 0, 0.38);
  text-align: center;
  transform: translateX(-50%);
  transform-origin: center;
  backdrop-filter: blur(12px);
}

.spin-result[hidden] {
  display: none;
}

.spin-result--visible {
  animation: winner-card-reveal 620ms cubic-bezier(0.16, 1, 0.3, 1);
}

.spin-result span {
  color: rgba(255, 255, 255, 0.58);
  font-size: 0.7rem;
  font-weight: 800;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

.spin-result strong {
  display: block;
  width: 100%;
  color: #ffffff;
  font-size: clamp(1.35rem, 3.4vw, 2.15rem);
  font-weight: 850;
  line-height: 1.08;
  overflow-wrap: anywhere;
  text-wrap: balance;
  white-space: normal;
  animation: winner-title-reveal 760ms cubic-bezier(0.16, 1, 0.3, 1);
}

.spin-result[data-title-size="medium"] strong {
  font-size: clamp(1.2rem, 2.9vw, 1.8rem);
}

.spin-result[data-title-size="long"] strong {
  font-size: clamp(1.05rem, 2.45vw, 1.5rem);
  line-height: 1.12;
}

.spin-result[data-title-size="extra-long"] strong {
  font-size: clamp(0.9rem, 2vw, 1.2rem);
  line-height: 1.16;
}

body[data-mode="overlay"] .spin-result {
  bottom: 2.5%;
  width: min(92%, 780px);
  border-color: rgba(255, 255, 255, 0.3);
  background: rgba(10, 11, 17, 0.92);
  box-shadow:
    0 18px 44px rgba(0, 0, 0, 0.48),
    0 0 30px rgba(255, 255, 255, 0.08);
}

.wheel__segment--winner {
  filter:
    brightness(1.22)
    saturate(1.2)
    drop-shadow(0 0 11px rgba(255, 255, 255, 0.72));
  animation: winner-segment-pulse 920ms ease-in-out 2;
}

.wheel__label--winner {
  fill: #ffffff;
  font-weight: 900;
  stroke-width: 5px;
}

@keyframes winner-card-reveal {
  0% {
    opacity: 0;
    transform: translateX(-50%) translateY(28px) scale(0.88);
  }

  58% {
    opacity: 1;
    transform: translateX(-50%) translateY(-6px) scale(1.035);
  }

  100% {
    opacity: 1;
    transform: translateX(-50%) translateY(0) scale(1);
  }
}

@keyframes winner-title-reveal {
  0% {
    opacity: 0;
    transform: scale(0.82);
    letter-spacing: 0.06em;
  }

  64% {
    opacity: 1;
    transform: scale(1.045);
    letter-spacing: 0;
  }

  100% {
    opacity: 1;
    transform: scale(1);
    letter-spacing: 0;
  }
}

@keyframes winner-segment-pulse {
  0%,
  100% {
    opacity: 1;
  }

  50% {
    opacity: 0.78;
  }
}

.runtime__footer {
  color: rgba(255, 255, 255, 0.58);
  font-size: 0.78rem;
}

.runtime__footer span:last-child {
  white-space: nowrap;
}

@media (max-width: 620px) {
  body {
    padding: 10px;
  }

  .runtime {
    border-radius: 20px;
  }

  .runtime__header,
  .runtime__footer {
    align-items: flex-start;
    flex-direction: column;
  }

  .wheel__label {
    font-size: 12px;
  }

  .spin-result {
    width: min(94%, 720px);
    padding: 12px 15px 14px;
  }

  .spin-result strong {
    font-size: clamp(1.05rem, 5.5vw, 1.5rem);
  }

  .spin-result[data-title-size="long"] strong,
  .spin-result[data-title-size="extra-long"] strong {
    font-size: clamp(0.88rem, 4.5vw, 1.18rem);
  }
}
"""

_JAVASCRIPT = """"use strict";

const SVG_NS = "http://www.w3.org/2000/svg";
const HEALTH_PATH = "/api/v1/health";
const SNAPSHOT_PATH = "/api/v1/snapshot";
const SPIN_PATH = "/api/v1/spin";
const POLL_INTERVAL_MS = 750;
const MAX_VISIBLE_LABELS = 36;
const OVERLAY_RESULT_HOLD_MS = 5000;
const SPIN_LAUNCH_SHARE = 0.16;
const SPIN_CRUISE_SHARE = 0.47;
const SPIN_LAUNCH_DISTANCE_SHARE = 0.24;
const SPIN_MIN_ANTICIPATION_ARC = 42;
const SPIN_MAX_ANTICIPATION_ARC = 160;
const SPIN_ANTICIPATION_SEGMENTS = 1.3;
const SPIN_LAUNCH_EASING = "cubic-bezier(0.45, 0, 0.75, 0.35)";
const SPIN_CRUISE_EASING = "linear";
const SPIN_ANTICIPATION_EASING = (
  "cubic-bezier(0.08, 0.72, 0.12, 1)"
);
const DISPLAY_MODE = (
  new URLSearchParams(window.location.search).get("mode") === "overlay"
    ? "overlay"
    : "preview"
);

const runtimeElement = document.getElementById("runtime-root");
const statusElement = document.getElementById("runtime-status");
const detailElement = document.getElementById("snapshot-detail");
const segmentsElement = document.getElementById("wheel-segments");
const countElement = document.getElementById("wheel-count");
const resultElement = document.getElementById("spin-result");
const winnerElement = document.getElementById("spin-winner");

let currentSnapshot = null;
let lastSnapshotIdentity = "";
let lastObservedSpinSequence = 0;
let lastObservedSpinId = "";
let currentRotation = 0;
let animationGeneration = 0;
let refreshInProgress = false;
let overlayHideTimer = null;

document.body.dataset.mode = DISPLAY_MODE;

function isOverlayMode() {
  return DISPLAY_MODE === "overlay";
}

function clearOverlayHideTimer() {
  if (overlayHideTimer === null) {
    return;
  }
  window.clearTimeout(overlayHideTimer);
  overlayHideTimer = null;
}

function showOverlay() {
  if (!isOverlayMode()) {
    return;
  }
  clearOverlayHideTimer();
  document.body.classList.add("overlay-active");
  runtimeElement.setAttribute("aria-hidden", "false");
}

function hideOverlay() {
  if (!isOverlayMode()) {
    return;
  }
  clearOverlayHideTimer();
  document.body.classList.remove("overlay-active");
  runtimeElement.setAttribute("aria-hidden", "true");
}

function scheduleOverlayHide() {
  if (!isOverlayMode()) {
    return;
  }
  clearOverlayHideTimer();
  overlayHideTimer = window.setTimeout(
    hideOverlay,
    OVERLAY_RESULT_HOLD_MS,
  );
}

function setStatus(text, state) {
  statusElement.textContent = text;
  statusElement.dataset.state = state;
}

function truncate(text, length) {
  const value = String(text || "").trim();
  return value.length > length
    ? `${value.slice(0, length - 1)}…`
    : value;
}

function pointOnCircle(radius, angleDegrees) {
  const angle = (angleDegrees - 90) * Math.PI / 180;
  return {
    x: 400 + radius * Math.cos(angle),
    y: 400 + radius * Math.sin(angle),
  };
}

function sectorPath(startDegrees, endDegrees) {
  const start = pointOnCircle(350, endDegrees);
  const end = pointOnCircle(350, startDegrees);
  const largeArc = endDegrees - startDegrees <= 180 ? 0 : 1;
  return [
    "M", 400, 400,
    "L", start.x.toFixed(3), start.y.toFixed(3),
    "A", 350, 350, 0, largeArc, 0,
    end.x.toFixed(3), end.y.toFixed(3),
    "Z",
  ].join(" ");
}

function segmentColor(index, total) {
  const denominator = Math.max(total, 1);
  const hue = Math.round((index * 360 / denominator + 252) % 360);
  return `hsl(${hue} 68% 48%)`;
}

function createSvgElement(name, attributes = {}) {
  const element = document.createElementNS(SVG_NS, name);
  for (const [key, value] of Object.entries(attributes)) {
    element.setAttribute(key, String(value));
  }
  return element;
}

function signedDegrees(angle) {
  return ((angle + 180) % 360 + 360) % 360 - 180;
}

function labelFlipForRotation(baseAngle, wheelRotation) {
  const screenAngle = signedDegrees(baseAngle + wheelRotation);
  return screenAngle > 90 || screenAngle < -90 ? 180 : 0;
}

function updateWheelLabelOrientation(wheelRotation) {
  const labels = segmentsElement.querySelectorAll(".wheel__label");
  labels.forEach((label) => {
    const baseAngle = Number(label.dataset.baseAngle);
    const x = Number(label.dataset.labelX);
    const y = Number(label.dataset.labelY);
    const flip = labelFlipForRotation(
      baseAngle,
      wheelRotation,
    );
    label.setAttribute(
      "transform",
      `rotate(${baseAngle + flip} ${x} ${y})`,
    );
  });
}

function resultTitleSize(title) {
  const length = Array.from(String(title || "").trim()).length;
  if (length > 96) {
    return "extra-long";
  }
  if (length > 62) {
    return "long";
  }
  if (length > 34) {
    return "medium";
  }
  return "short";
}

function clearWinnerHighlight() {
  segmentsElement
    .querySelectorAll(
      ".wheel__segment--winner, .wheel__label--winner",
    )
    .forEach((element) => {
      element.classList.remove(
        "wheel__segment--winner",
        "wheel__label--winner",
      );
    });
}

function highlightWinner(candidateId) {
  const normalizedId = String(candidateId || "");
  clearWinnerHighlight();

  segmentsElement
    .querySelectorAll("[data-candidate-id]")
    .forEach((element) => {
      if (element.dataset.candidateId !== normalizedId) {
        return;
      }
      if (element.classList.contains("wheel__segment")) {
        element.classList.add("wheel__segment--winner");
      }
      if (element.classList.contains("wheel__label")) {
        element.classList.add("wheel__label--winner");
      }
    });
}

function hideResult() {
  resultElement.hidden = true;
  resultElement.classList.remove("spin-result--visible");
  resultElement.removeAttribute("data-title-size");
  winnerElement.textContent = "";
  clearWinnerHighlight();
}

function showResult(title, candidateId) {
  const fullTitle = String(title || "").trim();
  winnerElement.textContent = fullTitle;
  resultElement.dataset.titleSize = resultTitleSize(fullTitle);
  resultElement.hidden = false;
  resultElement.classList.remove("spin-result--visible");
  void resultElement.offsetWidth;
  resultElement.classList.add("spin-result--visible");
  highlightWinner(candidateId);
}

function resetWheelRotation() {
  animationGeneration += 1;
  currentRotation = 0;
  segmentsElement.style.transition = "none";
  segmentsElement.style.transform = "rotate(0deg)";
  updateWheelLabelOrientation(currentRotation);
  hideResult();
  hideOverlay();
}

function renderEmptyWheel() {
  const circle = createSvgElement("circle", {
    class: "wheel__empty",
    cx: 400,
    cy: 400,
    r: 350,
  });
  segmentsElement.replaceChildren(circle);
  countElement.textContent = "0";
  resetWheelRotation();
}

function renderWheel(candidates) {
  const safeCandidates = Array.isArray(candidates) ? candidates : [];
  const count = safeCandidates.length;
  countElement.textContent = String(count);

  if (count === 0) {
    renderEmptyWheel();
    return;
  }

  const fragment = document.createDocumentFragment();
  const angle = 360 / count;

  safeCandidates.forEach((candidate, index) => {
    const start = index * angle;
    const end = (index + 1) * angle;
    const candidateId = String(candidate.id || "");

    let shape;
    if (count === 1) {
      shape = createSvgElement("circle", {
        class: "wheel__segment",
        cx: 400,
        cy: 400,
        r: 350,
        fill: segmentColor(index, count),
      });
    } else {
      shape = createSvgElement("path", {
        class: "wheel__segment",
        d: sectorPath(start, end),
        fill: segmentColor(index, count),
      });
    }
    shape.dataset.candidateId = candidateId;
    fragment.appendChild(shape);

    if (count <= MAX_VISIBLE_LABELS) {
      const midpoint = start + angle / 2;
      const position = pointOnCircle(
        count < 5 ? 225 : 255,
        midpoint,
      );
      const label = createSvgElement("text", {
        class: "wheel__label",
        x: position.x.toFixed(3),
        y: position.y.toFixed(3),
        "text-anchor": "middle",
        "dominant-baseline": "middle",
      });
      label.dataset.candidateId = candidateId;
      label.dataset.baseAngle = String(midpoint);
      label.dataset.labelX = position.x.toFixed(3);
      label.dataset.labelY = position.y.toFixed(3);
      label.textContent = truncate(
        candidate.title,
        count < 8 ? 24 : 15,
      );
      fragment.appendChild(label);
    }
  });

  segmentsElement.replaceChildren(fragment);
  resetWheelRotation();
}

function snapshotIdentity(snapshot) {
  return [
    snapshot.generated_at || "",
    snapshot.source?.revision || "",
    snapshot.candidates?.length || 0,
  ].join("|");
}

function spinMatchesSnapshot(spin, snapshot) {
  const candidates = Array.isArray(snapshot?.candidates)
    ? snapshot.candidates
    : [];
  const winnerIndex = Number(spin?.winner?.index);
  const winner = candidates[winnerIndex];

  return Boolean(
    spin
    && snapshot
    && spin.snapshot?.generated_at === snapshot.generated_at
    && spin.snapshot?.source_revision
      === (snapshot.source?.revision ?? null)
    && spin.snapshot?.candidate_count === candidates.length
    && Number.isInteger(winnerIndex)
    && winnerIndex >= 0
    && winnerIndex < candidates.length
    && String(winner?.id || "") === String(spin.winner?.id || "")
  );
}

function targetRotationForSpin(spin, candidateCount) {
  const angle = 360 / candidateCount;
  const winnerAngle = (
    Number(spin.winner.index)
    + Number(spin.animation.landing_offset)
  ) * angle;
  const targetModulo = (360 - winnerAngle) % 360;
  const currentModulo = ((currentRotation % 360) + 360) % 360;
  const alignment = (
    targetModulo
    - currentModulo
    + 360
  ) % 360;

  return (
    currentRotation
    + Number(spin.animation.turns) * 360
    + alignment
  );
}

function buildSpinMotionPlan(spin, snapshot) {
  const duration = Number(spin.animation.duration_ms);
  const start = currentRotation;
  const target = targetRotationForSpin(
    spin,
    snapshot.candidates.length,
  );
  const totalDistance = target - start;
  const segmentAngle = 360 / snapshot.candidates.length;
  const requestedAnticipationArc = (
    segmentAngle * SPIN_ANTICIPATION_SEGMENTS
  );
  const anticipationArc = Math.min(
    SPIN_MAX_ANTICIPATION_ARC,
    Math.max(
      SPIN_MIN_ANTICIPATION_ARC,
      requestedAnticipationArc,
    ),
    totalDistance * 0.25,
  );
  const preAnticipationDistance = totalDistance - anticipationArc;
  const launchTarget = (
    start
    + preAnticipationDistance * SPIN_LAUNCH_DISTANCE_SHARE
  );
  const cruiseTarget = target - anticipationArc;
  const launchDuration = Math.round(
    duration * SPIN_LAUNCH_SHARE
  );
  const cruiseDuration = Math.round(
    duration * SPIN_CRUISE_SHARE
  );
  const anticipationDuration = Math.max(
    1,
    duration - launchDuration - cruiseDuration,
  );

  return {
    start,
    target,
    launchTarget,
    cruiseTarget,
    launchDuration,
    cruiseDuration,
    anticipationDuration,
  };
}

function applySpinPhase(
  generation,
  target,
  duration,
  easing,
) {
  if (generation !== animationGeneration) {
    return;
  }
  updateWheelLabelOrientation(target);
  segmentsElement.style.transition = (
    `transform ${duration}ms ${easing}`
  );
  segmentsElement.style.transform = `rotate(${target}deg)`;
}

function animateSpin(spin, snapshot) {
  const generation = ++animationGeneration;
  const plan = buildSpinMotionPlan(spin, snapshot);
  const cruiseStart = plan.launchDuration;
  const anticipationStart = (
    plan.launchDuration + plan.cruiseDuration
  );
  const totalDuration = (
    anticipationStart + plan.anticipationDuration
  );

  showOverlay();
  hideResult();
  setStatus("Spinning…", "ready");
  detailElement.textContent = "Winner selected by the desktop application.";
  segmentsElement.style.transition = "none";
  segmentsElement.style.transform = `rotate(${plan.start}deg)`;

  window.requestAnimationFrame(() => {
    applySpinPhase(
      generation,
      plan.launchTarget,
      plan.launchDuration,
      SPIN_LAUNCH_EASING,
    );
  });

  window.setTimeout(() => {
    applySpinPhase(
      generation,
      plan.cruiseTarget,
      plan.cruiseDuration,
      SPIN_CRUISE_EASING,
    );
  }, cruiseStart);

  window.setTimeout(() => {
    applySpinPhase(
      generation,
      plan.target,
      plan.anticipationDuration,
      SPIN_ANTICIPATION_EASING,
    );
  }, anticipationStart);

  window.setTimeout(() => {
    if (generation !== animationGeneration) {
      return;
    }
    currentRotation = plan.target;
    segmentsElement.style.transition = "none";
    setStatus("Result ready", "ready");
    detailElement.textContent = (
      `Spin ${spin.sequence} · ${spin.issued_at}`
    );
    showResult(spin.winner.title, spin.winner.id);
    scheduleOverlayHide();
  }, totalDuration + 80);
}

function spinWasAlreadyObserved(spin) {
  const sequence = Number(spin?.sequence);
  const spinId = String(spin?.spin_id || "");

  return (
    !Number.isInteger(sequence)
    || sequence <= lastObservedSpinSequence
    || !spinId
    || spinId === lastObservedSpinId
  );
}

function observeSpin(spin, snapshot) {
  if (spinWasAlreadyObserved(spin)) {
    return;
  }

  if (!spinMatchesSnapshot(spin, snapshot)) {
    hideOverlay();
    setStatus("Synchronizing…", "waiting");
    detailElement.textContent = (
      "Waiting for the snapshot used by the latest spin."
    );
    return;
  }

  lastObservedSpinSequence = Number(spin.sequence);
  lastObservedSpinId = String(spin.spin_id);
  animateSpin(spin, snapshot);
}

async function getJson(path) {
  const response = await fetch(path, {
    cache: "no-store",
    credentials: "same-origin",
    headers: { "Accept": "application/json" },
  });
  const document = await response.json();
  if (!response.ok) {
    const message = document?.error?.message || `HTTP ${response.status}`;
    const error = new Error(message);
    error.status = response.status;
    throw error;
  }
  return document;
}

async function refreshSnapshot() {
  const snapshot = await getJson(SNAPSHOT_PATH);
  const identity = snapshotIdentity(snapshot);

  if (identity !== lastSnapshotIdentity) {
    renderWheel(snapshot.candidates);
    lastSnapshotIdentity = identity;
  }
  currentSnapshot = snapshot;
  return snapshot;
}

async function refreshRuntime() {
  if (refreshInProgress) {
    return;
  }
  refreshInProgress = true;

  try {
    const health = await getJson(HEALTH_PATH);
    const snapshotStatus = health.snapshot || {};
    const spinStatus = health.spin || {};

    if (!snapshotStatus.ready) {
      setStatus("Waiting for snapshot", "waiting");
      detailElement.textContent = (
        "The desktop runtime has not published data yet."
      );
      currentSnapshot = null;
      lastSnapshotIdentity = "";
      renderEmptyWheel();
      hideOverlay();
      return;
    }

    const snapshot = await refreshSnapshot();
    const count = Array.isArray(snapshot.candidates)
      ? snapshot.candidates.length
      : 0;
    const revision = snapshot.source?.revision;

    if (!spinStatus.configured) {
      hideOverlay();
      setStatus("Preview connected", "ready");
      detailElement.textContent = revision
        ? `${count} candidates · revision ${revision}`
        : `${count} candidates · ${snapshot.generated_at}`;
      return;
    }

    if (!spinStatus.ready) {
      hideOverlay();
      setStatus("Ready for spin", "ready");
      detailElement.textContent = `${count} candidates loaded`;
      return;
    }

    const spin = await getJson(SPIN_PATH);
    observeSpin(spin, snapshot);
  } catch (error) {
    if (error?.status === 503) {
      setStatus("Waiting for runtime", "waiting");
    } else {
      setStatus("Connection error", "error");
    }
    detailElement.textContent = error instanceof Error
      ? error.message
      : "The Wheel runtime could not be reached.";
  } finally {
    refreshInProgress = false;
  }
}

renderEmptyWheel();
hideOverlay();
refreshRuntime();
window.setInterval(refreshRuntime, POLL_INTERVAL_MS);
"""


def _asset(content_type: str, text: str) -> WheelRuntimeBrowserAsset:
    return WheelRuntimeBrowserAsset(
        content_type=content_type,
        payload=text.encode("utf-8"),
    )


_ASSETS = {
    WHEEL_RUNTIME_BROWSER_PATH: _asset(
        "text/html; charset=utf-8",
        _HTML,
    ),
    WHEEL_RUNTIME_BROWSER_STYLE_PATH: _asset(
        "text/css; charset=utf-8",
        _CSS,
    ),
    WHEEL_RUNTIME_BROWSER_SCRIPT_PATH: _asset(
        "text/javascript; charset=utf-8",
        _JAVASCRIPT,
    ),
}


def get_wheel_runtime_browser_asset(
    path: str,
) -> WheelRuntimeBrowserAsset | None:
    """Return one immutable embedded browser asset by exact route."""

    if not isinstance(path, str):
        raise TypeError("path must be a string")
    return _ASSETS.get(path)


__all__ = [
    "WHEEL_RUNTIME_BROWSER_PATH",
    "WHEEL_RUNTIME_BROWSER_REDIRECT_PATH",
    "WHEEL_RUNTIME_BROWSER_SCRIPT_PATH",
    "WHEEL_RUNTIME_BROWSER_STYLE_PATH",
    "WheelRuntimeBrowserAsset",
    "get_wheel_runtime_browser_asset",
]
