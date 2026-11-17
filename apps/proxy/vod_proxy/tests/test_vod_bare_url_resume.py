"""A request without a session_id resumes the same viewer's own session.

Some clients seek by starting a new connection (a new FFmpeg process) from the
original URL, so the session redirect they were given never reaches it. That
request arrives while the previous connection is still closing and still holds
the only provider slot. These tests cover how the proxy matches such a request
to the viewer's earlier session, waits briefly for it to close, and never joins
a connection that is still running.
"""

from __future__ import annotations

import fnmatch
import re
from unittest.mock import MagicMock, patch
from uuid import uuid4

from django.test import SimpleTestCase, TestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.accounts.models import User
from apps.m3u.models import M3UAccount
from apps.proxy.vod_proxy.multi_worker_connection_manager import (
    ANONYMOUS_USER_ID,
    MultiWorkerVODConnectionManager,
    SessionMatch,
    get_vod_client_stop_key,
)
from apps.proxy.vod_proxy.tests.test_vod_lock_contention import (
    LockAwareFakeRedis,
    _clear_script_cache,
    _import_vod,
)
from apps.proxy.vod_proxy.utils import UNKNOWN_CLIENT, get_client_info
from apps.vod.models import M3UMovieRelation, Movie

MANAGER = "apps.proxy.vod_proxy.multi_worker_connection_manager"

CLIENT_IP = "203.0.113.50"
CLIENT_UA = "Channels/1.0 (Android)"
SESSION_A = "vod_1793756721076_5915"
# A second session id in the shape the proxy mints, for tests that need two.
SESSION_B = "vod_1793756721099_1111"


class FakeSessionRedis(LockAwareFakeRedis):
    """LockAwareFakeRedis plus the commands the session scan and stop signal use."""

    def __init__(self):
        super().__init__()
        self.ttls = {}

    def scan(self, cursor, match=None, count=100):
        with self._lock:
            keys = [k for k in self._hashes if fnmatch.fnmatch(k, match or "*")]
        return 0, keys

    def scan_iter(self, match=None, count=None):
        # Stream-limit counting scans with scan_iter. One pass is enough:
        # scan() above already returns every matching hash.
        _cursor, keys = self.scan(0, match=match, count=count or 100)
        yield from keys

    def hmget(self, key, *fields):
        with self._lock:
            stored = self._hashes.get(key, {})
            return [stored.get(field) for field in fields]

    def setex(self, key, ttl, value):
        self.ttls[key] = ttl
        return self.set(key, value)


def make_manager(redis):
    manager = MultiWorkerVODConnectionManager.__new__(MultiWorkerVODConnectionManager)
    manager.redis_client = redis
    manager.worker_id = "test-worker"
    return manager


def seed_session(
    redis,
    session_id,
    *,
    content_uuid,
    active_streams=0,
    user_id=ANONYMOUS_USER_ID,
    client_ip=CLIENT_IP,
    client_user_agent=CLIENT_UA,
    profile_id=1,
    utc_start=None,
    utc_end=None,
    offset=None,
    last_activity=None,
):
    """Store a session the way the connection manager does."""
    RedisBackedVODConnection, SerializableConnectionState = _import_vod()
    state = SerializableConnectionState(
        session_id=session_id,
        stream_url="http://provider.example/movie.mkv",
        headers={},
        m3u_profile_id=profile_id,
        content_obj_type="movie",
        content_uuid=content_uuid,
        client_ip=client_ip,
        client_user_agent=client_user_agent,
        utc_start=utc_start,
        utc_end=utc_end,
        offset=offset,
        user_id=user_id,
    )
    state.active_streams = active_streams
    if last_activity is not None:
        state.last_activity = last_activity
    assert RedisBackedVODConnection(session_id, redis)._save_connection_state(
        state, include_active_streams=True
    )


def close_stream(redis, session_id):
    """End the one running stream of a session, as its client closing would."""
    RedisBackedVODConnection, _ = _import_vod()
    RedisBackedVODConnection(session_id, redis).decrement_active_streams_and_check()


class MatchingSessionTests(SimpleTestCase):
    CONTENT = "movie-1"

    def setUp(self):
        _clear_script_cache()
        self.redis = FakeSessionRedis()
        self.manager = make_manager(self.redis)

    def seed(self, session_id, **kwargs):
        kwargs.setdefault("content_uuid", self.CONTENT)
        seed_session(self.redis, session_id, **kwargs)

    def find_all(self, *, user_id=ANONYMOUS_USER_ID, include_active=False, **overrides):
        request = {
            "content_type": "movie",
            "content_uuid": self.CONTENT,
            "client_ip": CLIENT_IP,
            "client_user_agent": CLIENT_UA,
        }
        request.update(overrides)
        return self.manager.find_matching_sessions(
            user_id=user_id, include_active=include_active, **request
        )

    def find(self, **kwargs):
        """The best match, or None."""
        matches = self.find_all(**kwargs)
        return matches[0] if matches else None

    def test_the_user_must_match(self):
        self.seed("vod_a", user_id="7")

        self.assertEqual(self.find(user_id="7"), SessionMatch("vod_a", False))
        self.assertIsNone(self.find(user_id="8"))
        self.assertIsNone(self.find(user_id=ANONYMOUS_USER_ID))

    def test_an_anonymous_viewer_only_matches_an_anonymous_session(self):
        self.seed("vod_a")

        self.assertEqual(self.find(), SessionMatch("vod_a", False))
        self.assertIsNone(self.find(user_id="7"))

    def test_other_content_is_ignored(self):
        self.seed("vod_a", content_uuid="another-movie")

        self.assertIsNone(self.find())

    def test_a_running_session_is_only_found_when_asked_for(self):
        self.seed("vod_a", active_streams=1)

        self.assertIsNone(self.find())
        self.assertEqual(self.find(include_active=True), SessionMatch("vod_a", True))

    def test_a_running_session_must_match_the_whole_fingerprint(self):
        """Another viewer's live stream is never taken for this viewer's."""
        for field, value in (
            ("client_user_agent", "OtherPlayer/2.0"),
            ("client_ip", "198.51.100.7"),
        ):
            with self.subTest(different=field):
                self.redis._hashes.clear()
                self.seed("vod_a", active_streams=1, **{field: value})

                self.assertIsNone(self.find(include_active=True))

    def test_an_idle_session_also_requires_address_and_user_agent(self):
        """Content alone is not enough: the settle window must not hand one
        viewer's idle session to another on the same title."""
        for field, value in (
            ("client_user_agent", "OtherPlayer/2.0"),
            ("client_ip", "198.51.100.7"),
        ):
            with self.subTest(different=field):
                self.redis._hashes.clear()
                self.seed("vod_a", **{field: value})

                self.assertIsNone(self.find())

    WINDOW = {
        "utc_start": "2026-11-07T20:00:00Z",
        "utc_end": "2026-11-07T21:00:00Z",
        "offset": "300",
    }
    OTHER_WINDOW = {
        "utc_start": "2026-11-07T22:00:00Z",
        "utc_end": "2026-11-07T23:00:00Z",
        "offset": "600",
    }

    def test_every_timeshift_field_must_match(self):
        """A session opened for one window is not the session for another."""
        for field in self.WINDOW:
            for stored, asked in (
                (self.WINDOW, {**self.WINDOW, field: self.OTHER_WINDOW[field]}),
                ({}, {field: self.WINDOW[field]}),
            ):
                for active in (0, 1):
                    with self.subTest(field=field, stored=bool(stored), active=active):
                        self.redis._hashes.clear()
                        self.seed("vod_a", active_streams=active, **stored)

                        self.assertIsNone(self.find(include_active=True, **asked))

    def test_an_identical_timeshift_window_matches(self):
        self.seed("vod_a", **self.WINDOW)

        self.assertEqual(self.find(**self.WINDOW), SessionMatch("vod_a", False))

    def test_an_idle_session_is_listed_before_a_running_one(self):
        """An idle session holds no provider slot and no client, so it is the
        one to take, however recently the running stream was refreshed."""
        self.seed("vod_idle", last_activity=100.0)
        self.seed("vod_running", active_streams=1, last_activity=200.0)

        self.assertEqual(
            self.find_all(include_active=True),
            [SessionMatch("vod_idle", False), SessionMatch("vod_running", True)],
        )

    def test_the_most_recent_session_is_listed_first_among_the_same_kind(self):
        self.seed("vod_old_idle", last_activity=100.0)
        self.seed("vod_new_idle", last_activity=200.0)
        self.assertEqual(
            self.find_all(),
            [SessionMatch("vod_new_idle", False), SessionMatch("vod_old_idle", False)],
        )

        self.redis._hashes.clear()
        self.seed("vod_old_active", active_streams=1, last_activity=100.0)
        self.seed("vod_new_active", active_streams=1, last_activity=200.0)
        self.assertEqual(
            self.find_all(include_active=True),
            [
                SessionMatch("vod_new_active", True),
                SessionMatch("vod_old_active", True),
            ],
        )

    def test_running_sessions_are_left_out_unless_asked_for(self):
        self.seed("vod_idle")
        self.seed("vod_running", active_streams=1)

        self.assertEqual(self.find_all(), [SessionMatch("vod_idle", False)])

    def test_a_missing_client_identity_never_matches(self):
        """A request with no address or user agent stores ``UNKNOWN_CLIENT``,
        so two such requests are not the same client."""
        for field in ("client_ip", "client_user_agent"):
            with self.subTest(field=field):
                self.redis._hashes.clear()
                self.seed("vod_a", **{field: UNKNOWN_CLIENT})

                self.assertIsNone(self.find(**{field: UNKNOWN_CLIENT}))

    def test_a_request_without_a_user_agent_is_never_matched(self):
        """Run the value the request really produces through the matcher, so
        the stored marker and the matcher cannot drift apart."""
        request = APIRequestFactory().get("/proxy/vod/movie/uuid/", REMOTE_ADDR=CLIENT_IP)
        self.assertNotIn("HTTP_USER_AGENT", request.META)
        client_ip, client_user_agent = get_client_info(request)
        self.assertEqual(client_user_agent, UNKNOWN_CLIENT)

        self.seed("vod_a", client_ip=client_ip, client_user_agent=client_user_agent)

        self.assertIsNone(
            self.find(client_ip=client_ip, client_user_agent=client_user_agent)
        )

    def test_the_idle_finder_never_returns_a_running_session(self):
        self.seed("vod_running", active_streams=1)

        self.assertIsNone(
            self.manager.find_matching_idle_session(
                content_type="movie",
                content_uuid=self.CONTENT,
                client_ip=CLIENT_IP,
                client_user_agent=CLIENT_UA,
                user_id=ANONYMOUS_USER_ID,
            )
        )


class WaitForAnySessionIdleTests(SimpleTestCase):
    def setUp(self):
        _clear_script_cache()
        self.redis = FakeSessionRedis()
        self.manager = make_manager(self.redis)
        self.stop_key = get_vod_client_stop_key(SESSION_A)
        self.stop_key_b = get_vod_client_stop_key(SESSION_B)

    def running(self, *session_ids):
        for session_id in session_ids or (SESSION_A,):
            seed_session(self.redis, session_id, content_uuid="movie-1", active_streams=1)

    def wait(self, session_ids, **kwargs):
        return self.manager.wait_for_any_session_idle(session_ids, **kwargs)

    def test_an_idle_session_returns_at_once_without_a_stop_signal(self):
        seed_session(self.redis, SESSION_A, content_uuid="movie-1")

        with patch(f"{MANAGER}.time.sleep") as sleep:
            self.assertEqual(self.wait([SESSION_A], signal_stop=True), SESSION_A)

        sleep.assert_not_called()
        self.assertNotIn(self.stop_key, self.redis._data)

    def test_returns_once_the_stream_closes_and_clears_its_stop_signal(self):
        self.running()
        seen = {}

        def client_closes(_seconds):
            seen["stop_while_waiting"] = self.stop_key in self.redis._data
            close_stream(self.redis, SESSION_A)

        with patch(f"{MANAGER}.time.sleep", side_effect=client_closes):
            self.assertEqual(self.wait([SESSION_A], signal_stop=True), SESSION_A)

        self.assertTrue(seen["stop_while_waiting"])
        self.assertNotIn(self.stop_key, self.redis._data)

    def test_a_stream_that_stays_open_times_out_with_a_short_lived_stop_signal(self):
        self.running()

        with patch(f"{MANAGER}.SESSION_SETTLE_SECONDS", 0.05), \
             patch(f"{MANAGER}._SETTLE_POLL_SECONDS", 0.01):
            self.assertIsNone(self.wait([SESSION_A], signal_stop=True))

        self.assertIn(self.stop_key, self.redis._data)
        self.assertLessEqual(self.redis.ttls[self.stop_key], 10)

    def test_no_stop_signal_unless_requested(self):
        self.running()

        with patch(f"{MANAGER}.SESSION_SETTLE_SECONDS", 0.05), \
             patch(f"{MANAGER}._SETTLE_POLL_SECONDS", 0.01):
            self.assertIsNone(self.wait([SESSION_A]))

        self.assertNotIn(self.stop_key, self.redis._data)

    def test_whichever_session_closes_first_is_returned(self):
        """The previous connection is one of several running sessions and
        cannot be told apart, so all are watched, not just the first listed."""
        self.running(SESSION_A, SESSION_B)

        with patch(
            f"{MANAGER}.time.sleep",
            side_effect=lambda _seconds: close_stream(self.redis, SESSION_B),
        ):
            self.assertEqual(self.wait([SESSION_A, SESSION_B]), SESSION_B)

    def test_a_session_already_idle_among_running_ones_returns_at_once(self):
        self.running(SESSION_A)
        seed_session(self.redis, SESSION_B, content_uuid="movie-1")

        with patch(f"{MANAGER}.time.sleep") as sleep:
            self.assertEqual(self.wait([SESSION_A, SESSION_B]), SESSION_B)

        sleep.assert_not_called()

    def test_none_returned_when_every_session_stays_open(self):
        self.running(SESSION_A, SESSION_B)

        with patch(f"{MANAGER}.SESSION_SETTLE_SECONDS", 0.05), \
             patch(f"{MANAGER}._SETTLE_POLL_SECONDS", 0.01):
            self.assertIsNone(self.wait([SESSION_A, SESSION_B]))

    def test_only_the_session_that_closed_loses_its_stop_signal(self):
        """A stop signalled to a stream that is still running must still reach
        it, so only the key of the session that went idle is cleared."""
        self.running(SESSION_A, SESSION_B)

        with patch(
            f"{MANAGER}.time.sleep",
            side_effect=lambda _seconds: close_stream(self.redis, SESSION_A),
        ):
            self.assertEqual(
                self.wait([SESSION_A, SESSION_B], signal_stop=True), SESSION_A
            )

        self.assertNotIn(self.stop_key, self.redis._data)
        self.assertIn(self.stop_key_b, self.redis._data)


class StopSignalPollTests(TestCase):
    """A running stream notices a stop signal within a few chunks.

    The wait for a session to close depends on this: a stop that took hundreds
    of kilobytes to be noticed would outlast the wait at ordinary bitrates.
    """

    CHUNKS = 1000
    # Two stop-check intervals (32 chunks / 8 KiB = 256 KiB each). Well under a
    # second at ordinary bitrates and far fewer than the chunks between
    # activity refreshes.
    NOTICED_WITHIN_CHUNKS = 64

    def stream_with(self, *, stop_requested):
        _clear_script_cache()
        redis = FakeSessionRedis()
        manager = make_manager(redis)
        profile = M3UAccount.objects.create(name="stop-poll").profiles.get(is_default=True)
        redis.set(f"profile_connections:{profile.id}", 0)
        stop_key = get_vod_client_stop_key("vod_stop")
        if stop_requested:
            redis.set(stop_key, "true")

        content = MagicMock()
        content.uuid = "movie-stop"
        content.name = "Movie"
        request = MagicMock()
        request.META = {}
        upstream = MagicMock()
        upstream.iter_content.return_value = [b"x"] * self.CHUNKS
        upstream.headers = {}

        with patch.object(manager, "find_matching_idle_session", return_value=None), \
             patch.object(manager, "_check_and_reserve_profile_slot", return_value=True), \
             patch.object(manager, "_send_vod_event"), \
             patch(f"{MANAGER}.RedisBackedVODConnection.get_stream", return_value=upstream), \
             patch(
                 f"{MANAGER}.RedisBackedVODConnection.get_headers",
                 return_value={"content_type": "video/mp4"},
             ), \
             patch(f"{MANAGER}.Movie", new=type(content)), \
             patch(f"{MANAGER}.threading.Thread"):
            response = manager.stream_content_with_session(
                session_id="vod_stop",
                content_obj=content,
                stream_url="http://provider.example/movie.mp4",
                m3u_profile=profile,
                client_ip=CLIENT_IP,
                client_user_agent=CLIENT_UA,
                request=request,
            )
            chunks = list(response.streaming_content)

        return len(chunks), stop_key in redis._data

    def test_a_stop_signal_ends_the_stream_within_a_few_chunks(self):
        delivered, stop_left = self.stream_with(stop_requested=True)

        self.assertGreater(delivered, 0)
        self.assertLessEqual(delivered, self.NOTICED_WITHIN_CHUNKS)
        self.assertFalse(stop_left)

    def test_the_stream_runs_to_the_end_without_a_stop_signal(self):
        delivered, _stop_left = self.stream_with(stop_requested=False)

        self.assertEqual(delivered, self.CHUNKS)


class UrlSessionPreferredOverFingerprintMatchTests(TestCase):
    """A request that already carries a session_id must use that hash when it
    exists. Fingerprint matching only runs when the URL session is gone.
    """

    def setUp(self):
        _clear_script_cache()
        self.redis = FakeSessionRedis()
        self.manager = make_manager(self.redis)
        self.profile = M3UAccount.objects.create(
            name="url-session"
        ).profiles.get(is_default=True)
        self.redis.set(f"profile_connections:{self.profile.id}", 0)
        self.content = MagicMock()
        self.content.uuid = "movie-url"
        self.content.name = "Movie"
        self.request = MagicMock()
        self.request.META = {}
        upstream = MagicMock()
        upstream.iter_content.return_value = [b"x"]
        upstream.headers = {}
        self.upstream = upstream

    def stream(self, session_id, *, idle_match):
        with patch.object(
            self.manager, "find_matching_idle_session", return_value=idle_match
        ) as find, \
             patch.object(
                 self.manager, "_check_and_reserve_profile_slot", return_value=True
             ), \
             patch.object(self.manager, "_send_vod_event"), \
             patch(
                 f"{MANAGER}.RedisBackedVODConnection.get_stream",
                 return_value=self.upstream,
             ), \
             patch(
                 f"{MANAGER}.RedisBackedVODConnection.get_headers",
                 return_value={"content_type": "video/mp4"},
             ), \
             patch(f"{MANAGER}.Movie", new=type(self.content)), \
             patch(f"{MANAGER}.threading.Thread"):
            response = self.manager.stream_content_with_session(
                session_id=session_id,
                content_obj=self.content,
                stream_url="http://provider.example/movie.mp4",
                m3u_profile=self.profile,
                client_ip=CLIENT_IP,
                client_user_agent=CLIENT_UA,
                request=self.request,
            )
            list(response.streaming_content)
        return find

    def test_an_existing_url_session_is_used_without_matching(self):
        RedisBackedVODConnection, _ = _import_vod()
        seed_session(self.redis, SESSION_A, content_uuid="movie-url")
        seed_session(self.redis, "vod_other_idle", content_uuid="movie-url")

        find = self.stream(SESSION_A, idle_match="vod_other_idle")

        find.assert_not_called()
        self.assertTrue(
            self.redis.exists(f"vod_persistent_connection:{SESSION_A}")
        )
        self.assertEqual(
            RedisBackedVODConnection(
                "vod_other_idle", self.redis
            ).get_active_streams_count(),
            0,
            "a different idle session must not be reserved when the URL session exists",
        )

    def test_a_missing_url_session_adopts_a_fingerprint_match(self):
        RedisBackedVODConnection, _ = _import_vod()
        seed_session(self.redis, "vod_idle", content_uuid="movie-url")

        find = self.stream(SESSION_A, idle_match="vod_idle")

        find.assert_called_once()
        self.assertFalse(
            self.redis.exists(f"vod_persistent_connection:{SESSION_A}")
        )
        self.assertTrue(
            self.redis.exists("vod_persistent_connection:vod_idle")
        )
        self.assertEqual(
            RedisBackedVODConnection("vod_idle", self.redis).get_active_streams_count(),
            0,
        )

    def test_a_missing_url_session_with_no_match_creates_under_the_url_id(self):
        find = self.stream(SESSION_A, idle_match=None)

        find.assert_called_once()
        self.assertTrue(
            self.redis.exists(f"vod_persistent_connection:{SESSION_A}")
        )


class BareUrlResumeTests(TestCase):
    """stream_vod for a request that carries no session_id."""

    def setUp(self):
        _clear_script_cache()
        self.redis = FakeSessionRedis()
        self.factory = APIRequestFactory()

        account = M3UAccount.objects.create(
            name=f"resume-{uuid4().hex[:6]}",
            server_url="http://provider.example",
            username="user",
            password="pass",
            account_type=M3UAccount.Types.XC,
            is_active=True,
        )
        # The provider allows one connection, like the accounts this is about.
        self.profile = account.profiles.get(is_default=True)
        self.profile.max_streams = 1
        self.profile.save(update_fields=["max_streams"])
        self.counter_key = f"profile_connections:{self.profile.id}"
        self.movie = Movie.objects.create(name="Resume Movie")
        M3UMovieRelation.objects.create(
            m3u_account=account,
            movie=self.movie,
            stream_id="1905687",
            container_extension="mkv",
        )
        self.content_uuid = str(self.movie.uuid)
        self.stop_key = get_vod_client_stop_key(SESSION_A)

        self.manager = make_manager(self.redis)
        self.manager._send_vod_event = MagicMock()
        for active_patch in (
            patch("core.utils.RedisClient.get_client", return_value=self.redis),
            patch(
                "apps.proxy.vod_proxy.views.MultiWorkerVODConnectionManager.get_instance",
                return_value=self.manager,
            ),
            patch.object(
                self.manager,
                "_check_and_reserve_profile_slot",
                side_effect=self.reserve_provider_slot,
            ),
            patch("apps.proxy.vod_proxy.views.network_access_allowed", return_value=True),
            patch(
                "core.models.CoreSettings.is_default_stream_profile_redirect",
                return_value=False,
            ),
            patch(f"{MANAGER}.SESSION_SETTLE_SECONDS", 0.05),
            patch(f"{MANAGER}._SETTLE_POLL_SECONDS", 0.01),
        ):
            active_patch.start()
            self.addCleanup(active_patch.stop)

    def reserve_provider_slot(self, profile):
        """Take a provider slot the way the connection pool does: all or nothing."""
        if self.redis.incr(f"profile_connections:{profile.id}") > profile.max_streams:
            self.redis.decr(f"profile_connections:{profile.id}")
            return False
        return True

    def seed(self, session_id=SESSION_A, **kwargs):
        seed_session(
            self.redis,
            session_id,
            content_uuid=self.content_uuid,
            profile_id=self.profile.id,
            **kwargs,
        )

    def previous_connection_closes(self, _seconds=None):
        """The old stream ends and releases its provider slot, as teardown does."""
        close_stream(self.redis, SESSION_A)
        self.manager._decrement_profile_connections(self.profile.id)

    def follow_session_redirect(self, session_id):
        """Request the session URL a client was redirected to."""
        from apps.proxy.vod_proxy.views import stream_vod

        request = self.factory.get(
            f"/proxy/vod/movie/{self.content_uuid}/{session_id}",
            HTTP_USER_AGENT=CLIENT_UA,
            HTTP_RANGE="bytes=0-",
            REMOTE_ADDR=CLIENT_IP,
        )
        upstream = MagicMock()
        upstream.iter_content.return_value = [b"x"]
        upstream.headers = {}
        with patch(f"{MANAGER}.RedisBackedVODConnection.get_stream", return_value=upstream), \
             patch(
                 f"{MANAGER}.RedisBackedVODConnection.get_headers",
                 return_value={"content_type": "video/x-matroska"},
             ), \
             patch("apps.proxy.vod_proxy.views.close_old_connections"):
            return stream_vod(
                request,
                content_type="movie",
                content_id=self.content_uuid,
                session_id=session_id,
            )

    def open_without_session(self, *, user=None, ip=CLIENT_IP, user_agent=CLIENT_UA):
        from apps.proxy.vod_proxy.views import stream_vod

        request = self.factory.get(
            f"/proxy/vod/movie/{self.content_uuid}/",
            HTTP_USER_AGENT=user_agent,
            HTTP_RANGE="bytes=0-",
            REMOTE_ADDR=ip,
        )
        if user is not None:
            force_authenticate(request, user=user)
        return stream_vod(
            request,
            content_type="movie",
            content_id=self.content_uuid,
            session_id=None,
        )

    @staticmethod
    def session_redirected_to(response):
        assert response.status_code == 301, response.status_code
        return re.search(r"/(vod_\d+_\d+)/?$", response["Location"].rstrip("/")).group(1)

    def active_streams(self, session_id=SESSION_A):
        RedisBackedVODConnection, _ = _import_vod()
        return RedisBackedVODConnection(session_id, self.redis).get_active_streams_count()

    def test_an_idle_session_of_the_viewer_is_resumed_without_waiting(self):
        self.seed()

        with patch(f"{MANAGER}.time.sleep") as sleep:
            response = self.open_without_session()

        self.assertEqual(self.session_redirected_to(response), SESSION_A)
        sleep.assert_not_called()

    def test_an_idle_session_of_another_viewer_is_not_resumed(self):
        """The settle window after one viewer stops must not hand that session
        to someone else watching the same title."""
        other_user = User.objects.create_user(username=f"other-{uuid4().hex[:6]}", password="pass")
        cases = {
            "different user agent": {"user_agent": "OtherPlayer/2.0"},
            "different address": {"ip": "198.51.100.7"},
            "different user": {"user": other_user},
        }
        for name, request_overrides in cases.items():
            with self.subTest(name):
                self.redis._hashes.clear()
                self.seed()

                response = self.open_without_session(**request_overrides)

                self.assertNotEqual(self.session_redirected_to(response), SESSION_A)

    def test_a_running_session_that_closes_in_time_is_resumed(self):
        self.seed(active_streams=1)

        with patch(
            f"{MANAGER}.time.sleep",
            side_effect=lambda _seconds: close_stream(self.redis, SESSION_A),
        ):
            response = self.open_without_session()

        self.assertEqual(self.session_redirected_to(response), SESSION_A)
        self.assertNotIn(self.stop_key, self.redis._data)

    def test_a_running_session_that_stays_open_is_not_joined(self):
        self.seed(active_streams=1)

        response = self.open_without_session()

        self.assertNotEqual(self.session_redirected_to(response), SESSION_A)
        self.assertEqual(self.active_streams(), 1)

    def test_an_idle_session_is_resumed_without_waiting_on_a_running_one(self):
        """An idle session is free to take: it holds no slot and no client.
        It is taken at once, even when the running stream was refreshed more
        recently, and the running stream is left alone."""
        user = User.objects.create_user(
            username=f"limited-{uuid4().hex[:6]}", password="pass", stream_limit=1
        )
        self.seed(SESSION_A, active_streams=1, last_activity=200.0, user_id=str(user.id))
        self.seed(SESSION_B, last_activity=100.0, user_id=str(user.id))

        with patch(f"{MANAGER}.time.sleep") as sleep, patch(
            "apps.proxy.vod_proxy.views.user_limit_evicts_oldest_stream",
            return_value=True,
        ):
            response = self.open_without_session(user=user)

        sleep.assert_not_called()
        self.assertEqual(self.session_redirected_to(response), SESSION_B)
        self.assertEqual(self.active_streams(SESSION_A), 1)
        self.assertNotIn(self.stop_key, self.redis._data)

    def test_an_idle_scan_match_that_became_active_is_waited_on(self):
        """The scan can say idle while a concurrent request has already
        started a stream. Re-check Redis and wait instead of joining it."""
        self.seed(active_streams=1)
        stale_idle = [SessionMatch(SESSION_A, active=False)]

        with patch.object(
            self.manager, "find_matching_sessions", return_value=stale_idle
        ), patch(
            f"{MANAGER}.time.sleep",
            side_effect=lambda _seconds: close_stream(self.redis, SESSION_A),
        ) as sleep:
            response = self.open_without_session()

        sleep.assert_called()
        self.assertEqual(self.session_redirected_to(response), SESSION_A)

    def test_with_room_at_the_provider_the_idle_session_streams_beside_a_running_one(self):
        """Resuming the idle session needs a provider slot, and it has one: the
        slot the session released when its stream ended."""
        self.profile.max_streams = 2
        self.profile.save(update_fields=["max_streams"])
        self.seed(SESSION_A, active_streams=1, last_activity=200.0)
        self.seed(SESSION_B, last_activity=100.0)
        self.redis.set(self.counter_key, 1)

        redirect = self.open_without_session()
        resumed_session = self.session_redirected_to(redirect)
        response = self.follow_session_redirect(resumed_session)

        self.assertEqual(resumed_session, SESSION_B)
        self.assertEqual(response.status_code, 206)
        self.assertEqual(self.active_streams(SESSION_A), 1)
        self.assertEqual(self.active_streams(SESSION_B), 1)
        self.assertEqual(int(self.redis._data[self.counter_key]), 2)

    def test_whichever_running_session_closes_is_resumed(self):
        """Several running sessions match and the previous connection cannot be
        told apart, so all are watched. The one that closes is the one taken."""
        self.seed(SESSION_A, active_streams=1, last_activity=200.0)
        self.seed(SESSION_B, active_streams=1, last_activity=100.0)

        with patch(
            f"{MANAGER}.time.sleep",
            side_effect=lambda _seconds: close_stream(self.redis, SESSION_B),
        ):
            response = self.open_without_session()

        self.assertEqual(self.session_redirected_to(response), SESSION_B)
        self.assertEqual(self.active_streams(SESSION_A), 1)

    def test_no_running_session_is_joined_when_none_closes(self):
        self.seed(SESSION_A, active_streams=1)
        self.seed(SESSION_B, active_streams=1)

        response = self.open_without_session()

        self.assertNotIn(self.session_redirected_to(response), (SESSION_A, SESSION_B))
        self.assertEqual(self.active_streams(SESSION_A), 1)
        self.assertEqual(self.active_streams(SESSION_B), 1)

    def test_no_stream_is_told_to_stop_when_several_running_sessions_match(self):
        """One of them may belong to another device. The limits end the oldest
        stream when the new session starts, so none is stopped on a guess."""
        user = User.objects.create_user(
            username=f"limited-{uuid4().hex[:6]}", password="pass", stream_limit=1
        )
        self.seed(SESSION_A, active_streams=1, user_id=str(user.id))
        self.seed(SESSION_B, active_streams=1, user_id=str(user.id))
        stop_keys = {get_vod_client_stop_key(SESSION_A), get_vod_client_stop_key(SESSION_B)}
        stop_keys_while_waiting = []

        with patch(
            "apps.proxy.vod_proxy.views.user_limit_evicts_oldest_stream",
            return_value=True,
        ), patch(
            f"{MANAGER}.time.sleep",
            side_effect=lambda _seconds: stop_keys_while_waiting.append(
                stop_keys & set(self.redis._data)
            ),
        ):
            self.open_without_session(user=user)

        self.assertTrue(stop_keys_while_waiting)
        self.assertEqual(set().union(*stop_keys_while_waiting), set())

    def test_no_wait_when_the_running_session_is_not_an_exact_match(self):
        other_user = User.objects.create_user(username=f"other-{uuid4().hex[:6]}", password="pass")
        cases = {
            "different user agent": {"user_agent": "OtherPlayer/2.0"},
            "different address": {"ip": "198.51.100.7"},
            "different user": {"user": other_user},
        }
        for name, request_overrides in cases.items():
            with self.subTest(name), patch(f"{MANAGER}.time.sleep") as sleep:
                self.redis._hashes.clear()
                self.seed(active_streams=1)

                response = self.open_without_session(**request_overrides)

                self.assertNotEqual(self.session_redirected_to(response), SESSION_A)
                sleep.assert_not_called()

    def test_a_seek_by_a_new_connection_streams_within_the_provider_limit(self):
        """The client starts a new connection from the original URL while the
        old stream is still closing. It resumes the session and streams, with
        the one provider slot passing from the old stream to the new one."""
        self.seed(active_streams=1)
        self.redis.set(self.counter_key, 1)

        with patch(f"{MANAGER}.time.sleep", side_effect=self.previous_connection_closes):
            redirect = self.open_without_session()
        resumed_session = self.session_redirected_to(redirect)
        response = self.follow_session_redirect(resumed_session)

        self.assertEqual(resumed_session, SESSION_A)
        self.assertEqual(response.status_code, 206)
        self.assertEqual(self.active_streams(), 1)
        self.assertEqual(int(self.redis._data[self.counter_key]), 1)

    def test_the_provider_limit_still_holds_when_the_old_connection_never_closes(self):
        """A connection that stays open is a real second stream, so the new
        session is refused rather than the provider limit being exceeded."""
        self.seed(active_streams=1)
        self.redis.set(self.counter_key, 1)

        redirect = self.open_without_session()
        response = self.follow_session_redirect(self.session_redirected_to(redirect))

        self.assertEqual(response.status_code, 503)
        self.assertEqual(self.active_streams(), 1)
        self.assertEqual(int(self.redis._data[self.counter_key]), 1)

    def test_the_provider_limit_holds_with_a_running_stream_and_an_idle_leftover(self):
        """If another stream took the slot the idle session released, resuming
        it is refused. No second upstream connection is opened and the running
        stream keeps its slot."""
        self.seed(SESSION_A, active_streams=1, last_activity=100.0)
        self.seed(SESSION_B, last_activity=200.0)
        self.redis.set(self.counter_key, 1)

        redirect = self.open_without_session()
        response = self.follow_session_redirect(self.session_redirected_to(redirect))

        self.assertEqual(response.status_code, 429)
        self.assertEqual(self.active_streams(SESSION_A), 1)
        self.assertEqual(self.active_streams(SESSION_B), 0)
        self.assertEqual(int(self.redis._data[self.counter_key]), 1)

    def test_a_refused_attempt_is_followed_by_a_resume_once_the_old_connection_closes(self):
        """On a one-connection provider a refused attempt never leaves a second
        session behind, so the retry finds the original session and resumes it."""
        self.seed(SESSION_A, active_streams=1)
        self.redis.set(self.counter_key, 1)

        refused = self.follow_session_redirect(
            self.session_redirected_to(self.open_without_session())
        )
        self.assertEqual(refused.status_code, 503)
        self.assertEqual(
            [key for key in self.redis._hashes if key.startswith("vod_persistent_connection:")],
            [f"vod_persistent_connection:{SESSION_A}"],
        )

        self.previous_connection_closes()
        retry = self.open_without_session()
        resumed_session = self.session_redirected_to(retry)
        response = self.follow_session_redirect(resumed_session)

        self.assertEqual(resumed_session, SESSION_A)
        self.assertEqual(response.status_code, 206)
        self.assertEqual(self.active_streams(), 1)
        self.assertEqual(int(self.redis._data[self.counter_key]), 1)

    def test_the_running_stream_is_only_told_to_stop_when_limits_end_the_oldest(self):
        user = User.objects.create_user(
            username=f"limited-{uuid4().hex[:6]}", password="pass", stream_limit=1
        )
        for evicts in (True, False):
            with self.subTest(limits_end_the_oldest=evicts):
                self.redis._hashes.clear()
                self.redis._data.clear()
                self.seed(active_streams=1, user_id=str(user.id))
                stop_while_waiting = []

                with patch(
                    "apps.proxy.vod_proxy.views.user_limit_evicts_oldest_stream",
                    return_value=evicts,
                ), patch(
                    f"{MANAGER}.time.sleep",
                    side_effect=lambda _seconds: stop_while_waiting.append(
                        self.stop_key in self.redis._data
                    ),
                ):
                    self.open_without_session(user=user)

                self.assertTrue(stop_while_waiting)
                self.assertEqual(set(stop_while_waiting), {evicts})

    def test_an_idle_leftover_does_not_make_limits_stop_a_lone_running_match(self):
        """Idle settle hashes are not active streams. With room under the limit,
        a handoff wait must not tell the running stream to stop."""
        user = User.objects.create_user(
            username=f"limited-{uuid4().hex[:6]}", password="pass", stream_limit=2
        )
        self.seed(active_streams=1, user_id=str(user.id))
        seed_session(
            self.redis,
            SESSION_B,
            content_uuid=str(uuid4()),
            active_streams=0,
            user_id=str(user.id),
        )
        stop_while_waiting = []

        with patch(
            "apps.proxy.utils.CoreSettings.get_user_limits_settings",
            return_value={
                "terminate_on_limit_exceeded": True,
                "terminate_oldest": True,
                "ignore_same_channel_connections": False,
            },
        ), patch(
            f"{MANAGER}.time.sleep",
            side_effect=lambda _seconds: stop_while_waiting.append(
                self.stop_key in self.redis._data
            ),
        ):
            self.open_without_session(user=user)

        self.assertTrue(stop_while_waiting)
        self.assertEqual(set(stop_while_waiting), {False})
