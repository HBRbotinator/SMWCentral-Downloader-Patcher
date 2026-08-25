"""Read-only presentation model built exclusively from CollectionChangePlan."""
from __future__ import annotations

from dataclasses import dataclass

from collection_change_plan import CollectionChangePlan


_CORE_STORE_NAMES = frozenset({"collection", "collection_identity_hints"})


@dataclass(frozen=True)
class CollectionPlanPreviewSummary:
    """High-level counts shown above the final application preview."""

    creates: int
    updates: int
    identity_migrations: int
    rom_assets: int
    rom_provenance_updates: int
    primary_rom_selections: int
    imported_playthroughs: int
    user_state_changes: int
    ignored_roms: int
    remembered_associations: int
    skipped_items: int
    ignored_items: int
    dependent_reference_migrations: int
    dependent_stores: tuple[str, ...]


@dataclass(frozen=True)
class CollectionPlanPreviewRow:
    """One display-only row derived from a finalized plan operation."""

    category: str
    target: str
    change: str
    details: str


class CollectionIngestionPlanPreviewModel:
    """Project immutable plan operations without consulting session/provider state."""

    def __init__(self, plan: CollectionChangePlan):
        if not isinstance(plan, CollectionChangePlan):
            raise TypeError("CollectionIngestionPlanPreviewModel requires CollectionChangePlan.")
        self.plan = plan
        self._titles = self._target_titles(plan)

    def summary(self) -> CollectionPlanPreviewSummary:
        dependent_stores = self.dependent_store_names()
        return CollectionPlanPreviewSummary(
            creates=len(self.plan.creates),
            updates=len(self.plan.updates),
            identity_migrations=len(self.plan.identity_migrations),
            rom_assets=sum(len(item.assets) for item in self.plan.rom_updates),
            rom_provenance_updates=len(self.plan.rom_submission_provenance_updates),
            primary_rom_selections=len(self.plan.primary_rom_selections),
            imported_playthroughs=sum(
                len(item.playthroughs) for item in self.plan.user_history_updates
            ),
            user_state_changes=(
                len(self.plan.user_state_updates) + len(self.plan.first_clear_selections)
            ),
            ignored_roms=len(self.plan.ignored_roms),
            remembered_associations=len(self.plan.remembered_associations),
            skipped_items=len(self.plan.skipped_candidate_ids),
            ignored_items=len(self.plan.ignored_candidate_ids),
            dependent_reference_migrations=len(self.plan.reference_migrations),
            dependent_stores=dependent_stores,
        )

    def dependent_store_names(self) -> tuple[str, ...]:
        return tuple(
            item.store_name
            for item in self.plan.preconditions
            if item.store_name not in _CORE_STORE_NAMES
        )

    def rows(self) -> tuple[CollectionPlanPreviewRow, ...]:
        rows: list[CollectionPlanPreviewRow] = []
        stores = ", ".join(item.store_name for item in self.plan.preconditions)
        rows.append(
            CollectionPlanPreviewRow(
                category="Safety",
                target="",
                change="Reviewed store preconditions",
                details=stores or "None",
            )
        )

        for item in self.plan.record_intents:
            rows.append(
                CollectionPlanPreviewRow(
                    category="Collection",
                    target=self._target_label(item.target_key),
                    change=(
                        "Create Collection record"
                        if item in self.plan.creates
                        else "Update Collection record"
                    ),
                    details="Final target identity from completed review.",
                )
            )

        for item in self.plan.catalogue_updates:
            metadata = item.metadata
            parts = [metadata.title]
            if metadata.authors:
                parts.append("by " + ", ".join(metadata.authors))
            if metadata.difficulty:
                parts.append(metadata.difficulty)
            if metadata.hack_types:
                parts.append(", ".join(metadata.hack_types))
            if metadata.exits is not None:
                parts.append(f"{metadata.exits} exit(s)")
            if metadata.release_timestamp is not None:
                parts.append(f"release timestamp {metadata.release_timestamp}")
            if metadata.rating is not None:
                parts.append(f"rating {metadata.rating}")
            for label, value in (
                ("Hall of Fame", metadata.hall_of_fame),
                ("SA-1", metadata.sa1_compatible),
                ("collaboration", metadata.collaboration),
                ("demo", metadata.demo),
            ):
                if value is not None:
                    parts.append(f"{label}: {'yes' if value else 'no'}")
            rows.append(
                CollectionPlanPreviewRow(
                    category="Catalogue",
                    target=self._target_label(item.target_key),
                    change="Refresh durable KaizOFF/SMWC metadata",
                    details=" · ".join(parts),
                )
            )

        for item in self.plan.local_record_seeds:
            parts = [item.title]
            if item.authors:
                parts.append("by " + ", ".join(item.authors))
            if item.difficulty:
                parts.append(item.difficulty)
            if item.hack_types:
                parts.append(", ".join(item.hack_types))
            if item.exits is not None:
                parts.append(f"{item.exits} exit(s)")
            rows.append(
                CollectionPlanPreviewRow(
                    category="Local entry",
                    target=self._target_label(item.target_key),
                    change="Seed local/manual Collection metadata",
                    details=" · ".join(parts),
                )
            )

        for item in self.plan.identity_migrations:
            merge = "merge into existing target" if item.merge_existing_target else "move identity"
            provenance = "; ".join(item.provenance)
            prior = (
                " · prior SMWC IDs: " + ", ".join(str(value) for value in item.prior_submission_ids)
                if item.prior_submission_ids
                else ""
            )
            rows.append(
                CollectionPlanPreviewRow(
                    category="Identity",
                    target=f"{item.source_key} → {item.target_key}",
                    change=item.kind.value.replace("_", " ").title(),
                    details=f"{merge}. {provenance}{prior}".strip(),
                )
            )

        dependent_stores = self.dependent_store_names()
        for item in self.plan.reference_migrations:
            store_text = ", ".join(dependent_stores) or "registered dependent stores"
            rows.append(
                CollectionPlanPreviewRow(
                    category="References",
                    target=f"{item.source_key} → {item.target_key}",
                    change="Repoint dependent Collection references",
                    details=store_text,
                )
            )

        for item in self.plan.rom_updates:
            for asset in item.assets:
                provenance = ", ".join(source.value for source in asset.sources)
                suffix = ""
                if asset.smwc_submission_id is not None:
                    suffix = f" · SMWC provenance {asset.smwc_submission_id}"
                rows.append(
                    CollectionPlanPreviewRow(
                        category="ROM",
                        target=self._target_label(item.target_key),
                        change=(
                            "Retain ROM (primary)"
                            if item.primary_path == asset.path
                            else "Retain ROM"
                        ),
                        details=f"{asset.path} · SHA-256 {asset.sha256} · {provenance}{suffix}",
                    )
                )
            if item.preserve_existing_primary:
                rows.append(
                    CollectionPlanPreviewRow(
                        category="ROM",
                        target=self._target_label(item.target_key),
                        change="Preserve existing primary ROM",
                        details="No new primary path was selected.",
                    )
                )

        for item in self.plan.rom_submission_provenance_updates:
            rows.append(
                CollectionPlanPreviewRow(
                    category="ROM",
                    target=self._target_label(item.target_key),
                    change="Preserve SMWC submission provenance",
                    details=(
                        f"{item.path} · SMWC {item.smwc_submission_id} · {item.reason}"
                    ),
                )
            )

        for item in self.plan.user_history_updates:
            first_clear = "None / unknown"
            if item.first_clear_source is not None:
                first_clear = (
                    f"{item.first_clear_source.value}:"
                    f"{item.first_clear_source_record_id}"
                )
            rows.append(
                CollectionPlanPreviewRow(
                    category="History",
                    target=self._target_label(item.target_key),
                    change=f"Import {len(item.playthroughs)} playthrough(s)",
                    details=f"Selected first clear: {first_clear}",
                )
            )
            for playthrough in item.playthroughs:
                parts = [
                    value
                    for value in (
                        playthrough.play_kind,
                        playthrough.category,
                        playthrough.elapsed_text,
                        playthrough.completed_date_iso or playthrough.completed_date_text,
                        playthrough.notes,
                    )
                    if value
                ]
                rows.append(
                    CollectionPlanPreviewRow(
                        category="History detail",
                        target=self._target_label(item.target_key),
                        change=(
                            f"{playthrough.source.value}:"
                            f"{playthrough.source_record_id}"
                        ),
                        details=" · ".join(parts) or "Imported playthrough evidence",
                    )
                )

        for item in self.plan.user_state_updates:
            rows.append(
                CollectionPlanPreviewRow(
                    category="User state",
                    target=self._target_label(item.target_key),
                    change=f"Set {item.field} = {item.value!r}",
                    details=f"{item.source.value}: {item.reason}",
                )
            )

        for item in self.plan.primary_rom_selections:
            rows.append(
                CollectionPlanPreviewRow(
                    category="ROM",
                    target=self._target_label(item.target_key),
                    change="Select reviewed primary ROM",
                    details=f"{item.primary_path} · {item.reason}",
                )
            )

        for item in self.plan.first_clear_selections:
            rows.append(
                CollectionPlanPreviewRow(
                    category="User state",
                    target=self._target_label(item.target_key),
                    change="Select reviewed first-clear playthrough",
                    details=f"{item.source}:{item.source_record_id} · {item.reason}",
                )
            )

        for item in self.plan.remembered_associations:
            rows.append(
                CollectionPlanPreviewRow(
                    category="Matching hint",
                    target=self._target_label(item.target_key),
                    change="Remember reviewed source association",
                    details=f"{item.source.value}: {item.value}",
                )
            )

        for item in self.plan.ignored_roms:
            rows.append(
                CollectionPlanPreviewRow(
                    category="Ignore rule",
                    target="",
                    change="Ignore exact ROM discovery",
                    details=f"{item.path} · SHA-256 {item.sha256}",
                )
            )

        for candidate_id in self.plan.skipped_candidate_ids:
            rows.append(
                CollectionPlanPreviewRow(
                    category="Skipped",
                    target="",
                    change="Skip reviewed source item",
                    details=candidate_id,
                )
            )
        for candidate_id in self.plan.ignored_candidate_ids:
            rows.append(
                CollectionPlanPreviewRow(
                    category="Ignored",
                    target="",
                    change="Ignore reviewed source item",
                    details=candidate_id,
                )
            )
        return tuple(rows)

    def _target_label(self, target_key: str) -> str:
        title = self._titles.get(target_key, "")
        return f"{target_key} — {title}" if title else target_key

    @staticmethod
    def _target_titles(plan: CollectionChangePlan) -> dict[str, str]:
        result = {
            item.target_key: item.metadata.title
            for item in plan.catalogue_updates
            if item.metadata.title
        }
        for item in plan.local_record_seeds:
            if item.title:
                result.setdefault(item.target_key, item.title)
        return result


__all__ = [
    "CollectionIngestionPlanPreviewModel",
    "CollectionPlanPreviewRow",
    "CollectionPlanPreviewSummary",
]
