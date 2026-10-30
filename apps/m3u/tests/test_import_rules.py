"""Ordered import policy, account isolation and complete draft previews."""

import os
import tempfile
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.utils.dateparse import parse_datetime
from rest_framework.test import APIClient

from apps.channels.models import ChannelGroup, ChannelGroupM3UAccount, Stream
from apps.m3u.filter_catalog import (
    discard_live_filter_catalog,
    has_live_filter_catalog,
    iter_live_filter_catalog,
    publish_live_filter_catalog,
    write_live_filter_catalog,
)
from apps.m3u.group_rules import compile_group_rules, evaluate_group_rules
from apps.m3u.models import M3UAccount, M3UFilter, M3UGroupRule
from apps.m3u.tasks import process_groups
from apps.vod.models import (
    Movie,
    M3UMovieRelation,
    M3UVODCategoryRelation,
    VODCategory,
)


def draft(rule_id="new", **values):
    return {
        "preview_id": str(rule_id),
        "scope": "live",
        "match_field": "group_name",
        "match_mode": "any",
        "regex_pattern": ".*",
        "action": "enable",
        "case_sensitive": False,
        "enabled": True,
        "order": 0,
        **values,
    }


class RuleEvaluationTests(SimpleTestCase):
    def evaluate(self, *rules, **values):
        objects = [
            M3UGroupRule(id=index + 1, **rule) for index, rule in enumerate(rules)
        ]
        return evaluate_group_rules(compile_group_rules(objects), **values)

    def test_first_matching_rule_wins(self):
        result = self.evaluate(
            {"regex_pattern": "news", "action": "disable"},
            {"regex_pattern": ".*", "action": "enable"},
            group_name="NEWS",
        )
        self.assertFalse(result.enabled)
        self.assertEqual(result.matched_rule_id, 1)

    def test_inactive_rule_and_case_sensitive_rule_do_not_match(self):
        result = self.evaluate(
            {"regex_pattern": ".*", "enabled": False},
            {"regex_pattern": "news", "case_sensitive": True},
            group_name="NEWS",
            default_enabled=True,
        )
        self.assertTrue(result.enabled)
        self.assertIsNone(result.matched_rule_id)

    def test_unsupported_predicates_are_not_reinterpreted_as_category_matches(self):
        for field, mode in (("item_name", "any"), ("item_name", "all"), ("group_name", "all")):
            with self.subTest(field=field, mode=mode):
                result = self.evaluate(
                    {
                        "regex_pattern": ".*",
                        "match_field": field,
                        "match_mode": mode,
                        "action": "enable",
                    },
                    group_name="News",
                )
                self.assertFalse(result.enabled)
                self.assertIsNone(result.matched_rule_id)


class FilterCatalogTests(SimpleTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.settings_override = self.settings(
            M3U_FILTER_CATALOG_ROOT=self.directory.name
        )
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)

    def stream(self, name):
        return {
            "name": name,
            "url": "http://private.invalid/secret",
            "attributes": {"group-title": "News"},
        }

    def test_persists_full_prefilter_inventory_with_private_permissions(self):
        self.assertTrue(
            write_live_filter_catalog(1, [self.stream("###"), self.stream("News")])
        )
        self.assertEqual(
            [row["name"] for row in iter_live_filter_catalog(1)], ["###", "News"]
        )
        path = os.path.join(self.directory.name, "1.live-filter-preview.jsonl.gz")
        self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)

    def test_failed_write_keeps_previous_completed_catalog(self):
        write_live_filter_catalog(1, [self.stream("old")])

        def broken():
            yield self.stream("partial")
            raise RuntimeError("upstream failed")

        self.assertFalse(write_live_filter_catalog(1, broken()))
        self.assertEqual(next(iter_live_filter_catalog(1))["name"], "old")
        self.assertEqual(len(os.listdir(self.directory.name)), 1)

    def test_staged_inventory_is_not_visible_until_completed(self):
        staged = write_live_filter_catalog(1, [self.stream("new")], publish=False)
        self.assertFalse(has_live_filter_catalog(1))
        publish_live_filter_catalog(1, staged)
        self.assertTrue(has_live_filter_catalog(1))
        discarded = write_live_filter_catalog(
            1, [self.stream("partial")], publish=False
        )
        discard_live_filter_catalog(discarded)
        self.assertEqual(next(iter_live_filter_catalog(1))["name"], "new")


class ImportRuleApiTests(TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.override = self.settings(M3U_FILTER_CATALOG_ROOT=self.directory.name)
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.account = M3UAccount.objects.create(name="rules", account_type="XC")
        self.other = M3UAccount.objects.create(name="other", account_type="XC")
        self.client = APIClient()
        self.admin = get_user_model().objects.create_user(
            username="rule-admin", user_level=10
        )
        self.client.force_authenticate(self.admin)
        self.url = f"/api/m3u/accounts/{self.account.id}/group-rules/"

    def group(self, name, enabled=False, account=None):
        group = ChannelGroup.objects.create(name=name)
        return ChannelGroupM3UAccount.objects.create(
            m3u_account=account or self.account,
            channel_group=group,
            enabled=enabled,
        )

    def post_preview(self, rules, target="new", query=""):
        return self.client.post(
            self.url + "preview-draft/" + query,
            {"rules": rules, "target_id": str(target)},
            format="json",
        )

    def test_preview_is_read_only_and_evaluates_complete_ordered_draft(self):
        relation = self.group("News")
        response = self.post_preview(
            [
                draft("earlier", action="disable", regex_pattern="News"),
                draft("new", order=1),
            ]
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 0)
        self.assertFalse(M3UGroupRule.objects.exists())
        relation.refresh_from_db()
        self.assertFalse(relation.enabled)

    def test_preview_paginates_all_matches_without_200_row_cap(self):
        groups = ChannelGroup.objects.bulk_create(
            [ChannelGroup(name=f"Group {i}") for i in range(230)]
        )
        ChannelGroupM3UAccount.objects.bulk_create(
            [
                ChannelGroupM3UAccount(m3u_account=self.account, channel_group=group)
                for group in groups
            ]
        )
        self.group("Other account", account=self.other)
        response = self.post_preview([draft()], query="?page=5&page_size=50")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 230)
        self.assertEqual(len(response.data["results"]), 30)
        self.assertEqual(response.data["inventory_count"], 230)

    def test_group_preview_metadata_is_scoped_and_uses_live_refresh_fallback(self):
        self.group("News")
        self.group("Sport")
        self.group("Foreign", account=self.other)
        completed = "2026-10-14T06:00:00Z"
        self.account.custom_properties = {
            "refresh_timings": {"live_completed_at": completed}
        }
        self.account.save()
        response = self.post_preview([draft(regex_pattern="News")])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            (response.data["count"], response.data["inventory_count"]), (1, 2)
        )
        self.assertEqual(
            parse_datetime(response.data["last_completed_refresh"]),
            parse_datetime(completed),
        )
        self.assertFalse(response.data["catalog_complete"])

    def test_group_preview_uses_completed_catalog_timestamp(self):
        self.group("News")
        write_live_filter_catalog(self.account.id, [], scope="live-groups")
        path = os.path.join(
            self.directory.name,
            f"{self.account.id}.live-groups-filter-preview.jsonl.gz",
        )
        timestamp = parse_datetime("2026-10-14T06:00:00Z")
        os.utime(path, (timestamp.timestamp(), timestamp.timestamp()))
        self.account.custom_properties = {
            "refresh_timings": {"live_completed_at": "2026-10-15T06:00:00Z"}
        }
        self.account.save()
        response = self.post_preview([draft()])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            parse_datetime(response.data["last_completed_refresh"]), timestamp
        )
        self.assertTrue(response.data["catalog_complete"])

    def test_vod_preview_metadata_does_not_use_live_refresh_or_other_scopes(self):
        for scope, name in (("movie", "News Movies"), ("series", "News Series")):
            category = VODCategory.objects.create(name=name, category_type=scope)
            M3UVODCategoryRelation.objects.create(
                m3u_account=self.account, category=category
            )
        self.group("News Live")
        completed = "2026-10-13T03:00:00Z"
        self.account.custom_properties = {
            "refresh_timings": {
                "vod_completed_at": completed,
                "live_completed_at": "2026-10-15T06:00:00Z",
            }
        }
        self.account.save()
        response = self.post_preview([draft(scope="movie")])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            (response.data["count"], response.data["inventory_count"]), (1, 1)
        )
        self.assertEqual(
            parse_datetime(response.data["last_completed_refresh"]),
            parse_datetime(completed),
        )

    def test_save_does_not_change_existing_selections(self):
        relation = self.group("News")
        values = draft()
        values.pop("preview_id")
        response = self.client.post(self.url, values, format="json")
        self.assertEqual(response.status_code, 201)
        relation.refresh_from_db()
        self.assertFalse(relation.enabled)

    def test_duplicate_group_match_is_rejected_on_create_and_update(self):
        values = draft(regex_pattern="AFR")
        values.pop("preview_id")
        first = self.client.post(self.url, values, format="json")
        self.assertEqual(first.status_code, 201)
        duplicate = self.client.post(
            self.url, {**values, "action": "disable"}, format="json"
        )
        self.assertEqual(duplicate.status_code, 400)
        self.assertIn("regex_pattern", duplicate.data)
        self.assertEqual(self.account.group_rules.count(), 1)
        same = self.client.patch(
            self.url + f"{first.data['id']}/", {"action": "disable"}, format="json"
        )
        self.assertEqual(same.status_code, 200)
        other = M3UGroupRule.objects.create(
            m3u_account=self.account, scope="live", regex_pattern="EU"
        )
        changed = self.client.patch(
            self.url + f"{other.id}/", {"regex_pattern": "AFR"}, format="json"
        )
        self.assertEqual(changed.status_code, 400)
        other.refresh_from_db()
        self.assertEqual(other.regex_pattern, "EU")

    def test_duplicate_identity_respects_scope_field_case_and_item_mode(self):
        values = draft(regex_pattern="AFR")
        values.pop("preview_id")
        M3UGroupRule.objects.create(m3u_account=self.account, **values)
        for differences in (
            {"scope": "movie"},
            {"scope": "series"},
            {"case_sensitive": True},
            {"enabled": False},
        ):
            with self.subTest(differences=differences):
                response = self.client.post(
                    self.url, {**values, **differences}, format="json"
                )
                self.assertEqual(response.status_code, 201, response.data)
        ignored_mode = self.client.post(
            self.url, {**values, "match_mode": "all"}, format="json"
        )
        self.assertEqual(ignored_mode.status_code, 400)
        foreign = self.client.post(
            f"/api/m3u/accounts/{self.other.id}/group-rules/", values, format="json"
        )
        self.assertEqual(foreign.status_code, 201)

    def test_enabling_an_inactive_duplicate_is_rejected_without_changing_it(self):
        M3UGroupRule.objects.create(
            m3u_account=self.account, scope="live", regex_pattern="AFR"
        )
        inactive = M3UGroupRule.objects.create(
            m3u_account=self.account, scope="live", regex_pattern="AFR", enabled=False
        )
        response = self.client.patch(
            self.url + f"{inactive.id}/", {"enabled": True}, format="json"
        )
        self.assertEqual(response.status_code, 400)
        inactive.refresh_from_db()
        self.assertFalse(inactive.enabled)

    def test_filter_duplicates_respect_account_field_and_case(self):
        url = f"/api/m3u/accounts/{self.account.id}/filters/"
        values = {
            "filter_type": "name",
            "regex_pattern": "AFR",
            "exclude": True,
            "custom_properties": {"case_sensitive": False},
        }
        first = self.client.post(url, values, format="json")
        self.assertEqual(first.status_code, 201)
        duplicate = self.client.post(url, {**values, "exclude": False}, format="json")
        self.assertEqual(duplicate.status_code, 400)
        self.assertIn("regex_pattern", duplicate.data)
        self.assertEqual(self.account.filters.count(), 1)
        same = self.client.patch(
            url + f"{first.data['id']}/", {"exclude": False}, format="json"
        )
        self.assertEqual(same.status_code, 200)
        for differences in (
            {"filter_type": "url"},
            {"custom_properties": {"case_sensitive": True}},
        ):
            response = self.client.post(url, {**values, **differences}, format="json")
            self.assertEqual(response.status_code, 201, response.data)
        other = M3UFilter.objects.create(
            m3u_account=self.account,
            filter_type="name",
            regex_pattern="EU",
            custom_properties={"case_sensitive": False},
        )
        response = self.client.patch(
            url + f"{other.id}/", {"regex_pattern": "AFR"}, format="json"
        )
        self.assertEqual(response.status_code, 400)
        other.refresh_from_db()
        self.assertEqual(other.regex_pattern, "EU")
        foreign = self.client.post(
            f"/api/m3u/accounts/{self.other.id}/filters/", values, format="json"
        )
        self.assertEqual(foreign.status_code, 201)

    def test_filters_default_active_and_paused_duplicates_cannot_be_enabled(self):
        url = f"/api/m3u/accounts/{self.account.id}/filters/"
        values = {"filter_type": "name", "regex_pattern": "News"}
        active = self.client.post(url, values, format="json")
        self.assertEqual(active.status_code, 201)
        self.assertTrue(active.data["enabled"])
        paused = self.client.post(url, {**values, "enabled": False}, format="json")
        self.assertEqual(paused.status_code, 201)
        response = self.client.patch(
            url + f"{paused.data['id']}/", {"enabled": True}, format="json"
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(M3UFilter.objects.get(pk=paused.data["id"]).enabled)

    def test_disabled_filter_does_not_shadow_later_filter_in_preview(self):
        write_live_filter_catalog(self.account.id, [{
            "name": "News",
            "url": "http://example.invalid/live",
            "attributes": {"group-title": "News"},
        }])
        rows = [
            {
                "preview_id": "paused", "filter_type": "name",
                "regex_pattern": ".*", "exclude": True,
                "enabled": False, "order": 0,
            },
            {
                "preview_id": "active", "filter_type": "name",
                "regex_pattern": ".*", "exclude": False,
                "enabled": True, "order": 1,
            },
        ]
        url = f"/api/m3u/accounts/{self.account.id}/filters/preview-draft/"
        for target, count in (("paused", 0), ("active", 1)):
            response = self.client.post(
                url, {"rules": rows, "target_id": target}, format="json"
            )
            self.assertEqual(response.status_code, 200, response.data)
            self.assertEqual(response.data["count"], count)
            self.assertEqual(response.data["rule_coverage"], [
                {"rule_id": "paused", "count": 0},
                {"rule_id": "active", "count": 1},
            ])

    def test_disabled_rule_cannot_apply_or_save_apply(self):
        relation = self.group("News", enabled=True)
        rule = M3UGroupRule.objects.create(
            m3u_account=self.account, scope="live", regex_pattern=".*",
            action="disable", enabled=False,
        )
        response = self.client.post(self.url + f"{rule.pk}/apply/")
        self.assertEqual(response.status_code, 400)
        response = self.client.post(self.url + "save-apply/", {
            "rules": [draft(rule.pk, action="disable", enabled=False)],
            "target_id": str(rule.pk),
        }, format="json")
        self.assertEqual(response.status_code, 400)
        relation.refresh_from_db()
        self.assertTrue(relation.enabled)

    def test_save_apply_validates_the_final_list_before_any_writes(self):
        relation = self.group("AFR")
        first = M3UGroupRule.objects.create(
            m3u_account=self.account, scope="live", regex_pattern="AFR"
        )
        second = M3UGroupRule.objects.create(
            m3u_account=self.account, scope="live", regex_pattern="EU", order=1
        )
        duplicate = self.client.post(
            self.url + "save-apply/",
            {
                "rules": [
                    draft(first.id, regex_pattern="AFR"),
                    draft(second.id, regex_pattern="AFR", order=1),
                ],
                "target_id": str(first.id),
            },
            format="json",
        )
        self.assertEqual(duplicate.status_code, 400)
        second.refresh_from_db()
        relation.refresh_from_db()
        self.assertEqual(second.regex_pattern, "EU")
        self.assertFalse(relation.enabled)
        swapped = self.client.post(
            self.url + "save-apply/",
            {
                "rules": [
                    draft(first.id, regex_pattern="EU"),
                    draft(second.id, regex_pattern="AFR", order=1),
                ],
                "target_id": str(second.id),
            },
            format="json",
        )
        self.assertEqual(swapped.status_code, 200, swapped.data)
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual((first.regex_pattern, second.regex_pattern), ("EU", "AFR"))

    def test_coverage_is_evaluated_for_arbitrary_regexes_not_special_catch_all_text(
        self,
    ):
        self.group("News")
        self.group("Sport")
        for pattern in (r"[\s\S]+", "News|Sport", "(?i)news|sport", ".*"):
            with self.subTest(pattern=pattern):
                response = self.post_preview(
                    [
                        draft("first", regex_pattern=pattern),
                        draft("later", regex_pattern="Sport", order=1),
                    ],
                    target="first",
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    response.data["rule_coverage"],
                    [
                        {"rule_id": "first", "count": 2},
                        {"rule_id": "later", "count": 0},
                    ],
                )

    def test_stream_coverage_uses_order_and_actual_inventory(self):
        write_live_filter_catalog(
            self.account.id,
            [
                {"name": "News", "attributes": {}},
                {"name": "Sport", "attributes": {}},
            ],
        )
        response = self.client.post(
            f"/api/m3u/accounts/{self.account.id}/filters/preview-draft/",
            {
                "target_id": "one",
                "rules": [
                    {
                        "preview_id": "one",
                        "filter_type": "name",
                        "regex_pattern": "News|Sport",
                        "exclude": True,
                        "order": 0,
                    },
                    {
                        "preview_id": "two",
                        "filter_type": "name",
                        "regex_pattern": "Sport",
                        "exclude": False,
                        "order": 1,
                    },
                ],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data["rule_coverage"],
            [{"rule_id": "one", "count": 2}, {"rule_id": "two", "count": 0}],
        )

    def test_save_apply_updates_target_only_and_keeps_other_properties(self):
        relation = self.group("News")
        relation.custom_properties = {"channel_numbering_mode": "provider"}
        relation.save()
        untouched = self.group("Sport")
        foreign = self.group("News other", account=self.other)
        response = self.client.post(
            self.url + "save-apply/",
            {
                "rules": [draft(regex_pattern="^News$")],
                "target_id": "new",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["target_ids"], [relation.channel_group_id])
        relation.refresh_from_db()
        untouched.refresh_from_db()
        foreign.refresh_from_db()
        self.assertTrue(relation.enabled)
        self.assertEqual(
            relation.custom_properties["channel_numbering_mode"], "provider"
        )
        self.assertFalse(untouched.enabled)
        self.assertFalse(foreign.enabled)

    def test_stale_or_foreign_draft_cannot_overwrite_saved_rules(self):
        rule = M3UGroupRule.objects.create(
            m3u_account=self.other, scope="live", regex_pattern="News"
        )
        response = self.client.post(
            self.url + "save-apply/",
            {
                "rules": [draft(rule.id)],
                "target_id": str(rule.id),
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        rule.refresh_from_db()
        self.assertEqual(rule.m3u_account_id, self.other.id)
        self.assertFalse(self.account.group_rules.exists())

    def test_ignore_applies_without_deleting_existing_entries(self):
        relation = self.group("News", enabled=True)
        response = self.client.post(
            self.url + "save-apply/",
            {
                "rules": [draft(action="ignore")],
                "target_id": "new",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(
            ChannelGroupM3UAccount.objects.filter(pk=relation.pk, enabled=False, ignored=True).exists()
        )

    def test_invalid_regex_scope_target_and_pagination_are_rejected(self):
        for rows, target, query in (
            ([draft(regex_pattern="[")], "new", ""),
            ([draft(), draft("series", scope="series")], "new", ""),
            ([draft()], "missing", ""),
            ([draft(), draft()], "new", ""),
            ([draft()], "new", "?page=0"),
            ([draft()], "new", "?page_size=101"),
        ):
            with self.subTest(rows=rows, query=query):
                self.assertEqual(
                    self.post_preview(rows, target, query).status_code, 400
                )

    def test_reorder_changes_only_order_and_rejects_foreign_ids(self):
        first = M3UGroupRule.objects.create(
            m3u_account=self.account, scope="live", regex_pattern="News"
        )
        second = M3UGroupRule.objects.create(
            m3u_account=self.account, scope="live", regex_pattern="Sport", order=1
        )
        response = self.client.post(
            self.url + "reorder/",
            {
                "ids": [second.id, first.id],
                "positions": [0, 2],
                "scope": "live",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual((first.order, second.order), (2, 0))
        self.assertEqual(first.regex_pattern, "News")
        bad = self.client.post(
            self.url + "reorder/", {"ids": [first.id], "scope": "live"}, format="json"
        )
        self.assertEqual(bad.status_code, 400)

    def test_custom_actions_require_admin(self):
        user = get_user_model().objects.create_user(username="rule-user", user_level=5)
        self.client.force_authenticate(user)
        for suffix in ("preview-draft/", "save-apply/", "reorder/"):
            self.assertEqual(
                self.client.post(self.url + suffix, {}, format="json").status_code, 403
            )
        filters = f"/api/m3u/accounts/{self.account.id}/filters/"
        for suffix in ("preview-draft/", "reorder/"):
            self.assertEqual(
                self.client.post(filters + suffix, {}, format="json").status_code, 403
            )
        self.assertEqual(
            self.client.get(
                self.url + "content-preview/?scope=live&group_id=1"
            ).status_code,
            403,
        )

    def test_filter_preview_keeps_excluded_streams_without_exposing_urls(self):
        write_live_filter_catalog(
            self.account.id,
            [
                {
                    "name": f"### {i}",
                    "url": "http://private.invalid/password",
                    "attributes": {"group-title": "Events"},
                }
                for i in range(215)
            ],
        )
        filters = [
            {
                "preview_id": "new",
                "filter_type": "name",
                "regex_pattern": "###",
                "exclude": True,
                "order": 0,
                "custom_properties": {"case_sensitive": False},
            }
        ]
        response = self.client.post(
            f"/api/m3u/accounts/{self.account.id}/filters/preview-draft/?page=5&page_size=50",
            {"rules": filters, "target_id": "new"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            (response.data["count"], response.data["inventory_count"]), (215, 215)
        )
        self.assertEqual(len(response.data["results"]), 15)
        self.assertTrue(response.data["catalog_complete"])
        self.assertNotIn("password", str(response.data))
        self.assertFalse(M3UFilter.objects.exists())

    def test_account_deletion_cleans_catalog(self):
        account_id = self.account.id
        for scope in ("live", "movie", "series"):
            write_live_filter_catalog(account_id, [], scope=scope)
        self.account.delete()
        for scope in ("live", "movie", "series"):
            self.assertFalse(has_live_filter_catalog(account_id, scope))

    def test_category_preview_includes_disabled_categories_without_reading_item_catalog(self):
        category = VODCategory.objects.create(name="Season", category_type="movie")
        relation = M3UVODCategoryRelation.objects.create(
            category=category, m3u_account=self.account, enabled=False
        )
        write_live_filter_catalog(
            self.account.id,
            [
                {"name": "Anime title", "attributes": {"group-title": "Season"}},
            ],
            scope="movie",
        )
        with patch("apps.m3u.rule_previews.iter_live_filter_catalog") as inventory:
            response = self.post_preview(
                [draft(scope="movie", regex_pattern="^Season$")],
            )
        inventory.assert_not_called()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["item_count"], 0)
        self.assertTrue(response.data["catalog_complete"])
        relation.refresh_from_db()
        self.assertFalse(relation.enabled)

    def test_filter_preview_uses_snapshot_timestamp_not_newer_failed_refresh(self):
        write_live_filter_catalog(self.account.id, [])
        response = self.client.post(
            f"/api/m3u/accounts/{self.account.id}/filters/preview-draft/",
            {
                "rules": [
                    {
                        "preview_id": "new",
                        "filter_type": "name",
                        "regex_pattern": ".*",
                        "exclude": True,
                    }
                ],
                "target_id": "new",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(response.data["last_completed_refresh"])

    def test_group_content_is_exactly_scoped_to_account_and_category(self):
        category = VODCategory.objects.create(name="Movies", category_type="movie")
        M3UVODCategoryRelation.objects.create(
            category=category, m3u_account=self.account
        )
        M3UVODCategoryRelation.objects.create(category=category, m3u_account=self.other)
        for account, title in ((self.account, "Wanted"), (self.other, "Private")):
            movie = Movie.objects.create(name=title)
            M3UMovieRelation.objects.create(
                movie=movie,
                m3u_account=account,
                category=category,
                stream_id=title,
                declared_metadata={
                    "audio_languages": ["ger" if account == self.account else "fre"]
                },
            )
        response = self.client.get(
            self.url + f"content-preview/?scope=movie&group_id={category.id}"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual([row["name"] for row in response.data["results"]], ["Wanted"])
        self.assertEqual(
            response.data["results"][0]["source_metadata"]["values"]["audio_languages"],
            ["ger"],
        )

    def test_new_live_group_rules_preserve_existing_manual_selection(self):
        relation = self.group("News", enabled=False)
        M3UGroupRule.objects.create(
            m3u_account=self.account,
            scope="live",
            regex_pattern="News|Sport",
            action="enable",
        )
        M3UGroupRule.objects.create(
            m3u_account=self.account,
            scope="live",
            regex_pattern="Ignored",
            action="ignore",
            order=1,
        )
        with patch("apps.m3u.tasks.send_m3u_update"):
            process_groups(self.account, {"News": {}, "Sport": {}, "Ignored": {}})
        relation.refresh_from_db()
        self.assertFalse(relation.enabled)
        self.assertTrue(
            ChannelGroupM3UAccount.objects.get(
                m3u_account=self.account, channel_group__name="Sport"
            ).enabled
        )
        self.assertFalse(ChannelGroupM3UAccount.objects.get(
            m3u_account=self.account, channel_group__name="Ignored"
        ).enabled)

    def test_unmatched_new_live_groups_are_disabled_without_changing_known_selections(
        self,
    ):
        self.account.custom_properties = {"auto_enable_new_groups_live": True}
        self.account.save()
        known = self.group("Known", enabled=True)
        with patch("apps.m3u.tasks.send_m3u_update"):
            process_groups(self.account, {"Known": {}, "New": {}})
        known.refresh_from_db()
        self.assertTrue(known.enabled)
        self.assertFalse(
            ChannelGroupM3UAccount.objects.get(
                m3u_account=self.account, channel_group__name="New"
            ).enabled
        )

    def test_group_settings_reject_invalid_cleanup_mode_before_writing(self):
        relation = self.group("Keep", enabled=True)
        response = self.client.patch(
            f"/api/m3u/accounts/{self.account.id}/group-settings/",
            {
                "group_settings": [
                    {
                        "channel_group": relation.channel_group_id,
                        "enabled": False,
                        "custom_properties": {"orphan_channel_cleanup": "invalid"},
                    }
                ]
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        relation.refresh_from_db()
        self.assertTrue(relation.enabled)
