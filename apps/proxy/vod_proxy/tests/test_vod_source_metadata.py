import json
import time
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, TestCase

from apps.m3u.models import M3UAccount
from apps.vod.models import (
    Episode,
    M3UEpisodeRelation,
    M3USeriesRelation,
    Series,
    VODCategory,
)
from apps.proxy.vod_proxy.multi_worker_connection_manager import (
    MultiWorkerVODConnectionManager,
    RedisBackedVODConnection,
    SerializableConnectionState,
)
from apps.proxy.vod_proxy.views import (
    _build_vod_source_metadata,
    build_vod_stats_data,
)


class VODSourceMetadataStatsTests(TestCase):
    def setUp(self):
        self.account = M3UAccount.objects.create(
            name="tivione-z2u",
            server_url="http://example.com",
            is_active=True,
        )
        category = VODCategory.objects.create(
            name="NICKELODEON",
            category_type="series",
        )
        series = Series.objects.create(
            name="Avatar: Der Herr der Elemente",
            tmdb_id="246",
        )
        series_relation = M3USeriesRelation.objects.create(
            m3u_account=self.account,
            series=series,
            category=category,
            external_series_id="nick-avatar",
        )
        self.episode = Episode.objects.create(
            series=series,
            season_number=3,
            episode_number=1,
            name="DE - Canonical title",
            description="Canonical plot",
            duration_secs=1475,
        )
        self.relation = M3UEpisodeRelation.objects.create(
            m3u_account=self.account,
            episode=self.episode,
            series_relation=series_relation,
            stream_id="686164",
            custom_properties={
                "info": {
                    "title": "NICK - The Awakening",
                    "info": {
                        "plot": "Nickelodeon plot",
                        "duration_secs": 1443,
                    },
                }
            },
        )

    def test_stats_use_the_exact_episode_relation_metadata(self):
        source_metadata = _build_vod_source_metadata(
            "episode", self.episode, self.relation
        )
        redis_client = MagicMock()
        redis_client.scan.return_value = (
            0,
            ["vod_persistent_connection:nick-session"],
        )
        redis_client.hgetall.return_value = {
            "content_obj_type": "episode",
            "content_uuid": str(self.episode.uuid),
            "content_name": self.episode.name,
            "client_ip": "127.0.0.1",
            "client_user_agent": "UHF",
            "created_at": str(time.time()),
            "last_activity": str(time.time()),
            "active_streams": "1",
            "source_metadata": json.dumps(source_metadata),
        }

        stats = build_vod_stats_data(redis_client)

        self.assertEqual(stats["total_connections"], 1)
        vod = stats["vod_connections"][0]
        connection = vod["connections"][0]
        metadata = vod["content_metadata"]
        self.assertEqual(metadata["episode_name"], "NICK - The Awakening")
        self.assertEqual(metadata["description"], "Nickelodeon plot")
        self.assertEqual(metadata["duration_secs"], 1443)
        self.assertEqual(metadata["m3u_account_name"], "tivione-z2u")
        self.assertEqual(metadata["category_name"], "NICKELODEON")
        self.assertEqual(metadata["stream_id"], "686164")
        self.assertEqual(metadata["relation_id"], self.relation.id)
        self.assertEqual(
            connection["source_metadata"]["source_key"],
            f"episode:{self.relation.id}",
        )


class VODSourceSessionTests(SimpleTestCase):
    def _manager_with_session(self, source_key):
        redis_client = MagicMock()
        redis_client.scan.return_value = (
            0,
            ["vod_persistent_connection:existing"],
        )
        redis_client.hgetall.return_value = {
            "content_obj_type": "episode",
            "content_uuid": "episode-uuid",
            "source_metadata": json.dumps({"source_key": source_key}),
            "client_ip": "127.0.0.1",
            "client_user_agent": "UHF",
            "utc_start": "",
            "utc_end": "",
            "offset": "",
            "last_activity": "1000",
        }
        manager = MultiWorkerVODConnectionManager.__new__(
            MultiWorkerVODConnectionManager
        )
        manager.redis_client = redis_client
        return manager

    @patch.object(
        RedisBackedVODConnection,
        "has_active_streams",
        return_value=False,
    )
    def test_idle_session_is_not_reused_across_category_relations(
        self, _has_active_streams
    ):
        manager = self._manager_with_session("episode:1")

        match = manager.find_matching_idle_session(
            "episode",
            "episode-uuid",
            "127.0.0.1",
            "UHF",
            source_key="episode:2",
        )

        self.assertIsNone(match)

    @patch.object(
        RedisBackedVODConnection,
        "has_active_streams",
        return_value=False,
    )
    def test_idle_session_can_be_reused_for_the_same_relation(
        self, _has_active_streams
    ):
        manager = self._manager_with_session("episode:1")

        match = manager.find_matching_idle_session(
            "episode",
            "episode-uuid",
            "127.0.0.1",
            "UHF",
            source_key="episode:1",
        )

        self.assertEqual(match, "existing")

    def test_source_metadata_survives_redis_serialization(self):
        state = SerializableConnectionState(
            session_id="session",
            stream_url="http://example.com/episode.mkv",
            headers={},
            source_metadata={
                "source_key": "episode:7",
                "category_name": "NICKELODEON",
            },
        )

        restored = SerializableConnectionState.from_dict(state.to_dict())

        self.assertEqual(restored.source_metadata, state.source_metadata)

