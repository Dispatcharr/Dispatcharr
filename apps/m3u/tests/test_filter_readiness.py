"""A current pre-filter catalog, not imported Stream count, gates filter setup."""

import tempfile
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.channels.models import ChannelGroup, ChannelGroupM3UAccount, Stream
from apps.m3u.category_preview import _store_rows
from apps.m3u.filter_catalog import (
    iter_live_filter_catalog,
    live_filter_selection,
    publish_live_filter_catalog,
    write_live_filter_catalog,
)
from apps.m3u.models import M3UAccount, M3UGroupRule


@override_settings(
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
)
class StreamFilterReadinessTests(TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.override = self.settings(M3U_FILTER_CATALOG_ROOT=self.directory.name)
        self.override.enable()
        self.addCleanup(self.override.disable)
        cache.clear()
        self.addCleanup(cache.clear)
        self.account = M3UAccount.objects.create(
            name="Readiness",
            account_type="XC",
            server_url="https://provider.invalid",
            username="synthetic-user",
            password="synthetic-password",
        )
        self.group = ChannelGroup.objects.create(name="Sports")
        self.relation = ChannelGroupM3UAccount.objects.create(
            m3u_account=self.account,
            channel_group=self.group,
            enabled=True,
            custom_properties={"xc_id": "11"},
        )
        self.client = APIClient()
        self.client.force_authenticate(
            get_user_model().objects.create_user(username="ready-admin", user_level=10)
        )
        self.url = f"/api/m3u/accounts/{self.account.id}/filters/availability/"

    def catalog(self, streams=(), publish=True):
        return write_live_filter_catalog(
            self.account.id,
            streams,
            publish=publish,
            selection=live_filter_selection(self.account),
        )

    def test_complete_empty_catalog_is_ready_without_imported_streams(self):
        self.catalog()
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["ready"])
        self.assertEqual(response.data["selected_count"], 1)
        self.assertEqual(list(iter_live_filter_catalog(self.account.id)), [])
        self.assertFalse(Stream.objects.exists())

    def test_new_selection_or_connection_requires_refresh(self):
        self.catalog()
        self.relation.enabled = False
        self.relation.save(update_fields=["enabled"])
        self.assertFalse(self.client.get(self.url).data["ready"])

        self.relation.enabled = True
        self.relation.save(update_fields=["enabled"])
        self.assertTrue(self.client.get(self.url).data["ready"])
        self.account.password = "different-synthetic-password"
        self.account.save(update_fields=["password"])
        self.assertFalse(self.client.get(self.url).data["ready"])

    def test_legacy_string_properties_keep_the_provider_category_id(self):
        self.relation.custom_properties = '{"xc_id": "11"}'
        self.relation.save(update_fields=["custom_properties"])
        self.assertEqual(
            live_filter_selection(self.account)["categories"],
            [(self.group.id, "Sports", "11")],
        )

    def test_failed_or_running_refresh_does_not_open_previous_snapshot(self):
        self.catalog()
        for state in (
            M3UAccount.Status.ERROR,
            M3UAccount.Status.FETCHING,
            M3UAccount.Status.PARSING,
        ):
            self.account.status = state
            self.account.save(update_fields=["status"])
            self.assertFalse(self.client.get(self.url).data["ready"])

    def test_legacy_and_staged_catalogs_are_not_treated_as_current(self):
        write_live_filter_catalog(self.account.id, [])
        self.assertFalse(self.client.get(self.url).data["ready"])
        staged = self.catalog(publish=False)
        self.assertFalse(self.client.get(self.url).data["ready"])
        publish_live_filter_catalog(self.account.id, staged)
        self.assertTrue(self.client.get(self.url).data["ready"])

    def test_readiness_is_admin_only_and_account_scoped(self):
        self.catalog()
        other = M3UAccount.objects.create(name="Other")
        self.assertFalse(
            self.client.get(self.url.replace(str(self.account.id), str(other.id))).data[
                "ready"
            ]
        )
        self.client.force_authenticate(
            get_user_model().objects.create_user(username="ready-viewer", user_level=0)
        )
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_category_rules_do_not_need_preview_contents(self):
        rules = [
            {
                "preview_id": "1",
                "scope": "live",
                "match_field": "group_name",
                "match_mode": "any",
                "regex_pattern": ".*",
                "action": "disable",
                "enabled": True,
                "case_sensitive": False,
                "order": 0,
            },
            {
                "preview_id": "new-fallback",
                "scope": "live",
                "match_field": "group_name",
                "match_mode": "any",
                "regex_pattern": "Sports",
                "action": "enable",
                "enabled": True,
                "case_sensitive": False,
                "order": 1,
            },
        ]
        url = f"/api/m3u/accounts/{self.account.id}/group-rules/preview-draft/"
        before = self.client.post(
            url, {"rules": rules, "target_id": "1"}, format="json"
        )
        self.assertNotIn("unchecked_category_count", before.data)
        self.assertEqual(before.data["count"], 1)
        _store_rows(
            self.account, "live", "11", [{"category_id": "11", "name": "Sports HD"}]
        )
        after = self.client.post(
            url, {"rules": rules, "target_id": "1"}, format="json"
        )
        self.assertNotIn("unchecked_category_count", after.data)
        self.assertEqual(
            after.data["rule_coverage"],
            [
                {"rule_id": "1", "count": 1},
                {"rule_id": "new-fallback", "count": 0},
            ],
        )
        self.assertFalse(Stream.objects.exists())

    def test_regex_preview_uses_cached_names_without_importing_or_fetching(self):
        _store_rows(
            self.account, "live", "11", [{"category_id": "11", "name": "Sports HD"}]
        )
        with patch("apps.m3u.category_preview.Client") as client:
            response = self.client.get(
                "/api/channels/streams/regex-preview/",
                {
                    "channel_group": "Sports",
                    "m3u_account_id": self.account.id,
                    "find": " HD$",
                    "replace": "",
                },
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data["find_matches"], [{"before": "Sports HD", "after": "Sports"}]
        )
        self.assertEqual(response.data["content_source"], "provider")
        client.assert_not_called()
        self.assertFalse(Stream.objects.exists())

    def test_empty_cached_category_does_not_request_another_provider_load(self):
        _store_rows(self.account, "live", "11", [])
        response = self.client.get(
            "/api/channels/streams/regex-preview/",
            {
                "channel_group": "Sports",
                "m3u_account_id": self.account.id,
                "find": ".*",
            },
        )
        self.assertFalse(response.data["can_load_provider"])
        self.assertEqual(response.data["content_source"], "provider")

    def test_account_summary_counts_only_active_rules(self):
        M3UGroupRule.objects.create(
            m3u_account=self.account,
            scope="live",
            regex_pattern="Sports",
            action="enable",
            enabled=True,
        )
        M3UGroupRule.objects.create(
            m3u_account=self.account,
            scope="movie",
            regex_pattern="Movies",
            action="disable",
            enabled=False,
        )
        response = self.client.get(f"/api/m3u/accounts/{self.account.id}/")
        self.assertEqual(
            response.data["group_rule_counts"], {"live": 1, "movie": 0, "series": 0}
        )
