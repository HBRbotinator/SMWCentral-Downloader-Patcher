"""Collection presentation helpers for SMWC community ratings."""

from __future__ import annotations

import math


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
