"""Tests for the timeshift proxy view, focused on upstream status mapping."""

import fnmatch
import time
from unittest.mock import MagicMock, patch

from django.test import RequestFactory, TestCase, override_settings

from apps.timeshift import views
from apps.proxy.utils import check_user_stream_limits as _check_user_stream_limits
from apps.proxy.utils import find_ts_sync as _find_ts_sync

TEST_SESSION_ID = "timeshift_testsession1"
TEST_MEDIA_ID = "timeshift_8_2026-06-08-17-00"


def _proxy_url(session_id=TEST_SESSION_ID):
    base = "/timeshift/u/p/8/2026-06-08:17-00/8.ts"
    return f"{base}?session_id={session_id}" if session_id else base


def _seed_pool_session(
    redis,
    session_id=TEST_SESSION_ID,
    media_id=TEST_MEDIA_ID,
    *,
    busy="1",
    serving_range=None,
    user_id=5,
    client_ip="1.2.3.4",
    client_user_agent="test-agent",
):
    views._create_pool_session(
        redis,
        session_id=session_id,
        media_id=media_id,
        user_id=user_id,
        client_ip=client_ip,
        client_user_agent=client_user_agent,
        account_id=1,
        profile_id=31,
        stream_id="111",
        provider_timestamp="2026-06-08:19-00",
    )
    if serving_range is not None:
        redis.hset(f"timeshift_pool:{session_id}", "serving_range", serving_range)
    if busy is not None:
        redis.hset(f"timeshift_pool:{session_id}", "busy", busy)


class FindTsSyncTests(TestCase):
    """Locate the first MPEG-TS sync chain so a leading HTML/PHP preamble
    can be skipped before the bytes reach the strict demuxer (ExoPlayer)."""

    def test_returns_zero_when_buffer_already_aligned(self):
        buf = b"\x47" + b"\x00" * 187 + b"\x47" + b"\x00" * 187 + b"\x47" + b"\x00" * 187
        self.assertEqual(_find_ts_sync(buf), 0)

    def test_returns_offset_of_first_chain_after_preamble(self):
        preamble = b"<br />\n<b>Warning</b>"
        aligned = b"\x47" + b"\x00" * 187 + b"\x47" + b"\x00" * 187 + b"\x47" + b"\x00" * 187
        self.assertEqual(_find_ts_sync(preamble + aligned), len(preamble))

    def test_returns_minus_one_when_no_chain_exists(self):
        # Three lone 0x47 bytes that are NOT spaced at 188 — must not be
        # mistaken for a sync chain.
        self.assertEqual(_find_ts_sync(b"\x47\x00\x00\x47\x00\x00\x47" * 50), -1)

    def test_returns_minus_one_for_short_buffer(self):
        self.assertEqual(_find_ts_sync(b"\x47" * 10), -1)



def _make_ts_payload(size=1024):
    """Build a minimal valid MPEG-TS byte sequence with 0x47 sync markers."""
    packet = b"\x47" + b"\x00" * 187
    return (packet * ((size // 188) + 1))[:size]


def _fake_upstream(status_code, *, content_type="video/mp2t", body=b""):
    resp = MagicMock()
    resp.status_code = status_code
    resp.headers = {"Content-Type": content_type}
    resp.iter_content = MagicMock(return_value=iter([body] if body else []))
    resp.close = MagicMock()
    # Simulate raw.read() for the TS sync peek in _stream_from_provider.
    # For 200 responses, return valid TS bytes so the peek check passes.
    if status_code in (200, 206) and not body:
        ts_peek = _make_ts_payload()
        resp.raw = MagicMock()
        resp.raw.read = MagicMock(return_value=ts_peek)
    elif status_code in (200, 206):
        resp.raw = MagicMock()
        resp.raw.read = MagicMock(return_value=body)
    return resp


class StreamFromProviderStatusMappingTests(TestCase):
    """`_stream_from_provider` must translate upstream HTTP status codes into
    semantically correct Django responses so downstream IPTV clients react
    the right way (notably: stop retrying on 404)."""

    def setUp(self):
        self.factory = RequestFactory()
        self.kwargs = dict(
            candidate_urls=[
                "http://example.test/streaming/timeshift.php?stream=1&start=2026-05-12:17-00",
                "http://example.test/streaming/timeshift.php?stream=1&start=2026-05-12 17:00:00",
                "http://example.test/timeshift/u/p/60/2026-05-12:17-00/1.ts",
            ],
            user_agent="test-agent",
            range_header=None,
            virtual_channel_id="timeshift_1_2026-05-12-17-00_1",
            client_id="timeshift_test123",
            client_ip="127.0.0.1",
            user=None,
            channel_display_name="Test",
            timestamp_utc="2026-05-12:17-00",
            channel_logo_id=None,
            m3u_profile_id=None,
            debug=False,
        )

    @patch.object(views, "_open_upstream")
    def test_all_candidates_404_returns_404(self, mocked_open):
        mocked_open.return_value = _fake_upstream(404)
        response = views._stream_from_provider(**self.kwargs)
        self.assertEqual(response.status_code, 404)
        # Every candidate is attempted before giving up.
        self.assertEqual(mocked_open.call_count, 3)

    @patch.object(views, "_open_upstream")
    def test_upstream_403_short_circuits_loop(self, mocked_open):
        # 403 is decisive (auth) — no retry of further candidates.
        mocked_open.return_value = _fake_upstream(403)
        response = views._stream_from_provider(**self.kwargs)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(mocked_open.call_count, 1)

    @patch.object(views, "_open_upstream")
    def test_upstream_302_short_circuits_loop(self, mocked_open):
        # Any 3xx is decisive: for XC providers a 302 is the first sign of
        # an IP ban, so the cascade must STOP hammering immediately instead
        # of retrying other URL shapes (which escalates the ban).
        mocked_open.return_value = _fake_upstream(302)
        response = views._stream_from_provider(**self.kwargs)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(mocked_open.call_count, 1)

    @patch.object(views, "_open_upstream")
    def test_upstream_500_continues_to_next_candidate(self, mocked_open):
        # A 5xx is format-specific on many XC servers (PHP fatal with
        # display_errors off turns an "Undefined array key" warning into a
        # hard 500), so the cascade must keep trying — the next timestamp
        # shape often succeeds.  Regression: providers that 500 on the first
        # shape used to fail outright because the loop short-circuited.
        mocked_open.side_effect = [
            _fake_upstream(500),
            _fake_upstream(200, body=_make_ts_payload()),
        ]
        with patch.object(views, "RedisClient"), \
             patch.object(views, "_register_stats_client"), \
             patch.object(views, "_unregister_stats_client"):
            response = views._stream_from_provider(**self.kwargs)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(mocked_open.call_count, 2)

    @patch.object(views, "_open_upstream")
    def test_all_candidates_500_returns_error(self, mocked_open):
        # Every shape 500s → all candidates attempted, then a clean error.
        mocked_open.return_value = _fake_upstream(500)
        response = views._stream_from_provider(**self.kwargs)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(mocked_open.call_count, 3)

    @patch.object(views, "_open_upstream")
    def test_first_candidate_succeeds(self, mocked_open):
        mocked_open.side_effect = [_fake_upstream(200, body=_make_ts_payload())]
        with patch.object(views, "RedisClient"), \
             patch.object(views, "_register_stats_client"), \
             patch.object(views, "_unregister_stats_client"):
            response = views._stream_from_provider(**self.kwargs)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(mocked_open.call_count, 1)

    @patch.object(views, "_open_upstream")
    def test_second_candidate_succeeds_after_404(self, mocked_open):
        # Primary 404 → second candidate 200 → streams successfully.
        mocked_open.side_effect = [
            _fake_upstream(404),
            _fake_upstream(200, body=_make_ts_payload()),
        ]
        with patch.object(views, "RedisClient"), \
             patch.object(views, "_register_stats_client"), \
             patch.object(views, "_unregister_stats_client"):
            response = views._stream_from_provider(**self.kwargs)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(mocked_open.call_count, 2)

    @patch.object(views, "_open_upstream")
    def test_third_candidate_succeeds_after_400_then_404(self, mocked_open):
        mocked_open.side_effect = [
            _fake_upstream(400),
            _fake_upstream(404),
            _fake_upstream(200, body=_make_ts_payload()),
        ]
        with patch.object(views, "RedisClient"), \
             patch.object(views, "_register_stats_client"), \
             patch.object(views, "_unregister_stats_client"):
            response = views._stream_from_provider(**self.kwargs)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(mocked_open.call_count, 3)

    @override_settings(CACHES={
        "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}
    })
    @patch.object(views, "_open_upstream")
    def test_cache_promotes_winning_index_to_first(self, mocked_open):
        """Once a candidate succeeds for an account, the next request reorders
        the list so the cached winner is tried first — saving cascade
        overhead on fast-forward."""
        # locmem cache: isolates this test from the shared Redis-backed django
        # cache (which persists across runs and parallel test sessions).
        from django.core.cache import cache as django_cache
        django_cache.delete(views._FORMAT_CACHE_KEY.format(999))

        # First request: candidate index 1 wins after index 0 returns 404.
        mocked_open.side_effect = [
            _fake_upstream(404),
            _fake_upstream(200, body=_make_ts_payload()),
        ]
        kwargs = dict(self.kwargs, account_id=999)
        with patch.object(views, "RedisClient"), \
             patch.object(views, "_register_stats_client"), \
             patch.object(views, "_unregister_stats_client"):
            r1 = views._stream_from_provider(**kwargs)
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(mocked_open.call_count, 2)

        # Second request: cached winner (index 1) is tried first, succeeds
        # immediately — no cascade.
        mocked_open.reset_mock()
        mocked_open.side_effect = [_fake_upstream(200, body=_make_ts_payload())]
        with patch.object(views, "RedisClient"), \
             patch.object(views, "_register_stats_client"), \
             patch.object(views, "_unregister_stats_client"):
            r2 = views._stream_from_provider(**kwargs)
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(mocked_open.call_count, 1)
        # Confirm the URL used is the SQL-datetime candidate (index 1 in the
        # original list set up in setUp), not the dash-only one (index 0).
        self.assertIn("17:00:00", mocked_open.call_args_list[0][0][0])

    @patch.object(views, "_open_upstream")
    def test_php_error_200_cascades_to_next_candidate(self, mocked_open):
        """When the provider returns HTTP 200 but the body is PHP error text
        (no TS sync), the cascade should try the next candidate URL."""
        php_error = b'<br />\n<b>Warning</b>: Invalid argument supplied for foreach()'
        php_resp = _fake_upstream(200, body=php_error)
        php_resp.raw = MagicMock()
        php_resp.raw.read = MagicMock(return_value=php_error)

        ts_resp = _fake_upstream(200, body=_make_ts_payload())

        mocked_open.side_effect = [php_resp, ts_resp]
        with patch.object(views, "RedisClient"), \
             patch.object(views, "_register_stats_client"), \
             patch.object(views, "_unregister_stats_client"):
            response = views._stream_from_provider(**self.kwargs)
        self.assertEqual(response.status_code, 200)
        # PHP response was rejected, second candidate accepted
        self.assertEqual(mocked_open.call_count, 2)

    @patch.object(views, "_open_upstream")
    def test_416_range_not_satisfiable_passes_through(self, mocked_open):
        # A tail/seek probe past EOF must go back to the client verbatim,
        # never cascaded to other URL shapes (byte offsets are file-specific,
        # so cascading only multiplies upstream connections).
        resp = _fake_upstream(416)
        resp.headers = {"Content-Type": "video/mp2t", "Content-Range": "bytes */1000"}
        mocked_open.return_value = resp
        kwargs = dict(self.kwargs, range_header="bytes=999999-")
        response = views._stream_from_provider(**kwargs)
        self.assertEqual(response.status_code, 416)
        self.assertEqual(response["Content-Range"], "bytes */1000")
        self.assertTrue(getattr(response, "timeshift_passthrough", False))
        # No cascade: the first (and only) candidate decided the outcome.
        self.assertEqual(mocked_open.call_count, 1)

    @patch.object(views, "_open_upstream")
    def test_partial_206_to_range_request_accepted_mid_packet(self, mocked_open):
        # A 206 answering a Range request legitimately starts mid-TS-packet
        # (no 0x47 sync at offset 0). It must be served, not rejected as a
        # PHP error and cascaded across every URL shape and provider account.
        mid_packet = b"\x00" * 300
        self.assertEqual(_find_ts_sync(mid_packet), -1)
        resp = _fake_upstream(206, body=mid_packet)
        resp.raw = MagicMock()
        resp.raw.read = MagicMock(return_value=mid_packet)
        mocked_open.return_value = resp
        kwargs = dict(self.kwargs, range_header="bytes=1000-")
        with patch.object(views, "RedisClient"), \
             patch.object(views, "_register_stats_client"), \
             patch.object(views, "_unregister_stats_client"):
            response = views._stream_from_provider(**kwargs)
        self.assertEqual(response.status_code, 206)
        self.assertEqual(mocked_open.call_count, 1)

    @patch.object(views, "_open_upstream")
    def test_partial_206_html_error_still_rejected(self, mocked_open):
        # The mid-packet allowance is gated on content type: a 206 whose body
        # is an HTML/PHP error page must still be rejected and cascaded.
        html = b"<html><body>error</body></html>"
        bad = _fake_upstream(206, content_type="text/html", body=html)
        bad.raw = MagicMock()
        bad.raw.read = MagicMock(return_value=html)
        good = _fake_upstream(206, body=_make_ts_payload())
        mocked_open.side_effect = [bad, good]
        kwargs = dict(self.kwargs, range_header="bytes=0-")
        with patch.object(views, "RedisClient"), \
             patch.object(views, "_register_stats_client"), \
             patch.object(views, "_unregister_stats_client"):
            response = views._stream_from_provider(**kwargs)
        self.assertEqual(response.status_code, 206)
        self.assertEqual(mocked_open.call_count, 2)

    @patch.object(views, "_open_upstream")
    def test_206_without_range_header_still_requires_sync(self, mocked_open):
        # Without a Range header a 206 is unexpected; it must still pass the
        # TS-sync probe (the mid-packet allowance is range-only).
        mid_packet = b"\x00" * 300
        bad = _fake_upstream(206, body=mid_packet)
        bad.raw = MagicMock()
        bad.raw.read = MagicMock(return_value=mid_packet)
        good = _fake_upstream(206, body=_make_ts_payload())
        mocked_open.side_effect = [bad, good]
        with patch.object(views, "RedisClient"), \
             patch.object(views, "_register_stats_client"), \
             patch.object(views, "_unregister_stats_client"):
            response = views._stream_from_provider(**self.kwargs)
        self.assertEqual(response.status_code, 206)
        self.assertEqual(mocked_open.call_count, 2)


class RedactUrlTests(TestCase):
    """`_redact_url` is the guard that keeps XC credentials out of logs —
    both URL forms carry them (query params in format A, path segments in
    format B)."""

    def test_redacts_query_credentials(self):
        url = "http://example.test/streaming/timeshift.php?username=u&password=p&stream=1"
        self.assertEqual(views._redact_url(url), "http://example.test/...")

    def test_redacts_path_credentials(self):
        url = "http://example.test/timeshift/user/pass/60/2026-05-12:17-00/1.ts"
        self.assertEqual(views._redact_url(url), "http://example.test/...")

    def test_redacts_userinfo_credentials(self):
        url = "http://user:pass@example.test/timeshift/1.ts"
        self.assertEqual(views._redact_url(url), "http://example.test/...")

    def test_passes_through_non_urls(self):
        self.assertEqual(views._redact_url("not a url"), "not a url")
        self.assertIsNone(views._redact_url(None))


def _make_catchup_stream(provider_tz="Europe/Brussels", *, account_id=9,
                         stream_id="22372", account_type="XC", profile_id=31,
                         extra_profiles=()):
    """Build a mocked catch-up Stream with its own provider context.

    The default (tz-bearing) profile leads the active-profile list the view
    walks; ``extra_profiles`` appends alternate (non-default) profiles for
    capacity-walk tests.
    """
    profile = MagicMock()
    profile.id = profile_id
    profile.is_default = True
    profile.custom_properties = {"server_info": {"timezone": provider_tz}}
    m3u_account = MagicMock()
    m3u_account.account_type = account_type
    m3u_account.id = account_id
    m3u_account.profiles.filter.return_value = [profile, *extra_profiles]
    stream = MagicMock()
    stream.m3u_account = m3u_account
    stream.custom_properties = {"stream_id": stream_id} if stream_id else {}
    return stream


def _make_alt_profile(profile_id):
    """A non-default active profile for the capacity walk."""
    profile = MagicMock()
    profile.id = profile_id
    profile.is_default = False
    profile.custom_properties = {}
    return profile


class _FakeRedis:
    """Just enough of the redis-py surface for the idle-session pool: setex/get/
    delete plus a transactional pipeline doing GET+DEL, and the hash, set and
    lock primitives the pool entries rely on."""

    def __init__(self):
        self.store = {}

    def setex(self, key, ttl, value):
        self.store[key] = str(value)

    def set(self, key, value):
        self.store[key] = str(value)

    def get(self, key):
        return self.store.get(key)

    def delete(self, *keys):
        return sum(1 for k in keys if self.store.pop(k, None) is not None)

    def exists(self, key):
        return 1 if key in self.store else 0

    def pipeline(self, transaction=False):
        return _FakeRedisPipeline(self)

    # --- hash + lock surface for the session slot ---
    def hgetall(self, key):
        value = self.store.get(key)
        return dict(value) if isinstance(value, dict) else {}

    def hset(self, key, field=None, value=None, mapping=None, **kwargs):
        hash_value = self.store.get(key)
        if not isinstance(hash_value, dict):
            hash_value = {}
            self.store[key] = hash_value
        if field is not None and value is not None:
            hash_value[str(field)] = str(value)
        for f, v in (mapping or {}).items():
            hash_value[str(f)] = str(v)
        for f, v in kwargs.items():
            hash_value[str(f)] = str(v)
        return len(hash_value)

    def hincrby(self, key, field, amount=1):
        hash_value = self.store.get(key)
        if not isinstance(hash_value, dict):
            hash_value = {}
            self.store[key] = hash_value
        new_value = int(hash_value.get(field, 0)) + amount
        hash_value[field] = str(new_value)
        return new_value

    def hget(self, key, field):
        hash_value = self.store.get(key)
        return hash_value.get(field) if isinstance(hash_value, dict) else None

    def expire(self, key, ttl):
        return 1 if key in self.store else 0

    # --- set surface for the idle-session pool ---
    def sadd(self, key, *members):
        existing = self.store.get(key)
        if not isinstance(existing, set):
            existing = set()
            self.store[key] = existing
        before = len(existing)
        existing.update(str(m) for m in members)
        return len(existing) - before

    def srem(self, key, *members):
        existing = self.store.get(key)
        if not isinstance(existing, set):
            return 0
        removed = 0
        for member in members:
            if str(member) in existing:
                existing.discard(str(member))
                removed += 1
        return removed

    def smembers(self, key):
        existing = self.store.get(key)
        return set(existing) if isinstance(existing, set) else set()

    def scard(self, key):
        existing = self.store.get(key)
        return len(existing) if isinstance(existing, set) else 0

    def lock(self, name, timeout=None, blocking_timeout=None):
        return _FakeRedisLock()

    def scan(self, cursor=0, match=None, count=100):
        keys = sorted(
            k for k in self.store
            if match is None or fnmatch.fnmatch(k, match)
        )
        if cursor >= len(keys):
            return 0, []
        batch = keys[cursor:cursor + count]
        next_cursor = cursor + len(batch)
        if next_cursor >= len(keys):
            return 0, batch
        return next_cursor, batch


class _FakeRedisLock:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeRedisPipeline:
    def __init__(self, redis):
        self._redis = redis
        self._ops = []

    def get(self, key):
        self._ops.append(("get", key))

    def delete(self, key):
        self._ops.append(("delete", key))

    def execute(self):
        results = []
        for op, key in self._ops:
            if op == "get":
                results.append(self._redis.get(key))
            else:
                results.append(self._redis.delete(key))
        self._ops = []
        return results


def _fake_creds(acc, prof):
    """Distinguishable per-account credentials, mirroring what
    get_transformed_credentials returns for the reserved profile."""
    return (f"http://a{acc.id}.test", f"u{acc.id}", "p")


class TimeshiftProxyTimestampWiringTests(TestCase):
    """`timeshift_proxy` must convert the client's UTC timestamp to the
    serving provider's zone for the upstream URL, while keeping the ORIGINAL
    UTC timestamp for the EPG duration lookup — the only timezone conversion
    in the chain."""

    def setUp(self):
        self.factory = RequestFactory()

    def _call(self, timestamp, provider_tz="Europe/Brussels"):
        request = self.factory.get(f"/timeshift/u/p/8/{timestamp}/8.ts?session_id={TEST_SESSION_ID}")
        sentinel = MagicMock(status_code=200)
        with patch.object(views, "_authenticate_user", return_value=MagicMock()), \
             patch.object(views, "network_access_allowed", return_value=True), \
             patch.object(views, "Channel") as channel_cls, \
             patch.object(views, "_user_can_access_channel", return_value=True), \
             patch.object(views, "get_channel_catchup_streams",
                          return_value=[_make_catchup_stream(provider_tz)]), \
             patch.object(views, "get_programme_duration", return_value=40) as duration_mock, \
             patch.object(views, "build_timeshift_candidate_urls",
                          return_value=["http://example.test/x.ts"]) as build_mock, \
             patch.object(views, "check_user_stream_limits", return_value=True), \
             patch.object(views, "RedisClient") as redis_cls, \
             patch.object(views, "reserve_profile_slot", return_value=(True, 1, None)), \
             patch.object(views, "release_profile_slot"), \
             patch.object(views, "get_transformed_credentials", side_effect=_fake_creds), \
             patch.object(views, "get_user_active_connections", return_value=[]), \
             patch.object(views, "_stream_from_provider", return_value=sentinel) as stream_mock:
            redis_cls.get_client.return_value = _FakeRedis()
            channel_cls.objects.get.return_value = MagicMock(id=8, name="Test", logo_id=None)
            response = views.timeshift_proxy(request, "u", "p", "8", timestamp, "8.ts")
        return response, sentinel, build_mock, duration_mock, stream_mock

    def test_candidates_get_provider_local_timestamp(self):
        # June → CEST: 17:00 UTC must reach the URL builder as 19:00 Brussels.
        response, sentinel, build_mock, duration_mock, _ = self._call("2026-06-08:17-00")
        self.assertIs(response, sentinel)
        self.assertEqual(build_mock.call_args[0][2], "2026-06-08:19-00")

    def test_duration_lookup_keeps_original_utc_timestamp(self):
        # The EPG is stored in UTC — the duration lookup must NOT receive the
        # provider-converted value.
        _, _, _, duration_mock, _ = self._call("2026-06-08:17-00")
        self.assertEqual(duration_mock.call_args[0][1], "2026-06-08:17-00")

    def test_utc_provider_passes_timestamp_unchanged(self):
        _, _, build_mock, _, _ = self._call("2026-06-08:17-00", provider_tz="UTC")
        self.assertEqual(build_mock.call_args[0][2], "2026-06-08:17-00")

    def test_colon_seconds_timestamp_accepted(self):
        response, sentinel, build_mock, duration_mock, _ = self._call(
            "2026-06-23:04:00:00"
        )
        self.assertIs(response, sentinel)
        self.assertEqual(duration_mock.call_args[0][1], "2026-06-23:04:00:00")

    def test_invalid_timestamp_rejected_before_upstream(self):
        request = self.factory.get("/timeshift/u/p/8/garbage/8.ts")
        with patch.object(views, "_authenticate_user", return_value=MagicMock()), \
             patch.object(views, "network_access_allowed", return_value=True), \
             patch.object(views, "Channel") as channel_cls, \
             patch.object(views, "_user_can_access_channel", return_value=True), \
             patch.object(views, "get_channel_catchup_streams") as catchup_mock, \
             patch.object(views, "_stream_from_provider") as stream_mock:
            channel_cls.objects.get.return_value = MagicMock(id=8)
            response = views.timeshift_proxy(request, "u", "p", "8", "garbage", "8.ts")
        self.assertEqual(response.status_code, 400)
        catchup_mock.assert_not_called()
        stream_mock.assert_not_called()

    def test_network_access_denied_returns_403(self):
        # Same network gate as other XC API endpoints (player_api, xmltv, etc.).
        request = self.factory.get(_proxy_url())
        with patch.object(views, "_authenticate_user", return_value=MagicMock()), \
             patch.object(views, "network_access_allowed", return_value=False) as gate, \
             patch.object(views, "Channel") as channel_cls, \
             patch.object(views, "_stream_from_provider") as stream_mock:
            response = views.timeshift_proxy(
                request, "u", "p", "8", "2026-06-08:17-00", "8.ts"
            )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(gate.call_args[0][1], "XC_API")
        channel_cls.objects.get.assert_not_called()
        stream_mock.assert_not_called()


class TimeshiftProxyFailoverTests(TestCase):
    """When the first catch-up stream's provider cannot serve the archive,
    the proxy must fail over to the channel's next catch-up stream — each
    attempt with its own provider context."""

    def setUp(self):
        self.factory = RequestFactory()

    def _call(self, streams, provider_responses):
        request = self.factory.get(_proxy_url())
        with patch.object(views, "_authenticate_user", return_value=MagicMock()), \
             patch.object(views, "network_access_allowed", return_value=True), \
             patch.object(views, "Channel") as channel_cls, \
             patch.object(views, "_user_can_access_channel", return_value=True), \
             patch.object(views, "get_channel_catchup_streams", return_value=streams), \
             patch.object(views, "get_programme_duration", return_value=40), \
             patch.object(views, "build_timeshift_candidate_urls",
                          return_value=["http://example.test/x.ts"]) as build_mock, \
             patch.object(views, "check_user_stream_limits", return_value=True) as limits_mock, \
             patch.object(views, "RedisClient") as redis_cls, \
             patch.object(views, "reserve_profile_slot", return_value=(True, 1, None)), \
             patch.object(views, "release_profile_slot"), \
             patch.object(views, "get_transformed_credentials",
                          side_effect=_fake_creds) as creds_mock, \
             patch.object(views, "get_user_active_connections", return_value=[]), \
             patch.object(views, "_stream_from_provider",
                          side_effect=provider_responses) as stream_mock:
            redis_cls.get_client.return_value = _FakeRedis()
            channel_cls.objects.get.return_value = MagicMock(id=8, name="Test", logo_id=None)
            response = views.timeshift_proxy(
                request, "u", "p", "8", "2026-06-08:17-00", "8.ts"
            )
        self.creds_mock = creds_mock
        return response, stream_mock, build_mock, limits_mock

    def test_second_stream_serves_after_first_fails(self):
        streams = [
            _make_catchup_stream(account_id=1, stream_id="111"),
            _make_catchup_stream(account_id=2, stream_id="222"),
        ]
        ok = MagicMock(status_code=200)
        response, stream_mock, build_mock, _ = self._call(
            streams, [MagicMock(status_code=404), ok]
        )
        self.assertIs(response, ok)
        self.assertEqual(stream_mock.call_count, 2)
        # Each attempt used its own provider context: credentials resolved per
        # account/profile (via get_transformed_credentials) and its stream id.
        self.assertEqual(
            [c.args[0] for c in build_mock.call_args_list],
            [("http://a1.test", "u1", "p"), ("http://a2.test", "u2", "p")],
        )
        self.assertEqual(
            [c.args[0] for c in self.creds_mock.call_args_list],
            [streams[0].m3u_account, streams[1].m3u_account],
        )
        self.assertEqual(
            [c.args[1] for c in build_mock.call_args_list], ["111", "222"]
        )
        self.assertEqual(
            [c.kwargs["account_id"] for c in stream_mock.call_args_list], [1, 2]
        )

    def test_all_streams_fail_returns_last_failure(self):
        streams = [
            _make_catchup_stream(account_id=1, stream_id="111"),
            _make_catchup_stream(account_id=2, stream_id="222"),
        ]
        last = MagicMock(status_code=404)
        response, stream_mock, _, _ = self._call(
            streams, [MagicMock(status_code=400), last]
        )
        self.assertIs(response, last)
        self.assertEqual(stream_mock.call_count, 2)

    def test_non_xc_and_missing_stream_id_are_skipped(self):
        streams = [
            _make_catchup_stream(account_id=1, account_type="M3U"),
            _make_catchup_stream(account_id=2, stream_id=None),
            _make_catchup_stream(account_id=3, stream_id="333"),
        ]
        ok = MagicMock(status_code=200)
        response, stream_mock, _, _ = self._call(streams, [ok])
        self.assertIs(response, ok)
        # Only the eligible third stream produced an upstream attempt.
        self.assertEqual(stream_mock.call_count, 1)
        self.assertEqual(stream_mock.call_args.kwargs["account_id"], 3)

    def test_stream_limits_checked_once_for_the_request(self):
        streams = [
            _make_catchup_stream(account_id=1, stream_id="111"),
            _make_catchup_stream(account_id=2, stream_id="222"),
        ]
        _, _, _, limits_mock = self._call(
            streams, [MagicMock(status_code=404), MagicMock(status_code=200)]
        )
        self.assertEqual(limits_mock.call_count, 1)

    def test_passthrough_is_not_failed_over_to_other_accounts(self):
        # A terminal range answer (e.g. 416 past EOF) must be returned as-is;
        # the loop must NOT try the next account, whose byte offsets would not
        # match this file and which would just burn another provider slot.
        streams = [
            _make_catchup_stream(account_id=1, stream_id="111"),
            _make_catchup_stream(account_id=2, stream_id="222"),
        ]
        passthrough = MagicMock(status_code=416)
        passthrough.timeshift_passthrough = True
        response, stream_mock, _, _ = self._call(streams, [passthrough])
        self.assertIs(response, passthrough)
        self.assertEqual(stream_mock.call_count, 1)


class _ProxyLoopTestMixin:
    """Shared driver for tests exercising the failover loop end to end —
    pool reservation, credential resolution and Redis are all controlled."""

    def setUp(self):
        self.factory = RequestFactory()

    def _call(self, streams, provider_responses, limits=True, reserve_results=None,
              build_side_effect=None):
        request = self.factory.get(_proxy_url())
        self.fake_redis = _FakeRedis()
        reserve_kwargs = (
            {"side_effect": reserve_results}
            if reserve_results is not None
            else {"return_value": (True, 1, None)}
        )
        build_kwargs = (
            {"side_effect": build_side_effect}
            if build_side_effect is not None
            else {"return_value": ["http://example.test/x.ts"]}
        )
        with patch.object(views, "_authenticate_user", return_value=MagicMock()), \
             patch.object(views, "network_access_allowed", return_value=True), \
             patch.object(views, "Channel") as channel_cls, \
             patch.object(views, "_user_can_access_channel", return_value=True), \
             patch.object(views, "get_channel_catchup_streams", return_value=streams), \
             patch.object(views, "get_programme_duration", return_value=40), \
             patch.object(views, "build_timeshift_candidate_urls",
                          **build_kwargs) as build_mock, \
             patch.object(views, "check_user_stream_limits", return_value=limits), \
             patch.object(views, "RedisClient") as redis_cls, \
             patch.object(views, "reserve_profile_slot", **reserve_kwargs) as reserve_mock, \
             patch.object(views, "release_profile_slot") as release_mock, \
             patch.object(views, "get_transformed_credentials",
                          side_effect=_fake_creds) as creds_mock, \
             patch.object(views, "get_user_active_connections", return_value=[]), \
             patch.object(views, "_stream_from_provider",
                          side_effect=provider_responses) as stream_mock:
            redis_cls.get_client.return_value = self.fake_redis
            channel_cls.objects.get.return_value = MagicMock(id=8, name="Test", logo_id=None)
            # Exposed before the call so raising tests can still assert on them.
            self.reserve_mock = reserve_mock
            self.release_mock = release_mock
            self.creds_mock = creds_mock
            self.stream_mock = stream_mock
            response = views.timeshift_proxy(
                request, "u", "p", "8", "2026-06-08:17-00", "8.ts"
            )
        return response, stream_mock, build_mock


class TimeshiftProxyFailoverHardeningTests(_ProxyLoopTestMixin, TestCase):
    """Ban-safety and per-provider context guarantees of the failover loop."""

    def test_decisive_failure_skips_same_accounts_other_streams(self):
        # Account 1 carries two variants (e.g. FHD + HD). A decisive
        # (auth/ban-class) failure on the first must NOT retry account 1's
        # second stream — that would hammer a banning provider — but a
        # DIFFERENT account stays fair game.
        streams = [
            _make_catchup_stream(account_id=1, stream_id="111"),
            _make_catchup_stream(account_id=1, stream_id="112"),
            _make_catchup_stream(account_id=2, stream_id="222"),
        ]
        decisive = MagicMock(status_code=403, timeshift_decisive=True)
        ok = MagicMock(status_code=200)
        response, stream_mock, _ = self._call(streams, [decisive, ok])
        self.assertIs(response, ok)
        self.assertEqual(stream_mock.call_count, 2)
        self.assertEqual(
            [c.kwargs["account_id"] for c in stream_mock.call_args_list], [1, 2]
        )

    def test_soft_failure_still_tries_same_accounts_other_streams(self):
        # A soft failure (404: this stream's archive missing) is stream-
        # specific — the same account's other variant may still have it.
        streams = [
            _make_catchup_stream(account_id=1, stream_id="111"),
            _make_catchup_stream(account_id=1, stream_id="112"),
        ]
        soft = MagicMock(status_code=404, timeshift_decisive=False)
        ok = MagicMock(status_code=200)
        response, stream_mock, _ = self._call(streams, [soft, ok])
        self.assertIs(response, ok)
        self.assertEqual(stream_mock.call_count, 2)
        self.assertEqual(
            [c.kwargs["account_id"] for c in stream_mock.call_args_list], [1, 1]
        )

    def test_each_stream_uses_its_own_provider_timezone(self):
        # June: 17:00 UTC = 19:00 Brussels (CEST) but 13:00 New York (EDT).
        # The converted timestamp must be recomputed per attempt.
        streams = [
            _make_catchup_stream(account_id=1, stream_id="111",
                                 provider_tz="Europe/Brussels"),
            _make_catchup_stream(account_id=2, stream_id="222",
                                 provider_tz="America/New_York"),
        ]
        response, _, build_mock = self._call(
            streams,
            [MagicMock(status_code=404, timeshift_decisive=False),
             MagicMock(status_code=200)],
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [c.args[2] for c in build_mock.call_args_list],
            ["2026-06-08:19-00", "2026-06-08:13-00"],
        )

    def test_stream_limit_exceeded_returns_403_before_upstream(self):
        streams = [_make_catchup_stream(account_id=1, stream_id="111")]
        response, stream_mock, _ = self._call(streams, [], limits=False)
        self.assertEqual(response.status_code, 403)
        stream_mock.assert_not_called()

    def test_no_catchup_streams_returns_400(self):
        response, stream_mock, _ = self._call([], [])
        self.assertEqual(response.status_code, 400)
        stream_mock.assert_not_called()

    def test_all_streams_ineligible_returns_400(self):
        streams = [
            _make_catchup_stream(account_id=1, account_type="M3U"),
            _make_catchup_stream(account_id=2, stream_id=None),
        ]
        response, stream_mock, _ = self._call(streams, [])
        self.assertEqual(response.status_code, 400)
        stream_mock.assert_not_called()


class XcServerInfoUtcTests(TestCase):
    """The XC server_info 'timezone triple' guarantee the timeshift chain
    relies on: server_info.timezone is always UTC and time_now is UTC
    wall-clock. (Tested here because catch-up seek correctness depends on
    it: clients build the timeshift URL from this declared zone.)"""

    def test_server_info_is_strictly_utc(self):
        from datetime import datetime, timezone as dt_timezone
        from apps.output.views import _build_xc_server_info

        request = MagicMock(scheme="http")
        info = _build_xc_server_info(request, "example.test", "9191")
        self.assertEqual(info["timezone"], "UTC")
        reported = datetime.strptime(info["time_now"], "%Y-%m-%d %H:%M:%S")
        now_utc = datetime.now(dt_timezone.utc).replace(tzinfo=None)
        self.assertLess(abs((now_utc - reported).total_seconds()), 60)
        self.assertIsInstance(info["timestamp_now"], int)


class StreamFromProviderDecisiveEdgeTests(TestCase):
    """Remaining decisive-status and transport-error paths of the cascade."""

    def setUp(self):
        self.kwargs = dict(
            candidate_urls=[
                "http://example.test/timeshift/u/p/60/2026-05-12:17-00/1.ts",
                "http://example.test/streaming/timeshift.php?stream=1&start=2026-05-12_17-00",
            ],
            user_agent="test-agent",
            range_header=None,
            virtual_channel_id="timeshift_1_2026-05-12-17-00_1",
            client_id="timeshift_test456",
            client_ip="127.0.0.1",
            user=None,
            channel_display_name="Test",
            timestamp_utc="2026-05-12:17-00",
            channel_logo_id=None,
            m3u_profile_id=None,
            debug=False,
        )

    @patch.object(views, "_open_upstream")
    def test_406_is_decisive_and_marks_response(self, mocked_open):
        # 406 = IP-wide block in the XC ban escalation — single attempt,
        # generic 400 to the client, and the failover loop must see the
        # decisive marker so it skips this account's other streams.
        mocked_open.return_value = _fake_upstream(406)
        response = views._stream_from_provider(**self.kwargs)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(mocked_open.call_count, 1)
        self.assertTrue(response.timeshift_decisive)

    @patch.object(views, "_open_upstream")
    def test_404_failure_is_not_decisive(self, mocked_open):
        mocked_open.return_value = _fake_upstream(404)
        response = views._stream_from_provider(**self.kwargs)
        self.assertEqual(response.status_code, 404)
        self.assertFalse(response.timeshift_decisive)

    @patch.object(views, "_open_upstream")
    def test_connection_error_returns_400_after_single_attempt(self, mocked_open):
        import requests as _requests
        mocked_open.side_effect = _requests.exceptions.ConnectionError("boom")
        response = views._stream_from_provider(**self.kwargs)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(mocked_open.call_count, 1)
        # Transport errors are host-level, not auth/ban-class: the failover
        # loop may still try a different account.
        self.assertFalse(getattr(response, "timeshift_decisive", False))


class CatchupStreamsDbTests(TestCase):
    """get_channel_catchup_streams: the function that defines the failover
    order — channelstream order, catch-up streams only, active accounts only."""

    @classmethod
    def setUpTestData(cls):
        from apps.channels.models import Channel, ChannelStream, Stream
        from apps.m3u.models import M3UAccount

        cls.active = M3UAccount.objects.create(
            name="ts-test-active", server_url="http://example.test",
            account_type="XC", is_active=True,
        )
        cls.inactive = M3UAccount.objects.create(
            name="ts-test-inactive", server_url="http://example.test",
            account_type="XC", is_active=False,
        )
        cls.channel = Channel.objects.create(name="ts-test-channel", is_catchup=True)

        def add(name, account, *, catchup, order):
            s = Stream.objects.create(
                name=name, url=f"http://example.test/{name}",
                m3u_account=account, is_catchup=catchup,
            )
            ChannelStream.objects.create(channel=cls.channel, stream=s, order=order)
            return s

        cls.s_inactive = add("s-inactive", cls.inactive, catchup=True, order=0)
        cls.s_second = add("s-second", cls.active, catchup=True, order=2)
        cls.s_first = add("s-first", cls.active, catchup=True, order=1)
        cls.s_live_only = add("s-live-only", cls.active, catchup=False, order=3)

    def test_ordered_active_catchup_streams_only(self):
        from apps.channels.utils import get_channel_catchup_streams

        result = get_channel_catchup_streams(self.channel)
        # Inactive-account and non-catchup streams excluded; channelstream order.
        self.assertEqual([s.id for s in result], [self.s_first.id, self.s_second.id])

    def test_channel_without_catchup_flag_returns_empty(self):
        from apps.channels.models import Channel
        from apps.channels.utils import get_channel_catchup_streams

        ch = Channel.objects.create(name="ts-test-nocatchup", is_catchup=False)
        self.assertEqual(get_channel_catchup_streams(ch), [])


class AuthHelpersDbTests(TestCase):
    """_authenticate_user (xc_password custom property) and
    _user_can_access_channel (user_level gate) — exercised against real models
    instead of being mocked away."""

    @classmethod
    def setUpTestData(cls):
        from apps.accounts.models import User
        from apps.channels.models import Channel

        cls.viewer = User.objects.create(
            username="ts-test-viewer", user_level=0,
            custom_properties={"xc_password": "right-pass"},
        )
        cls.no_xc = User.objects.create(
            username="ts-test-noxc", user_level=10,
            custom_properties={},
        )
        cls.basic_channel = Channel.objects.create(name="ts-test-basic", user_level=0)
        cls.admin_channel = Channel.objects.create(name="ts-test-adult", user_level=10)

    def test_valid_xc_password_authenticates(self):
        user = views._authenticate_user("ts-test-viewer", "right-pass")
        self.assertIsNotNone(user)
        self.assertEqual(user.id, self.viewer.id)

    def test_wrong_xc_password_rejected(self):
        self.assertIsNone(views._authenticate_user("ts-test-viewer", "wrong"))

    def test_user_without_xc_password_rejected(self):
        # Accounts with no xc_password set (e.g. admins) must be denied even
        # if the caller guesses any string — there is nothing to compare to.
        self.assertIsNone(views._authenticate_user("ts-test-noxc", ""))
        self.assertIsNone(views._authenticate_user("ts-test-noxc", "anything"))

    def test_unknown_username_rejected(self):
        self.assertIsNone(views._authenticate_user("ts-test-ghost", "x"))

    def test_user_level_gate(self):
        # Level-0 viewer with no profiles: allowed on level-0, denied on level-10.
        self.assertTrue(views._user_can_access_channel(self.viewer, self.basic_channel))
        self.assertFalse(views._user_can_access_channel(self.viewer, self.admin_channel))


class TimeshiftSlotPoolTests(_ProxyLoopTestMixin, TestCase):
    """Provider pool participation: a profile slot is reserved before any
    upstream attempt and released exactly once afterwards, the same accounting
    contract live (Channel.get_stream) and VOD follow. Each active stream
    reserves its own slot so concurrent provider connections stay capped by
    max_streams."""

    POOL_KEY = f"timeshift_pool:{TEST_SESSION_ID}"

    def _pool_entry_ids(self):
        return [k for k in self.fake_redis.store if k.startswith("timeshift_pool:")]

    def test_reserve_called_with_default_profile_before_upstream(self):
        streams = [_make_catchup_stream(account_id=1, stream_id="111", profile_id=31)]
        response, stream_mock, _ = self._call(streams, [MagicMock(status_code=200)])
        self.assertEqual(response.status_code, 200)
        self.reserve_mock.assert_called_once()
        reserved_profile = self.reserve_mock.call_args.args[0]
        self.assertEqual(reserved_profile.id, 31)
        # The reserved profile's id is what reaches the stats metadata.
        self.assertEqual(stream_mock.call_args.kwargs["m3u_profile_id"], 31)

    def test_slot_released_after_failed_attempt(self):
        streams = [_make_catchup_stream(account_id=1, stream_id="111", profile_id=31)]
        response, _, _ = self._call(
            streams, [MagicMock(status_code=404, timeshift_decisive=False)]
        )
        self.assertEqual(response.status_code, 404)
        # The failed attempt's slot was released and its pool entry removed.
        self.release_mock.assert_called_once_with(31, self.fake_redis)
        self.assertEqual(self._pool_entry_ids(), [])

    def test_slot_kept_on_success_for_the_streaming_session(self):
        streams = [_make_catchup_stream(account_id=1, stream_id="111", profile_id=31)]
        response, _, _ = self._call(streams, [MagicMock(status_code=200)])
        self.assertEqual(response.status_code, 200)
        # Slot still owned by the (mocked) streaming session: a busy pool entry
        # remains for the next request to reuse, nothing released yet.
        self.release_mock.assert_not_called()
        self.assertEqual(len(self._pool_entry_ids()), 1)

    def test_decisive_failure_releases_slot_and_skips_account(self):
        streams = [
            _make_catchup_stream(account_id=1, stream_id="111", profile_id=31),
            _make_catchup_stream(account_id=1, stream_id="112", profile_id=31),
        ]
        response, stream_mock, _ = self._call(
            streams, [MagicMock(status_code=403, timeshift_decisive=True)]
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(stream_mock.call_count, 1)
        self.release_mock.assert_called_once_with(31, self.fake_redis)
        # Decisive skip means the second stream never reserved a slot.
        self.assertEqual(self.reserve_mock.call_count, 1)

    def test_profile_full_walks_to_next_profile_same_account(self):
        alt = _make_alt_profile(32)
        streams = [_make_catchup_stream(
            account_id=1, stream_id="111", profile_id=31, extra_profiles=(alt,)
        )]
        response, stream_mock, _ = self._call(
            streams, [MagicMock(status_code=200)],
            reserve_results=[(False, 1, "profile_full"), (True, 1, None)],
        )
        self.assertEqual(response.status_code, 200)
        # Default profile full -> alternate profile reserved and used.
        self.assertEqual(
            [c.args[0].id for c in self.reserve_mock.call_args_list], [31, 32]
        )
        self.assertEqual(stream_mock.call_args.kwargs["m3u_profile_id"], 32)
        # Credentials were resolved for the RESERVED (alternate) profile.
        self.assertIs(self.creds_mock.call_args.args[1], alt)

    def test_all_profiles_full_returns_503_without_upstream_attempt(self):
        streams = [
            _make_catchup_stream(account_id=1, stream_id="111", profile_id=31),
            _make_catchup_stream(account_id=2, stream_id="222", profile_id=41),
        ]
        response, stream_mock, _ = self._call(
            streams, [],
            reserve_results=[
                (False, 1, "profile_full"),
                (False, 1, "credential_full"),
            ],
        )
        # Pool capacity exhausted everywhere: 503 (VOD's pool-exhausted
        # status), and crucially the provider was never contacted.
        self.assertEqual(response.status_code, 503)
        stream_mock.assert_not_called()
        self.release_mock.assert_not_called()

    def test_capacity_failure_is_not_decisive_for_the_account(self):
        # profile_full on account 1's first stream must NOT mark account 1
        # decisive — capacity is transient, unlike a ban-class status.
        streams = [
            _make_catchup_stream(account_id=1, stream_id="111", profile_id=31),
            _make_catchup_stream(account_id=1, stream_id="112", profile_id=31),
        ]
        response, stream_mock, _ = self._call(
            streams, [MagicMock(status_code=200)],
            reserve_results=[(False, 1, "profile_full"), (True, 1, None)],
        )
        self.assertEqual(response.status_code, 200)
        # Second stream of the SAME account still got its reservation attempt.
        self.assertEqual(self.reserve_mock.call_count, 2)
        self.assertEqual(stream_mock.call_count, 1)

    def test_account_without_active_default_profile_is_skipped(self):
        # Mirrors live dispatch: no active default profile -> skip the account
        # without reserving anything.
        stream = _make_catchup_stream(account_id=1, stream_id="111")
        stream.m3u_account.profiles.filter.return_value = [_make_alt_profile(32)]
        response, stream_mock, _ = self._call([stream], [])
        self.assertEqual(response.status_code, 400)
        self.reserve_mock.assert_not_called()
        stream_mock.assert_not_called()

    def test_exception_from_provider_releases_slot(self):
        # An unexpected exception between reserve and response construction
        # must release the slot before propagating — otherwise the counter
        # (no TTL) leaks until the next Redis flush.
        streams = [_make_catchup_stream(account_id=1, stream_id="111", profile_id=31)]
        with self.assertRaises(RuntimeError):
            self._call(streams, RuntimeError("boom"))
        self.release_mock.assert_called_once_with(31, self.fake_redis)
        self.assertEqual(self._pool_entry_ids(), [])

    def test_exception_before_upstream_releases_slot(self):
        # Same guarantee for failures BEFORE the upstream call (URL building,
        # credential resolution, user-agent lookup) — the guarded window
        # starts right after the reservation.
        streams = [_make_catchup_stream(account_id=1, stream_id="111", profile_id=31)]
        with self.assertRaises(RuntimeError):
            self._call(streams, [], build_side_effect=RuntimeError("boom"))
        self.stream_mock.assert_not_called()
        self.release_mock.assert_called_once_with(31, self.fake_redis)
        self.assertEqual(self._pool_entry_ids(), [])

    def test_mixed_capacity_then_upstream_failure_returns_failure(self):
        # Mixed outcome: one stream capacity-blocked, another actually tried
        # upstream and failed -> the REAL upstream failure wins over 503
        # (capacity was not the sole blocker).
        streams = [
            _make_catchup_stream(account_id=1, stream_id="111", profile_id=31),
            _make_catchup_stream(account_id=2, stream_id="222", profile_id=41),
        ]
        response, _, _ = self._call(
            streams,
            [MagicMock(status_code=404, timeshift_decisive=False)],
            reserve_results=[(False, 1, "profile_full"), (True, 1, None)],
        )
        self.assertEqual(response.status_code, 404)

    def test_mixed_upstream_failure_then_capacity_returns_failure(self):
        # Same in the opposite order.
        streams = [
            _make_catchup_stream(account_id=1, stream_id="111", profile_id=31),
            _make_catchup_stream(account_id=2, stream_id="222", profile_id=41),
        ]
        response, _, _ = self._call(
            streams,
            [MagicMock(status_code=404, timeshift_decisive=False)],
            reserve_results=[(True, 1, None), (False, 1, "profile_full")],
        )
        self.assertEqual(response.status_code, 404)


class TimeshiftPoolReleaseTests(TestCase):
    """Pool slot release and response close paths for a pooled session."""

    def setUp(self):
        self.redis = _FakeRedis()
        self.session_id = TEST_SESSION_ID

    def _pool_key(self):
        return f"timeshift_pool:{self.session_id}"

    def test_release_callback_frees_slot_exactly_once(self):
        _seed_pool_session(self.redis, session_id=self.session_id)
        release = views._make_release_once(self.redis, self.session_id, 31)
        with patch.object(views, "release_profile_slot") as release_mock:
            release()
            release()
        release_mock.assert_called_once_with(31, self.redis)
        self.assertEqual(self.redis.hget(self._pool_key(), "busy"), "0")
        self.assertTrue(self.redis.exists(self._pool_key()))

    def test_discard_frees_slot_and_removes_entry(self):
        _seed_pool_session(self.redis, session_id=self.session_id)
        with patch.object(views, "release_profile_slot") as release_mock:
            views._discard_pool_session(self.redis, self.session_id, 31)
        release_mock.assert_called_once_with(31, self.redis)
        self.assertFalse(self.redis.exists(self._pool_key()))

    def test_release_without_redis_is_noop(self):
        release = views._make_release_once(None, self.session_id, 31)
        with patch.object(views, "release_profile_slot") as release_mock:
            release()
        release_mock.assert_not_called()

    def test_wrapper_close_releases_even_when_generator_never_started(self):
        # The WSGI layer can close the response before the first chunk is
        # pulled; closing a never-started generator runs NO body code, so the
        # generator's own finally cannot be the only release point.
        finally_ran = []

        def gen():
            try:
                yield b"x"
            finally:
                finally_ran.append(True)

        on_close = MagicMock()
        wrapper = views._SlotReleasingStream(gen(), on_close)
        wrapper.close()
        on_close.assert_called_once()
        self.assertEqual(finally_ran, [])  # proves the leak this wrapper fixes

    def test_streaming_response_close_invokes_wrapper_close(self):
        # Locks the Django contract the wrapper relies on: an iterator with a
        # close() method is registered as a resource closer of the response.
        from django.http import StreamingHttpResponse

        on_close = MagicMock()
        wrapper = views._SlotReleasingStream(iter([b"x"]), on_close)
        response = StreamingHttpResponse(wrapper, content_type="video/mp2t")
        response.close()
        on_close.assert_called_once()


class TimeshiftTakeoverTests(TestCase):
    """A new request displaces the user's previous catch-up session(s) on the
    same channel at a DIFFERENT position (stats unregister + stop key, leaving
    the displaced generator to free its own slot), while leaving sibling range
    requests of the same playback alone, and never touching other users,
    channels, or live."""

    def setUp(self):
        self.redis = _FakeRedis()
        self.user = MagicMock(id=5)

    def _conn(self, media_id, client_id, conn_type="timeshift"):
        return {
            "media_id": media_id,
            "client_id": client_id,
            "connected_at": 0.0,
            "type": conn_type,
        }

    def test_displaces_other_positions_on_same_channel(self):
        connections = [
            self._conn("timeshift_8_2026-06-08-17-00_111", "timeshift_old1"),
            self._conn("timeshift_9_2026-06-08-17-00_222", "timeshift_other"),
            self._conn("42", "live_client", conn_type="live"),
        ]
        with patch.object(views, "get_user_active_connections",
                          return_value=connections) as conns_mock, \
             patch.object(views, "release_profile_slot") as release_mock, \
             patch.object(views, "_unregister_stats_client") as unregister_mock:
            views._terminate_previous_timeshift_sessions(
                self.redis, self.user, 8, "timeshift_8_2026-06-09-20-00", "timeshift_current",
            )
        conns_mock.assert_called_once_with(5)
        # Takeover defers slot release to the displaced generator's stop path;
        # it only drops stats and signals the stop key.
        release_mock.assert_not_called()
        unregister_mock.assert_called_once_with(
            self.redis, "timeshift_8_2026-06-08-17-00_111", "timeshift_old1"
        )
        from apps.proxy.live_proxy.redis_keys import RedisKeys
        stop_key = RedisKeys.client_stop(
            "timeshift_8_2026-06-08-17-00_111", "timeshift_old1"
        )
        self.assertIn(stop_key, self.redis.store)
        # Channel 9's session untouched: no stop key set for it.
        other_stop = RedisKeys.client_stop(
            "timeshift_9_2026-06-08-17-00_222", "timeshift_other"
        )
        self.assertNotIn(other_stop, self.redis.store)

    def test_leaves_sibling_requests_of_current_playback(self):
        # Concurrent range/probe requests of the SAME playback must not
        # displace one another.
        connections = [
            self._conn("timeshift_8_2026-06-08-17-00_111", "timeshift_sibling"),
        ]
        with patch.object(views, "get_user_active_connections",
                          return_value=connections), \
             patch.object(views, "release_profile_slot") as release_mock, \
             patch.object(views, "_unregister_stats_client") as unregister_mock:
            views._terminate_previous_timeshift_sessions(
                self.redis, self.user, 8, "timeshift_8_2026-06-08-17-00",
                "timeshift_sibling",
            )
        release_mock.assert_not_called()
        unregister_mock.assert_not_called()

    def test_channel_id_prefix_cannot_match_other_channels(self):
        # Channel 8 must not displace channel 80/81 sessions (prefix ends
        # with an underscore).
        connections = [
            self._conn("timeshift_80_2026-06-08-17-00_111", "timeshift_c80"),
        ]
        with patch.object(views, "get_user_active_connections",
                          return_value=connections), \
             patch.object(views, "release_profile_slot") as release_mock, \
             patch.object(views, "_unregister_stats_client") as unregister_mock:
            views._terminate_previous_timeshift_sessions(
                self.redis, self.user, 8, "timeshift_8_2026-06-08-17-00",
                "timeshift_new",
            )
        release_mock.assert_not_called()
        unregister_mock.assert_not_called()

    def test_noop_without_redis_or_user(self):
        with patch.object(views, "get_user_active_connections") as conns_mock:
            views._terminate_previous_timeshift_sessions(
                None, self.user, 8, "timeshift_8_ts", "timeshift_s"
            )
            views._terminate_previous_timeshift_sessions(
                self.redis, None, 8, "timeshift_8_ts", "timeshift_s"
            )
        conns_mock.assert_not_called()

    def test_proxy_runs_takeover_before_stream_limit_check(self):
        # Order matters: with terminate_on_limit_exceeded=False a seek must
        # displace its own predecessor BEFORE the limit check counts it, or
        # the user's own seek gets denied.
        call_order = []
        request = RequestFactory().get(_proxy_url())
        with patch.object(views, "_authenticate_user", return_value=MagicMock()), \
             patch.object(views, "network_access_allowed", return_value=True), \
             patch.object(views, "Channel") as channel_cls, \
             patch.object(views, "_user_can_access_channel", return_value=True), \
             patch.object(views, "get_channel_catchup_streams",
                          return_value=[_make_catchup_stream()]), \
             patch.object(views, "get_programme_duration", return_value=40), \
             patch.object(views, "RedisClient") as redis_cls, \
             patch.object(views, "_terminate_previous_timeshift_sessions",
                          side_effect=lambda *a: call_order.append("takeover")) as takeover_mock, \
             patch.object(views, "check_user_stream_limits",
                          side_effect=lambda *a, **k: call_order.append("limits") or False):
            redis_cls.get_client.return_value = self.redis
            channel_cls.objects.get.return_value = MagicMock(id=8, name="Test", logo_id=None)
            response = views.timeshift_proxy(
                request, "u", "p", "8", "2026-06-08:17-00", "8.ts"
            )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(call_order, ["takeover", "limits"])
        self.assertEqual(takeover_mock.call_args.args[2], 8)


class TimeshiftSessionReuseTests(TestCase):
    """Per-client session pool acquire/reuse paths."""

    SESSION = TEST_SESSION_ID

    def setUp(self):
        self.redis = _FakeRedis()
        self.factory = RequestFactory()
        self.channel = MagicMock(id=8, name="Test")
        self.user = MagicMock(id=5)

    def _pool_key(self):
        return f"timeshift_pool:{self.SESSION}"

    def _make_idle_entry(self):
        _seed_pool_session(self.redis, session_id=self.SESSION)
        with patch.object(views, "release_profile_slot"):
            views._release_pool_session(self.redis, self.SESSION, 31)

    def test_wait_returns_none_without_blocking_when_pool_empty(self):
        start = time.monotonic()
        acquired = views._wait_for_idle_pool_session(self.redis, self.SESSION)
        self.assertIsNone(acquired)
        self.assertLess(time.monotonic() - start, 0.5)

    def test_acquire_reuses_idle_entry_and_reserves_slot(self):
        self._make_idle_entry()
        profile = MagicMock(id=31)
        with patch.object(views.M3UAccountProfile.objects, "get",
                          return_value=profile), \
             patch.object(views, "reserve_profile_slot",
                          return_value=(True, 1, None)) as reserve_mock:
            acquired = views._acquire_idle_pool_session(self.redis, self.SESSION)
        self.assertIsNotNone(acquired)
        descriptor, got_profile = acquired
        self.assertEqual(descriptor["stream_id"], "111")
        self.assertIs(got_profile, profile)
        reserve_mock.assert_called_once_with(profile, self.redis)
        self.assertEqual(self.redis.hget(self._pool_key(), "busy"), "1")

    def test_acquire_skips_busy_entry(self):
        _seed_pool_session(self.redis, session_id=self.SESSION, busy="1")
        with patch.object(views.M3UAccountProfile.objects, "get") as prof_mock, \
             patch.object(views, "reserve_profile_slot") as reserve_mock:
            acquired = views._acquire_idle_pool_session(self.redis, self.SESSION)
        self.assertIsNone(acquired)
        prof_mock.assert_not_called()
        reserve_mock.assert_not_called()

    def test_find_matching_idle_session_requires_ip_and_user_agent(self):
        _seed_pool_session(
            self.redis, session_id="timeshift_other",
            user_id=5, client_ip="1.2.3.4", client_user_agent="test-agent",
        )
        with patch.object(views, "release_profile_slot"):
            views._release_pool_session(self.redis, "timeshift_other", 31)
        matched = views._find_matching_idle_session(
            self.redis,
            media_id=TEST_MEDIA_ID,
            user_id=5,
            client_ip="1.2.3.4",
            client_user_agent="test-agent",
        )
        self.assertEqual(matched, "timeshift_other")

    def test_find_matching_idle_session_rejects_ip_only_partial_fingerprint(self):
        _seed_pool_session(
            self.redis, session_id="timeshift_other",
            user_id=5, client_ip="1.2.3.4", client_user_agent="other-agent",
        )
        with patch.object(views, "release_profile_slot"):
            views._release_pool_session(self.redis, "timeshift_other", 31)
        matched = views._find_matching_idle_session(
            self.redis,
            media_id=TEST_MEDIA_ID,
            user_id=5,
            client_ip="1.2.3.4",
            client_user_agent="test-agent",
        )
        self.assertIsNone(matched)

    def test_find_matching_idle_session_rejects_different_user(self):
        _seed_pool_session(
            self.redis, session_id="timeshift_other",
            user_id=99, client_ip="1.2.3.4", client_user_agent="test-agent",
        )
        with patch.object(views, "release_profile_slot"):
            views._release_pool_session(self.redis, "timeshift_other", 31)
        matched = views._find_matching_idle_session(
            self.redis,
            media_id=TEST_MEDIA_ID,
            user_id=5,
            client_ip="1.2.3.4",
            client_user_agent="test-agent",
        )
        self.assertIsNone(matched)

    def test_legacy_pool_entry_exists_helper_removed(self):
        self.assertFalse(hasattr(views, "_pool_entry_exists"))

    def test_new_session_uses_single_hgetall_before_pool_create(self):
        redis = _FakeRedis()
        request = self.factory.get(_proxy_url("timeshift_newsession1"))
        with patch.object(views, "_authenticate_user", return_value=MagicMock(id=5)), \
             patch.object(views, "network_access_allowed", return_value=True), \
             patch.object(views, "Channel") as channel_cls, \
             patch.object(views, "_user_can_access_channel", return_value=True), \
             patch.object(views, "get_channel_catchup_streams",
                          return_value=[_make_catchup_stream()]), \
             patch.object(views, "get_programme_duration", return_value=40), \
             patch.object(views, "check_user_stream_limits", return_value=True), \
             patch.object(views, "_find_matching_idle_session", return_value=None), \
             patch.object(views, "_attempt_timeshift_stream",
                          return_value=MagicMock(status_code=200)), \
             patch.object(views, "RedisClient") as redis_cls, \
             patch.object(views, "reserve_profile_slot", return_value=(True, 1, None)), \
             patch.object(views, "release_profile_slot"), \
             patch.object(views, "get_transformed_credentials", side_effect=_fake_creds), \
             patch.object(views, "get_user_active_connections", return_value=[]):
            redis_cls.get_client.return_value = redis
            channel_cls.objects.get.return_value = MagicMock(id=8, name="Test", logo_id=None)
            with patch.object(redis, "hgetall", wraps=redis.hgetall) as hgetall_mock:
                views.timeshift_proxy(
                    request, "u", "p", "8", "2026-06-08:17-00", "8.ts",
                )
        pool_key = "timeshift_pool:timeshift_newsession1"
        self.assertEqual(
            sum(1 for c in hgetall_mock.call_args_list if c.args == (pool_key,)),
            1,
        )


class TimeshiftSessionRedirectTests(TestCase):
    """First request must establish a session via 301 redirect (VOD-style)."""

    def setUp(self):
        self.factory = RequestFactory()

    def test_missing_session_id_redirects(self):
        request = self.factory.get(_proxy_url(session_id=None))
        with patch.object(views, "_authenticate_user", return_value=MagicMock(id=1)), \
             patch.object(views, "network_access_allowed", return_value=True), \
             patch.object(views, "Channel") as channel_cls, \
             patch.object(views, "_user_can_access_channel", return_value=True), \
             patch.object(views, "get_channel_catchup_streams",
                          return_value=[_make_catchup_stream()]), \
             patch.object(views, "get_programme_duration", return_value=40), \
             patch.object(views, "parse_catchup_timestamp", return_value=True), \
             patch.object(views, "RedisClient") as redis_cls:
            redis_cls.get_client.return_value = _FakeRedis()
            channel_cls.objects.get.return_value = MagicMock(id=8)
            response = views.timeshift_proxy(
                request, "u", "p", "8", "2026-06-08:17-00", "8.ts",
            )
        self.assertEqual(response.status_code, 301)
        self.assertIn("session_id=timeshift_", response["Location"])

    def test_redirect_preserves_existing_query_params(self):
        request = self.factory.get(
            "/timeshift/u/p/8/2026-06-08:17-00/8.ts?foo=bar&baz=1",
        )
        with patch.object(views, "_authenticate_user", return_value=MagicMock(id=1)), \
             patch.object(views, "network_access_allowed", return_value=True), \
             patch.object(views, "Channel") as channel_cls, \
             patch.object(views, "_user_can_access_channel", return_value=True), \
             patch.object(views, "get_channel_catchup_streams",
                          return_value=[_make_catchup_stream()]), \
             patch.object(views, "get_programme_duration", return_value=40), \
             patch.object(views, "parse_catchup_timestamp", return_value=True), \
             patch.object(views, "RedisClient") as redis_cls:
            redis_cls.get_client.return_value = _FakeRedis()
            channel_cls.objects.get.return_value = MagicMock(id=8)
            response = views.timeshift_proxy(
                request, "u", "p", "8", "2026-06-08:17-00", "8.ts",
            )
        self.assertEqual(response.status_code, 301)
        location = response["Location"]
        self.assertIn("session_id=timeshift_", location)
        self.assertIn("foo=bar", location)
        self.assertIn("baz=1", location)


class TimeshiftStreamLimitExemptionTests(TestCase):
    """Timeshift stream-limit bypass requires the same client session."""

    MEDIA = TEST_MEDIA_ID

    def setUp(self):
        self.user = MagicMock(id=5, username="viewer", stream_limit=1)

    def _limits_settings(self, ignore_same_channel=True):
        return {
            "ignore_same_channel_connections": ignore_same_channel,
            "terminate_on_limit_exceeded": False,
        }

    def test_same_session_probe_allowed_at_limit(self):
        connections = [{
            "media_id": f"{self.MEDIA}_111",
            "client_id": TEST_SESSION_ID,
            "connected_at": 0.0,
            "type": "timeshift",
        }]
        with patch("apps.proxy.utils.get_user_active_connections",
                   return_value=connections), \
             patch("apps.proxy.utils.CoreSettings.get_user_limits_settings",
                   return_value=self._limits_settings()):
            allowed = _check_user_stream_limits(
                self.user, TEST_SESSION_ID, media_id=self.MEDIA,
            )
        self.assertTrue(allowed)

    def test_different_session_same_programme_counts_against_limit(self):
        connections = [{
            "media_id": f"{self.MEDIA}_111",
            "client_id": "timeshift_other_session",
            "connected_at": 0.0,
            "type": "timeshift",
        }]
        with patch("apps.proxy.utils.get_user_active_connections",
                   return_value=connections), \
             patch("apps.proxy.utils.CoreSettings.get_user_limits_settings",
                   return_value=self._limits_settings()):
            allowed = _check_user_stream_limits(
                self.user, TEST_SESSION_ID, media_id=self.MEDIA,
            )
        self.assertFalse(allowed)


class FakeRedisScanTests(TestCase):
    """FakeRedis SCAN matches redis-py glob semantics used by the pool scanner."""

    def setUp(self):
        self.redis = _FakeRedis()
        self.redis.store["timeshift_pool:timeshift_a"] = {"busy": "0"}
        self.redis.store["timeshift_pool:timeshift_b"] = {"busy": "0"}
        self.redis.store["timeshift_pool:other_c"] = {"busy": "0"}
        self.redis.store["vod_persistent_connection:x"] = {}

    def test_scan_glob_filters_pool_keys(self):
        cursor = 0
        seen = []
        while True:
            cursor, keys = self.redis.scan(
                cursor, match="timeshift_pool:timeshift_*", count=1,
            )
            seen.extend(keys)
            if cursor == 0:
                break
        self.assertEqual(
            seen,
            ["timeshift_pool:timeshift_a", "timeshift_pool:timeshift_b"],
        )


class TimeshiftRangeClassificationTests(TestCase):
    """Startup probes must not be treated as scrubs."""

    def test_full_file_request_is_not_displacing(self):
        self.assertFalse(views._should_displace_busy_playback(None))

    def test_bytes_zero_displaces_full_file_probe(self):
        self.assertTrue(
            views._should_displace_busy_playback("bytes=0-", busy_serving_range="none")
        )

    def test_bytes_zero_does_not_displace_active_start_stream(self):
        self.assertFalse(
            views._should_displace_busy_playback("bytes=0-", busy_serving_range="start")
        )

    def test_bytes_zero_without_busy_context_is_not_displacing(self):
        self.assertFalse(views._should_displace_busy_playback("bytes=0-"))

    def test_near_eof_probe_is_not_displacing(self):
        self.assertTrue(views._is_near_eof_probe("bytes=2527702896-"))
        self.assertFalse(views._should_displace_busy_playback("bytes=2527702896-"))

    def test_near_eof_probe_uses_cached_content_length(self):
        # 5 MB into a 10 MB file is a scrub, not a tail probe.
        self.assertFalse(
            views._is_near_eof_probe("bytes=5000000-", content_length="10000000")
        )
        self.assertTrue(
            views._should_displace_busy_playback("bytes=5000000-", content_length="10000000")
        )
        # Within 512 KB of EOF is a tail probe once length is known.
        self.assertTrue(
            views._is_near_eof_probe("bytes=9990000-", content_length="10000000")
        )

    def test_midfile_seek_is_displacing(self):
        self.assertTrue(views._should_displace_busy_playback("bytes=5000000-"))

    def test_small_nonzero_range_is_displacing(self):
        self.assertTrue(views._should_displace_busy_playback("bytes=1000-"))


class TimeshiftScrubPreemptTests(TestCase):
    """Scrub/range requests must stop the in-flight stream and reuse the pooled
    provider slot instead of opening parallel upstream connections."""

    def setUp(self):
        self.redis = _FakeRedis()
        self.user = MagicMock(id=5)
        self.factory = RequestFactory()

    def _conn(self, media_id, client_id):
        return {
            "media_id": media_id,
            "client_id": client_id,
            "connected_at": 0.0,
            "type": "timeshift",
        }

    def test_preempt_stops_sibling_clients_of_same_playback(self):
        connections = [
            self._conn(f"{TEST_MEDIA_ID}_111", TEST_SESSION_ID),
            self._conn("timeshift_9_2026-06-08-17-00_222", "timeshift_other"),
        ]
        with patch.object(views, "get_user_active_connections",
                          return_value=connections), \
             patch.object(views, "_unregister_stats_client") as unregister_mock:
            views._preempt_playback_streams(self.redis, TEST_SESSION_ID, self.user)
        unregister_mock.assert_called_once_with(
            self.redis, f"{TEST_MEDIA_ID}_111", TEST_SESSION_ID,
        )
        from apps.proxy.live_proxy.redis_keys import RedisKeys
        stop_key = RedisKeys.client_stop(f"{TEST_MEDIA_ID}_111", TEST_SESSION_ID)
        self.assertIn(stop_key, self.redis.store)

    def test_preempt_leaves_other_playbacks_alone(self):
        connections = [
            self._conn("timeshift_8_2026-06-09-20-00_111", "timeshift_other_pos"),
        ]
        with patch.object(views, "get_user_active_connections",
                          return_value=connections), \
             patch.object(views, "_unregister_stats_client") as unregister_mock:
            views._preempt_playback_streams(self.redis, TEST_SESSION_ID, self.user)
        unregister_mock.assert_not_called()

    def test_busy_pool_returns_503_instead_of_second_provider_connection(self):
        _seed_pool_session(self.redis, session_id=TEST_SESSION_ID)
        request = self.factory.get(
            _proxy_url(TEST_SESSION_ID),
            HTTP_RANGE="bytes=1000-",
        )
        streams = [_make_catchup_stream(account_id=1, stream_id="111", profile_id=31)]
        with patch.object(views, "_authenticate_user", return_value=MagicMock()), \
             patch.object(views, "network_access_allowed", return_value=True), \
             patch.object(views, "Channel") as channel_cls, \
             patch.object(views, "_user_can_access_channel", return_value=True), \
             patch.object(views, "get_channel_catchup_streams", return_value=streams), \
             patch.object(views, "get_programme_duration", return_value=40), \
             patch.object(views, "check_user_stream_limits", return_value=True), \
             patch.object(views, "RedisClient") as redis_cls, \
             patch.object(views, "reserve_profile_slot", return_value=(True, 1, None)), \
             patch.object(views, "release_profile_slot"), \
             patch.object(views, "get_transformed_credentials", side_effect=_fake_creds), \
             patch.object(views, "get_user_active_connections", return_value=[]), \
             patch.object(views, "_preempt_playback_streams") as preempt_mock, \
             patch.object(views, "_wait_for_idle_pool_session", return_value=None), \
             patch.object(views, "_attempt_timeshift_stream") as attempt_mock:
            redis_cls.get_client.return_value = self.redis
            channel_cls.objects.get.return_value = MagicMock(
                id=8, name="Test", logo_id=None,
            )
            response = views.timeshift_proxy(
                request, "u", "p", "8", "2026-06-08:17-00", "8.ts",
            )
        self.assertEqual(response.status_code, 503)
        preempt_mock.assert_called_once()
        attempt_mock.assert_not_called()
        self.assertEqual(len(self._pool_entry_ids()), 1)

    def _pool_entry_ids(self):
        return [k for k in self.redis.store if k.startswith("timeshift_pool:")]

    def test_startup_bytes_zero_deferred_without_preempt(self):
        _seed_pool_session(
            self.redis, session_id=TEST_SESSION_ID, serving_range="start",
        )
        request = self.factory.get(
            _proxy_url(TEST_SESSION_ID),
            HTTP_RANGE="bytes=0-",
        )
        streams = [_make_catchup_stream(account_id=1, stream_id="111", profile_id=31)]
        with patch.object(views, "_authenticate_user", return_value=MagicMock()), \
             patch.object(views, "network_access_allowed", return_value=True), \
             patch.object(views, "Channel") as channel_cls, \
             patch.object(views, "_user_can_access_channel", return_value=True), \
             patch.object(views, "get_channel_catchup_streams", return_value=streams), \
             patch.object(views, "get_programme_duration", return_value=40), \
             patch.object(views, "check_user_stream_limits", return_value=True), \
             patch.object(views, "RedisClient") as redis_cls, \
             patch.object(views, "reserve_profile_slot", return_value=(True, 1, None)), \
             patch.object(views, "release_profile_slot"), \
             patch.object(views, "get_transformed_credentials", side_effect=_fake_creds), \
             patch.object(views, "get_user_active_connections", return_value=[]), \
             patch.object(views, "_preempt_playback_streams") as preempt_mock, \
             patch.object(views, "_attempt_timeshift_stream") as attempt_mock:
            redis_cls.get_client.return_value = self.redis
            channel_cls.objects.get.return_value = MagicMock(
                id=8, name="Test", logo_id=None,
            )
            response = views.timeshift_proxy(
                request, "u", "p", "8", "2026-06-08:17-00", "8.ts",
            )
        self.assertEqual(response.status_code, 503)
        preempt_mock.assert_not_called()
        attempt_mock.assert_not_called()

    def test_eof_probe_deferred_without_preempt(self):
        _seed_pool_session(self.redis, session_id=TEST_SESSION_ID)
        request = self.factory.get(
            _proxy_url(TEST_SESSION_ID),
            HTTP_RANGE="bytes=2527702896-",
        )
        streams = [_make_catchup_stream(account_id=1, stream_id="111", profile_id=31)]
        with patch.object(views, "_authenticate_user", return_value=MagicMock()), \
             patch.object(views, "network_access_allowed", return_value=True), \
             patch.object(views, "Channel") as channel_cls, \
             patch.object(views, "_user_can_access_channel", return_value=True), \
             patch.object(views, "get_channel_catchup_streams", return_value=streams), \
             patch.object(views, "get_programme_duration", return_value=40), \
             patch.object(views, "check_user_stream_limits", return_value=True), \
             patch.object(views, "RedisClient") as redis_cls, \
             patch.object(views, "reserve_profile_slot", return_value=(True, 1, None)), \
             patch.object(views, "release_profile_slot"), \
             patch.object(views, "get_transformed_credentials", side_effect=_fake_creds), \
             patch.object(views, "get_user_active_connections", return_value=[]), \
             patch.object(views, "_preempt_playback_streams") as preempt_mock, \
             patch.object(views, "_attempt_timeshift_stream") as attempt_mock:
            redis_cls.get_client.return_value = self.redis
            channel_cls.objects.get.return_value = MagicMock(
                id=8, name="Test", logo_id=None,
            )
            response = views.timeshift_proxy(
                request, "u", "p", "8", "2026-06-08:17-00", "8.ts",
            )
        self.assertEqual(response.status_code, 503)
        preempt_mock.assert_not_called()
        attempt_mock.assert_not_called()

    def test_create_pool_session_rejects_duplicate_entry(self):
        first = views._create_pool_session(
            self.redis,
            session_id=TEST_SESSION_ID,
            media_id=TEST_MEDIA_ID,
            user_id=5,
            client_ip="1.2.3.4",
            client_user_agent="test-agent",
            account_id=1,
            profile_id=31,
            stream_id="111",
            provider_timestamp="2026",
        )
        second = views._create_pool_session(
            self.redis,
            session_id=TEST_SESSION_ID,
            media_id=TEST_MEDIA_ID,
            user_id=5,
            client_ip="1.2.3.4",
            client_user_agent="test-agent",
            account_id=2,
            profile_id=41,
            stream_id="222",
            provider_timestamp="2026",
        )
        self.assertTrue(first)
        self.assertFalse(second)
        self.assertTrue(self.redis.exists(f"timeshift_pool:{TEST_SESSION_ID}"))

    def test_scrub_reuses_idle_pool_without_opening_failover(self):
        _seed_pool_session(self.redis, session_id=TEST_SESSION_ID)
        with patch.object(views, "release_profile_slot"):
            views._release_pool_session(self.redis, TEST_SESSION_ID, 31)

        request = self.factory.get(
            _proxy_url(TEST_SESSION_ID),
            HTTP_RANGE="bytes=5000-",
        )
        streams = [_make_catchup_stream(account_id=1, stream_id="111", profile_id=31)]
        profile = MagicMock(id=31)
        ok = MagicMock(status_code=206)
        with patch.object(views, "_authenticate_user", return_value=MagicMock()), \
             patch.object(views, "network_access_allowed", return_value=True), \
             patch.object(views, "Channel") as channel_cls, \
             patch.object(views, "_user_can_access_channel", return_value=True), \
             patch.object(views, "get_channel_catchup_streams", return_value=streams), \
             patch.object(views, "get_programme_duration", return_value=40), \
             patch.object(views, "check_user_stream_limits", return_value=True), \
             patch.object(views, "RedisClient") as redis_cls, \
             patch.object(views, "reserve_profile_slot",
                          return_value=(True, 1, None)) as reserve_mock, \
             patch.object(views, "release_profile_slot"), \
             patch.object(views.M3UAccountProfile.objects, "get",
                          return_value=profile), \
             patch.object(views, "get_transformed_credentials", side_effect=_fake_creds), \
             patch.object(views, "get_user_active_connections", return_value=[]), \
             patch.object(views, "_preempt_playback_streams") as preempt_mock, \
             patch.object(views, "_stream_reused_session", return_value=ok) as reuse_mock, \
             patch.object(views, "_attempt_timeshift_stream") as attempt_mock:
            redis_cls.get_client.return_value = self.redis
            channel_cls.objects.get.return_value = MagicMock(
                id=8, name="Test", logo_id=None,
            )
            response = views.timeshift_proxy(
                request, "u", "p", "8", "2026-06-08:17-00", "8.ts",
            )
        self.assertIs(response, ok)
        preempt_mock.assert_not_called()
        reuse_mock.assert_called_once()
        attempt_mock.assert_not_called()
        # Pool acquire re-reserves the idle slot once; failover must not add another.
        reserve_mock.assert_called_once_with(profile, self.redis)



class RollupSelfHealDbTests(TestCase):
    """Catch-up flag consistency after stream removal.

    The ChannelStream signal handles bulk deletes (locked by a regression test).
    The account-scoped rollup self-heals stale flags on channels still linked
    to that account.
    """

    @classmethod
    def setUpTestData(cls):
        from apps.m3u.models import M3UAccount

        cls.account = M3UAccount.objects.create(
            name="ts-rollup-account", server_url="http://example.test",
            account_type="XC", is_active=True,
        )

    def _make_channel_with_catchup_stream(self, name, days=5):
        from apps.channels.models import Channel, ChannelStream, Stream

        channel = Channel.objects.create(name=name)
        stream = Stream.objects.create(
            name=f"{name}-stream", url=f"http://example.test/{name}",
            m3u_account=self.account, is_catchup=True, catchup_days=days,
        )
        ChannelStream.objects.create(channel=channel, stream=stream, order=0)
        return channel, stream

    def test_bulk_stream_delete_resets_channel_flags_via_signal(self):
        # cleanup_streams() removes stale streams with a queryset bulk delete;
        # the cascaded ChannelStream rows still fire post_delete (signal
        # listeners disable Django's fast-delete path), which must reset the
        # channel's denormalized catch-up fields.
        from apps.channels.models import Stream

        channel, stream = self._make_channel_with_catchup_stream("ts-rollup-bulk")
        channel.refresh_from_db()
        self.assertTrue(channel.is_catchup)
        self.assertEqual(channel.catchup_days, 5)

        Stream.objects.filter(id=stream.id).delete()

        channel.refresh_from_db()
        self.assertFalse(channel.is_catchup)
        self.assertEqual(channel.catchup_days, 0)

    def test_rollup_self_heals_stale_channel_with_non_catchup_stream(self):
        # Channel still linked to the account but no active catch-up streams
        # (e.g. catch-up flag cleared on import). Rollup must reset stale flags.
        from apps.channels.models import Channel, ChannelStream, Stream
        from apps.m3u.tasks import rollup_channel_catchup_fields

        channel = Channel.objects.create(name="ts-rollup-stale")
        stream = Stream.objects.create(
            name="ts-rollup-stale-stream",
            url="http://example.test/ts-rollup-stale",
            m3u_account=self.account,
            is_catchup=False,
            catchup_days=0,
        )
        ChannelStream.objects.create(channel=channel, stream=stream, order=0)
        Channel.objects.filter(pk=channel.pk).update(is_catchup=True, catchup_days=9)

        rollup_channel_catchup_fields(self.account.id)

        channel.refresh_from_db()
        self.assertFalse(channel.is_catchup)
        self.assertEqual(channel.catchup_days, 0)

    def test_rollup_self_heal_skips_channels_not_linked_to_account(self):
        from apps.channels.models import Channel
        from apps.m3u.models import M3UAccount
        from apps.m3u.tasks import rollup_channel_catchup_fields

        other_account = M3UAccount.objects.create(
            name="ts-rollup-other",
            server_url="http://example.test/other",
            account_type="XC",
            is_active=True,
        )
        channel = Channel.objects.create(name="ts-rollup-unrelated")
        Channel.objects.filter(pk=channel.pk).update(is_catchup=True, catchup_days=9)

        rollup_channel_catchup_fields(other_account.id)

        channel.refresh_from_db()
        self.assertTrue(channel.is_catchup)
        self.assertEqual(channel.catchup_days, 9)

    def test_rollup_keeps_and_corrects_channels_with_catchup_streams(self):
        # The self-heal pass must not touch channels that legitimately have
        # catch-up streams. The account-scoped pass still corrects their values.
        from apps.channels.models import Channel
        from apps.m3u.tasks import rollup_channel_catchup_fields

        channel, _ = self._make_channel_with_catchup_stream("ts-rollup-valid", days=7)
        # Knock the denormalized values out of sync (bypasses signals).
        Channel.objects.filter(pk=channel.pk).update(is_catchup=False, catchup_days=0)

        rollup_channel_catchup_fields(self.account.id)

        channel.refresh_from_db()
        self.assertTrue(channel.is_catchup)
        self.assertEqual(channel.catchup_days, 7)
