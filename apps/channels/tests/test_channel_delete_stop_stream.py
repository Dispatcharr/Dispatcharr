"""Channel delete optionally stops live proxy sessions (default: leave playing)."""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from apps.channels.models import Channel, ChannelGroup

User = get_user_model()


class ChannelDeleteStopStreamAPITests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="deleter", password="testpass123")
        self.user.user_level = 10
        self.user.save()
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.group = ChannelGroup.objects.create(name="Delete API Group")
        self.channel = Channel.objects.create(
            channel_number=42.0,
            name="Playing Channel",
            channel_group=self.group,
        )

    @patch(
        "apps.proxy.live_proxy.services.channel_service.ChannelService.stop_channels"
    )
    def test_delete_without_stop_stream_leaves_proxy_running(self, mock_stop_channels):
        url = f"/api/channels/channels/{self.channel.id}/"
        response = self.client.delete(url)

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Channel.objects.filter(pk=self.channel.pk).exists())
        mock_stop_channels.assert_not_called()

    @patch(
        "apps.proxy.live_proxy.services.channel_service.ChannelService.stop_channels"
    )
    def test_delete_with_stop_stream_stops_before_delete(self, mock_stop_channels):
        url = f"/api/channels/channels/{self.channel.id}/?stop_stream=true"
        channel_uuid = self.channel.uuid

        response = self.client.delete(url)

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Channel.objects.filter(pk=self.channel.pk).exists())
        mock_stop_channels.assert_called_once()
        stopped = list(mock_stop_channels.call_args[0][0])
        self.assertEqual(stopped, [channel_uuid])

    @patch(
        "apps.proxy.live_proxy.services.channel_service.ChannelService.stop_channels"
    )
    def test_bulk_delete_without_stop_stream(self, mock_stop_channels):
        other = Channel.objects.create(
            channel_number=43.0,
            name="Other",
            channel_group=self.group,
        )
        response = self.client.delete(
            "/api/channels/channels/bulk-delete/",
            {"channel_ids": [self.channel.id, other.id]},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Channel.objects.filter(pk=self.channel.pk).exists())
        mock_stop_channels.assert_not_called()

    @patch(
        "apps.proxy.live_proxy.services.channel_service.ChannelService.stop_channels"
    )
    def test_bulk_delete_with_stop_stream(self, mock_stop_channels):
        other = Channel.objects.create(
            channel_number=43.0,
            name="Other",
            channel_group=self.group,
        )
        response = self.client.delete(
            "/api/channels/channels/bulk-delete/",
            {
                "channel_ids": [self.channel.id, other.id],
                "stop_stream": True,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        mock_stop_channels.assert_called_once()
        stopped = set(mock_stop_channels.call_args[0][0])
        self.assertEqual(stopped, {self.channel.uuid, other.uuid})
