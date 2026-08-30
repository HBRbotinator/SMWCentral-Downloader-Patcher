"""Collection presentation helpers for SMWC community ratings."""

from __future__ import annotations

import json
import math
import os
import tempfile


PERSONAL_RATING_COLUMN_ID = "rating"
SMWC_RATING_COLUMN_ID = "smwc_rating"


def parse_smwc_rating(value):
    """Return a valid rated value, or None for Unrated/invalid values."""
    if isinstance(value, bool):
        return None

    try:
        rating = float(value)
    except (TypeError, ValueError):
        return None

    if not math.isfinite(rating) or rating <= 0 or rating > 5:
        return None
    return rating


def format_smwc_rating(value):
    """Format a stored SMWC community rating for Collection UI display."""
    rating = parse_smwc_rating(value)
    if rating is None:
        return "Unrated"

    rating_text = f"{rating:.2f}".rstrip("0").rstrip(".")
    return f"{rating_text} / 5"


def smwc_rating_sort_value(value):
    """Return a stable numeric sort key, with Unrated entries at zero."""
    rating = parse_smwc_rating(value)
    return rating if rating is not None else 0.0


def repair_record_smwc_rating(record):
    """Canonicalize one numeric Collection record's community rating storage.

    ``rating`` is the durable Collection field for the SMWC community rating.
    A short-lived Collection ingestion bug wrote the same provider value to
    ``smwc_rating`` instead. Preserve an already-valid canonical value; only
    promote the legacy value when the canonical field is absent or unrated.
    The accidental field is removed so later consumers cannot prefer stale data.
    """

    if not isinstance(record, dict) or "smwc_rating" not in record:
        return False

    canonical = parse_smwc_rating(record.get("rating"))
    legacy = parse_smwc_rating(record.get("smwc_rating"))
    if canonical is None and legacy is not None:
        record["rating"] = legacy
    record.pop("smwc_rating", None)
    return True


def repair_processed_smwc_ratings(data):
    """Repair accidental ``smwc_rating`` fields on numeric SMWC records in-place.

    Local ``usr_*`` records are intentionally left alone because they do not own
    provider community metadata. Returns the number of records changed.
    """

    if not isinstance(data, dict):
        return 0

    repaired = 0
    for hack_id, record in data.items():
        if not str(hack_id).strip().isdigit():
            continue
        if repair_record_smwc_rating(record):
            repaired += 1
    return repaired


def repair_processed_smwc_rating_file(path):
    """Atomically persist the one-time canonical SMWC rating repair.

    Returns the number of numeric Collection records changed. Missing files are
    a no-op. The replacement is written beside ``processed.json`` and published
    with ``os.replace`` so an interrupted write cannot leave a partial JSON file.
    """

    path = os.fspath(path)
    if not os.path.exists(path):
        return 0

    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    repaired = repair_processed_smwc_ratings(data)
    if not repaired:
        return 0

    parent = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(parent, exist_ok=True)
    temp_path = ""
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=parent,
            prefix=f".{os.path.basename(path)}.rating-",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_path = handle.name
            json.dump(data, handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
        temp_path = ""
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass
    return repaired


def migrate_smwc_rating_column(visible_columns, column_order):
    """Add the new SMWC column once to an existing saved configuration.

    A saved full column order acts as the migration marker. Once the new ID is
    present in that order, later user choices to hide the column are preserved.
    Fresh configurations have no saved order and already receive all default
    columns from CollectionPage.DEFAULT_COLUMNS.
    """
    visible = list(visible_columns or [])
    if not column_order:
        if SMWC_RATING_COLUMN_ID in visible:
            return visible, column_order, False
        visible.append(SMWC_RATING_COLUMN_ID)
        return visible, column_order, True

    order = list(column_order)
    if SMWC_RATING_COLUMN_ID in order:
        return visible, order, False

    if PERSONAL_RATING_COLUMN_ID in order:
        order_index = order.index(PERSONAL_RATING_COLUMN_ID) + 1
    else:
        order_index = len(order)
    order.insert(order_index, SMWC_RATING_COLUMN_ID)

    if SMWC_RATING_COLUMN_ID not in visible:
        if PERSONAL_RATING_COLUMN_ID in visible:
            visible_index = visible.index(PERSONAL_RATING_COLUMN_ID) + 1
        else:
            visible_index = len(visible)
        visible.insert(visible_index, SMWC_RATING_COLUMN_ID)

    return visible, order, True
