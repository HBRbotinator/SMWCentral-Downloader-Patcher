"""Save Data Sync source-folder policy and path-scoped association helpers.

The legacy :mod:`save_sync` module deliberately keeps its flat-folder scanning
and filename association contracts.  This module layers the v5.1 configured
source behavior on top:

* recursion is opt-in per configured source and defaults off;
* the same physical save is scanned once even when configured roots overlap;
* explicit matches for nested saves are scoped to source + relative path, so
  equal filenames in different subfolders do not overwrite each other;
* legacy filename-only aliases remain valid for unique/top-level saves.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import hashlib
import os
from typing import Iterable, Mapping

import save_sync

RECURSIVE_DIRECTORIES_CONFIG_KEY = "save_sync_recursive_dirs"
PATH_ASSOCIATIONS_CONFIG_KEY = "save_sync_path_associations"
_PATH_ASSOCIATION_VERSION = "v1"


@dataclass(frozen=True)
class DiscoveredSave:
    path: str
    source_root: str


def _canonical_directory(directory):
    try:
        raw = os.fspath(directory)
    except TypeError:
        return ""
    cleaned = save_sync.clean_save_directories([raw])
    return cleaned[0] if cleaned else ""


def _directory_identity(directory):
    canonical = _canonical_directory(directory)
    if not canonical:
        return ""
    return os.path.normcase(os.path.realpath(canonical))


def clean_recursive_save_directories(value, configured_directories=None):
    """Return canonical recursive sources, optionally limited to configured roots."""

    raw = value if isinstance(value, (list, tuple)) else []
    configured = (
        []
        if configured_directories is None
        else save_sync.clean_save_directories(configured_directories)
    )
    allowed = {
        _directory_identity(directory): directory
        for directory in configured
        if _directory_identity(directory)
    }
    cleaned = []
    seen = set()
    for directory in save_sync.clean_save_directories(raw):
        identity = _directory_identity(directory)
        if not identity or identity in seen:
            continue
        if configured_directories is not None and identity not in allowed:
            continue
        seen.add(identity)
        cleaned.append(allowed.get(identity, directory))
    return cleaned


def get_recursive_save_directories(config_manager, directories=None):
    """Load per-source recursion flags, pruning entries for removed sources."""

    if config_manager is None:
        return []
    configured = (
        save_sync.get_save_directories(config_manager)
        if directories is None
        else save_sync.clean_save_directories(directories)
    )
    raw = config_manager.get(RECURSIVE_DIRECTORIES_CONFIG_KEY, [])
    cleaned = clean_recursive_save_directories(raw, configured)
    if raw != cleaned:
        config_manager.set(RECURSIVE_DIRECTORIES_CONFIG_KEY, cleaned)
    return cleaned


def is_save_directory_recursive(config_manager, directory):
    target = _directory_identity(directory)
    return bool(target) and target in {
        _directory_identity(item)
        for item in get_recursive_save_directories(config_manager)
    }


def set_save_directory_recursive(config_manager, directory, recursive):
    """Persist the opt-in recursion flag for one already configured source."""

    if config_manager is None:
        return False
    configured = save_sync.get_save_directories(config_manager)
    target = _canonical_directory(directory)
    target_identity = _directory_identity(target)
    if not target_identity or target_identity not in {
        _directory_identity(item) for item in configured
    }:
        raise ValueError("Save folder must be configured before changing recursion.")

    current = get_recursive_save_directories(config_manager, configured)
    current_by_id = {_directory_identity(item): item for item in current}
    if recursive:
        current_by_id[target_identity] = target
    else:
        current_by_id.pop(target_identity, None)
    updated = [
        directory
        for directory in configured
        if _directory_identity(directory) in current_by_id
    ]
    if updated == current:
        return False
    config_manager.set(RECURSIVE_DIRECTORIES_CONFIG_KEY, updated)
    return True


def _source_token(source_root):
    identity = _directory_identity(source_root)
    if not identity:
        return ""
    return hashlib.sha256(identity.encode("utf-8", errors="surrogatepass")).hexdigest()[:16]


def _normalized_relative_path(source_root, save_path):
    source = os.path.realpath(_canonical_directory(source_root))
    path = os.path.realpath(os.path.abspath(os.path.expanduser(os.fspath(save_path))))
    try:
        if os.path.commonpath([source, path]) != source:
            return ""
    except (OSError, ValueError):
        return ""
    relative = os.path.relpath(path, source)
    if relative in ("", ".") or relative == os.pardir or relative.startswith(os.pardir + os.sep):
        return ""
    normalized = os.path.normcase(os.path.normpath(relative))
    return normalized.replace("\\", "/")


def scoped_association_key(source_root, save_path):
    """Return a source+relative-path key without embedding an absolute path."""

    token = _source_token(source_root)
    relative = _normalized_relative_path(source_root, save_path)
    if not token or not relative:
        return ""
    return f"{_PATH_ASSOCIATION_VERSION}:{token}:{relative}"


def _source_prefix(source_root):
    token = _source_token(source_root)
    return f"{_PATH_ASSOCIATION_VERSION}:{token}:" if token else ""


def clean_path_associations(value):
    """Return well-formed scoped-association config without reinterpreting keys."""

    if not isinstance(value, dict):
        return {}
    cleaned = {}
    prefix = _PATH_ASSOCIATION_VERSION + ":"
    for raw_key, raw_target in value.items():
        if not isinstance(raw_key, str):
            continue
        key = raw_key.strip()
        target = str(raw_target or "").strip()
        if not key.startswith(prefix) or key.count(":") < 2 or not target:
            continue
        cleaned[key] = target
    return cleaned


def get_path_associations(config_manager):
    if config_manager is None:
        return {}
    raw = config_manager.get(PATH_ASSOCIATIONS_CONFIG_KEY, {})
    cleaned = clean_path_associations(raw)
    if raw != cleaned:
        config_manager.set(PATH_ASSOCIATIONS_CONFIG_KEY, cleaned)
    return cleaned


def prune_path_associations(value, existing_ids):
    cleaned = clean_path_associations(value)
    valid_ids = {str(hack_id) for hack_id in existing_ids}
    valid = {
        key: target
        for key, target in cleaned.items()
        if target in valid_ids
    }
    return valid, len(cleaned) - len(valid)


def _recursive_save_files(directory):
    """Return recursive save files without following directory symlinks."""

    root = _canonical_directory(directory)
    if not root:
        return []
    found = []
    pending = [root]
    while pending:
        current = pending.pop()
        try:
            entries = sorted(os.scandir(current), key=lambda entry: entry.name.casefold())
        except OSError:
            continue
        child_directories = []
        for entry in entries:
            try:
                if entry.is_dir(follow_symlinks=False):
                    child_directories.append(entry.path)
                    continue
                if (
                    entry.name.lower().endswith(save_sync.SAVE_EXTENSIONS)
                    and entry.is_file(follow_symlinks=False)
                ):
                    found.append(os.path.abspath(entry.path))
            except OSError:
                continue
        # Stack in reverse so the lexical order remains stable when popped.
        pending.extend(reversed(child_directories))
    return sorted(found, key=os.path.normcase)


def discover_save_files(directories, recursive_directories=()):
    """Discover unique saves and retain the most-specific configured source root."""

    configured = save_sync.clean_save_directories(directories)
    recursive_ids = {
        _directory_identity(item)
        for item in clean_recursive_save_directories(recursive_directories, configured)
    }
    discovered = {}
    for source in configured:
        source_id = _directory_identity(source)
        paths = (
            _recursive_save_files(source)
            if source_id in recursive_ids
            else save_sync.list_save_files(source)
        )
        for path in paths:
            identity = os.path.normcase(os.path.realpath(path))
            row = DiscoveredSave(path=os.path.abspath(path), source_root=source)
            previous = discovered.get(identity)
            if previous is None or len(_directory_identity(source)) > len(
                _directory_identity(previous.source_root)
            ):
                discovered[identity] = row
    return sorted(discovered.values(), key=lambda row: os.path.normcase(row.path))


def source_for_save_path(config_manager, save_path):
    """Return the most-specific configured source that is allowed to discover a save."""

    if config_manager is None:
        return ""
    directories = save_sync.get_save_directories(config_manager)
    recursive_ids = {
        _directory_identity(item)
        for item in get_recursive_save_directories(config_manager, directories)
    }
    path = os.path.realpath(os.path.abspath(os.path.expanduser(os.fspath(save_path))))
    candidates = []
    for source in directories:
        source_real = os.path.realpath(source)
        try:
            if os.path.commonpath([source_real, path]) != source_real:
                continue
        except (OSError, ValueError):
            continue
        relative = os.path.relpath(path, source_real)
        if relative in ("", "."):
            continue
        nested = os.path.dirname(relative) not in ("", ".")
        if nested and _directory_identity(source) not in recursive_ids:
            continue
        candidates.append(source)
    if not candidates:
        return ""
    return max(candidates, key=lambda item: len(_directory_identity(item)))


def _is_nested(source_root, save_path):
    relative = _normalized_relative_path(source_root, save_path)
    return bool(relative) and "/" in relative


def _save_name_occurrence_count(config_manager, save_path):
    """Count currently discoverable saves sharing this normalized basename."""

    if config_manager is None:
        return 0
    directories = save_sync.get_save_directories(config_manager)
    recursive = get_recursive_save_directories(config_manager, directories)
    wanted = save_sync.association_key(os.path.basename(os.fspath(save_path)))
    if not wanted:
        return 0
    return sum(
        1
        for row in discover_save_files(directories, recursive)
        if save_sync.association_key(os.path.basename(row.path)) == wanted
    )


def remember_candidate_association(config_manager, candidate, hack_id):
    """Remember an explicit match without letting equal filenames collide."""

    if config_manager is None:
        return False
    target = str(hack_id or "").strip()
    if not target:
        return False
    source = source_for_save_path(config_manager, candidate.save_path)
    if not source:
        return save_sync.remember_save_association(
            config_manager, candidate.save_name, target
        )

    nested = _is_nested(source, candidate.save_path)
    duplicate_name = _save_name_occurrence_count(config_manager, candidate.save_path) > 1
    if not nested and not duplicate_name:
        # Preserve the established portable filename alias for the ordinary
        # unambiguous top-level case.
        return save_sync.remember_save_association(
            config_manager, candidate.save_name, target
        )

    key = scoped_association_key(source, candidate.save_path)
    associations = get_path_associations(config_manager)
    if not key or associations.get(key) == target:
        return False
    associations[key] = target
    config_manager.set(PATH_ASSOCIATIONS_CONFIG_KEY, associations)
    return True


def forget_candidate_association(config_manager, candidate):
    """Forget only the association shape applicable to this save candidate."""

    if config_manager is None:
        return False
    source = source_for_save_path(config_manager, candidate.save_path)
    if not source:
        return save_sync.forget_save_association(
            config_manager, candidate.save_name
        )

    nested = _is_nested(source, candidate.save_path)
    duplicate_name = _save_name_occurrence_count(config_manager, candidate.save_path) > 1
    if not nested and not duplicate_name:
        return save_sync.forget_save_association(
            config_manager, candidate.save_name
        )

    key = scoped_association_key(source, candidate.save_path)
    associations = get_path_associations(config_manager)
    if not key or key not in associations:
        return False
    del associations[key]
    config_manager.set(PATH_ASSOCIATIONS_CONFIG_KEY, associations)
    return True


def remove_associations_for_hack(config_manager, hack_id):
    """Remove both legacy and path-scoped aliases targeting one Collection ID."""

    if config_manager is None:
        return 0
    target = str(hack_id or "").strip()
    removed = 0

    legacy = save_sync.get_save_associations(config_manager)
    kept_legacy = {key: value for key, value in legacy.items() if value != target}
    removed += len(legacy) - len(kept_legacy)
    if kept_legacy != legacy:
        config_manager.set(save_sync.ASSOCIATION_CONFIG_KEY, kept_legacy)

    scoped = get_path_associations(config_manager)
    kept_scoped = {key: value for key, value in scoped.items() if value != target}
    removed += len(scoped) - len(kept_scoped)
    if kept_scoped != scoped:
        config_manager.set(PATH_ASSOCIATIONS_CONFIG_KEY, kept_scoped)
    return removed


def remove_source_state(config_manager, directory):
    """Drop recursion/path-alias state owned by one removed source folder."""

    if config_manager is None:
        return False
    changed = False
    remaining = get_recursive_save_directories(config_manager)
    target_id = _directory_identity(directory)
    updated_recursive = [
        item for item in remaining if _directory_identity(item) != target_id
    ]
    if updated_recursive != remaining:
        config_manager.set(RECURSIVE_DIRECTORIES_CONFIG_KEY, updated_recursive)
        changed = True

    prefix = _source_prefix(directory)
    scoped = get_path_associations(config_manager)
    if prefix:
        kept = {key: value for key, value in scoped.items() if not key.startswith(prefix)}
        if kept != scoped:
            config_manager.set(PATH_ASSOCIATIONS_CONFIG_KEY, kept)
            changed = True
    return changed


def _candidate_strength(candidate):
    exits = candidate.collected_exits if isinstance(candidate.collected_exits, int) else -1
    return exits, candidate.mtime


def _display_name(source_root, save_path):
    source = os.path.realpath(_canonical_directory(source_root))
    path = os.path.realpath(os.path.abspath(os.path.expanduser(os.fspath(save_path))))
    try:
        if os.path.commonpath([source, path]) != source:
            return os.path.basename(save_path)
    except (OSError, ValueError):
        return os.path.basename(save_path)
    relative = os.path.normpath(os.path.relpath(path, source))
    if relative in ("", ".") or relative == os.pardir or relative.startswith(os.pardir + os.sep):
        return os.path.basename(save_path)
    # Keep ordinary flat-source presentation unchanged. Nested saves display
    # their relative folder, preserving user-visible path casing.
    return relative if os.path.dirname(relative) not in ("", ".") else os.path.basename(save_path)


def scan_save_directories(
    config_manager,
    directories,
    hacks,
    mark_all=False,
    associations=None,
):
    """Scan configured sources with per-folder recursion and scoped aliases."""

    configured = save_sync.clean_save_directories(directories)
    recursive = get_recursive_save_directories(config_manager, configured)
    discovered = discover_save_files(configured, recursive)
    legacy = (
        save_sync.get_save_associations(config_manager)
        if associations is None
        else save_sync.clean_save_associations(associations)
    )
    scoped = get_path_associations(config_manager)
    hacks_by_id = {str(hack.get("id", "")): hack for hack in hacks}
    filename_counts = Counter(
        save_sync.association_key(os.path.basename(row.path)) for row in discovered
    )

    matched = {}
    unmatched = []
    for row in discovered:
        basename = os.path.basename(row.path)
        filename_key = save_sync.association_key(basename)
        scoped_target = scoped.get(scoped_association_key(row.source_root, row.path), "")

        if scoped_target and scoped_target in hacks_by_id:
            # A reviewed path-specific alias is stronger than filename/title
            # evidence for this exact save path.
            scan_hacks = [hacks_by_id[scoped_target]]
            scan_associations = {filename_key: scoped_target}
        else:
            scan_hacks = hacks
            legacy_target = legacy.get(filename_key, "") if filename_counts[filename_key] == 1 else ""
            scan_associations = {filename_key: legacy_target} if legacy_target else {}

        rows = save_sync._scan_save_paths(
            [row.path],
            scan_hacks,
            mark_all=mark_all,
            associations=scan_associations,
        )
        if not rows:
            continue
        candidate = rows[0]
        candidate.save_name = _display_name(row.source_root, row.path)
        candidate.save_source_root = row.source_root
        if scoped_target and candidate.hack_id == scoped_target:
            candidate.match_source = save_sync.MATCH_SOURCE_SAVED_ALIAS

        if not candidate.hack_id:
            unmatched.append(candidate)
            continue
        current = matched.get(candidate.hack_id)
        if current is None or _candidate_strength(candidate) > _candidate_strength(current):
            matched[candidate.hack_id] = candidate

    return list(matched.values()) + unmatched


__all__ = [
    "DiscoveredSave",
    "PATH_ASSOCIATIONS_CONFIG_KEY",
    "RECURSIVE_DIRECTORIES_CONFIG_KEY",
    "clean_path_associations",
    "clean_recursive_save_directories",
    "discover_save_files",
    "forget_candidate_association",
    "get_path_associations",
    "get_recursive_save_directories",
    "is_save_directory_recursive",
    "prune_path_associations",
    "remember_candidate_association",
    "remove_associations_for_hack",
    "remove_source_state",
    "scan_save_directories",
    "scoped_association_key",
    "set_save_directory_recursive",
    "source_for_save_path",
]
