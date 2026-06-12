"""Tests for the timeshift proxy view, focused on upstream status mapping."""

from unittest.mock import MagicMock, patch

from django.test import RequestFactory, TestCase, override_settings

from apps.timeshift import views
from apps.proxy.live_proxy.input.http_streamer import find_ts_sync as _find_ts_sync


class FindTsSyncTests(TestCase):
    """Locate the first MPEG-TS sync chain so a leading HTML/PHP preamble
    can be skipped before the bytes reach a strict demuxer (ExoPlayer)."""

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
    """Just enough of the redis-py surface for the slot-token protocol:
    setex/get/delete plus a transactional pipeline doing GET+DEL."""

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
        request = self.factory.get(f"/timeshift/u/p/8/{timestamp}/8.ts")
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
        # Same network-level gate as the live XC endpoint: when the request's
        # network is not allowed for STREAMS, nothing else runs.
        request = self.factory.get("/timeshift/u/p/8/2026-06-08:17-00/8.ts")
        with patch.object(views, "_authenticate_user", return_value=MagicMock()), \
             patch.object(views, "network_access_allowed", return_value=False) as gate, \
             patch.object(views, "Channel") as channel_cls, \
             patch.object(views, "_stream_from_provider") as stream_mock:
            response = views.timeshift_proxy(
                request, "u", "p", "8", "2026-06-08:17-00", "8.ts"
            )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(gate.call_args[0][1], "STREAMS")
        channel_cls.objects.get.assert_not_called()
        stream_mock.assert_not_called()


class TimeshiftProxyFailoverTests(TestCase):
    """When the first catch-up stream's provider cannot serve the archive,
    the proxy must fail over to the channel's next catch-up stream — each
    attempt with its own provider context."""

    def setUp(self):
        self.factory = RequestFactory()

    def _call(self, streams, provider_responses):
        request = self.factory.get("/timeshift/u/p/8/2026-06-08:17-00/8.ts")
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


class _ProxyLoopTestMixin:
    """Shared driver for tests exercising the failover loop end to end —
    pool reservation, credential resolution and Redis are all controlled."""

    def setUp(self):
        self.factory = RequestFactory()

    def _call(self, streams, provider_responses, limits=True, reserve_results=None,
              build_side_effect=None):
        request = self.factory.get("/timeshift/u/p/8/2026-06-08:17-00/8.ts")
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
    upstream attempt and released exactly once afterwards — the same
    accounting contract live (Channel.get_stream) and VOD follow."""

    def _slot_token_keys(self):
        return [k for k in self.fake_redis.store if k.startswith("timeshift_slot:")]

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
        # The one-shot token was consumed and the pool counter decremented.
        self.release_mock.assert_called_once_with(31, self.fake_redis)
        self.assertEqual(self._slot_token_keys(), [])

    def test_slot_kept_on_success_for_the_streaming_session(self):
        streams = [_make_catchup_stream(account_id=1, stream_id="111", profile_id=31)]
        response, _, _ = self._call(streams, [MagicMock(status_code=200)])
        self.assertEqual(response.status_code, 200)
        # Slot still owned by the (mocked) streaming session: token present,
        # nothing released yet.
        self.release_mock.assert_not_called()
        self.assertEqual(len(self._slot_token_keys()), 1)

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
        self.assertEqual(self._slot_token_keys(), [])

    def test_exception_before_upstream_releases_slot(self):
        # Same guarantee for failures BEFORE the upstream call (URL building,
        # credential resolution, user-agent lookup) — the guarded window
        # starts right after the reservation.
        streams = [_make_catchup_stream(account_id=1, stream_id="111", profile_id=31)]
        with self.assertRaises(RuntimeError):
            self._call(streams, [], build_side_effect=RuntimeError("boom"))
        self.stream_mock.assert_not_called()
        self.release_mock.assert_called_once_with(31, self.fake_redis)
        self.assertEqual(self._slot_token_keys(), [])

    def test_token_store_failure_releases_directly(self):
        # If the ownership token cannot be written, no release path could
        # ever free the slot — the view must release it directly and report
        # transient unavailability instead of streaming unaccounted.
        streams = [_make_catchup_stream(account_id=1, stream_id="111", profile_id=31)]
        with patch.object(views, "_store_slot_token", return_value=False):
            response, stream_mock, _ = self._call(streams, [])
        self.assertEqual(response.status_code, 503)
        stream_mock.assert_not_called()
        self.release_mock.assert_called_once_with(31, self.fake_redis)

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


class TimeshiftSlotTokenTests(TestCase):
    """The one-shot release token: exactly-once semantics across all release
    paths (generator finally, response close, takeover, failed attempt)."""

    def setUp(self):
        self.redis = _FakeRedis()

    def test_release_happens_exactly_once(self):
        views._store_slot_token(self.redis, "timeshift_abc", 31)
        with patch.object(views, "release_profile_slot") as release_mock:
            self.assertTrue(views._release_slot_token(self.redis, "timeshift_abc"))
            self.assertFalse(views._release_slot_token(self.redis, "timeshift_abc"))
        release_mock.assert_called_once_with(31, self.redis)

    def test_release_without_token_is_noop(self):
        with patch.object(views, "release_profile_slot") as release_mock:
            self.assertFalse(views._release_slot_token(self.redis, "timeshift_ghost"))
        release_mock.assert_not_called()

    def test_release_without_redis_is_noop(self):
        with patch.object(views, "release_profile_slot") as release_mock:
            self.assertFalse(views._release_slot_token(None, "timeshift_abc"))
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
    """One catch-up session per user+channel: a new request displaces the
    user's previous session on the same channel — synchronous slot release +
    stats unregister + stop key — and never touches other users, other
    channels, or live sessions."""

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

    def test_displaces_only_same_channel_timeshift_sessions(self):
        views._store_slot_token(self.redis, "timeshift_old1", 31)
        views._store_slot_token(self.redis, "timeshift_other", 41)
        connections = [
            self._conn("timeshift_8_2026-06-08-17-00_111", "timeshift_old1"),
            self._conn("timeshift_9_2026-06-08-17-00_222", "timeshift_other"),
            self._conn("42", "live_client", conn_type="live"),
        ]
        with patch.object(views, "get_user_active_connections",
                          return_value=connections) as conns_mock, \
             patch.object(views, "release_profile_slot") as release_mock, \
             patch.object(views, "_unregister_stats_client") as unregister_mock:
            views._terminate_previous_timeshift_sessions(self.redis, self.user, 8)
        conns_mock.assert_called_once_with(5)
        # Channel 8's old session: slot released, stats dropped, stop key set.
        release_mock.assert_called_once_with(31, self.redis)
        unregister_mock.assert_called_once_with(
            self.redis, "timeshift_8_2026-06-08-17-00_111", "timeshift_old1"
        )
        from apps.proxy.live_proxy.redis_keys import RedisKeys
        stop_key = RedisKeys.client_stop(
            "timeshift_8_2026-06-08-17-00_111", "timeshift_old1"
        )
        self.assertIn(stop_key, self.redis.store)
        # Channel 9's session untouched: token still present, no stop key.
        self.assertIn("timeshift_slot:timeshift_other", self.redis.store)

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
            views._terminate_previous_timeshift_sessions(self.redis, self.user, 8)
        release_mock.assert_not_called()
        unregister_mock.assert_not_called()

    def test_noop_without_redis_or_user(self):
        with patch.object(views, "get_user_active_connections") as conns_mock:
            views._terminate_previous_timeshift_sessions(None, self.user, 8)
            views._terminate_previous_timeshift_sessions(self.redis, None, 8)
        conns_mock.assert_not_called()

    def test_proxy_runs_takeover_before_stream_limit_check(self):
        # Order matters: with terminate_on_limit_exceeded=False a seek must
        # displace its own predecessor BEFORE the limit check counts it, or
        # the user's own seek gets denied.
        call_order = []
        request = RequestFactory().get("/timeshift/u/p/8/2026-06-08:17-00/8.ts")
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


class RollupSelfHealDbTests(TestCase):
    """Catch-up flag consistency after stream removal — the review-#4 point 1
    guarantees: the ChannelStream signal handles bulk deletes (locked by a
    regression test) and the rollup self-heals any channel left flagged with
    no catch-up stream, regardless of how the link rows disappeared."""

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

    def test_rollup_self_heals_stale_channel_without_streams(self):
        # Simulate staleness no signal caught (raw SQL delete, historic data):
        # a flagged channel with zero catch-up streams must be reset by the
        # rollup even though no remaining stream ties it to the account.
        from apps.channels.models import Channel
        from apps.m3u.tasks import rollup_channel_catchup_fields

        channel = Channel.objects.create(name="ts-rollup-stale")
        Channel.objects.filter(pk=channel.pk).update(is_catchup=True, catchup_days=9)

        rollup_channel_catchup_fields(self.account.id)

        channel.refresh_from_db()
        self.assertFalse(channel.is_catchup)
        self.assertEqual(channel.catchup_days, 0)

    def test_rollup_keeps_and_corrects_channels_with_catchup_streams(self):
        # The self-heal pass must not touch channels that legitimately have
        # catch-up streams — and the account-scoped pass still corrects their
        # values.
        from apps.channels.models import Channel
        from apps.m3u.tasks import rollup_channel_catchup_fields

        channel, _ = self._make_channel_with_catchup_stream("ts-rollup-valid", days=7)
        # Knock the denormalized values out of sync (bypasses signals).
        Channel.objects.filter(pk=channel.pk).update(is_catchup=False, catchup_days=0)

        rollup_channel_catchup_fields(self.account.id)

        channel.refresh_from_db()
        self.assertTrue(channel.is_catchup)
        self.assertEqual(channel.catchup_days, 7)
