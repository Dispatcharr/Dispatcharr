"""Tests for combined connection stats API and live stats builder."""

import json
from unittest.mock import MagicMock, patch

from django.test import TestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.accounts.models import User
from apps.proxy import stats_views
from apps.proxy.live_proxy.channel_status import build_live_channel_stats_data


class BuildLiveChannelStatsDataTests(TestCase):
    @patch("apps.proxy.live_proxy.channel_status.ChannelStatus.get_basic_channel_info")
    def test_builds_channel_list_from_metadata_scan(self, mock_get_info):
        mock_get_info.side_effect = lambda ch_id: {"channel_id": ch_id}

        redis = MagicMock()
        redis.scan.return_value = (
            0,
            [
                "live:channel:abc-uuid:metadata",
                "live:channel:def-uuid:metadata",
            ],
        )

        result = build_live_channel_stats_data(redis)

        self.assertEqual(result["count"], 2)
        self.assertEqual(
            [ch["channel_id"] for ch in result["channels"]],
            ["abc-uuid", "def-uuid"],
        )

    def test_returns_empty_when_redis_unavailable(self):
        result = build_live_channel_stats_data(None)
        self.assertEqual(result, {"channels": [], "count": 0})

    @patch("apps.proxy.live_proxy.channel_status.ChannelStatus.get_basic_channel_info")
    def test_returns_empty_on_error(self, mock_get_info):
        mock_get_info.side_effect = RuntimeError("redis blew up")

        redis = MagicMock()
        redis.scan.return_value = (0, ["live:channel:abc-uuid:metadata"])

        result = build_live_channel_stats_data(redis)

        self.assertEqual(result, {"channels": [], "count": 0})


class CombinedStatsApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create(
            username="combined-stats-admin",
            user_level=User.UserLevel.ADMIN,
        )

    def setUp(self):
        self.factory = APIRequestFactory()

    @patch("apps.proxy.stats_views.build_timeshift_stats_data")
    @patch("apps.proxy.stats_views.build_vod_stats_data")
    @patch("apps.proxy.stats_views.build_live_channel_stats_data")
    @patch("apps.proxy.stats_views.RedisClient.get_client")
    def test_combined_stats_returns_all_sections(
        self,
        redis_mock,
        live_mock,
        vod_mock,
        catchup_mock,
    ):
        redis_mock.return_value = MagicMock()
        live_mock.return_value = {"channels": [{"channel_id": "ch-1"}], "count": 1}
        vod_mock.return_value = {
            "vod_connections": [],
            "total_connections": 0,
            "timestamp": 100.0,
        }
        catchup_mock.return_value = {
            "timeshift_sessions": [],
            "total_connections": 0,
            "timestamp": 100.0,
        }

        request = self.factory.get("/proxy/stats/")
        force_authenticate(request, user=self.admin)
        response = stats_views.combined_stats(request)

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.content)
        self.assertEqual(payload["live"]["count"], 1)
        self.assertIn("vod_connections", payload["vod"])
        self.assertIn("timeshift_sessions", payload["catchup"])
        self.assertIn("timestamp", payload)
        live_mock.assert_called_once()
        vod_mock.assert_called_once()
        catchup_mock.assert_called_once()

    @patch("apps.proxy.stats_views.RedisClient.get_client")
    def test_combined_stats_redis_unavailable(self, redis_mock):
        redis_mock.return_value = None

        request = self.factory.get("/proxy/stats/")
        force_authenticate(request, user=self.admin)
        response = stats_views.combined_stats(request)

        self.assertEqual(response.status_code, 500)
        self.assertIn("error", json.loads(response.content))
