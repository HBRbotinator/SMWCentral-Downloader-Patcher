"""Shared PyInstaller definitions for every supported package target.

The checked-in spec files are deliberately thin wrappers. Product names,
versions, resources, hidden imports, and target architecture are resolved from
``product_manifest.json`` through this module.
"""
from __future__ import annotations

from typing import Any, MutableMapping

from build_support.manifest import (
    ROOT,
    build_resources,
    component_build_config,
    component_output_name,
    hidden_imports,
    package_data_packages,
    target_config,
)
from build_support.metadata import write_build_identity
from package_metadata import macos_bundle_metadata
from product_identity import APPLICATION_IDENTITY, UPDATER_IDENTITY


def _pyinstaller_symbols(namespace: MutableMapping[str, Any]) -> tuple[Any, Any, Any, Any]:
    try:
        return namespace["Analysis"], namespace["PYZ"], namespace["EXE"], namespace["BUNDLE"]
    except KeyError as exc:
        raise RuntimeError("This module must be called from a PyInstaller spec file") from exc


def _datas(component_name: str, target_name: str) -> list[tuple[str, str]]:
    values = build_resources(component_name)
    if package_data_packages(component_name):
        from PyInstaller.utils.hooks import collect_data_files

        for package_name in package_data_packages(component_name):
            values.extend(collect_data_files(package_name))
    values.append((str(write_build_identity(target_name)), "."))
    return values


def _target_arch(target_name: str) -> str | None:
    target = target_config(target_name)
    return str(target["architecture"]) if target["platform"] == "macos" else None


def _icon_path(platform_name: str) -> str | None:
    if platform_name == "windows":
        return str(ROOT / "assets" / "icon.ico")
    if platform_name == "macos":
        return str(ROOT / "assets" / "icon.icns")
    return None


def _windows_version_path(component_name: str, platform_name: str) -> str | None:
    if platform_name != "windows":
        return None
    filename = "version.txt" if component_name == "application" else "updater_version.txt"
    return str(ROOT / filename)


def _analysis(
    namespace: MutableMapping[str, Any],
    component_name: str,
    target_name: str,
) -> tuple[Any, Any]:
    Analysis, PYZ, _, _ = _pyinstaller_symbols(namespace)
    identity = (
        APPLICATION_IDENTITY if component_name == "application" else UPDATER_IDENTITY
    )
    analysis = Analysis(
        [str(ROOT / identity["entry_point"])],
        pathex=[str(ROOT)],
        binaries=[],
        datas=_datas(component_name, target_name),
        hiddenimports=hidden_imports(component_name),
        hookspath=[],
        hooksconfig={},
        runtime_hooks=[],
        excludes=[],
        noarchive=False,
        optimize=0,
    )
    return analysis, PYZ(analysis.pure)


def _exe(
    namespace: MutableMapping[str, Any],
    component_name: str,
    target_name: str,
    analysis: Any,
    pyz: Any,
) -> Any:
    _, _, EXE, _ = _pyinstaller_symbols(namespace)
    target = target_config(target_name)
    platform_name = str(target["platform"])
    return EXE(
        pyz,
        analysis.scripts,
        analysis.binaries,
        analysis.datas,
        [],
        name=component_output_name(component_name, target_name),
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        upx_exclude=[],
        runtime_tmpdir=None,
        console=bool(component_build_config(component_name)["console"]),
        disable_windowed_traceback=False,
        argv_emulation=platform_name == "macos",
        target_arch=_target_arch(target_name),
        codesign_identity=None,
        entitlements_file=None,
        icon=_icon_path(platform_name),
        version=_windows_version_path(component_name, platform_name),
    )


def _bundle(
    namespace: MutableMapping[str, Any],
    component_name: str,
    target_name: str,
    exe: Any,
) -> None:
    target = target_config(target_name)
    if target["platform"] != "macos":
        return

    _, _, _, BUNDLE = _pyinstaller_symbols(namespace)
    metadata = macos_bundle_metadata(component_name)
    info_plist: dict[str, Any] = {
        "CFBundleDisplayName": metadata["display_name"],
        "CFBundleName": metadata["display_name"],
        "CFBundleShortVersionString": metadata["short_version"],
        "CFBundleVersion": metadata["bundle_version"],
        "LSBackgroundOnly": False,
        "NSHighResolutionCapable": True,
    }
    if component_name == "application":
        info_plist.update(
            {
                "LSApplicationCategoryType": "public.app-category.utilities",
                "NSAppTransportSecurity": {"NSAllowsArbitraryLoads": True},
            }
        )
    else:
        info_plist["NSRequiresAquaSystemAppearance"] = False

    BUNDLE(
        exe,
        name=metadata["bundle_name"],
        icon=str(ROOT / "assets" / "icon.icns"),
        bundle_identifier=metadata["bundle_identifier"],
        version=metadata["bundle_version"],
        info_plist=info_plist,
    )


def build_component(
    namespace: MutableMapping[str, Any],
    component_name: str,
    target_name: str,
) -> None:
    """Build a manifest-defined component for one target."""

    target_config(target_name)
    analysis, pyz = _analysis(namespace, component_name, target_name)
    exe = _exe(namespace, component_name, target_name, analysis, pyz)
    _bundle(namespace, component_name, target_name, exe)


def build_application(namespace: MutableMapping[str, Any], target_name: str) -> None:
    build_component(namespace, "application", target_name)


def build_updater(namespace: MutableMapping[str, Any], target_name: str) -> None:
    build_component(namespace, "updater", target_name)
