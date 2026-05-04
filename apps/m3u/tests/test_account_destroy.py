"""
DELETE /api/m3u/accounts/{id}/ behavior.

The endpoint always cascade-deletes auto-created channels owned by the
account. Manual channels survive even if some of their streams were
owned by the deleted account; only the streams from that account go
away with the account, and the channel keeps any streams sourced from
other accounts. The legacy ``cleanup_channels`` query parameter is
accepted but ignored.
"""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.channels.models import (
    Channel,
    ChannelGroup,
    ChannelStream,
    Stream,
)
from apps.m3u.models import M3UAccount

User = get_user_model()


class M3UAccountDestroyTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="destroyer", password="testpass123"
        )
        self.user.user_level = 10
        self.user.save()
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        # Patching the proxy stop here keeps the Redis-backed call out
        # of the test path. The endpoint loops over every auto-created
        # channel before the DB transaction; the real implementation is
        # exercised by integration tests, not unit tests.
        self._stop_patch = patch(
            "apps.proxy.ts_proxy.services.channel_service."
            "ChannelService.stop_channel"
        )
        self._stop_patch.start()
        self.addCleanup(self._stop_patch.stop)

        self.account = M3UAccount.objects.create(
            name="ProviderA",
            server_url="http://example.com/a.m3u",
        )
        self.other_account = M3UAccount.objects.create(
            name="ProviderB",
            server_url="http://example.com/b.m3u",
        )
        self.group = ChannelGroup.objects.create(name="News")

    def _make_stream(self, account, name="ESPN"):
        return Stream.objects.create(
            name=name,
            url=f"http://example.com/{name.lower()}.m3u8",
            m3u_account=account,
            channel_group=self.group,
            tvg_id=name.lower(),
            last_seen=timezone.now(),
        )

    def test_cascade_deletes_auto_created_channels(self):
        # Two auto-created channels under the account being deleted.
        for n in (101.0, 102.0):
            ch = Channel.objects.create(
                channel_number=n,
                name=f"Auto {n}",
                channel_group=self.group,
                auto_created=True,
                auto_created_by=self.account,
            )
            ChannelStream.objects.create(
                channel=ch,
                stream=self._make_stream(self.account, name=f"Auto{int(n)}"),
                order=0,
            )

        response = self.client.delete(
            f"/api/m3u/accounts/{self.account.id}/"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["deleted_channels"], 2)
        self.assertFalse(M3UAccount.objects.filter(id=self.account.id).exists())
        self.assertFalse(
            Channel.objects.filter(auto_created_by_id=self.account.id).exists()
        )

    def test_manual_channel_survives_with_other_provider_streams(self):
        # Manual channel with one stream from each account. The provider
        # account's stream goes away with the account; the other
        # account's stream stays, and the channel survives.
        manual = Channel.objects.create(
            channel_number=200.0,
            name="Manual",
            channel_group=self.group,
            auto_created=False,
        )
        provider_stream = self._make_stream(self.account, name="ProviderA")
        other_stream = self._make_stream(self.other_account, name="ProviderB")
        ChannelStream.objects.create(channel=manual, stream=provider_stream, order=0)
        ChannelStream.objects.create(channel=manual, stream=other_stream, order=1)

        response = self.client.delete(
            f"/api/m3u/accounts/{self.account.id}/"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["deleted_channels"], 0)

        manual.refresh_from_db()
        remaining = list(manual.channelstream_set.values_list("stream__id", flat=True))
        self.assertEqual(remaining, [other_stream.id])

    def test_legacy_cleanup_channels_param_is_ignored(self):
        # Behavior must be identical with or without the deprecated
        # ``cleanup_channels`` query parameter.
        ch = Channel.objects.create(
            channel_number=300.0,
            name="Auto",
            channel_group=self.group,
            auto_created=True,
            auto_created_by=self.account,
        )
        response = self.client.delete(
            f"/api/m3u/accounts/{self.account.id}/?cleanup_channels=false"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["deleted_channels"], 1)
        self.assertFalse(Channel.objects.filter(id=ch.id).exists())

    def test_no_op_when_account_has_no_auto_created_channels(self):
        response = self.client.delete(
            f"/api/m3u/accounts/{self.account.id}/"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["deleted_channels"], 0)
