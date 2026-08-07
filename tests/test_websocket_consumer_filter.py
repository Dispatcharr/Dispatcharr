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
    user_is_admin,
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

    def test_admin_only_system_notification_blocked_for_standard_user(self):
        user = _user(user_level=User.UserLevel.STANDARD)
        self.assertFalse(
            user_may_receive_update(
                user,
                {
                    "type": "system_notification",
                    "notification": {
                        "notification_key": "admin.only",
                        "admin_only": True,
                        "title": "Secret",
                    },
                },
            )
        )

    def test_public_system_notification_allowed_for_standard_user(self):
        user = _user(user_level=User.UserLevel.STANDARD)
        self.assertTrue(
            user_may_receive_update(
                user,
                {
                    "type": "system_notification",
                    "notification": {
                        "notification_key": "public.note",
                        "admin_only": False,
                        "title": "Hello",
                    },
                },
            )
        )

    def test_admin_only_system_notification_allowed_for_admin(self):
        user = _user(user_level=User.UserLevel.ADMIN)
        self.assertTrue(
            user_may_receive_update(
                user,
                {
                    "type": "system_notification",
                    "notification": {
                        "notification_key": "admin.only",
                        "admin_only": True,
                        "title": "Secret",
                    },
                },
            )
        )


class UserIsAdminTests(SimpleTestCase):
    def test_admin_user(self):
        self.assertTrue(user_is_admin(_user(user_level=User.UserLevel.ADMIN)))

    def test_standard_user(self):
        self.assertFalse(user_is_admin(_user(user_level=User.UserLevel.STANDARD)))

    def test_anonymous_or_missing(self):
        self.assertFalse(user_is_admin(None))
        self.assertFalse(
            user_is_admin(_user(authenticated=False, user_level=User.UserLevel.ADMIN))
        )


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

    def test_update_drops_admin_only_notification_for_standard_user(self):
        consumer = self._consumer(_user(user_level=User.UserLevel.STANDARD))
        event = {
            "type": "update",
            "data": {
                "type": "system_notification",
                "notification": {"admin_only": True, "title": "Secret"},
            },
        }
        async_to_sync(consumer.update)(event)
        consumer.send.assert_not_awaited()


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

    def test_m3u_profile_test_rejects_oversized_fields(self):
        """Oversized url/search/replace must not reach regex.sub or transform."""
        from dispatcharr.consumers import (
            _M3U_PROFILE_TEST_PATTERN_MAX_LEN,
            _M3U_PROFILE_TEST_URL_MAX_LEN,
        )

        consumer = self._consumer(_user(user_level=User.UserLevel.ADMIN))
        url = "http://example.com/" + ("x" * _M3U_PROFILE_TEST_URL_MAX_LEN)
        payload = {
            "type": "m3u_profile_test",
            "url": url,
            "search": "a" * (_M3U_PROFILE_TEST_PATTERN_MAX_LEN + 1),
            "replace": "b",
        }
        with patch(
            "apps.proxy.live_proxy.url_utils.transform_url"
        ) as mock_transform, patch(
            "dispatcharr.consumers.regex.sub"
        ) as mock_sub:
            async_to_sync(consumer.receive)(json.dumps(payload))
        mock_transform.assert_not_called()
        mock_sub.assert_not_called()
        consumer.send.assert_awaited_once()
        sent = json.loads(consumer.send.await_args.kwargs["text_data"])
        self.assertEqual(sent["data"]["type"], "m3u_profile_test")
        self.assertEqual(
            sent["data"]["result"],
            url[:_M3U_PROFILE_TEST_URL_MAX_LEN],
        )

    def test_m3u_profile_test_catastrophic_regex_returns_quickly(self):
        """Alternation+star ReDoS must time out instead of blocking Daphne."""
        import time

        from dispatcharr.consumers import _M3U_PROFILE_TEST_REGEX_TIMEOUT

        consumer = self._consumer(_user(user_level=User.UserLevel.ADMIN))
        # (a|a)*$ backtracks exponentially on the regex engine; without a
        # timeout this stalls Daphne's shared event loop.
        payload = {
            "type": "m3u_profile_test",
            "url": ("a" * 28) + "!",
            "search": r"(a|a)*$",
            "replace": "x",
        }
        started = time.perf_counter()
        async_to_sync(consumer.receive)(json.dumps(payload))
        elapsed = time.perf_counter() - started
        # Two regex calls (preview + transform) each bounded by the timeout;
        # a generous multiple keeps this from being flaky under CI load
        # while still catching a regression back to unbounded backtracking.
        self.assertLess(
            elapsed,
            _M3U_PROFILE_TEST_REGEX_TIMEOUT * 20,
            f"m3u_profile_test blocked for {elapsed:.2f}s on catastrophic regex",
        )
        consumer.send.assert_awaited_once()
        sent = json.loads(consumer.send.await_args.kwargs["text_data"])
        # On timeout, preview and transform fall back to the original URL.
        self.assertEqual(sent["data"]["search_preview"], payload["url"])
        self.assertEqual(sent["data"]["result"], payload["url"])

    def test_m3u_profile_test_passes_timeout_to_preview_sub(self):
        from dispatcharr.consumers import _M3U_PROFILE_TEST_REGEX_TIMEOUT

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
        ), patch(
            "dispatcharr.consumers.regex.sub",
            return_value="http://example.com/<mark>a</mark>",
        ) as mock_sub:
            async_to_sync(consumer.receive)(json.dumps(payload))
        self.assertEqual(
            mock_sub.call_args.kwargs.get("timeout"),
            _M3U_PROFILE_TEST_REGEX_TIMEOUT,
        )

    def test_m3u_profile_test_normal_rewrite_still_works(self):
        consumer = self._consumer(_user(user_level=User.UserLevel.ADMIN))
        payload = {
            "type": "m3u_profile_test",
            "url": "http://example.com/live/user/pass/1.ts",
            "search": r"(.*)/(.*)/(.*)/(.*)$",
            "replace": r"$1/newuser/newpass/$4",
        }
        async_to_sync(consumer.receive)(json.dumps(payload))
        consumer.send.assert_awaited_once()
        sent = json.loads(consumer.send.await_args.kwargs["text_data"])
        self.assertIn("<mark>", sent["data"]["search_preview"])
        self.assertEqual(
            sent["data"]["result"],
            "http://example.com/live/newuser/newpass/1.ts",
        )