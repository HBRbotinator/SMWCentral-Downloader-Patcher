import unittest

from download_identity_policy import provider_marks_obsolete, same_title_collection_ids


class ProviderObsoletePolicyTest(unittest.TestCase):
    def test_provider_flag_is_authoritative_regardless_of_numeric_id_order(self):
        self.assertFalse(
            provider_marks_obsolete({"id": "50000", "raw_fields": {"obsolete": False}})
        )
        self.assertTrue(
            provider_marks_obsolete({"id": "100", "raw_fields": {"obsolete": True}})
        )

    def test_top_level_flag_is_only_a_compatibility_fallback(self):
        self.assertTrue(provider_marks_obsolete({"obsolete": True}))
        self.assertFalse(
            provider_marks_obsolete(
                {"obsolete": True, "raw_fields": {"obsolete": False}}
            )
        )


class SameTitleCollectionPolicyTest(unittest.TestCase):
    def test_same_title_ids_are_advisory_and_do_not_mutate_collection_state(self):
        processed = {
            "100": {"title": "Quickie World", "obsolete": False},
            "99999": {"title": "Quickie World", "obsolete": False},
            "usr_deadbeefdeadbeef": {"title": "Different Hack", "obsolete": False},
        }
        before = {key: dict(value) for key, value in processed.items()}

        matches = same_title_collection_ids(processed, "500", "Quickie World")

        self.assertEqual(("100", "99999"), matches)
        self.assertEqual(before, processed)

    def test_current_id_and_different_titles_are_excluded(self):
        processed = {
            "500": {"title": "Quickie World"},
            "600": {"title": "Quickie World 2"},
        }
        self.assertEqual(
            (), same_title_collection_ids(processed, "500", "Quickie World")
        )


if __name__ == "__main__":
    unittest.main()
