"""Custom M3U account actions must require admin, matching standard update."""

from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from apps.channels.models import ChannelGroup, ChannelGroupM3UAccount
from apps.m3u.models import M3UAccount

User = get_user_model()


class M3UAccountCustomActionPermissionTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.account = M3UAccount.objects.create(
            name=f"acct-{uuid4().hex[:8]}",
            server_url="http://example.com/playlist.m3u",
            account_type=M3UAccount.Types.XC,
            is_active=True,
            custom_properties={"enable_vod": True},
        )
        self.group = ChannelGroup.objects.create(name=f"group-{uuid4().hex[:6]}")
        ChannelGroupM3UAccount.objects.create(
            m3u_account=self.account,
            channel_group=self.group,
            enabled=True,
        )

    def _user(self, level):
        return User.objects.create_user(
            username=f"m3u-act-{level}-{uuid4().hex[:8]}",
            password="pass",
            user_level=level,
        )

    def _group_settings_payload(self):
        return {
            "group_settings": [
                {
                    "channel_group": self.group.id,
                    "enabled": True,
                    "auto_channel_sync": True,
                    "auto_sync_channel_start": 500.0,
                    "auto_sync_channel_end": 600.0,
                }
            ]
        }

    def test_streamer_denied_custom_actions(self):
        self.client.force_authenticate(user=self._user(User.UserLevel.STREAMER))
        group_settings = self.client.patch(
            f"/api/m3u/accounts/{self.account.id}/group-settings/",
            self._group_settings_payload(),
            format="json",
        )
        repack = self.client.post(
            f"/api/m3u/accounts/{self.account.id}/repack-group/"
            f"?channel_group_id={self.group.id}"
        )
        refresh = self.client.post(
            f"/api/m3u/accounts/{self.account.id}/refresh-vod/"
        )
        preview = self.client.get(
            f"/api/m3u/accounts/{self.account.id}/auto-created-channels-count/"
        )
        self.assertEqual(group_settings.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(repack.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(refresh.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(preview.status_code, status.HTTP_403_FORBIDDEN)

    def test_standard_user_denied_custom_actions(self):
        self.client.force_authenticate(user=self._user(User.UserLevel.STANDARD))
        group_settings = self.client.patch(
            f"/api/m3u/accounts/{self.account.id}/group-settings/",
            self._group_settings_payload(),
            format="json",
        )
        repack = self.client.post(
            f"/api/m3u/accounts/{self.account.id}/repack-group/"
            f"?channel_group_id={self.group.id}"
        )
        refresh = self.client.post(
            f"/api/m3u/accounts/{self.account.id}/refresh-vod/"
        )
        self.assertEqual(group_settings.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(repack.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(refresh.status_code, status.HTTP_403_FORBIDDEN)

    @patch("apps.vod.tasks.refresh_vod_content.delay")
    def test_admin_can_call_custom_actions(self, mock_refresh):
        self.client.force_authenticate(user=self._user(User.UserLevel.ADMIN))
        group_settings = self.client.patch(
            f"/api/m3u/accounts/{self.account.id}/group-settings/",
            self._group_settings_payload(),
            format="json",
        )
        self.assertEqual(group_settings.status_code, status.HTTP_200_OK)

        with patch(
            "apps.channels.compact_numbering.repack_group",
            return_value={"assigned": 0, "released": 0, "failed": 0},
        ):
            repack = self.client.post(
                f"/api/m3u/accounts/{self.account.id}/repack-group/"
                f"?channel_group_id={self.group.id}"
            )
        self.assertEqual(repack.status_code, status.HTTP_200_OK)

        refresh = self.client.post(
            f"/api/m3u/accounts/{self.account.id}/refresh-vod/"
        )
        self.assertEqual(refresh.status_code, status.HTTP_202_ACCEPTED)
        mock_refresh.assert_called_once_with(self.account.id)

        preview = self.client.get(
            f"/api/m3u/accounts/{self.account.id}/auto-created-channels-count/"
        )
        self.assertEqual(preview.status_code, status.HTTP_200_OK)
