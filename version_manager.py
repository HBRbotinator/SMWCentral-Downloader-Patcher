"""Compatibility accessors backed by the authoritative product manifest."""
from __future__ import annotations

from product_identity import PRODUCT_VERSION, VERSION, WINDOWS_VERSION_TUPLE


def get_version() -> str:
    """Return the display version, including the leading ``v``."""

    return VERSION


def get_version_number() -> str:
    """Return the manifest version without the leading ``v``."""

    return PRODUCT_VERSION


def get_version_tuple() -> tuple[int, int, int, int]:
    """Return the four-part numeric Windows version tuple."""

    return WINDOWS_VERSION_TUPLE


def get_version_string() -> str:
    """Return the manifest version for textual package metadata."""

    return PRODUCT_VERSION


def get_package_name() -> str:
    """Return the legacy package stem with the authoritative version."""

    return f"SMWC_Downloader_{VERSION}"


def get_zip_name() -> str:
    """Return the legacy ZIP name with the authoritative version."""

    return f"{get_package_name()}.zip"


if __name__ == "__main__":
    print(f"Version: {get_version()}")
    print(f"Version Number: {get_version_number()}")
    print(f"Version Tuple: {get_version_tuple()}")
    print(f"Version String: {get_version_string()}")
    print(f"Package Name: {get_package_name()}")
    print(f"Zip Name: {get_zip_name()}")
