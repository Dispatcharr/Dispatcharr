"""Tests for WebSocket delivery context detection in core.utils."""

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase


class WebSocketContextDetectionTests(SimpleTestCase):
    def test_sync_not_used_without_gevent_patch(self):
        from core.utils import _should_use_sync_websocket_send

        with patch("core.utils._is_gevent_monkey_patched", return_value=False), patch(
            "core.utils._is_celery_worker_context", return_value=True
        ):
            self.assertFalse(_should_use_sync_websocket_send())

    def test_sync_not_used_in_gevent_uwsgi_without_celery(self):
        from core.utils import _should_use_sync_websocket_send

        with patch("core.utils._is_gevent_monkey_patched", return_value=True), patch(
            "core.utils._is_celery_worker_context", return_value=False
        ):
            self.assertFalse(_should_use_sync_websocket_send())

    def test_sync_used_in_celery_with_gevent_patch(self):
        from core.utils import _should_use_sync_websocket_send

        with patch("core.utils._is_gevent_monkey_patched", return_value=True), patch(
            "core.utils._is_celery_worker_context", return_value=True
        ):
            self.assertTrue(_should_use_sync_websocket_send())


class SendWebsocketUpdateRoutingTests(SimpleTestCase):
    def test_celery_gevent_uses_sync_redis_path(self):
        from core.utils import send_websocket_update

        with patch("core.utils._should_use_sync_websocket_send", return_value=True), patch(
            "core.utils._gevent_ws_send"
        ) as mock_sync, patch("core.utils.get_channel_layer") as mock_layer:
            send_websocket_update("updates", "update", {"type": "epg_refresh"})

        mock_sync.assert_called_once()
        mock_layer.assert_not_called()

    def test_gevent_uwsgi_uses_spawn(self):
        from core.utils import send_websocket_update

        with patch("core.utils._should_use_sync_websocket_send", return_value=False), patch(
            "core.utils._is_gevent_monkey_patched", return_value=True
        ), patch("gevent.spawn") as mock_spawn, patch(
            "core.utils.get_channel_layer"
        ) as mock_layer:
            send_websocket_update("updates", "update", {"type": "epg_refresh"})

        mock_spawn.assert_called_once()
        mock_layer.assert_not_called()

    def test_plain_context_uses_channel_layer(self):
        from core.utils import send_websocket_update

        mock_layer = MagicMock()
        with patch("core.utils._should_use_sync_websocket_send", return_value=False), patch(
            "core.utils._is_gevent_monkey_patched", return_value=False
        ), patch("core.utils.get_channel_layer", return_value=mock_layer), patch(
            "core.utils.async_to_sync", side_effect=lambda fn: fn
        ) as mock_async_to_sync:
            send_websocket_update("updates", "update", {"type": "epg_refresh"})

        mock_async_to_sync.assert_called_once()
        mock_layer.group_send.assert_called_once()
