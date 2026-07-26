"""Generate package version metadata from product_manifest.json."""
from __future__ import annotations

from package_metadata import write_windows_version_files
from product_identity import PRODUCT_VERSION


def generate_version_txt() -> None:
    """Generate application and updater Windows version metadata files."""

    paths = write_windows_version_files()
    print(f"Generated package metadata for {PRODUCT_VERSION}:")
    for component_name, path in paths.items():
        print(f"  {component_name}: {path}")


if __name__ == "__main__":
    generate_version_txt()
