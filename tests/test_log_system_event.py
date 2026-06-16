"""Tests for log_system_event Connect/plugin dispatch and DB cleanup."""

from unittest.mock import patch

from django.test import SimpleTestCase


class LogSystemEventDispatchTests(SimpleTestCase):
    @patch("django.db.close_old_connections")
    @patch("core.utils._dispatch_system_event_integrations")
    @patch("core.models.SystemEvent.objects")
    @patch("core.models.CoreSettings.objects")
    def test_log_system_event_dispatches_integrations_and_closes_db(
        self, mock_core_settings, mock_system_event, mock_dispatch, mock_close
    ):
        mock_system_event.count.return_value = 1
        mock_core_settings.filter.return_value.first.return_value = None

        from core.utils import log_system_event

        log_system_event("channel_start", channel_id="abc", channel_name="Test")

        mock_dispatch.assert_called_once_with(
            "channel_start",
            channel_id="abc",
            channel_name="Test",
        )
        mock_close.assert_called_once()

    @patch("django.db.close_old_connections")
    @patch("apps.connect.utils.trigger_event")
    def test_integration_dispatch_closes_db_on_sync_path(
        self, mock_trigger, mock_close
    ):
        from core.utils import _dispatch_system_event_integrations

        with patch("core.utils._should_use_sync_websocket_send", return_value=True):
            _dispatch_system_event_integrations("client_connect", channel_id="abc")

        mock_trigger.assert_called_once()
        mock_close.assert_called_once()

    @patch("core.utils.dispatch_event_system")
    def test_integration_dispatch_spawns_on_gevent_uwsgi(
        self, mock_dispatch
    ):
        from core.utils import _dispatch_system_event_integrations

        with patch("core.utils._should_use_sync_websocket_send", return_value=False), patch(
            "core.utils._is_gevent_monkey_patched", return_value=True
        ), patch("gevent.spawn") as mock_spawn:
            _dispatch_system_event_integrations("channel_stop", channel_id="abc")

        mock_spawn.assert_called_once()
        mock_dispatch.assert_not_called()
