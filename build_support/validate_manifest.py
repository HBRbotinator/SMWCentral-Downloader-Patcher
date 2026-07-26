"""Validate product identity, build configuration, and generated metadata."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from build_support.manifest import ROOT, validate_build_manifest
from package_metadata import windows_version_text
from product_identity import PRODUCT_MANIFEST


def validate_manifest_state(root: Path = ROOT) -> dict[str, Any]:
    """Return a machine-readable snapshot after validating committed metadata."""

    build = validate_build_manifest()
    expected_files = {
        "application": (root / "version.txt", windows_version_text("application")),
        "updater": (root / "updater_version.txt", windows_version_text("updater")),
    }
    metadata_files: dict[str, str] = {}
    for component, (path, expected) in expected_files.items():
        if not path.is_file():
            raise RuntimeError(f"Generated metadata file is missing: {path.name}")
        actual = path.read_text(encoding="utf-8")
        if actual != expected:
            raise RuntimeError(
                f"Generated metadata is stale: {path.name}; run update_version.py"
            )
        metadata_files[component] = path.name

    product = PRODUCT_MANIFEST["product"]
    return {
        "status": "ok",
        "product_id": product["id"],
        "product_name": product["display_name"],
        "version": product["version"],
        "release_channel": product["release_channel"],
        "targets": sorted(build["targets"]),
        "components": sorted(build["components"]),
        "metadata_files": metadata_files,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Emit JSON output")
    args = parser.parse_args(argv)
    result = validate_manifest_state()
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(
            f"Manifest OK: {result['product_name']} {result['version']} "
            f"({len(result['targets'])} targets)"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
