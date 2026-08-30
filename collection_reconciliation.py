"""Reviewable reconciliation domain for Collection ingestion evidence."""
from __future__ import annotations

import re
import secrets
from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Mapping, Sequence

from collection_ingestion import CollectionCandidate, IngestionSource, UserPlaythroughEvidence


_LOCAL_ID_RE = re.compile(r"^usr_[0-9a-f]{16}$")
_SPEEDRUN_MARKERS = (
    "pb",
    "personal best",
    "speedrun",
    "speed run",
    "race",
    "rta",
    "practice",
)
_USER_OWNED_FIELDS = frozenset(
    {
        "completed",
        "completed_date",
        "personal_rating",
        "notes",
        "time_to_beat",
    }
)
_GIGANTIC_BUCKET_AUTOMATIC_FIELDS = frozenset({"completed", "completed_date"})
_SAVE_SCAN_AUTOMATIC_FIELDS = frozenset({"completed", "completed_date"})


class MatchBasis(str, Enum):
    """Why a candidate currently points at a Collection identity."""

    DIRECT = "direct"
    USER_CONFIRMED = "user_confirmed"
    AUTO_TITLE = "auto_title"
    SUGGESTED_TITLE = "suggested_title"
    AMBIGUOUS = "ambiguous"
    CONFLICT = "conflict"
    UNMATCHED = "unmatched"


class ReviewState(str, Enum):
    """Review concerns independent of matcher-specific classifications."""

    READY = "ready"
    AUTO_MATCHED = "auto_matched"
    NEEDS_CONFIRMATION = "needs_confirmation"
    AMBIGUOUS = "ambiguous"
    IDENTITY_CONFLICT = "identity_conflict"
    ROM_SELECTION_REQUIRED = "rom_selection_required"
    USER_DATA_CONFLICT = "user_data_conflict"
    FIRST_CLEAR_VERIFICATION = "first_clear_verification"
    UNMATCHED = "unmatched"
    IDENTITY_MIGRATION = "identity_migration"
    SKIPPED = "skipped"
    IGNORED = "ignored"


BLOCKING_REVIEW_STATES = frozenset(
    {
        ReviewState.NEEDS_CONFIRMATION,
        ReviewState.AMBIGUOUS,
        ReviewState.IDENTITY_CONFLICT,
        ReviewState.ROM_SELECTION_REQUIRED,
        ReviewState.USER_DATA_CONFLICT,
        ReviewState.FIRST_CLEAR_VERIFICATION,
        ReviewState.UNMATCHED,
        ReviewState.IDENTITY_MIGRATION,
    }
)


class ReviewAction(str, Enum):
    """Explicit user dispositions understood by the domain layer."""

    ACCEPT = "accept"
    USE_TARGET = "use_target"
    IMPORT_LOCAL = "import_local"
    CONFIRM_MIGRATION = "confirm_migration"
    KEEP_SEPARATE = "keep_separate"
    SKIP = "skip"
    IGNORE = "ignore"


class IdentityMigrationKind(str, Enum):
    """Explicitly reviewed ways one Collection identity can change."""

    LOCAL_PROMOTION = "local_promotion"
    SUBMISSION_REPLACEMENT = "submission_replacement"


class ReconciliationError(ValueError):
    """Raised when reconciliation input violates the agreed domain rules."""


def is_numeric_collection_key(value: str) -> bool:
    """Return True for canonical positive-decimal SMWC Collection keys."""

    if not isinstance(value, str) or not value or not value.isdecimal():
        return False
    try:
        number = int(value)
    except ValueError:
        return False
    return number > 0 and str(number) == value


def is_local_collection_key(value: str) -> bool:
    """Return True for the generic opaque local-key shape introduced here."""

    return isinstance(value, str) and _LOCAL_ID_RE.fullmatch(value) is not None


def validate_collection_key(value: str) -> str:
    """Validate a numeric SMWC key or the generic opaque usr_* form."""

    if is_numeric_collection_key(value) or is_local_collection_key(value):
        return value
    raise ReconciliationError(f"Invalid Collection identity: {value!r}")


def generate_local_collection_id() -> str:
    """Allocate an opaque local identity without using title/path/hash evidence."""

    return f"usr_{secrets.token_hex(8)}"


@dataclass(frozen=True)
class IdentityMigrationProposal:
    """A user-reviewable identity change; never inferred from title similarity alone."""

    source_key: str
    target_key: str
    kind: IdentityMigrationKind
    prior_submission_ids: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        validate_collection_key(self.source_key)
        validate_collection_key(self.target_key)
        if self.source_key == self.target_key:
            raise ReconciliationError("Identity migration source and target must differ.")
        if self.kind is IdentityMigrationKind.LOCAL_PROMOTION:
            if not is_local_collection_key(self.source_key):
                raise ReconciliationError("Local promotion must start from usr_* identity.")
            if not is_numeric_collection_key(self.target_key):
                raise ReconciliationError("Local promotion must target a numeric SMWC ID.")
            if self.prior_submission_ids:
                raise ReconciliationError(
                    "Local promotion cannot claim prior numeric SMWC submissions."
                )
        elif self.kind is IdentityMigrationKind.SUBMISSION_REPLACEMENT:
            if not is_numeric_collection_key(self.source_key):
                raise ReconciliationError(
                    "Submission replacement must start from a numeric SMWC ID."
                )
            if not is_numeric_collection_key(self.target_key):
                raise ReconciliationError(
                    "Submission replacement must target a numeric SMWC ID."
                )
            for value in self.prior_submission_ids:
                if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                    raise ReconciliationError("Prior SMWC submission IDs must be positive.")

    @property
    def retained_submission_ids(self) -> tuple[int, ...]:
        """Return user-confirmed prior submission provenance without duplicates."""

        if self.kind is IdentityMigrationKind.LOCAL_PROMOTION:
            return ()
        values = [int(self.source_key), *self.prior_submission_ids]
        return tuple(dict.fromkeys(values))


@dataclass(frozen=True)
class UserFieldProposal:
    """One explicit proposal affecting user-owned scalar Collection state."""

    field: str
    current_value: bool | int | float | str | None
    proposed_value: bool | int | float | str | None
    source: IngestionSource
    reason: str
    conflict: bool = False

    def __post_init__(self) -> None:
        if self.field not in _USER_OWNED_FIELDS:
            raise ReconciliationError(f"Unsupported user-owned field: {self.field!r}")
        if self.source in {
            IngestionSource.KAIZOFF,
            IngestionSource.ROM_SCAN,
            IngestionSource.TOOL_PATCH,
        }:
            raise ReconciliationError(
                f"{self.source.value} cannot propose user-owned Collection state."
            )
        if self.source is IngestionSource.GIGANTIC_BUCKET:
            if self.field not in _GIGANTIC_BUCKET_AUTOMATIC_FIELDS:
                raise ReconciliationError(
                    "GiganticBucket playthroughs do not overwrite general notes, "
                    "ratings, or time_to_beat."
                )
        if self.source is IngestionSource.SAVE_SCAN:
            if self.field not in _SAVE_SCAN_AUTOMATIC_FIELDS:
                raise ReconciliationError(
                    "Save scanning may only propose completion facts here."
                )
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise ReconciliationError("User-field proposals require provenance text.")


@dataclass(frozen=True)
class CandidateResolution:
    """One source candidate plus its current proposed identity resolution."""

    candidate_id: str
    candidate: CollectionCandidate
    match_basis: MatchBasis
    target_key: str = ""
    existing_collection_key: str = ""
    alternative_target_keys: tuple[str, ...] = ()
    migration: IdentityMigrationProposal | None = None
    user_field_proposals: tuple[UserFieldProposal, ...] = ()
    first_clear_requires_verification: bool = False
    reason: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.candidate_id, str) or not self.candidate_id.strip():
            raise ReconciliationError("candidate_id must be non-empty.")
        if not isinstance(self.candidate, CollectionCandidate):
            raise ReconciliationError("candidate must be a CollectionCandidate.")
        target_required = self.match_basis in {
            MatchBasis.DIRECT,
            MatchBasis.USER_CONFIRMED,
            MatchBasis.AUTO_TITLE,
            MatchBasis.SUGGESTED_TITLE,
        }
        if target_required and not self.target_key:
            raise ReconciliationError(f"{self.match_basis.value} resolution needs a target.")
        if self.target_key:
            validate_collection_key(self.target_key)
        if self.existing_collection_key:
            validate_collection_key(self.existing_collection_key)
        for key in self.alternative_target_keys:
            validate_collection_key(key)
        if self.migration is not None:
            if self.existing_collection_key != self.migration.source_key:
                raise ReconciliationError(
                    "Migration source must be the candidate's existing Collection key."
                )
            if self.target_key != self.migration.target_key:
                raise ReconciliationError(
                    "Migration target must match the proposed candidate target."
                )
            if self.match_basis not in {MatchBasis.USER_CONFIRMED, MatchBasis.DIRECT}:
                raise ReconciliationError(
                    "Identity migration cannot originate from title similarity alone."
                )


@dataclass(frozen=True)
class ReviewIssue:
    """One reason a reconciliation group is or is not ready to finalize."""

    state: ReviewState
    reason: str

    @property
    def blocking(self) -> bool:
        return self.state in BLOCKING_REVIEW_STATES


@dataclass(frozen=True)
class ReconciliationGroup:
    """Evidence reviewed together without silently manufacturing identity."""

    group_id: str
    members: tuple[CandidateResolution, ...]
    proposed_target_key: str
    issues: tuple[ReviewIssue, ...]
    rom_hashes: tuple[str, ...]
    migration: IdentityMigrationProposal | None = None

    @property
    def blocking(self) -> bool:
        return any(issue.blocking for issue in self.issues)

    @property
    def review_states(self) -> tuple[ReviewState, ...]:
        return tuple(issue.state for issue in self.issues)

    @property
    def rom_files(self):
        return tuple(
            rom
            for member in self.members
            for rom in member.candidate.rom_files
        )

    @property
    def user_field_proposals(self) -> tuple[UserFieldProposal, ...]:
        return tuple(
            proposal
            for member in self.members
            for proposal in member.user_field_proposals
        )

    @property
    def user_history(self) -> tuple[UserPlaythroughEvidence, ...]:
        return tuple(
            history
            for member in self.members
            for history in member.candidate.user_history
        )


@dataclass(frozen=True)
class IgnoredRomDecision:
    """Ignore this exact file content at this exact local path."""

    path: str
    sha256: str


@dataclass(frozen=True)
class RomSelectionDecision:
    """Explicitly retained ROM paths and the one primary local ROM."""

    kept_paths: tuple[str, ...]
    primary_path: str
    ignored: tuple[IgnoredRomDecision, ...] = ()


@dataclass(frozen=True)
class UserFieldResolution:
    """Resolve one conflicting user-owned scalar proposal."""

    field: str
    use_proposed: bool


@dataclass(frozen=True)
class FirstClearDecision:
    """Explicit first-clear choice; None means the user chose no first clear."""

    decided: bool
    source: IngestionSource | None = None
    source_record_id: str | None = None

    def __post_init__(self) -> None:
        if not self.decided and (self.source is not None or self.source_record_id is not None):
            raise ReconciliationError(
                "An unfinished first-clear decision cannot select a playthrough."
            )
        if (self.source is None) != (self.source_record_id is None):
            raise ReconciliationError(
                "First-clear selection requires both source and source_record_id."
            )


@dataclass(frozen=True)
class RememberedAssociationDecision:
    """Source-scoped user-taught matching evidence."""

    source: IngestionSource
    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.value, str) or not self.value.strip():
            raise ReconciliationError("Remembered association value must be non-empty.")


@dataclass(frozen=True)
class ReviewDecision:
    """All explicit choices needed to resolve one review group."""

    group_id: str
    action: ReviewAction
    target_key: str = ""
    rom_selection: RomSelectionDecision | None = None
    user_field_resolutions: tuple[UserFieldResolution, ...] = ()
    first_clear: FirstClearDecision | None = None
    remembered_associations: tuple[RememberedAssociationDecision, ...] = ()


def _unique_rom_hashes(member: CandidateResolution) -> tuple[str, ...]:
    return tuple(dict.fromkeys(rom.sha256 for rom in member.candidate.rom_files))


def _is_established_target(member: CandidateResolution) -> bool:
    if not member.target_key:
        return False
    if member.migration is not None:
        return False
    if member.existing_collection_key == member.target_key:
        return True
    return member.match_basis in {MatchBasis.DIRECT, MatchBasis.USER_CONFIRMED}


def _bucket_key(
    member: CandidateResolution,
    established_targets: frozenset[str],
) -> str:
    if member.migration is not None:
        return f"migration:{member.migration.source_key}->{member.migration.target_key}"

    # Guarded title suggestions are review evidence, not established identity.
    # Keep them isolated until the user explicitly confirms a target so an
    # unrelated ROM cannot be folded into another hack merely because that
    # hack was its least-bad catalogue suggestion.
    if member.match_basis is MatchBasis.SUGGESTED_TITLE:
        hashes = _unique_rom_hashes(member)
        if len(hashes) == 1:
            return f"review-sha256:{hashes[0]}"
        return f"review-candidate:{member.candidate_id}"

    if member.target_key:
        if member.target_key in established_targets:
            return f"target:{member.target_key}"
        return f"proposal:{member.target_key}"
    hashes = _unique_rom_hashes(member)
    if len(hashes) == 1:
        return f"sha256:{hashes[0]}"
    return f"candidate:{member.candidate_id}"


def _contains_speedrun_marker(history: UserPlaythroughEvidence) -> bool:
    haystack = " ".join((history.category, history.play_kind, history.icon)).casefold()
    tokens = set(re.findall(r"[a-z0-9]+", haystack))
    if "pb" in tokens or "rta" in tokens:
        return True
    return any(marker in haystack for marker in _SPEEDRUN_MARKERS if " " in marker or len(marker) > 3)


def automatic_first_clear(
    history: Sequence[UserPlaythroughEvidence],
) -> UserPlaythroughEvidence | None:
    """Return the sole ordinary playthrough, otherwise require explicit review."""

    if len(history) != 1:
        return None
    only = history[0]
    if _contains_speedrun_marker(only):
        return None
    return only


def _issues_for_group(members: tuple[CandidateResolution, ...]) -> tuple[ReviewIssue, ...]:
    blockers: dict[ReviewState, str] = {}
    migration = next((member.migration for member in members if member.migration), None)

    bases = {member.match_basis for member in members}
    if MatchBasis.CONFLICT in bases:
        blockers[ReviewState.IDENTITY_CONFLICT] = "Conflicting strong identity evidence."
    elif MatchBasis.AMBIGUOUS in bases:
        blockers[ReviewState.AMBIGUOUS] = "Multiple catalogue identities remain plausible."
    elif MatchBasis.UNMATCHED in bases:
        blockers[ReviewState.UNMATCHED] = "No catalogue identity has been established."
    elif MatchBasis.SUGGESTED_TITLE in bases:
        blockers[ReviewState.NEEDS_CONFIRMATION] = (
            "The catalogue match is a guarded suggestion and needs confirmation."
        )

    if migration is not None:
        blockers[ReviewState.IDENTITY_MIGRATION] = (
            "Changing a Collection identity requires explicit confirmation."
        )

    hashes = tuple(
        dict.fromkeys(
            rom.sha256
            for member in members
            for rom in member.candidate.rom_files
        )
    )
    if len(hashes) > 1:
        blockers[ReviewState.ROM_SELECTION_REQUIRED] = (
            "Different ROM hashes do not establish version order or equivalence."
        )

    proposals = tuple(
        proposal
        for member in members
        for proposal in member.user_field_proposals
    )
    if any(proposal.conflict for proposal in proposals):
        blockers[ReviewState.USER_DATA_CONFLICT] = (
            "Conflicting user-owned Collection state needs an explicit choice."
        )

    history = tuple(
        item
        for member in members
        for item in member.candidate.user_history
    )
    if history:
        force_review = any(member.first_clear_requires_verification for member in members)
        if force_review or automatic_first_clear(history) is None:
            blockers[ReviewState.FIRST_CLEAR_VERIFICATION] = (
                "The first-clear record cannot be established safely without review."
            )

    if blockers:
        ordered = tuple(
            state
            for state in ReviewState
            if state in blockers and state in BLOCKING_REVIEW_STATES
        )
        return tuple(ReviewIssue(state=state, reason=blockers[state]) for state in ordered)

    if MatchBasis.AUTO_TITLE in bases:
        return (
            ReviewIssue(
                state=ReviewState.AUTO_MATCHED,
                reason="High-confidence catalogue proposal is visible but non-blocking.",
            ),
        )
    return (
        ReviewIssue(
            state=ReviewState.READY,
            reason="Direct or previously confirmed evidence is ready to apply.",
        ),
    )


def build_reconciliation_groups(
    resolutions: Iterable[CandidateResolution],
) -> tuple[ReconciliationGroup, ...]:
    """Group direct/common evidence while keeping title similarity reviewable."""

    members = tuple(sorted(resolutions, key=lambda item: item.candidate_id))
    if not members:
        return ()
    identifiers = [member.candidate_id for member in members]
    if len(identifiers) != len(set(identifiers)):
        raise ReconciliationError("candidate_id values must be unique.")

    established_targets = frozenset(
        member.target_key for member in members if _is_established_target(member)
    )
    buckets: dict[str, list[CandidateResolution]] = {}
    for member in members:
        buckets.setdefault(_bucket_key(member, established_targets), []).append(member)

    groups = []
    for group_id in sorted(buckets):
        grouped = tuple(buckets[group_id])
        targets = tuple(dict.fromkeys(item.target_key for item in grouped if item.target_key))
        if len(targets) > 1:
            raise ReconciliationError("One reconciliation group cannot target multiple keys.")
        migrations = tuple(
            dict.fromkeys(item.migration for item in grouped if item.migration is not None)
        )
        if len(migrations) > 1:
            raise ReconciliationError("One reconciliation group cannot contain two migrations.")
        hashes = tuple(
            dict.fromkeys(
                rom.sha256
                for item in grouped
                for rom in item.candidate.rom_files
            )
        )
        groups.append(
            ReconciliationGroup(
                group_id=group_id,
                members=grouped,
                proposed_target_key=targets[0] if targets else "",
                issues=_issues_for_group(grouped),
                rom_hashes=hashes,
                migration=migrations[0] if migrations else None,
            )
        )
    return tuple(groups)


def _roms_by_path(group: ReconciliationGroup) -> Mapping[str, object]:
    return {rom.path: rom for rom in group.rom_files}


def _validate_rom_selection(
    group: ReconciliationGroup,
    selection: RomSelectionDecision,
) -> None:
    available = _roms_by_path(group)
    kept = tuple(dict.fromkeys(selection.kept_paths))
    if kept != selection.kept_paths:
        raise ReconciliationError("ROM selection cannot contain duplicate kept paths.")
    if not kept:
        raise ReconciliationError("ROM selection must keep at least one ROM path.")
    unknown = set(kept).difference(available)
    if unknown:
        raise ReconciliationError(f"ROM selection references unknown paths: {sorted(unknown)!r}")
    if selection.primary_path not in kept:
        raise ReconciliationError("Primary ROM path must be one of the retained ROM paths.")
    ignored_paths = set()
    for ignored in selection.ignored:
        if ignored.path not in available:
            raise ReconciliationError("Ignored ROM path was not discovered by this group.")
        rom = available[ignored.path]
        if getattr(rom, "sha256") != ignored.sha256:
            raise ReconciliationError("Ignored ROM decision must match path + SHA-256.")
        if ignored.path in kept:
            raise ReconciliationError("A ROM path cannot be both retained and ignored.")
        if ignored.path in ignored_paths:
            raise ReconciliationError("Ignored ROM path cannot be repeated.")
        ignored_paths.add(ignored.path)


def validate_review_decision(
    group: ReconciliationGroup,
    decision: ReviewDecision | None,
) -> None:
    """Validate that one explicit disposition resolves every blocking concern."""

    if decision is None:
        if group.blocking:
            raise ReconciliationError(f"Group {group.group_id!r} still needs review.")
        return
    if decision.group_id != group.group_id:
        raise ReconciliationError("Review decision belongs to another group.")
    if decision.target_key:
        validate_collection_key(decision.target_key)

    if decision.action in {ReviewAction.SKIP, ReviewAction.IGNORE}:
        if decision.action is ReviewAction.IGNORE and not group.rom_files:
            raise ReconciliationError("Only groups with ROM evidence can be ignored.")
        return

    states = set(group.review_states)
    identity_states = {
        ReviewState.NEEDS_CONFIRMATION,
        ReviewState.AMBIGUOUS,
        ReviewState.IDENTITY_CONFLICT,
        ReviewState.UNMATCHED,
    }
    if states.intersection(identity_states):
        if decision.action not in {ReviewAction.USE_TARGET, ReviewAction.IMPORT_LOCAL}:
            raise ReconciliationError("Identity review requires a target or local import.")
        if decision.action is ReviewAction.USE_TARGET and not decision.target_key:
            raise ReconciliationError("USE_TARGET requires an explicit Collection key.")

    if ReviewState.IDENTITY_MIGRATION in states:
        if decision.action not in {
            ReviewAction.CONFIRM_MIGRATION,
            ReviewAction.KEEP_SEPARATE,
        }:
            raise ReconciliationError(
                "Identity migration must be confirmed or explicitly kept separate."
            )

    if ReviewState.ROM_SELECTION_REQUIRED in states:
        if decision.rom_selection is None:
            raise ReconciliationError("Different ROM hashes require an explicit selection.")
        _validate_rom_selection(group, decision.rom_selection)
    elif decision.rom_selection is not None:
        _validate_rom_selection(group, decision.rom_selection)

    if ReviewState.USER_DATA_CONFLICT in states:
        conflict_fields = {
            proposal.field
            for proposal in group.user_field_proposals
            if proposal.conflict
        }
        resolutions = {item.field: item for item in decision.user_field_resolutions}
        if set(resolutions) != conflict_fields:
            raise ReconciliationError(
                "Every conflicting user-owned field requires exactly one resolution."
            )

    if ReviewState.FIRST_CLEAR_VERIFICATION in states:
        if decision.first_clear is None or not decision.first_clear.decided:
            raise ReconciliationError("First-clear review requires an explicit decision.")
        if decision.first_clear.source_record_id is not None:
            known = {
                (item.source, item.source_record_id)
                for item in group.user_history
            }
            selected = (
                decision.first_clear.source,
                decision.first_clear.source_record_id,
            )
            if selected not in known:
                raise ReconciliationError("Selected first-clear playthrough is not in this group.")


def resolved_target_key(
    group: ReconciliationGroup,
    decision: ReviewDecision | None,
    local_identity: str = "",
) -> str | None:
    """Resolve the final target key without allocating identities implicitly."""

    validate_review_decision(group, decision)
    if decision is not None and decision.action in {ReviewAction.SKIP, ReviewAction.IGNORE}:
        return None
    if decision is not None and decision.action is ReviewAction.IMPORT_LOCAL:
        if not local_identity:
            raise ReconciliationError("Local import requires a pre-allocated usr_* identity.")
        if not is_local_collection_key(local_identity):
            raise ReconciliationError("Local import allocation must use opaque usr_* identity.")
        return local_identity
    if decision is not None and decision.action is ReviewAction.USE_TARGET:
        return decision.target_key
    if decision is not None and decision.action in {
        ReviewAction.CONFIRM_MIGRATION,
        ReviewAction.KEEP_SEPARATE,
    }:
        if group.migration is None:
            raise ReconciliationError("Migration action used on a non-migration group.")
        return group.migration.target_key
    if group.proposed_target_key:
        return group.proposed_target_key
    raise ReconciliationError("Resolved group has no Collection target.")


__all__ = [
    "BLOCKING_REVIEW_STATES",
    "CandidateResolution",
    "FirstClearDecision",
    "IdentityMigrationKind",
    "IdentityMigrationProposal",
    "IgnoredRomDecision",
    "MatchBasis",
    "ReconciliationError",
    "ReconciliationGroup",
    "RememberedAssociationDecision",
    "ReviewAction",
    "ReviewDecision",
    "ReviewIssue",
    "ReviewState",
    "RomSelectionDecision",
    "UserFieldProposal",
    "UserFieldResolution",
    "automatic_first_clear",
    "build_reconciliation_groups",
    "generate_local_collection_id",
    "is_local_collection_key",
    "is_numeric_collection_key",
    "resolved_target_key",
    "validate_collection_key",
    "validate_review_decision",
]
