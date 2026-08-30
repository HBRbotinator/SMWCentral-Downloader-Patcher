"""Privacy-safe diagnostic export for Collection ingestion review sessions."""
from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path
from typing import Mapping

from collection_ingestion_session import CollectionIngestionSession
from collection_reconciliation import ReviewDecision
from local_collection_matching import find_local_collection_matches


REPORT_VERSION = 2


def diagnostic_filename(now: datetime | None = None) -> str:
    stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    return f"SMWC-Collection-Import-Diagnostics-{stamp}.json"


def _basename(path: str) -> str:
    return os.path.basename(str(path or ""))


def _redact_paths(text: str, paths) -> str:
    value = str(text or "")
    for path in sorted({str(item or "") for item in paths if item}, key=len, reverse=True):
        if path:
            value = value.replace(path, _basename(path))
    return value


def _rom_summary(rom) -> dict:
    return {
        "filename": _basename(rom.path) or str(getattr(rom, "filename", "")),
        "sha256": str(rom.sha256),
        "size_bytes": int(rom.size_bytes),
        "title_hint": str(getattr(rom, "title_hint", "") or ""),
        "difficulty_hint": str(getattr(rom, "difficulty_hint", "") or ""),
        "embedded_smwc_submission_id": getattr(rom, "embedded_smwc_submission_id", None),
    }


def _decision_summary(decision: ReviewDecision | None) -> dict | None:
    if decision is None:
        return None
    row = {
        "action": decision.action.value,
        "target_key": str(decision.target_key or ""),
        "remembered_associations": [
            {"source": item.source.value, "value": item.value}
            for item in decision.remembered_associations
        ],
    }
    if decision.local_metadata is not None:
        row["local_metadata"] = {
            "title": decision.local_metadata.title,
            "difficulty": decision.local_metadata.difficulty,
            "type": list(decision.local_metadata.hack_types),
            "exits": decision.local_metadata.exits,
        }
    if decision.rom_selection is not None:
        row["rom_selection"] = {
            "kept_filenames": [_basename(path) for path in decision.rom_selection.kept_paths],
            "primary_filename": _basename(decision.rom_selection.primary_path),
            "ignored": [
                {"filename": _basename(item.path), "sha256": item.sha256}
                for item in decision.rom_selection.ignored
            ],
        }
    if decision.user_field_resolutions:
        row["user_field_resolutions"] = [
            {"field": item.field, "use_proposed": bool(item.use_proposed)}
            for item in decision.user_field_resolutions
        ]
    if decision.first_clear is not None:
        row["first_clear"] = {
            "decided": bool(decision.first_clear.decided),
            "source": (
                decision.first_clear.source.value
                if decision.first_clear.source is not None
                else None
            ),
            # Deliberately omit source_record_id: diagnostics do not need imported
            # personal-history identifiers to troubleshoot matching/finalization.
            "selected": decision.first_clear.source_record_id is not None,
        }
    return row


def _converged_decision_summary(decision) -> dict:
    selection = decision.selection
    return {
        "target_key": str(decision.target_key),
        "kept_filenames": [_basename(path) for path in selection.kept_paths],
        "primary_filename": _basename(selection.primary_path),
        "ignored": [
            {"filename": _basename(item.path), "sha256": item.sha256}
            for item in selection.ignored
        ],
    }


def build_diagnostic_report(
    session: CollectionIngestionSession,
    decisions: Mapping[str, ReviewDecision] | None = None,
    *,
    converged_rom_decisions: Mapping | None = None,
    finalization_error: str = "",
) -> dict:
    """Return a JSON-safe report without absolute paths or imported-history IDs."""

    if not isinstance(session, CollectionIngestionSession):
        raise TypeError("Collection ingestion diagnostics require a frozen session.")
    decision_map = dict(decisions or {})
    review_by_id = {item.candidate_id: item for item in session.review_entries}
    known_paths = [
        rom.path
        for group in session.groups
        for member in group.members
        for rom in member.candidate.rom_files
    ] + [item.path for item in session.suppressed_roms]

    groups = []
    for group in session.groups:
        local_hints = tuple(
            dict.fromkeys(
                str(title).strip()
                for member in group.members
                for title in member.candidate.title_hints
                if str(title).strip()
            )
        )
        local_matches = find_local_collection_matches(
            local_hints, session.local_collection_entries
        )
        members = []
        for member in group.members:
            review = review_by_id.get(member.candidate_id)
            members.append(
                {
                    "candidate_id": member.candidate_id,
                    "source": member.candidate.source.value,
                    "match_basis": member.match_basis.value,
                    "target_key": str(member.target_key or ""),
                    "existing_collection_key": str(member.existing_collection_key or ""),
                    "alternative_target_keys": list(member.alternative_target_keys),
                    "title_hints": list(member.candidate.title_hints),
                    "roms": [_rom_summary(rom) for rom in member.candidate.rom_files],
                    "matcher": (
                        {
                            "classification": review.classification,
                            "confidence": review.confidence,
                            "reason": _redact_paths(review.reason, known_paths),
                            "suggestions": [
                                {
                                    "smwc_id": item.target_key,
                                    "title": item.title,
                                    "confidence": item.confidence,
                                    "difficulty": item.difficulty,
                                    "type": item.hack_type,
                                }
                                for item in review.suggestions[:5]
                            ],
                        }
                        if review is not None
                        else None
                    ),
                }
            )
        groups.append(
            {
                "group_id": group.group_id,
                "proposed_target_key": str(group.proposed_target_key or ""),
                "review_states": [state.value for state in group.review_states],
                "issues": [
                    {"state": issue.state.value, "reason": _redact_paths(issue.reason, known_paths)}
                    for issue in group.issues
                ],
                "rom_hash_count": len(group.rom_hashes),
                "existing_local_suggestions": [
                    {
                        "collection_id": item.target_key,
                        "title": item.title,
                        "confidence": item.confidence,
                        "difficulty": item.difficulty,
                        "type": list(item.hack_types),
                        "exits": item.exits,
                    }
                    for item in local_matches
                ],
                "members": members,
                "decision": _decision_summary(decision_map.get(group.group_id)),
            }
        )

    return {
        "report": "smwc_collection_ingestion",
        "report_version": REPORT_VERSION,
        "catalogue": {
            "source": session.catalogue_source,
            "stale": bool(session.catalogue_stale),
            "entry_count": len(session.catalogue_entries),
        },
        "summary": {
            "group_count": len(session.groups),
            "blocking_group_count": len(session.blocking_groups),
            "suppressed_rom_count": len(session.suppressed_roms),
            "decision_count": len(decision_map),
        },
        "suppressed_roms": [
            {
                "filename": _basename(item.path),
                "sha256": item.sha256,
                "reason": _redact_paths(item.reason, known_paths),
            }
            for item in session.suppressed_roms
        ],
        "groups": groups,
        "converged_rom_decisions": [
            _converged_decision_summary(decision)
            for _, decision in sorted(dict(converged_rom_decisions or {}).items())
        ],
        "finalization_error": _redact_paths(finalization_error, known_paths),
        "privacy": {
            "absolute_paths_included": False,
            "raw_rom_bytes_included": False,
            "imported_history_record_ids_included": False,
        },
    }


def write_diagnostic_report(
    destination: str | Path,
    session: CollectionIngestionSession,
    decisions: Mapping[str, ReviewDecision] | None = None,
    *,
    converged_rom_decisions: Mapping | None = None,
    finalization_error: str = "",
) -> str:
    report = build_diagnostic_report(
        session,
        decisions,
        converged_rom_decisions=converged_rom_decisions,
        finalization_error=finalization_error,
    )
    path = Path(destination).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return str(path)


__all__ = [
    "REPORT_VERSION",
    "build_diagnostic_report",
    "diagnostic_filename",
    "write_diagnostic_report",
]
