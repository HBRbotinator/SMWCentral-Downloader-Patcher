"""
SMWCentral API Pipeline
Core downloading and processing functionality for SMWCentral hacks

Copyright (c) 2025 iamtheratio
Licensed under the MIT License - see LICENSE file for details
"""

import requests
import os
import tempfile
import time
from datetime import datetime
from pathlib import Path

from utils import (
    safe_filename, get_sorted_folder_name,
    DIFFICULTY_LOOKUP, DIFFICULTY_KEYMAP,
    load_processed, save_processed, make_output_path,
    TYPE_KEYMAP, TYPE_DISPLAY_LOOKUP,
    title_case, clean_hack_title, PROCESSED_JSON_PATH  # Import the new function
)
from smwc_api_proxy import smwc_api_get
from patch_handler import PatchHandler
from rom_filename_policy import build_patched_rom_filename
from rom_asset_metadata import build_tool_patch_rom_asset, merge_collection_rom_assets

# Global cancellation flag
_cancel_operation = False

def cancel_pipeline():
    """Cancel the current pipeline operation"""
    global _cancel_operation
    _cancel_operation = True

def reset_cancel_flag():
    """Reset the cancellation flag"""
    global _cancel_operation
    _cancel_operation = False

def is_cancelled():
    """Check if operation was cancelled"""
    global _cancel_operation
    return _cancel_operation


def extract_smwc_rating(record):
    """Return a normalized SMWC rating, or None when metadata is absent."""
    if not isinstance(record, dict) or "rating" not in record:
        return None

    value = record.get("rating")
    if value is None:
        return None
    if isinstance(value, str) and value.strip().lower() in {
        "", "n/a", "none", "unknown"
    }:
        return None

    try:
        rating = float(value)
    except (TypeError, ValueError):
        return None

    if not 0 <= rating <= 5:
        return None
    return round(rating, 2)


def normalize_smwc_rating(value):
    """Normalize an API rating for persistence, defaulting to unrated."""
    rating = extract_smwc_rating({"rating": value})
    return 0 if rating is None else rating


def _is_smwc_hack_id(hack_id):
    """Return whether a Collection identity can represent an SMWC file ID."""
    return str(hack_id).strip().isdigit()


def _metadata_still_missing(existing, fetched):
    needs_time = not existing.get("date") or not existing.get("time")
    needs_rating = extract_smwc_rating(existing) is None
    has_time = bool(fetched.get("time"))
    has_rating = "rating" in fetched
    return (needs_time and not has_time) or (needs_rating and not has_rating)

def _fetch_hack_list_smwc(config, page=1, waiting_mode=False, log=None):
    """Direct SMWCentral list fallback, including waiting submissions."""
    params = {
        "a": "getsectionlist",
        "s": "smwhacks",
        "n": page,
        "u": "1" if waiting_mode else "0"
    }

    # Add order parameter if specified
    if "order" in config:
        params["o"] = config["order"]

    # Handle difficulty filtering with "No Difficulty" support
    difficulties = config.get("difficulties", [])
    has_no_difficulty = "no difficulty" in difficulties
    regular_difficulties = [d for d in difficulties if d != "no difficulty"]

    for key, values in config.items():
        if key == "difficulties" and values:
            if regular_difficulties and not has_no_difficulty:
                converted = []
                for d in regular_difficulties:
                    if d in DIFFICULTY_KEYMAP:
                        diff_key = DIFFICULTY_KEYMAP[d]
                        if diff_key:
                            converted.append(f"diff_{diff_key}")
                if converted:
                    params["f[difficulty][]"] = converted
        elif key == "name" and values:
            # Handle name search - direct text search
            params["f[name]"] = values
        elif key == "author" and values:
            # Handle author search - direct text search
            params["f[author]"] = values
        elif key == "tags" and values:
            # Handle tags search - comma-separated
            if isinstance(values, list):
                params["f[tags]"] = ", ".join(values)
            else:
                params["f[tags]"] = values
        elif key == "description" and values:
            # Handle description search - direct text search
            params["f[description]"] = values
        elif key != "waiting" and values:
            # Special handling for different parameter types
            if key == "type":
                # Type parameter always needs array format
                if isinstance(values, list):
                    params["f[type][]"] = values
                else:
                    params["f[type][]"] = [values]
            else:
                # Other filters (hof, demo, sa1, collab) use single format when single value
                if isinstance(values, list) and len(values) > 1:
                    # Multiple values - use array format
                    for val in values:
                        params.setdefault(f"f[{key}][]", []).append(val)
                elif isinstance(values, list) and len(values) == 1:
                    # Single value in list - use single format
                    params[f"f[{key}]"] = values[0]
                elif not isinstance(values, list):
                    # Single value - use single format
                    params[f"f[{key}]"] = values

    response = smwc_api_get("https://www.smwcentral.net/ajax.php", params=params, log=log)
    response_data = response.json()
    raw_data = response_data.get("data", [])

    # Log pagination info on first page
    if page == 1 and log:
        total = response_data.get("total", 0)
        last_page = response_data.get("last_page", 1)
        hack_type = "waiting" if waiting_mode else "moderated"
        log(f"📊 Found {total} {hack_type} hacks across {last_page} pages", level="information")

    # Return both data and pagination info
    return {
        "data": raw_data,
        "last_page": response_data.get("last_page", page),
        "current_page": response_data.get("current_page", page)
    }

def fetch_hack_list_direct_smwc(config, page=1, waiting_mode=False, log=None):
    """Explicit direct-SMWCentral list access reserved for fallback/unsupported data."""

    return _fetch_hack_list_smwc(
        config, page=page, waiting_mode=waiting_mode, log=log
    )


def _fetch_file_metadata_smwc(file_id, log=None):
    params = {"a": "getfile", "v": "2", "id": file_id}
    response = smwc_api_get("https://www.smwcentral.net/ajax.php", params=params, log=log)

    if response:
        try:
            # The API returns data directly, not nested under "data"
            data = response.json()
            # Wrap in "data" key for backward compatibility with existing code
            return {"data": data}
        except Exception as e:
            if log:
                log(f"Error parsing file metadata JSON: {e}", "Error")
            return None
    return None

_CORE_KAIZOFF_PROVIDER = None
_CORE_KAIZOFF_QUERY_CACHE = None
_KAIZOFF_COMPAT_PAGE_SIZE = 50
_KAIZOFF_SPARSE_DETAIL_LIMIT = 25
_KAIZOFF_LOCAL_FILTER_KEYS = frozenset(
    {
        "name",
        "author",
        "tags",
        "description",
        "type",
        "hof",
        "sa1",
        "collab",
        "demo",
        "difficulties",
        "order",
        "waiting",
    }
)
_KAIZOFF_INDEX_FILTER_KEYS = frozenset({"name", "type", "waiting"})


class _UseKaizOffRichCatalogue(RuntimeError):
    """Internal signal that a sparse Index result is too broad to hydrate per ID."""


def _get_core_kaizoff_provider():
    global _CORE_KAIZOFF_PROVIDER
    if _CORE_KAIZOFF_PROVIDER is None:
        from kaizoff_provider import KaizOffCatalogueProvider

        processed = Path(PROCESSED_JSON_PATH).expanduser().absolute()
        _CORE_KAIZOFF_PROVIDER = KaizOffCatalogueProvider(
            cache_dir=processed.with_name("kaizoff_cache")
        )
    return _CORE_KAIZOFF_PROVIDER


def _normalize_filter_text(value):
    return str(value or "").strip().casefold()


def _normalize_type_filter(value):
    return _normalize_filter_text(value).replace("-", "_").replace(" ", "_")


def _requested_boolean(value):
    if isinstance(value, (list, tuple)):
        if not value:
            return None
        value = value[0]
    normalized = _normalize_filter_text(value)
    if normalized in {"1", "true", "yes"}:
        return True
    if normalized in {"0", "false", "no"}:
        return False
    return None


def _freeze_filter_value(value):
    if isinstance(value, dict):
        return tuple(
            sorted((str(key), _freeze_filter_value(item)) for key, item in value.items())
        )
    if isinstance(value, (list, tuple, set, frozenset)):
        return tuple(_freeze_filter_value(item) for item in value)
    return value


def _kaizoff_filter_signature(config):
    return tuple(
        sorted((str(key), _freeze_filter_value(value)) for key, value in config.items())
    )


def _active_filter_keys(config):
    return {
        str(key)
        for key, value in config.items()
        if value not in (None, "", [], (), {}) and key != "waiting"
    }


def _validate_kaizoff_filter_keys(config):
    unsupported = sorted(_active_filter_keys(config) - _KAIZOFF_LOCAL_FILTER_KEYS)
    if unsupported:
        raise ValueError(
            "KaizOFF local filtering does not support: " + ", ".join(unsupported)
        )


def _should_try_sparse_index(config):
    """Use Index + per-ID detail only for genuinely sparse interactive searches.

    The public Index is ideal for name discovery. Broad searches and filters that
    need rich fields intentionally use the paginated full-record catalogue so a
    migration/bulk job does not turn into hundreds of individual detail requests.
    """

    keys = _active_filter_keys(config)
    return bool(_normalize_filter_text(config.get("name"))) and keys.issubset(
        _KAIZOFF_INDEX_FILTER_KEYS
    )


def _kaizoff_index_entry_matches(entry, config):
    name = _normalize_filter_text(config.get("name"))
    if name and name not in entry.title.casefold():
        return False

    requested_types = config.get("type")
    if requested_types:
        if not isinstance(requested_types, (list, tuple)):
            requested_types = [requested_types]
        requested = {_normalize_type_filter(value) for value in requested_types}
        actual = {
            _normalize_type_filter(value)
            for value in str(entry.hack_type or "").split(",")
            if str(value).strip()
        }
        if requested and not requested.intersection(actual):
            return False
    return True


def _kaizoff_record_matches(metadata, config):
    _validate_kaizoff_filter_keys(config)

    name = _normalize_filter_text(config.get("name"))
    if name and name not in metadata.title.casefold():
        return False

    author = _normalize_filter_text(config.get("author"))
    if author and not any(author in value.casefold() for value in metadata.authors):
        return False

    description = _normalize_filter_text(config.get("description"))
    if description and description not in metadata.description.casefold():
        return False

    tags = config.get("tags")
    if tags:
        if isinstance(tags, (list, tuple)):
            requested_tags = [str(value).strip() for value in tags if str(value).strip()]
        else:
            requested_tags = [
                value.strip() for value in str(tags).split(",") if value.strip()
            ]
        available_tags = {value.casefold() for value in metadata.tags}
        if any(value.casefold() not in available_tags for value in requested_tags):
            return False

    requested_types = config.get("type")
    if requested_types:
        if not isinstance(requested_types, (list, tuple)):
            requested_types = [requested_types]
        requested = {_normalize_type_filter(value) for value in requested_types}
        actual = {_normalize_type_filter(value) for value in metadata.hack_types}
        if requested and not requested.intersection(actual):
            return False

    difficulties = config.get("difficulties") or []
    if difficulties:
        requested_ids = set()
        allow_missing = False
        for difficulty in difficulties:
            normalized = _normalize_filter_text(difficulty)
            if normalized == "no difficulty":
                allow_missing = True
                continue
            key = DIFFICULTY_KEYMAP.get(normalized)
            if key:
                requested_ids.add(f"diff_{key}")
        actual_id = str(getattr(metadata, "difficulty_id", "") or "").strip()
        if actual_id:
            if requested_ids and actual_id not in requested_ids:
                return False
            if not requested_ids and allow_missing:
                return False
        elif not allow_missing:
            return False

    for field, attribute in (
        ("hof", "hall_of_fame"),
        ("sa1", "sa1_compatible"),
        ("collab", "collaboration"),
        ("demo", "demo"),
    ):
        if field not in config:
            continue
        expected = _requested_boolean(config.get(field))
        if expected is not None and getattr(metadata, attribute) is not expected:
            return False

    return True


def _legacy_record_from_kaizoff(metadata):
    obsolete = bool(
        metadata.active is False
        or metadata.obsoleted_by_submission_id is not None
    )
    hack_types = list(metadata.hack_types) or ["standard"]
    return {
        "id": str(metadata.smwc_submission_id),
        "name": metadata.title,
        "time": int(metadata.release_timestamp or 0),
        "authors": [{"name": name} for name in metadata.authors],
        "tags": list(metadata.tags),
        "images": list(metadata.image_urls),
        "rating": metadata.rating,
        "size": metadata.size_bytes,
        "downloads": metadata.downloads,
        "download_url": metadata.download_url,
        "difficulty": metadata.difficulty,
        "type": hack_types[0] if len(hack_types) == 1 else ", ".join(hack_types),
        "exits": metadata.exits,
        "length": metadata.exits,
        "demo": metadata.demo,
        "hof": metadata.hall_of_fame,
        "sa1": metadata.sa1_compatible,
        "collab": metadata.collaboration,
        "description": metadata.description,
        "active": metadata.active,
        "moderated": metadata.moderated,
        "obsoleted_by": metadata.obsoleted_by_submission_id,
        "last_fetched": metadata.last_fetched,
        "raw_fields": {
            "difficulty": str(metadata.difficulty_id or ""),
            "type": hack_types,
            "length": int(metadata.exits or 0),
            "hof": bool(metadata.hall_of_fame),
            "sa1": bool(metadata.sa1_compatible),
            "collab": bool(metadata.collaboration),
            "demo": bool(metadata.demo),
            "description": metadata.description,
            "obsolete": obsolete,
        },
    }


def _fetch_sparse_kaizoff_index(config, page, log=None):
    provider = _get_core_kaizoff_provider()
    snapshot = provider.get_index()
    entries = [
        entry for entry in snapshot.entries if _kaizoff_index_entry_matches(entry, config)
    ]
    if len(entries) > _KAIZOFF_SPARSE_DETAIL_LIMIT:
        raise _UseKaizOffRichCatalogue(
            f"Index search matched {len(entries)} hacks; bulk rich catalogue is cheaper."
        )

    records = []
    for entry in entries:
        detail = provider.get_hack(entry.smwc_submission_id)
        if _kaizoff_record_matches(detail.metadata, config):
            records.append(detail.metadata)

    page_number = max(1, int(page))
    selected = records if page_number == 1 else []
    if log and page_number == 1:
        stale = " stale-cache" if snapshot.stale else ""
        log(
            f"📊 Found {len(records)} moderated hacks through KaizOFF Index "
            f"({snapshot.source}{stale}); hydrated {len(records)} rich records",
            level="information",
        )
    return {
        "data": [_legacy_record_from_kaizoff(row) for row in selected],
        "last_page": 1,
        "current_page": page_number,
        "lookup_source": "kaizoff_index_detail",
    }


def _fetch_rich_kaizoff_catalogue(config, page, log=None):
    provider = _get_core_kaizoff_provider()
    snapshot = provider.get_catalogue()
    signature = _kaizoff_filter_signature(config)
    global _CORE_KAIZOFF_QUERY_CACHE
    cached = _CORE_KAIZOFF_QUERY_CACHE
    if (
        cached is not None
        and cached[0] == snapshot.fetched_at
        and cached[1] == signature
    ):
        records = list(cached[2])
    else:
        records = [
            metadata
            for metadata in snapshot.records
            if _kaizoff_record_matches(metadata, config)
        ]
        if config.get("order") == "date":
            records.sort(
                key=lambda metadata: (
                    int(metadata.release_timestamp or 0),
                    metadata.smwc_submission_id,
                ),
                reverse=True,
            )
        _CORE_KAIZOFF_QUERY_CACHE = (
            snapshot.fetched_at,
            signature,
            tuple(records),
        )

    page_number = max(1, int(page))
    total = len(records)
    last_page = max(
        1, (total + _KAIZOFF_COMPAT_PAGE_SIZE - 1) // _KAIZOFF_COMPAT_PAGE_SIZE
    )
    start = (page_number - 1) * _KAIZOFF_COMPAT_PAGE_SIZE
    selected = records[start : start + _KAIZOFF_COMPAT_PAGE_SIZE]
    if log and page_number == 1:
        stale = " stale-cache" if snapshot.stale else ""
        log(
            f"📊 Found {total} moderated hacks through KaizOFF rich catalogue "
            f"({snapshot.source}{stale}) across {last_page} local pages",
            level="information",
        )
    return {
        "data": [_legacy_record_from_kaizoff(row) for row in selected],
        "last_page": last_page,
        "current_page": page_number,
        "lookup_source": "kaizoff_catalogue",
    }


def _smwc_catalogue_fallback(config, page, log, reason):
    if log:
        log(
            "[WRN] KaizOFF could not satisfy the moderated catalogue request; "
            f"falling back to the direct SMWCentral API for this page: {reason}",
            level="warning",
        )
    result = _fetch_hack_list_smwc(
        config, page=page, waiting_mode=False, log=log
    )
    if isinstance(result, dict):
        result = dict(result)
        result["lookup_source"] = "smwc_fallback"
    return result


def fetch_hack_list(config, page=1, waiting_mode=False, log=None):
    """Fetch SMWC catalogue rows through the cheapest suitable KaizOFF path.

    Sparse name discovery uses the one-shot Index and hydrates only the small
    matching set. Broad searches, rich-field filters, and bulk scans use the
    paginated full-record public catalogue, cached as one local snapshot.
    Waiting/unmoderated submissions remain a direct-SMWCentral exception.
    """

    if waiting_mode:
        if log and page == 1:
            log(
                "[WRN] Waiting submissions are not available in the KaizOFF active "
                "catalogue; using the direct SMWCentral API for waiting results.",
                level="warning",
            )
        return _fetch_hack_list_smwc(
            config, page=page, waiting_mode=True, log=log
        )

    try:
        _validate_kaizoff_filter_keys(config)
    except ValueError as exc:
        return _smwc_catalogue_fallback(config, page, log, exc)

    if _should_try_sparse_index(config):
        try:
            return _fetch_sparse_kaizoff_index(config, page, log=log)
        except _UseKaizOffRichCatalogue as exc:
            if log and int(page) == 1:
                log(
                    f"[DEBUG] {exc} Using KaizOFF paginated rich catalogue instead.",
                    level="debug",
                )
        except Exception as index_error:
            if log and int(page) == 1:
                log(
                    "[WRN] KaizOFF Index path failed; trying the KaizOFF paginated "
                    f"rich catalogue before SMWCentral fallback: {index_error}",
                    level="warning",
                )

    try:
        return _fetch_rich_kaizoff_catalogue(config, page, log=log)
    except Exception as exc:
        return _smwc_catalogue_fallback(config, page, log, exc)


def fetch_file_metadata(file_id, log=None):
    """Fetch one SMWC submission with KaizOFF public detail as primary."""

    try:
        snapshot = _get_core_kaizoff_provider().get_hack(int(file_id))
        if log:
            stale = " stale-cache" if snapshot.stale else ""
            log(
                f"[DEBUG] Loaded SMWC {file_id} metadata through KaizOFF "
                f"({snapshot.source}{stale})",
                level="debug",
            )
        return {
            "data": _legacy_record_from_kaizoff(snapshot.metadata),
            "lookup_source": "kaizoff",
        }
    except Exception as exc:
        if log:
            log(
                "[WRN] KaizOFF detail unavailable; falling back to the direct "
                f"SMWCentral API for SMWC {file_id}: {exc}",
                level="warning",
            )
        result = _fetch_file_metadata_smwc(file_id, log=log)
        if isinstance(result, dict):
            result = dict(result)
            result["lookup_source"] = "smwc_fallback"
        return result

def _select_best_patch(patch_files, hack_name=""):
    """Pick the best single patch from an already-collected sorted list.

    Uses the same priority heuristics as the old single-patch path so callers
    avoid re-opening or re-extracting the zip just to get a selection.
    """
    import re
    if len(patch_files) == 1:
        return patch_files[0]

    # Try to match with hack name if provided
    if hack_name:
        hack_name_simple = re.sub(r'[^a-zA-Z0-9]', '', hack_name.lower())
        for patch_file in patch_files:
            file_name = os.path.basename(patch_file).lower()
            file_name_simple = re.sub(r'[^a-zA-Z0-9]', '', file_name)
            if hack_name_simple in file_name_simple:
                return patch_file

    # Look for common main patch indicators
    main_indicators = ["main", "patch", "rom", "smc", "sfc"]
    for indicator in main_indicators:
        for patch_file in patch_files:
            if indicator in os.path.basename(patch_file).lower():
                return patch_file

    # Exclude common auxiliary patches
    exclude_indicators = ["music", "graphics", "optional", "extra", "addon"]
    filtered_files = [f for f in patch_files if not any(
        indicator in os.path.basename(f).lower() for indicator in exclude_indicators
    )]

    if filtered_files:
        return max(filtered_files, key=os.path.getsize)

    return max(patch_files, key=os.path.getsize)


def extract_patches_from_zip(zip_path, extract_to, hack_name="", return_all=False):
    """Extract zip and find patch files (IPS or BPS).

    Args:
        zip_path:    Path to the downloaded ZIP archive.
        extract_to:  Directory to extract contents into.
        hack_name:   Name hint used to pick the best single patch (ignored when return_all=True).
        return_all:  When True, return a sorted list of ALL patch file paths found.
                     When False (default), return a single best-match path string (or None).
    """
    import zipfile

    # Extract zip contents with zip-slip protection
    try:
        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            bad_file = zip_ref.testzip()
            if bad_file:
                raise zipfile.BadZipFile(f"Bad zip file, first bad file: {bad_file}")
            # Validate every entry stays inside extract_to using pure string
            # normalisation (abspath) — no filesystem I/O needed for this check.
            extract_to_abs = os.path.abspath(extract_to)
            for member in zip_ref.namelist():
                member_path = os.path.abspath(os.path.join(extract_to_abs, member))
                if not member_path.startswith(extract_to_abs + os.sep) and member_path != extract_to_abs:
                    raise ValueError(f"Zip entry outside target directory (zip slip): {member}")
            zip_ref.extractall(extract_to)
    except Exception as e:
        raise e

    # Skip the zip file itself when walking
    zip_basename = os.path.basename(zip_path)

    # Collect all patch files (IPS and BPS), excluding the source zip
    patch_files = []
    for root, _, files in os.walk(extract_to):
        for fname in files:
            if fname == zip_basename:
                continue
            if fname.lower().endswith((".ips", ".bps")):
                patch_files.append(os.path.join(root, fname))

    if not patch_files:
        return [] if return_all else None

    # Sort alphabetically by filename so higher versions come last
    patch_files = sorted(patch_files, key=lambda p: os.path.basename(p).lower())

    if return_all:
        return patch_files

    return _select_best_patch(patch_files, hack_name)

def run_pipeline(filter_payload, base_rom_path, output_dir, log=None, multi_patch_callback=None):
    """
    Main pipeline function using unified patch handler
    """
    # Reset cancellation flag at start
    reset_cancel_flag()

    processed = load_processed()
    all_hacks = []
    if log: log("🔎 Starting download...")

    # Check if we need to do post-collection filtering
    difficulties = filter_payload.get("difficulties", [])
    has_no_difficulty = "no difficulty" in difficulties
    regular_difficulties = [d for d in difficulties if d != "no difficulty"]
    needs_post_filtering = has_no_difficulty and not regular_difficulties

    # Add warning for "No Difficulty" selections
    if has_no_difficulty:
        if log:
            log("[WRN] 'No Difficulty' selected - filtering the complete catalogue locally", level="warning")

    # PHASE 1: Fetch all moderated hacks (u=0)
    page = 1
    while True:
        # Check for cancellation
        if is_cancelled():
            if log: log("❌ Operation cancelled by user", "warning")
            return

        page_result = fetch_hack_list(filter_payload, page=page, waiting_mode=False, log=log)

        hacks = page_result["data"]
        last_page = page_result.get("last_page", page)

        if not hacks:
            if log: log("📄 No more moderated pages available", level="information")
            break

        all_hacks.extend(hacks)

        if log:
            log(f"📄 Moderated page {page} returned {len(hacks)} entries", level="information")

        # Stop if we've reached the last page
        if page >= last_page:
            if log: log(f"📄 Reached last moderated page ({last_page})", level="information")
            break

        page += 1

    # PHASE 2: Fetch waiting hacks if enabled (u=1)
    if filter_payload.get("waiting", False):
        page = 1
        while True:
            # Check for cancellation
            if is_cancelled():
                if log: log("❌ Operation cancelled by user", "warning")
                return

            page_result = fetch_hack_list(filter_payload, page=page, waiting_mode=True, log=log)

            waiting_hacks = page_result["data"]
            last_page = page_result.get("last_page", page)

            if not waiting_hacks:
                if log: log("📄 No more waiting pages available", level="information")
                break

            all_hacks.extend(waiting_hacks)

            if log:
                log(f"📄 Waiting page {page} returned {len(waiting_hacks)} entries", level="information")

            # Stop if we've reached the last page
            if page >= last_page:
                if log: log(f"📄 Reached last waiting page ({last_page})", level="information")
                break

            page += 1

    # Remove duplicates (just in case)
    unique_hacks = []
    seen_ids = set()
    for hack in all_hacks:
        hack_id = hack.get('id')
        if hack_id not in seen_ids:
            unique_hacks.append(hack)
            seen_ids.add(hack_id)

    if len(all_hacks) != len(unique_hacks) and log:
        log(f"📦 Removed {len(all_hacks) - len(unique_hacks)} duplicates", level="information")

    all_hacks = unique_hacks

    # Post-collection filtering for "No Difficulty" scenarios
    if needs_post_filtering or (has_no_difficulty and regular_difficulties):
        if log:
            log(f"🔍 Filtering {len(all_hacks)} hacks for difficulty criteria...")

        filtered_hacks = []
        for hack in all_hacks:
            hack_difficulty = hack.get("raw_fields", {}).get("difficulty", "")

            if has_no_difficulty and not regular_difficulties:
                # ONLY "No Difficulty" selected
                if hack_difficulty == "" or hack_difficulty is None or hack_difficulty == "N/A":
                    filtered_hacks.append(hack)
            elif has_no_difficulty and regular_difficulties:
                # MIXED: Both "No Difficulty" AND regular difficulties
                selected_diff_keys = []
                for d in regular_difficulties:
                    if d in DIFFICULTY_KEYMAP:
                        diff_key = DIFFICULTY_KEYMAP[d]
                        if diff_key:
                            selected_diff_keys.append(f"diff_{diff_key}")

                # Include if: no difficulty OR matches selected difficulties
                if (hack_difficulty == "" or hack_difficulty is None or hack_difficulty == "N/A") or hack_difficulty in selected_diff_keys:
                    filtered_hacks.append(hack)

        if log:
            log(f"✅ Filtered to {len(filtered_hacks)} hacks matching criteria")

        all_hacks = filtered_hacks

    if log:
        log(f"📦 Found {len(all_hacks)} total hacks.")
        log("🧪 Starting patching...")

    base_rom_ext = os.path.splitext(base_rom_path)[1]
    from config_manager import ConfigManager
    include_smwc_id_in_filename = bool(
        ConfigManager().get("include_smwc_id_in_filename", False)
    )

    # Normalize to internal key, NOT display name
    raw_type = filter_payload["type"][0]
    normalized_type = raw_type.lower().replace("-", "_")

    for hack in all_hacks:
        # Check for cancellation at the start of each hack processing
        if is_cancelled():
            if log: log("❌ Operation cancelled by user", "warning")
            return

        hack_id = str(hack["id"])
        raw_title = hack["name"]
        title_clean = title_case(safe_filename(raw_title))
        raw_diff = hack.get("raw_fields", {}).get("difficulty", "")

        # Fix: Handle None/empty difficulty values consistently
        if not raw_diff or raw_diff in [None, "N/A"]:
            raw_diff = ""

        display_diff = DIFFICULTY_LOOKUP.get(raw_diff, "No Difficulty")  # Changed default from "Unknown" to "No Difficulty"
        folder_name = get_sorted_folder_name(display_diff)

        # OPTIMIZED: Extract only the metadata fields we want to track and update
        raw_fields = hack.get("raw_fields", {})
        page_metadata = {
            "exits": raw_fields.get("length", hack.get("length", 0)) or 0,
            "hall_of_fame": bool(raw_fields.get("hof", False)),
            "sa1_compatibility": bool(raw_fields.get("sa1", False)),
            "collaboration": bool(raw_fields.get("collab", False)),
            "demo": bool(raw_fields.get("demo", False)),
            "authors": hack.get("authors", []),
            "obsolete": bool(raw_fields.get("obsolete", False)),
        }
        page_rating = extract_smwc_rating(hack)
        if page_rating is not None:
            page_metadata["rating"] = page_rating

        if hack_id in processed:
            actual_diff = processed[hack_id].get("current_difficulty", "")

            # Determine whether the recorded ROM actually exists using Collection state.
            # Never infer ownership from a generated title/difficulty path: catalogue refresh
            # is metadata-only for an existing ROM, and any layout drift belongs to the
            # explicit Collection organization workflow.
            _stored_path = processed[hack_id].get("file_path", "")
            _stored_files = processed[hack_id].get("files", [])
            if _stored_files:
                _primary = next((f for f in _stored_files if f.get("primary")), _stored_files[0])
                _file_on_disk = os.path.exists(_primary.get("path", ""))
            elif _stored_path:
                _file_on_disk = os.path.exists(_stored_path)
            else:
                _file_on_disk = False

            if not _file_on_disk:
                if log:
                    log(f"⚠️ Source Not Found: Redownloading {title_clean}", "Warning")
                # Don't continue here - fall through to redownload the hack. Existing
                # unrecorded paths are never guessed, renamed, or adopted implicitly.
            else:
                if log:
                    log(f"✅ Skipped: {title_clean}")

                # OPTIMIZED: Still update metadata from page data even when skipping download.
                existing_hack = processed.get(hack_id, {})
                for key, new_value in page_metadata.items():
                    old_value = existing_hack.get(key)
                    if old_value != new_value:
                        if log:
                            log(f"Updated: {title_clean} attribute {key} updated from {old_value} → {new_value}", "Information")
                        processed[hack_id][key] = new_value

                # Update title if it doesn't match the properly formatted version.
                current_title = existing_hack.get("title", "")
                proper_title = clean_hack_title(raw_title)
                if current_title != proper_title:
                    if log:
                        log(f"Updated: {title_clean} title formatting updated from '{current_title}' → '{proper_title}'", "Information")
                    processed[hack_id]["title"] = proper_title

                if actual_diff != display_diff:
                    processed[hack_id]["current_difficulty"] = display_diff
                    processed[hack_id]["difficulty_id"] = raw_diff
                    processed[hack_id]["folder_name"] = folder_name
                    if log:
                        log(
                            f"📝 Updated difficulty from {actual_diff} → {display_diff}; "
                            "the existing ROM was left in place for explicit Collection organization.",
                            "Information",
                        )

                save_processed(processed)
                continue

        # OPTIMIZED: Use download_url directly from page data (eliminates API call)
        download_url = hack.get("download_url")
        if not download_url:
            if log:
                log(f"❌ Error: No download URL found for {title_clean}", "Error")
            continue

        temp_dir = tempfile.mkdtemp()
        try:
            zip_path = os.path.join(temp_dir, "hack.zip")

            # Add debug logging for file download
            if log:
                log(f"[DEBUG] Downloading file: {download_url}", level="debug")

            r = requests.get(download_url)
            with open(zip_path, "wb") as f:
                f.write(r.content)

            patch_files = extract_patches_from_zip(zip_path, temp_dir, title_clean, return_all=True)
            if not patch_files:
                raise Exception("Patch file (.ips or .bps) not found in archive")

            # ── Multi-patch path ────────────────────────────────────────
            if len(patch_files) > 1 and multi_patch_callback:
                if log:
                    log(f"🗂️ {len(patch_files)} patch files found in {title_clean} – asking user to choose...", "Information")
                selections = multi_patch_callback(patch_files, title_clean, temp_dir)

                if selections is None:
                    if log:
                        log(f"⏭️ Skipped: {title_clean} (cancelled by user)", "Warning")
                    continue

                primary_output_path = None
                patched_files = []

                for sel in selections:
                    clean_name = safe_filename(sel['output_name'])
                    out_filename = build_patched_rom_filename(
                        clean_name,
                        base_rom_ext,
                        smwc_id=hack_id,
                        include_smwc_id=include_smwc_id_in_filename,
                    )
                    out_path = os.path.join(
                        make_output_path(output_dir, normalized_type, folder_name),
                        out_filename
                    )
                    if log:
                        log(f"🔧 Patching {clean_name}...", "Information")
                    success = PatchHandler.apply_patch(sel["patch_path"], base_rom_path, out_path, log)
                    if not success:
                        if log:
                            log(f"⚠️ Patch failed for {clean_name}, skipping.", "Warning")
                        continue
                    patched_files.append(
                        build_tool_patch_rom_asset(
                            out_path,
                            smwc_submission_id=int(hack_id),
                            primary=bool(sel["primary"]),
                        )
                    )
                    if sel["primary"]:
                        primary_output_path = out_path

                if not patched_files:
                    raise Exception("All selected patches failed")

                if primary_output_path is None:
                    primary_output_path = patched_files[0]["path"]
                    patched_files[0]["primary"] = True

                patched_files_data = patched_files
                primary_output_path = next(
                    row["path"] for row in patched_files_data if row.get("primary")
                )
                output_path = primary_output_path
                if log:
                    log(f"✅ Patched: {title_clean} ({len(patched_files)} file(s))")

            else:
                # ── Single-patch path (original behaviour) ──────────────
                patch_path = _select_best_patch(patch_files, title_clean)
                output_filename = build_patched_rom_filename(
                    title_clean,
                    base_rom_ext,
                    smwc_id=hack_id,
                    include_smwc_id=include_smwc_id_in_filename,
                )
                output_path = os.path.join(make_output_path(output_dir, normalized_type, folder_name), output_filename)
                success = PatchHandler.apply_patch(patch_path, base_rom_path, output_path, log)
                if not success:
                    raise Exception("Patch application failed")
                patched_files_data = [
                    build_tool_patch_rom_asset(
                        output_path,
                        smwc_submission_id=int(hack_id),
                        primary=True,
                    )
                ]
                output_path = patched_files_data[0]["path"]
                if log:
                    log(f"✅ Patched: {title_clean}")

            # Check if hack exists and compare metadata for sync (v3.1 feature)
            existing_hack = processed.get(hack_id, {})
            metadata_changes = []

            # v3.1 OPTIMIZED: Use metadata from page data instead of individual API calls
            new_metadata = page_metadata.copy()  # Use the metadata extracted from page data

            # v3.1 NEW: Check for metadata changes and log them
            if existing_hack:
                for key, new_value in new_metadata.items():
                    old_value = existing_hack.get(key)
                    if old_value != new_value:
                        metadata_changes.append(f"{key}: {old_value} → {new_value}")
                        if log:
                            log(f"Updated: {title_clean} attribute {key} updated from {old_value} → {new_value}", "Information")

                # Check for title changes and log them
                # This ensures we log when title formatting is updated during re-download
                current_title = existing_hack.get("title", "")
                proper_title = clean_hack_title(raw_title)
                if current_title != proper_title:
                    if log:
                        log(f"Updated: {title_clean} title formatting updated from '{current_title}' → '{proper_title}'", "Information")

            # Overlay refreshed provider/download facts onto the existing Collection
            # record so user-owned and newer local fields survive a redownload.
            updated_record = dict(existing_hack)
            updated_record.update({
                "title": clean_hack_title(raw_title),
                "difficulty_id": raw_diff,
                "current_difficulty": display_diff,
                "folder_name": folder_name,
                "file_path": output_path,
                "hack_type": normalized_type,
                "hall_of_fame": new_metadata.get("hall_of_fame", False),
                "sa1_compatibility": new_metadata.get("sa1_compatibility", False),
                "collaboration": new_metadata.get("collaboration", False),
                "demo": new_metadata.get("demo", False),
                "exits": new_metadata.get("exits", 0),
                "authors": new_metadata.get("authors", []),
                "rating": new_metadata.get("rating", existing_hack.get("rating", 0)),
                "time": new_metadata.get("time", 0),
                "date": "",
                "obsolete": new_metadata.get("obsolete", False),
            })
            updated_record["files"] = merge_collection_rom_assets(
                existing_hack.get("files", []),
                patched_files_data,
                primary_path=output_path,
            )
            processed[hack_id] = updated_record

            # Populate date from time if available
            if processed[hack_id]["time"]:
                try:
                    from datetime import datetime
                    timestamp = int(processed[hack_id]["time"])
                    processed[hack_id]["date"] = datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d')
                except Exception:
                    pass

            save_processed(processed)

        except Exception as e:
            if log:
                log(f"❌ Error processing {title_clean}: {str(e)}", "Error")
        finally:
            # Clean up temp files
            import shutil
            try:
                shutil.rmtree(temp_dir)
            except Exception:
                pass

def save_hack_to_processed_json(hack_data, file_path, hack_type):
    """Save hack data with actual SMWC metadata to processed.json"""

    # Extract actual boolean values from SMWC API response
    processed_data = {
        "title": clean_hack_title(hack_data.get("title", "Unknown")),  # Clean the title
        "current_difficulty": hack_data.get("difficulty", "Unknown"),
        "folder_name": get_sorted_folder_name(hack_data.get("difficulty", "Unknown")),
        # Removed file_path for privacy - contains usernames
        "hack_type": hack_type.lower(),

        # Use actual API metadata as booleans
        "hall_of_fame": bool(hack_data.get("hall_of_fame", False)),
        "sa1_compatibility": bool(hack_data.get("sa1", False)),
        "collaboration": bool(hack_data.get("collaboration", False)),
        "demo": bool(hack_data.get("demo", False)),

        # v3.1 NEW: Additional metadata fields
        "exits": hack_data.get("length", 0),  # API length becomes exits
        "authors": hack_data.get("authors", []),  # Authors array
        "rating": normalize_smwc_rating(hack_data.get("rating", 0)),
        "time": hack_data.get("time", 0),  # Raw timestamp
        "date": "",  # Will be populated below

        # Collection tracking fields
        "completed": False,
        "completed_date": "",
        "personal_rating": 0,
        "notes": "",
        "time_to_beat": 0  # v3.1 NEW: Time to beat in seconds
    }

    # Populate date from time if available
    if processed_data["time"]:
        try:
             from datetime import datetime
             timestamp = int(processed_data["time"])
             processed_data["date"] = datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d')
        except Exception:
             pass

    # Save to processed.json
    # ... existing save logic

def process_individual_hacks(selected_hacks, base_rom_path, output_dir, log=None):
    """Process a list of pre-selected hacks for download and patching"""
    if log: log(f"🎯 Processing {len(selected_hacks)} individually selected hacks...")

    processed = load_processed()
    patch_handler = PatchHandler(base_rom_path, output_dir, log)

    # Reset cancellation flag at start
    reset_cancel_flag()

    total_hacks = len(selected_hacks)
    successful_downloads = 0

    for i, hack in enumerate(selected_hacks, 1):
        # Check for cancellation
        if is_cancelled():
            if log: log("❌ Operation cancelled by user", "warning")
            break

        hack_id = hack.get("id")
        hack_name = hack.get("name", "Unknown")

        if log: log(f"📥 [{i}/{total_hacks}] Processing: {hack_name}")

        # Check if already processed
        if hack_id in processed:
            if log: log(f"⏭️ Skipping {hack_name} (already processed)")
            continue

        try:
            # Fetch detailed metadata
            file_metadata = fetch_file_metadata(hack_id, log)
            if not file_metadata:
                if log: log(f"❌ Could not fetch metadata for {hack_name}")
                continue

            # Merge hack data with detailed metadata
            full_hack_data = {**hack, **file_metadata}

            # Download and patch
            success = download_and_patch_hack(full_hack_data, patch_handler, processed, log)
            if success:
                successful_downloads += 1
                # Save progress after each successful download
                save_processed(processed)

        except Exception as e:
            if log: log(f"❌ Error processing {hack_name}: {str(e)}", "error")
            continue

    # Final report
    if log:
        log(f"✅ Single download complete! Successfully processed {successful_downloads}/{total_hacks} hacks")
        if successful_downloads > 0:
            log(f"📁 Output location: {output_dir}")

def download_and_patch_hack(hack_data, patch_handler, processed, log=None):
    """Download and patch a single hack"""
    hack_id = hack_data.get("id")
    hack_name = hack_data.get("name", "Unknown")

    try:
        # Get download URL from metadata
        download_url = hack_data.get("download_url")
        if not download_url:
            if log: log(f"❌ No download URL for {hack_name}")
            return False

        # Create output folder
        difficulty = hack_data.get("difficulty", "")
        difficulty_name = DIFFICULTY_LOOKUP.get(difficulty, "No Difficulty")
        folder_name = get_sorted_folder_name(difficulty_name)

        authors = hack_data.get("authors", "Unknown")
        hack_type = hack_data.get("type", "")
        type_name = TYPE_DISPLAY_LOOKUP.get(hack_type, "Unknown")

        # Generate safe filename
        from config_manager import ConfigManager
        output_filename = build_patched_rom_filename(
            hack_name,
            ".smc",
            smwc_id=hack_id,
            include_smwc_id=bool(
                ConfigManager().get("include_smwc_id_in_filename", False)
            ),
        )

        # Download the hack file
        if log: log(f"⬇️ Downloading {hack_name}...")

        response = requests.get(download_url, timeout=30)
        response.raise_for_status()

        # Create temporary file for the downloaded hack
        with tempfile.NamedTemporaryFile(delete=False, suffix='.zip') as temp_file:
            temp_file.write(response.content)
            temp_path = temp_file.name

        try:
            # Process the hack file (extract and patch)
            result = patch_handler.process_hack_file(
                temp_path,
                output_filename,
                folder_name,
                {
                    "id": hack_id,
                    "name": hack_name,
                    "authors": authors,
                    "type": type_name,
                    "difficulty": difficulty_name,
                    "rating": hack_data.get("rating", "N/A"),
                    "exit": hack_data.get("exit", "N/A"),
                    "date": hack_data.get("date", "Unknown")
                }
            )

            if result["success"]:
                # Mark as processed
                processed[hack_id] = {
                    "name": hack_name,
                    "processed_date": datetime.now().isoformat(),
                    "output_path": result.get("output_path", ""),
                    "type": type_name,
                    "difficulty": difficulty_name,
                    "authors": authors,
                    "rating": normalize_smwc_rating(
                        hack_data.get("rating", 0)
                    ),
                    "time": hack_data.get("time", 0),  # Raw timestamp
                    "date": "",  # Will be populated below
                    "obsolete": False  # NEW: Default new hacks to not obsolete
                }

                # Populate date from time if available
                if processed[hack_id]["time"]:
                    try:
                        timestamp = int(processed[hack_id]["time"])
                        processed[hack_id]["date"] = datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d')
                    except (ValueError, TypeError, OSError, OverflowError):
                        # Ignore invalid or out-of-range timestamps; leave date as default ""
                        pass

                if log: log(f"✅ Successfully processed {hack_name}")
                return True
            else:
                if log: log(f"❌ Failed to patch {hack_name}: {result.get('error', 'Unknown error')}")
                return False

        finally:
            # Clean up temp file
            try:
                os.unlink(temp_path)
            except:
                pass

    except Exception as e:
        if log: log(f"❌ Error downloading {hack_name}: {str(e)}")
        return False
def backfill_metadata(log_callback=None, cancel_check=None):
    """Backfill missing release metadata and SMWC ratings."""
    processed = load_processed()
    if not processed:
        if log_callback:
            log_callback("No processed hacks found.", "Warning")
        return 0

    updated_count = 0
    total_hacks = len(processed)
    if log_callback:
        log_callback(
            f"Checking {total_hacks} hacks for missing SMWC metadata...",
            "Information",
        )

    ids_to_update = set()
    for hack_id, data in processed.items():
        if not isinstance(data, dict) or not _is_smwc_hack_id(hack_id):
            continue
        if (
            not data.get("date")
            or not data.get("time")
            or extract_smwc_rating(data) is None
        ):
            ids_to_update.add(str(hack_id))

    if not ids_to_update:
        if log_callback:
            log_callback("All SMWC hacks already have metadata.", "Information")
        return 0

    if log_callback:
        log_callback(
            f"Found {len(ids_to_update)} SMWC hacks missing metadata. "
            "Fetching through KaizOFF first...",
            "Information",
        )

    api_metadata = {}
    total_fetched = 0
    if log_callback:
        log_callback("🌐 Loading SMWC catalogue through KaizOFF first...", "Information")

    for waiting_mode in [False, True]:
        if not ids_to_update:
            break
        section_name = "waiting" if waiting_mode else "moderated"
        page = 1
        if log_callback:
            log_callback(f"🔍 Checking {section_name} hacks...", "Information")

        while True:
            if cancel_check and cancel_check():
                if log_callback:
                    log_callback("⚠️ Metadata fetch cancelled by user", "Warning")
                return -1

            response = fetch_hack_list(
                {},
                page=page,
                waiting_mode=waiting_mode,
                log=log_callback,
            )
            if not response or not response.get("data"):
                break

            page_matches = 0
            for hack in response["data"]:
                hack_id = str(hack.get("id", ""))
                if hack_id not in ids_to_update:
                    continue

                metadata = api_metadata.setdefault(hack_id, {})
                hack_time = hack.get("time", 0)
                if hack_time:
                    metadata["time"] = hack_time
                if "downloads" in hack:
                    metadata["downloads"] = hack.get("downloads", 0)
                rating = extract_smwc_rating(hack)
                if rating is not None:
                    metadata["rating"] = rating

                if metadata:
                    page_matches += 1
                if not _metadata_still_missing(
                    processed[hack_id],
                    metadata,
                ):
                    ids_to_update.discard(hack_id)
                    total_fetched += 1

            if log_callback:
                log_callback(
                    f"📄 {section_name.title()} Page {page}: "
                    f"Found {page_matches} matching hacks",
                    "Information",
                )

            if page >= response.get("last_page", 1):
                break
            if not ids_to_update:
                break

            page += 1
            time.sleep(0.5)

    if ids_to_update:
        if log_callback:
            log_callback(
                "🔍 Attempting individual lookups for "
                f"{len(ids_to_update)} hack(s) not fully resolved in listings...",
                "Information",
            )

        fallback_found = 0
        for hack_id in list(ids_to_update):
            if cancel_check and cancel_check():
                if log_callback:
                    log_callback("⚠️ Metadata fetch cancelled by user", "Warning")
                return -1

            hack_title = processed.get(hack_id, {}).get("title", "Unknown")
            try:
                file_data = fetch_file_metadata(hack_id, log=log_callback)
                if file_data and file_data.get("data"):
                    hack_data = file_data["data"]
                    metadata = api_metadata.setdefault(hack_id, {})
                    hack_time = hack_data.get("time", 0)
                    if hack_time:
                        metadata["time"] = hack_time
                    if "downloads" in hack_data:
                        metadata["downloads"] = hack_data.get("downloads", 0)
                    rating = extract_smwc_rating(hack_data)
                    if rating is not None:
                        metadata["rating"] = rating

                    if not _metadata_still_missing(
                        processed[hack_id],
                        metadata,
                    ):
                        ids_to_update.remove(hack_id)
                        fallback_found += 1
                        total_fetched += 1
                        if log_callback:
                            log_callback(
                                f"   ✓ Found metadata for ID {hack_id}: "
                                f"{hack_title}",
                                "Information",
                            )
                    elif log_callback:
                        log_callback(
                            f"   ⚠️ ID {hack_id} ({hack_title}): "
                            "Metadata remains incomplete",
                            "Warning",
                        )
                elif log_callback:
                    log_callback(
                        f"   ✗ ID {hack_id} ({hack_title}): "
                        "Not found or inaccessible",
                        "Warning",
                    )
                time.sleep(0.5)
            except Exception as error:
                if log_callback:
                    log_callback(
                        f"   ✗ ID {hack_id} ({hack_title}): "
                        f"Error - {error}",
                        "Warning",
                    )

        if fallback_found and log_callback:
            log_callback(
                f"✅ Found {fallback_found} hack(s) via individual lookup",
                "Information",
            )

    if ids_to_update and log_callback:
        log_callback(
            f"⚠️ {len(ids_to_update)} hack(s) could not be fully updated",
            "Warning",
        )

    if log_callback:
        log_callback("💾 Writing metadata to file (cannot cancel)...", "Information")

    for hack_id, metadata in api_metadata.items():
        if hack_id not in processed:
            continue

        changed = False
        if metadata.get("time"):
            try:
                timestamp = int(metadata["time"])
                date_str = datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d")
                if processed[hack_id].get("time") != timestamp:
                    processed[hack_id]["time"] = timestamp
                    changed = True
                if processed[hack_id].get("date") != date_str:
                    processed[hack_id]["date"] = date_str
                    changed = True
            except (ValueError, TypeError, OSError, OverflowError) as error:
                if log_callback:
                    hack_title = processed[hack_id].get("title", "Unknown")
                    log_callback(
                        f"⚠️ Invalid timestamp for '{hack_title}': {error}",
                        "Warning",
                    )

        if "downloads" in metadata:
            downloads = metadata["downloads"]
            if processed[hack_id].get("downloads") != downloads:
                processed[hack_id]["downloads"] = downloads
                changed = True

        if "rating" in metadata:
            rating = normalize_smwc_rating(metadata["rating"])
            if extract_smwc_rating(processed[hack_id]) != rating:
                processed[hack_id]["rating"] = rating
                changed = True

        if changed:
            updated_count += 1

    if updated_count:
        save_processed(processed)
    if log_callback:
        log_callback(
            f"💾 Saved {updated_count} updated hacks",
            "Information",
        )
        log_callback(
            f"Backfill function completing (updated {updated_count} hacks)...",
            "Information",
        )

    return updated_count
