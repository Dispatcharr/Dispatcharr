from unittest.mock import patch

from django.test import SimpleTestCase, TestCase

from apps.epg.models import EPGSource, EPGData
from apps.epg.tasks import (
    _EPG_PARSE_DEFER_MAX,
    _EPG_REFRESH_DEFER_SECONDS,
    _defer_parse_programs_for_tvg_id,
    _refresh_epg_data_impl,
    parse_programs_for_tvg_id,
)


class DeferParseProgramsTests(SimpleTestCase):
    @patch("apps.epg.tasks.parse_programs_for_tvg_id.apply_async")
    def test_defer_schedules_retry_for_refresh(self, mock_apply_async):
        result = _defer_parse_programs_for_tvg_id(5, False, 0, "source refresh in progress")

        self.assertEqual(result, "Deferred")
        mock_apply_async.assert_called_once_with(
            args=[5],
            kwargs={"force": False, "_defer_retry": 1},
            countdown=_EPG_REFRESH_DEFER_SECONDS,
        )

    @patch("apps.epg.tasks.parse_programs_for_tvg_id.apply_async")
    def test_defer_gives_up_after_max_retries(self, mock_apply_async):
        result = _defer_parse_programs_for_tvg_id(
            5, False, _EPG_PARSE_DEFER_MAX, "source refresh in progress"
        )

        self.assertIn("Deferred too many times", result)
        mock_apply_async.assert_not_called()


class ParseProgramsForTvgIdLockTests(TestCase):
    def setUp(self):
        self.source = EPGSource.objects.create(
            name="Lock Test",
            source_type="xmltv",
            file_path="/tmp/unused.xml",
        )
        self.epg = EPGData.objects.create(
            tvg_id="test.channel",
            name="Test",
            epg_source=self.source,
        )

    @patch("apps.epg.tasks.parse_programs_for_tvg_id.apply_async")
    @patch("apps.epg.tasks.is_task_lock_held", return_value=True)
    def test_defers_while_source_refresh_running(self, mock_held, mock_apply_async):
        result = parse_programs_for_tvg_id(self.epg.id)

        self.assertEqual(result, "Deferred")
        mock_held.assert_called_once_with("refresh_epg_data", self.source.id)
        mock_apply_async.assert_called_once()

    @patch("apps.epg.tasks._decr_source_tvg_parse_count")
    @patch("apps.epg.tasks._incr_source_tvg_parse_count")
    @patch("apps.epg.tasks.acquire_task_lock", return_value=False)
    @patch("apps.epg.tasks.is_task_lock_held", return_value=False)
    def test_skips_when_duplicate_epg_parse_running(
        self, mock_held, mock_acquire, mock_incr, mock_decr
    ):
        result = parse_programs_for_tvg_id(self.epg.id)

        self.assertEqual(result, "Task already running")
        mock_acquire.assert_called_once_with("parse_epg_programs", self.epg.id)
        mock_incr.assert_called_once_with(self.source.id)
        mock_decr.assert_called_once_with(self.source.id)


class RefreshEpgDataDeferTests(TestCase):
    def setUp(self):
        self.source = EPGSource.objects.create(
            name="Refresh Defer Test",
            source_type="xmltv",
            file_path="/tmp/unused.xml",
        )

    @patch("apps.epg.tasks.refresh_epg_data.apply_async")
    @patch("apps.epg.tasks.fetch_xmltv")
    @patch("apps.epg.tasks._source_tvg_parse_count", return_value=1)
    def test_refresh_defers_while_per_channel_parses_running(
        self, mock_count, mock_fetch, mock_apply_async
    ):
        _refresh_epg_data_impl(self.source.id)

        mock_fetch.assert_not_called()
        mock_apply_async.assert_called_once_with(
            args=[self.source.id],
            kwargs={"force": False, "_file_defer_retry": 1},
            countdown=_EPG_REFRESH_DEFER_SECONDS,
        )
