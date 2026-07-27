"""Frozen/source startup smoke test used by candidate packaging and CI."""
from __future__ import annotations

import importlib
import importlib.resources
import json
import os
import platform
import sys
from pathlib import Path
from typing import Any, Iterable

from build_support.manifest import (
    canonical_machine,
    canonical_platform,
    required_package_resources,
)
from product_identity import (
    PRODUCT_DISPLAY_NAME,
    PRODUCT_VERSION,
    load_build_identity,
    validate_runtime_resources,
    validate_supported_python,
)

SMOKE_MODULES = (
    "api_pipeline",
    "config_manager",
    "hack_data_manager",
    "save_sync",
    "ui",
    "ui.layout",
    "ui.pages.collection_page",
    "ui.pages.download_page",
    "ui.pages.settings_page",
    "ui.save_sync_dialog",
    "PIL.Image",
    "PIL.ImageTk",
    "PIL.ImageDraw",
    "PIL.ImageFont",
    "sv_ttk",
)


def _iter_resources(node: Any) -> Iterable[Any]:
    if node.is_file():
        yield node
        return
    if node.is_dir():
        for child in node.iterdir():
            yield from _iter_resources(child)


def _validate_package_resources() -> list[str]:
    validated: list[str] = []
    for requirement in required_package_resources("application"):
        package_name = requirement["package"]
        suffix = requirement["suffix"]
        root = importlib.resources.files(package_name)
        if not any(item.name.endswith(suffix) for item in _iter_resources(root)):
            raise RuntimeError(
                f"Required package resource {suffix!r} is missing from {package_name}"
            )
        validated.append(f"{package_name}:*{suffix}")
    return validated


def _assert_frozen_target(identity: dict[str, Any]) -> None:
    if not bool(getattr(sys, "frozen", False)):
        return
    expected_platform = str(identity.get("platform", ""))
    expected_architecture = canonical_machine(str(identity.get("architecture", "")))
    actual_platform = canonical_platform()
    actual_architecture = canonical_machine()
    if actual_platform != expected_platform or actual_architecture != expected_architecture:
        raise RuntimeError(
            "Frozen target mismatch: "
            f"expected {expected_platform}/{expected_architecture}, "
            f"running {actual_platform}/{actual_architecture}"
        )


def run_runtime_smoke() -> int:
    """Validate imports, resources and embedded identity without opening the GUI."""

    validate_supported_python()
    resources = validate_runtime_resources("application")
    package_resources = _validate_package_resources()
    imported: list[str] = []
    for module_name in SMOKE_MODULES:
        importlib.import_module(module_name)
        imported.append(module_name)

    identity = load_build_identity()
    _assert_frozen_target(identity)
    result = {
        "status": "ok",
        "product": PRODUCT_DISPLAY_NAME,
        "version": PRODUCT_VERSION,
        "identity": identity,
        "resources": resources,
        "package_resources": package_resources,
        "imports": imported,
        "python": platform.python_version(),
    }
    output = json.dumps(result, indent=2, sort_keys=True)
    result_path = os.environ.get("SMWC_SMOKE_RESULT", "").strip()
    if result_path:
        path = Path(result_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(output + "\n", encoding="utf-8")
    print("SMWC_CANDIDATE_SMOKE_OK")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(run_runtime_smoke())
