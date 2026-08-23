"""Internal evidence model for Collection ingestion workflows."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Mapping


class IngestionSource(str, Enum):
    """Known origins of candidate Collection evidence."""

    ROM_SCAN = "rom_scan"
    TOOL_PATCH = "tool_patch"
    SAVE_SCAN = "save_scan"
    KAIZOFF = "kaizoff"
    GIGANTIC_BUCKET = "giganticbucket"
    MANUAL = "manual"


class EvidenceStrength(str, Enum):
    """How strongly one piece of evidence identifies something."""

    EXACT = "exact"
    STRONG = "strong"
    HINT = "hint"


class IdentityEvidenceKind(str, Enum):
    """Identity/equivalence evidence understood by the ingestion layer."""

    SMWC_SUBMISSION_ID = "smwc_submission_id"
    ROM_SHA256 = "rom_sha256"
    TITLE = "title"
    EXISTING_COLLECTION_KEY = "existing_collection_key"
    SOURCE_RECORD_ID = "source_record_id"


@dataclass(frozen=True)
class SourceCapabilities:
    """Fields a source category may legitimately propose."""

    shared_metadata: bool = False
    rom_paths: bool = False
    save_paths: bool = False
    user_history: bool = False


SOURCE_CAPABILITIES: Mapping[IngestionSource, SourceCapabilities] = MappingProxyType(
    {
        IngestionSource.ROM_SCAN: SourceCapabilities(rom_paths=True),
        IngestionSource.TOOL_PATCH: SourceCapabilities(rom_paths=True),
        IngestionSource.SAVE_SCAN: SourceCapabilities(save_paths=True),
        IngestionSource.KAIZOFF: SourceCapabilities(shared_metadata=True),
        IngestionSource.GIGANTIC_BUCKET: SourceCapabilities(user_history=True),
        IngestionSource.MANUAL: SourceCapabilities(
            shared_metadata=True,
            rom_paths=True,
            save_paths=True,
            user_history=True,
        ),
    }
)


@dataclass(frozen=True)
class IdentityEvidence:
    """One source-scoped identity clue."""

    kind: IdentityEvidenceKind
    value: str
    source: IngestionSource
    strength: EvidenceStrength


@dataclass(frozen=True)
class RomFileEvidence:
    """Immutable facts discovered about one local ROM file."""

    path: str
    filename: str
    sha256: str
    size_bytes: int
    title_hint: str
    folder_title_hint: str = ""
    difficulty_hint: str = ""
    embedded_smwc_submission_id: int | None = None
    probable_base_rom: bool = False

    def identity_evidence(self) -> tuple[IdentityEvidence, ...]:
        """Return local identity clues without claiming remote catalogue identity."""

        evidence = [
            IdentityEvidence(
                kind=IdentityEvidenceKind.ROM_SHA256,
                value=self.sha256,
                source=IngestionSource.ROM_SCAN,
                strength=EvidenceStrength.EXACT,
            ),
        ]
        if self.title_hint:
            evidence.append(
                IdentityEvidence(
                    kind=IdentityEvidenceKind.TITLE,
                    value=self.title_hint,
                    source=IngestionSource.ROM_SCAN,
                    strength=EvidenceStrength.HINT,
                )
            )
        if self.embedded_smwc_submission_id is not None:
            evidence.append(
                IdentityEvidence(
                    kind=IdentityEvidenceKind.SMWC_SUBMISSION_ID,
                    value=str(self.embedded_smwc_submission_id),
                    source=IngestionSource.ROM_SCAN,
                    strength=EvidenceStrength.STRONG,
                )
            )
        return tuple(evidence)


@dataclass(frozen=True)
class SharedMetadataEvidence:
    """Provider-owned hack metadata that never grants local-path authority."""

    source: IngestionSource
    title: str
    authors: tuple[str, ...] = ()
    difficulty: str = ""
    hack_types: tuple[str, ...] = ()
    exits: int | None = None
    release_timestamp: int | None = None
    rating: float | None = None
    hall_of_fame: bool | None = None
    sa1_compatible: bool | None = None
    collaboration: bool | None = None
    demo: bool | None = None
    description: str = ""
    tags: tuple[str, ...] = ()
    image_urls: tuple[str, ...] = ()
    download_url: str = ""
    active: bool | None = None
    obsoleted_by_submission_id: int | None = None


@dataclass(frozen=True)
class UserPlaythroughEvidence:
    """Imported user-history evidence; merge policy is intentionally deferred."""

    source: IngestionSource
    source_record_id: str
    category: str = ""
    play_kind: str = ""
    icon: str = ""
    elapsed_text: str = ""
    elapsed_seconds: int | None = None
    version: str = ""
    completed_date_text: str = ""
    completed_date_iso: str = ""
    notes: str = ""
    counts_as_hack: bool = False
    exit_count: int | None = None
    duration_milliseconds: int | None = None
    duration_precision: str = ""


@dataclass(frozen=True)
class CollectionCandidate:
    """Internal aggregation of source evidence for one potential Collection hack."""

    source: IngestionSource
    title_hints: tuple[str, ...] = ()
    author_hints: tuple[str, ...] = ()
    identity_evidence: tuple[IdentityEvidence, ...] = ()
    rom_files: tuple[RomFileEvidence, ...] = ()
    shared_metadata: tuple[SharedMetadataEvidence, ...] = ()
    user_history: tuple[UserPlaythroughEvidence, ...] = ()
    allow_local_only: bool = False


__all__ = [
    "CollectionCandidate",
    "EvidenceStrength",
    "IdentityEvidence",
    "IdentityEvidenceKind",
    "IngestionSource",
    "RomFileEvidence",
    "SOURCE_CAPABILITIES",
    "SharedMetadataEvidence",
    "SourceCapabilities",
    "UserPlaythroughEvidence",
]
