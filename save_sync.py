"""
Save Data Sync

Scan a directory of SNES battery-save files (.srm / .sav), match them to hacks
in the collection by filename, and derive completion status + last-played date.

Format notes
------------
Both .srm and .sav files are raw SNES SRAM dumps. The structured parser first
checks the three standard SMW slots and their backup copies. Checksum-valid
slots are treated as medium-confidence evidence and the strongest valid
overworld-event counter is selected. When no standard slot can be proven, the
inherited byte at 0x8C remains available as low-confidence compatibility
evidence for smaller saves. Expanded SRAM images without a validated slot
suppress that raw byte to avoid false progress from unrelated layouts.

An overworld-event counter is still not universally equivalent to a ROM hack's
advertised exits. Later profiles can provide hack-specific semantics without
changing the matching or collection-update contracts in this module.

Real-world play time is not stored in SMW SRAM, so this module never touches
``time_to_beat``. The completion date comes from the file's on-disk modified
timestamp because SRAM stores no real-world date either.

Copyright (c) 2025 iamtheratio
Licensed under the MIT License - see LICENSE file for details
"""

import hashlib
import json
import os
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone

from save_analysis import (
    LEGACY_COUNTER_OFFSET,
    MIN_LEGACY_SAVE_SIZE,
    UNINITIALIZED_BYTE as _UNINITIALIZED_BYTE,
    SaveAnalysis,
    analyze_save,
)

# --- SMW SRAM layout ---------------------------------------------------------

# Backwards-compatible public aliases. The structured parser names this an
# inherited raw counter because 0x8C is not universally an advertised-exit count.
SMW_EXIT_COUNT_OFFSET = LEGACY_COUNTER_OFFSET
MIN_SAVE_SIZE = MIN_LEGACY_SAVE_SIZE
UNINITIALIZED_BYTE = _UNINITIALIZED_BYTE

# No real SMW hack has anywhere near this many exits; larger reads are garbage
# (e.g. FXPak-padded 128KB files that don't use the vanilla offset).
MAX_PLAUSIBLE_EXITS = 120

# Save-file extensions we understand (both are raw SMW SRAM).
SAVE_EXTENSIONS = (".srm", ".sav")

# Privacy-safe diagnostic report format. Reports contain parser and matching
# evidence, but never absolute paths, parent directories, or raw save bytes.
DIAGNOSTIC_SCHEMA_VERSION = 4

# --- Classification verdicts -------------------------------------------------

STATUS_COMPLETED = "completed"          # will be marked completed
STATUS_IN_PROGRESS = "in_progress"      # played but not finished
STATUS_UNCERTAIN = "uncertain"          # can't decide (unreadable / no ref exits)
STATUS_ALREADY_COMPLETED = "already_completed"  # hack already marked done
STATUS_UNMATCHED = "unmatched"          # save file matched no hack

# --- Orphan resolution results (unmatched save -> SMWC lookup) ---------------

RESOLUTION_NONE = ""                 # lookup not attempted yet
RESOLUTION_RESOLVED = "resolved"     # confident single SMWC match, not in collection
RESOLUTION_EXISTS = "exists"         # resolved to a hack already in the collection
RESOLUTION_NO_MATCH = "no_match"     # SMWC search returned no exact-title match
RESOLUTION_AMBIGUOUS = "ambiguous"   # multiple exact matches, can't auto-pick
RESOLUTION_ERROR = "error"           # network / API error during lookup
RESOLUTION_LOCAL = "local"           # user-defined non-SMWC collection entry
SEARCH_RESULTS = "results"         # manual search returned options

ASSOCIATION_CONFIG_KEY = "save_sync_associations"
SAVE_DIRECTORIES_CONFIG_KEY = "save_sync_dirs"
LEGACY_SAVE_DIRECTORY_CONFIG_KEY = "save_sync_dir"
MATCH_SOURCE_COLLECTION = "collection"
MATCH_SOURCE_SAVED_ALIAS = "saved_alias"
MATCH_SOURCE_LOCAL = "local_custom"
AUTO_SCAN_INTERVAL_CHOICES = (5, 15, 30, 60)
DEFAULT_AUTO_SCAN_INTERVAL_MINUTES = 15


def normalize_auto_scan_interval(value):
    """Return a supported review-only background scan interval."""

    try:
        minutes = int(value)
    except (TypeError, ValueError):
        return DEFAULT_AUTO_SCAN_INTERVAL_MINUTES
    if minutes not in AUTO_SCAN_INTERVAL_CHOICES:
        return DEFAULT_AUTO_SCAN_INTERVAL_MINUTES
    return minutes


def read_collected_exits(path):
    """Return the strongest supported progress-counter evidence.

    Checksum-valid standard SMW slots take precedence. The inherited raw byte at
    ``0x8C`` remains a low-confidence fallback only for smaller non-standard
    saves. Expanded SRAM images require a validated profile and otherwise return
    no progress value.
    """

    return analyze_save(path).selected_value


def classify(collected, total, already_completed, mark_all):
    """Decide the completion verdict for a single matched save.

    Args:
        collected (int | None): inherited raw counter from
            :func:`read_collected_exits`.
        total (int): the hack's total exit count (0 if unknown).
        already_completed (bool): hack is already marked completed.
        mark_all (bool): user chose to mark every matched save as completed,
            bypassing the exit-count comparison.
    """
    if already_completed:
        return STATUS_ALREADY_COMPLETED

    if mark_all:
        return STATUS_COMPLETED

    # Exit-count rule (the default, stricter mode).
    if collected is None:
        return STATUS_UNCERTAIN
    if total <= 0:
        # No reference exit count -> the rule can't be applied.
        return STATUS_UNCERTAIN
    # Guard against garbage / oversized reads (e.g. padded FXPak files).
    if collected > max(total * 2, MAX_PLAUSIBLE_EXITS):
        return STATUS_UNCERTAIN
    if collected >= total:
        return STATUS_COMPLETED
    return STATUS_IN_PROGRESS


def _normalize(name):
    """Normalize a title or filename for exact-with-light-normalization matching.

    Strips the directory and extension, applies the same emoji/ASCII cleanup used
    to build ROM filenames (:func:`utils.safe_filename`), drops trailing version
    markers (``v1.1``, ``_v0.3``, `` 1.0``), lowercases, and removes every
    non-alphanumeric character.
    """
    from utils import safe_filename

    base = os.path.splitext(os.path.basename(name))[0]
    base = safe_filename(base).lower()
    # Drop a trailing version marker: optional separator, optional 'v', N(.N)+.
    base = re.sub(r"[\s_-]*v?\d+(?:\.\d+)+\s*$", "", base)
    base = re.sub(r"[^a-z0-9]", "", base)
    return base


def clean_save_directories(value, legacy_directory=""):
    """Return canonical, ordered, duplicate-free save source folders.

    ``save_sync_dir`` from older configurations is accepted as a migration
    fallback. Paths are expanded and made absolute for stable persistence, but
    they are never included in privacy-safe diagnostic exports.
    """

    if isinstance(value, str):
        raw_directories = [value]
    elif isinstance(value, (list, tuple)):
        raw_directories = list(value)
    else:
        raw_directories = []

    if not raw_directories and legacy_directory:
        raw_directories = [legacy_directory]

    cleaned = []
    seen = set()
    for raw_directory in raw_directories:
        if not isinstance(raw_directory, str):
            continue
        stripped = raw_directory.strip()
        if not stripped:
            continue
        directory = os.path.normpath(
            os.path.abspath(os.path.expanduser(stripped))
        )
        identity = os.path.normcase(directory)
        if identity in seen:
            continue
        seen.add(identity)
        cleaned.append(directory)
    return cleaned


def set_save_directories(config_manager, directories):
    """Persist save sources and mirror the first source to the legacy key."""

    if config_manager is None:
        return False
    cleaned = clean_save_directories(directories)
    legacy = cleaned[0] if cleaned else ""
    changed = False

    if config_manager.get(SAVE_DIRECTORIES_CONFIG_KEY, []) != cleaned:
        config_manager.set(SAVE_DIRECTORIES_CONFIG_KEY, cleaned)
        changed = True
    if config_manager.get(LEGACY_SAVE_DIRECTORY_CONFIG_KEY, "") != legacy:
        config_manager.set(LEGACY_SAVE_DIRECTORY_CONFIG_KEY, legacy)
        changed = True
    return changed


def get_save_directories(config_manager):
    """Load save sources and migrate the legacy single-directory setting."""

    if config_manager is None:
        return []
    stored = config_manager.get(SAVE_DIRECTORIES_CONFIG_KEY, [])
    legacy = config_manager.get(LEGACY_SAVE_DIRECTORY_CONFIG_KEY, "")
    cleaned = clean_save_directories(stored, legacy_directory=legacy)
    set_save_directories(config_manager, cleaned)
    return cleaned


def add_save_directory(config_manager, directory):
    """Append one save source, preserving order and suppressing duplicates."""

    directories = get_save_directories(config_manager)
    updated = clean_save_directories([*directories, directory])
    changed = updated != directories
    if changed:
        set_save_directories(config_manager, updated)
    return changed


def remove_save_directory(config_manager, directory):
    """Remove one save source and return whether it was present."""

    directories = get_save_directories(config_manager)
    target = clean_save_directories([directory])
    if not target:
        return False
    target_identity = os.path.normcase(target[0])
    updated = [
        item
        for item in directories
        if os.path.normcase(item) != target_identity
    ]
    if updated == directories:
        return False
    set_save_directories(config_manager, updated)
    return True


def association_key(name):
    """Return the normalized, path-free key used for explicit save matches."""

    return _normalize(os.path.basename(str(name or "")))


def clean_save_associations(value):
    """Return a normalized ``save filename -> SMWC ID`` mapping."""

    if not isinstance(value, dict):
        return {}

    cleaned = {}
    for raw_name, raw_hack_id in value.items():
        key = association_key(raw_name)
        hack_id = str(raw_hack_id or "").strip()
        if key and hack_id:
            cleaned[key] = hack_id
    return cleaned


def get_save_associations(config_manager):
    """Load normalized explicit save matches from an application config."""

    if config_manager is None:
        return {}
    return clean_save_associations(
        config_manager.get(ASSOCIATION_CONFIG_KEY, {})
    )


def remember_save_association(config_manager, save_name, hack_id):
    """Persist one explicit filename-to-hack selection.

    Returns ``True`` when the stored value changed. Existing values for the same
    normalized save filename are replaced, allowing the user to correct a prior
    selection.
    """

    if config_manager is None:
        return False
    key = association_key(save_name)
    target = str(hack_id or "").strip()
    if not key or not target:
        return False

    associations = get_save_associations(config_manager)
    changed = associations.get(key) != target
    if changed:
        associations[key] = target
        config_manager.set(ASSOCIATION_CONFIG_KEY, associations)
    return changed


def forget_save_association(config_manager, save_name):
    """Remove one explicit filename association and return whether it existed."""

    if config_manager is None:
        return False
    key = association_key(save_name)
    associations = get_save_associations(config_manager)
    if not key or key not in associations:
        return False

    del associations[key]
    config_manager.set(ASSOCIATION_CONFIG_KEY, associations)
    return True


def prune_save_associations(associations, existing_ids):
    """Drop associations whose target no longer exists in the collection."""

    cleaned = clean_save_associations(associations)
    valid_ids = {str(hack_id) for hack_id in existing_ids}
    valid = {
        key: hack_id
        for key, hack_id in cleaned.items()
        if hack_id in valid_ids
    }
    return valid, len(cleaned) - len(valid)

def build_hack_index(hacks):
    """Build ``normalized-name -> hack`` map for matching save filenames.

    Each hack is indexed under its normalized title plus the normalized basename
    of every known ROM path (``file_path`` and each ``files[].path``, which are
    already ``safe_filename``-derived). First writer wins on collision so exact
    titles take precedence over path-derived keys.
    """
    index = {}
    for hack in hacks:
        # User-created local entries are linked only through an explicit saved
        # filename association. Treating their title as an automatic match would
        # make "Forget Saved Match" ineffective and could connect unrelated
        # saves that happen to normalize to the same local title.
        if hack.get("local_save_entry"):
            continue

        keys = set()

        title = hack.get("title", "")
        if title:
            keys.add(_normalize(title))

        file_path = hack.get("file_path", "")
        if file_path:
            keys.add(_normalize(file_path))

        for entry in hack.get("files", []) or []:
            path = entry.get("path", "") if isinstance(entry, dict) else ""
            if path:
                keys.add(_normalize(path))

        for key in keys:
            if key and key not in index:
                index[key] = hack
    return index


@dataclass
class SyncCandidate:
    """One save file and the collection change it implies."""

    save_path: str
    save_name: str
    mtime: float
    collected_exits: object  # int, or None when unreadable
    analysis: SaveAnalysis | None = None
    save_size: int = 0
    profile: str = ""
    counter_kind: str = "unknown"
    confidence: str = "none"
    warnings: tuple[str, ...] = ()
    hack_id: str = ""
    title: str = ""
    total_exits: int = 0
    status: str = STATUS_UNMATCHED
    already_completed: bool = False
    # Orphan-resolution state (only used for unmatched saves looked up on SMWC)
    resolution: str = RESOLUTION_NONE
    resolved_hack: object = None      # raw SMWC hack dict for a new import
    resolved_hack_id: str = ""
    local_entry: object = None
    match_source: str = ""
    manual_selection: bool = False

    @property
    def completed_date(self):
        """Save file's last-modified date as ``YYYY-MM-DD`` (empty if unknown)."""
        if not self.mtime:
            return ""
        return datetime.fromtimestamp(self.mtime).strftime("%Y-%m-%d")

    @property
    def will_complete(self):
        return self.status == STATUS_COMPLETED

    @property
    def exits_display(self):
        """e.g. ``'12 / 12'`` (collected / total), ``'? / 12'`` if unreadable."""
        got = self.collected_exits if isinstance(self.collected_exits, int) else "?"
        return f"{got} / {self.total_exits}"

    def evidence(self):
        """Return structured read evidence for diagnostics and later UI work."""

        if self.analysis is not None:
            return self.analysis.as_dict()
        return {
            "path": self.save_path,
            "size": self.save_size,
            "profile": self.profile,
            "confidence": self.confidence,
            "counter_kind": self.counter_kind,
            "selected_value": (
                self.collected_exits
                if isinstance(self.collected_exits, int)
                else None
            ),
            "warnings": list(self.warnings),
            "attempts": [],
        }



def auto_review_candidates(candidates):
    """Return startup-scan results that merit an explicit user review.

    Automatic scans never write collection data. Completed candidates can
    propose a collection update, while unmatched saves may need a manual SMWC
    association. In-progress, uncertain, and already-completed matches remain
    available through a normal manual scan but do not create a startup prompt.
    """

    return [
        candidate
        for candidate in candidates
        if candidate.status == STATUS_COMPLETED or not candidate.hack_id
    ]


def _utc_timestamp(value=None):
    """Return an ISO-8601 UTC timestamp for diagnostic metadata."""

    moment = value or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    else:
        moment = moment.astimezone(timezone.utc)
    return moment.isoformat(timespec="seconds").replace("+00:00", "Z")


def diagnostic_filename(value=None):
    """Return a timestamped default filename for a diagnostic export."""

    moment = value or datetime.now()
    return f"SMWC-Save-Diagnostics-{moment.strftime('%Y%m%d-%H%M%S')}.json"


def _safe_analysis_evidence(candidate):
    """Return candidate evidence with local filesystem paths removed."""

    evidence = dict(candidate.evidence())
    evidence.pop("path", None)
    return evidence


def _diagnostic_match_state(candidate):
    """Return explicit direct, resolved, and effective matching evidence."""

    resolution = str(candidate.resolution or RESOLUTION_NONE)
    direct_hack_id = str(candidate.hack_id or "")
    resolved_hack_id = str(candidate.resolved_hack_id or "")
    resolved = resolution in {RESOLUTION_RESOLVED, RESOLUTION_EXISTS} and bool(
        resolved_hack_id
    )
    local_custom = resolution == RESOLUTION_LOCAL and bool(resolved_hack_id)
    pre_resolved = bool(direct_hack_id) and not resolved and not local_custom
    source = candidate.match_source or MATCH_SOURCE_COLLECTION
    saved_association = pre_resolved and source == MATCH_SOURCE_SAVED_ALIAS
    direct = pre_resolved and not saved_association

    if pre_resolved:
        effective_hack_id = direct_hack_id
    elif resolution == RESOLUTION_EXISTS and resolved_hack_id:
        source = "smwc_existing"
        effective_hack_id = resolved_hack_id
    elif resolution == RESOLUTION_RESOLVED and resolved_hack_id:
        source = "smwc_new"
        effective_hack_id = resolved_hack_id
    elif local_custom:
        source = MATCH_SOURCE_LOCAL
        effective_hack_id = resolved_hack_id
    else:
        source = "none"
        effective_hack_id = ""

    return {
        "direct": direct,
        "resolved_through_smwc": resolved,
        "effective": bool(effective_hack_id),
        "source": source,
        "effective_hack_id": effective_hack_id,
        "saved_association": saved_association,
    }


def _diagnostic_candidate(candidate):
    """Serialize one candidate without paths or raw save contents."""

    save_name = os.path.basename(candidate.save_name or candidate.save_path)
    match_state = _diagnostic_match_state(candidate)
    return {
        "save": {
            "name": save_name,
            "extension": os.path.splitext(save_name)[1].lower(),
            "size": int(candidate.save_size or 0),
            "modified_date": candidate.completed_date or None,
        },
        "analysis": _safe_analysis_evidence(candidate),
        "match": {
            "hack_id": str(candidate.hack_id or ""),
            "title": str(candidate.title or ""),
            "total_exits": int(candidate.total_exits or 0),
            "status": str(candidate.status or STATUS_UNMATCHED),
            "already_completed": bool(candidate.already_completed),
            **match_state,
        },
        "resolution": {
            "status": str(candidate.resolution or RESOLUTION_NONE),
            "resolved_hack_id": str(candidate.resolved_hack_id or ""),
        },
    }


def build_diagnostic_report(candidates, generated_at=None):
    """Build a privacy-safe Save Data Sync diagnostic report.

    The report intentionally excludes absolute paths, parent-directory names,
    raw SRAM bytes, and complete SMWC response objects. It is suitable for issue
    reports and parser research without exposing the user's local directory
    layout.
    """

    rows = sorted(
        (_diagnostic_candidate(candidate) for candidate in candidates),
        key=lambda row: (
            row["save"]["name"].casefold(),
            row["match"]["hack_id"],
        ),
    )
    status_counts = Counter(row["match"]["status"] for row in rows)
    profile_counts = Counter(row["analysis"]["profile"] for row in rows)
    confidence_counts = Counter(row["analysis"]["confidence"] for row in rows)
    resolution_counts = Counter(
        row["resolution"]["status"] or "not_attempted" for row in rows
    )
    direct_match_count = sum(row["match"]["direct"] for row in rows)
    saved_association_count = sum(
        row["match"]["saved_association"] for row in rows
    )
    local_custom_count = sum(
        row["match"]["source"] == MATCH_SOURCE_LOCAL for row in rows
    )
    resolved_match_count = sum(
        row["match"]["resolved_through_smwc"] for row in rows
    )
    effective_match_count = sum(row["match"]["effective"] for row in rows)
    unresolved_count = len(rows) - effective_match_count

    return {
        "schema_version": DIAGNOSTIC_SCHEMA_VERSION,
        "generated_at_utc": _utc_timestamp(generated_at),
        "privacy": {
            "absolute_paths_included": False,
            "parent_directories_included": False,
            "raw_save_bytes_included": False,
        },
        "summary": {
            "candidate_count": len(rows),
            "direct_match_count": direct_match_count,
            "saved_association_count": saved_association_count,
            "local_custom_count": local_custom_count,
            "resolved_through_smwc_count": resolved_match_count,
            "effective_matched_count": effective_match_count,
            "unresolved_count": unresolved_count,
            "matched_count": effective_match_count,
            "unmatched_count": unresolved_count,
            "status_counts": dict(sorted(status_counts.items())),
            "resolution_counts": dict(sorted(resolution_counts.items())),
            "profile_counts": dict(sorted(profile_counts.items())),
            "confidence_counts": dict(sorted(confidence_counts.items())),
        },
        "candidates": rows,
    }


def write_diagnostic_report(destination, candidates, generated_at=None):
    """Write a diagnostic report atomically and return its absolute path."""

    absolute = os.path.abspath(os.fspath(destination))
    parent = os.path.dirname(absolute)
    if parent:
        os.makedirs(parent, exist_ok=True)

    report = build_diagnostic_report(candidates, generated_at=generated_at)
    temporary = absolute + ".tmp"
    try:
        with open(temporary, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(report, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temporary, absolute)
    finally:
        try:
            if os.path.exists(temporary):
                os.remove(temporary)
        except OSError:
            pass
    return absolute


def list_save_files(directory):
    """Return sorted absolute paths of ``.srm``/``.sav`` files in *directory*."""
    found = []
    try:
        entries = os.listdir(directory)
    except OSError:
        return found
    for entry in entries:
        if entry.lower().endswith(SAVE_EXTENSIONS):
            full = os.path.join(directory, entry)
            if os.path.isfile(full):
                found.append(full)
    return sorted(found)


def list_save_files_from_directories(directories):
    """Return unique save files from every configured source folder."""

    found = {}
    for directory in clean_save_directories(directories):
        for path in list_save_files(directory):
            identity = os.path.normcase(os.path.realpath(path))
            found.setdefault(identity, path)
    return sorted(found.values(), key=os.path.normcase)


def _strength(candidate):
    """Sort key for picking the best save among duplicates for one hack."""
    exits = candidate.collected_exits if isinstance(candidate.collected_exits, int) else -1
    return (exits, candidate.mtime)


def _scan_save_paths(paths, hacks, mark_all=False, associations=None):
    """Analyze save *paths* and retain the strongest candidate per hack."""

    index = build_hack_index(hacks)
    hacks_by_id = {str(hack.get("id", "")): hack for hack in hacks}
    association_map = clean_save_associations(associations)
    matched = {}
    unmatched = []

    for path in paths:
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            mtime = 0

        analysis = analyze_save(path)
        collected = analysis.selected_value
        candidate = SyncCandidate(
            save_path=path,
            save_name=os.path.basename(path),
            mtime=mtime,
            collected_exits=collected,
            analysis=analysis,
            save_size=analysis.size,
            profile=analysis.profile,
            counter_kind=analysis.counter_kind,
            confidence=analysis.confidence,
            warnings=analysis.warnings,
        )

        hack = index.get(_normalize(candidate.save_name))
        if hack:
            candidate.match_source = MATCH_SOURCE_COLLECTION
        else:
            associated_id = association_map.get(
                association_key(candidate.save_name), ""
            )
            hack = hacks_by_id.get(associated_id)
            if hack:
                candidate.match_source = MATCH_SOURCE_SAVED_ALIAS

        if not hack:
            unmatched.append(candidate)
            continue

        candidate.hack_id = str(hack.get("id", ""))
        candidate.title = hack.get("title", "")
        candidate.total_exits = int(hack.get("exits", 0) or 0)
        candidate.already_completed = bool(hack.get("completed", False))
        candidate.status = classify(
            collected,
            candidate.total_exits,
            candidate.already_completed,
            mark_all,
        )

        best = matched.get(candidate.hack_id)
        if best is None or _strength(candidate) > _strength(best):
            matched[candidate.hack_id] = candidate

    return list(matched.values()) + unmatched


def scan_saves(directory, hacks, mark_all=False, associations=None):
    """Scan one legacy save directory and return review candidates."""

    return _scan_save_paths(
        list_save_files(directory),
        hacks,
        mark_all=mark_all,
        associations=associations,
    )


def scan_save_directories(
    directories, hacks, mark_all=False, associations=None
):
    """Scan all configured save source folders as one logical collection."""

    return _scan_save_paths(
        list_save_files_from_directories(directories),
        hacks,
        mark_all=mark_all,
        associations=associations,
    )


def apply_candidates(candidates, data_manager):
    """Mark the given candidates completed with their save's last-modified date.

    Sets ``completed_date`` first (from the save mtime) then ``completed=True`` so
    the data manager's auto-today fallback doesn't overwrite the real play date.
    Only ever sets completion on -- never un-completes. Flushes to disk and
    returns the number of hacks updated.
    """
    applied = 0
    for candidate in candidates:
        if not candidate.hack_id:
            continue
        if candidate.completed_date:
            data_manager.update_hack(candidate.hack_id, "completed_date", candidate.completed_date)
        data_manager.update_hack(candidate.hack_id, "completed", True)
        applied += 1

    if applied:
        data_manager.force_save()
    return applied


# --- Orphan import (unmatched save -> SMWC lookup -> collection entry) --------

def make_search_query(name):
    """Turn a save filename into a human-readable SMWC name-search query.

    Keeps words (unlike :func:`_normalize`): strips the extension, turns
    separators into spaces, drops version tokens, and collapses whitespace.
    ``"le_plume_v0.3.srm"`` -> ``"le plume"``.
    """
    base = os.path.splitext(os.path.basename(name))[0]
    base = base.replace("_", " ").replace("-", " ")
    base = re.sub(r"\bv?\d+(?:\.\d+)+\b", " ", base)  # version tokens like v1.1 / 0.3
    base = re.sub(r"\s+", " ", base).strip()
    return base


def _smwc_entry_fields(hack):
    """Build the metadata portion of a processed.json entry from an SMWC hack.

    Mirrors how the download pipeline stores hacks (:mod:`api_pipeline`) so an
    imported entry is indistinguishable from a downloaded one -- minus the ROM
    (``file_path`` is empty until the user actually downloads it).
    """
    from utils import (
        clean_hack_title, get_sorted_folder_name,
        DIFFICULTY_LOOKUP, normalize_types,
    )

    raw = hack.get("raw_fields", {}) or {}
    raw_diff = raw.get("difficulty") or ""
    if raw_diff in (None, "N/A"):
        raw_diff = ""
    display_diff = DIFFICULTY_LOOKUP.get(raw_diff, "No Difficulty")
    types = normalize_types(raw.get("type", "standard")) or ["standard"]

    time_ts = int(hack.get("time", 0) or 0)
    date_str = ""
    if time_ts:
        try:
            date_str = datetime.fromtimestamp(time_ts).strftime("%Y-%m-%d")
        except (ValueError, OverflowError, OSError):
            date_str = ""

    return {
        "title": clean_hack_title(hack.get("name", "")),
        "difficulty_id": raw_diff,
        "current_difficulty": display_diff,
        "folder_name": get_sorted_folder_name(display_diff),
        "hack_type": types[0],
        "hack_types": types,
        "hall_of_fame": bool(raw.get("hof", False)),
        "sa1_compatibility": bool(raw.get("sa1", False)),
        "collaboration": bool(raw.get("collab", False)),
        "demo": bool(raw.get("demo", False)),
        "authors": hack.get("authors", []) or [],
        "exits": int(raw.get("length", hack.get("length", 0)) or 0),
        "time": time_ts,
        "date": date_str,
        "obsolete": bool(raw.get("obsolete", False)),
        "file_path": "",
        "additional_paths": [],
    }


def local_entry_id(save_name, title):
    """Return a deterministic path-free ID for a user-defined save entry."""

    identity = f"{association_key(save_name)}\0{_normalize(title)}"
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
    return f"usr_save_{digest}"


def build_local_entry(save_name, title, total_exits):
    """Build a collection entry for a hack that is not listed on SMWCentral."""

    from utils import get_sorted_folder_name

    clean_title = str(title or "").strip()
    if not clean_title:
        raise ValueError("A local hack title is required.")
    try:
        exits = int(total_exits)
    except (TypeError, ValueError) as exc:
        raise ValueError("Total exits must be a whole number.") from exc
    if exits < 0 or exits > 999:
        raise ValueError("Total exits must be between 0 and 999.")

    hack_id = local_entry_id(save_name, clean_title)
    return hack_id, {
        "title": clean_title,
        "difficulty_id": "",
        "current_difficulty": "No Difficulty",
        "folder_name": get_sorted_folder_name("No Difficulty"),
        "hack_type": "standard",
        "hack_types": ["standard"],
        "hall_of_fame": False,
        "sa1_compatibility": False,
        "collaboration": False,
        "demo": False,
        "authors": [],
        "exits": exits,
        "time": 0,
        "date": "",
        "obsolete": False,
        "file_path": "",
        "additional_paths": [],
        "local_save_entry": True,
    }


def resolution_for_local_entry(save_name, title, total_exits, existing_ids):
    """Build an explicit resolution for a non-SMWC local collection entry."""

    hack_id, entry = build_local_entry(save_name, title, total_exits)
    existing = {str(existing_id) for existing_id in existing_ids}
    if hack_id in existing:
        return {
            "status": RESOLUTION_EXISTS,
            "hack": None,
            "hack_id": hack_id,
            "local_entry": entry,
        }
    return {
        "status": RESOLUTION_LOCAL,
        "hack": None,
        "hack_id": hack_id,
        "local_entry": entry,
    }


def resolve_orphan(save_name, existing_ids, fetch_fn=None, log=None):
    """Resolve an unmatched save filename to an SMWC hack via name search.

    Returns ``{"status": RESOLUTION_*, "hack": <dict|None>, "hack_id": str}``.

    Args:
        save_name: the save file's name (with or without extension).
        existing_ids: set of hack IDs already in the collection (as strings);
            an exact match already present is reported as ``RESOLUTION_EXISTS``.
        fetch_fn: injectable ``fetch_hack_list``-style callable (for testing);
            defaults to :func:`api_pipeline.fetch_hack_list`.
    """
    if fetch_fn is None:
        from api_pipeline import fetch_hack_list as fetch_fn

    query = make_search_query(save_name)
    if not query:
        return {"status": RESOLUTION_NO_MATCH, "hack": None, "hack_id": ""}

    try:
        result = fetch_fn({"name": query}, log=log)
    except Exception as exc:  # network / parse errors -> caller can retry
        if log:
            log(f"SMWC lookup failed for '{query}': {exc}", "Error")
        return {"status": RESOLUTION_ERROR, "hack": None, "hack_id": ""}

    data = result.get("data", []) if isinstance(result, dict) else []
    target = _normalize(save_name)
    exact = [h for h in data if _normalize(h.get("name", "")) == target]

    if not exact:
        return {"status": RESOLUTION_NO_MATCH, "hack": None, "hack_id": ""}

    if len(exact) > 1:
        # Prefer the single non-obsolete version if that disambiguates.
        live = [h for h in exact if not (h.get("raw_fields", {}) or {}).get("obsolete")]
        if len(live) == 1:
            exact = live
        else:
            return {"status": RESOLUTION_AMBIGUOUS, "hack": None, "hack_id": ""}

    hack = exact[0]
    hack_id = str(hack.get("id", ""))
    if not hack_id:
        return {"status": RESOLUTION_NO_MATCH, "hack": None, "hack_id": ""}

    status = RESOLUTION_EXISTS if hack_id in existing_ids else RESOLUTION_RESOLVED
    return {"status": status, "hack": hack, "hack_id": hack_id}


def search_orphan_options(
    query, existing_ids, fetch_fn=None, log=None, limit=50
):
    """Return deterministic, user-selectable SMWC results for a manual query.

    Unlike :func:`resolve_orphan`, this function never chooses a hack. It only
    returns options for an explicit user selection, preserving the strict exact
    title rule used by automatic orphan resolution.
    """

    if fetch_fn is None:
        from api_pipeline import fetch_hack_list as fetch_fn

    cleaned_query = make_search_query(query)
    if not cleaned_query:
        return {
            "status": RESOLUTION_NO_MATCH,
            "query": "",
            "options": [],
        }

    try:
        result = fetch_fn({"name": cleaned_query}, log=log)
    except Exception as exc:
        if log:
            log(
                f"SMWC manual search failed for '{cleaned_query}': {exc}",
                "Error",
            )
        return {
            "status": RESOLUTION_ERROR,
            "query": cleaned_query,
            "options": [],
        }

    data = result.get("data", []) if isinstance(result, dict) else []
    if not isinstance(data, list):
        data = []

    target = _normalize(cleaned_query)
    existing = {str(hack_id) for hack_id in existing_ids}
    options = []

    for hack in data:
        if not isinstance(hack, dict):
            continue
        hack_id = str(hack.get("id", ""))
        name = str(hack.get("name", "") or "").strip()
        if not hack_id or not name:
            continue

        raw = hack.get("raw_fields", {}) or {}
        try:
            difficulty = _smwc_entry_fields(hack)["current_difficulty"]
        except (KeyError, TypeError, ValueError):
            difficulty = ""

        options.append(
            {
                "hack_id": hack_id,
                "name": name,
                "exact_title": _normalize(name) == target,
                "obsolete": bool(raw.get("obsolete", False)),
                "in_collection": hack_id in existing,
                "difficulty": difficulty,
                "hack": hack,
            }
        )

    options.sort(
        key=lambda option: (
            not option["exact_title"],
            option["obsolete"],
            not option["in_collection"],
            option["name"].casefold(),
            option["hack_id"],
        )
    )

    deduplicated = []
    seen_ids = set()
    result_limit = max(1, int(limit))
    for option in options:
        if option["hack_id"] in seen_ids:
            continue
        seen_ids.add(option["hack_id"])
        deduplicated.append(option)
        if len(deduplicated) >= result_limit:
            break

    return {
        "status": SEARCH_RESULTS if deduplicated else RESOLUTION_NO_MATCH,
        "query": cleaned_query,
        "options": deduplicated,
    }


def resolution_for_selected_hack(hack, existing_ids):
    """Build a resolution for a hack the user explicitly selected."""

    if not isinstance(hack, dict):
        return {"status": RESOLUTION_NO_MATCH, "hack": None, "hack_id": ""}

    hack_id = str(hack.get("id", ""))
    if not hack_id:
        return {"status": RESOLUTION_NO_MATCH, "hack": None, "hack_id": ""}

    existing = {str(existing_id) for existing_id in existing_ids}
    status = RESOLUTION_EXISTS if hack_id in existing else RESOLUTION_RESOLVED
    return {"status": status, "hack": hack, "hack_id": hack_id}


def attach_resolution(candidate, resolution, data_manager, mark_all=False):
    """Record an SMWC lookup result on an unmatched candidate and reclassify it.

    - ``EXISTS``  -> becomes a normal completion update on the existing hack.
    - ``RESOLVED``-> becomes an importable new-hack candidate (status reflects
      whether its save meets the completion rule).
    Other statuses just annotate the candidate for display.
    """
    status = resolution.get("status", RESOLUTION_NO_MATCH)
    hack = resolution.get("hack")
    hack_id = resolution.get("hack_id", "")
    local_entry = resolution.get("local_entry")

    candidate.resolution = status
    candidate.resolved_hack = hack
    candidate.resolved_hack_id = hack_id
    candidate.local_entry = local_entry

    if status == RESOLUTION_EXISTS and hack_id in data_manager.data:
        existing = data_manager.data[hack_id]
        candidate.hack_id = hack_id
        candidate.title = existing.get("title") or (hack.get("name", "") if hack else "")
        candidate.total_exits = int(existing.get("exits", 0) or 0)
        candidate.already_completed = bool(existing.get("completed", False))
        candidate.status = classify(
            candidate.collected_exits, candidate.total_exits,
            candidate.already_completed, mark_all,
        )
    elif status == RESOLUTION_RESOLVED and hack:
        fields = _smwc_entry_fields(hack)
        candidate.title = fields["title"]
        candidate.total_exits = fields["exits"]
        candidate.status = classify(
            candidate.collected_exits, candidate.total_exits, False, mark_all,
        )
    elif status == RESOLUTION_LOCAL and isinstance(local_entry, dict):
        candidate.title = local_entry["title"]
        candidate.total_exits = int(local_entry.get("exits", 0) or 0)
        candidate.status = classify(
            candidate.collected_exits, candidate.total_exits, False, mark_all,
        )
    return candidate


def import_local_orphan(candidate, data_manager, mark_all=False):
    """Create a user-defined collection entry for an explicitly matched save."""

    entry = candidate.local_entry
    hack_id = str(candidate.resolved_hack_id or "")
    if (
        candidate.resolution != RESOLUTION_LOCAL
        or not isinstance(entry, dict)
        or not hack_id
        or hack_id in data_manager.data
    ):
        return False

    entry = dict(entry)
    status = classify(candidate.collected_exits, entry["exits"], False, mark_all)
    completed = status == STATUS_COMPLETED
    entry.update({
        "completed": completed,
        "completed_date": candidate.completed_date if completed else "",
        "personal_rating": 0,
        "notes": "",
        "time_to_beat": 0,
    })
    data_manager.add_user_hack(hack_id, entry)
    return True


def import_orphan(candidate, data_manager, mark_all=False):
    """Create a new collection entry for a RESOLVED orphan candidate.

    Keyed by the real SMWC ID so a later download/update merges into the same
    entry instead of duplicating. No-op (returns False) if the id already exists
    or the candidate wasn't resolved to a new hack.
    """
    hack = candidate.resolved_hack
    hack_id = candidate.resolved_hack_id
    if not hack or not hack_id or hack_id in data_manager.data:
        return False

    entry = _smwc_entry_fields(hack)
    status = classify(candidate.collected_exits, entry["exits"], False, mark_all)
    completed = status == STATUS_COMPLETED
    entry.update({
        "completed": completed,
        "completed_date": candidate.completed_date if completed else "",
        "personal_rating": 0,
        "notes": "",
        "time_to_beat": 0,
    })
    data_manager.add_user_hack(hack_id, entry)
    return True
