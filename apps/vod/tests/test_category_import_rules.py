"""VOD import rules stay independent of title identity and enrichment."""

import tempfile
from unittest.mock import Mock, patch

from django.test import TestCase

from apps.m3u.group_rules import CategoryImportMap
from apps.m3u.models import M3UAccount, M3UGroupRule
from apps.vod.models import Movie, M3UVODCategoryRelation, Series, VODCategory
from apps.vod.tasks import (
    _category_import_map,
    batch_create_categories,
    process_movie_batch,
    process_series_batch,
    refresh_movies,
    refresh_series,
)


class CategoryImportRuleTests(TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        override = self.settings(M3U_FILTER_CATALOG_ROOT=directory.name)
        override.enable()
        self.addCleanup(override.disable)
        self.account = M3UAccount.objects.create(name="vod-rules", account_type="XC")

    def rule(self, pattern, action, scope="movie", **values):
        return M3UGroupRule.objects.create(
            m3u_account=self.account,
            scope=scope,
            regex_pattern=pattern,
            action=action,
            **values,
        )

    def test_new_categories_follow_first_rule_and_default(self):
        self.rule("Ignored", "ignore")
        self.rule("Disabled", "disable", order=1)
        self.rule("Enabled", "enable", order=2)
        result = batch_create_categories(
            [
                {"category_name": "Ignored"},
                {"category_name": "Disabled"},
                {"category_name": "Enabled"},
                {"category_name": "Enabled"},
            ],
            "movie",
            self.account,
        )
        self.assertEqual(result.ignored, {"Ignored"})
        self.assertFalse(M3UVODCategoryRelation.objects.get(
            category=result["Ignored"], m3u_account=self.account
        ).enabled)
        self.assertFalse(
            M3UVODCategoryRelation.objects.get(category=result["Disabled"]).enabled
        )
        self.assertTrue(
            M3UVODCategoryRelation.objects.get(category=result["Enabled"]).enabled
        )

    def test_existing_account_selection_is_not_replaced(self):
        category = VODCategory.objects.create(name="Known", category_type="movie")
        relation = M3UVODCategoryRelation.objects.create(
            category=category, m3u_account=self.account, enabled=False
        )
        self.rule("Known", "ignore")
        result = batch_create_categories(
            [{"category_name": "Known"}], "movie", self.account
        )
        relation.refresh_from_db()
        self.assertFalse(relation.enabled)
        self.assertIn("Known", result)
        self.assertFalse(result.ignored)

    def test_new_unmatched_categories_are_disabled_despite_legacy_auto_enable(self):
        self.account.custom_properties = {
            "auto_enable_new_groups_vod": True,
            "auto_enable_new_groups_series": True,
        }
        self.account.save()
        for scope in ("movie", "series"):
            with self.subTest(scope=scope):
                result = batch_create_categories(
                    [{"category_name": "Unmatched"}], scope, self.account
                )
                self.assertFalse(
                    M3UVODCategoryRelation.objects.get(
                        m3u_account=self.account, category=result["Unmatched"]
                    ).enabled
                )

    def test_shared_global_category_is_new_to_this_account(self):
        category = VODCategory.objects.create(name="Shared", category_type="movie")
        self.rule("Shared", "disable")
        result = batch_create_categories(
            [{"category_name": "Shared"}], "movie", self.account
        )
        self.assertEqual(result["Shared"].id, category.id)
        self.assertFalse(
            M3UVODCategoryRelation.objects.get(
                category=category, m3u_account=self.account
            ).enabled
        )

    def test_category_rules_do_not_fetch_content_before_import(self):
        for scope, fetch_name, refresh in (
            ("movie", "get_vod_streams", refresh_movies),
            ("series", "get_series", refresh_series),
        ):
            with self.subTest(scope=scope):
                self.rule("^Season$", "enable", scope=scope)
                client = Mock()
                getattr(client, fetch_name).return_value = [
                    {"name": "Anime", "category_id": 2}
                ]
                result = _category_import_map(
                    [{"category_name": "Season", "category_id": 2}],
                    scope,
                    self.account,
                )
                self.assertEqual(client.mock_calls, [])
                relations = {
                    rel.category_id: rel
                    for rel in M3UVODCategoryRelation.objects.filter(
                        m3u_account=self.account
                    )
                }
                with patch(f"apps.vod.tasks.process_{scope}_batch"):
                    refresh(client, self.account, result, relations)
                getattr(client, fetch_name).assert_called_once_with()

    def test_ignored_category_items_do_not_fall_back_to_uncategorized(self):
        categories = CategoryImportMap(ignored={"42"})
        process_movie_batch(
            self.account,
            [{"stream_id": 1, "name": "Ignored movie", "category_id": 42}],
            categories,
            {},
        )
        process_series_batch(
            self.account,
            [{"series_id": 1, "name": "Ignored series", "category_id": 42}],
            categories,
            {},
        )
        self.assertFalse(Movie.objects.filter(name="Ignored movie").exists())
        self.assertFalse(Series.objects.filter(name="Ignored series").exists())
