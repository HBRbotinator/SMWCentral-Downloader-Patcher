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


def canonical_machine(value: str | None = None) -> str:
    """Normalize common architecture aliases used by Python and build tools."""

    raw = (value or platform.machine()).strip().casefold()
    aliases = {
        "amd64": "x86_64",
        "x64": "x86_64",
        "x86-64": "x86_64",
        "aarch64": "arm64",
    }
    return aliases.get(raw, raw)


def canonical_platform(value: str | None = None) -> str:
    """Normalize ``sys.platform``/``platform.system`` style names."""

    raw = (value or sys.platform).strip().casefold()
    if raw.startswith("win"):
        return "windows"
    if raw == "darwin" or raw.startswith("mac"):
        return "macos"
    if raw.startswith("linux"):
        return "linux"
    return raw


def target_config(target_name: str) -> dict[str, Any]:
    """Return an isolated build-target definition."""

    target = PRODUCT_MANIFEST["targets"].get(target_name)
    if not isinstance(target, dict):
        raise ProductManifestError(f"Unknown build target: {target_name}")
    return deepcopy(target)


def _string_list(value: object, context: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ProductManifestError(f"{context} must contain strings")
    return list(value)


def _package_resource_list(value: object, context: str) -> list[dict[str, str]]:
    if not isinstance(value, list):
        raise ProductManifestError(f"{context} must be a list")

    normalized: list[dict[str, str]] = []
    for index, item in enumerate(value):
        item_context = f"{context}[{index}]"
        if not isinstance(item, Mapping):
            raise ProductManifestError(f"{item_context} must be an object")
        package_name = item.get("package")
        suffix = item.get("suffix")
        if not isinstance(package_name, str) or not package_name:
            raise ProductManifestError(f"{item_context}.package must be a non-empty string")
        if not isinstance(suffix, str) or not suffix:
            raise ProductManifestError(f"{item_context}.suffix must be a non-empty string")
        normalized.append({"package": package_name, "suffix": suffix})
    return normalized


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
    if not isinstance(console, bool):
        raise ProductManifestError(f"build.{component_name}.console must be a boolean")
    if not isinstance(resources, list):
        raise ProductManifestError(f"build.{component_name}.resources must be a list")

    hidden = _string_list(
        config.get("hidden_imports"),
        f"build.{component_name}.hidden_imports",
    )
    package_data = _string_list(
        config.get("package_data"),
        f"build.{component_name}.package_data",
    )
    required_runtime_resources = _string_list(
        config.get("required_runtime_resources", []),
        f"build.{component_name}.required_runtime_resources",
    )
    required_package_resources = _package_resource_list(
        config.get("required_package_resources", []),
        f"build.{component_name}.required_package_resources",
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
        "hidden_imports": hidden,
        "package_data": package_data,
        "required_runtime_resources": required_runtime_resources,
        "required_package_resources": required_package_resources,
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


def required_runtime_resources(component_name: str) -> list[str]:
    return list(component_build_config(component_name)["required_runtime_resources"])


def required_package_resources(component_name: str) -> list[dict[str, str]]:
    return deepcopy(component_build_config(component_name)["required_package_resources"])


def auto_target(
    platform_name: str | None = None,
    machine_name: str | None = None,
) -> str:
    """Resolve the supported native target for the current host."""

    platform_value = canonical_platform(platform_name)
    machine_value = canonical_machine(machine_name)
    target = f"{platform_value}-{machine_value}"
    if target not in SUPPORTED_TARGETS:
        raise ProductManifestError(
            f"This host does not map to a supported build target: {target}. "
            f"Supported targets: {', '.join(SUPPORTED_TARGETS)}"
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
