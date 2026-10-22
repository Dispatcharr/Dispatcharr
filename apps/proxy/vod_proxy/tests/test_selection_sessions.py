"""A VOD session may only be reused for the same selected source context."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import RequestFactory, SimpleTestCase

from apps.proxy.vod_proxy.multi_worker_connection_manager import (
    MultiWorkerVODConnectionManager,
    SerializableConnectionState,
)
from apps.proxy.vod_proxy.tests.test_vod_lock_contention import (
    LockAwareFakeRedis,
    _seed_session,
)


class SelectionSessionTests(SimpleTestCase):
    def setUp(self):
        self.redis = LockAwareFakeRedis()
        self.manager = MultiWorkerVODConnectionManager.__new__(
            MultiWorkerVODConnectionManager
        )
        self.manager.redis_client = self.redis
        self.manager.worker_id = "synthetic-worker"

    def test_selection_key_survives_serialization_and_legacy_sessions(self):
        state = SerializableConnectionState(
            session_id="vod_selected",
            stream_url="https://example.invalid/movie",
            headers={},
            selection_key="movie:1:ger-1080p",
        )
        self.assertEqual(
            SerializableConnectionState.from_dict(state.to_dict()).selection_key,
            "movie:1:ger-1080p",
        )
        legacy = state.to_dict()
        legacy.pop("selection_key")
        self.assertEqual(
            SerializableConnectionState.from_dict(legacy).selection_key, ""
        )

    def test_idle_session_matching_requires_the_same_selection(self):
        _seed_session(self.redis, "vod_selected", active_streams=0)
        self.redis.hset(
            "vod_persistent_connection:vod_selected",
            mapping={
                "selection_key": "ger-1080p",
            },
        )
        self.redis.scan = MagicMock(
            return_value=(0, ["vod_persistent_connection:vod_selected"])
        )
        arguments = dict(
            content_type="movie",
            content_uuid="abc-123",
            client_ip="192.0.2.1",
            client_user_agent="synthetic-client",
        )
        self.assertIsNone(
            self.manager.find_matching_idle_session(
                **arguments,
                selection_key="eng-1080p",
            )
        )
        self.assertIsNone(self.manager.find_matching_idle_session(**arguments))
        self.assertEqual(
            self.manager.find_matching_idle_session(
                **arguments,
                selection_key="ger-1080p",
            ),
            "vod_selected",
        )

    def test_provided_session_with_other_selection_is_rejected_before_upstream(self):
        _seed_session(self.redis, "vod_selected", active_streams=0)
        self.redis.hset(
            "vod_persistent_connection:vod_selected",
            mapping={
                "selection_key": "ger-1080p",
            },
        )
        content = SimpleNamespace(
            uuid="abc-123", name="Synthetic movie", _vod_selection_key="eng-1080p"
        )
        with (
            patch.object(self.manager, "find_matching_idle_session", return_value=None),
            patch.object(self.manager, "_check_and_reserve_profile_slot") as reserve,
        ):
            response = self.manager.stream_content_with_session(
                "vod_selected",
                content,
                "https://example.invalid/movie",
                SimpleNamespace(id=7),
                "192.0.2.1",
                "synthetic-client",
                RequestFactory().get("/proxy/vod/episode/synthetic/"),
            )
        self.assertEqual(response.status_code, 409)
        reserve.assert_not_called()
        self.assertEqual(
            self.redis.hget("vod_persistent_connection:vod_selected", "active_streams"),
            "0",
        )
