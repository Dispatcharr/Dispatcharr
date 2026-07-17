"""Tests for catch-up stats API and builders."""

import json
import time
from datetime import datetime, timedelta, timezone as dt_timezone
from unittest.mock import MagicMock, patch

from django.test import TestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.accounts.models import User
from apps.proxy.live_proxy.constants import ChannelMetadataField, ChannelState
from apps.timeshift.redis_keys import TimeshiftRedisKeys as RedisKeys, parse_stats_channel_id
from apps.timeshift import stats_views
from apps.timeshift.helpers import get_programme_info
from apps.timeshift.stats import (
    build_timeshift_stats_data,
    compute_playback_base_from_byte_range,
    compute_playback_position_secs,
    find_stats_channel_for_session,
    resolve_stats_playback_fields,
    seed_stream_stats_metadata,
    stream_stats_to_metadata_fields,
    update_catchup_session_position,
)
from apps.timeshift.tests.test_views import _FakeRedis

TEST_SESSION_ID = "testsession1"
STATS_CHANNEL_ID = f"8_{TEST_SESSION_ID}"


class TimeshiftHelperParsingTests(TestCase):
    def test_parse_stats_channel_id(self):
        parsed = parse_stats_channel_id(STATS_CHANNEL_ID)
        self.assertEqual(parsed["channel_id"], 8)
        self.assertEqual(parsed["session_id"], TEST_SESSION_ID)


class GetProgrammeInfoTests(TestCase):
    def _channel_with_programme(self, title="Evening News", sub_title="Local Edition", minutes=45):
        start = datetime(2026, 6, 8, 17, 0, tzinfo=dt_timezone.utc)
        programme = MagicMock(
            title=title,
            sub_title=sub_title,
            description="Details",
            start_time=start,
            end_time=start + timedelta(minutes=minutes),
        )
        channel = MagicMock()
        channel.epg_data.programs.filter.return_value.first.return_value = programme
        return channel

    def test_get_programme_info_resolves_title(self):
        info = get_programme_info(self._channel_with_programme(), "2026-06-08:17-00")
        self.assertEqual(info["title"], "Evening News")
        self.assertEqual(info["sub_title"], "Local Edition")
        self.assertEqual(info["duration_secs"], 45 * 60)

    def test_get_programme_info_advances_past_end(self):
        from datetime import datetime, timedelta, timezone as dt_timezone
        from unittest.mock import MagicMock

        start = datetime(2026, 6, 8, 17, 0, tzinfo=dt_timezone.utc)
        first = MagicMock(
            title="Show A",
            sub_title="",
            description="",
            start_time=start,
            end_time=start + timedelta(minutes=30),
        )
        second = MagicMock(
            title="Show B",
            sub_title="",
            description="",
            start_time=start + timedelta(minutes=30),
            end_time=start + timedelta(minutes=60),
        )
        channel = MagicMock()

        def _filter(**kwargs):
            qs = MagicMock()
            dt = kwargs["start_time__lte"]
            chosen = None
            for prog in (first, second):
                if prog.start_time <= dt and prog.end_time > dt:
                    chosen = prog
                    break
            qs.first.return_value = chosen
            return qs

        channel.epg_data.programs.filter.side_effect = _filter
        info = get_programme_info(channel, "2026-06-08:17-00", position_secs=31 * 60)
        self.assertEqual(info["title"], "Show B")
        self.assertEqual(info["duration_secs"], 30 * 60)


class ComputePlaybackPositionTests(TestCase):
    EPG_START = "2026-07-10T14:00:00+00:00"

    def test_byte_range_base_plus_elapsed(self):
        pos = compute_playback_position_secs(
            "2026-07-10:14-00",
            self.EPG_START,
            position_anchor_at=1000.0,
            current_time=1030.0,
            duration_secs=3600,
            playback_base_secs=1800.0,
        )
        self.assertAlmostEqual(pos, 1830.0)

    def test_url_offset_plus_elapsed(self):
        # Seeked to 14:19 (19 min into a 14:00 programme), stream opened 30s ago.
        pos = compute_playback_position_secs(
            "2026-07-10:14-19",
            self.EPG_START,
            position_anchor_at=1000.0,
            current_time=1030.0,
            duration_secs=3600,
        )
        self.assertAlmostEqual(pos, 19 * 60 + 30)

    def test_capped_at_duration(self):
        pos = compute_playback_position_secs(
            "2026-07-10:14-19",
            self.EPG_START,
            position_anchor_at=1000.0,
            current_time=100000.0,
            duration_secs=1800,
        )
        self.assertEqual(pos, 1800)

    def test_missing_epg_returns_none(self):
        self.assertIsNone(
            compute_playback_position_secs(
                "2026-07-10:14-19", None, 1000.0, 1030.0,
            )
        )

    def test_no_anchor_uses_url_offset_only(self):
        pos = compute_playback_position_secs(
            "2026-07-10:14-05",
            self.EPG_START,
            position_anchor_at=None,
            current_time=1030.0,
            duration_secs=3600,
        )
        self.assertAlmostEqual(pos, 5 * 60)

    def test_paused_freezes_wall_clock_advance(self):
        pos = compute_playback_position_secs(
            "2026-07-10:14-00",
            self.EPG_START,
            position_anchor_at=1000.0,
            current_time=1300.0,
            duration_secs=3600,
            playback_base_secs=900.0,
            paused=True,
        )
        self.assertAlmostEqual(pos, 900.0)


class ByteRangePlaybackTests(TestCase):
    def test_compute_playback_base_from_byte_range(self):
        base = compute_playback_base_from_byte_range(
            506786520, 833563944, 3900,
        )
        self.assertAlmostEqual(base, 2371.0, delta=2.0)

    def test_resolve_byte_seek_reanchors(self):
        base, anchor = resolve_stats_playback_fields(
            timestamp_utc="2026-07-09:20:00:00",
            existing_programme_start="2026-07-09:20:00:00",
            existing_position_anchor="1000.0",
            existing_playback_base=None,
            range_start=506786520,
            representation_length=833563944,
            programme_duration_secs=3900,
            now="2000.0",
        )
        self.assertAlmostEqual(base, 2371.0, delta=2.0)
        self.assertEqual(anchor, "2000.0")

    def test_resolve_plain_get_reanchors_on_same_programme(self):
        base, anchor = resolve_stats_playback_fields(
            timestamp_utc="2026-06-08:17-00",
            existing_programme_start="2026-06-08:17-00",
            existing_position_anchor="1000.0",
            existing_playback_base="900.0",
            range_start=None,
            representation_length=833563944,
            programme_duration_secs=3900,
            now="2000.0",
        )
        self.assertIsNone(base)
        self.assertEqual(anchor, "2000.0")

    def test_resolve_near_eof_probe_keeps_existing_position(self):
        # Clients probe ~1.88MB from EOF for duration; must not flash to end.
        total = 8_783_238_116
        base, anchor = resolve_stats_playback_fields(
            timestamp_utc="2026-07-14:14-59",
            existing_programme_start="2026-07-14:14-59",
            existing_position_anchor="1000.0",
            existing_playback_base="2100.0",
            range_start=total - 1_880_000,
            representation_length=total,
            programme_duration_secs=3600,
            now="2000.0",
        )
        self.assertAlmostEqual(base, 2100.0)
        self.assertEqual(anchor, "1000.0")


class TimeshiftStreamStatsTests(TestCase):
    def test_stream_stats_to_metadata_fields(self):
        fields = stream_stats_to_metadata_fields({
            "resolution": "1920x1080",
            "source_fps": 30,
            "video_codec": "h264",
        })
        self.assertEqual(fields[ChannelMetadataField.RESOLUTION], "1920x1080")
        self.assertEqual(fields[ChannelMetadataField.SOURCE_FPS], "30")
        self.assertEqual(fields[ChannelMetadataField.VIDEO_CODEC], "h264")
        self.assertIn(ChannelMetadataField.STREAM_INFO_UPDATED, fields)

    def test_seed_stream_stats_metadata_skips_when_stream_unchanged(self):
        redis = _FakeRedis()
        metadata_key = RedisKeys.channel_metadata(STATS_CHANNEL_ID)
        redis.hset(metadata_key, ChannelMetadataField.STREAM_ID, "7")
        payload = {}
        seed_stream_stats_metadata(
            redis, metadata_key, payload,
            stats_stream_id=7,
            stream_stats={"resolution": "1920x1080"},
        )
        self.assertEqual(payload, {})

    def test_seed_stream_stats_metadata_applies_new_stream(self):
        redis = _FakeRedis()
        metadata_key = RedisKeys.channel_metadata(STATS_CHANNEL_ID)
        payload = {}
        seed_stream_stats_metadata(
            redis, metadata_key, payload,
            stats_stream_id=7,
            stream_stats={"resolution": "1280x720", "video_codec": "h264"},
        )
        self.assertEqual(payload[ChannelMetadataField.STREAM_ID], "7")
        self.assertEqual(payload[ChannelMetadataField.RESOLUTION], "1280x720")


class BuildTimeshiftStatsDataTests(TestCase):
    def setUp(self):
        self.channel_id = 42
        self.session_id = TEST_SESSION_ID
        self.stats_channel_id = f"{self.channel_id}_{self.session_id}"
        self.redis = _FakeRedis()
        now = time.time()
        metadata_key = RedisKeys.channel_metadata(self.stats_channel_id)
        client_set_key = RedisKeys.clients(self.stats_channel_id)
        client_key = RedisKeys.client_metadata(self.stats_channel_id, self.session_id)

        self.redis.hset(
            metadata_key,
            mapping={
                ChannelMetadataField.STATE: ChannelState.ACTIVE,
                ChannelMetadataField.CHANNEL_ID: str(self.channel_id),
                ChannelMetadataField.CHANNEL_UUID: "00000000-0000-0000-0000-000000000042",
                ChannelMetadataField.CHANNEL_NAME: "Catch-up Stats Channel",
                ChannelMetadataField.INIT_TIME: str(now - 120),
                ChannelMetadataField.TOTAL_BYTES: "1048576",
                ChannelMetadataField.LOGO_ID: "0",
                ChannelMetadataField.RESOLUTION: "1920x1080",
                ChannelMetadataField.SOURCE_FPS: "29.97",
                ChannelMetadataField.VIDEO_CODEC: "h264",
            },
        )
        self.redis.sadd(client_set_key, self.session_id)
        self.anchor_at = now - 30
        self.redis.hset(
            client_key,
            mapping={
                "user_agent": "VLC/3.0.0",
                "ip_address": "10.0.0.5",
                "connected_at": str(now - 60),
                "user_id": "1",
                "username": "viewer",
                "programme_vid": f"8_{self.channel_id}_2026-06-08-17-00_111",
                "programme_start": "2026-06-08:17-15",
                "position_anchor_at": str(self.anchor_at),
            },
        )

    @patch("apps.timeshift.stats.Channel")
    def test_build_timeshift_stats_data_redis_only_programme_fields(
        self, mock_channel_model,
    ):
        channel = MagicMock()
        channel.id = self.channel_id
        channel.name = "Catch-up Stats Channel"
        channel.uuid = "00000000-0000-0000-0000-000000000042"
        channel.logo_id = None
        channel.logo = None
        mock_channel_model.objects.filter.return_value = [
            channel,
        ]
        payload = build_timeshift_stats_data(self.redis)
        self.assertEqual(payload["total_connections"], 1)
        self.assertEqual(len(payload["timeshift_sessions"]), 1)
        session = payload["timeshift_sessions"][0]
        self.assertEqual(session["session_id"], self.session_id)
        self.assertEqual(session["programme_start"], "2026-06-08:17-15")
        self.assertAlmostEqual(session["position_anchor_at"], self.anchor_at, places=3)
        self.assertNotIn("programme_title", session)
        self.assertNotIn("playback_position_secs", session)
        self.assertEqual(session["channel_name"], "Catch-up Stats Channel")
        self.assertEqual(session["resolution"], "1920x1080")
        self.assertFalse(session["paused"])
        self.assertEqual(session["connections"][0]["ip_address"], "10.0.0.5")

    @patch("apps.timeshift.stats.Channel")
    def test_build_timeshift_stats_exposes_logo_id_only(self, mock_channel_model):
        channel = MagicMock()
        channel.id = self.channel_id
        channel.name = "Catch-up Stats Channel"
        channel.uuid = "00000000-0000-0000-0000-000000000042"
        channel.logo_id = 77
        mock_channel_model.objects.filter.return_value = [channel]
        session = build_timeshift_stats_data(self.redis)["timeshift_sessions"][0]
        self.assertEqual(session["logo_id"], 77)
        self.assertNotIn("logo_url", session)

    def test_find_stats_channel_for_session(self):
        found = find_stats_channel_for_session(self.redis, self.session_id)
        self.assertEqual(found, self.stats_channel_id)

    def test_update_catchup_session_position_sets_base_and_pause(self):
        updated = update_catchup_session_position(
            self.session_id,
            position_secs=842.5,
            paused=True,
            user_id=1,
            redis_client=self.redis,
        )
        self.assertTrue(updated)
        client_key = RedisKeys.client_metadata(self.stats_channel_id, self.session_id)
        data = self.redis.hgetall(client_key)
        self.assertEqual(data["playback_base_secs"], "842.5")
        self.assertEqual(data["paused"], "1")
        self.assertIsNotNone(data.get("position_anchor_at"))

    @patch("apps.timeshift.stats.Channel")
    def test_build_includes_paused_flag(self, mock_channel_model):
        channel = MagicMock()
        channel.id = self.channel_id
        channel.name = "Catch-up Stats Channel"
        channel.uuid = "00000000-0000-0000-0000-000000000042"
        channel.logo_id = None
        channel.logo = None
        mock_channel_model.objects.filter.return_value = [
            channel,
        ]
        client_key = RedisKeys.client_metadata(self.stats_channel_id, self.session_id)
        self.redis.hset(client_key, mapping={"paused": "1", "playback_base_secs": "100"})
        session = build_timeshift_stats_data(self.redis)["timeshift_sessions"][0]
        self.assertTrue(session["paused"])
        self.assertEqual(session["playback_base_secs"], 100.0)

    @patch("apps.timeshift.stats.Channel")
    def test_skips_clients_missing_required_metadata(self, mock_channel_model):
        mock_channel_model.objects.filter.return_value = []
        orphan_key = RedisKeys.client_metadata(self.stats_channel_id, "orphan")
        self.redis.hset(orphan_key, mapping={"user_agent": "VLC"})
        self.redis.sadd(RedisKeys.clients(self.stats_channel_id), "orphan")
        payload = build_timeshift_stats_data(self.redis)
        self.assertEqual(payload["total_connections"], 1)


class TimeshiftStatsApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create(
            username="catchup-stats-admin",
            user_level=User.UserLevel.ADMIN,
        )

    def setUp(self):
        self.factory = APIRequestFactory()
        self.redis = _FakeRedis()
        self.session_id = TEST_SESSION_ID
        self.stats_channel_id = f"8_{self.session_id}"

    @patch("apps.timeshift.stats_views.RedisClient.get_client")
    @patch("apps.timeshift.stats_views.build_timeshift_stats_data")
    def test_timeshift_stats_requires_admin(self, mock_build, redis_mock):
        mock_build.return_value = {
            "timeshift_sessions": [],
            "total_connections": 0,
            "timestamp": 1,
        }
        redis_mock.return_value = self.redis

        request = self.factory.get("/proxy/catchup/stats/")
        force_authenticate(request, user=self.admin)
        response = stats_views.timeshift_stats(request)
        self.assertEqual(response.status_code, 200)
        self.assertIn("timeshift_sessions", json.loads(response.content))

    @patch("apps.timeshift.stats_views.stop_timeshift_client")
    @patch("apps.timeshift.stats_views.RedisClient.get_client")
    def test_stop_timeshift_session(self, redis_mock, stop_mock):
        redis_mock.return_value = self.redis
        stop_mock.return_value = {"status": "success"}

        metadata_key = RedisKeys.channel_metadata(self.stats_channel_id)
        client_key = RedisKeys.client_metadata(self.stats_channel_id, self.session_id)
        self.redis.hset(metadata_key, mapping={ChannelMetadataField.STATE: ChannelState.ACTIVE})
        self.redis.sadd(RedisKeys.clients(self.stats_channel_id), self.session_id)
        self.redis.hset(
            client_key,
            mapping={
                "programme_start": "2026-06-08:17-00",
            },
        )

        request = self.factory.post(
            "/proxy/catchup/stop_client/",
            {"session_id": self.session_id},
            format="json",
        )
        force_authenticate(request, user=self.admin)
        response = stats_views.stop_timeshift_session(request)
        self.assertEqual(response.status_code, 200)
        stop_mock.assert_called_once_with(
            self.redis, self.stats_channel_id, self.session_id,
        )

    @patch("apps.timeshift.stats_views.get_catchup_programmes_for_sessions")
    def test_catchup_programmes_batch(self, programmes_mock):
        programmes_mock.return_value = [{
            "session_id": self.session_id,
            "title": "Evening News",
            "start_time": "2026-06-08T17:00:00+00:00",
        }]
        request = self.factory.post(
            "/proxy/catchup/programs/",
            {"sessions": [{
                "session_id": self.session_id,
                "channel_uuid": "00000000-0000-0000-0000-000000000099",
                "programme_start": "2026-06-08:17-00",
            }]},
            format="json",
        )
        force_authenticate(request, user=self.admin)
        response = stats_views.catchup_programmes(request)
        self.assertEqual(response.status_code, 200)
        body = json.loads(response.content)
        self.assertEqual(body["sessions"][0]["title"], "Evening News")
        programmes_mock.assert_called_once()
