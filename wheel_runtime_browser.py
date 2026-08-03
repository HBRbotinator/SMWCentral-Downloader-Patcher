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
  <main class="runtime" aria-labelledby="runtime-title">
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
        <g id="wheel-segments"></g>
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
  color: #f7f7fb;
}

.runtime {
  width: min(94vw, 920px);
  padding: clamp(18px, 3vw, 34px);
  border: 1px solid rgba(255, 255, 255, 0.14);
  border-radius: 28px;
  background:
    linear-gradient(145deg, rgba(24, 25, 35, 0.96), rgba(9, 10, 16, 0.94));
  box-shadow: 0 24px 70px rgba(0, 0, 0, 0.42);
  backdrop-filter: blur(14px);
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

.wheel {
  width: 100%;
  height: 100%;
  overflow: visible;
  filter: drop-shadow(0 20px 30px rgba(0, 0, 0, 0.28));
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
}
"""

_JAVASCRIPT = """"use strict";

const SVG_NS = "http://www.w3.org/2000/svg";
const HEALTH_PATH = "/api/v1/health";
const SNAPSHOT_PATH = "/api/v1/snapshot";
const POLL_INTERVAL_MS = 2000;
const MAX_VISIBLE_LABELS = 36;

const statusElement = document.getElementById("runtime-status");
const detailElement = document.getElementById("snapshot-detail");
const segmentsElement = document.getElementById("wheel-segments");
const countElement = document.getElementById("wheel-count");

let lastSnapshotIdentity = "";

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
  const hue = Math.round((index * 360 / Math.max(total, 1) + 252) % 360);
  return `hsl(${hue} 68% 48%)`;
}

function createSvgElement(name, attributes = {}) {
  const element = document.createElementNS(SVG_NS, name);
  for (const [key, value] of Object.entries(attributes)) {
    element.setAttribute(key, String(value));
  }
  return element;
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
      const position = pointOnCircle(count < 5 ? 225 : 255, midpoint);
      const label = createSvgElement("text", {
        class: "wheel__label",
        x: position.x.toFixed(3),
        y: position.y.toFixed(3),
        "text-anchor": "middle",
        "dominant-baseline": "middle",
      });
      label.dataset.candidateId = candidateId;
      label.textContent = truncate(candidate.title, count < 8 ? 24 : 15);
      fragment.appendChild(label);
    }
  });

  segmentsElement.replaceChildren(fragment);
}

function snapshotIdentity(snapshot) {
  return [
    snapshot.generated_at || "",
    snapshot.source?.revision || "",
    snapshot.candidates?.length || 0,
  ].join("|");
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
    throw new Error(message);
  }
  return document;
}

async function refreshPreview() {
  try {
    const health = await getJson(HEALTH_PATH);
    const snapshotStatus = health.snapshot || {};

    if (!snapshotStatus.ready) {
      setStatus("Waiting for snapshot", "waiting");
      detailElement.textContent = "The desktop runtime has not published data yet.";
      renderEmptyWheel();
      lastSnapshotIdentity = "";
      return;
    }

    const snapshot = await getJson(SNAPSHOT_PATH);
    const identity = snapshotIdentity(snapshot);
    if (identity !== lastSnapshotIdentity) {
      renderWheel(snapshot.candidates);
      lastSnapshotIdentity = identity;
    }

    const count = Array.isArray(snapshot.candidates)
      ? snapshot.candidates.length
      : 0;
    const revision = snapshot.source?.revision;
    setStatus("Connected", "ready");
    detailElement.textContent = revision
      ? `${count} candidates · revision ${revision}`
      : `${count} candidates · ${snapshot.generated_at}`;
  } catch (error) {
    setStatus("Connection error", "error");
    detailElement.textContent = error instanceof Error
      ? error.message
      : "The Wheel runtime could not be reached.";
  }
}

renderEmptyWheel();
refreshPreview();
window.setInterval(refreshPreview, POLL_INTERVAL_MS);
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
