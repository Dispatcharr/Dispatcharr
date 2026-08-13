"""Catch-up honors Redirect as the default stream profile like VOD."""

from contextlib import ExitStack
from unittest.mock import MagicMock, patch

from django.http import HttpResponseRedirect
from django.test import RequestFactory, SimpleTestCase

from apps.timeshift import views
from apps.timeshift.helpers import (
    TimeshiftCredentials,
    build_timeshift_redirect_url,
    client_timeshift_url_layout,
)
from apps.timeshift.tests.test_views import (
    _FakeRedis,
    _make_catchup_stream,
    _proxy_url,
    _seed_pool_session,
)


class ClientTimeshiftUrlLayoutTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_path_layout(self):
        request = self.factory.get("/timeshift/u/p/40/2026-06-08:17-00/8.ts")
        self.assertEqual(client_timeshift_url_layout(request), "path")

    def test_query_layout(self):
        request = self.factory.get(
            "/streaming/timeshift.php",
            {
                "username": "u",
                "password": "p",
                "stream": "8",
                "start": "2026-06-08:17-00",
                "duration": "40",
            },
        )
        self.assertEqual(client_timeshift_url_layout(request), "query")

    def test_native_catchup_defaults_to_path(self):
        request = self.factory.get(
            "/proxy/catchup/uuid",
            {"start": "2026-06-08:17-00"},
        )
        self.assertEqual(client_timeshift_url_layout(request), "path")


class BuildTimeshiftRedirectUrlTests(SimpleTestCase):
    def test_path_mirrors_format_b(self):
        creds = TimeshiftCredentials("http://provider.test", "pu", "pp")
        url = build_timeshift_redirect_url(
            creds, "22372", "2026-06-08:19-00", 45, "path",
        )
        self.assertEqual(
            url,
            "http://provider.test/timeshift/pu/pp/45/2026-06-08:19-00/22372.ts",
        )

    def test_query_mirrors_format_a(self):
        creds = TimeshiftCredentials("http://provider.test", "pu", "pp")
        url = build_timeshift_redirect_url(
            creds, "22372", "2026-06-08:19-00", 45, "query",
        )
        self.assertIn("/streaming/timeshift.php?", url)
        self.assertIn("stream=22372", url)
        self.assertIn("start=2026-06-08:19-00", url)
        self.assertIn("duration=45", url)


class CatchupRedirectViewTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def _enter_common(self, stack, *, is_redirect, stream=None, redis=None):
        stream = stream or _make_catchup_stream(provider_tz="UTC")
        channel_cls = stack.enter_context(patch.object(views, "Channel"))
        redis_cls = stack.enter_context(patch.object(views, "RedisClient"))
        stack.enter_context(
            patch.object(views, "_authenticate_user", return_value=MagicMock(id=1))
        )
        stack.enter_context(
            patch.object(views, "network_access_allowed", return_value=True)
        )
        stack.enter_context(
            patch.object(views, "_user_can_access_channel", return_value=True)
        )
        stack.enter_context(
            patch.object(views, "get_channel_catchup_streams", return_value=[stream])
        )
        stack.enter_context(
            patch.object(views, "resolve_catchup_duration", return_value=40)
        )
        stack.enter_context(
            patch.object(views, "parse_catchup_timestamp", return_value=True)
        )
        is_redirect_mock = stack.enter_context(
            patch(
                "core.models.CoreSettings.is_default_stream_profile_redirect",
                return_value=is_redirect,
            )
        )
        stack.enter_context(
            patch.object(
                views,
                "get_transformed_credentials",
                return_value=("http://provider.test", "pu", "pp"),
            )
        )
        stack.enter_context(
            patch(
                "apps.timeshift.views.pool_has_capacity_for_profile",
                return_value=True,
            )
        )
        redis_cls.get_client.return_value = redis if redis is not None else _FakeRedis()
        channel_cls.objects.get.return_value = MagicMock(id=8, name="Ch", logo_id=None)
        return channel_cls, redis_cls, stream, is_redirect_mock

    def test_redirect_on_path_hands_off_provider_url(self):
        request = self.factory.get(_proxy_url(session_id=None))
        with ExitStack() as stack:
            self._enter_common(stack, is_redirect=True)
            response = views.timeshift_proxy(
                request, "u", "p", "40", "2026-06-08:17-00", "8.ts",
            )

        self.assertIsInstance(response, HttpResponseRedirect)
        self.assertEqual(
            response["Location"],
            "http://provider.test/timeshift/pu/pp/40/2026-06-08:17-00/22372.ts",
        )

    def test_redirect_on_query_mirrors_query_layout(self):
        request = self.factory.get(
            "/streaming/timeshift.php",
            {
                "username": "u",
                "password": "p",
                "stream": "8",
                "start": "2026-06-08:17-00",
                "duration": "40",
            },
        )
        with ExitStack() as stack:
            self._enter_common(stack, is_redirect=True)
            response = views.timeshift_proxy_query(request)

        self.assertIsInstance(response, HttpResponseRedirect)
        self.assertIn("/streaming/timeshift.php?", response["Location"])
        self.assertIn("stream=22372", response["Location"])
        self.assertNotIn("session_id=", response["Location"])

    def test_redirect_off_still_mints_session(self):
        request = self.factory.get(_proxy_url(session_id=None))
        with ExitStack() as stack:
            self._enter_common(stack, is_redirect=False)
            response = views.timeshift_proxy(
                request, "u", "p", "40", "2026-06-08:17-00", "8.ts",
            )

        self.assertEqual(response.status_code, 301)
        self.assertIn("session_id=", response["Location"])

    def test_pool_match_skips_provider_redirect(self):
        existing = "existingbusy1"
        redis = _FakeRedis()
        _seed_pool_session(
            redis,
            session_id=existing,
            user_id=1,
            client_ip="127.0.0.1",
            client_user_agent="vlc-test",
            busy="1",
        )
        request = self.factory.get(
            _proxy_url(session_id=None),
            HTTP_USER_AGENT="vlc-test",
            REMOTE_ADDR="127.0.0.1",
        )
        ok = MagicMock(status_code=200)
        profile = MagicMock(id=31)
        descriptor = {"account_id": "1", "stream_id": "111", "profile_id": "31"}
        with ExitStack() as stack:
            self._enter_common(stack, is_redirect=True, redis=redis)
            stack.enter_context(
                patch.object(views, "check_user_stream_limits", return_value=True)
            )
            stack.enter_context(
                patch.object(
                    views,
                    "_try_reacquire_idle_pool",
                    return_value=(descriptor, profile),
                )
            )
            stack.enter_context(
                patch.object(views, "_stream_reused_session", return_value=ok)
            )
            select_mock = stack.enter_context(
                patch.object(views, "_select_catchup_redirect_url")
            )
            response = views.timeshift_proxy(
                request, "u", "p", "40", "2026-06-08:17-00", "8.ts",
            )

        self.assertIs(response, ok)
        select_mock.assert_not_called()

    def test_existing_session_skips_redirect_decision(self):
        request = self.factory.get(_proxy_url(session_id="sess123"))
        ok = MagicMock(status_code=200)
        with ExitStack() as stack:
            _, _, _, is_redirect_mock = self._enter_common(stack, is_redirect=True)
            stack.enter_context(
                patch.object(views, "check_user_stream_limits", return_value=True)
            )
            stack.enter_context(
                patch.object(views, "_get_pool_entry", return_value=None)
            )
            stack.enter_context(
                patch.object(views, "_find_matching_pool_session", return_value=None)
            )
            stack.enter_context(
                patch.object(views, "reserve_profile_slot", return_value=(True, 1, None))
            )
            stack.enter_context(
                patch.object(views, "_create_pool_session", return_value=True)
            )
            stack.enter_context(
                patch.object(views, "_make_release_once", return_value=lambda: None)
            )
            stack.enter_context(
                patch.object(views, "_attempt_timeshift_stream", return_value=ok)
            )
            response = views.timeshift_proxy(
                request, "u", "p", "40", "2026-06-08:17-00", "8.ts",
            )

        self.assertIs(response, ok)
        is_redirect_mock.assert_not_called()

    def test_redirect_returns_503_when_no_capacity(self):
        request = self.factory.get(_proxy_url(session_id=None))
        with ExitStack() as stack:
            self._enter_common(stack, is_redirect=True)
            stack.enter_context(
                patch(
                    "apps.timeshift.views.pool_has_capacity_for_profile",
                    return_value=False,
                )
            )
            response = views.timeshift_proxy(
                request, "u", "p", "40", "2026-06-08:17-00", "8.ts",
            )

        self.assertEqual(response.status_code, 503)
