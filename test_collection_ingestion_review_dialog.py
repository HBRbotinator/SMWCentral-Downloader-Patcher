"""Source contracts for the non-persisting Collection ingestion review workspace."""
from __future__ import annotations

import ast
from pathlib import Path
import unittest


_DIALOG = Path(__file__).parent / "ui" / "collection_ingestion_review_dialog.py"


class CollectionIngestionReviewDialogContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = _DIALOG.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source)

    def test_dialog_is_real_tk_review_ui(self):
        self.assertIn("class CollectionIngestionReviewDialog:", self.source)
        self.assertIn('self.win.title("Review Collection Import")', self.source)
        self.assertIn("ttk.Treeview", self.source)
        self.assertIn("Review Selected...", self.source)
        self.assertIn("Review Remaining", self.source)
        self.assertIn("Save & Next", self.source)
        self.assertIn("Continue", self.source)

    def test_item_decisions_use_a_dedicated_full_width_workspace(self):
        required = (
            "self.review_win = tk.Toplevel(self.win)",
            "self._size_item_review_window()",
            "screen_width - 80",
            "screen_height - 100",
            "width = min(1180, max(1",
            "height = min(960, max(1",
            'text="Review selected import item"',
            "full-width decision workspace",
            'self.tree.bind("<Double-1>"',
            "self._open_selected_review",
            "center_window_on_parent(self.review_win, self.win)",
        )
        for value in required:
            with self.subTest(value=value):
                self.assertIn(value, self.source)
        self.assertNotIn("ttk.Panedwindow(root", self.source)

    def test_needs_attention_is_an_unresolved_work_queue(self):
        self.assertIn("rows = self.model.rows(attention_only=False)", self.source)
        self.assertIn("row.blocking and not row.resolved", self.source)
        self.assertIn('tags = ("resolved",) if row.resolved else ()', self.source)
        self.assertIn('self.tree.tag_configure("resolved", foreground="gray")', self.source)
        self.assertIn("It remains available from All.", self.source)

    def test_save_and_next_advances_the_dedicated_workspace(self):
        save = next(
            node
            for node in ast.walk(self.tree)
            if isinstance(node, ast.FunctionDef) and node.name == "_save_current"
        )
        text = ast.get_source_segment(self.source, save)
        self.assertIn("self._select_next_unresolved(quiet=True)", text)
        self.assertIn("self._close_item_review()", text)
        self.assertIn("self._render_group(current)", text)

    def test_dialog_exposes_all_blocking_decision_families(self):
        required = (
            "ReviewAction.USE_TARGET",
            "ReviewAction.IMPORT_LOCAL",
            "ReviewAction.CONFIRM_MIGRATION",
            "ReviewAction.KEEP_SEPARATE",
            "ReviewAction.SKIP",
            "ReviewAction.IGNORE",
            "RomSelectionDecision",
            "UserFieldResolution",
            "FirstClearDecision",
            "RememberedAssociationDecision",
        )
        for value in required:
            with self.subTest(value=value):
                self.assertIn(value, self.source)

    def test_catalogue_search_is_session_local_not_network_or_provider_access(self):
        self.assertIn("self.model.search_catalogue", self.source)
        self.assertIn("catalogue snapshot only", self.source)
        forbidden = (
            "KaizOffCatalogueProvider",
            "requests.",
            "urllib",
            "urlopen",
            "get_hack(",
            "get_index(",
        )
        for value in forbidden:
            with self.subTest(value=value):
                self.assertNotIn(value, self.source)

    def test_dialog_cannot_apply_or_persist_collection_state(self):
        forbidden = (
            "HackDataManager",
            "CollectionIdentityHintsStore",
            "apply_collection_change_plan",
            "finalize_ingestion_session_plan",
            "collection_plan_apply",
            "collection_transaction",
            "processed.json",
            "config.json",
            "save_sync_reference_participant",
        )
        for value in forbidden:
            with self.subTest(value=value):
                self.assertNotIn(value, self.source)
        self.assertIn("Nothing changes until you apply the final preview.", self.source)

    def test_completion_callback_receives_only_detached_review_decisions(self):
        complete = next(
            node
            for node in ast.walk(self.tree)
            if isinstance(node, ast.FunctionDef) and node.name == "_complete"
        )
        text = ast.get_source_segment(self.source, complete)
        self.assertIn("decisions = self.model.decisions", text)
        self.assertIn("self.on_complete(decisions)", text)
        self.assertNotIn("self.close()", text)
        self.assertNotIn("finalize", text)
        self.assertNotIn("apply", text)

    def test_review_actions_stay_outside_scrollable_item_canvas(self):
        self.assertIn("item_canvas = tk.Canvas(workspace", self.source)
        self.assertIn("self.detail_actions = ttk.Frame(workspace", self.source)
        self.assertIn('text="Reset"', self.source)
        self.assertIn('text="Save & Next"', self.source)
        self.assertIn('text="Save"', self.source)
        self.assertIn("_save_current(advance=True)", self.source)

    def test_decision_sections_remain_compact_and_bounded(self):
        required = (
            'text="Why this needs review"',
            "height=min(2, max(1, len(lines)))",
            'height=4, selectmode="browse"',
            "height=min(2, max(1, len(context.local_suggestions)))",
            'orient="vertical", command=self.local_tree.yview',
            "list_height = 30 * min(4, max(1, len(group.rom_files)))",
            'text="ROM variants"',
            'text=f"ROM path: {path}"',
            "frame.pack_forget()",
        )
        for value in required:
            with self.subTest(value=value):
                self.assertIn(value, self.source)
        self.assertLess(
            self.source.index("self._render_local_metadata("),
            self.source.index("self._render_roms(group, previous, parent=self._support_left)"),
        )

    def test_identity_keeps_full_width_and_secondary_sections_share_lower_row(self):
        required = (
            "self._render_identity(group, context, previous, parent=self._decision_area)",
            "self._support_area = ttk.Frame(self._decision_area)",
            "self._support_left = ttk.Frame(self._support_area)",
            "self._support_right = ttk.Frame(self._support_area)",
            "self._render_roms(group, previous, parent=self._support_left)",
            "context, previous, parent=self._support_right",
            'mode = "wide" if width >= 760 else "stacked"',
            'left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))',
            'right.grid(row=0, column=1, sticky="nsew")',
            "area.columnconfigure(0, weight=3)",
            "area.columnconfigure(1, weight=2)",
        )
        for value in required:
            with self.subTest(value=value):
                self.assertIn(value, self.source)
        self.assertNotIn("_layout_decision_columns", self.source)

    def test_local_metadata_is_prioritized_before_rom_choices(self):
        render = next(
            node
            for node in ast.walk(self.tree)
            if isinstance(node, ast.FunctionDef) and node.name == "_render_group"
        )
        text = ast.get_source_segment(self.source, render)
        self.assertLess(
            text.index("self._render_local_metadata("),
            text.index("self._render_roms("),
        )
        self.assertIn("parent=self._decision_area", text)
        self.assertIn("directly below the identity choice", text)

    def test_review_copy_uses_user_facing_catalogue_language(self):
        self.assertIn('text="Search catalogue"', self.source)
        self.assertIn('text="Use selected SMWC match"', self.source)
        self.assertIn("Catalogue snapshot: ready", self.source)
        self.assertNotIn("Search KaizOFF", self.source)
        self.assertNotIn("frozen KaizOFF Index", self.source)
        self.assertNotIn("Select a KaizOFF result first", self.source)

    def test_full_width_catalogue_table_includes_author_and_detail_fallback(self):
        self.assertIn('"author": ("Author", 190)', self.source)
        self.assertIn("_catalogue_author_text(suggestion)", self.source)
        self.assertIn('parts.append(f"by {author}")', self.source)
        self.assertIn('"title": ("Local hack", 340)', self.source)
        self.assertIn('orient="horizontal"', self.source)
        self.assertIn("xscrollcommand=tree_hscroll.set", self.source)
        self.assertIn("_update_selected_suggestion_text", self.source)

    def test_single_rom_defaults_to_visible_primary(self):
        self.assertIn("if not default_primary and len(group.rom_files) == 1", self.source)
        self.assertIn("default_primary = group.rom_files[0].path", self.source)

    def test_diagnostics_export_is_metadata_only(self):
        self.assertIn('text="Export Diagnostics..."', self.source)
        self.assertIn("write_diagnostic_report", self.source)
        self.assertIn("no absolute", self.source.lower())
        self.assertNotIn("open(rom.path", self.source)

    def test_dialog_keeps_rom_ignore_path_hash_semantics(self):
        self.assertIn("IgnoredRomDecision(path=path, sha256=by_path[path].sha256)", self.source)
        self.assertIn('(\"Keep\", \"Ignore\", \"Leave out\")', self.source)
        self.assertIn("Primary", self.source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
