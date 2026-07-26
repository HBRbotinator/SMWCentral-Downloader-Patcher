"""Manifest-backed build configuration shared by every package target."""
from __future__ import annotations

import platform
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

from product_identity import PRODUCT_MANIFEST, ProductManifestError

ROOT = Path(__file__).resolve().parents[1]
SUPPORTED_TARGETS = tuple(PRODUCT_MANIFEST["targets"])
_COMPONENT_NAMES = ("application", "updater")


def _component_name(component_name: str) -> str:
    if component_name not in _COMPONENT_NAMES:
        raise ProductManifestError(
            f"Unknown build component {component_name!r}; "
            f"expected one of {', '.join(_COMPONENT_NAMES)}"
        )
    return component_name


def target_config(target_name: str) -> dict[str, Any]:
    """Return an isolated build-target definition."""

    target = PRODUCT_MANIFEST["targets"].get(target_name)
    if not isinstance(target, dict):
        raise ProductManifestError(f"Unknown build target: {target_name}")
    return deepcopy(target)


def component_build_config(component_name: str) -> dict[str, Any]:
    """Return validated packaging configuration for one component."""

    component_name = _component_name(component_name)
    build = PRODUCT_MANIFEST.get("build")
    if not isinstance(build, Mapping):
        raise ProductManifestError("manifest.build must be an object")
    config = build.get(component_name)
    if not isinstance(config, Mapping):
        raise ProductManifestError(f"manifest.build.{component_name} must be an object")

    console = config.get("console")
    resources = config.get("resources")
    hidden = config.get("hidden_imports")
    package_data = config.get("package_data")
    if not isinstance(console, bool):
        raise ProductManifestError(f"build.{component_name}.console must be a boolean")
    if not isinstance(resources, list):
        raise ProductManifestError(f"build.{component_name}.resources must be a list")
    if not isinstance(hidden, list) or any(not isinstance(value, str) for value in hidden):
        raise ProductManifestError(
            f"build.{component_name}.hidden_imports must contain strings"
        )
    if not isinstance(package_data, list) or any(
        not isinstance(value, str) for value in package_data
    ):
        raise ProductManifestError(
            f"build.{component_name}.package_data must contain strings"
        )

    normalized_resources: list[dict[str, str]] = []
    for index, resource in enumerate(resources):
        context = f"build.{component_name}.resources[{index}]"
        if not isinstance(resource, Mapping):
            raise ProductManifestError(f"{context} must be an object")
        source = resource.get("source")
        destination = resource.get("destination")
        kind = resource.get("kind")
        if not isinstance(source, str) or not source:
            raise ProductManifestError(f"{context}.source must be a non-empty string")
        if not isinstance(destination, str) or not destination:
            raise ProductManifestError(
                f"{context}.destination must be a non-empty string"
            )
        if kind not in {"file", "directory"}:
            raise ProductManifestError(f"{context}.kind must be 'file' or 'directory'")
        source_path = ROOT / source
        if kind == "file" and not source_path.is_file():
            raise ProductManifestError(f"Required build file is missing: {source}")
        if kind == "directory" and not source_path.is_dir():
            raise ProductManifestError(f"Required build directory is missing: {source}")
        normalized_resources.append(
            {"source": source, "destination": destination, "kind": str(kind)}
        )

    return {
        "console": console,
        "resources": normalized_resources,
        "hidden_imports": list(hidden),
        "package_data": list(package_data),
    }


def build_resources(component_name: str) -> list[tuple[str, str]]:
    """Return PyInstaller data-file tuples for one component."""

    values: list[tuple[str, str]] = []
    for resource in component_build_config(component_name)["resources"]:
        values.append((str(ROOT / resource["source"]), resource["destination"]))
    return values


def hidden_imports(component_name: str) -> list[str]:
    return list(component_build_config(component_name)["hidden_imports"])


def package_data_packages(component_name: str) -> list[str]:
    return list(component_build_config(component_name)["package_data"])


def component_console(component_name: str) -> bool:
    return bool(component_build_config(component_name)["console"])


def auto_target(
    platform_name: str | None = None,
    machine_name: str | None = None,
) -> str:
    """Resolve the supported native target for the current host."""

    platform_value = (platform_name or sys.platform).casefold()
    machine_value = (machine_name or platform.machine()).casefold()
    if platform_value.startswith("win"):
        target = "windows-x86_64"
    elif platform_value.startswith("linux"):
        target = "linux-x86_64"
    elif platform_value.startswith("darwin") or platform_value.startswith("mac"):
        if machine_value in {"arm64", "aarch64"}:
            target = "macos-arm64"
        elif machine_value in {"x86_64", "amd64"}:
            target = "macos-x86_64"
        else:
            raise ProductManifestError(
                f"Unsupported macOS build architecture: {machine_value or '<empty>'}"
            )
    else:
        raise ProductManifestError(f"Unsupported build platform: {platform_value}")

    declared = target_config(target)
    expected_machine = str(declared["architecture"])
    normalized_machine = "x86_64" if machine_value == "amd64" else machine_value
    if target.startswith(("windows-", "linux-")) and normalized_machine not in {
        "x86_64",
        "amd64",
    }:
        raise ProductManifestError(
            f"Target {target} requires {expected_machine}, detected {machine_value}"
        )
    return target


def _component_identity(component_name: str) -> Mapping[str, Any]:
    component_name = _component_name(component_name)
    component = PRODUCT_MANIFEST["components"].get(component_name)
    if not isinstance(component, Mapping):
        raise ProductManifestError(f"Missing component identity: {component_name}")
    return component


def component_output_name(component_name: str, target_name: str) -> str:
    """Return the PyInstaller executable name for a target."""

    component = _component_identity(component_name)
    target = target_config(target_name)
    platform_name = target["platform"]
    if platform_name == "windows":
        return str(component["windows_name"])
    if platform_name == "linux":
        return str(component["linux_name"])
    if platform_name == "macos":
        return str(component["macos_bundle_name"]).removesuffix(".app")
    raise ProductManifestError(f"Unsupported target platform: {platform_name}")


def validate_build_manifest() -> dict[str, Any]:
    """Validate all targets and component packaging definitions."""

    targets = {name: target_config(name) for name in SUPPORTED_TARGETS}
    components = {
        name: component_build_config(name) for name in _COMPONENT_NAMES
    }
    return {"targets": targets, "components": components}
