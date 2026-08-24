"""Local ROM discovery and source-neutral candidate construction."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from collection_ingestion import (
    CollectionCandidate,
    IngestionSource,
    RomFileEvidence,
)
from rom_title_matching import (
    CatalogueEntry,
    CatalogueMatcher,
    CatalogueMatchResult,
    clean_title_for_match,
    extract_explicit_smwc_submission_ids,
    infer_difficulty_hint,
    is_probable_base_rom,
)

ROM_EXTENSIONS = frozenset({".sfc", ".smc"})
_HASH_CHUNK_SIZE = 1024 * 1024


class RomIngestionError(RuntimeError):
    """Raised when a local ROM scan cannot be represented safely."""


@dataclass(frozen=True)
class RomDuplicateGroup:
    """Local paths whose current file contents are byte-identical."""

    sha256: str
    paths: tuple[str, ...]


@dataclass(frozen=True)
class RomLibraryScan:
    """Immutable result of one recursive ROM-folder scan."""

    root: str
    roms: tuple[RomFileEvidence, ...]
    duplicate_groups: tuple[RomDuplicateGroup, ...]


@dataclass(frozen=True)
class RomCatalogueResolution:
    """Catalogue suggestion for one scanned ROM."""

    rom: RomFileEvidence
    selected: CatalogueEntry | None
    suggestion: CatalogueEntry | None
    confidence: float
    classification: str
    auto_selected: bool
    evidence_title: str
    manual_import_available: bool = True


def _hash_stable_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        before = path.stat()
        while True:
            chunk = handle.read(_HASH_CHUNK_SIZE)
            if not chunk:
                break
            digest.update(chunk)
        after = path.stat()

    if (
        before.st_size != after.st_size
        or before.st_mtime_ns != after.st_mtime_ns
    ):
        raise RomIngestionError(
            f"ROM changed while it was being scanned: {path.name}"
        )
    return digest.hexdigest(), after.st_size


def _folder_title_hint(
    path: Path,
    root: Path,
    known_difficulties: Iterable[str],
) -> str:
    parent = path.parent
    if parent == root or parent == parent.parent:
        return ""
    cleaned = clean_title_for_match(parent.name)
    if not cleaned:
        return ""
    folder_key = cleaned.casefold()
    stripped_key = folder_key
    while stripped_key and stripped_key[0].isdigit():
        stripped_key = stripped_key[1:]
    stripped_key = stripped_key.lstrip(" ._-")
    known = {
        str(item).strip().casefold()
        for item in known_difficulties
        if str(item).strip()
    }
    inferred_difficulty = infer_difficulty_hint(
        str(path),
        known_difficulties,
    )
    if stripped_key in known or (
        inferred_difficulty
        and stripped_key == clean_title_for_match(inferred_difficulty).casefold()
    ):
        return ""
    if folder_key in {
        "rom",
        "roms",
        "hack",
        "hacks",
        "smw",
        "super mario world",
        "kaizo",
        "standard",
        "tool assisted",
        "pit",
        "puzzle",
    }:
        return ""
    return cleaned


def scan_rom_library(
    root: str | Path,
    known_difficulties: Iterable[str] = (),
) -> RomLibraryScan:
    """Recursively discover .sfc/.smc files without moving or changing them."""

    base = Path(root).expanduser().resolve()
    if not base.is_dir():
        raise NotADirectoryError(str(base))

    roms = []
    for path in sorted(base.rglob("*"), key=lambda item: str(item).casefold()):
        # The user selected one tree. Do not follow symlinked files outside it.
        if path.is_symlink():
            continue
        if not path.is_file() or path.suffix.casefold() not in ROM_EXTENSIONS:
            continue

        resolved = path.resolve()
        if not resolved.is_relative_to(base):
            continue

        identifiers = extract_explicit_smwc_submission_ids(path.name)
        if len(identifiers) > 1:
            raise RomIngestionError(
                "ROM filename contains conflicting explicit SMWC IDs: "
                f"{path.name}"
            )

        title_hint = clean_title_for_match(path.name) or path.stem
        sha256, size_bytes = _hash_stable_file(path)
        roms.append(
            RomFileEvidence(
                path=str(resolved),
                filename=path.name,
                sha256=sha256,
                size_bytes=size_bytes,
                title_hint=title_hint,
                folder_title_hint=_folder_title_hint(
                    path,
                    base,
                    known_difficulties,
                ),
                difficulty_hint=infer_difficulty_hint(
                    str(path),
                    known_difficulties,
                ),
                embedded_smwc_submission_id=(
                    identifiers[0] if identifiers else None
                ),
                probable_base_rom=is_probable_base_rom(path.name),
            )
        )

    by_hash: dict[str, list[str]] = {}
    for rom in roms:
        by_hash.setdefault(rom.sha256, []).append(rom.path)
    duplicates = tuple(
        RomDuplicateGroup(
            sha256=sha256,
            paths=tuple(sorted(paths, key=str.casefold)),
        )
        for sha256, paths in sorted(by_hash.items())
        if len(paths) > 1
    )

    return RomLibraryScan(
        root=str(base),
        roms=tuple(roms),
        duplicate_groups=duplicates,
    )


def candidate_from_rom(rom: RomFileEvidence) -> CollectionCandidate:
    """Create an internal candidate from facts discovered about one ROM."""

    title_hints = tuple(
        dict.fromkeys(
            hint
            for hint in (rom.title_hint, rom.folder_title_hint)
            if hint
        )
    )
    return CollectionCandidate(
        source=IngestionSource.ROM_SCAN,
        title_hints=title_hints,
        identity_evidence=rom.identity_evidence(),
        rom_files=(rom,),
        allow_local_only=True,
    )


def _as_resolution(
    rom: RomFileEvidence,
    result: CatalogueMatchResult,
    *,
    evidence_title: str,
    force_review: bool = False,
    classification: str | None = None,
) -> RomCatalogueResolution:
    auto_selected = bool(result.auto_selected and not force_review)
    selected = result.selected if auto_selected else None
    return RomCatalogueResolution(
        rom=rom,
        selected=selected,
        suggestion=result.suggestion,
        confidence=result.confidence,
        classification=(
            classification
            if classification is not None
            else result.classification
        ),
        auto_selected=auto_selected,
        evidence_title=evidence_title,
    )


def resolve_rom_against_catalogue(
    rom: RomFileEvidence,
    matcher: CatalogueMatcher,
) -> RomCatalogueResolution:
    """Resolve one ROM conservatively against a prepared lightweight catalogue."""

    embedded_id = rom.embedded_smwc_submission_id
    if embedded_id is not None:
        entry = matcher.get(embedded_id)
        if entry is None:
            # An explicit filename ID is strong user-controlled evidence. If it
            # is absent from the frozen catalogue, do not silently reidentify
            # the ROM by title to a different submission.
            return RomCatalogueResolution(
                rom=rom,
                selected=None,
                suggestion=None,
                confidence=0.0,
                classification="SMWC ID not in current catalogue - review",
                auto_selected=False,
                evidence_title=rom.title_hint,
            )
        direct_match = matcher.score_entry(
            rom.title_hint,
            embedded_id,
            difficulty_hint=rom.difficulty_hint,
        )
        direct_score = direct_match.score if direct_match is not None else 0.0

        # The explicit filename ID is strong evidence, but filenames are
        # user-controlled. A severe title disagreement is surfaced for
        # review instead of silently attaching the wrong catalogue record.
        if direct_score >= 0.68:
            return RomCatalogueResolution(
                rom=rom,
                selected=entry,
                suggestion=entry,
                confidence=direct_score,
                classification="Explicit SMWC ID",
                auto_selected=True,
                evidence_title=rom.title_hint,
            )
        return RomCatalogueResolution(
            rom=rom,
            selected=None,
            suggestion=entry,
            confidence=direct_score,
            classification="SMWC ID/title conflict - review",
            auto_selected=False,
            evidence_title=rom.title_hint,
        )

    filename_result = matcher.find(
        rom.title_hint,
        difficulty_hint=rom.difficulty_hint,
    )
    if filename_result.auto_selected:
        return _as_resolution(
            rom,
            filename_result,
            evidence_title=rom.title_hint,
        )

    folder_result = None
    if (
        rom.folder_title_hint
        and rom.folder_title_hint.casefold() != rom.title_hint.casefold()
    ):
        folder_result = matcher.find(
            rom.folder_title_hint,
            difficulty_hint=rom.difficulty_hint,
        )

    if folder_result is not None:
        filename_id = (
            filename_result.suggestion.smwc_submission_id
            if filename_result.suggestion is not None
            else None
        )
        folder_id = (
            folder_result.suggestion.smwc_submission_id
            if folder_result.suggestion is not None
            else None
        )

        # Two independent local labels agreeing on one catalogue record is
        # stronger than either weak signal alone.
        if (
            filename_id is not None
            and filename_id == folder_id
            and filename_result.confidence >= 0.68
            and folder_result.confidence >= 0.68
        ):
            selected = matcher.get(filename_id)
            confidence = max(
                filename_result.confidence,
                folder_result.confidence,
            )
            return RomCatalogueResolution(
                rom=rom,
                selected=selected,
                suggestion=selected,
                confidence=confidence,
                classification="Strong",
                auto_selected=True,
                evidence_title=(
                    f"{rom.title_hint} + folder {rom.folder_title_hint}"
                ),
            )

        # A parent directory is only a hint: even an exact folder match must be
        # reviewed if the filename itself did not independently resolve.
        if folder_result.suggestion is not None and (
            filename_result.suggestion is None
            or folder_result.confidence > filename_result.confidence
        ):
            return _as_resolution(
                rom,
                folder_result,
                evidence_title=rom.folder_title_hint,
                force_review=True,
                classification="Folder title - review",
            )

    return _as_resolution(
        rom,
        filename_result,
        evidence_title=rom.title_hint,
    )


__all__ = [
    "ROM_EXTENSIONS",
    "RomCatalogueResolution",
    "RomDuplicateGroup",
    "RomIngestionError",
    "RomLibraryScan",
    "candidate_from_rom",
    "resolve_rom_against_catalogue",
    "scan_rom_library",
]
