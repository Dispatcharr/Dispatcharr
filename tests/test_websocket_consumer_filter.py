"""Tests for admin-only WebSocket update filtering."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from asgiref.sync import async_to_sync
from django.test import SimpleTestCase

from apps.accounts.models import User
from dispatcharr.consumers import (
    ADMIN_ONLY_UPDATE_TYPES,
    MyWebSocketConsumer,
    user_may_receive_update,
)


def _user(*, authenticated=True, user_level=User.UserLevel.STANDARD):
    return SimpleNamespace(is_authenticated=authenticated, user_level=user_level)


class UserMayReceiveUpdateTests(SimpleTestCase):
    def test_admin_only_types_are_explicit(self):
        self.assertEqual(
            ADMIN_ONLY_UPDATE_TYPES,
            frozenset(
                {
                    "channel_stats",
                    "vod_stats",
                    "timeshift_stats",
                    "vod_started",
                    "vod_stopped",
                }
            ),
        )

    def test_non_sensitive_types_allowed_for_standard_user(self):
        user = _user(user_level=User.UserLevel.STANDARD)
        self.assertTrue(
            user_may_receive_update(user, {"type": "epg_refresh", "success": True})
        )
        self.assertTrue(
            user_may_receive_update(user, {"type": "system_notification"})
        )
        self.assertTrue(user_may_receive_update(user, {"type": "ip_lookup_complete"}))

    def test_channel_stats_blocked_for_standard_user(self):
        user = _user(user_level=User.UserLevel.STANDARD)
        self.assertFalse(
            user_may_receive_update(
                user,
                {
                    "type": "channel_stats",
                    "stats": '{"channels":[{"channel_id":"leak-uuid","url":"http://provider"}]}',
                },
            )
        )

    def test_vod_and_timeshift_telemetry_blocked_for_standard_user(self):
        user = _user(user_level=User.UserLevel.STANDARD)
        for event_type in (
            "vod_stats",
            "timeshift_stats",
            "vod_started",
            "vod_stopped",
        ):
            with self.subTest(event_type=event_type):
                self.assertFalse(
                    user_may_receive_update(user, {"type": event_type})
                )

    def test_channel_stats_allowed_for_admin(self):
        user = _user(user_level=User.UserLevel.ADMIN)
        self.assertTrue(
            user_may_receive_update(user, {"type": "channel_stats", "stats": "{}"})
        )

    def test_missing_or_anonymous_user_blocked_for_admin_only_types(self):
        self.assertFalse(user_may_receive_update(None, {"type": "channel_stats"}))
        self.assertFalse(
            user_may_receive_update(
                _user(authenticated=False, user_level=User.UserLevel.ADMIN),
                {"type": "channel_stats"},
            )
        )

    def test_empty_data_allowed(self):
        # Unknown/empty payloads should not be dropped for Standard users.
        self.assertTrue(user_may_receive_update(_user(), None))
        self.assertTrue(user_may_receive_update(_user(), {}))


class ConsumerUpdateFilteringTests(SimpleTestCase):
    def _consumer(self, user):
        consumer = MyWebSocketConsumer()
        consumer.scope = {"user": user}
        consumer.send = AsyncMock()
        return consumer

    def test_update_drops_channel_stats_for_standard_user(self):
        consumer = self._consumer(_user(user_level=User.UserLevel.STANDARD))
        event = {
            "type": "update",
            "data": {"type": "channel_stats", "stats": '{"channels":[]}'},
        }
        async_to_sync(consumer.update)(event)
        consumer.send.assert_not_awaited()

    def test_update_forwards_channel_stats_for_admin(self):
        consumer = self._consumer(_user(user_level=User.UserLevel.ADMIN))
        event = {
            "type": "update",
            "data": {"type": "channel_stats", "stats": '{"channels":[]}'},
        }
        async_to_sync(consumer.update)(event)
        consumer.send.assert_awaited_once()
        sent = consumer.send.await_args.kwargs["text_data"]
        self.assertIn("channel_stats", sent)

    def test_update_forwards_non_sensitive_for_standard_user(self):
        consumer = self._consumer(_user(user_level=User.UserLevel.STANDARD))
        event = {
            "type": "update",
            "data": {"type": "epg_refresh", "success": True},
        }
        async_to_sync(consumer.update)(event)
        consumer.send.assert_awaited_once()


class ConsumerM3UProfileTestReceiveTests(SimpleTestCase):
    def _consumer(self, user):
        consumer = MyWebSocketConsumer()
        consumer.scope = {"user": user}
        consumer.send = AsyncMock()
        return consumer

    def test_m3u_profile_test_ignored_for_standard_user(self):
        consumer = self._consumer(_user(user_level=User.UserLevel.STANDARD))
        payload = {
            "type": "m3u_profile_test",
            "url": "http://example.com/a",
            "search": "a",
            "replace": "b",
        }
        async_to_sync(consumer.receive)(json.dumps(payload))
        consumer.send.assert_not_awaited()

    def test_m3u_profile_test_runs_for_admin(self):
        consumer = self._consumer(_user(user_level=User.UserLevel.ADMIN))
        payload = {
            "type": "m3u_profile_test",
            "url": "http://example.com/a",
            "search": "a",
            "replace": "b",
        }
        with patch(
            "apps.proxy.live_proxy.url_utils.transform_url",
            return_value="http://example.com/b",
        ) as mock_transform:
            async_to_sync(consumer.receive)(json.dumps(payload))
        mock_transform.assert_called_once()
        consumer.send.assert_awaited_once()
