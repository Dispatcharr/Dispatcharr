"""Tests for M3U stream filter compilation and batch application."""
import tempfile
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.accounts.models import User
from apps.channels.models import ChannelGroup, Stream
from apps.m3u.api_views import M3UFilterViewSet
from apps.m3u.models import M3UAccount, M3UFilter
from apps.m3u.tasks import (
    _compile_m3u_stream_filters,
    _stream_passes_m3u_filters,
    process_m3u_batch_direct,
    write_live_filter_catalog,
)


class M3UStreamFilterAPITests(TestCase):
    def setUp(self):
        self.media_root = tempfile.TemporaryDirectory()
        self.settings_override = override_settings(MEDIA_ROOT=self.media_root.name)
        self.settings_override.enable()
        self.factory = APIRequestFactory()
        self.admin = User.objects.create_user(
            username="stream-filter-admin",
            password="test-password",
            user_level=10,
        )
        self.account = M3UAccount.objects.create(
            name="stream-filter-account",
            server_url="https://provider.example",
        )

    def tearDown(self):
        self.settings_override.disable()
        self.media_root.cleanup()
        super().tearDown()

    def test_identical_stream_filters_are_rejected(self):
        payload = {
            "filter_type": "name",
            "regex_pattern": "NEWS.*",
            "exclude": True,
            "order": 0,
            "custom_properties": {"case_sensitive": False},
        }
        create = M3UFilterViewSet.as_view({"post": "create"})
        first_request = self.factory.post("/filters/", payload, format="json")
        force_authenticate(first_request, user=self.admin)
        first_response = create(first_request, account_id=self.account.id)
        second_request = self.factory.post("/filters/", payload, format="json")
        force_authenticate(second_request, user=self.admin)
        second_response = create(second_request, account_id=self.account.id)

        self.assertEqual(first_response.status_code, 201, first_response.data)
        self.assertEqual(second_response.status_code, 400)
        self.assertEqual(
            M3UFilter.objects.filter(m3u_account=self.account).count(),
            1,
        )

    def test_draft_preview_respects_first_match_order(self):
        group = ChannelGroup.objects.create(name="Preview News")
        Stream.objects.create(
            name="Block News",
            url="https://provider.example/block",
            stream_hash="preview-block",
            m3u_account=self.account,
            channel_group=group,
        )
        matching = Stream.objects.create(
            name="Daily News",
            url="https://provider.example/daily",
            stream_hash="preview-daily",
            m3u_account=self.account,
            channel_group=group,
        )
        Stream.objects.create(
            name="Sports",
            url="https://provider.example/sports",
            stream_hash="preview-sports",
            m3u_account=self.account,
            channel_group=group,
        )
        M3UFilter.objects.create(
            m3u_account=self.account,
            filter_type="name",
            regex_pattern="^Block",
            exclude=True,
            order=0,
            custom_properties={"case_sensitive": False},
        )
        request = self.factory.post(
            "/filters/preview-draft/",
            {
                "filter_type": "name",
                "regex_pattern": "News",
                "exclude": False,
                "order": 1,
                "custom_properties": {"case_sensitive": False},
            },
            format="json",
        )
        force_authenticate(request, user=self.admin)

        response = M3UFilterViewSet.as_view({"post": "preview_draft"})(
            request,
            account_id=self.account.id,
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["id"], matching.id)
        self.assertTrue(response.data["first_match_wins"])

    def test_preview_uses_pre_filter_catalog_for_excluded_streams(self):
        write_live_filter_catalog(
            self.account.id,
            [
                {
                    "name": "### Hidden channel",
                    "url": "https://provider.example/hidden",
                    "attributes": {"group-title": "Enabled Group"},
                },
                {
                    "name": "Visible channel",
                    "url": "https://provider.example/visible",
                    "attributes": {"group-title": "Enabled Group"},
                },
            ],
        )
        request = self.factory.post(
            "/filters/preview-draft/",
            {
                "filter_type": "name",
                "regex_pattern": "###",
                "exclude": True,
                "order": 0,
                "custom_properties": {"case_sensitive": True},
            },
            format="json",
        )
        force_authenticate(request, user=self.admin)

        response = M3UFilterViewSet.as_view({"post": "preview_draft"})(
            request,
            account_id=self.account.id,
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["inventory_count"], 2)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["name"], "### Hidden channel")
        self.assertTrue(response.data["catalog_complete"])


class CompileM3UStreamFiltersTests(SimpleTestCase):
    def test_compiles_case_insensitive_when_configured(self):
        filter_obj = MagicMock()
        filter_obj.regex_pattern = "news"
        filter_obj.custom_properties = {"case_sensitive": False}

        compiled = _compile_m3u_stream_filters([filter_obj])

        self.assertEqual(len(compiled), 1)
        pattern, _ = compiled[0]
        self.assertTrue(pattern.search("NEWS"))

    def test_compiles_case_sensitive_by_default(self):
        filter_obj = MagicMock()
        filter_obj.regex_pattern = "news"
        filter_obj.custom_properties = {}

        compiled = _compile_m3u_stream_filters([filter_obj])

        pattern, _ = compiled[0]
        self.assertIsNone(pattern.search("NEWS"))
        self.assertTrue(pattern.search("news"))


class StreamPassesM3UFiltersTests(SimpleTestCase):
    def _compiled(self, *, filter_type="name", exclude=False, pattern="Adult"):
        filter_obj = MagicMock()
        filter_obj.filter_type = filter_type
        filter_obj.exclude = exclude
        filter_obj.regex_pattern = pattern
        filter_obj.custom_properties = {}
        return _compile_m3u_stream_filters([filter_obj])

    def test_include_filter_passes_matching_stream(self):
        compiled = self._compiled(exclude=False)
        self.assertTrue(
            _stream_passes_m3u_filters("Adult Channel", "http://x", "News", compiled)
        )

    def test_include_filter_passes_non_matching_stream(self):
        """Non-matching streams still pass unless a matching exclude filter hits."""
        compiled = self._compiled(exclude=False, pattern="news")
        self.assertTrue(
            _stream_passes_m3u_filters("Sports", "http://x", "Sports", compiled)
        )

    def test_exclude_filter_rejects_matching_stream(self):
        compiled = self._compiled(exclude=True, pattern="Adult")
        self.assertFalse(
            _stream_passes_m3u_filters("Adult Channel", "http://x", "News", compiled)
        )

    def test_url_filter_type_targets_url(self):
        compiled = self._compiled(filter_type="url", exclude=True, pattern="blocked")
        self.assertFalse(
            _stream_passes_m3u_filters("OK", "http://blocked.example/live", "News", compiled)
        )
        self.assertTrue(
            _stream_passes_m3u_filters("blocked name", "http://ok.example/live", "News", compiled)
        )

    def test_group_filter_type_targets_group(self):
        compiled = self._compiled(filter_type="group", exclude=True, pattern="Hidden")
        self.assertFalse(
            _stream_passes_m3u_filters("Channel", "http://x", "Hidden Group", compiled)
        )


class ProcessM3UBatchFilterTests(TestCase):
    def _mock_stream_meta(self, mock_stream_cls, max_length=255):
        mock_field = MagicMock()
        mock_field.max_length = max_length
        mock_stream_cls._meta.get_field.return_value = mock_field

    @patch("apps.m3u.tasks._bulk_update_stream_refresh_batches")
    @patch("apps.m3u.tasks.Stream")
    @patch("apps.m3u.tasks.M3UAccount")
    def test_exclude_filter_skips_stream_import(
        self, mock_account_cls, mock_stream_cls, mock_bulk_update,
    ):
        self._mock_stream_meta(mock_stream_cls)
        mock_account = MagicMock()
        mock_account.account_type = "STD"
        mock_account_cls.objects.get.return_value = mock_account
        mock_stream_cls.objects.filter.return_value.select_related.return_value.only.return_value = (
            []
        )
        mock_stream_cls.generate_hash_key = MagicMock(return_value="hash123")

        filter_obj = MagicMock()
        filter_obj.regex_pattern = "skip-me"
        filter_obj.filter_type = "name"
        filter_obj.exclude = True
        filter_obj.custom_properties = {}
        compiled = _compile_m3u_stream_filters([filter_obj])

        batch = [{
            "name": "skip-me channel",
            "url": "http://example/live",
            "attributes": {"group-title": "News"},
            "vlc_opts": {},
        }]

        with patch("django.db.connections"):
            result = process_m3u_batch_direct(
                1, batch, {"News": 1}, ["name", "url"], compiled_filters=compiled,
            )

        self.assertIn("0 created", result)
        mock_stream_cls.objects.bulk_create.assert_not_called()
        mock_bulk_update.assert_called_once_with([], [], batch_size=200)

    @patch("apps.m3u.tasks._bulk_update_stream_refresh_batches")
    @patch("apps.m3u.tasks.Stream")
    @patch("apps.m3u.tasks.M3UAccount")
    def test_no_filters_imports_matching_stream(
        self, mock_account_cls, mock_stream_cls, mock_bulk_update,
    ):
        self._mock_stream_meta(mock_stream_cls)
        mock_account = MagicMock()
        mock_account.account_type = "STD"
        mock_account_cls.objects.get.return_value = mock_account
        mock_stream_cls.objects.filter.return_value.select_related.return_value.only.return_value = (
            []
        )
        mock_stream_cls.generate_hash_key = MagicMock(return_value="hash123")
        mock_stream_cls.objects.bulk_create.return_value = []

        batch = [{
            "name": "News One",
            "url": "http://example/live",
            "attributes": {"group-title": "News"},
            "vlc_opts": {},
        }]

        with patch("django.db.connections"), patch(
            "apps.m3u.tasks.transaction.atomic",
        ):
            result = process_m3u_batch_direct(
                1, batch, {"News": 1}, ["name", "url"], compiled_filters=[],
            )

        self.assertIn("1 created", result)
        mock_stream_cls.objects.bulk_create.assert_called_once()
