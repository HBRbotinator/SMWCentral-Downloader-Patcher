"""Presentation-only review model for Collection ingestion sessions.

This module owns no persistence and performs no network access. It projects the
frozen Commit 006 session into review rows, tracks explicit ReviewDecision
objects, and searches only the catalogue snapshot captured by that session.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from collection_ingestion import IngestionSource
from collection_ingestion_session import (
    CatalogueSuggestion,
    CollectionIngestionSession,
    search_session_catalogue,
)
from collection_reconciliation import (
    ReconciliationError,
    ReconciliationGroup,
    ReviewAction,
    ReviewDecision,
    ReviewState,
    validate_review_decision,
)


_STATE_LABELS = {
    ReviewState.READY: "Ready",
    ReviewState.AUTO_MATCHED: "Auto-matched",
    ReviewState.NEEDS_CONFIRMATION: "Needs confirmation",
    ReviewState.AMBIGUOUS: "Ambiguous",
    ReviewState.IDENTITY_CONFLICT: "Identity conflict",
    ReviewState.ROM_SELECTION_REQUIRED: "ROM selection",
    ReviewState.USER_DATA_CONFLICT: "User-data conflict",
    ReviewState.FIRST_CLEAR_VERIFICATION: "First-clear review",
    ReviewState.UNMATCHED: "Unmatched",
    ReviewState.IDENTITY_MIGRATION: "Identity migration",
    ReviewState.SKIPPED: "Skipped",
    ReviewState.IGNORED: "Ignored",
}

_SOURCE_LABELS = {
    IngestionSource.ROM_SCAN: "ROM scan",
    IngestionSource.GIGANTIC_BUCKET: "GiganticBucket",
    IngestionSource.SAVE_SCAN: "Save scan",
    IngestionSource.TOOL_PATCH: "Tool download/patch",
    IngestionSource.KAIZOFF: "KaizOFF",
    IngestionSource.MANUAL: "Manual",
}


class CollectionIngestionReviewError(ValueError):
    """Raised when presentation/review state is inconsistent with the session."""


@dataclass(frozen=True)
class ReviewSummary:
    total_groups: int
    ready_groups: int
    blocking_groups: int
    resolved_blocking_groups: int
    unresolved_blocking_groups: int
    skipped_groups: int
    ignored_groups: int
    suppressed_roms: int

    @property
    def can_complete(self) -> bool:
        return self.unresolved_blocking_groups == 0


@dataclass(frozen=True)
class ReviewRow:
    group_id: str
    title: str
    sources: tuple[str, ...]
    status: str
    blocking: bool
    resolved: bool
    target_key: str
    target_title: str
    issue_labels: tuple[str, ...]
    rom_count: int
    unique_rom_hashes: int
    history_count: int


@dataclass(frozen=True)
class GroupReviewContext:
    group: ReconciliationGroup
    row: ReviewRow
    suggestions: tuple[CatalogueSuggestion, ...]
    candidate_reasons: tuple[str, ...]
    rememberable_aliases: tuple[tuple[IngestionSource, str], ...]


class CollectionIngestionReviewModel:
    """Mutable UI session state containing only explicit user review choices."""

    def __init__(
        self,
        session: CollectionIngestionSession,
        decisions: Mapping[str, ReviewDecision] | None = None,
    ) -> None:
        if not isinstance(session, CollectionIngestionSession):
            raise CollectionIngestionReviewError(
                "CollectionIngestionReviewModel requires a frozen ingestion session."
            )
        self.session = session
        self._groups = {group.group_id: group for group in session.groups}
        self._reviews = {entry.candidate_id: entry for entry in session.review_entries}
        self._decisions: dict[str, ReviewDecision] = {}
        for group_id, decision in dict(decisions or {}).items():
            self.set_decision(group_id, decision)

    @property
    def decisions(self) -> dict[str, ReviewDecision]:
        """Return a detached snapshot suitable for finalization callbacks."""

        return dict(self._decisions)

    def get_group(self, group_id: str) -> ReconciliationGroup:
        try:
            return self._groups[group_id]
        except KeyError as error:
            raise CollectionIngestionReviewError(
                f"Unknown reconciliation group: {group_id!r}"
            ) from error

    def decision_for(self, group_id: str) -> ReviewDecision | None:
        self.get_group(group_id)
        return self._decisions.get(group_id)

    def set_decision(self, group_id: str, decision: ReviewDecision) -> None:
        group = self.get_group(group_id)
        if not isinstance(decision, ReviewDecision):
            raise CollectionIngestionReviewError("decision must be a ReviewDecision.")
        if decision.group_id != group_id:
            raise CollectionIngestionReviewError(
                "Review decision group_id does not match the selected group."
            )
        try:
            validate_review_decision(group, decision)
        except ReconciliationError as error:
            raise CollectionIngestionReviewError(str(error)) from error
        self._decisions[group_id] = decision

    def clear_decision(self, group_id: str) -> None:
        self.get_group(group_id)
        self._decisions.pop(group_id, None)

    def is_group_resolved(self, group_id: str) -> bool:
        group = self.get_group(group_id)
        decision = self._decisions.get(group_id)
        if not group.blocking:
            return True
        if decision is None:
            return False
        try:
            validate_review_decision(group, decision)
        except ReconciliationError:
            return False
        return True

    def unresolved_group_ids(self) -> tuple[str, ...]:
        return tuple(
            group.group_id
            for group in self.session.groups
            if group.blocking and not self.is_group_resolved(group.group_id)
        )

    @property
    def can_complete(self) -> bool:
        return not self.unresolved_group_ids()

    def summary(self) -> ReviewSummary:
        blocking = tuple(group for group in self.session.groups if group.blocking)
        resolved = tuple(
            group for group in blocking if self.is_group_resolved(group.group_id)
        )
        decisions = self._decisions.values()
        skipped = sum(1 for item in decisions if item.action is ReviewAction.SKIP)
        ignored = sum(1 for item in decisions if item.action is ReviewAction.IGNORE)
        return ReviewSummary(
            total_groups=len(self.session.groups),
            ready_groups=len(self.session.groups) - len(blocking),
            blocking_groups=len(blocking),
            resolved_blocking_groups=len(resolved),
            unresolved_blocking_groups=len(blocking) - len(resolved),
            skipped_groups=skipped,
            ignored_groups=ignored,
            suppressed_roms=len(self.session.suppressed_roms),
        )

    def rows(self, *, attention_only: bool = False) -> tuple[ReviewRow, ...]:
        rows = tuple(self._row_for_group(group) for group in self.session.groups)
        if attention_only:
            rows = tuple(
                row
                for row in rows
                if row.blocking or row.group_id in self._decisions
            )
        return tuple(sorted(rows, key=_row_sort_key))

    def context(self, group_id: str) -> GroupReviewContext:
        group = self.get_group(group_id)
        suggestions: dict[str, CatalogueSuggestion] = {}
        reasons = []
        aliases = []
        for member in group.members:
            review = self._reviews.get(member.candidate_id)
            if review is not None:
                if review.reason and review.reason not in reasons:
                    reasons.append(review.reason)
                for suggestion in review.suggestions:
                    previous = suggestions.get(suggestion.target_key)
                    if previous is None or suggestion.confidence > previous.confidence:
                        suggestions[suggestion.target_key] = suggestion
            for target in (member.target_key, *member.alternative_target_keys):
                if target and target not in suggestions:
                    suggestions[target] = CatalogueSuggestion(
                        target_key=target,
                        title=f"SMWC {target}",
                        difficulty="",
                        hack_type="",
                        exits=None,
                        confidence=0.0,
                    )
            if member.candidate.source is IngestionSource.ROM_SCAN:
                for value in member.candidate.title_hints:
                    normalized = " ".join(str(value).strip().split())
                    key = (IngestionSource.ROM_SCAN, normalized)
                    if normalized and key not in aliases:
                        aliases.append(key)
        ordered = tuple(
            sorted(
                suggestions.values(),
                key=lambda item: (-item.confidence, _target_sort_key(item.target_key)),
            )
        )
        return GroupReviewContext(
            group=group,
            row=self._row_for_group(group),
            suggestions=ordered,
            candidate_reasons=tuple(reasons),
            rememberable_aliases=tuple(aliases),
        )

    def search_catalogue(self, query: str, *, limit: int = 20) -> tuple[CatalogueSuggestion, ...]:
        return search_session_catalogue(self.session, query, limit=limit)

    def _row_for_group(self, group: ReconciliationGroup) -> ReviewRow:
        decision = self._decisions.get(group.group_id)
        resolved = self.is_group_resolved(group.group_id)
        title = _group_title(group)
        source_labels = tuple(
            dict.fromkeys(
                _SOURCE_LABELS.get(member.candidate.source, member.candidate.source.value)
                for member in group.members
            )
        )
        target_key = _display_target(group, decision)
        target_title = self._target_title(group, target_key)
        if decision is not None and decision.action is ReviewAction.SKIP:
            status = "Skipped"
        elif decision is not None and decision.action is ReviewAction.IGNORE:
            status = "Ignored"
        elif group.blocking and resolved:
            status = "Resolved"
        elif group.blocking:
            status = _STATE_LABELS.get(group.review_states[0], "Needs review")
        else:
            status = _STATE_LABELS.get(group.review_states[0], "Ready")
        return ReviewRow(
            group_id=group.group_id,
            title=title,
            sources=source_labels,
            status=status,
            blocking=group.blocking,
            resolved=resolved,
            target_key=target_key,
            target_title=target_title,
            issue_labels=tuple(_STATE_LABELS.get(state, state.value) for state in group.review_states),
            rom_count=len(group.rom_files),
            unique_rom_hashes=len(group.rom_hashes),
            history_count=len(group.user_history),
        )

    def _target_title(self, group: ReconciliationGroup, target_key: str) -> str:
        if not target_key:
            return ""
        for member in group.members:
            review = self._reviews.get(member.candidate_id)
            if review is None:
                continue
            for suggestion in review.suggestions:
                if suggestion.target_key == target_key:
                    return suggestion.title
        for entry in self.session.catalogue_entries:
            if str(entry.smwc_submission_id) == target_key:
                return entry.title
        return f"SMWC {target_key}" if target_key.isdecimal() else target_key


def _group_title(group: ReconciliationGroup) -> str:
    for member in group.members:
        for title in member.candidate.title_hints:
            value = " ".join(str(title).strip().split())
            if value:
                return value
        for rom in member.candidate.rom_files:
            if rom.filename:
                return rom.filename
    if group.proposed_target_key:
        return f"Collection {group.proposed_target_key}"
    return group.group_id


def _display_target(
    group: ReconciliationGroup,
    decision: ReviewDecision | None,
) -> str:
    if decision is not None:
        if decision.action is ReviewAction.USE_TARGET:
            return decision.target_key
        if decision.action is ReviewAction.IMPORT_LOCAL:
            return "Local entry"
        if decision.action in {ReviewAction.SKIP, ReviewAction.IGNORE}:
            return ""
        if decision.action in {
            ReviewAction.CONFIRM_MIGRATION,
            ReviewAction.KEEP_SEPARATE,
        } and group.migration is not None:
            return group.migration.target_key
    return group.proposed_target_key


def _row_sort_key(row: ReviewRow):
    return (
        0 if row.blocking and not row.resolved else 1,
        0 if row.blocking else 1,
        row.title.casefold(),
        row.group_id,
    )


def _target_sort_key(value: str):
    if value.isdecimal():
        return (0, int(value))
    return (1, value)


__all__ = [
    "CollectionIngestionReviewError",
    "CollectionIngestionReviewModel",
    "GroupReviewContext",
    "ReviewRow",
    "ReviewSummary",
]
