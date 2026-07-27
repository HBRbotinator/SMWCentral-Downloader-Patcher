"""Validate complete native candidate evidence before final publication."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping

from build_support.manifest import SUPPORTED_TARGETS, canonical_machine, target_config
from product_identity import (
    PRODUCT_DISPLAY_NAME,
    PRODUCT_ID,
    PRODUCT_VERSION,
    RELEASE_CHANNEL,
)

_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
_STABLE_TAG_PATTERN = re.compile(r"^v[0-9]+\.[0-9]+\.[0-9]+$")
_STABLE_CHANNELS = frozenset({"stable", "release"})


class ReleaseGateError(RuntimeError):
    """Raised when final-release evidence is incomplete or inconsistent."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _require_mapping(value: object, context: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ReleaseGateError(f"{context} must contain a JSON object")
    return value


def _load_json(path: Path) -> Mapping[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReleaseGateError(f"Unable to read valid JSON from {path}: {exc}") from exc
    return _require_mapping(payload, str(path))


def _find_unique(root: Path, filename: str) -> Path:
    matches = sorted(path for path in root.rglob(filename) if path.is_file())
    if not matches:
        raise ReleaseGateError(f"Required release input is missing: {filename}")
    if len(matches) != 1:
        rendered = ", ".join(str(path) for path in matches)
        raise ReleaseGateError(
            f"Release input {filename!r} must appear exactly once; found {rendered}"
        )
    return matches[0]


def _require_equal(
    payload: Mapping[str, Any],
    key: str,
    expected: object,
    context: str,
) -> None:
    actual = payload.get(key)
    if actual != expected:
        raise ReleaseGateError(
            f"{context}.{key} must be {expected!r}, found {actual!r}"
        )


def _validate_revision(value: str, context: str) -> str:
    normalized = value.strip().casefold()
    if not _SHA_PATTERN.fullmatch(normalized):
        raise ReleaseGateError(
            f"{context} must be a full 40-character hexadecimal Git revision"
        )
    return normalized


def validate_release_tag(
    tag: str,
    *,
    version: str = PRODUCT_VERSION,
    release_channel: str = RELEASE_CHANNEL,
) -> str:
    """Require an exact stable tag for a stable-channel product manifest."""

    normalized = tag.strip()
    if not _STABLE_TAG_PATTERN.fullmatch(normalized):
        raise ReleaseGateError(
            f"Final release tag must use vMAJOR.MINOR.PATCH, found {tag!r}"
        )
    expected = f"v{version}"
    if normalized != expected:
        raise ReleaseGateError(
            f"Release tag {normalized!r} does not match manifest version {version!r}"
        )
    if release_channel.casefold() not in _STABLE_CHANNELS:
        raise ReleaseGateError(
            "Final publication is disabled for manifest release channel "
            f"{release_channel!r}"
        )
    return normalized


def _parse_checksum(path: Path, artifact_name: str) -> str:
    try:
        lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines()]
    except (OSError, UnicodeDecodeError) as exc:
        raise ReleaseGateError(f"Unable to read checksum file {path}: {exc}") from exc
    non_empty = [line for line in lines if line]
    if len(non_empty) != 1:
        raise ReleaseGateError(f"Checksum file {path} must contain exactly one entry")
    parts = non_empty[0].split(maxsplit=1)
    if len(parts) != 2:
        raise ReleaseGateError(f"Checksum file {path} has an invalid entry")
    digest, recorded_name = parts
    recorded_name = recorded_name.lstrip("*")
    if not re.fullmatch(r"[0-9a-fA-F]{64}", digest):
        raise ReleaseGateError(f"Checksum file {path} does not contain SHA-256")
    if recorded_name != artifact_name:
        raise ReleaseGateError(
            f"Checksum file {path} names {recorded_name!r}, expected {artifact_name!r}"
        )
    return digest.casefold()


def _validate_smoke(
    path: Path,
    *,
    target_name: str,
    target: Mapping[str, Any],
    expected_revision: str,
) -> Mapping[str, Any]:
    smoke = _load_json(path)
    context = path.name
    _require_equal(smoke, "status", "ok", context)
    _require_equal(smoke, "product", PRODUCT_DISPLAY_NAME, context)
    _require_equal(smoke, "version", PRODUCT_VERSION, context)
    identity = _require_mapping(smoke.get("identity"), f"{context}.identity")
    expected_identity = {
        "product_id": PRODUCT_ID,
        "product_name": PRODUCT_DISPLAY_NAME,
        "version": PRODUCT_VERSION,
        "release_channel": RELEASE_CHANNEL,
        "target": target_name,
        "platform": target["platform"],
        "architecture": target["architecture"],
        "artifact_name": target["artifact_name"],
        "source_revision": expected_revision,
        "source_dirty": False,
    }
    for key, expected in expected_identity.items():
        _require_equal(identity, key, expected, f"{context}.identity")
    return smoke


def _validate_verification(
    path: Path,
    *,
    target_name: str,
    target: Mapping[str, Any],
    expected_revision: str,
    artifact_digest: str,
    checksum_name: str,
) -> Mapping[str, Any]:
    verification = _load_json(path)
    context = path.name
    expected_architecture = canonical_machine(str(target["architecture"]))
    expected_values = {
        "status": "ok",
        "target": target_name,
        "product_id": PRODUCT_ID,
        "product": PRODUCT_DISPLAY_NAME,
        "version": PRODUCT_VERSION,
        "platform": target["platform"],
        "expected_architecture": expected_architecture,
        "application_architecture": expected_architecture,
        "updater_architecture": expected_architecture,
        "artifact": target["artifact_name"],
        "artifact_type": target["artifact_type"],
        "artifact_sha256": artifact_digest,
        "checksum": checksum_name,
        "source_revision": expected_revision,
        "source_dirty": False,
    }
    for key, expected in expected_values.items():
        _require_equal(verification, key, expected, context)
    return verification


def validate_release_inputs(
    artifacts_directory: str | Path,
    *,
    expected_revision: str,
    expected_tag: str | None = None,
) -> dict[str, Any]:
    """Validate one complete, same-revision evidence set for every target."""

    root = Path(artifacts_directory)
    if not root.is_dir():
        raise ReleaseGateError(f"Release input directory does not exist: {root}")
    revision = _validate_revision(expected_revision, "Expected source revision")
    if expected_tag is not None:
        validate_release_tag(expected_tag)

    target_results: dict[str, dict[str, Any]] = {}
    for target_name in SUPPORTED_TARGETS:
        target = target_config(target_name)
        artifact_name = str(target["artifact_name"])
        checksum_name = artifact_name + ".sha256"
        smoke_name = f"{target_name}-smoke.json"
        verification_name = f"{target_name}-verification.json"

        artifact_path = _find_unique(root, artifact_name)
        checksum_path = _find_unique(root, checksum_name)
        smoke_path = _find_unique(root, smoke_name)
        verification_path = _find_unique(root, verification_name)
        if artifact_path.stat().st_size <= 0:
            raise ReleaseGateError(f"Release artifact is empty: {artifact_path}")

        artifact_digest = _sha256(artifact_path)
        recorded_digest = _parse_checksum(checksum_path, artifact_name)
        if recorded_digest != artifact_digest:
            raise ReleaseGateError(
                f"Checksum mismatch for {artifact_name}: "
                f"expected {recorded_digest}, calculated {artifact_digest}"
            )

        _validate_smoke(
            smoke_path,
            target_name=target_name,
            target=target,
            expected_revision=revision,
        )
        _validate_verification(
            verification_path,
            target_name=target_name,
            target=target,
            expected_revision=revision,
            artifact_digest=artifact_digest,
            checksum_name=checksum_name,
        )
        target_results[target_name] = {
            "platform": target["platform"],
            "architecture": canonical_machine(str(target["architecture"])),
            "artifact": artifact_name,
            "artifact_sha256": artifact_digest,
            "checksum": checksum_name,
            "smoke_report": smoke_name,
            "verification_report": verification_name,
        }

    return {
        "schema_version": 1,
        "status": "ok",
        "product_id": PRODUCT_ID,
        "product": PRODUCT_DISPLAY_NAME,
        "version": PRODUCT_VERSION,
        "release_channel": RELEASE_CHANNEL,
        "source_revision": revision,
        "targets": target_results,
    }


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _print_targets() -> int:
    print("\n".join(SUPPORTED_TARGETS))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts-dir", type=Path)
    parser.add_argument("--expected-revision")
    parser.add_argument("--expected-tag")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--print-targets", action="store_true")
    args = parser.parse_args(argv)

    if args.print_targets:
        if any(
            value is not None
            for value in (
                args.artifacts_dir,
                args.expected_revision,
                args.expected_tag,
                args.output,
            )
        ):
            parser.error("--print-targets cannot be combined with validation options")
        return _print_targets()

    if args.artifacts_dir is None or args.expected_revision is None:
        parser.error("--artifacts-dir and --expected-revision are required")
    payload = validate_release_inputs(
        args.artifacts_dir,
        expected_revision=args.expected_revision,
        expected_tag=args.expected_tag,
    )
    if args.output is not None:
        _write_json(args.output, payload)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
