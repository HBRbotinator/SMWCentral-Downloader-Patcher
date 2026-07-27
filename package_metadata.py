"""Generate package metadata from the authoritative product manifest.

The module is intentionally independent of PyInstaller. Build specifications,
release scripts, and validation tests can consume the same metadata without
copying version strings or platform-specific product names.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

from product_identity import PRODUCT_MANIFEST

ROOT = Path(__file__).resolve().parent
_COMPONENTS = ("application", "updater")


def _manifest(payload: Mapping[str, Any] | None) -> Mapping[str, Any]:
    return payload if payload is not None else PRODUCT_MANIFEST


def _component(
    component_name: str,
    payload: Mapping[str, Any] | None = None,
) -> Mapping[str, Any]:
    if component_name not in _COMPONENTS:
        raise ValueError(
            f"Unknown component {component_name!r}; expected one of {', '.join(_COMPONENTS)}"
        )
    manifest = _manifest(payload)
    component = manifest["components"][component_name]
    if not isinstance(component, Mapping):
        raise ValueError(f"Manifest component {component_name!r} must be an object")
    return component


def _unicode_literal(value: object) -> str:
    """Return an escaped unicode literal for a PyInstaller version resource."""

    return "u" + repr(str(value))


def windows_version_text(
    component_name: str = "application",
    payload: Mapping[str, Any] | None = None,
) -> str:
    """Return PyInstaller-compatible Windows version metadata text."""

    manifest = _manifest(payload)
    product = manifest["product"]
    component = _component(component_name, manifest)
    version_tuple = tuple(int(value) for value in manifest["versions"]["windows_numeric"])
    product_name = str(product["display_name"])
    component_name_windows = str(component["windows_name"])
    description = product_name if component_name == "application" else f"{product_name} Updater"
    executable_name = f"{component_name_windows}.exe"

    return f"""# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={version_tuple!r},
    prodvers={version_tuple!r},
    mask=0x3f,
    flags=0x0,
    OS=0x4,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        u'040904B0',
        [
          StringStruct(u'CompanyName', {_unicode_literal(product['publisher'])}),
          StringStruct(u'FileDescription', {_unicode_literal(description)}),
          StringStruct(u'FileVersion', {_unicode_literal(product['version'])}),
          StringStruct(u'InternalName', {_unicode_literal(component_name_windows)}),
          StringStruct(u'LegalCopyright', {_unicode_literal(product['copyright'])}),
          StringStruct(u'OriginalFilename', {_unicode_literal(executable_name)}),
          StringStruct(u'ProductName', {_unicode_literal(product_name)}),
          StringStruct(u'ProductVersion', {_unicode_literal(product['version'])})
        ]
      )
    ]),
    VarFileInfo([VarStruct(u'Translation', [1033, 1200])])
  ]
)
"""


def macos_bundle_metadata(
    component_name: str = "application",
    payload: Mapping[str, Any] | None = None,
) -> dict[str, str]:
    """Return normalized macOS bundle metadata for a product component."""

    manifest = _manifest(payload)
    product = manifest["product"]
    component = _component(component_name, manifest)
    display_name = (
        str(product["display_name"])
        if component_name == "application"
        else str(component["macos_bundle_name"]).removesuffix(".app")
    )
    return {
        "bundle_name": str(component["macos_bundle_name"]),
        "bundle_identifier": str(component["macos_bundle_identifier"]),
        "display_name": display_name,
        "short_version": str(manifest["versions"]["macos_short"]),
        "bundle_version": str(manifest["versions"]["macos_bundle"]),
    }


def package_metadata(payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Return an isolated package metadata snapshot for all components."""

    manifest = _manifest(payload)
    return {
        "product": deepcopy(manifest["product"]),
        "versions": deepcopy(manifest["versions"]),
        "application": {
            "windows_version_text": windows_version_text("application", manifest),
            "macos": macos_bundle_metadata("application", manifest),
        },
        "updater": {
            "windows_version_text": windows_version_text("updater", manifest),
            "macos": macos_bundle_metadata("updater", manifest),
        },
    }


def write_windows_version_files(
    output_directory: str | Path = ROOT,
    payload: Mapping[str, Any] | None = None,
) -> dict[str, Path]:
    """Write deterministic application and updater Windows metadata files."""

    directory = Path(output_directory)
    directory.mkdir(parents=True, exist_ok=True)
    paths = {
        "application": directory / "version.txt",
        "updater": directory / "updater_version.txt",
    }
    paths["application"].write_text(
        windows_version_text("application", payload),
        encoding="utf-8",
        newline="\n",
    )
    paths["updater"].write_text(
        windows_version_text("updater", payload),
        encoding="utf-8",
        newline="\n",
    )
    return paths
