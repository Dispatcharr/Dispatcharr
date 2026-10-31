"""Literal additions share one global rule set across import, preview and jobs."""

from unittest.mock import patch

from django.test import SimpleTestCase, TestCase

from apps.vod import library
from apps.vod.canonical_import import import_title
from apps.vod.models import VODMetadataState
from apps.vod.tasks import extract_year_from_data
from apps.vod.title_cleanup import clean_lookup_title, normalize_removal_rules

from . import test_library as fixtures


class LiteralRemovalTests(SimpleTestCase):
    def test_removals_are_literal_anywhere_and_run_before_end_only_year_rules(self):
        title = "DE - (ES) Film - 2020 (IT)"
        rules = ["(ES)", "(IT)"]
        years = [{"value": "- YYYY", "position": "end"}]
        self.assertEqual(
            clean_lookup_title(
                title, rules=["DE - "], removal_rules=rules, year_rules=years
            ),
            "Film",
        )
        self.assertEqual(
            extract_year_from_data(
                {"name": title}, year_rules=years, removal_rules=rules
            ),
            2020,
        )
        self.assertEqual(title, "DE - (ES) Film - 2020 (IT)")
        self.assertEqual(
            clean_lookup_title("A .* Film (ES) (ES)", removal_rules=[".*", "(ES)"]),
            "A Film",
        )
        self.assertEqual(clean_lookup_title("A (es)", removal_rules=["(ES)"]), "A (es)")

    def test_disabled_rules_and_title_numbers_are_preserved(self):
        for title in ("2012", "Blade Runner 2049"):
            self.assertEqual(
                clean_lookup_title(f"{title} (ES)", removal_rules=["(ES)"]), title
            )
        self.assertEqual(
            clean_lookup_title(
                "Film (ES)", removal_rules=[{"value": "(ES)", "enabled": False}]
            ),
            "Film (ES)",
        )
        for value in ([""], ["x"] * 21, [{"value": "x" * 256}]):
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_removal_rules(value)


class SharedLiteralCleanupTests(TestCase):
    setUp = fixtures.LibraryTests.setUp
    endpoint = fixtures.LibraryTests.endpoint
    selection = fixtures.LibraryTests.selection

    @patch("apps.vod.tasks.enrich_vod_library.apply_async")
    def test_global_settings_preview_import_and_job_use_the_same_saved_rules(
        self, _publish
    ):
        self.source.custom_properties = {
            "basic_data": {"name": "NF - Film - 2020 (ES)"}
        }
        self.source.save()
        response = self.client.put(
            self.endpoint("settings"),
            {
                "title_rules": ["NF - "],
                "removal_rules": ["(ES)"],
                "year_rules": [{"value": "- YYYY", "position": "end"}],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(
            response.data["removal_rules"], [{"value": "(ES)", "enabled": True}]
        )
        rules = library.library_settings()
        self.assertEqual(import_title("NF - Film - 2020 (ES)", 2020, rules), "Film")
        response = self.client.post(
            self.endpoint("cleanup-preview"), self.selection(), format="json"
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(
            (response.data["results"][0]["after"], response.data["results"][0]["year"]),
            ("Film", 2020),
        )
        response = self.client.post(
            self.endpoint("bulk"), self.selection(operation="cleanup"), format="json"
        )
        self.assertEqual(response.status_code, 202, response.data)
        state = VODMetadataState.objects.get(pk=1)
        self.assertEqual(
            state.progress["settings"]["removal_rules"],
            [{"value": "(ES)", "enabled": True}],
        )
        library.save_library_settings({"removal_rules": []})
        library.run_library_job(state.task_id)
        self.movie.refresh_from_db()
        self.source.refresh_from_db()
        self.assertEqual(self.movie.clean_title, "Film")
        self.assertEqual(
            self.source.custom_properties["basic_data"]["name"], "NF - Film - 2020 (ES)"
        )

    def test_duplicate_literal_rules_are_rejected_without_changing_global_settings(
        self,
    ):
        for field in ("title_rules", "removal_rules"):
            response = self.client.put(
                self.endpoint("settings"), {field: ["(ES)", "(ES)"]}, format="json"
            )
            self.assertEqual(response.status_code, 400, response.data)
            self.assertEqual(library.library_settings()[field], [])
