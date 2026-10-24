"""Setup stream filters use complete draft selections, never an early import."""

import tempfile
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.channels.models import Channel, ChannelGroup, ChannelGroupM3UAccount, Stream
from apps.m3u.category_preview import _store_rows
from apps.m3u.filter_catalog import live_filter_selection, write_live_filter_catalog
from apps.m3u.models import M3UAccount


@override_settings(
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
)
class SetupFilterPreviewTests(TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        setting = self.settings(M3U_FILTER_CATALOG_ROOT=directory.name)
        setting.enable()
        self.addCleanup(setting.disable)
        cache.clear()
        self.addCleanup(cache.clear)
        self.account = M3UAccount.objects.create(
            name="Setup",
            account_type="XC",
            setup_step="categories",
            server_url="https://provider.invalid/",
            username="synthetic-user",
            password="synthetic-password",
        )
        self.groups = [
            ChannelGroup.objects.create(name=name) for name in ("Sports", "News")
        ]
        self.relations = [
            ChannelGroupM3UAccount.objects.create(
                m3u_account=self.account,
                channel_group=group,
                enabled=False,
                custom_properties={"xc_id": str(index)},
            )
            for index, group in enumerate(self.groups, 11)
        ]
        self.ids = [row.id for row in self.groups]
        self.client = APIClient()
        self.client.force_authenticate(
            get_user_model().objects.create_user(username="setup-admin", user_level=10)
        )
        root = f"/api/m3u/accounts/{self.account.id}/filters/"
        self.availability_url = root + "availability/"
        self.preview_url = root + "preview-draft/"

    def store(self, index=0, rows=None):
        provider_id = str(11 + index)
        _store_rows(
            self.account, "live", provider_id,
            rows if rows is not None else [{
                "category_id": provider_id,
                "stream_id": 7 + index,
                "name": self.groups[index].name + " HD",
            }],
        )

    def availability(self, ids=None):
        return self.client.post(
            self.availability_url,
            {"group_ids": self.ids if ids is None else ids},
            format="json",
        )

    def preview(self, ids=None, field="name", pattern=".*"):
        return self.client.post(
            self.preview_url,
            {
                "group_ids": self.ids if ids is None else ids,
                "target_id": "draft",
                "rules": [{
                    "preview_id": "draft",
                    "filter_type": field,
                    "regex_pattern": pattern,
                    "exclude": True,
                    "enabled": True,
                    "order": 0,
                    "custom_properties": {"case_sensitive": False},
                }],
            },
            format="json",
        )

    def assert_no_import_or_selection_save(self):
        self.assertFalse(Stream.objects.exists())
        self.assertFalse(Channel.objects.exists())
        self.assertFalse(self.account.channel_group.filter(enabled=True).exists())
        self.account.refresh_from_db()
        self.assertEqual(self.account.setup_step, "categories")

    def test_complete_cached_draft_is_available_without_saving_selection(self):
        for index in range(2):
            self.store(index)
        with patch("apps.m3u.category_preview.Client") as provider:
            response = self.availability()
            preview = self.preview()
        provider.assert_not_called()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["ready"])
        self.assertEqual(response.data["missing_group_ids"], [])
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(preview.data["inventory_count"], 2)
        self.assertTrue(preview.data["catalog_complete"])
        self.assertIsNone(preview.data["last_completed_refresh"])
        self.assert_no_import_or_selection_save()

    def test_only_missing_categories_are_reported_and_no_provider_is_contacted(self):
        self.store(0)
        with patch("apps.m3u.category_preview.Client") as provider:
            response = self.availability()
        provider.assert_not_called()
        self.assertFalse(response.data["ready"])
        self.assertTrue(response.data["can_load_provider"])
        self.assertEqual(response.data["missing_group_ids"], [self.ids[1]])
        self.assert_no_import_or_selection_save()

    def test_missing_category_never_falls_back_to_partial_or_old_refresh_data(self):
        self.store(0)
        write_live_filter_catalog(
            self.account.id, [], selection=live_filter_selection(self.account)
        )
        response = self.preview()
        self.assertEqual(response.status_code, 400)
        self.assertNotIn("results", response.data)
        self.assert_no_import_or_selection_save()

    def test_known_empty_categories_are_complete_and_duplicates_do_not_duplicate_streams(self):
        self.store(0)
        self.store(1, [])
        self.assertTrue(self.availability().data["ready"])
        self.assertEqual(self.preview(self.ids + self.ids).data["count"], 1)
        self.assertEqual(self.preview([self.ids[1]]).data["inventory_count"], 0)

    def test_category_and_url_filters_use_import_equivalent_values_without_exposing_credentials(self):
        self.store(0)
        response = self.preview(
            [self.ids[0]], "url", r"/live/synthetic-user/synthetic-password/7\.ts$"
        )
        self.assertEqual(response.data["count"], 1)
        self.assertNotIn("synthetic-password", response.content.decode())
        self.assertEqual(
            self.preview([self.ids[0]], "group", "^Sports$").data["count"], 1
        )
        self.assert_no_import_or_selection_save()

    def test_expired_or_changed_connection_cache_is_not_reused(self):
        self.store(0)
        self.account.password = "different-synthetic-password"
        self.account.save(update_fields=["password"])
        self.assertFalse(self.availability([self.ids[0]]).data["ready"])
        self.assertEqual(self.preview([self.ids[0]]).status_code, 400)

    def test_draft_category_ids_are_validated_and_account_scoped(self):
        foreign = ChannelGroup.objects.create(name="Foreign")
        for ids in ([], [-1], [foreign.id], [self.ids[0], foreign.id]):
            with self.subTest(ids=ids):
                self.assertEqual(self.availability(ids).status_code, 400)
                self.assertEqual(self.preview(ids).status_code, 400)

    def test_selection_availability_and_preview_are_admin_only(self):
        self.client.force_authenticate(
            get_user_model().objects.create_user(username="setup-viewer", user_level=0)
        )
        self.assertEqual(self.availability().status_code, 403)
        self.assertEqual(self.preview().status_code, 403)

    def test_standard_url_and_file_reuse_discovery_without_fetching_or_importing(self):
        for file_path in ("", "/tmp/synthetic-playlist.m3u"):
            with self.subTest(file_path=file_path):
                self.account.account_type = "STD"
                self.account.file_path = file_path
                self.account.save(update_fields=["account_type", "file_path"])
                write_live_filter_catalog(
                    self.account.id,
                    [
                        {"name": "Sports HD", "url": "https://stream.invalid/play/7",
                         "attributes": {"group-title": "Sports"}},
                        {"name": "News HD", "url": "https://stream.invalid/play/8",
                         "attributes": {"group-title": "News"}},
                    ],
                    scope="live-groups",
                    selection=live_filter_selection(self.account),
                )
                with patch("apps.m3u.category_preview.Client") as provider:
                    response = self.availability([self.ids[0]])
                    preview = self.preview([self.ids[0]], "url", "/play/7$")
                provider.assert_not_called()
                self.assertTrue(response.data["ready"])
                self.assertEqual(preview.data["count"], 1)
                self.assertEqual(preview.data["inventory_count"], 1)
                self.assert_no_import_or_selection_save()

    def test_standard_missing_or_unverified_snapshot_does_not_trigger_fetch(self):
        self.account.account_type = "STD"
        self.account.save(update_fields=["account_type"])
        for unverified in (False, True):
            if unverified:
                write_live_filter_catalog(self.account.id, [], scope="live-groups")
            response = self.availability()
            self.assertFalse(response.data["ready"])
            self.assertFalse(response.data["can_load_provider"])
            self.assertEqual(self.preview().status_code, 400)
        self.assert_no_import_or_selection_save()
