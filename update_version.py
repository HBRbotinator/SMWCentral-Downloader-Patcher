"""Update the development version in product_manifest.json."""
from __future__ import annotations

import argparse
import json
import re
import tempfile
from pathlib import Path
from typing import Any

from package_metadata import write_windows_version_files
from product_identity import load_product_manifest

ROOT = Path(__file__).resolve().parent
MANIFEST_PATH = ROOT / "product_manifest.json"
_VERSION_PATTERN = re.compile(r"(\d+)\.(\d+)\.(\d+)-dev\.(\d+)")


def _normalized_version(value: str) -> tuple[str, tuple[int, int, int, int]]:
    normalized = value.strip().removeprefix("v")
    match = _VERSION_PATTERN.fullmatch(normalized)
    if not match:
        raise ValueError(
            "Development versions must use MAJOR.MINOR.PATCH-dev.BUILD, "
            "for example 5.1.0-dev.2"
        )
    parts = tuple(int(item) for item in match.groups())
    return normalized, parts


def _updated_payload(payload: dict[str, Any], version: str) -> dict[str, Any]:
    normalized, (major, minor, patch, build) = _normalized_version(version)
    previous_version = str(payload["product"]["version"])

    payload["product"]["version"] = normalized
    payload["product"]["pep440_version"] = f"{major}.{minor}.{patch}.dev{build}"
    payload["versions"]["windows_numeric"] = [major, minor, patch, build]
    payload["versions"]["macos_short"] = f"{major}.{minor}.{patch}"
    payload["versions"]["macos_bundle"] = f"{major}.{minor}.{patch}.{build}"

    for target in payload["targets"].values():
        artifact_name = str(target["artifact_name"])
        if previous_version not in artifact_name:
            raise ValueError(
                "Target artifact name does not contain the current product version: "
                f"{artifact_name!r}"
            )
        target["artifact_name"] = artifact_name.replace(
            previous_version,
            normalized,
            1,
        )
    return payload


def _validate_payload(payload: dict[str, Any], parent_directory: Path) -> None:
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        suffix=".json",
        prefix="product-manifest-",
        dir=parent_directory,
        delete=False,
    ) as temporary_file:
        temporary_path = Path(temporary_file.name)
        json.dump(payload, temporary_file, indent=2)
        temporary_file.write("\n")
    try:
        load_product_manifest(temporary_path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _write_manifest_atomically(path: Path, payload: dict[str, Any]) -> None:
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    temporary_path.write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    temporary_path.replace(path)


def update_version(
    new_version: str,
    manifest_path: str | Path = MANIFEST_PATH,
    metadata_directory: str | Path | None = None,
) -> str:
    """Update and validate the manifest, then regenerate package metadata."""

    path = Path(manifest_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    updated = _updated_payload(payload, new_version)
    _validate_payload(updated, path.parent)
    _write_manifest_atomically(path, updated)
    output_directory = Path(metadata_directory) if metadata_directory else path.parent
    write_windows_version_files(output_directory, updated)
    return str(updated["product"]["version"])


def show_current_version(manifest_path: str | Path = MANIFEST_PATH) -> str:
    """Print and return the current authoritative product version."""

    payload = load_product_manifest(manifest_path)
    version = str(payload["product"]["version"])
    print(f"Current version: {version}")
    return version


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "version",
        nargs="?",
        help="New development version, for example 5.1.0-dev.2",
    )
    args = parser.parse_args(argv)
    if args.version:
        version = update_version(args.version)
        print(f"Updated authoritative version to {version}.")
    else:
        show_current_version()
        print("To update it, run: python update_version.py 5.1.0-dev.2")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
