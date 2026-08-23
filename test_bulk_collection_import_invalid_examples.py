"""Checked malformed/real-world bulk Collection import fixtures."""
from __future__ import annotations
import tempfile, unittest
from pathlib import Path
from bulk_collection_import_application_preview import BulkCollectionImportApplicationPreviewError, build_v5_1_bulk_collection_import_application_preview
from bulk_collection_import_json import BulkCollectionImportJsonError, load_bulk_collection_import_json
from bulk_collection_import_review_form import build_bulk_collection_import_review_document, build_bulk_collection_import_review_form
from bulk_collection_import_workflow_preview import plan_v5_1_bulk_collection_import_workflow_preview
from bulk_collection_import_workflow_resolution import resolve_v5_1_bulk_collection_import_review
from hack_data_manager import HackDataManager
ROOT=Path(__file__).resolve().parent
INVALID_DIRECTORY=ROOT/'examples'/'bulk_collection_import'/'invalid'
class BulkCollectionImportInvalidExamplesTest(unittest.TestCase):
    def _empty_manager(self):
        temporary=tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        processed=Path(temporary.name)/'processed.json'; processed.write_text('{}\n',encoding='utf-8')
        manager=HackDataManager(str(processed)); manager._schedule_delayed_save=lambda:None; return manager
    def assert_json_error(self,filename,expected):
        path=INVALID_DIRECTORY/filename; self.assertTrue(path.is_file(),filename)
        with self.assertRaises(BulkCollectionImportJsonError) as raised: load_bulk_collection_import_json(path)
        message=str(raised.exception); self.assertIn(expected,message); return message
    def test_malformed_json_fixture_has_actionable_error(self):
        self.assertEqual(self.assert_json_error('malformed-json.json','contains malformed JSON'),'Bulk Collection import file contains malformed JSON.')
    def test_duplicate_object_key_names_the_problem_key(self):
        message=self.assert_json_error('duplicate-object-key.json','Duplicate JSON object key is not allowed: title'); self.assertNotIn('malformed JSON',message)
    def test_unexpected_top_level_field_names_the_extra_field(self):
        message=self.assert_json_error('unexpected-top-level-field.json','unexpected: provider'); self.assertIn('fields must match the versioned contract',message)
    def test_forbidden_user_state_names_the_reserved_attribute(self): self.assert_json_error('forbidden-user-state.json','user-owned Collection state: notes')
    def test_duplicate_source_identity_names_identity_and_owners(self):
        message=self.assert_json_error('duplicate-source-identity.json','Source reference belongs to more than one entry: smwc:12345'); self.assertIn('(first, second)',message)
    def test_missing_group_coverage_names_the_missing_entry(self): self.assert_json_error('missing-group-entry.json','missing: second')
    def test_unknown_group_entry_names_the_unknown_key(self): self.assert_json_error('unknown-group-entry.json','unknown entry_key: missing')
    def test_invalid_source_name_points_to_source_field(self):
        message=self.assert_json_error('invalid-source-name.json','source has an invalid identifier format'); self.assertIn('entries[0].source_references[0].source',message)
    def test_invalid_smwc_id_fails_before_apply_with_allocator_message(self):
        path=INVALID_DIRECTORY/'invalid-smwc-id.json'; manager=self._empty_manager(); loaded=load_bulk_collection_import_json(path)
        self.assertEqual(loaded.document.entries[0].source_references[0].external_id,'not-a-number')
        preview=plan_v5_1_bulk_collection_import_workflow_preview(str(path),manager); form=build_bulk_collection_import_review_form(preview); self.assertEqual(form.items,())
        review=build_bulk_collection_import_review_document(form,{})
        resolution=resolve_v5_1_bulk_collection_import_review(str(path),manager,review); self.assertEqual(resolution.summary['review_required'],0)
        with self.assertRaises(BulkCollectionImportApplicationPreviewError) as raised: build_v5_1_bulk_collection_import_application_preview(resolution,manager)
        message=str(raised.exception); self.assertIn('SMWCentral external IDs must be decimal.',message); self.assertNotIn('Apply failed',message)
    def test_invalid_fixture_directory_contains_only_checked_cases(self):
        expected={'malformed-json.json','duplicate-object-key.json','unexpected-top-level-field.json','forbidden-user-state.json','duplicate-source-identity.json','missing-group-entry.json','unknown-group-entry.json','invalid-source-name.json','invalid-smwc-id.json'}
        self.assertEqual({p.name for p in INVALID_DIRECTORY.iterdir() if p.is_file()},expected)
    def test_public_documentation_lists_common_failure_messages(self):
        source=(ROOT/'BULK_COLLECTION_IMPORT.md').read_text(encoding='utf-8')
        for required in ('## Common validation failures','malformed JSON','Duplicate JSON object key','unexpected: provider','user-owned Collection state','Source reference belongs to more than one entry','missing:','unknown entry_key','invalid identifier format','SMWCentral external IDs must be decimal','before any Apply confirmation'):
            with self.subTest(required=required): self.assertIn(required,source)
if __name__=='__main__': unittest.main(verbosity=2)
