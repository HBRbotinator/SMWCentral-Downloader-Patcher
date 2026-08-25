"""Shared naming policy for newly patched ROM files.

The optional SMWC-ID suffix is portable identity evidence only. Existing ROMs and
save files are never renamed by this module.
"""

from __future__ import annotations

import re

from utils import safe_filename


_SMWC_ID_SUFFIX_RE = re.compile(r"\s*\[SMWC(?:-ID)?-(\d+)\]\s*$", re.IGNORECASE)


def build_patched_rom_filename(
    stem,
    extension,
    *,
    smwc_id=None,
    include_smwc_id=False,
):
    """Return a safe filename for a newly generated patched ROM.

    When ``include_smwc_id`` is true, ``smwc_id`` must be a positive numeric
    SMWCentral submission ID and the canonical ``[SMWC-ID-<id>]`` suffix is
    appended. A pre-existing recognized suffix is normalized rather than
    duplicated.
    """

    safe_stem = safe_filename(str(stem or "")).strip()
    if not safe_stem:
        raise ValueError("Patched ROM filename requires a non-empty stem.")

    suffix = str(extension or "").strip()
    if not suffix:
        raise ValueError("Patched ROM filename requires a file extension.")
    if not suffix.startswith("."):
        suffix = f".{suffix}"

    if include_smwc_id:
        normalized_id = _normalize_smwc_id(smwc_id)
        safe_stem = _SMWC_ID_SUFFIX_RE.sub("", safe_stem).rstrip()
        safe_stem = f"{safe_stem} [SMWC-ID-{normalized_id}]"

    return f"{safe_stem}{suffix}"


def _normalize_smwc_id(value):
    text = str(value or "").strip()
    if not text.isdigit() or int(text) <= 0:
        raise ValueError("SMWC-ID filename suffix requires a positive numeric submission ID.")
    return str(int(text))


__all__ = ["build_patched_rom_filename"]
