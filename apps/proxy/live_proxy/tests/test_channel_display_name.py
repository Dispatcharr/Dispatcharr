"""Logged channel names should be override-aware when available."""

from unittest.mock import MagicMock, patch

from django.test import TestCase

from apps.channels.models import Channel, ChannelOverride
from apps.proxy.live_proxy.services.channel_service import ChannelService


class ChannelServiceDisplayNameTests(TestCase):
    @patch("apps.proxy.live_proxy.services.channel_service.close_old_connections")
    @patch("apps.proxy.live_proxy.services.channel_service.ProxyServer")
    def test_fallback_loads_effective_name(self, mock_proxy_cls, _mock_close):
        channel = Channel.objects.create(
            channel_number=1.0,
            name="Provider Name",
            auto_created=True,
        )
        ChannelOverride.objects.create(channel=channel, name="Display Name")

        proxy_server = MagicMock()
        proxy_server.redis_client = None
        proxy_server.initialize_channel.return_value = True
        mock_proxy_cls.get_instance.return_value = proxy_server

        result = ChannelService.initialize_channel(
            str(channel.uuid),
            "http://example.com/stream.ts",
            "ua",
        )

        self.assertTrue(result)
        proxy_server.initialize_channel.assert_called_once()
        self.assertEqual(
            proxy_server.initialize_channel.call_args.kwargs["channel_name"],
            "Display Name",
        )

    @patch("apps.proxy.live_proxy.services.channel_service.close_old_connections")
    @patch("apps.proxy.live_proxy.services.channel_service.ProxyServer")
    def test_explicit_channel_name_is_not_overwritten(self, mock_proxy_cls, _mock_close):
        channel = Channel.objects.create(
            channel_number=2.0,
            name="Provider Name",
            auto_created=True,
        )
        ChannelOverride.objects.create(channel=channel, name="Display Name")

        proxy_server = MagicMock()
        proxy_server.redis_client = None
        proxy_server.initialize_channel.return_value = True
        mock_proxy_cls.get_instance.return_value = proxy_server

        result = ChannelService.initialize_channel(
            str(channel.uuid),
            "http://example.com/stream.ts",
            "ua",
            channel_name="Caller Name",
        )

        self.assertTrue(result)
        self.assertEqual(
            proxy_server.initialize_channel.call_args.kwargs["channel_name"],
            "Caller Name",
        )
