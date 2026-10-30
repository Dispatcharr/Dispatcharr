"""Ignored categories remain recoverable, account-scoped and excluded from import."""

import tempfile
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.channels.models import ChannelGroup, ChannelGroupM3UAccount
from apps.m3u.models import M3UAccount, M3UGroupRule
from apps.m3u.tasks import process_groups, cleanup_stale_group_relationships
from apps.vod.models import VODCategory, M3UVODCategoryRelation
from apps.vod.tasks import batch_create_categories


class ReversibleIgnoreTests(TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        override = self.settings(M3U_FILTER_CATALOG_ROOT=directory.name)
        override.enable()
        self.addCleanup(override.disable)
        self.account = M3UAccount.objects.create(name="ignore-test", account_type="XC")
        self.other = M3UAccount.objects.create(name="ignore-other", account_type="XC")
        self.client = APIClient()
        self.client.force_authenticate(get_user_model().objects.create_user(
            username="ignore-admin", user_level=10,
        ))
        self.url = f"/api/m3u/accounts/{self.account.pk}/"

    def relation(self, scope, account=None):
        account = account or self.account
        if scope == "live":
            category, _ = ChannelGroup.objects.get_or_create(name="EN Test")
            return ChannelGroupM3UAccount.objects.create(
                channel_group=category, m3u_account=account, enabled=True,
                custom_properties={"provider": "preserve"},
            )
        category, _ = VODCategory.objects.get_or_create(name="EN Test", category_type=scope)
        return M3UVODCategoryRelation.objects.create(
            category=category, m3u_account=account, enabled=True,
            metadata_defaults={"subtitle_languages": ["ger"]},
            custom_properties={"provider": "preserve"},
        )

    def test_preview_apply_and_manual_restore_for_each_scope_preserve_rows(self):
        for scope in ("live", "movie", "series"):
            with self.subTest(scope=scope):
                row = self.relation(scope)
                foreign = self.relation(scope, self.other)
                rule = M3UGroupRule.objects.create(
                    m3u_account=self.account, scope=scope, regex_pattern="^EN",
                    action="ignore", metadata_defaults=(
                        {"audio_languages": ["eng"]} if scope != "live" else {}
                    ),
                )
                values = {
                    "preview_id": str(rule.pk), "scope": scope,
                    "regex_pattern": "^EN", "action": "ignore", "enabled": True,
                    "metadata_defaults": rule.metadata_defaults,
                }
                response = self.client.post(self.url + "group-rules/preview-draft/", {
                    "rules": [values], "target_id": str(rule.pk),
                }, format="json")
                self.assertEqual(response.status_code, 200, response.data)
                self.assertTrue(response.data["results"][0]["would_ignore"])
                row.refresh_from_db()
                self.assertFalse(row.ignored)
                response = self.client.post(self.url + f"group-rules/{rule.pk}/apply/")
                self.assertEqual(response.status_code, 200, response.data)
                self.assertTrue(response.data["category_updates"][0]["ignored"])
                row.refresh_from_db()
                foreign.refresh_from_db()
                self.assertTrue(row.ignored)
                self.assertFalse(row.enabled)
                self.assertTrue(foreign.enabled)
                self.assertFalse(foreign.ignored)
                self.assertEqual(row.custom_properties, {"provider": "preserve"})
                key = "channel_group" if scope == "live" else "id"
                category_id = row.channel_group_id if scope == "live" else row.category_id
                payload_key = "group_settings" if scope == "live" else "category_settings"
                # Metadata-only/old-client saves must not accidentally un-ignore.
                response = self.client.patch(self.url + "group-settings/", {
                    payload_key: [{key: category_id, "custom_properties": {"note": "kept"}}],
                }, format="json")
                self.assertEqual(response.status_code, 200, response.data)
                row.refresh_from_db()
                self.assertTrue(row.ignored)
                response = self.client.patch(self.url + "group-settings/", {
                    payload_key: [{key: category_id, "enabled": True, "ignored": False}],
                }, format="json")
                self.assertEqual(response.status_code, 200, response.data)
                row.refresh_from_db()
                self.assertTrue(row.enabled)
                self.assertFalse(row.ignored)
                if scope != "live":
                    self.assertEqual(row.metadata_defaults, {
                        "subtitle_languages": ["ger"], "audio_languages": ["eng"],
                    })

    def test_discovery_stores_ignored_categories_and_preserves_manual_restore(self):
        for scope in ("live", "movie", "series"):
            M3UGroupRule.objects.create(
                m3u_account=self.account, scope=scope, regex_pattern="EN", action="ignore",
            )
            if scope == "live":
                with patch("apps.m3u.tasks.send_m3u_update"):
                    process_groups(self.account, {"EN Test": {}})
                row = ChannelGroupM3UAccount.objects.get(m3u_account=self.account)
            else:
                mapping = batch_create_categories(
                    [{"category_name": "EN Test"}], scope, self.account
                )
                self.assertIn("EN Test", mapping)
                self.assertIn("EN Test", mapping.ignored)
                row = M3UVODCategoryRelation.objects.get(
                    m3u_account=self.account, category__category_type=scope
                )
            self.assertTrue(row.ignored)
            self.assertFalse(row.enabled)
            row.ignored, row.enabled = False, True
            row.save()
            if scope == "live":
                process_groups(self.account, {"EN Test": {}})
            else:
                mapping = batch_create_categories(
                    [{"category_name": "EN Test"}], scope, self.account
                )
                self.assertNotIn("EN Test", mapping.ignored)
            row.refresh_from_db()
            self.assertTrue(row.enabled)
            self.assertFalse(row.ignored)

    def test_ignored_categories_are_retained_if_provider_temporarily_omits_them(self):
        row = self.relation("live")
        row.ignored = True
        row.last_seen = timezone.now() - timezone.timedelta(days=30)
        row.save()
        cleanup_stale_group_relationships(self.account, timezone.now())
        self.assertTrue(ChannelGroupM3UAccount.objects.filter(pk=row.pk).exists())
        for scope in ("movie", "series"):
            row = self.relation(scope)
            row.ignored = True
            row.save()
            batch_create_categories([], scope, self.account)
            self.assertTrue(M3UVODCategoryRelation.objects.filter(pk=row.pk).exists())

    def test_database_rejects_enabled_and_ignored_at_the_same_time(self):
        for scope in ("live", "movie", "series"):
            row = self.relation(scope)
            with self.assertRaises(IntegrityError), transaction.atomic():
                type(row).objects.filter(pk=row.pk).update(enabled=True, ignored=True)
