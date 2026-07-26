"""Read and validate the authoritative SMWC Downloader & Patcher identity.

The module intentionally depends only on the Python standard library. Runtime,
build, packaging, diagnostics, and release tooling can therefore consume the
same product metadata without importing the Tk application.
"""
from __future__ import annotations

import json
import os
import re
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

MANIFEST_FILENAME = "product_manifest.json"
_REQUIRED_TARGETS = {
    "windows-x86_64": ("windows", "x86_64"),
    "linux-x86_64": ("linux", "x86_64"),
    "macos-arm64": ("macos", "arm64"),
    "macos-x86_64": ("macos", "x86_64"),
}


class ProductManifestError(RuntimeError):
    """Raised when the authoritative product manifest is missing or invalid."""


def _runtime_root() -> Path:
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        return Path(frozen_root)
    return Path(__file__).resolve().parent


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ProductManifestError(f"Required product manifest is missing: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ProductManifestError(f"Product manifest is invalid JSON: {path}: {exc}") from exc

    if not isinstance(payload, dict):
        raise ProductManifestError(f"Product manifest root must be an object: {path}")
    return payload


def _require_mapping(mapping: Mapping[str, Any], key: str, context: str) -> Mapping[str, Any]:
    value = mapping.get(key)
    if not isinstance(value, dict) or not value:
        raise ProductManifestError(f"{context}.{key} must be a non-empty object")
    return value


def _require_string(mapping: Mapping[str, Any], key: str, context: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ProductManifestError(f"{context}.{key} must be a non-empty string")
    return value


def _validate_product(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    product = _require_mapping(payload, "product", "manifest")
    for key in (
        "id",
        "display_name",
        "version",
        "pep440_version",
        "release_channel",
        "publisher",
        "copyright",
        "python_requires",
    ):
        _require_string(product, key, "product")
    return product


def _validate_versions(
    payload: Mapping[str, Any], product_version: str, pep440_version: str
) -> Mapping[str, Any]:
    versions = _require_mapping(payload, "versions", "manifest")
    windows_numeric = versions.get("windows_numeric")
    if (
        not isinstance(windows_numeric, list)
        or len(windows_numeric) != 4
        or any(not isinstance(value, int) or value < 0 for value in windows_numeric)
    ):
        raise ProductManifestError(
            "versions.windows_numeric must contain four non-negative integers"
        )

    macos_short = _require_string(versions, "macos_short", "versions")
    macos_bundle = _require_string(versions, "macos_bundle", "versions")

    version_match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)-dev\.(\d+)", product_version)
    if not version_match:
        raise ProductManifestError(
            "product.version must use the development format X.Y.Z-dev.N"
        )

    major, minor, patch, development = (int(value) for value in version_match.groups())
    expected_windows = [major, minor, patch, development]
    expected_short = f"{major}.{minor}.{patch}"
    expected_bundle = f"{major}.{minor}.{patch}.{development}"
    expected_pep440 = f"{major}.{minor}.{patch}.dev{development}"

    if pep440_version != expected_pep440:
        raise ProductManifestError(
            "product.pep440_version does not match product.version: "
            f"expected {expected_pep440!r}, got {pep440_version!r}"
        )
    if windows_numeric != expected_windows:
        raise ProductManifestError(
            "versions.windows_numeric does not match product.version: "
            f"expected {expected_windows!r}, got {windows_numeric!r}"
        )
    if macos_short != expected_short:
        raise ProductManifestError(
            "versions.macos_short does not match product.version: "
            f"expected {expected_short!r}, got {macos_short!r}"
        )
    if macos_bundle != expected_bundle:
        raise ProductManifestError(
            "versions.macos_bundle does not match product.version: "
            f"expected {expected_bundle!r}, got {macos_bundle!r}"
        )
    return versions


def _validate_components(
    payload: Mapping[str, Any], product: Mapping[str, Any]
) -> Mapping[str, Any]:
    components = _require_mapping(payload, "components", "manifest")

    application = _require_mapping(components, "application", "components")
    for key in (
        "entry_point",
        "windows_name",
        "linux_name",
        "macos_bundle_name",
        "macos_bundle_identifier",
    ):
        _require_string(application, key, "components.application")

    updater = _require_mapping(components, "updater", "components")
    for key in (
        "entry_point",
        "windows_name",
        "linux_name",
        "macos_bundle_name",
        "macos_bundle_identifier",
        "product_id",
        "release_channel",
    ):
        _require_string(updater, key, "components.updater")

    expected_references = {
        "product_id": product["id"],
        "release_channel": product["release_channel"],
    }
    for key, expected in expected_references.items():
        if updater[key] != expected:
            raise ProductManifestError(
                f"components.updater.{key} must match product.{key}: "
                f"expected {expected!r}, got {updater[key]!r}"
            )
    return components


def _validate_targets(payload: Mapping[str, Any], product_version: str) -> Mapping[str, Any]:
    targets = _require_mapping(payload, "targets", "manifest")
    missing = sorted(set(_REQUIRED_TARGETS) - set(targets))
    unexpected = sorted(set(targets) - set(_REQUIRED_TARGETS))
    if missing or unexpected:
        details = []
        if missing:
            details.append("missing " + ", ".join(missing))
        if unexpected:
            details.append("unexpected " + ", ".join(unexpected))
        raise ProductManifestError("manifest.targets is invalid: " + "; ".join(details))

    for target_name, (expected_platform, expected_architecture) in _REQUIRED_TARGETS.items():
        target = _require_mapping(targets, target_name, "targets")
        for key in (
            "platform",
            "architecture",
            "runner",
            "artifact_type",
            "artifact_name",
        ):
            _require_string(target, key, f"targets.{target_name}")

        if target["platform"] != expected_platform:
            raise ProductManifestError(
                f"targets.{target_name}.platform must be {expected_platform!r}"
            )
        if target["architecture"] != expected_architecture:
            raise ProductManifestError(
                f"targets.{target_name}.architecture must be {expected_architecture!r}"
            )
        if product_version not in target["artifact_name"]:
            raise ProductManifestError(
                f"targets.{target_name}.artifact_name must contain {product_version!r}"
            )
    return targets


def load_product_manifest(path: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    """Load and validate a product manifest.

    Args:
        path: Optional manifest path. When omitted, the manifest beside this
            module (or inside the frozen application root) is used.
    """

    manifest_path = Path(path) if path is not None else _runtime_root() / MANIFEST_FILENAME
    payload = _read_json(manifest_path)
    if payload.get("schema_version") != 1:
        raise ProductManifestError(
            f"Unsupported product manifest schema: {payload.get('schema_version')!r}"
        )

    product = _validate_product(payload)
    _validate_versions(
        payload,
        str(product["version"]),
        str(product["pep440_version"]),
    )
    _validate_components(payload, product)
    _validate_targets(payload, str(product["version"]))
    return payload


PRODUCT_MANIFEST = load_product_manifest()
_PRODUCT = PRODUCT_MANIFEST["product"]
_COMPONENTS = PRODUCT_MANIFEST["components"]
_VERSIONS = PRODUCT_MANIFEST["versions"]

PRODUCT_ID = str(_PRODUCT["id"])
PRODUCT_DISPLAY_NAME = str(_PRODUCT["display_name"])
PRODUCT_VERSION = str(_PRODUCT["version"])
PEP440_VERSION = str(_PRODUCT["pep440_version"])
RELEASE_CHANNEL = str(_PRODUCT["release_channel"])
PYTHON_REQUIRES = str(_PRODUCT["python_requires"])
VERSION = f"v{PRODUCT_VERSION}"
WINDOWS_VERSION_TUPLE = tuple(int(value) for value in _VERSIONS["windows_numeric"])
MACOS_SHORT_VERSION = str(_VERSIONS["macos_short"])
MACOS_BUNDLE_VERSION = str(_VERSIONS["macos_bundle"])
APPLICATION_IDENTITY = deepcopy(_COMPONENTS["application"])
UPDATER_IDENTITY = deepcopy(_COMPONENTS["updater"])


def validate_supported_python(version_info: tuple[int, int] | None = None) -> tuple[int, int]:
    """Validate a Python major/minor version against ``python_requires``."""

    match = re.fullmatch(r">=(\d+)\.(\d+),<(\d+)\.(\d+)", PYTHON_REQUIRES)
    if not match:
        raise ProductManifestError(f"Unsupported python_requires format: {PYTHON_REQUIRES!r}")

    lower = (int(match.group(1)), int(match.group(2)))
    upper = (int(match.group(3)), int(match.group(4)))
    current = version_info or (sys.version_info.major, sys.version_info.minor)
    if not lower <= current < upper:
        raise ProductManifestError(
            f"Python {current[0]}.{current[1]} is outside the supported range "
            f"{PYTHON_REQUIRES}"
        )
    return current


def get_target(target_name: str) -> dict[str, Any]:
    """Return an isolated copy of a declared build target."""

    target = PRODUCT_MANIFEST["targets"].get(target_name)
    if not isinstance(target, dict):
        raise ProductManifestError(f"Unknown build target: {target_name}")
    return deepcopy(target)
