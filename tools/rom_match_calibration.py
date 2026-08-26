"""Aggregate ROM-title matcher calibration against known Collection identities.

This developer tool is intentionally read-only. It compares numeric Collection
records that have a recorded ROM path against a lightweight KaizOFF/SMWC index
and reports aggregate matching outcomes without printing local filesystem paths.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rom_title_matching import CatalogueEntry, CatalogueMatcher


@dataclass(frozen=True)
class CalibrationSummary:
    eligible_records: int
    missing_catalogue_records: int
    auto_correct: int
    auto_wrong: int
    review_with_correct_top: int
    top_wrong: int
    classifications: tuple[tuple[str, int], ...]

    @property
    def top_correct(self) -> int:
        return self.auto_correct + self.review_with_correct_top


def _rom_filename_stem(record: Mapping[str, Any]) -> str:
    files = record.get("files")
    candidates: list[str] = []
    if isinstance(files, list):
        primary = [
            item
            for item in files
            if isinstance(item, Mapping) and item.get("primary") is True
        ]
        ordered = primary or [item for item in files if isinstance(item, Mapping)]
        for item in ordered:
            path = item.get("path")
            if isinstance(path, str) and path.strip():
                candidates.append(path.strip())
                break
    file_path = record.get("file_path")
    if not candidates and isinstance(file_path, str) and file_path.strip():
        candidates.append(file_path.strip())
    if not candidates:
        return ""

    basename = re.split(r"[\\/]", candidates[0])[-1]
    return os.path.splitext(basename)[0].strip()


def _difficulty_hint(record: Mapping[str, Any]) -> str:
    return str(record.get("current_difficulty") or record.get("difficulty") or "").strip()


def _catalogue_rows(document: Any) -> Sequence[Mapping[str, Any]]:
    if isinstance(document, list):
        return tuple(item for item in document if isinstance(item, Mapping))
    if isinstance(document, Mapping):
        data = document.get("data")
        if isinstance(data, list):
            return tuple(item for item in data if isinstance(item, Mapping))
    raise ValueError("Catalogue JSON must be an array or an object containing a data array.")


def calibrate_collection(
    collection: Mapping[str, Any],
    catalogue_document: Any,
) -> CalibrationSummary:
    matcher = CatalogueMatcher(
        [CatalogueEntry.from_mapping(row) for row in _catalogue_rows(catalogue_document)]
    )
    classifications: Counter[str] = Counter()
    eligible = 0
    missing_catalogue = 0
    auto_correct = 0
    auto_wrong = 0
    review_correct_top = 0
    top_wrong = 0

    for raw_key, record in collection.items():
        if not isinstance(record, Mapping):
            continue
        try:
            smwc_id = int(raw_key)
        except (TypeError, ValueError):
            continue
        if smwc_id <= 0:
            continue
        title_hint = _rom_filename_stem(record)
        if not title_hint:
            continue
        if matcher.get(smwc_id) is None:
            missing_catalogue += 1
            continue

        eligible += 1
        result = matcher.find(title_hint, difficulty_hint=_difficulty_hint(record))
        classifications[result.classification] += 1
        selected_id = result.selected.smwc_submission_id if result.selected else None
        suggestion_id = result.suggestion.smwc_submission_id if result.suggestion else None

        if selected_id is not None:
            if selected_id == smwc_id:
                auto_correct += 1
            else:
                auto_wrong += 1
        elif suggestion_id == smwc_id:
            review_correct_top += 1

        if suggestion_id != smwc_id:
            top_wrong += 1

    return CalibrationSummary(
        eligible_records=eligible,
        missing_catalogue_records=missing_catalogue,
        auto_correct=auto_correct,
        auto_wrong=auto_wrong,
        review_with_correct_top=review_correct_top,
        top_wrong=top_wrong,
        classifications=tuple(sorted(classifications.items())),
    )


def _load_json(path: str) -> Any:
    with open(Path(path).expanduser(), "r", encoding="utf-8") as handle:
        return json.load(handle)


def _format_summary(summary: CalibrationSummary) -> str:
    lines = [
        "ROM title matcher calibration",
        f"Eligible known-ROM records: {summary.eligible_records}",
        f"Known IDs missing from catalogue: {summary.missing_catalogue_records}",
        f"Automatic matches correct: {summary.auto_correct}",
        f"Automatic matches wrong: {summary.auto_wrong}",
        f"Review cases with correct top suggestion: {summary.review_with_correct_top}",
        f"Top suggestion wrong: {summary.top_wrong}",
        f"Top suggestion correct: {summary.top_correct}",
        "Classifications:",
    ]
    lines.extend(f"  {name}: {count}" for name, count in summary.classifications)
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("collection", help="Path to a processed.json / Collection snapshot.")
    parser.add_argument("catalogue", help="Path to a KaizOFF/SMWC lightweight catalogue JSON.")
    args = parser.parse_args(argv)

    collection = _load_json(args.collection)
    if not isinstance(collection, Mapping):
        parser.error("Collection JSON must be an object keyed by Collection identity.")
    summary = calibrate_collection(collection, _load_json(args.catalogue))
    print(_format_summary(summary))
    return 1 if summary.auto_wrong or summary.top_wrong else 0


if __name__ == "__main__":
    raise SystemExit(main())
