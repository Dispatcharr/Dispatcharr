"""Category-only matching applies to every content scope and write path."""

import tempfile

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.channels.models import ChannelGroup, ChannelGroupM3UAccount, Stream
from apps.m3u.models import M3UAccount, M3UGroupRule


class CategoryNameRuleTests(TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        settings = self.settings(M3U_FILTER_CATALOG_ROOT=directory.name)
        settings.enable()
        self.addCleanup(settings.disable)
        self.account = M3UAccount.objects.create(name="category-rule-account")
        self.client = APIClient()
        self.client.force_authenticate(
            get_user_model().objects.create_user(
                username="category-admin", user_level=10
            )
        )
        self.url = f"/api/m3u/accounts/{self.account.pk}/group-rules/"

    def values(self, **overrides):
        return {
            "scope": "live", "regex_pattern": "News", "action": "enable",
            "enabled": True, **overrides,
        }

    def draft_request(self, values, *, rule_id="new", endpoint="preview-draft/"):
        return self.client.post(
            self.url + endpoint,
            {
                "rules": [{"preview_id": str(rule_id), **values}],
                "target_id": str(rule_id),
            },
            format="json",
        )

    def test_new_rules_use_category_names_for_every_scope(self):
        for scope in M3UGroupRule.Scope.values:
            response = self.client.post(
                self.url, self.values(scope=scope), format="json"
            )
            self.assertEqual(response.status_code, 201, response.data)
            self.assertEqual(response.data["match_field"], "group_name")
            self.assertEqual(response.data["match_mode"], "any")

    def test_live_category_rule_matches_names_without_loading_contained_streams(self):
        news = ChannelGroup.objects.create(name="News")
        sport = ChannelGroup.objects.create(name="Sport")
        memberships = [
            ChannelGroupM3UAccount.objects.create(
                m3u_account=self.account, channel_group=group, enabled=False
            )
            for group in (news, sport)
        ]
        Stream.objects.create(
            name="World News", url="http://example.invalid/stream",
            m3u_account=self.account, channel_group=sport,
        )
        response = self.draft_request(self.values())
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["name"], "News")
        self.assertNotIn("unchecked_category_count", response.data)
        self.assertFalse(self.account.group_rules.exists())

        response = self.draft_request(self.values(), endpoint="save-apply/")
        self.assertEqual(response.status_code, 200, response.data)
        for membership, expected in zip(memberships, (True, False)):
            membership.refresh_from_db()
            self.assertEqual(membership.enabled, expected)

    def test_item_matching_and_all_mode_are_rejected_on_every_draft_write_path(self):
        for scope in M3UGroupRule.Scope.values:
            for predicate in (
                {"match_field": "item_name", "match_mode": "any"},
                {"match_field": "item_name", "match_mode": "all"},
                {"match_field": "group_name", "match_mode": "all"},
            ):
                values = self.values(scope=scope, **predicate)
                responses = [self.client.post(self.url, values, format="json")]
                responses.extend(
                    self.draft_request(values, endpoint=endpoint)
                    for endpoint in ("preview-draft/", "save-apply/")
                )
                for response in responses:
                    self.assertEqual(response.status_code, 400, response.data)
        self.assertFalse(self.account.group_rules.exists())

    def test_saved_rule_ids_do_not_exempt_unsupported_matching(self):
        for scope in M3UGroupRule.Scope.values:
            for mode in ("any", "all"):
                rule = M3UGroupRule.objects.create(
                    m3u_account=self.account,
                    **self.values(scope=scope, match_field="item_name", match_mode=mode),
                )
                url = self.url + f"{rule.pk}/"
                response = self.client.patch(
                    url, {"regex_pattern": "Sport"}, format="json"
                )
                self.assertEqual(response.status_code, 400, response.data)
                response = self.client.post(url + "apply/", {}, format="json")
                self.assertEqual(response.status_code, 400, response.data)
                for endpoint in ("preview-draft/", "save-apply/"):
                    response = self.draft_request(
                        self.values(scope=scope, match_field="item_name", match_mode=mode),
                        rule_id=rule.pk, endpoint=endpoint,
                    )
                    self.assertEqual(response.status_code, 400, response.data)
                    response = self.draft_request(
                        self.values(scope=scope), rule_id=rule.pk, endpoint=endpoint
                    )
                    self.assertEqual(response.status_code, 400, response.data)
                rule.refresh_from_db()
                self.assertEqual(rule.regex_pattern, "News")
                self.assertEqual(self.client.delete(url).status_code, 204)
