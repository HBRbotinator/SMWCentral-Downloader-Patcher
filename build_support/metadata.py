"""Generate target-bound candidate metadata from the product manifest."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

from build_support.manifest import ROOT, SUPPORTED_TARGETS, target_config
from product_identity import (
    APPLICATION_IDENTITY,
    PRODUCT_DISPLAY_NAME,
    PRODUCT_ID,
    PRODUCT_VERSION,
    RELEASE_CHANNEL,
    UPDATER_IDENTITY,
)

GENERATED_ROOT = ROOT / "build" / "generated"


def _source_revision() -> str:
    explicit = os.environ.get("SMWC_SOURCE_REVISION") or os.environ.get("GITHUB_SHA")
    if explicit:
        return explicit.strip()
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip() or "unknown"
    except (FileNotFoundError, subprocess.CalledProcessError):
        return "unknown"


def _source_dirty() -> bool | None:
    explicit = os.environ.get("SMWC_SOURCE_DIRTY")
    if explicit is not None:
        return explicit.strip().casefold() in {"1", "true", "yes", "on"}
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        return bool(result.stdout.strip())
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None


def build_identity(target_name: str) -> dict[str, Any]:
    """Return deterministic identity for one native candidate target."""

    target = target_config(target_name)
    return {
        "schema_version": 1,
        "product_id": PRODUCT_ID,
        "product_name": PRODUCT_DISPLAY_NAME,
        "version": PRODUCT_VERSION,
        "release_channel": RELEASE_CHANNEL,
        "target": target_name,
        "platform": target["platform"],
        "architecture": target["architecture"],
        "artifact_name": target["artifact_name"],
        "source_revision": _source_revision(),
        "source_dirty": _source_dirty(),
        "components": {
            "application": {
                "windows_name": APPLICATION_IDENTITY["windows_name"],
                "linux_name": APPLICATION_IDENTITY["linux_name"],
                "macos_bundle_name": APPLICATION_IDENTITY["macos_bundle_name"],
            },
            "updater": {
                "windows_name": UPDATER_IDENTITY["windows_name"],
                "linux_name": UPDATER_IDENTITY["linux_name"],
                "macos_bundle_name": UPDATER_IDENTITY["macos_bundle_name"],
            },
        },
    }


def write_build_identity(
    target_name: str,
    output_directory: str | Path | None = None,
) -> Path:
    """Write one candidate identity file and return its path."""

    if target_name not in SUPPORTED_TARGETS:
        raise ValueError(f"Unknown target {target_name!r}")
    directory = (
        Path(output_directory)
        if output_directory is not None
        else GENERATED_ROOT / target_name
    )
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "build_identity.json"
    path.write_text(
        json.dumps(build_identity(target_name), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path
