"""Tests for M3U stream filter compilation and batch application."""
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, TestCase

from apps.m3u.tasks import (
    _compile_m3u_stream_filters,
    _stream_passes_m3u_filters,
    process_m3u_batch_direct,
)


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
