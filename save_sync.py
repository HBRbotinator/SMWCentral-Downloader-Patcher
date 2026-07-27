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

import os
import re
from dataclasses import dataclass
from datetime import datetime

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


def build_hack_index(hacks):
    """Build ``normalized-name -> hack`` map for matching save filenames.

    Each hack is indexed under its normalized title plus the normalized basename
    of every known ROM path (``file_path`` and each ``files[].path``, which are
    already ``safe_filename``-derived). First writer wins on collision so exact
    titles take precedence over path-derived keys.
    """
    index = {}
    for hack in hacks:
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


def _strength(candidate):
    """Sort key for picking the best save among duplicates for one hack."""
    exits = candidate.collected_exits if isinstance(candidate.collected_exits, int) else -1
    return (exits, candidate.mtime)


def scan_saves(directory, hacks, mark_all=False):
    """Scan *directory* and return a list of :class:`SyncCandidate`.

    When several saves map to the same hack (e.g. ``le_plume`` v0.1/0.2/0.3), the
    strongest one is kept -- highest collected exits, then newest mtime. Unmatched
    saves are all returned so the UI can report them.
    """
    index = build_hack_index(hacks)
    matched = {}       # hack_id -> best SyncCandidate
    unmatched = []

    for path in list_save_files(directory):
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
        if not hack:
            unmatched.append(candidate)
            continue

        candidate.hack_id = hack.get("id", "")
        candidate.title = hack.get("title", "")
        candidate.total_exits = int(hack.get("exits", 0) or 0)
        candidate.already_completed = bool(hack.get("completed", False))
        candidate.status = classify(
            collected, candidate.total_exits, candidate.already_completed, mark_all
        )

        best = matched.get(candidate.hack_id)
        if best is None or _strength(candidate) > _strength(best):
            matched[candidate.hack_id] = candidate

    return list(matched.values()) + unmatched


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

    candidate.resolution = status
    candidate.resolved_hack = hack
    candidate.resolved_hack_id = hack_id

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
    return candidate


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
