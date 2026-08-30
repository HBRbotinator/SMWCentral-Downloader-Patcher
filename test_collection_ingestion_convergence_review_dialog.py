"""Source contracts for the detached combined-ROM convergence review UI."""
from __future__ import annotations

import ast
from pathlib import Path
import unittest


_DIALOG = Path(__file__).parent / "ui" / "collection_ingestion_convergence_review_dialog.py"
_PAGE = Path(__file__).parent / "ui" / "pages" / "collection_page.py"
_REVIEW = Path(__file__).parent / "ui" / "collection_ingestion_review_dialog.py"


class CollectionIngestionConvergenceReviewDialogContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = _DIALOG.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source)
        cls.page_source = _PAGE.read_text(encoding="utf-8")
        cls.review_source = _REVIEW.read_text(encoding="utf-8")

    def test_dialog_is_read_only_combined_rom_review(self):
        self.assertIn("Review Combined ROM Variants", self.source)
        self.assertIn("ConvergedRomDecision", self.source)
        self.assertIn("RomSelectionDecision", self.source)
        self.assertIn("Save Decision", self.source)
        self.assertIn("Primary", self.source)
        self.assertIn("Nothing is written from this dialog", self.source)
        for forbidden in (
            "KaizOffCatalogueProvider",
            "requests.",
            "HackDataManager",
            "apply_collection_change_plan",
            "processed.json",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, self.source)

    def test_single_retained_rom_becomes_primary_without_extra_click(self):
        self.assertIn("if len(kept) == 1:", self.source)
        self.assertIn("primary = kept[0]", self.source)

    def test_main_review_stays_alive_while_finalization_runs(self):
        complete = next(
            node
            for node in ast.walk(ast.parse(self.review_source))
            if isinstance(node, ast.FunctionDef) and node.name == "_complete"
        )
        text = ast.get_source_segment(self.review_source, complete)
        self.assertIn("self.on_complete(decisions)", text)
        self.assertNotIn("self.close()", text)
        self.assertIn("def set_submitting", self.review_source)

    def test_page_routes_convergence_before_finalization_and_restores_review_on_error(self):
        self.assertIn("build_converged_rom_reviews", self.page_source)
        self.assertIn("CollectionIngestionConvergenceReviewDialog", self.page_source)
        self.assertIn("converged_rom_decisions=converged_rom_decisions", self.page_source)
        self.assertIn("Your review choices are still open", self.page_source)
        self.assertIn("review_dialog.set_submitting(False)", self.page_source)
        self.assertIn("review_dialog.lift()", self.page_source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
