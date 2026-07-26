"""Build, smoke-test, verify, and package one native release candidate.

The command is deliberately target-bound: a target may only be built on a
matching host platform and architecture.  PyInstaller produces the application
and updater, the frozen application runs its non-GUI smoke test, and the final
package receives a checksum plus a machine-readable verification report.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import plistlib
import shutil
import stat
import struct
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Mapping, Sequence

from build_support.manifest import (
    ROOT,
    SUPPORTED_TARGETS,
    auto_target,
    canonical_machine,
    canonical_platform,
    component_output_name,
    target_config,
)
from build_support.metadata import write_build_identity
from package_metadata import write_windows_version_files
from product_identity import (
    APPLICATION_IDENTITY,
    PRODUCT_DISPLAY_NAME,
    PRODUCT_ID,
    PRODUCT_MANIFEST,
    PRODUCT_VERSION,
    UPDATER_IDENTITY,
)

ARTIFACTS_DIR = ROOT / "artifacts"
DIST_DIR = ROOT / "dist"
BUILD_DIR = ROOT / "build" / "pyinstaller"

_SUPPORT_FILES = (
    "README.md",
    "LICENSE",
    "config.template.json",
    "product_manifest.json",
    "VERSION_MANAGEMENT.md",
)


def _run(
    command: Sequence[str | os.PathLike[str]],
    *,
    env: Mapping[str, str] | None = None,
    cwd: Path = ROOT,
) -> None:
    rendered = [os.fspath(value) for value in command]
    print("+ " + " ".join(rendered), flush=True)
    subprocess.run(rendered, cwd=cwd, env=env, check=True)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_checksum(path: Path) -> Path:
    checksum = path.with_name(path.name + ".sha256")
    checksum.write_text(f"{_sha256(path)}  {path.name}\n", encoding="utf-8")
    return checksum


def _read_binary_architecture(path: Path, *, host_platform: str | None = None) -> str:
    """Return the native architecture encoded by a PE, ELF, or Mach-O file."""

    with path.open("rb") as stream:
        magic = stream.read(4)
        if magic[:2] == b"MZ":
            stream.seek(0x3C)
            offset_bytes = stream.read(4)
            if len(offset_bytes) != 4:
                raise RuntimeError(f"Truncated PE header: {path}")
            pe_offset = struct.unpack("<I", offset_bytes)[0]
            stream.seek(pe_offset)
            if stream.read(4) != b"PE\x00\x00":
                raise RuntimeError(f"Invalid PE header: {path}")
            machine_bytes = stream.read(2)
            if len(machine_bytes) != 2:
                raise RuntimeError(f"Truncated PE machine field: {path}")
            machine = struct.unpack("<H", machine_bytes)[0]
            return {0x8664: "x86_64", 0xAA64: "arm64"}.get(
                machine, f"pe-{machine:#x}"
            )

        if magic == b"\x7fELF":
            stream.seek(18)
            machine_bytes = stream.read(2)
            if len(machine_bytes) != 2:
                raise RuntimeError(f"Truncated ELF machine field: {path}")
            machine = struct.unpack("<H", machine_bytes)[0]
            return {62: "x86_64", 183: "arm64"}.get(machine, f"elf-{machine}")

    platform_name = canonical_platform(host_platform)
    if platform_name == "macos":
        result = subprocess.run(
            ["lipo", "-archs", str(path)],
            check=True,
            capture_output=True,
            text=True,
        )
        architectures = [canonical_machine(value) for value in result.stdout.split()]
        if not architectures:
            raise RuntimeError(f"lipo did not report an architecture: {path}")
        return "+".join(sorted(set(architectures)))

    raise RuntimeError(f"Unsupported executable format: {path}")


def _specs(target_name: str) -> tuple[str, str]:
    platform_name = str(target_config(target_name)["platform"])
    if platform_name == "windows":
        return "SMWC Downloader.spec", "SMWC Updater.spec"
    if platform_name == "linux":
        return "SMWC Downloader Linux.spec", "SMWC Updater Linux.spec"
    if platform_name == "macos":
        return "SMWC Downloader macOS.spec", "SMWC Updater macOS.spec"
    raise RuntimeError(f"Unsupported target platform: {platform_name}")


def _host_guard(
    target_name: str,
    *,
    host_platform: str | None = None,
    host_machine: str | None = None,
) -> None:
    target = target_config(target_name)
    actual = f"{canonical_platform(host_platform)}-{canonical_machine(host_machine)}"
    expected = f"{target['platform']}-{target['architecture']}"
    if actual != expected:
        raise RuntimeError(
            f"Target {target_name} must be built on {expected}; current host is {actual}"
        )


def _component_binary(component_name: str, target_name: str) -> Path:
    target = target_config(target_name)
    output_name = component_output_name(component_name, target_name)
    if target["platform"] == "windows":
        return DIST_DIR / f"{output_name}.exe"
    if target["platform"] == "linux":
        return DIST_DIR / output_name

    identity = (
        APPLICATION_IDENTITY if component_name == "application" else UPDATER_IDENTITY
    )
    return (
        DIST_DIR
        / str(identity["macos_bundle_name"])
        / "Contents"
        / "MacOS"
        / output_name
    )


def _main_binary(target_name: str) -> Path:
    return _component_binary("application", target_name)


def _updater_binary(target_name: str) -> Path:
    return _component_binary("updater", target_name)


def _copy_support_files(destination: Path, identity_path: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for relative in _SUPPORT_FILES:
        source = ROOT / relative
        if source.exists():
            shutil.copy2(source, destination / source.name)
    shutil.copy2(identity_path, destination / "build_identity.json")


def _package_windows(target_name: str, identity_path: Path, artifact_path: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="smwc-candidate-windows-") as temporary:
        stage = Path(temporary) / "SMWC Downloader"
        updater_directory = stage / "updater"
        stage.mkdir(parents=True)
        updater_directory.mkdir()
        shutil.copy2(_main_binary(target_name), stage / _main_binary(target_name).name)
        shutil.copy2(
            _updater_binary(target_name),
            updater_directory / _updater_binary(target_name).name,
        )
        _copy_support_files(stage, identity_path)
        with zipfile.ZipFile(
            artifact_path,
            "w",
            zipfile.ZIP_DEFLATED,
            compresslevel=9,
        ) as archive:
            for path in sorted(stage.rglob("*")):
                if path.is_file():
                    archive.write(path, path.relative_to(stage.parent))


_LINUX_EXECUTABLE_MEMBERS = frozenset(
    {
        "smwc-downloader/smwc-downloader",
        "smwc-downloader/updater/smwc-updater",
        "smwc-downloader/run-smwc-downloader.sh",
    }
)


def _linux_tar_filter(member: tarfile.TarInfo) -> tarfile.TarInfo:
    """Assign portable Unix modes independently of the host filesystem."""

    normalized_name = member.name.replace("\\", "/")
    if member.isdir():
        member.mode = 0o755
    elif normalized_name in _LINUX_EXECUTABLE_MEMBERS:
        member.mode = 0o755
    elif member.isfile():
        member.mode = 0o644
    return member


def _package_linux(target_name: str, identity_path: Path, artifact_path: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="smwc-candidate-linux-") as temporary:
        stage = Path(temporary) / "smwc-downloader"
        updater_directory = stage / "updater"
        stage.mkdir(parents=True)
        updater_directory.mkdir()
        main_destination = stage / _main_binary(target_name).name
        updater_destination = updater_directory / _updater_binary(target_name).name
        shutil.copy2(_main_binary(target_name), main_destination)
        shutil.copy2(_updater_binary(target_name), updater_destination)
        for executable in (main_destination, updater_destination):
            executable.chmod(
                executable.stat().st_mode
                | stat.S_IXUSR
                | stat.S_IXGRP
                | stat.S_IXOTH
            )
        _copy_support_files(stage, identity_path)
        launcher = stage / "run-smwc-downloader.sh"
        launcher.write_text(
            '#!/usr/bin/env sh\nDIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)\n'
            'exec "$DIR/smwc-downloader" "$@"\n',
            encoding="utf-8",
            newline="\n",
        )
        launcher.chmod(0o755)
        with tarfile.open(artifact_path, "w:gz") as archive:
            archive.add(
                stage,
                arcname=stage.name,
                recursive=True,
                filter=_linux_tar_filter,
            )


def _package_macos(target_name: str, identity_path: Path, artifact_path: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="smwc-candidate-macos-") as temporary:
        stage = Path(temporary) / "dmg"
        updater_directory = stage / "updater"
        stage.mkdir()
        updater_directory.mkdir()
        application_bundle = str(APPLICATION_IDENTITY["macos_bundle_name"])
        updater_bundle = str(UPDATER_IDENTITY["macos_bundle_name"])
        shutil.copytree(DIST_DIR / application_bundle, stage / application_bundle)
        shutil.copytree(
            DIST_DIR / updater_bundle,
            updater_directory / updater_bundle,
        )
        documentation = stage / "Documentation"
        _copy_support_files(documentation, identity_path)
        os.symlink("/Applications", stage / "Applications")
        _run(
            [
                "hdiutil",
                "create",
                "-volname",
                PRODUCT_DISPLAY_NAME,
                "-srcfolder",
                stage,
                "-ov",
                "-format",
                "UDZO",
                artifact_path,
            ]
        )


def _artifact_members(path: Path, artifact_type: str) -> list[str]:
    if artifact_type == "zip":
        with zipfile.ZipFile(path) as archive:
            return sorted(name for name in archive.namelist() if not name.endswith("/"))
    if artifact_type == "tar.gz":
        with tarfile.open(path, "r:gz") as archive:
            return sorted(member.name for member in archive.getmembers() if member.isfile())
    if artifact_type == "dmg":
        return []
    raise RuntimeError(f"Unsupported artifact type: {artifact_type}")


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"Expected a JSON object: {path}")
    return payload


def _validate_smoke_result(path: Path, target_name: str) -> dict[str, Any]:
    payload = _load_json(path)
    if payload.get("status") != "ok":
        raise RuntimeError(f"Smoke test did not report success: {path}")
    if payload.get("version") != PRODUCT_VERSION:
        raise RuntimeError("Smoke-test version does not match the product manifest")
    identity = payload.get("identity")
    if not isinstance(identity, dict) or identity.get("target") != target_name:
        raise RuntimeError(
            "Smoke-test build identity does not match the requested target"
        )
    if identity.get("product_id") != PRODUCT_ID:
        raise RuntimeError("Smoke-test product identity does not match the manifest")
    return payload


def _validate_windows_metadata(binary: Path) -> dict[str, Any]:
    command = [
        "powershell",
        "-NoProfile",
        "-NonInteractive",
        "-Command",
        (
            "$v=(Get-Item -LiteralPath $args[0]).VersionInfo; "
            "@{ProductName=$v.ProductName;ProductVersion=$v.ProductVersion;"
            "FileVersion=$v.FileVersion;OriginalFilename=$v.OriginalFilename}"
            "|ConvertTo-Json -Compress"
        ),
        str(binary),
    ]
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    payload = json.loads(result.stdout.strip())
    if payload.get("ProductName") != PRODUCT_DISPLAY_NAME:
        raise RuntimeError(
            f"Windows ProductName mismatch: {payload.get('ProductName')!r}"
        )
    for key in ("ProductVersion", "FileVersion"):
        if payload.get(key) != PRODUCT_VERSION:
            raise RuntimeError(f"Windows {key} mismatch: {payload.get(key)!r}")
    return {"windows_version_info": payload}


def _validate_macos_bundle(component_name: str) -> dict[str, Any]:
    identity = (
        APPLICATION_IDENTITY if component_name == "application" else UPDATER_IDENTITY
    )
    bundle_path = DIST_DIR / str(identity["macos_bundle_name"])
    info_path = bundle_path / "Contents" / "Info.plist"
    with info_path.open("rb") as stream:
        info = plistlib.load(stream)
    versions = PRODUCT_MANIFEST["versions"]
    if info.get("CFBundleShortVersionString") != versions["macos_short"]:
        raise RuntimeError(f"{component_name} macOS short version mismatch")
    if info.get("CFBundleVersion") != versions["macos_bundle"]:
        raise RuntimeError(f"{component_name} macOS bundle version mismatch")
    if info.get("CFBundleIdentifier") != identity["macos_bundle_identifier"]:
        raise RuntimeError(f"{component_name} macOS bundle identifier mismatch")
    return {
        "info_plist": str(info_path.relative_to(ROOT)),
        "bundle_identifier": info.get("CFBundleIdentifier"),
    }


def _write_verification(target_name: str, payload: Mapping[str, Any]) -> Path:
    path = ARTIFACTS_DIR / f"{target_name}-verification.json"
    path.write_text(
        json.dumps(dict(payload), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def build_candidate(target_name: str) -> dict[str, Any]:
    """Build and verify one candidate on its matching native host."""

    _host_guard(target_name)
    target = target_config(target_name)
    write_windows_version_files()
    identity_path = write_build_identity(target_name)

    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    shutil.rmtree(DIST_DIR, ignore_errors=True)
    shutil.rmtree(BUILD_DIR, ignore_errors=True)

    application_spec, updater_spec = _specs(target_name)
    environment = os.environ.copy()
    environment["SMWC_BUILD_TARGET"] = target_name
    common_arguments: list[str | os.PathLike[str]] = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--distpath",
        DIST_DIR,
        "--workpath",
        BUILD_DIR,
    ]
    _run([*common_arguments, application_spec], env=environment)
    _run([*common_arguments, updater_spec], env=environment)

    main_binary = _main_binary(target_name)
    updater_binary = _updater_binary(target_name)
    for path in (main_binary, updater_binary):
        if not path.exists():
            raise RuntimeError(f"Expected build output is missing: {path}")

    smoke_path = ARTIFACTS_DIR / f"{target_name}-smoke.json"
    smoke_path.unlink(missing_ok=True)
    smoke_environment = environment.copy()
    smoke_environment["SMWC_SMOKE_RESULT"] = str(smoke_path)
    _run([main_binary, "--smoke-test"], env=smoke_environment)
    smoke_payload = _validate_smoke_result(smoke_path, target_name)

    expected_architecture = canonical_machine(str(target["architecture"]))
    main_architecture = _read_binary_architecture(main_binary)
    updater_architecture = _read_binary_architecture(updater_binary)
    if main_architecture != expected_architecture:
        raise RuntimeError(
            "Application architecture mismatch: "
            f"expected {expected_architecture}, found {main_architecture}"
        )
    if updater_architecture != expected_architecture:
        raise RuntimeError(
            "Updater architecture mismatch: "
            f"expected {expected_architecture}, found {updater_architecture}"
        )

    artifact_path = ARTIFACTS_DIR / str(target["artifact_name"])
    artifact_path.unlink(missing_ok=True)
    if target["platform"] == "windows":
        _package_windows(target_name, identity_path, artifact_path)
    elif target["platform"] == "linux":
        _package_linux(target_name, identity_path, artifact_path)
    elif target["platform"] == "macos":
        _package_macos(target_name, identity_path, artifact_path)
    else:
        raise RuntimeError(f"Unsupported target platform: {target['platform']}")

    checksum_path = _write_checksum(artifact_path)
    verification: dict[str, Any] = {
        "status": "ok",
        "target": target_name,
        "product_id": PRODUCT_ID,
        "product": PRODUCT_DISPLAY_NAME,
        "version": PRODUCT_VERSION,
        "platform": target["platform"],
        "expected_architecture": expected_architecture,
        "application_architecture": main_architecture,
        "updater_architecture": updater_architecture,
        "application_binary": str(main_binary.relative_to(ROOT)),
        "updater_binary": str(updater_binary.relative_to(ROOT)),
        "artifact": artifact_path.name,
        "artifact_type": target["artifact_type"],
        "artifact_sha256": _sha256(artifact_path),
        "artifact_members": _artifact_members(
            artifact_path, str(target["artifact_type"])
        ),
        "checksum": checksum_path.name,
        "smoke_result": str(smoke_path.relative_to(ROOT)),
        "source_revision": smoke_payload["identity"].get(
            "source_revision", "unknown"
        ),
        "source_dirty": smoke_payload["identity"].get("source_dirty"),
    }
    if target["platform"] == "windows":
        verification.update(_validate_windows_metadata(main_binary))
    elif target["platform"] == "macos":
        verification["macos_application"] = _validate_macos_bundle("application")
        verification["macos_updater"] = _validate_macos_bundle("updater")

    verification_path = _write_verification(target_name, verification)
    print(json.dumps(verification, indent=2, sort_keys=True))
    print(f"Verification report: {verification_path}")
    return verification


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--target",
        choices=SUPPORTED_TARGETS,
        default=None,
        help="Native target to build; defaults to the current host target.",
    )
    arguments = parser.parse_args(argv)
    build_candidate(arguments.target or auto_target())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
