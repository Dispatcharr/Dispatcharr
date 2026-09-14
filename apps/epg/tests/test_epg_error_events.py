from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from apps.epg.models import EPGSource
from apps.epg.tasks import _set_epg_source_status


class SetEPGSourceStatusTests(SimpleTestCase):
    @patch("apps.epg.tasks.log_system_event")
    @patch("apps.epg.tasks.send_epg_update")
    @patch("apps.epg.tasks.EPGSource")
    @patch("apps.epg.tasks._release_task_db_connection")
    def test_set_status_notify_error_emits_epg_error_event(
        self, _mock_release, mock_model, mock_ws, mock_log_event
    ):
        qs = MagicMock()
        mock_model.objects.filter.return_value = qs

        _set_epg_source_status(
            source_id=20,
            status=EPGSource.STATUS_ERROR,
            last_message="HTTP error 500",
            source_name="My EPG Guide",
            notify_error=True,
            ws_action="downloading",
            ws_error="HTTP error 500",
        )

        qs.update.assert_called_once_with(
            status=EPGSource.STATUS_ERROR,
            last_message="HTTP error 500",
        )
        mock_ws.assert_called_once_with(
            20,
            "downloading",
            100,
            status="error",
            error="HTTP error 500",
        )
        mock_log_event.assert_called_once_with(
            event_type="epg_error",
            source_name="My EPG Guide",
            message="HTTP error 500",
        )

    @patch("apps.epg.tasks.log_system_event")
    @patch("apps.epg.tasks.send_epg_update")
    @patch("apps.epg.tasks.EPGSource")
    @patch("apps.epg.tasks._release_task_db_connection")
    def test_set_status_notify_error_falls_back_to_str_id(
        self, _mock_release, mock_model, mock_ws, mock_log_event
    ):
        qs = MagicMock()
        mock_model.objects.filter.return_value = qs

        _set_epg_source_status(
            source_id=20,
            status=EPGSource.STATUS_ERROR,
            last_message="Download timed out",
            notify_error=True,
        )

        mock_log_event.assert_called_once_with(
            event_type="epg_error",
            source_name="20",
            message="Download timed out",
        )

    @patch("apps.epg.tasks.log_system_event")
    @patch("apps.epg.tasks.send_epg_update")
    @patch("apps.epg.tasks.EPGSource")
    @patch("apps.epg.tasks._release_task_db_connection")
    def test_set_status_without_notify_error_does_not_emit_event(
        self, _mock_release, mock_model, mock_ws, mock_log_event
    ):
        qs = MagicMock()
        mock_model.objects.filter.return_value = qs

        _set_epg_source_status(
            source_id=20,
            status=EPGSource.STATUS_FETCHING,
            last_message="Downloading...",
            source_name="My EPG Guide",
            notify_error=False,
        )

        qs.update.assert_called_once_with(
            status=EPGSource.STATUS_FETCHING,
            last_message="Downloading...",
        )
        mock_ws.assert_not_called()
        mock_log_event.assert_not_called()


class FetchXmltvErrorEventsTests(SimpleTestCase):
    @patch("apps.epg.tasks._set_epg_source_status")
    def test_missing_url_calls_set_epg_source_status_with_error(self, mock_set_status):
        from apps.epg.tasks import fetch_xmltv

        source = MagicMock(id=1, url=None)
        source.name = "No URL Source"
        source.get_cache_file.return_value = "/tmp/nonexistent_epg_file.xml"
        source.extracted_file_path = None
        source.file_path = None

        with patch("os.path.exists", return_value=False):
            result = fetch_xmltv(source)

        self.assertFalse(result)
        mock_set_status.assert_called_once_with(
            1,
            EPGSource.STATUS_ERROR,
            "No URL provided and no valid local file exists",
            source_name="No URL Source",
            notify_error=True,
            ws_action="downloading",
            ws_error="No URL provided and no valid local file exists",
        )


class SchedulesDirectErrorEventsTests(SimpleTestCase):
    @patch("apps.epg.sd_tasks._set_epg_source_status")
    def test_missing_credentials_calls_set_epg_source_status_with_error(self, mock_set_status):
        from apps.epg.sd_tasks import fetch_schedules_direct

        source = MagicMock(id=99, username="", password="")
        source.name = "SD Source"

        fetch_schedules_direct(source)

        mock_set_status.assert_called_once_with(
            99,
            EPGSource.STATUS_ERROR,
            "Schedules Direct source requires both a username and password.",
            source_name="SD Source",
            notify_error=True,
            ws_action="refresh",
            ws_error="Schedules Direct source requires both a username and password.",
        )
