"""Tests for the timeshift proxy view, focused on upstream status mapping."""

import fnmatch
import time
from unittest.mock import MagicMock, patch

import requests
from django.http import HttpResponse
from django.test import RequestFactory, TestCase, override_settings
from django.urls import resolve
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.timeshift import views
from apps.timeshift.redis_keys import TimeshiftRedisKeys
from apps.proxy.utils import check_user_stream_limits as _check_user_stream_limits
from apps.proxy.utils import find_ts_sync as _find_ts_sync

TEST_SESSION_ID = "testsession1"
TEST_MEDIA_ID = "8_2026-06-08-17-00"


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
    provider_tz_name="Europe/Brussels",
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
        dispatcharr_stream_id=1,
        provider_timestamp="2026-06-08:19-00",
        provider_tz_name=provider_tz_name,
    )
    if serving_range is not None:
        redis.hset(TimeshiftRedisKeys.pool(session_id), "serving_range", serving_range)
    if busy is not None:
        redis.hset(TimeshiftRedisKeys.pool(session_id), "busy", busy)


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
        # Three lone 0x47 bytes that are NOT spaced at 188 - must not be
        # mistaken for a sync chain.
        self.assertEqual(_find_ts_sync(b"\x47\x00\x00\x47\x00\x00\x47" * 50), -1)

    def test_returns_minus_one_for_short_buffer(self):
        self.assertEqual(_find_ts_sync(b"\x47" * 10), -1)



def _make_ts_payload(size=1024):
    """Build a minimal valid MPEG-TS byte sequence with 0x47 sync markers."""
    packet = b"\x47" + b"\x00" * 187
    return (packet * ((size // 188) + 1))[:size]


def _fake_upstream(status_code, *, content_type="video/mp2t", body=b"", url=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.headers = {"Content-Type": content_type}
    resp.url = url or "http://cdn.example.test/timeshift.ts"
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
            client_user_agent="test-client-agent",
            range_header=None,
            virtual_channel_id="1_2026-05-12-17-00_1",
            client_id="test123",
            client_ip="127.0.0.1",
            user=None,
            channel_display_name="Test",
            timestamp_utc="2026-05-12:17-00",
            channel_logo_id=None,
            m3u_profile_id=None,
            channel_id=1,
            channel_uuid="00000000-0000-0000-0000-000000000001",
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
        # 403 is decisive (auth) - no retry of further candidates.
        mocked_open.return_value = _fake_upstream(403)
        response = views._stream_from_provider(**self.kwargs)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(mocked_open.call_count, 1)

    @patch.object(views, "_open_upstream")
    def test_stores_final_url_after_successful_open(self, mocked_open):
        redis = _FakeRedis()
        session_id = "sess-cdn-store"
        cdn = "http://cdn.example.test/tok/archive.ts"
        mocked_open.return_value = _fake_upstream(
            200, body=_make_ts_payload(), url=cdn,
        )
        with patch.object(views, "_register_stats_client"), \
             patch.object(views, "_unregister_stats_client"):
            response = views._stream_from_provider(
                **self.kwargs,
                redis_client=redis,
                pool_session_id=session_id,
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            redis.hget(views._pool_key(session_id), "final_url"), cdn,
        )

    @patch.object(views, "_open_upstream")
    def test_reuses_cached_final_url_without_portal(self, mocked_open):
        cdn = "http://cdn.example.test/tok/archive.ts"
        mocked_open.return_value = _fake_upstream(
            200, body=_make_ts_payload(), url=cdn,
        )
        with patch.object(views, "_register_stats_client"), \
             patch.object(views, "_unregister_stats_client"):
            response = views._stream_from_provider(
                **self.kwargs, final_url=cdn,
            )
        self.assertEqual(response.status_code, 200)
        mocked_open.assert_called_once()
        self.assertEqual(mocked_open.call_args.args[0], cdn)
        self.assertFalse(mocked_open.call_args.kwargs.get("allow_redirects", True))

    @patch.object(views, "_open_upstream")
    def test_xc_scrub_rewrite_does_not_byte_map_stats_position(self, mocked_open):
        # Injected CDN Range is for the provider only; stats must follow the XC
        # URL timestamp, not archive_offset/programme_duration (false "26:00").
        cdn = "http://cdn.example.test/timeshift/u/p/60/2026-05-12:17-00/1.ts?token=x"
        upstream = _fake_upstream(206, body=_make_ts_payload(), url=cdn)
        upstream.headers["Content-Range"] = "bytes 500000000-999999999/1000000000"
        upstream.headers["Content-Length"] = "500000000"
        mocked_open.return_value = upstream
        kwargs = dict(
            self.kwargs,
            final_url=cdn,
            range_header="bytes=500000000-",
            rewrite_plain_get=True,
            presentation_remaining=500000000,
            presentation_byte_base=500000000,
            duration_minutes=120,
        )
        with patch.object(views, "_register_stats_client") as register_mock, \
             patch.object(views, "_unregister_stats_client"):
            response = views._stream_from_provider(**kwargs)
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(register_mock.call_args.kwargs.get("range_start"))

    @patch.object(views, "_open_upstream")
    def test_expired_final_url_falls_back_to_portal(self, mocked_open):
        cdn = "http://cdn.example.test/expired.ts"
        portal = self.kwargs["candidate_urls"][0]
        redis = _FakeRedis()
        session_id = "sess-cdn-expire"
        redis.hset(views._pool_key(session_id), "final_url", cdn)
        mocked_open.side_effect = [
            _fake_upstream(403, url=cdn),
            _fake_upstream(200, body=_make_ts_payload(), url=cdn + "?fresh=1"),
        ]
        with patch.object(views, "_register_stats_client"), \
             patch.object(views, "_unregister_stats_client"):
            response = views._stream_from_provider(
                **self.kwargs,
                final_url=cdn,
                redis_client=redis,
                pool_session_id=session_id,
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(mocked_open.call_count, 2)
        self.assertEqual(mocked_open.call_args_list[0].args[0], cdn)
        self.assertEqual(mocked_open.call_args_list[1].args[0], portal)
        self.assertTrue(
            mocked_open.call_args_list[1].kwargs.get("allow_redirects", True)
        )
        # Fresh portal response re-stores CDN URL.
        self.assertEqual(
            redis.hget(views._pool_key(session_id), "final_url"),
            cdn + "?fresh=1",
        )

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
        # hard 500), so the cascade must keep trying - the next timestamp
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

    @patch.object(views, "close_old_connections")
    @patch.object(views, "_open_upstream")
    def test_streaming_response_closes_db_before_return(
        self, mocked_open, mock_close,
    ):
        mocked_open.side_effect = [_fake_upstream(200, body=_make_ts_payload())]
        with patch.object(views, "RedisClient"), \
             patch.object(views, "_register_stats_client"), \
             patch.object(views, "_unregister_stats_client"):
            response = views._stream_from_provider(**self.kwargs)
        self.assertEqual(response.status_code, 200)
        mock_close.assert_called_once()

    @patch.object(views, "close_old_connections")
    @patch.object(views, "_open_upstream")
    def test_upstream_failure_closes_db_before_return(self, mocked_open, mock_close):
        mocked_open.return_value = _fake_upstream(404)
        response = views._stream_from_provider(**self.kwargs)
        self.assertEqual(response.status_code, 404)
        mock_close.assert_called_once()

    @patch.object(views, "close_old_connections")
    @patch.object(views, "_open_upstream")
    def test_passthrough_416_closes_db_before_return(self, mocked_open, mock_close):
        upstream = _fake_upstream(416)
        upstream.headers["Content-Range"] = "bytes */1000"
        mocked_open.return_value = upstream
        response = views._stream_from_provider(**self.kwargs)
        self.assertEqual(response.status_code, 416)
        mock_close.assert_called_once()

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
        the list so the cached winner is tried first - saving cascade
        overhead on fast-forward."""
        # locmem cache: isolates this test from the shared Redis-backed django
        # cache (which persists across runs and parallel test sessions).
        from django.core.cache import cache as django_cache
        django_cache.delete(TimeshiftRedisKeys.format_cache(999))

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
        # immediately - no cascade.
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

    @patch.object(views, "_iter_upstream_with_stop")
    @patch.object(views, "_open_upstream")
    def test_partial_206_with_sync_in_peek_not_trimmed(
        self, mocked_open, mock_iter,
    ):
        # Near-EOF range probes often land on a TS sync byte mid-buffer. The
        # partial-response path must win over sync trimming or Content-Length
        # will not match bytes actually streamed.
        preamble = b"\x00" * 80
        peek = preamble + _make_ts_payload(1024 - len(preamble))
        self.assertGreater(_find_ts_sync(peek), 0)
        resp = _fake_upstream(206, body=peek)
        resp.raw = MagicMock()
        resp.raw.read = MagicMock(return_value=peek)
        resp.headers["Content-Length"] = str(len(peek) + 500)
        resp.headers["Content-Range"] = "bytes 1000-1599/2000"
        mocked_open.return_value = resp
        mock_iter.return_value = iter([])
        kwargs = dict(self.kwargs, range_header="bytes=1000-")
        with patch.object(views, "RedisClient"), \
             patch.object(views, "_register_stats_client"), \
             patch.object(views, "_unregister_stats_client"):
            response = views._stream_from_provider(**kwargs)
        list(response.streaming_content)
        self.assertEqual(response.status_code, 206)
        mock_iter.assert_called_once()
        self.assertEqual(mock_iter.call_args.kwargs.get("peek_data"), peek)
        self.assertEqual(response["Content-Length"], str(len(peek) + 500))
        self.assertEqual(response["Content-Range"], "bytes 1000-1599/2000")

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
    """`_redact_url` is the guard that keeps XC credentials out of logs  - 
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
    stream.m3u_account_id = account_id
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
        self.ttl = {}

    def setex(self, key, ttl, value):
        self.store[key] = str(value)
        self.ttl[key] = ttl

    def set(self, key, value):
        self.store[key] = str(value)

    def get(self, key):
        return self.store.get(key)

    def delete(self, *keys):
        removed = 0
        for key in keys:
            if self.store.pop(key, None) is not None:
                self.ttl.pop(key, None)
                removed += 1
        return removed

    def eval(self, script, numkeys, *keys_and_args):
        if numkeys != 1 or len(keys_and_args) != 2:
            raise NotImplementedError("FakeRedis eval only supports claim script")
        key, token = keys_and_args
        current = self.store.get(key)
        if current is not None and str(current) == str(token):
            self.store.pop(key, None)
            return 1
        return 0

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

    def incr(self, key):
        current = self.store.get(key, 0)
        try:
            current = int(current)
        except (TypeError, ValueError):
            current = 0
        new_value = current + 1
        self.store[key] = str(new_value)
        return new_value

    def hget(self, key, field):
        hash_value = self.store.get(key)
        return hash_value.get(field) if isinstance(hash_value, dict) else None

    def hdel(self, key, *fields):
        hash_value = self.store.get(key)
        if not isinstance(hash_value, dict):
            return 0
        return sum(1 for f in fields if hash_value.pop(f, None) is not None)

    def expire(self, key, ttl):
        if key in self.store:
            self.ttl[key] = ttl
            return 1
        return 0

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

    def hset(self, key, field=None, value=None, mapping=None, **kwargs):
        self._ops.append(("hset", key, field, value, mapping, kwargs))

    def sadd(self, key, member):
        self._ops.append(("sadd", key, member))

    def expire(self, key, ttl):
        self._ops.append(("expire", key, ttl))

    def setex(self, key, ttl, value):
        self._ops.append(("setex", key, ttl, value))

    def hdel(self, key, *fields):
        self._ops.append(("hdel", key, fields))

    def hincrby(self, key, field, amount=1):
        self._ops.append(("hincrby", key, field, amount))

    def execute(self):
        results = []
        for op in self._ops:
            if op[0] == "get":
                results.append(self._redis.get(op[1]))
            elif op[0] == "delete":
                results.append(self._redis.delete(op[1]))
            elif op[0] == "hset":
                _, key, field, value, mapping, kwargs = op
                results.append(self._redis.hset(key, field, value, mapping=mapping, **kwargs))
            elif op[0] == "sadd":
                _, key, member = op
                results.append(self._redis.sadd(key, member))
            elif op[0] == "expire":
                _, key, ttl = op
                results.append(self._redis.expire(key, ttl))
            elif op[0] == "setex":
                _, key, ttl, value = op
                results.append(self._redis.setex(key, ttl, value))
            elif op[0] == "hdel":
                _, key, fields = op
                results.append(self._redis.hdel(key, *fields))
            elif op[0] == "hincrby":
                _, key, field, amount = op
                results.append(self._redis.hincrby(key, field, amount))
        self._ops = []
        return results


def _fake_creds(acc, prof):
    """Distinguishable per-account credentials, mirroring what
    get_transformed_credentials returns for the reserved profile."""
    return (f"http://a{acc.id}.test", f"u{acc.id}", "p")


class TimeshiftProxyTimestampWiringTests(TestCase):
    """`timeshift_proxy` must convert the client's UTC timestamp to the
    serving provider's zone for the upstream URL, while keeping the ORIGINAL
    UTC timestamp for the EPG duration lookup - the only timezone conversion
    in the chain."""

    def setUp(self):
        self.factory = RequestFactory()

    def _call(self, timestamp, provider_tz="Europe/Brussels"):
        request = self.factory.get(f"/timeshift/u/p/8/{timestamp}/8.ts?session_id={TEST_SESSION_ID}")
        sentinel = MagicMock(status_code=200)
        with patch.object(views, "_authenticate_user", return_value=MagicMock(id=5)), \
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
        # The EPG is stored in UTC - the duration lookup must NOT receive the
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
        with patch.object(views, "_authenticate_user", return_value=MagicMock(id=5)), \
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
        with patch.object(views, "_authenticate_user", return_value=MagicMock(id=5)), \
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


class TimeshiftProxyQueryRoutingTests(TestCase):
    """QUERY-layout ``/streaming/timeshift.php`` must resolve to
    ``timeshift_proxy_query``; PATH-layout ``/timeshift/...`` must still
    resolve to ``timeshift_proxy``."""

    def test_query_style_path_resolves_to_timeshift_proxy_query(self):
        match = resolve("/streaming/timeshift.php")
        self.assertIs(match.func, views.timeshift_proxy_query)

    def test_path_style_still_resolves_to_timeshift_proxy(self):
        match = resolve("/timeshift/u/p/8/2026-06-08:17-00/8.ts")
        self.assertIs(match.func, views.timeshift_proxy)


class TimeshiftProxyQueryParamMappingTests(TestCase):
    """`timeshift_proxy_query` must extract the same fields from the
    querystring that `timeshift_proxy` receives as URL kwargs, and reject
    the request before touching auth/DB when required params are absent."""

    def setUp(self):
        self.factory = RequestFactory()

    def test_delegates_with_mapped_params(self):
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
        with patch.object(views, "_timeshift_proxy_impl", return_value=HttpResponse()) as impl:
            views.timeshift_proxy_query(request)
        impl.assert_called_once_with(request, "u", "p", "2026-06-08:17-00", "8")

    def test_missing_stream_param_returns_400_without_touching_impl(self):
        request = self.factory.get(
            "/streaming/timeshift.php",
            {"username": "u", "password": "p", "start": "2026-06-08:17-00"},
        )
        with patch.object(views, "_timeshift_proxy_impl") as impl:
            response = views.timeshift_proxy_query(request)
        self.assertEqual(response.status_code, 400)
        impl.assert_not_called()


class TimeshiftProxyFailoverTests(TestCase):
    """When the first catch-up stream's provider cannot serve the archive,
    the proxy must fail over to the channel's next catch-up stream - each
    attempt with its own provider context."""

    def setUp(self):
        self.factory = RequestFactory()

    def _call(self, streams, provider_responses):
        request = self.factory.get(_proxy_url())
        with patch.object(views, "_authenticate_user", return_value=MagicMock(id=5)), \
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
    """Shared driver for tests exercising the failover loop end to end  - 
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
        with patch.object(views, "_authenticate_user", return_value=MagicMock(id=5)), \
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
        # second stream - that would hammer a banning provider - but a
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
        # specific - the same account's other variant may still have it.
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
            client_user_agent="test-client-agent",
            range_header=None,
            virtual_channel_id="1_2026-05-12-17-00_1",
            client_id="test456",
            client_ip="127.0.0.1",
            user=None,
            channel_display_name="Test",
            timestamp_utc="2026-05-12:17-00",
            channel_logo_id=None,
            m3u_profile_id=None,
            channel_id=1,
            channel_uuid="00000000-0000-0000-0000-000000000001",
            debug=False,
        )

    @patch.object(views, "_open_upstream")
    def test_406_is_decisive_and_marks_response(self, mocked_open):
        # 406 = IP-wide block in the XC ban escalation - single attempt,
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
    order - channelstream order, catch-up streams only, active accounts only."""

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
    _user_can_access_channel (user_level gate) - exercised against real models
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
        # if the caller guesses any string - there is nothing to compare to.
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

    POOL_KEY = f"timeshift:pool:{TEST_SESSION_ID}"

    def _pool_entry_ids(self):
        return [k for k in self.fake_redis.store if k.startswith("timeshift:pool:")]

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
        # decisive - capacity is transient, unlike a ban-class status.
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
        # must release the slot before propagating - otherwise the counter
        # (no TTL) leaks until the next Redis flush.
        streams = [_make_catchup_stream(account_id=1, stream_id="111", profile_id=31)]
        with self.assertRaises(RuntimeError):
            self._call(streams, RuntimeError("boom"))
        self.release_mock.assert_called_once_with(31, self.fake_redis)
        self.assertEqual(self._pool_entry_ids(), [])

    def test_exception_before_upstream_releases_slot(self):
        # Same guarantee for failures BEFORE the upstream call (URL building,
        # credential resolution, user-agent lookup) - the guarded window
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
        return f"timeshift:pool:{self.session_id}"

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

    def test_refresh_pool_ttl_extends_busy_session(self):
        _seed_pool_session(self.redis, session_id=self.session_id, busy="1")
        self.redis.hset(self._pool_key(), "last_activity", "1.0")
        views._refresh_pool_session_ttl(self.redis, self.session_id)
        self.assertGreater(
            float(self.redis.hget(self._pool_key(), "last_activity")), 1.0,
        )

    def test_refresh_pool_ttl_extends_idle_session(self):
        _seed_pool_session(self.redis, session_id=self.session_id, busy="0")
        self.redis.hset(self._pool_key(), "last_activity", "1.0")
        views._refresh_pool_session_ttl(self.redis, self.session_id)
        self.assertGreater(
            float(self.redis.hget(self._pool_key(), "last_activity")), 1.0,
        )

    def test_refresh_pool_ttl_skips_missing_entry(self):
        views._refresh_pool_session_ttl(self.redis, self.session_id)
        self.assertNotIn(self._pool_key(), self.redis.store)

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

    def test_same_session_programme_hop_leaves_stats_to_pool(self):
        connections = [
            self._conn("8_same", "same"),
        ]
        with patch.object(views, "get_user_active_connections",
                          return_value=connections), \
             patch.object(views, "_unregister_stats_client") as unregister_mock:
            views._terminate_previous_timeshift_sessions(
                self.redis, self.user, 8, "8_2026-06-08-17-30",
                "same",
            )
        unregister_mock.assert_not_called()
        from apps.timeshift.redis_keys import TimeshiftRedisKeys as RedisKeys, TimeshiftRedisKeys
        stop_key = RedisKeys.client_stop(
            "8_2026-06-08-17-00_111", "same",
        )
        self.assertNotIn(stop_key, self.redis.store)

    def test_displaces_other_positions_on_same_channel(self):
        from apps.timeshift.redis_keys import TimeshiftRedisKeys as RedisKeys, TimeshiftRedisKeys

        old_client = "old1"
        stats_channel_id = views.stats_channel_id(8, old_client)
        programme_vid = "8_2026-06-08-17-00_111"
        client_key = RedisKeys.client_metadata(stats_channel_id, old_client)
        self.redis.hset(client_key, "programme_vid", programme_vid)

        connections = [
            self._conn(stats_channel_id, old_client),
            self._conn("9_2026-06-08-17-00_222", "other"),
            self._conn("42", "live_client", conn_type="live"),
        ]
        with patch.object(views, "get_user_active_connections",
                          return_value=connections) as conns_mock, \
             patch.object(views, "release_profile_slot") as release_mock, \
             patch.object(views, "_unregister_stats_client") as unregister_mock:
            views._terminate_previous_timeshift_sessions(
                self.redis, self.user, 8, "8_2026-06-09-20-00", "current",
            )
        conns_mock.assert_called_once_with(5)
        # Takeover defers slot release to the displaced generator's stop path;
        # it only drops stats and signals the stop key.
        release_mock.assert_not_called()
        unregister_mock.assert_called_once_with(
            self.redis, stats_channel_id, old_client,
        )
        stop_key = RedisKeys.client_stop(programme_vid, old_client)
        self.assertIn(stop_key, self.redis.store)
        # Channel 9's session untouched: no stop key set for it.
        other_stop = RedisKeys.client_stop(
            "9_2026-06-08-17-00_222", "other"
        )
        self.assertNotIn(other_stop, self.redis.store)

    def test_leaves_sibling_requests_of_current_playback(self):
        # Concurrent range/probe requests of the SAME playback must not
        # displace one another.
        connections = [
            self._conn("8_2026-06-08-17-00_111", "sibling"),
        ]
        with patch.object(views, "get_user_active_connections",
                          return_value=connections), \
             patch.object(views, "release_profile_slot") as release_mock, \
             patch.object(views, "_unregister_stats_client") as unregister_mock:
            views._terminate_previous_timeshift_sessions(
                self.redis, self.user, 8, "8_2026-06-08-17-00",
                "sibling",
            )
        release_mock.assert_not_called()
        unregister_mock.assert_not_called()

    def test_channel_id_prefix_cannot_match_other_channels(self):
        # Channel 8 must not displace channel 80/81 sessions (prefix ends
        # with an underscore).
        connections = [
            self._conn("80_2026-06-08-17-00_111", "c80"),
        ]
        with patch.object(views, "get_user_active_connections",
                          return_value=connections), \
             patch.object(views, "release_profile_slot") as release_mock, \
             patch.object(views, "_unregister_stats_client") as unregister_mock:
            views._terminate_previous_timeshift_sessions(
                self.redis, self.user, 8, "8_2026-06-08-17-00",
                "new",
            )
        release_mock.assert_not_called()
        unregister_mock.assert_not_called()

    def test_noop_without_redis_or_user(self):
        with patch.object(views, "get_user_active_connections") as conns_mock:
            views._terminate_previous_timeshift_sessions(
                None, self.user, 8, "8_ts", "s"
            )
            views._terminate_previous_timeshift_sessions(
                self.redis, None, 8, "8_ts", "s"
            )
        conns_mock.assert_not_called()

    def test_proxy_runs_takeover_before_stream_limit_check(self):
        # Order matters: with terminate_on_limit_exceeded=False a seek must
        # displace its own predecessor BEFORE the limit check counts it, or
        # the user's own seek gets denied.
        call_order = []
        request = RequestFactory().get(_proxy_url())
        with patch.object(views, "_authenticate_user", return_value=MagicMock(id=5)), \
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
        return f"timeshift:pool:{self.SESSION}"

    def _make_idle_entry(self):
        _seed_pool_session(self.redis, session_id=self.SESSION)
        with patch.object(views, "release_profile_slot"):
            views._release_pool_session(self.redis, self.SESSION, 31)

    def test_store_pool_provider_user_agent_snapshots_resolved_value(self):
        _seed_pool_session(self.redis, session_id=self.SESSION)
        views._store_pool_provider_user_agent(
            self.redis, self.SESSION, "provider-agent",
        )
        self.assertEqual(
            self.redis.hget(self._pool_key(), "provider_user_agent"),
            "provider-agent",
        )

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
            acquired = views._acquire_idle_pool_session(
                self.redis, self.SESSION, user_id=5,
            )
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
            acquired = views._acquire_idle_pool_session(
                self.redis, self.SESSION, user_id=5,
            )
        self.assertIsNone(acquired)
        prof_mock.assert_not_called()
        reserve_mock.assert_not_called()

    def test_acquire_rejects_foreign_user(self):
        self._make_idle_entry()
        profile = MagicMock(id=31)
        with patch.object(views.M3UAccountProfile.objects, "get",
                          return_value=profile), \
             patch.object(views, "reserve_profile_slot",
                          return_value=(True, 1, None)) as reserve_mock:
            acquired = views._acquire_idle_pool_session(
                self.redis, self.SESSION, user_id=99,
            )
        self.assertIsNone(acquired)
        reserve_mock.assert_not_called()

    def test_foreign_session_id_redirects_instead_of_reusing_pool(self):
        victim_session = "victim_session"
        _seed_pool_session(self.redis, session_id=victim_session, user_id=99)
        request = self.factory.get(_proxy_url(victim_session))
        attacker = MagicMock(id=5)
        with patch.object(views, "_authenticate_user", return_value=attacker), \
             patch.object(views, "network_access_allowed", return_value=True), \
             patch.object(views, "Channel") as channel_cls, \
             patch.object(views, "_user_can_access_channel", return_value=True), \
             patch.object(views, "get_channel_catchup_streams",
                          return_value=[_make_catchup_stream()]), \
             patch.object(views, "get_programme_duration", return_value=40), \
             patch.object(views, "parse_catchup_timestamp", return_value=True), \
             patch.object(views, "RedisClient") as redis_cls, \
             patch.object(views, "_acquire_idle_pool_session") as acquire_mock, \
             patch.object(views, "_attempt_timeshift_stream") as attempt_mock:
            redis_cls.get_client.return_value = self.redis
            channel_cls.objects.get.return_value = MagicMock(id=8)
            response = views.timeshift_proxy(
                request, "u", "p", "8", "2026-06-08:17-00", "8.ts",
            )
        self.assertEqual(response.status_code, 301)
        self.assertIn("session_id=", response["Location"])
        self.assertNotIn(victim_session, response["Location"])
        acquire_mock.assert_not_called()
        attempt_mock.assert_not_called()

    def test_find_matching_pool_session_idle_requires_ip_and_user_agent(self):
        _seed_pool_session(
            self.redis, session_id="other",
            user_id=5, client_ip="1.2.3.4", client_user_agent="test-agent",
        )
        with patch.object(views, "release_profile_slot"):
            views._release_pool_session(self.redis, "other", 31)
        matched = views._find_matching_pool_session(
            self.redis,
            media_id=TEST_MEDIA_ID,
            user_id=5,
            client_ip="1.2.3.4",
            client_user_agent="test-agent",
            include_busy=False,
        )
        self.assertEqual(matched, "other")

    def test_find_matching_pool_session_idle_rejects_ip_only_partial_fingerprint(self):
        _seed_pool_session(
            self.redis, session_id="other",
            user_id=5, client_ip="1.2.3.4", client_user_agent="other-agent",
        )
        with patch.object(views, "release_profile_slot"):
            views._release_pool_session(self.redis, "other", 31)
        matched = views._find_matching_pool_session(
            self.redis,
            media_id=TEST_MEDIA_ID,
            user_id=5,
            client_ip="1.2.3.4",
            client_user_agent="test-agent",
            include_busy=False,
        )
        self.assertIsNone(matched)

    def test_find_matching_pool_session_idle_rejects_different_user(self):
        _seed_pool_session(
            self.redis, session_id="other",
            user_id=99, client_ip="1.2.3.4", client_user_agent="test-agent",
        )
        with patch.object(views, "release_profile_slot"):
            views._release_pool_session(self.redis, "other", 31)
        matched = views._find_matching_pool_session(
            self.redis,
            media_id=TEST_MEDIA_ID,
            user_id=5,
            client_ip="1.2.3.4",
            client_user_agent="test-agent",
            include_busy=False,
        )
        self.assertIsNone(matched)

    def test_find_matching_pool_session_fresh_session_skips_idle_exact_media(self):
        _seed_pool_session(
            self.redis, session_id="old",
            user_id=5, client_ip="1.2.3.4", client_user_agent="test-agent",
        )
        with patch.object(views, "release_profile_slot"):
            views._release_pool_session(self.redis, "old", 31)
        matched = views._find_matching_pool_session(
            self.redis,
            media_id=TEST_MEDIA_ID,
            channel_id=8,
            user_id=5,
            client_ip="1.2.3.4",
            client_user_agent="test-agent",
            include_busy=True,
            fresh_session=True,
        )
        self.assertIsNone(matched)

    def test_find_matching_pool_session_fresh_session_keeps_busy_exact_media(self):
        _seed_pool_session(
            self.redis, session_id="busy",
            user_id=5, client_ip="1.2.3.4", client_user_agent="test-agent",
            busy="1",
        )
        matched = views._find_matching_pool_session(
            self.redis,
            media_id=TEST_MEDIA_ID,
            channel_id=8,
            user_id=5,
            client_ip="1.2.3.4",
            client_user_agent="test-agent",
            include_busy=True,
            fresh_session=True,
        )
        self.assertEqual(matched, "busy")

    def test_find_matching_pool_session_fresh_session_keeps_channel_hop_idle(self):
        _seed_pool_session(
            self.redis, session_id="old",
            media_id="8_2026-06-08-17-00",
            user_id=5, client_ip="1.2.3.4", client_user_agent="test-agent",
        )
        with patch.object(views, "release_profile_slot"):
            views._release_pool_session(self.redis, "old", 31)
        matched = views._find_matching_pool_session(
            self.redis,
            media_id="8_2026-06-08-17-30",
            channel_id=8,
            user_id=5,
            client_ip="1.2.3.4",
            client_user_agent="test-agent",
            include_busy=True,
            fresh_session=True,
        )
        self.assertEqual(matched, "old")

    def test_fresh_session_id_does_not_adopt_idle_exact_media_pool(self):
        """FF race: redirect mints a new session, then reconnects to
        the old programme timestamp before the real seek arrives. Must not
        fingerprint-adopt the idle pool from the previous session."""
        old_session = "oldrewsession1"
        new_session = "newafterredirect1"
        _seed_pool_session(
            self.redis,
            session_id=old_session,
            user_id=5,
            client_ip="1.2.3.4",
            client_user_agent="test-agent",
        )
        with patch.object(views, "release_profile_slot"):
            views._release_pool_session(self.redis, old_session, 31)

        request = self.factory.get(
            _proxy_url(new_session),
            HTTP_USER_AGENT="test-agent",
            REMOTE_ADDR="1.2.3.4",
        )
        streams = [_make_catchup_stream(account_id=1, stream_id="111", profile_id=31)]
        ok = MagicMock(status_code=200)
        with patch.object(views, "_authenticate_user", return_value=self.user), \
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
             patch.object(views, "_attempt_timeshift_stream", return_value=ok) as attempt_mock, \
             patch.object(views, "_acquire_idle_pool_session") as acquire_mock:
            redis_cls.get_client.return_value = self.redis
            channel_cls.objects.get.return_value = MagicMock(
                id=8, name="Test", logo_id=None,
            )
            response = views.timeshift_proxy(
                request, "u", "p", "8", "2026-06-08:17-00", "8.ts",
            )
        self.assertIs(response, ok)
        acquire_mock.assert_not_called()
        self.assertEqual(
            attempt_mock.call_args.kwargs["client_id"],
            new_session,
        )
        self.assertTrue(self.redis.exists(f"timeshift:pool:{new_session}"))

    def test_find_matching_pool_session_finds_busy_pool_on_same_channel(self):
        _seed_pool_session(
            self.redis, session_id="busy",
            media_id="8_2026-06-08-17-00",
            user_id=5, client_ip="1.2.3.4", client_user_agent="test-agent",
            busy="1",
        )
        matched = views._find_matching_pool_session(
            self.redis,
            media_id="8_2026-06-08-17-30",
            channel_id=8,
            user_id=5,
            client_ip="1.2.3.4",
            client_user_agent="test-agent",
            include_busy=True,
        )
        self.assertEqual(matched, "busy")

    def test_find_matching_pool_session_finds_busy_pool(self):
        _seed_pool_session(
            self.redis, session_id="busy",
            user_id=5, client_ip="1.2.3.4", client_user_agent="test-agent",
            busy="1",
        )
        matched = views._find_matching_pool_session(
            self.redis,
            media_id=TEST_MEDIA_ID,
            user_id=5,
            client_ip="1.2.3.4",
            client_user_agent="test-agent",
            include_busy=True,
        )
        self.assertEqual(matched, "busy")
        self.assertIsNone(
            views._find_matching_pool_session(
                self.redis,
                media_id=TEST_MEDIA_ID,
                user_id=5,
                client_ip="1.2.3.4",
                client_user_agent="test-agent",
                include_busy=False,
            )
        )

    def test_legacy_pool_entry_exists_helper_removed(self):
        self.assertFalse(hasattr(views, "_pool_entry_exists"))

    def test_new_session_uses_single_hgetall_before_pool_create(self):
        redis = _FakeRedis()
        request = self.factory.get(_proxy_url("newsession1"))
        with patch.object(views, "_authenticate_user", return_value=MagicMock(id=5)), \
             patch.object(views, "network_access_allowed", return_value=True), \
             patch.object(views, "Channel") as channel_cls, \
             patch.object(views, "_user_can_access_channel", return_value=True), \
             patch.object(views, "get_channel_catchup_streams",
                          return_value=[_make_catchup_stream()]), \
             patch.object(views, "get_programme_duration", return_value=40), \
             patch.object(views, "check_user_stream_limits", return_value=True), \
             patch.object(views, "_find_matching_pool_session", return_value=None), \
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
        pool_key = "timeshift:pool:newsession1"
        self.assertEqual(
            sum(1 for c in hgetall_mock.call_args_list if c.args == (pool_key,)),
            1,
        )

    def test_reuse_decisive_failure_skips_same_account_in_failover(self):
        _seed_pool_session(self.redis, session_id=TEST_SESSION_ID)
        with patch.object(views, "release_profile_slot"):
            views._release_pool_session(self.redis, TEST_SESSION_ID, 31)

        streams = [
            _make_catchup_stream(account_id=1, stream_id="111", profile_id=31),
            _make_catchup_stream(account_id=1, stream_id="112", profile_id=31),
            _make_catchup_stream(account_id=2, stream_id="222", profile_id=41),
        ]
        profile = MagicMock(id=31, custom_properties={})
        account = MagicMock(id=1)
        decisive = MagicMock(status_code=403)
        decisive.timeshift_decisive = True
        ok = MagicMock(status_code=200)
        request = self.factory.get(_proxy_url(TEST_SESSION_ID))
        with patch.object(views, "_authenticate_user", return_value=self.user), \
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
             patch.object(views.M3UAccount.objects, "get", return_value=account), \
             patch.object(views.M3UAccountProfile.objects, "get",
                          return_value=profile), \
             patch.object(views, "get_transformed_credentials", side_effect=_fake_creds), \
             patch.object(views, "get_user_active_connections", return_value=[]), \
             patch.object(views, "build_timeshift_candidate_urls",
                          return_value=["http://example.test/x.ts"]), \
             patch.object(views, "_stream_from_provider",
                          side_effect=[decisive, ok]) as stream_mock:
            redis_cls.get_client.return_value = self.redis
            channel_cls.objects.get.return_value = MagicMock(
                id=8, name="Test", logo_id=None,
            )
            response = views.timeshift_proxy(
                request, "u", "p", "8", "2026-06-08:17-00", "8.ts",
            )
        self.assertIs(response, ok)
        self.assertEqual(stream_mock.call_count, 2)
        self.assertEqual(
            [c.kwargs["account_id"] for c in stream_mock.call_args_list], [1, 2]
        )
        # Reuse reserved once; failover reserved only for the other account.
        self.assertEqual(reserve_mock.call_count, 2)

    def _call_reused_session(self, timestamp, media_id):
        """Drive _stream_reused_session against a session anchored at 17-00
        (provider position 19-00) with a NEW requested timestamp."""
        profile = MagicMock(id=31, custom_properties={})
        account = MagicMock(id=1)
        ok = MagicMock(status_code=200)
        with patch.object(views.M3UAccount.objects, "get", return_value=account), \
             patch.object(views, "_attempt_timeshift_stream",
                          return_value=ok) as attempt_mock:
            response = views._stream_reused_session(
                self.redis,
                session_id=self.SESSION,
                descriptor={
                    "account_id": "1",
                    "stream_id": "111",
                    "provider_timestamp": "2026-06-08:19-00",
                    "provider_tz_name": "Europe/Brussels",
                },
                profile=profile,
                channel=self.channel,
                media_id=media_id,
                safe_ts=timestamp.replace(":", "-"),
                timestamp=timestamp,
                duration_minutes=40,
                client_id=self.SESSION,
                client_ip="1.2.3.4",
                client_user_agent="test-agent",
                range_header=None,
                channel_logo_id=None,
                user=self.user,
                debug=False,
            )
        return response, ok, attempt_mock

    def test_session_scrub_reuses_final_url_and_injects_range(self):
        # Client FF rebuilds /timeshift/.../<new_start>/... with the same
        # session_id. That must Range-seek the open CDN archive, not portal.
        _seed_pool_session(self.redis, session_id=self.SESSION)
        cdn = "http://cdn.example/archive.ts?token=ok"
        self.redis.hset(self._pool_key(), mapping={
            "final_url": cdn,
            "content_length": "1800000000",
            "archive_anchor_ts": "2026-06-08:17-00",
            "archive_duration_secs": "3600",
        })
        profile = MagicMock(id=31, custom_properties={})
        account = MagicMock(id=1)
        ok = MagicMock(status_code=200)
        with patch.object(views.M3UAccount.objects, "get", return_value=account), \
             patch.object(views, "_attempt_timeshift_stream",
                          return_value=ok) as attempt_mock:
            views._stream_reused_session(
                self.redis,
                session_id=self.SESSION,
                descriptor={
                    "account_id": "1",
                    "stream_id": "111",
                    "media_id": TEST_MEDIA_ID,
                    "provider_timestamp": "2026-06-08:19-00",
                    "provider_tz_name": "Europe/Brussels",
                    "final_url": cdn,
                    "content_length": "1800000000",
                    "archive_anchor_ts": "2026-06-08:17-00",
                    "archive_duration_secs": "3600",
                },
                profile=profile,
                channel=self.channel,
                media_id="8_2026-06-08-17-30",
                safe_ts="2026-06-08-17-30",
                timestamp="2026-06-08:17-30",
                duration_minutes=40,
                client_id=self.SESSION,
                client_ip="1.2.3.4",
                client_user_agent="test-agent",
                range_header=None,
                channel_logo_id=None,
                user=self.user,
                debug=False,
            )
        kwargs = attempt_mock.call_args.kwargs
        self.assertEqual(kwargs.get("final_url"), cdn)
        self.assertTrue(kwargs.get("rewrite_plain_get"))
        self.assertTrue(kwargs.get("range_header", "").startswith("bytes="))
        self.assertIsNotNone(kwargs.get("presentation_remaining"))
        self.assertIsNotNone(kwargs.get("presentation_byte_base"))
        # Archive CDN state must survive the media_id move.
        self.assertEqual(self.redis.hget(self._pool_key(), "final_url"), cdn)

    def test_session_scrub_reuses_opaque_final_url(self):
        """Opaque CDNs still scrub via Range on the cached URL (no portal hop)."""
        _seed_pool_session(self.redis, session_id=self.SESSION)
        opaque = "http://opaque-cdn.example/hash/token/t5/test-stream/serve"
        self.redis.hset(self._pool_key(), mapping={
            "final_url": opaque,
            "content_length": "722718720",
            "archive_anchor_ts": "2026-06-08:17-00",
            "archive_duration_secs": "2100",
        })
        profile = MagicMock(id=31, custom_properties={})
        account = MagicMock(id=1)
        ok = MagicMock(status_code=200)
        with patch.object(views.M3UAccount.objects, "get", return_value=account), \
             patch.object(views, "_attempt_timeshift_stream",
                          return_value=ok) as attempt_mock:
            views._stream_reused_session(
                self.redis,
                session_id=self.SESSION,
                descriptor={
                    "account_id": "1",
                    "stream_id": "111",
                    "media_id": TEST_MEDIA_ID,
                    "provider_timestamp": "2026-06-08:19-00",
                    "provider_tz_name": "Europe/Brussels",
                    "final_url": opaque,
                    "content_length": "722718720",
                    "archive_anchor_ts": "2026-06-08:17-00",
                    "archive_duration_secs": "2100",
                },
                profile=profile,
                channel=self.channel,
                media_id="8_2026-06-08-17-11",
                safe_ts="2026-06-08-17-11",
                timestamp="2026-06-08:17-11",
                duration_minutes=35,
                client_id=self.SESSION,
                client_ip="1.2.3.4",
                client_user_agent="test-agent",
                range_header=None,
                channel_logo_id=None,
                user=self.user,
                debug=False,
            )
        kwargs = attempt_mock.call_args.kwargs
        self.assertEqual(kwargs.get("final_url"), opaque)
        self.assertTrue(kwargs.get("rewrite_plain_get"))
        self.assertTrue(str(kwargs.get("range_header") or "").startswith("bytes="))

    def test_session_range_after_scrub_maps_through_presentation_base(self):
        # After a scrub rewrite, near-EOF probes are relative to the presented
        # window, not the full CDN file.
        _seed_pool_session(self.redis, session_id=self.SESSION)
        cdn = "http://cdn.example/archive.ts?token=ok"
        base = 314_934_968
        remaining = 419_913_672
        self.redis.hset(self._pool_key(), mapping={
            "final_url": cdn,
            "content_length": str(base + remaining),
            "archive_anchor_ts": "2026-06-08:17-00",
            "archive_duration_secs": "3600",
            "presentation_length": str(remaining),
            "presentation_byte_base": str(base),
            "media_id": "8_2026-06-08-17-30",
        })
        profile = MagicMock(id=31, custom_properties={})
        account = MagicMock(id=1)
        ok = MagicMock(status_code=206)
        client_range = f"bytes={remaining - 112_800}-"
        with patch.object(views.M3UAccount.objects, "get", return_value=account), \
             patch.object(views, "_attempt_timeshift_stream",
                          return_value=ok) as attempt_mock:
            views._stream_reused_session(
                self.redis,
                session_id=self.SESSION,
                descriptor={
                    "account_id": "1",
                    "stream_id": "111",
                    "media_id": "8_2026-06-08-17-30",
                    "provider_timestamp": "2026-06-08:19-30",
                    "provider_tz_name": "Europe/Brussels",
                    "final_url": cdn,
                    "content_length": str(base + remaining),
                    "archive_anchor_ts": "2026-06-08:17-00",
                    "archive_duration_secs": "3600",
                    "presentation_length": str(remaining),
                    "presentation_byte_base": str(base),
                },
                profile=profile,
                channel=self.channel,
                media_id="8_2026-06-08-17-30",
                safe_ts="2026-06-08-17-30",
                timestamp="2026-06-08:17-30",
                duration_minutes=40,
                client_id=self.SESSION,
                client_ip="1.2.3.4",
                client_user_agent="test-agent",
                range_header=client_range,
                channel_logo_id=None,
                user=self.user,
                debug=False,
            )
        kwargs = attempt_mock.call_args.kwargs
        self.assertEqual(
            kwargs.get("range_header"),
            f"bytes={base + remaining - 112_800}-",
        )
        self.assertTrue(kwargs.get("relative_presentation_range"))
        self.assertFalse(kwargs.get("rewrite_plain_get"))
        self.assertEqual(kwargs.get("final_url"), cdn)

    def test_return_to_archive_start_resets_presentation_base(self):
        """Scrubbing back to the archive open must clear the prior scrub window."""
        _seed_pool_session(self.redis, session_id=self.SESSION)
        cdn = "http://cdn.example/archive.ts?token=ok"
        archive_total = 870_621_184
        stale_base = 348_248_380
        self.redis.hset(self._pool_key(), mapping={
            "final_url": cdn,
            "content_length": str(archive_total),
            "archive_anchor_ts": "2026-06-08:17-00",
            "archive_duration_secs": "2100",
            "presentation_length": str(archive_total - stale_base),
            "presentation_byte_base": str(stale_base),
            "media_id": "8_2026-06-08-17-14",
        })
        profile = MagicMock(id=31, custom_properties={})
        account = MagicMock(id=1)
        ok = MagicMock(status_code=200)
        with patch.object(views.M3UAccount.objects, "get", return_value=account), \
             patch.object(views, "_attempt_timeshift_stream",
                          return_value=ok) as attempt_mock:
            views._stream_reused_session(
                self.redis,
                session_id=self.SESSION,
                descriptor={
                    "account_id": "1",
                    "stream_id": "111",
                    "media_id": "8_2026-06-08-17-14",
                    "provider_timestamp": "2026-06-08:19-14",
                    "provider_tz_name": "Europe/Brussels",
                    "final_url": cdn,
                    "content_length": str(archive_total),
                    "archive_anchor_ts": "2026-06-08:17-00",
                    "archive_duration_secs": "2100",
                    "presentation_length": str(archive_total - stale_base),
                    "presentation_byte_base": str(stale_base),
                },
                profile=profile,
                channel=self.channel,
                media_id=TEST_MEDIA_ID,
                safe_ts="2026-06-08-17-00",
                timestamp="2026-06-08:17-00",
                duration_minutes=35,
                client_id=self.SESSION,
                client_ip="1.2.3.4",
                client_user_agent="test-agent",
                range_header=None,
                channel_logo_id=None,
                user=self.user,
                debug=False,
            )
        kwargs = attempt_mock.call_args.kwargs
        self.assertEqual(kwargs.get("presentation_byte_base"), 0)
        self.assertEqual(kwargs.get("presentation_remaining"), archive_total)
        self.assertIsNone(kwargs.get("range_header"))
        self.assertFalse(kwargs.get("rewrite_plain_get"))
        self.assertFalse(kwargs.get("relative_presentation_range"))

    def test_return_to_archive_start_range_skips_stale_presentation_map(self):
        """Ranges after return-to-start are archive-absolute, not scrub-relative."""
        _seed_pool_session(self.redis, session_id=self.SESSION)
        cdn = "http://cdn.example/archive.ts?token=ok"
        archive_total = 870_621_184
        stale_base = 348_248_380
        client_range = f"bytes={archive_total - 112_800}-"
        self.redis.hset(self._pool_key(), mapping={
            "final_url": cdn,
            "content_length": str(archive_total),
            "archive_anchor_ts": "2026-06-08:17-00",
            "archive_duration_secs": "2100",
            "presentation_length": str(archive_total - stale_base),
            "presentation_byte_base": str(stale_base),
            "media_id": TEST_MEDIA_ID,
        })
        profile = MagicMock(id=31, custom_properties={})
        account = MagicMock(id=1)
        ok = MagicMock(status_code=206)
        with patch.object(views.M3UAccount.objects, "get", return_value=account), \
             patch.object(views, "_attempt_timeshift_stream",
                          return_value=ok) as attempt_mock:
            views._stream_reused_session(
                self.redis,
                session_id=self.SESSION,
                descriptor={
                    "account_id": "1",
                    "stream_id": "111",
                    "media_id": TEST_MEDIA_ID,
                    "provider_timestamp": "2026-06-08:19-00",
                    "provider_tz_name": "Europe/Brussels",
                    "final_url": cdn,
                    "content_length": str(archive_total),
                    "archive_anchor_ts": "2026-06-08:17-00",
                    "archive_duration_secs": "2100",
                    "presentation_length": str(archive_total - stale_base),
                    "presentation_byte_base": str(stale_base),
                },
                profile=profile,
                channel=self.channel,
                media_id=TEST_MEDIA_ID,
                safe_ts="2026-06-08-17-00",
                timestamp="2026-06-08:17-00",
                duration_minutes=35,
                client_id=self.SESSION,
                client_ip="1.2.3.4",
                client_user_agent="test-agent",
                range_header=client_range,
                channel_logo_id=None,
                user=self.user,
                debug=False,
            )
        kwargs = attempt_mock.call_args.kwargs
        self.assertEqual(kwargs.get("range_header"), client_range)
        self.assertEqual(kwargs.get("presentation_byte_base"), 0)
        self.assertFalse(kwargs.get("relative_presentation_range"))

    def test_session_scrub_outside_window_forces_portal(self):
        _seed_pool_session(self.redis, session_id=self.SESSION)
        stale_cdn = "http://cdn.example/old.ts?token=stale"
        self.redis.hset(self._pool_key(), mapping={
            "final_url": stale_cdn,
            "content_length": "1800000000",
            "archive_anchor_ts": "2026-06-08:17-00",
            "archive_duration_secs": "1800",  # 30 min window
        })
        profile = MagicMock(id=31, custom_properties={})
        account = MagicMock(id=1)
        ok = MagicMock(status_code=200)
        with patch.object(views.M3UAccount.objects, "get", return_value=account), \
             patch.object(views, "_attempt_timeshift_stream",
                          return_value=ok) as attempt_mock:
            views._stream_reused_session(
                self.redis,
                session_id=self.SESSION,
                descriptor={
                    "account_id": "1",
                    "stream_id": "111",
                    "media_id": TEST_MEDIA_ID,
                    "provider_timestamp": "2026-06-08:19-00",
                    "provider_tz_name": "Europe/Brussels",
                    "final_url": stale_cdn,
                    "content_length": "1800000000",
                    "archive_anchor_ts": "2026-06-08:17-00",
                    "archive_duration_secs": "1800",
                },
                profile=profile,
                channel=self.channel,
                # 40 minutes after anchor, outside the 30 min archive window.
                media_id="8_2026-06-08-17-40",
                safe_ts="2026-06-08-17-40",
                timestamp="2026-06-08:17-40",
                duration_minutes=40,
                client_id=self.SESSION,
                client_ip="1.2.3.4",
                client_user_agent="test-agent",
                range_header=None,
                channel_logo_id=None,
                user=self.user,
                debug=False,
            )
        self.assertIsNone(attempt_mock.call_args.kwargs.get("final_url"))
        self.assertIsNone(self.redis.hget(self._pool_key(), "final_url"))

    def test_same_programme_reuse_keeps_final_url(self):
        _seed_pool_session(self.redis, session_id=self.SESSION)
        cdn = "http://cdn.example/same.ts?token=ok"
        self.redis.hset(self._pool_key(), mapping={
            "final_url": cdn,
            "content_length": "1000000",
            "archive_anchor_ts": "2026-06-08:17-00",
            "archive_duration_secs": "3600",
        })
        profile = MagicMock(id=31, custom_properties={})
        account = MagicMock(id=1)
        ok = MagicMock(status_code=200)
        with patch.object(views.M3UAccount.objects, "get", return_value=account), \
             patch.object(views, "_attempt_timeshift_stream",
                          return_value=ok) as attempt_mock:
            views._stream_reused_session(
                self.redis,
                session_id=self.SESSION,
                descriptor={
                    "account_id": "1",
                    "stream_id": "111",
                    "media_id": TEST_MEDIA_ID,
                    "provider_timestamp": "2026-06-08:19-00",
                    "provider_tz_name": "Europe/Brussels",
                    "final_url": cdn,
                    "content_length": "1000000",
                    "archive_anchor_ts": "2026-06-08:17-00",
                    "archive_duration_secs": "3600",
                },
                profile=profile,
                channel=self.channel,
                media_id=TEST_MEDIA_ID,
                safe_ts="2026-06-08-17-00",
                timestamp="2026-06-08:17-00",
                duration_minutes=40,
                client_id=self.SESSION,
                client_ip="1.2.3.4",
                client_user_agent="test-agent",
                range_header=None,
                channel_logo_id=None,
                user=self.user,
                debug=False,
            )
        self.assertEqual(attempt_mock.call_args.kwargs.get("final_url"), cdn)
        self.assertFalse(attempt_mock.call_args.kwargs.get("rewrite_plain_get"))

    def test_reused_session_serves_requested_timestamp_not_stored_anchor(self):
        # Field bug: rewind to X, play, then FF. Some clients keep the
        # ?session_id= query when rebuilding the seek URL with a new start,
        # and the reused session replayed the STORED position, snapping
        # playback back to the rewind anchor X. The reuse path must always
        # serve the REQUESTED timestamp.
        _seed_pool_session(self.redis, session_id=self.SESSION)
        response, ok, attempt_mock = self._call_reused_session(
            "2026-06-08:17-30", "8_2026-06-08-17-30",
        )
        self.assertIs(response, ok)
        # June -> CEST: 17:30 UTC reaches the provider as 19:30 local, never
        # the session's stored 19:00 anchor.
        self.assertEqual(
            attempt_mock.call_args.kwargs["provider_timestamp"],
            "2026-06-08:19-30",
        )

    def test_reused_session_moves_pool_entry_to_requested_position(self):
        # The descriptor must follow the seek so fingerprint matching and
        # same-channel displacement compare against the position actually
        # being served.
        _seed_pool_session(self.redis, session_id=self.SESSION)
        self._call_reused_session(
            "2026-06-08:17-30", "8_2026-06-08-17-30",
        )
        self.assertEqual(
            self.redis.hget(self._pool_key(), "media_id"),
            "8_2026-06-08-17-30",
        )
        self.assertEqual(
            self.redis.hget(self._pool_key(), "provider_timestamp"),
            "2026-06-08:19-30",
        )

    def test_position_move_drops_previous_byte_state(self):
        # content_length / serving_range / final_url describe ONE provider file;
        # carrying them across a seek would feed near-EOF heuristics another
        # programme's size and hit the wrong CDN token. Same-position keeps them.
        _seed_pool_session(self.redis, session_id=self.SESSION)
        self.redis.hset(self._pool_key(), mapping={
            "content_length": "2000000000",
            "serving_range": "start",
            "final_url": "http://cdn.example/old.ts",
        })
        self._call_reused_session(
            "2026-06-08:17-30", "8_2026-06-08-17-30",
        )
        self.assertIsNone(self.redis.hget(self._pool_key(), "content_length"))
        self.assertIsNone(self.redis.hget(self._pool_key(), "serving_range"))
        self.assertIsNone(self.redis.hget(self._pool_key(), "final_url"))

        # Same-position call (media unchanged): byte state survives.
        self.redis.hset(self._pool_key(), mapping={
            "content_length": "1000000",
            "serving_range": "range",
            "final_url": "http://cdn.example/same.ts",
        })
        self._call_reused_session(
            "2026-06-08:17-30", "8_2026-06-08-17-30",
        )
        self.assertEqual(
            self.redis.hget(self._pool_key(), "content_length"), "1000000",
        )
        self.assertEqual(
            self.redis.hget(self._pool_key(), "final_url"),
            "http://cdn.example/same.ts",
        )

    def test_position_update_never_resurrects_vanished_entry(self):
        # If the pool key expired/vanished mid-request, writing to it would
        # recreate a partial TTL-less hash that 503-wedges the session_id.
        views._update_pool_position(
            self.redis, self.SESSION,
            media_id="8_2026-06-08-17-30",
            provider_timestamp="2026-06-08:19-30",
        )
        self.assertFalse(self.redis.exists(self._pool_key()))

    def test_reused_session_tz_falls_back_to_reserved_profile(self):
        # Legacy pool entries without provider_tz_name fall back to the
        # reserved profile's server_info for conversion.
        _seed_pool_session(self.redis, session_id=self.SESSION, provider_tz_name=None)
        self.redis.hset(self._pool_key(), "provider_tz_name", "")
        profile = MagicMock(id=31, custom_properties={
            "server_info": {"timezone": "Europe/Brussels"},
        })
        account = MagicMock(id=1)
        ok = MagicMock(status_code=200)
        with patch.object(views.M3UAccount.objects, "get", return_value=account), \
             patch.object(views, "_attempt_timeshift_stream",
                          return_value=ok) as attempt_mock:
            views._stream_reused_session(
                self.redis,
                session_id=self.SESSION,
                descriptor={
                    "account_id": "1",
                    "stream_id": "111",
                    "provider_timestamp": "2026-06-08:19-00",
                },
                profile=profile,
                channel=self.channel,
                media_id="8_2026-06-08-17-30",
                safe_ts="2026-06-08-17-30",
                timestamp="2026-06-08:17-30",
                duration_minutes=40,
                client_id=self.SESSION,
                client_ip="1.2.3.4",
                client_user_agent="test-agent",
                range_header=None,
                channel_logo_id=None,
                user=self.user,
                debug=False,
            )
        self.assertEqual(
            attempt_mock.call_args.kwargs["provider_timestamp"],
            "2026-06-08:19-30",
        )

    def test_seek_same_session_new_timestamp_serves_new_position(self):
        # End-to-end repro of the field report: idle session anchored at
        # 17-00, then a timestamp-jump request for 17-30 carrying the SAME
        # session_id (no Range header).
        _seed_pool_session(self.redis, session_id=TEST_SESSION_ID)
        with patch.object(views, "release_profile_slot"):
            views._release_pool_session(self.redis, TEST_SESSION_ID, 31)

        request = self.factory.get(
            f"/timeshift/u/p/8/2026-06-08:17-30/8.ts?session_id={TEST_SESSION_ID}"
        )
        profile = MagicMock(id=31, custom_properties={})
        tz_profile = MagicMock(
            custom_properties={"server_info": {"timezone": "Europe/Brussels"}}
        )
        account = MagicMock(id=1)
        account.profiles.filter.return_value.first.return_value = tz_profile
        ok = MagicMock(status_code=200)
        with patch.object(views, "_authenticate_user", return_value=self.user), \
             patch.object(views, "network_access_allowed", return_value=True), \
             patch.object(views, "Channel") as channel_cls, \
             patch.object(views, "_user_can_access_channel", return_value=True), \
             patch.object(views, "get_channel_catchup_streams",
                          return_value=[_make_catchup_stream(
                              account_id=1, stream_id="111", profile_id=31)]), \
             patch.object(views, "get_programme_duration", return_value=40), \
             patch.object(views, "check_user_stream_limits", return_value=True), \
             patch.object(views, "RedisClient") as redis_cls, \
             patch.object(views, "reserve_profile_slot",
                          return_value=(True, 1, None)), \
             patch.object(views, "release_profile_slot"), \
             patch.object(views.M3UAccount.objects, "get", return_value=account), \
             patch.object(views.M3UAccountProfile.objects, "get",
                          return_value=profile), \
             patch.object(views, "get_user_active_connections", return_value=[]), \
             patch.object(views, "_attempt_timeshift_stream",
                          return_value=ok) as attempt_mock:
            redis_cls.get_client.return_value = self.redis
            channel_cls.objects.get.return_value = MagicMock(
                id=8, name="Test", logo_id=None,
            )
            response = views.timeshift_proxy(
                request, "u", "p", "8", "2026-06-08:17-30", "8.ts",
            )
        self.assertIs(response, ok)
        attempt_mock.assert_called_once()
        self.assertEqual(
            attempt_mock.call_args.kwargs["provider_timestamp"],
            "2026-06-08:19-30",
        )
        self.assertEqual(
            self.redis.hget(self._pool_key(), "media_id"),
            "8_2026-06-08-17-30",
        )


class TimeshiftSessionRedirectTests(TestCase):
    """Session mint (301) and inline pool adopt when session_id is omitted."""

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
        self.assertIn("session_id=", response["Location"])

    def test_missing_session_id_serves_existing_busy_pool_without_redirect(self):
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
        with patch.object(views, "_authenticate_user", return_value=MagicMock(id=1)), \
             patch.object(views, "network_access_allowed", return_value=True), \
             patch.object(views, "Channel") as channel_cls, \
             patch.object(views, "_user_can_access_channel", return_value=True), \
             patch.object(views, "get_channel_catchup_streams",
                          return_value=[_make_catchup_stream()]), \
             patch.object(views, "get_programme_duration", return_value=40), \
             patch.object(views, "parse_catchup_timestamp", return_value=True), \
             patch.object(views, "check_user_stream_limits", return_value=True), \
             patch.object(views, "RedisClient") as redis_cls, \
             patch.object(
                 views, "_try_reacquire_idle_pool",
                 return_value=(descriptor, profile),
             ) as reacquire_mock, \
             patch.object(views, "_stream_reused_session", return_value=ok) as reuse_mock:
            redis_cls.get_client.return_value = redis
            channel_cls.objects.get.return_value = MagicMock(id=8)
            response = views.timeshift_proxy(
                request, "u", "p", "8", "2026-06-08:17-00", "8.ts",
            )
        self.assertIs(response, ok)
        reacquire_mock.assert_called_once()
        reuse_mock.assert_called_once()

    def test_missing_session_id_serves_busy_pool_on_channel_hop_without_redirect(self):
        existing = "channelhop1"
        redis = _FakeRedis()
        _seed_pool_session(
            redis,
            session_id=existing,
            media_id="8_2026-06-08-17-00",
            user_id=1,
            client_ip="127.0.0.1",
            client_user_agent="vlc-test",
            busy="1",
        )
        # Programme-change preempt ignores hops within the startup window.
        redis.hset(
            views._pool_key(existing),
            "last_activity",
            str(time.time() - 10.0),
        )
        request = self.factory.get(
            "/timeshift/u/p/8/2026-06-08:17-30/8.ts",
            HTTP_USER_AGENT="vlc-test",
            REMOTE_ADDR="127.0.0.1",
        )
        ok = MagicMock(status_code=200)
        profile = MagicMock(id=31)
        descriptor = {"account_id": "1", "stream_id": "111", "profile_id": "31"}
        with patch.object(views, "_authenticate_user", return_value=MagicMock(id=1)), \
             patch.object(views, "network_access_allowed", return_value=True), \
             patch.object(views, "Channel") as channel_cls, \
             patch.object(views, "_user_can_access_channel", return_value=True), \
             patch.object(views, "get_channel_catchup_streams",
                          return_value=[_make_catchup_stream()]), \
             patch.object(views, "get_programme_duration", return_value=40), \
             patch.object(views, "parse_catchup_timestamp", return_value=True), \
             patch.object(views, "check_user_stream_limits", return_value=True), \
             patch.object(views, "RedisClient") as redis_cls, \
             patch.object(
                 views, "_try_reacquire_idle_pool",
                 return_value=(descriptor, profile),
             ) as reacquire_mock, \
             patch.object(views, "_stream_reused_session", return_value=ok) as reuse_mock:
            redis_cls.get_client.return_value = redis
            channel_cls.objects.get.return_value = MagicMock(id=8)
            response = views.timeshift_proxy(
                request, "u", "p", "8", "2026-06-08:17-30", "8.ts",
            )
        self.assertIs(response, ok)
        reacquire_mock.assert_called_once()
        reuse_mock.assert_called_once()

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
        self.assertIn("session_id=", location)
        self.assertIn("foo=bar", location)
        self.assertIn("baz=1", location)

    @patch.object(views, "close_old_connections")
    def test_redirect_closes_db_after_orm(self, mock_close):
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
        mock_close.assert_called_once()


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

    def test_same_session_probe_allowed_without_ignore_same_channel(self):
        connections = [{
            "media_id": f"{self.MEDIA}_111",
            "client_id": TEST_SESSION_ID,
            "connected_at": 0.0,
            "type": "timeshift",
        }]
        with patch("apps.proxy.utils.get_user_active_connections",
                   return_value=connections), \
             patch("apps.proxy.utils.CoreSettings.get_user_limits_settings",
                   return_value=self._limits_settings(ignore_same_channel=False)):
            allowed = _check_user_stream_limits(
                self.user, TEST_SESSION_ID, media_id=self.MEDIA,
            )
        self.assertTrue(allowed)

    def test_different_session_same_programme_counts_against_limit(self):
        connections = [{
            "media_id": f"{self.MEDIA}_111",
            "client_id": "other_session",
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

    def test_same_session_probe_allowed_via_stable_stats_channel(self):
        # Programme hop: the active connection is tracked under the stable
        # stats channel id (timeshift_{channel}_{client_id}) from an OLDER
        # programme, while this request is for a NEW programme timestamp on
        # the same channel. Same client/channel must still be exempt.
        connections = [{
            "media_id": f"8_{TEST_SESSION_ID}",
            "client_id": TEST_SESSION_ID,
            "connected_at": 0.0,
            "type": "timeshift",
        }]
        with patch("apps.proxy.utils.get_user_active_connections",
                   return_value=connections), \
             patch("apps.proxy.utils.CoreSettings.get_user_limits_settings",
                   return_value=self._limits_settings()):
            allowed = _check_user_stream_limits(
                self.user, TEST_SESSION_ID, media_id="8_2026-06-08-17-30",
            )
        self.assertTrue(allowed)

    def test_different_channel_stable_stats_key_not_exempt(self):
        connections = [{
            "media_id": f"9_{TEST_SESSION_ID}",
            "client_id": TEST_SESSION_ID,
            "connected_at": 0.0,
            "type": "timeshift",
        }]
        with patch("apps.proxy.utils.get_user_active_connections",
                   return_value=connections), \
             patch("apps.proxy.utils.CoreSettings.get_user_limits_settings",
                   return_value=self._limits_settings(ignore_same_channel=False)):
            allowed = _check_user_stream_limits(
                self.user, TEST_SESSION_ID, media_id="8_2026-06-08-17-30",
            )
        self.assertFalse(allowed)


class TimeshiftPoolIdleTtlTests(TestCase):
    """The idle pool entry (fingerprint recovery) must outlive the stats
    client entry, or a reconnect within that window mints a NEW session
    (pool forgot it) while takeover logic still displaces the "old" one
    (stats hadn't forgotten it yet) -- contradictory outcomes for what is
    really the same viewer reconnecting after a pause."""

    def test_pool_idle_ttl_covers_stats_client_ttl(self):
        self.assertGreaterEqual(views._POOL_IDLE_TTL, views.CLIENT_TTL_SECONDS)

    def test_pool_idle_ttl_covers_disconnect_grace(self):
        self.assertGreaterEqual(
            views._POOL_IDLE_TTL, views._STATS_DISCONNECT_GRACE_SECONDS,
        )


class FakeRedisScanTests(TestCase):
    """FakeRedis SCAN matches redis-py glob semantics used by the pool scanner."""

    def setUp(self):
        self.redis = _FakeRedis()
        self.redis.store["timeshift:pool:a"] = {"busy": "0"}
        self.redis.store["timeshift:pool:b"] = {"busy": "0"}
        self.redis.store["timeshift_pool_legacy:other_c"] = {"busy": "0"}
        self.redis.store["vod_persistent_connection:x"] = {}

    def test_scan_glob_filters_pool_keys(self):
        cursor = 0
        seen = []
        while True:
            cursor, keys = self.redis.scan(
                cursor, match=TimeshiftRedisKeys.pool_scan_pattern(), count=1,
            )
            seen.extend(keys)
            if cursor == 0:
                break
        self.assertEqual(
            seen,
            ["timeshift:pool:a", "timeshift:pool:b"],
        )


class TimeshiftRangeClassificationTests(TestCase):
    """Range classification and presentation helpers."""

    def test_full_file_request_is_not_displacing(self):
        self.assertFalse(views._should_displace_busy_playback(None))

    def test_bytes_zero_displaces_full_file_probe(self):
        self.assertTrue(
            views._should_displace_busy_playback("bytes=0-", busy_serving_range="none")
        )

    def test_bytes_zero_does_not_displace_active_start_stream(self):
        # Scrub rule still false; residual same-session path preempts at serve time.
        self.assertFalse(
            views._should_displace_busy_playback("bytes=0-", busy_serving_range="start")
        )

    def test_bytes_zero_without_busy_context_is_not_displacing(self):
        self.assertFalse(views._should_displace_busy_playback("bytes=0-"))

    def test_near_eof_probe_is_not_displacing(self):
        self.assertTrue(views._is_near_eof_probe("bytes=2527702896-"))
        self.assertFalse(views._should_displace_busy_playback("bytes=2527702896-"))

    def test_cap_open_ended_range_limits_probe_span(self):
        self.assertEqual(
            views._cap_open_ended_range("bytes=1000-", 100),
            "bytes=1000-1099",
        )
        self.assertEqual(
            views._cap_open_ended_range("bytes=1000-2000", 100),
            "bytes=1000-2000",
        )

    def test_resolve_session_archive_scrub_maps_ff_offset(self):
        scrub = views._resolve_session_archive_scrub(
            {
                "final_url": "http://cdn/x",
                "content_length": "1800000000",
                "archive_anchor_ts": "2026-06-08:17-00",
                "archive_duration_secs": "3600",
            },
            "2026-06-08:17-30",
        )
        self.assertEqual(scrub["kind"], "scrub")
        # 30 minutes into 60 minutes ≈ half file, aligned to 188-byte TS packets.
        self.assertEqual(scrub["byte_offset"] % 188, 0)
        self.assertAlmostEqual(scrub["byte_offset"] / 1800000000, 0.5, places=2)
        self.assertEqual(scrub["remaining"], 1800000000 - scrub["byte_offset"])

    def test_resolve_session_archive_scrub_rejects_outside_window(self):
        self.assertIsNone(
            views._resolve_session_archive_scrub(
                {
                    "final_url": "http://cdn/x",
                    "content_length": "1800000000",
                    "archive_anchor_ts": "2026-06-08:17-00",
                    "archive_duration_secs": "1800",
                },
                "2026-06-08:17-40",
            )
        )

    def test_map_client_range_through_presentation(self):
        self.assertEqual(
            views._map_client_range_through_presentation(
                "bytes=419800872-", 314934968,
            ),
            "bytes=734735840-",
        )
        self.assertEqual(
            views._map_client_range_through_presentation(
                "bytes=100-200", 1000,
            ),
            "bytes=1100-1200",
        )

    def test_presentation_relative_content_range(self):
        self.assertEqual(
            views._presentation_relative_content_range(
                "bytes 314934968-734848639/734848640",
                presentation_byte_base=314934968,
                presentation_length=419913672,
            ),
            "bytes 0-419913671/419913672",
        )

    def test_near_eof_probe_uses_presentation_length_not_full_archive(self):
        # After scrub rewrite CL≈420MB; Range near that end must not displace
        # (XC parallel probe) even though the offset is mid-file on the CDN archive.
        self.assertTrue(
            views._is_near_eof_probe(
                "bytes=419800872-", content_length="419913672",
            )
        )
        self.assertFalse(
            views._should_displace_busy_playback(
                "bytes=419800872-", content_length="419913672",
            )
        )

    def test_near_eof_probe_uses_cached_content_length(self):
        # 5 MB into a 10 MB file is a scrub, not a tail probe.
        self.assertFalse(
            views._is_near_eof_probe("bytes=5000000-", content_length="10000000")
        )
        self.assertTrue(
            views._should_displace_busy_playback("bytes=5000000-", content_length="10000000")
        )
        # Within 2 MiB of EOF (incl. common 1.88MB / 10000-packet probes).
        self.assertTrue(
            views._is_near_eof_probe("bytes=9990000-", content_length="10000000")
        )
        total = 8_783_238_116
        self.assertTrue(
            views._is_near_eof_probe(
                f"bytes={total - 1_880_000}-", content_length=str(total),
            )
        )
        self.assertFalse(
            views._should_displace_busy_playback(
                f"bytes={total - 1_880_000}-", content_length=str(total),
            )
        )

    def test_midfile_seek_is_displacing(self):
        self.assertTrue(views._should_displace_busy_playback("bytes=5000000-"))

    def test_small_nonzero_range_is_displacing(self):
        self.assertTrue(views._should_displace_busy_playback("bytes=1000-"))

    def test_programme_change_does_not_displace_busy_pool(self):
        self.assertFalse(
            views._should_displace_busy_pool(
                None, None, None,
                pool_media_id="8_2026-06-08-17-00",
                media_id="8_2026-06-08-17-30",
            )
        )

    def test_programme_change_preempt_after_startup_window(self):
        redis = _FakeRedis()
        _seed_pool_session(
            redis, session_id=TEST_SESSION_ID,
            media_id="8_2026-06-08-17-00",
        )
        redis.hset(
            views._pool_key(TEST_SESSION_ID), "last_activity", "1.0",
        )
        with patch.object(views.time, "time", return_value=10.0):
            self.assertTrue(
                views._should_preempt_for_programme_change(
                    redis, TEST_SESSION_ID,
                    "8_2026-06-08-17-00",
                    "8_2026-06-08-17-30",
                ),
            )

    def test_parallel_programme_probe_does_not_preempt(self):
        redis = _FakeRedis()
        _seed_pool_session(
            redis, session_id=TEST_SESSION_ID,
            media_id="8_2026-06-08-17-00",
        )
        redis.hset(
            views._pool_key(TEST_SESSION_ID),
            "last_activity",
            str(views.time.time()),
        )
        self.assertFalse(
            views._should_preempt_for_programme_change(
                redis, TEST_SESSION_ID,
                "8_2026-06-08-17-00",
                "8_2026-06-08-17-30",
            ),
        )

    def test_active_playback_seek_always_preempts(self):
        # Heartbeats keep last_activity fresh; seek during play must still preempt.
        redis = _FakeRedis()
        _seed_pool_session(
            redis, session_id=TEST_SESSION_ID,
            media_id="8_2026-06-08-17-00",
        )
        redis.hset(
            views._pool_key(TEST_SESSION_ID),
            "last_activity",
            str(views.time.time()),
        )
        user = MagicMock(id=5)
        with patch.object(
            views, "_session_has_active_timeshift_stream", return_value=True,
        ):
            self.assertTrue(
                views._should_preempt_for_programme_change(
                    redis, TEST_SESSION_ID,
                    "8_2026-06-08-17-00",
                    "8_2026-06-08-17-30",
                    user=user,
                ),
            )


class TimeshiftStatsClientTests(TestCase):
    def setUp(self):
        self.redis = _FakeRedis()
        self.virtual_channel_id = f"{TEST_MEDIA_ID}_111"
        self.stats_channel_id = views.stats_channel_id(8, TEST_SESSION_ID)
        self.client_id = TEST_SESSION_ID
        self.user = MagicMock(id=5, username="viewer")

    def test_register_stats_preserves_connected_at_on_reregister(self):
        from apps.proxy.live_proxy.constants import ChannelMetadataField
        from apps.timeshift.redis_keys import TimeshiftRedisKeys as RedisKeys, TimeshiftRedisKeys

        client_key = RedisKeys.client_metadata(self.stats_channel_id, self.client_id)
        metadata_key = RedisKeys.channel_metadata(self.stats_channel_id)
        self.redis.hset(client_key, "connected_at", "1000.0")
        self.redis.hset(metadata_key, ChannelMetadataField.INIT_TIME, "1000.0")

        views._register_stats_client(
            self.redis,
            self.stats_channel_id,
            self.client_id,
            "1.2.3.4",
            "vlc",
            self.user,
            channel_display_name="A&E",
            timestamp_utc="2026-06-08:17-00",
            primary_url="http://example.test/timeshift.ts",
            programme_vid=self.virtual_channel_id,
            channel_id=8,
            channel_uuid="00000000-0000-0000-0000-000000000008",
        )

        self.assertEqual(self.redis.hget(client_key, "connected_at"), "1000.0")
        self.assertEqual(
            self.redis.hget(metadata_key, ChannelMetadataField.INIT_TIME), "1000.0",
        )
        self.assertEqual(
            self.redis.hget(client_key, "programme_vid"), self.virtual_channel_id,
        )
        self.assertEqual(
            self.redis.hget(metadata_key, ChannelMetadataField.CHANNEL_ID), "8",
        )
        self.assertEqual(
            self.redis.hget(metadata_key, ChannelMetadataField.CHANNEL_UUID),
            "00000000-0000-0000-0000-000000000008",
        )
        self.assertIsNone(self.redis.hget(client_key, "channel_id"))

    def test_register_stats_emits_update_for_new_client(self):
        with patch.object(views, "_trigger_timeshift_stats_update") as trigger_mock:
            views._register_stats_client(
                self.redis,
                self.stats_channel_id,
                self.client_id,
                "1.2.3.4",
                "vlc",
                self.user,
                channel_display_name="A&E",
                timestamp_utc="2026-06-08:17-00",
                primary_url="http://example.test/timeshift.ts",
                programme_vid=self.virtual_channel_id,
                channel_id=8,
                channel_uuid="00000000-0000-0000-0000-000000000008",
                emit_stats_update=True,
            )
        trigger_mock.assert_called_once_with(self.redis)

    def test_register_stats_skips_update_for_same_client_reregister(self):
        from apps.timeshift.redis_keys import TimeshiftRedisKeys as RedisKeys, TimeshiftRedisKeys

        client_key = RedisKeys.client_metadata(self.stats_channel_id, self.client_id)
        self.redis.hset(client_key, "connected_at", "1000.0")
        self.redis.hset(client_key, "programme_vid", self.virtual_channel_id)
        with patch.object(views, "_trigger_timeshift_stats_update") as trigger_mock:
            views._register_stats_client(
                self.redis,
                self.stats_channel_id,
                self.client_id,
                "1.2.3.4",
                "vlc",
                self.user,
                channel_display_name="A&E",
                timestamp_utc="2026-06-08:17-00",
                primary_url="http://example.test/timeshift.ts",
                programme_vid=self.virtual_channel_id,
                channel_id=8,
                channel_uuid="00000000-0000-0000-0000-000000000008",
                range_start=500_000_000,
                representation_length=1_000_000_000,
                programme_duration_secs=3600,
                emit_stats_update=True,
            )
        trigger_mock.assert_not_called()

    def test_register_stats_emits_update_for_programme_change(self):
        from apps.timeshift.redis_keys import TimeshiftRedisKeys as RedisKeys, TimeshiftRedisKeys

        new_programme_vid = "8_2026-06-08-17-30_111"
        client_key = RedisKeys.client_metadata(self.stats_channel_id, self.client_id)
        self.redis.hset(client_key, "connected_at", "1000.0")
        self.redis.hset(client_key, "programme_vid", self.virtual_channel_id)
        with patch.object(views, "_trigger_timeshift_stats_update") as trigger_mock:
            views._register_stats_client(
                self.redis,
                self.stats_channel_id,
                self.client_id,
                "1.2.3.4",
                "vlc",
                self.user,
                channel_display_name="A&E",
                timestamp_utc="2026-06-08:17-30",
                primary_url="http://example.test/timeshift.ts",
                programme_vid=new_programme_vid,
                channel_id=8,
                channel_uuid="00000000-0000-0000-0000-000000000008",
                emit_stats_update=True,
            )
        trigger_mock.assert_called_once_with(self.redis)

    def test_register_stats_updates_programme_on_hop(self):
        from apps.timeshift.redis_keys import TimeshiftRedisKeys as RedisKeys, TimeshiftRedisKeys

        new_programme_vid = "8_2026-06-08-17-30_111"
        client_key = RedisKeys.client_metadata(self.stats_channel_id, self.client_id)
        self.redis.hset(client_key, "connected_at", "1000.0")
        self.redis.hset(client_key, "programme_vid", self.virtual_channel_id)

        views._register_stats_client(
            self.redis,
            self.stats_channel_id,
            self.client_id,
            "1.2.3.4",
            "vlc",
            self.user,
            channel_display_name="A&E",
            timestamp_utc="2026-06-08:17-30",
            primary_url="http://example.test/timeshift.ts",
            programme_vid=new_programme_vid,
            channel_id=8,
            channel_uuid="00000000-0000-0000-0000-000000000008",
        )

        self.assertEqual(self.redis.hget(client_key, "connected_at"), "1000.0")
        self.assertEqual(self.redis.hget(client_key, "programme_vid"), new_programme_vid)

    def test_register_stats_cleans_old_programme_stream_generation_on_hop(self):
        from apps.timeshift.redis_keys import TimeshiftRedisKeys as RedisKeys, TimeshiftRedisKeys

        old_programme_vid = "8_2026-06-08-17-00_111"
        new_programme_vid = "8_2026-06-08-17-30_111"
        client_key = RedisKeys.client_metadata(self.stats_channel_id, self.client_id)
        self.redis.hset(client_key, "programme_vid", old_programme_vid)
        old_gen = views._stream_generation_key(old_programme_vid, self.client_id)
        self.redis.incr(old_gen)

        views._register_stats_client(
            self.redis,
            self.stats_channel_id,
            self.client_id,
            "1.2.3.4",
            "vlc",
            self.user,
            channel_display_name="A&E",
            timestamp_utc="2026-06-08:17-30",
            primary_url="http://example.test/timeshift.ts",
            programme_vid=new_programme_vid,
            channel_id=8,
            channel_uuid="00000000-0000-0000-0000-000000000008",
        )

        self.assertNotIn(old_gen, self.redis.store)

    def test_register_stats_reanchors_position_on_plain_get_reconnect(self):
        from apps.timeshift.redis_keys import TimeshiftRedisKeys as RedisKeys, TimeshiftRedisKeys

        client_key = RedisKeys.client_metadata(self.stats_channel_id, self.client_id)
        self.redis.hset(client_key, "programme_start", "2026-06-08:17-00")
        self.redis.hset(client_key, "position_anchor_at", "1000.0")
        self.redis.hset(client_key, "playback_base_secs", "900.0")

        views._register_stats_client(
            self.redis,
            self.stats_channel_id,
            self.client_id,
            "1.2.3.4",
            "vlc",
            self.user,
            channel_display_name="A&E",
            timestamp_utc="2026-06-08:17-00",
            primary_url="http://example.test/timeshift.ts",
            programme_vid=self.virtual_channel_id,
            channel_id=8,
            channel_uuid="00000000-0000-0000-0000-000000000008",
        )
        self.assertNotEqual(self.redis.hget(client_key, "position_anchor_at"), "1000.0")
        self.assertIsNone(self.redis.hget(client_key, "playback_base_secs"))

    def test_register_stats_byte_range_seek_sets_playback_base(self):
        from apps.timeshift.redis_keys import TimeshiftRedisKeys as RedisKeys, TimeshiftRedisKeys

        client_key = RedisKeys.client_metadata(self.stats_channel_id, self.client_id)
        self.redis.hset(client_key, "programme_start", "2026-06-08:17-00")
        self.redis.hset(client_key, "position_anchor_at", "1000.0")

        views._register_stats_client(
            self.redis,
            self.stats_channel_id,
            self.client_id,
            "1.2.3.4",
            "vlc",
            self.user,
            channel_display_name="A&E",
            timestamp_utc="2026-06-08:17-00",
            primary_url="http://example.test/timeshift.ts",
            programme_vid=self.virtual_channel_id,
            channel_id=8,
            channel_uuid="00000000-0000-0000-0000-000000000008",
            range_start=500_000_000,
            representation_length=1_000_000_000,
            programme_duration_secs=3600,
        )
        self.assertAlmostEqual(
            float(self.redis.hget(client_key, "playback_base_secs")),
            1800.0,
            delta=1.0,
        )
        self.assertNotEqual(self.redis.hget(client_key, "position_anchor_at"), "1000.0")

    def test_register_stats_reanchors_position_on_seek(self):
        from apps.timeshift.redis_keys import TimeshiftRedisKeys as RedisKeys, TimeshiftRedisKeys

        client_key = RedisKeys.client_metadata(self.stats_channel_id, self.client_id)
        self.redis.hset(client_key, "programme_start", "2026-06-08:17-00")
        self.redis.hset(client_key, "position_anchor_at", "1000.0")

        views._register_stats_client(
            self.redis,
            self.stats_channel_id,
            self.client_id,
            "1.2.3.4",
            "vlc",
            self.user,
            channel_display_name="A&E",
            timestamp_utc="2026-06-08:17-19",
            primary_url="http://example.test/timeshift.ts",
            programme_vid=self.virtual_channel_id,
            channel_id=8,
            channel_uuid="00000000-0000-0000-0000-000000000008",
        )
        self.assertNotEqual(self.redis.hget(client_key, "position_anchor_at"), "1000.0")

    def test_register_stats_seeds_stream_stats_from_memory(self):
        from apps.proxy.live_proxy.constants import ChannelMetadataField
        from apps.timeshift.redis_keys import TimeshiftRedisKeys as RedisKeys, TimeshiftRedisKeys

        metadata_key = RedisKeys.channel_metadata(self.stats_channel_id)
        views._register_stats_client(
            self.redis,
            self.stats_channel_id,
            self.client_id,
            "1.2.3.4",
            "vlc",
            self.user,
            channel_display_name="A&E",
            timestamp_utc="2026-06-08:17-00",
            primary_url="http://example.test/timeshift.ts",
            programme_vid=self.virtual_channel_id,
            channel_id=8,
            channel_uuid="00000000-0000-0000-0000-000000000008",
            stats_stream_id=42,
            stream_stats={
                "resolution": "1920x1080",
                "source_fps": 29.97,
                "video_codec": "h264",
                "audio_codec": "aac",
            },
        )
        self.assertEqual(self.redis.hget(metadata_key, ChannelMetadataField.RESOLUTION), "1920x1080")
        self.assertEqual(self.redis.hget(metadata_key, ChannelMetadataField.SOURCE_FPS), "29.97")
        self.assertEqual(self.redis.hget(metadata_key, ChannelMetadataField.STREAM_ID), "42")

    def test_register_stats_skips_stream_stats_when_stream_unchanged(self):
        from apps.proxy.live_proxy.constants import ChannelMetadataField
        from apps.timeshift.redis_keys import TimeshiftRedisKeys as RedisKeys, TimeshiftRedisKeys

        metadata_key = RedisKeys.channel_metadata(self.stats_channel_id)
        self.redis.hset(metadata_key, mapping={
            ChannelMetadataField.STREAM_ID: "42",
            ChannelMetadataField.RESOLUTION: "1280x720",
        })
        views._register_stats_client(
            self.redis,
            self.stats_channel_id,
            self.client_id,
            "1.2.3.4",
            "vlc",
            self.user,
            channel_display_name="A&E",
            timestamp_utc="2026-06-08:17-00",
            primary_url="http://example.test/timeshift.ts",
            programme_vid=self.virtual_channel_id,
            channel_id=8,
            channel_uuid="00000000-0000-0000-0000-000000000008",
            stats_stream_id=42,
            stream_stats={"resolution": "1920x1080"},
        )
        self.assertEqual(self.redis.hget(metadata_key, ChannelMetadataField.RESOLUTION), "1280x720")

    def test_register_stats_updates_stream_stats_on_failover_stream_change(self):
        from apps.proxy.live_proxy.constants import ChannelMetadataField
        from apps.timeshift.redis_keys import TimeshiftRedisKeys as RedisKeys, TimeshiftRedisKeys

        metadata_key = RedisKeys.channel_metadata(self.stats_channel_id)
        self.redis.hset(metadata_key, mapping={
            ChannelMetadataField.STREAM_ID: "42",
            ChannelMetadataField.RESOLUTION: "1280x720",
        })
        views._register_stats_client(
            self.redis,
            self.stats_channel_id,
            self.client_id,
            "1.2.3.4",
            "vlc",
            self.user,
            channel_display_name="A&E",
            timestamp_utc="2026-06-08:17-00",
            primary_url="http://example.test/timeshift.ts",
            programme_vid=self.virtual_channel_id,
            channel_id=8,
            channel_uuid="00000000-0000-0000-0000-000000000008",
            stats_stream_id=99,
            stream_stats={"resolution": "1920x1080", "video_codec": "hevc"},
        )
        self.assertEqual(self.redis.hget(metadata_key, ChannelMetadataField.STREAM_ID), "99")
        self.assertEqual(self.redis.hget(metadata_key, ChannelMetadataField.RESOLUTION), "1920x1080")
        self.assertEqual(self.redis.hget(metadata_key, ChannelMetadataField.VIDEO_CODEC), "hevc")

    @patch.object(views, "_open_upstream")
    def test_stream_keeps_stats_when_stopped_for_seek(self, mocked_open):
        from apps.timeshift.redis_keys import TimeshiftRedisKeys as RedisKeys, TimeshiftRedisKeys

        ts = _make_ts_payload(2048)
        upstream = MagicMock()
        upstream.status_code = 206
        upstream.headers = {
            "Content-Type": "video/mp2t",
            "Content-Range": "bytes 0-2047/10000",
        }
        upstream.raw.read = MagicMock(side_effect=[ts, ts, ts, b""])
        upstream.close = MagicMock()
        mocked_open.return_value = upstream

        release_cb = MagicMock()
        with patch.object(views, "_unregister_stats_client") as unregister_mock, \
             patch.object(views, "_schedule_stats_disconnect_grace") as grace_mock:
            response = views._stream_from_provider(
                candidate_urls=["http://example.test/timeshift.ts"],
                user_agent="provider-agent",
                client_user_agent="vlc",
                range_header="bytes=0-",
                virtual_channel_id=self.virtual_channel_id,
                stats_channel_id=self.stats_channel_id,
                client_id=self.client_id,
                client_ip="1.2.3.4",
                user=self.user,
                channel_display_name="A&E",
                timestamp_utc="2026-06-08:17-00",
                channel_logo_id=None,
                m3u_profile_id=31,
                channel_id=8,
                channel_uuid="00000000-0000-0000-0000-000000000008",
                debug=False,
                redis_client=self.redis,
                release_cb=release_cb,
            )

            self.assertEqual(response["Content-Range"], "bytes 0-2047/10000")
            self.assertEqual(response["Content-Length"], "2048")
            self.assertEqual(response["Accept-Ranges"], "bytes")

            iterator = iter(response.streaming_content)
            next(iterator)

            stop_key = RedisKeys.client_stop(self.virtual_channel_id, self.client_id)
            self.redis.setex(stop_key, 60, views._STOP_REASON_REUSE)

            for _ in iterator:
                pass
            response.close()

        unregister_mock.assert_not_called()
        grace_mock.assert_not_called()
        release_cb.assert_called_once()

    @patch.object(views, "_open_upstream")
    def test_stream_schedules_grace_on_plain_client_disconnect(self, mocked_open):
        # Known client disconnect (no preempt stop key): defer stats removal so
        # a reconnect within the grace window keeps connected_at continuity.
        ts = _make_ts_payload(65536)
        upstream = MagicMock()
        upstream.status_code = 206
        upstream.headers = {
            "Content-Type": "video/mp2t",
            "Content-Range": "bytes 0-65535/100000",
        }
        upstream.raw.read = MagicMock(side_effect=[ts, ConnectionError("reset by peer")])
        upstream.close = MagicMock()
        mocked_open.return_value = upstream

        release_cb = MagicMock()
        with patch.object(views, "_unregister_stats_client") as unregister_mock, \
             patch.object(views, "_schedule_stats_disconnect_grace") as grace_mock:
            response = views._stream_from_provider(
                candidate_urls=["http://example.test/timeshift.ts"],
                user_agent="provider-agent",
                client_user_agent="vlc",
                range_header="bytes=0-",
                virtual_channel_id=self.virtual_channel_id,
                stats_channel_id=self.stats_channel_id,
                client_id=self.client_id,
                client_ip="1.2.3.4",
                user=self.user,
                channel_display_name="A&E",
                timestamp_utc="2026-06-08:17-00",
                channel_logo_id=None,
                m3u_profile_id=31,
                channel_id=8,
                channel_uuid="00000000-0000-0000-0000-000000000008",
                debug=False,
                redis_client=self.redis,
                release_cb=release_cb,
            )

            for _ in response.streaming_content:
                pass
            response.close()

        unregister_mock.assert_not_called()
        grace_mock.assert_called_once_with(
            self.redis, self.stats_channel_id, self.client_id,
        )
        release_cb.assert_called_once_with(
            mark_pool_idle=True, release_profile=True,
        )

    @patch.object(views, "_open_upstream")
    def test_stopped_for_reuse_handoff_keeps_profile_slot(self, mocked_open):
        """After a scrub preempt, the displaced stream keeps the profile slot."""
        from apps.timeshift.redis_keys import TimeshiftRedisKeys as RedisKeys, TimeshiftRedisKeys

        _seed_pool_session(self.redis, session_id=self.client_id)
        ts = _make_ts_payload(65536)
        upstream = MagicMock()
        upstream.status_code = 206
        upstream.headers = {
            "Content-Type": "video/mp2t",
            "Content-Range": "bytes 0-65535/100000",
        }
        upstream.raw.read = MagicMock(side_effect=[ts, b""])
        upstream.close = MagicMock()
        mocked_open.return_value = upstream

        release_cb = views._make_release_once(self.redis, self.client_id, 31)
        with patch.object(views, "_schedule_stats_disconnect_grace") as grace_mock, \
             patch.object(views, "release_profile_slot") as release_mock:
            response = views._stream_from_provider(
                candidate_urls=["http://example.test/timeshift.ts"],
                user_agent="provider-agent",
                client_user_agent="vlc",
                range_header="bytes=0-",
                virtual_channel_id=self.virtual_channel_id,
                stats_channel_id=self.stats_channel_id,
                client_id=self.client_id,
                client_ip="1.2.3.4",
                user=self.user,
                channel_display_name="A&E",
                timestamp_utc="2026-06-08:17-00",
                channel_logo_id=None,
                m3u_profile_id=31,
                channel_id=8,
                channel_uuid="00000000-0000-0000-0000-000000000008",
                debug=False,
                redis_client=self.redis,
                release_cb=release_cb,
            )

            iterator = iter(response.streaming_content)
            next(iterator)
            stop_key = RedisKeys.client_stop(self.virtual_channel_id, self.client_id)
            self.redis.setex(stop_key, 60, "1")
            for _ in iterator:
                pass
            response.close()

        grace_mock.assert_not_called()
        release_mock.assert_not_called()
        self.assertEqual(
            self.redis.hget(f"timeshift:pool:{self.client_id}", "busy"),
            "1",
        )

    def test_handoff_reacquire_skips_profile_reserve(self):
        _seed_pool_session(self.redis, session_id=TEST_SESSION_ID, busy="1")
        profile = MagicMock(id=31)
        with patch.object(views.M3UAccountProfile.objects, "get", return_value=profile), \
             patch.object(views, "reserve_profile_slot") as reserve_mock:
            acquired = views._acquire_idle_pool_session(
                self.redis, TEST_SESSION_ID, handoff=True,
            )
        self.assertIsNotNone(acquired)
        reserve_mock.assert_not_called()
        self.assertEqual(
            self.redis.hget(f"timeshift:pool:{TEST_SESSION_ID}", "busy"),
            "1",
        )

    def test_handoff_release_keeps_pool_busy(self):
        _seed_pool_session(self.redis, session_id=TEST_SESSION_ID, busy="1")
        with patch.object(views, "release_profile_slot") as release_mock:
            views._release_pool_session(
                self.redis, TEST_SESSION_ID, 31,
                mark_pool_idle=False, release_profile=False,
            )
        release_mock.assert_not_called()
        self.assertEqual(
            self.redis.hget(f"timeshift:pool:{TEST_SESSION_ID}", "busy"),
            "1",
        )

    @patch.object(views, "_open_upstream")
    def test_disconnect_after_seek_preempt_schedules_grace(self, mocked_open):
        """The replacement stream after a seek must still arm disconnect cleanup."""
        from apps.timeshift.redis_keys import TimeshiftRedisKeys as RedisKeys, TimeshiftRedisKeys

        ts = _make_ts_payload(65536)
        upstream = MagicMock()
        upstream.status_code = 206
        upstream.headers = {
            "Content-Type": "video/mp2t",
            "Content-Range": "bytes 0-65535/100000",
        }
        upstream.raw.read = MagicMock(side_effect=[ts, ConnectionError("reset by peer")])
        upstream.close = MagicMock()
        mocked_open.return_value = upstream

        release_cb = MagicMock()
        gen_key = views._stream_generation_key(
            self.virtual_channel_id, self.client_id,
        )
        self.redis.set(gen_key, "1")
        stop_key = RedisKeys.client_stop(self.virtual_channel_id, self.client_id)
        self.redis.setex(stop_key, 60, "1")

        with patch.object(views, "_schedule_stats_disconnect_grace") as grace_mock:
            response = views._stream_from_provider(
                candidate_urls=["http://example.test/timeshift.ts"],
                user_agent="provider-agent",
                client_user_agent="vlc",
                range_header="bytes=1000-",
                virtual_channel_id=self.virtual_channel_id,
                stats_channel_id=self.stats_channel_id,
                client_id=self.client_id,
                client_ip="1.2.3.4",
                user=self.user,
                channel_display_name="A&E",
                timestamp_utc="2026-06-08:17-00",
                channel_logo_id=None,
                m3u_profile_id=31,
                channel_id=8,
                channel_uuid="00000000-0000-0000-0000-000000000008",
                debug=False,
                redis_client=self.redis,
                release_cb=release_cb,
            )

            for _ in response.streaming_content:
                pass
            response.close()

        self.assertNotIn(stop_key, self.redis.store)
        grace_mock.assert_called_once_with(
            self.redis, self.stats_channel_id, self.client_id,
        )
        release_cb.assert_called_once_with(
            mark_pool_idle=True, release_profile=True,
        )

    def test_create_pool_session_clears_superseded_marker(self):
        self.redis.set(views._superseded_pool_key(TEST_SESSION_ID), "1")
        created = views._create_pool_session(
            self.redis,
            session_id=TEST_SESSION_ID,
            media_id=TEST_MEDIA_ID,
            user_id=5,
            client_ip="1.2.3.4",
            client_user_agent="test-agent",
            account_id=1,
            profile_id=31,
            stream_id="111",
            dispatcharr_stream_id=10,
            provider_timestamp="2026-06-08:19-00",
        )
        self.assertTrue(created)
        self.assertNotIn(
            views._superseded_pool_key(TEST_SESSION_ID), self.redis.store,
        )

    @patch.object(views, "_open_upstream")
    def test_stream_disconnect_cleans_programme_stream_generation(self, mocked_open):
        ts = _make_ts_payload(65536)
        upstream = MagicMock()
        upstream.status_code = 206
        upstream.headers = {
            "Content-Type": "video/mp2t",
            "Content-Range": "bytes 0-65535/100000",
        }
        upstream.raw.read = MagicMock(side_effect=[ts, b""])
        upstream.close = MagicMock()
        mocked_open.return_value = upstream

        gen_key = views._stream_generation_key(
            self.virtual_channel_id, self.client_id,
        )
        release_cb = MagicMock()
        with patch.object(views, "_schedule_stats_disconnect_grace"):
            response = views._stream_from_provider(
                candidate_urls=["http://example.test/timeshift.ts"],
                user_agent="provider-agent",
                client_user_agent="vlc",
                range_header="bytes=0-",
                virtual_channel_id=self.virtual_channel_id,
                stats_channel_id=self.stats_channel_id,
                client_id=self.client_id,
                client_ip="1.2.3.4",
                user=self.user,
                channel_display_name="A&E",
                timestamp_utc="2026-06-08:17-00",
                channel_logo_id=None,
                m3u_profile_id=31,
                channel_id=8,
                channel_uuid="00000000-0000-0000-0000-000000000008",
                debug=False,
                redis_client=self.redis,
                release_cb=release_cb,
            )
            for _ in response.streaming_content:
                pass
            response.close()

        self.assertNotIn(gen_key, self.redis.store)

    @patch.object(views, "_open_upstream")
    def test_stream_skips_grace_when_newer_generation_active(self, mocked_open):
        # Seek race: the replacement stream bumps generation before the old
        # generator's finally runs (VLC resets TCP without a polled stop key).
        ts = _make_ts_payload(2048)
        upstream = MagicMock()
        upstream.status_code = 206
        upstream.headers = {
            "Content-Type": "video/mp2t",
            "Content-Range": "bytes 0-2047/10000",
        }
        upstream.raw.read = MagicMock(side_effect=[ts, b""])
        upstream.close = MagicMock()
        mocked_open.return_value = upstream

        release_cb = MagicMock()
        gen_key = views._stream_generation_key(
            self.virtual_channel_id, self.client_id,
        )

        with patch.object(views, "_unregister_stats_client") as unregister_mock, \
             patch.object(views, "_schedule_stats_disconnect_grace") as grace_mock:
            response = views._stream_from_provider(
                candidate_urls=["http://example.test/timeshift.ts"],
                user_agent="provider-agent",
                client_user_agent="vlc",
                range_header="bytes=0-",
                virtual_channel_id=self.virtual_channel_id,
                stats_channel_id=self.stats_channel_id,
                client_id=self.client_id,
                client_ip="1.2.3.4",
                user=self.user,
                channel_display_name="A&E",
                timestamp_utc="2026-06-08:17-00",
                channel_logo_id=None,
                m3u_profile_id=31,
                channel_id=8,
                channel_uuid="00000000-0000-0000-0000-000000000008",
                debug=False,
                redis_client=self.redis,
                release_cb=release_cb,
            )

            iterator = iter(response.streaming_content)
            next(iterator)
            self.redis.incr(gen_key)
            for _ in iterator:
                pass
            response.close()

        unregister_mock.assert_not_called()
        grace_mock.assert_not_called()
        release_cb.assert_called_once()

    def test_register_cancels_pending_stats_grace(self):
        grace_key = views._stats_disconnect_grace_key(
            self.stats_channel_id, self.client_id,
        )
        self.redis.setex(grace_key, 10, "pending-token")

        views._register_stats_client(
            self.redis,
            self.stats_channel_id,
            self.client_id,
            "1.2.3.4",
            "vlc",
            self.user,
            channel_display_name="A&E",
            timestamp_utc="2026-06-08:17-00",
            primary_url="http://example.test/timeshift.ts",
            programme_vid=self.virtual_channel_id,
            channel_id=8,
            channel_uuid="00000000-0000-0000-0000-000000000008",
        )

        self.assertNotIn(grace_key, self.redis.store)

    def test_grace_unregister_runs_when_not_cancelled(self):
        from apps.timeshift.redis_keys import TimeshiftRedisKeys as RedisKeys, TimeshiftRedisKeys

        grace_key = views._stats_disconnect_grace_key(
            self.stats_channel_id, self.client_id,
        )
        token = "grace-token"
        self.redis.setex(grace_key, 10, token)
        client_key = RedisKeys.client_metadata(
            self.stats_channel_id, self.client_id,
        )
        self.redis.hset(client_key, "last_active", "1000.0")

        with patch.object(views, "_unregister_stats_client") as unregister_mock, \
             patch.object(views, "_trigger_timeshift_stats_update") as trigger_mock:
            views._run_stats_disconnect_grace(
                self.redis, self.stats_channel_id, self.client_id, token,
                disconnected_at=2000.0,
            )

        unregister_mock.assert_called_once_with(
            self.redis, self.stats_channel_id, self.client_id,
        )
        trigger_mock.assert_called_once_with(self.redis)
        self.assertNotIn(grace_key, self.redis.store)

    def test_grace_unregister_skipped_when_reconnect_cancelled(self):
        grace_key = views._stats_disconnect_grace_key(
            self.stats_channel_id, self.client_id,
        )
        self.redis.setex(grace_key, 10, "new-token")

        with patch.object(views, "_unregister_stats_client") as unregister_mock:
            views._run_stats_disconnect_grace(
                self.redis, self.stats_channel_id, self.client_id, "old-token",
                disconnected_at=1000.0,
            )

        unregister_mock.assert_not_called()

    def test_grace_unregister_skipped_when_client_reconnected(self):
        from apps.timeshift.redis_keys import TimeshiftRedisKeys as RedisKeys, TimeshiftRedisKeys

        grace_key = views._stats_disconnect_grace_key(
            self.stats_channel_id, self.client_id,
        )
        token = "grace-token"
        self.redis.setex(grace_key, 10, token)
        client_key = RedisKeys.client_metadata(
            self.stats_channel_id, self.client_id,
        )
        self.redis.hset(client_key, "last_active", "2000.0")

        with patch.object(views, "_unregister_stats_client") as unregister_mock:
            views._run_stats_disconnect_grace(
                self.redis, self.stats_channel_id, self.client_id, token,
                disconnected_at=1000.0,
            )

        unregister_mock.assert_not_called()

    def test_grace_unregister_deletes_api_catchup_session(self):
        from apps.timeshift.redis_keys import TimeshiftRedisKeys as RedisKeys, TimeshiftRedisKeys
        
        grace_key = views._stats_disconnect_grace_key(
            self.stats_channel_id, self.client_id,
        )
        token = "grace-token"
        self.redis.setex(grace_key, 10, token)
        client_key = RedisKeys.client_metadata(
            self.stats_channel_id, self.client_id,
        )
        self.redis.hset(client_key, "last_active", "1000.0")
        session_key = TimeshiftRedisKeys.api_session(self.client_id)
        self.redis.hset(session_key, "user_id", "5")

        views._run_stats_disconnect_grace(
            self.redis, self.stats_channel_id, self.client_id, token,
            disconnected_at=2000.0,
        )

        self.assertNotIn(session_key, self.redis.store)

    def test_grace_unregister_cleans_stream_generation(self):
        from apps.timeshift.redis_keys import TimeshiftRedisKeys as RedisKeys, TimeshiftRedisKeys

        grace_key = views._stats_disconnect_grace_key(
            self.stats_channel_id, self.client_id,
        )
        token = "grace-token"
        self.redis.setex(grace_key, 10, token)
        client_key = RedisKeys.client_metadata(
            self.stats_channel_id, self.client_id,
        )
        self.redis.hset(client_key, "last_active", "1000.0")
        old_vid = "8_2026-06-08-17-00_111"
        new_vid = "8_2026-06-08-17-30_111"
        self.redis.hset(client_key, "programme_vid", new_vid)
        old_gen = views._stream_generation_key(old_vid, self.client_id)
        new_gen = views._stream_generation_key(new_vid, self.client_id)
        self.redis.incr(old_gen)
        self.redis.incr(new_gen)

        views._run_stats_disconnect_grace(
            self.redis, self.stats_channel_id, self.client_id, token,
            disconnected_at=2000.0,
        )

        self.assertNotIn(old_gen, self.redis.store)
        self.assertNotIn(new_gen, self.redis.store)

    def test_grace_unregister_discards_pool_for_api_session(self):
        from apps.timeshift.redis_keys import TimeshiftRedisKeys as RedisKeys, TimeshiftRedisKeys
        
        grace_key = views._stats_disconnect_grace_key(
            self.stats_channel_id, self.client_id,
        )
        token = "grace-token"
        self.redis.setex(grace_key, 10, token)
        client_key = RedisKeys.client_metadata(
            self.stats_channel_id, self.client_id,
        )
        self.redis.hset(client_key, "last_active", "1000.0")
        self.redis.hset(TimeshiftRedisKeys.api_session(self.client_id), "user_id", "5")
        pool_key = views._pool_key(self.client_id)
        self.redis.hset(pool_key, mapping={"busy": "0", "profile_id": "31"})

        with patch.object(views, "release_profile_slot") as release_mock:
            views._run_stats_disconnect_grace(
                self.redis, self.stats_channel_id, self.client_id, token,
                disconnected_at=2000.0,
            )

        self.assertNotIn(pool_key, self.redis.store)
        release_mock.assert_not_called()

    def test_grace_unregister_keeps_idle_pool_for_xc_session(self):
        from apps.timeshift.redis_keys import TimeshiftRedisKeys as RedisKeys, TimeshiftRedisKeys

        grace_key = views._stats_disconnect_grace_key(
            self.stats_channel_id, self.client_id,
        )
        token = "grace-token"
        self.redis.setex(grace_key, 10, token)
        client_key = RedisKeys.client_metadata(
            self.stats_channel_id, self.client_id,
        )
        self.redis.hset(client_key, "last_active", "1000.0")
        pool_key = views._pool_key(self.client_id)
        self.redis.hset(pool_key, "busy", "0")

        views._run_stats_disconnect_grace(
            self.redis, self.stats_channel_id, self.client_id, token,
            disconnected_at=2000.0,
        )

        self.assertIn(pool_key, self.redis.store)
        self.assertEqual(
            self.redis.ttl.get(pool_key), views._POOL_IDLE_TTL,
        )

    def test_allocate_stream_generation_sets_ttl(self):
        with patch.object(self.redis, "expire", wraps=self.redis.expire) as expire_mock:
            views._allocate_stream_generation(
                self.redis, self.virtual_channel_id, self.client_id,
            )
        gen_key = views._stream_generation_key(
            self.virtual_channel_id, self.client_id,
        )
        expire_mock.assert_called_once_with(gen_key, views._POOL_ENTRY_TTL)

    def test_grace_unregister_runs_when_last_active_equals_disconnect(self):
        from apps.timeshift.redis_keys import TimeshiftRedisKeys as RedisKeys, TimeshiftRedisKeys

        grace_key = views._stats_disconnect_grace_key(
            self.stats_channel_id, self.client_id,
        )
        token = "grace-token"
        self.redis.setex(grace_key, 10, token)
        client_key = RedisKeys.client_metadata(
            self.stats_channel_id, self.client_id,
        )
        self.redis.hset(client_key, "last_active", "1000.0")

        with patch.object(views, "_unregister_stats_client") as unregister_mock:
            views._run_stats_disconnect_grace(
                self.redis, self.stats_channel_id, self.client_id, token,
                disconnected_at=1000.0,
            )

        unregister_mock.assert_called_once_with(
            self.redis, self.stats_channel_id, self.client_id,
        )

    def test_should_schedule_grace_skips_startup_probe(self):
        pool_key = views._pool_key(self.client_id)
        self.redis.hset(pool_key, "busy", "0")
        self.assertFalse(
            views._should_schedule_stats_disconnect_grace(
                996, 0.5, stopped_for_reuse=False,
            ),
        )
        self.assertFalse(
            views._should_schedule_stats_disconnect_grace(
                525220, 0.9,
                stopped_for_reuse=False,
                redis_client=self.redis,
                client_id=self.client_id,
            ),
        )
        self.assertTrue(
            views._should_schedule_stats_disconnect_grace(
                996, 3.0, stopped_for_reuse=False,
            ),
        )
        self.assertTrue(
            views._should_schedule_stats_disconnect_grace(
                120000, 0.5, stopped_for_reuse=False,
            ),
        )
        self.assertTrue(
            views._should_schedule_stats_disconnect_grace(
                120000, 3.0,
                stopped_for_reuse=False,
                redis_client=self.redis,
                client_id=self.client_id,
            ),
        )
        self.assertFalse(
            views._should_schedule_stats_disconnect_grace(
                120000, 0.5, stopped_for_reuse=True,
            ),
        )

    def test_touch_stats_on_session_request_cancels_grace(self):
        from apps.timeshift.redis_keys import TimeshiftRedisKeys as RedisKeys, TimeshiftRedisKeys

        grace_key = views._stats_disconnect_grace_key(
            self.stats_channel_id, self.client_id,
        )
        self.redis.setex(grace_key, 10, "pending-token")
        client_key = RedisKeys.client_metadata(
            self.stats_channel_id, self.client_id,
        )
        self.redis.hset(client_key, mapping={
            "last_active": "1000.0",
            "channel_id": "8",
            "programme_start": "2026-06-08:17-00",
        })

        views._touch_stats_on_session_request(
            self.redis, 8, self.client_id,
        )

        self.assertNotIn(grace_key, self.redis.store)
        last_active = float(self.redis.hget(client_key, "last_active"))
        self.assertGreater(last_active, 1000.0)

    def test_grace_unregister_skipped_when_client_reconnected_during_settle(self):
        from apps.timeshift.redis_keys import TimeshiftRedisKeys as RedisKeys, TimeshiftRedisKeys

        grace_key = views._stats_disconnect_grace_key(
            self.stats_channel_id, self.client_id,
        )
        token = "grace-token"
        self.redis.setex(grace_key, 10, token)
        client_key = RedisKeys.client_metadata(
            self.stats_channel_id, self.client_id,
        )
        self.redis.hset(client_key, "last_active", "2000.0")
        pool_key = views._pool_key(self.client_id)
        self.redis.hset(pool_key, mapping={"busy": "0", "last_activity": "2000.0"})

        with patch.object(views, "_unregister_stats_client") as unregister_mock:
            views._run_stats_disconnect_grace(
                self.redis, self.stats_channel_id, self.client_id, token,
                disconnected_at=1000.0,
            )

        unregister_mock.assert_not_called()

    def test_stats_client_reconnected_ignores_idle_pool_release_timestamp(self):
        pool_key = views._pool_key(self.client_id)
        self.redis.hset(pool_key, mapping={"busy": "0", "last_activity": "2000.0"})
        self.assertFalse(
            views._stats_client_reconnected(
                self.redis, self.stats_channel_id, self.client_id,
                disconnected_at=1000.0,
            ),
        )

    def test_grace_unregister_runs_after_idle_pool_release_timestamp(self):
        from apps.timeshift.redis_keys import TimeshiftRedisKeys as RedisKeys, TimeshiftRedisKeys
        
        grace_key = views._stats_disconnect_grace_key(
            self.stats_channel_id, self.client_id,
        )
        token = "grace-token"
        self.redis.setex(grace_key, 10, token)
        client_key = RedisKeys.client_metadata(
            self.stats_channel_id, self.client_id,
        )
        self.redis.hset(client_key, "last_active", "1000.0")
        pool_key = views._pool_key(self.client_id)
        self.redis.hset(pool_key, mapping={"busy": "0", "last_activity": "2000.0"})
        session_key = TimeshiftRedisKeys.api_session(self.client_id)
        self.redis.hset(session_key, "user_id", "5")

        views._run_stats_disconnect_grace(
            self.redis, self.stats_channel_id, self.client_id, token,
            disconnected_at=1000.0,
        )

        self.assertNotIn(client_key, self.redis.store)
        self.assertNotIn(session_key, self.redis.store)
        self.assertNotIn(pool_key, self.redis.store)

    def test_scheduled_grace_unregisters_after_settle_when_pool_only_released(self):
        from apps.timeshift.redis_keys import TimeshiftRedisKeys as RedisKeys, TimeshiftRedisKeys

        client_key = RedisKeys.client_metadata(
            self.stats_channel_id, self.client_id,
        )
        self.redis.hset(client_key, "last_active", "1000.0")
        pool_key = views._pool_key(self.client_id)
        self.redis.hset(pool_key, mapping={"busy": "0", "last_activity": "2000.0"})

        with patch.object(views, "_spawn_background_task", lambda func: func()), \
             patch.object(views.time, "sleep", lambda _s: None), \
             patch.object(views, "_unregister_stats_client") as unregister_mock:
            views._schedule_stats_disconnect_grace(
                self.redis, self.stats_channel_id, self.client_id,
            )

        unregister_mock.assert_called_once_with(
            self.redis, self.stats_channel_id, self.client_id,
        )

    def test_schedule_grace_stores_deadline_on_client_metadata(self):
        from apps.timeshift.redis_keys import TimeshiftRedisKeys as RedisKeys, TimeshiftRedisKeys

        client_key = RedisKeys.client_metadata(
            self.stats_channel_id, self.client_id,
        )
        self.redis.hset(client_key, "last_active", "1000.0")

        with patch.object(views, "_spawn_background_task", lambda func: None):
            views._schedule_stats_disconnect_grace(
                self.redis, self.stats_channel_id, self.client_id,
            )

        self.assertIn(views._STATS_GRACE_DEADLINE_FIELD, self.redis.store[client_key])
        self.assertIn(
            views._STATS_GRACE_DISCONNECTED_AT_FIELD, self.redis.store[client_key],
        )

    def test_complete_expired_stats_grace_runs_after_deadline(self):
        from apps.timeshift.redis_keys import TimeshiftRedisKeys as RedisKeys, TimeshiftRedisKeys
        
        grace_key = views._stats_disconnect_grace_key(
            self.stats_channel_id, self.client_id,
        )
        token = "grace-token"
        self.redis.setex(grace_key, 10, token)
        client_key = RedisKeys.client_metadata(
            self.stats_channel_id, self.client_id,
        )
        self.redis.hset(client_key, mapping={
            "last_active": "0.5",
            views._STATS_GRACE_DEADLINE_FIELD: "1.0",
            views._STATS_GRACE_DISCONNECTED_AT_FIELD: "1.0",
        })
        session_key = TimeshiftRedisKeys.api_session(self.client_id)
        self.redis.hset(session_key, "user_id", "5")

        views._complete_expired_stats_grace(
            self.redis, self.stats_channel_id, self.client_id,
        )

        self.assertNotIn(client_key, self.redis.store)
        self.assertNotIn(session_key, self.redis.store)
        self.assertNotIn(grace_key, self.redis.store)

    def test_heartbeat_refreshes_idle_pool_and_catchup_session(self):
        from apps.timeshift.redis_keys import TimeshiftRedisKeys as RedisKeys, TimeshiftRedisKeys
        from apps.timeshift.sessions import SESSION_IDLE_TTL_SECONDS

        client_key = RedisKeys.client_metadata(
            self.stats_channel_id, self.client_id,
        )
        self.redis.hset(client_key, mapping={
            "last_active": "1000.0",
            "programme_vid": self.virtual_channel_id,
        })
        pool_key = views._pool_key(self.client_id)
        self.redis.hset(pool_key, mapping={"busy": "0", "last_activity": "1.0"})
        session_key = TimeshiftRedisKeys.api_session(self.client_id)
        self.redis.hset(session_key, "user_id", "5")
        self.redis.expire(session_key, 60)
        gen_key = views._stream_generation_key(
            self.virtual_channel_id, self.client_id,
        )
        self.redis.set(gen_key, "1")
        self.redis.expire(gen_key, 60)

        views._heartbeat_stats_client(
            self.redis, self.stats_channel_id, self.client_id,
            bytes_delta=1024,
            pool_session_id=self.client_id,
            programme_vid=self.virtual_channel_id,
        )

        self.assertGreater(
            float(self.redis.hget(pool_key, "last_activity")), 1.0,
        )
        self.assertEqual(
            self.redis.ttl.get(session_key), SESSION_IDLE_TTL_SECONDS,
        )
        self.assertEqual(
            self.redis.ttl.get(gen_key), views._POOL_ENTRY_TTL,
        )

    def test_grace_unregister_skipped_when_pool_session_busy(self):
        from apps.timeshift.redis_keys import TimeshiftRedisKeys as RedisKeys, TimeshiftRedisKeys

        grace_key = views._stats_disconnect_grace_key(
            self.stats_channel_id, self.client_id,
        )
        token = "grace-token"
        self.redis.setex(grace_key, 10, token)
        client_key = RedisKeys.client_metadata(
            self.stats_channel_id, self.client_id,
        )
        self.redis.hset(client_key, "last_active", "1000.0")
        pool_key = views._pool_key(self.client_id)
        self.redis.hset(pool_key, "busy", "1")

        with patch.object(views, "_unregister_stats_client") as unregister_mock:
            views._run_stats_disconnect_grace(
                self.redis, self.stats_channel_id, self.client_id, token,
                disconnected_at=2000.0,
            )

        unregister_mock.assert_not_called()
        self.assertNotIn(grace_key, self.redis.store)


class TimeshiftUpstreamStopTests(TestCase):
    def test_iter_upstream_with_stop_honors_stop_before_read(self):
        redis = _FakeRedis()
        from apps.timeshift.redis_keys import TimeshiftRedisKeys as RedisKeys, TimeshiftRedisKeys

        upstream = MagicMock()
        upstream.raw.read = MagicMock(side_effect=[b"a", b"b", b"c", b""])

        stop_key = RedisKeys.client_stop("1_test_111", "client_1")
        chunks = list(
            views._iter_upstream_with_stop(
                upstream, 1, redis, stop_key, stream_generation=1, peek_data=b"p",
            )
        )
        self.assertEqual(chunks, [b"p", b"a", b"b", b"c"])
        self.assertEqual(upstream.raw.read.call_count, 4)

        redis.setex(stop_key, 60, "1")
        upstream.raw.read.reset_mock()
        chunks = list(
            views._iter_upstream_with_stop(
                upstream, 1, redis, stop_key, stream_generation=1, peek_data=b"p",
            )
        )
        self.assertEqual(chunks, [])
        upstream.raw.read.assert_not_called()
        upstream.close.assert_called()

    def test_iter_upstream_with_stop_honors_admin_stop(self):
        redis = _FakeRedis()
        from apps.timeshift.redis_keys import TimeshiftRedisKeys as RedisKeys, TimeshiftRedisKeys

        upstream = MagicMock()
        upstream.raw.read = MagicMock(return_value=b"chunk")

        stop_key = RedisKeys.client_stop("1_test_111", "client_1")
        redis.setex(stop_key, 60, views._STOP_REASON_ADMIN)
        chunks = list(
            views._iter_upstream_with_stop(
                upstream, 1, redis, stop_key, stream_generation=1,
            )
        )
        self.assertEqual(chunks, [])
        upstream.raw.read.assert_not_called()
        upstream.close.assert_called_once()

    def test_iter_upstream_with_stop_honors_limit_stop(self):
        redis = _FakeRedis()
        from apps.timeshift.redis_keys import TimeshiftRedisKeys as RedisKeys, TimeshiftRedisKeys

        upstream = MagicMock()
        upstream.raw.read = MagicMock(return_value=b"chunk")

        stop_key = RedisKeys.client_stop("1_test_111", "client_1")
        redis.setex(stop_key, 60, views._STOP_REASON_LIMIT)
        chunks = list(
            views._iter_upstream_with_stop(
                upstream, 1, redis, stop_key, stream_generation=99,
            )
        )
        self.assertEqual(chunks, [])
        upstream.raw.read.assert_not_called()
        upstream.close.assert_called_once()

    def test_successor_stream_ignores_preempt_stop_for_prior_generation(self):
        redis = _FakeRedis()
        from apps.timeshift.redis_keys import TimeshiftRedisKeys as RedisKeys, TimeshiftRedisKeys

        upstream = MagicMock()
        upstream.raw.read = MagicMock(side_effect=[b"a", b"b", b""])

        stop_key = RedisKeys.client_stop("1_test_111", "client_1")
        redis.setex(stop_key, 60, "1")

        chunks = list(
            views._iter_upstream_with_stop(
                upstream, 1, redis, stop_key, stream_generation=2, peek_data=b"p",
            )
        )
        self.assertEqual(chunks, [b"p", b"a", b"b"])
        upstream.close.assert_not_called()

    def test_iter_upstream_with_stop_retries_after_read_timeout(self):
        redis = _FakeRedis()
        from apps.timeshift.redis_keys import TimeshiftRedisKeys as RedisKeys, TimeshiftRedisKeys

        upstream = MagicMock()
        upstream.raw.read = MagicMock(
            side_effect=[
                requests.exceptions.ReadTimeout("timed out"),
                b"abc",
                b"",
            ],
        )

        stop_key = RedisKeys.client_stop("1_test_111", "client_1")
        chunks = list(
            views._iter_upstream_with_stop(
                upstream, 3, redis, stop_key, stream_generation=1,
            )
        )
        self.assertEqual(chunks, [b"abc"])
        self.assertEqual(upstream.raw.read.call_count, 3)

    def test_iter_upstream_with_stop_closes_on_upstream_inactivity(self):
        redis = _FakeRedis()
        from apps.timeshift.redis_keys import TimeshiftRedisKeys as RedisKeys, TimeshiftRedisKeys

        upstream = MagicMock()
        upstream.raw.read = MagicMock(
            side_effect=requests.exceptions.ReadTimeout("timed out"),
        )
        stop_key = RedisKeys.client_stop("1_test_111", "client_1")
        times = iter([100.0, 100.0, 100.0, 111.0])

        with patch.object(views.time, "time", side_effect=lambda: next(times)):
            chunks = list(
                views._iter_upstream_with_stop(
                    upstream, 3, redis, stop_key, stream_generation=1,
                    inactivity_timeout=10,
                )
            )

        self.assertEqual(chunks, [])
        upstream.close.assert_called()


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
        from apps.timeshift.redis_keys import TimeshiftRedisKeys as RedisKeys, TimeshiftRedisKeys

        stats_channel_id = views.stats_channel_id(8, TEST_SESSION_ID)
        programme_vid = f"{TEST_MEDIA_ID}_111"
        client_key = RedisKeys.client_metadata(stats_channel_id, TEST_SESSION_ID)
        self.redis.hset(client_key, "programme_vid", programme_vid)

        connections = [
            self._conn(stats_channel_id, TEST_SESSION_ID),
            self._conn("9_2026-06-08-17-00_222", "other"),
        ]
        with patch.object(views, "get_user_active_connections",
                          return_value=connections), \
             patch.object(views, "_unregister_stats_client") as unregister_mock:
            views._allocate_stream_generation(self.redis, programme_vid, TEST_SESSION_ID)
            views._preempt_playback_streams(self.redis, TEST_SESSION_ID, self.user)
        unregister_mock.assert_not_called()
        stop_key = RedisKeys.client_stop(programme_vid, TEST_SESSION_ID)
        self.assertIn(stop_key, self.redis.store)
        stop_value = self.redis.get(stop_key)
        if isinstance(stop_value, bytes):
            stop_value = stop_value.decode()
        self.assertEqual(stop_value, "1")

    def test_preempt_leaves_other_playbacks_alone(self):
        connections = [
            self._conn("8_2026-06-09-20-00_111", "other_pos"),
        ]
        with patch.object(views, "get_user_active_connections",
                          return_value=connections), \
             patch.object(views, "_unregister_stats_client") as unregister_mock:
            views._preempt_playback_streams(self.redis, TEST_SESSION_ID, self.user)
        unregister_mock.assert_not_called()

    def test_fresh_session_id_adopts_busy_pool_for_preempt(self):
        existing = TEST_SESSION_ID
        _seed_pool_session(
            self.redis,
            session_id=existing,
            user_id=5,
            client_ip="1.2.3.4",
            client_user_agent="test-agent",
            busy="1",
        )
        request = self.factory.get(
            _proxy_url("brandnewsession"),
            HTTP_RANGE="bytes=1000-",
            HTTP_USER_AGENT="test-agent",
            REMOTE_ADDR="1.2.3.4",
        )
        streams = [_make_catchup_stream(account_id=1, stream_id="111", profile_id=31)]
        ok = MagicMock(status_code=206)
        profile = MagicMock(id=31)
        descriptor = {"account_id": "1", "stream_id": "111", "profile_id": "31"}
        with patch.object(views, "_authenticate_user", return_value=self.user), \
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
             patch.object(
                 views, "_try_reacquire_idle_pool",
                 return_value=(descriptor, profile),
             ) as reacquire_mock, \
             patch.object(views, "_stream_reused_session", return_value=ok):
            redis_cls.get_client.return_value = self.redis
            channel_cls.objects.get.return_value = MagicMock(
                id=8, name="Test", logo_id=None,
            )
            response = views.timeshift_proxy(
                request, "u", "p", "8", "2026-06-08:17-00", "8.ts",
            )
        self.assertIs(response, ok)
        reacquire_mock.assert_called_once()

    def test_plain_reconnect_preempts_busy_pool_without_range(self):
        """Plain GET reconnect should match provider byte-0 restart."""
        _seed_pool_session(self.redis, session_id=TEST_SESSION_ID)
        request = self.factory.get(_proxy_url(TEST_SESSION_ID))
        streams = [_make_catchup_stream(account_id=1, stream_id="111", profile_id=31)]
        ok = MagicMock(status_code=200)
        profile = MagicMock(id=31)
        descriptor = {"account_id": "1", "stream_id": "111", "profile_id": "31"}
        with patch.object(views, "_authenticate_user", return_value=MagicMock(id=5)), \
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
             patch.object(
                 views, "_try_reacquire_idle_pool",
                 return_value=(descriptor, profile),
             ) as reacquire_mock, \
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
        reacquire_mock.assert_called_once()
        reuse_mock.assert_called_once()
        self.assertIsNone(reuse_mock.call_args.kwargs["range_header"])
        attempt_mock.assert_not_called()

    def test_busy_pool_reuses_slot_after_scrub_preempt(self):
        _seed_pool_session(self.redis, session_id=TEST_SESSION_ID)
        request = self.factory.get(
            _proxy_url(TEST_SESSION_ID),
            HTTP_RANGE="bytes=1000-",
        )
        streams = [_make_catchup_stream(account_id=1, stream_id="111", profile_id=31)]
        ok = MagicMock(status_code=206)
        profile = MagicMock(id=31)
        descriptor = {"account_id": "1", "stream_id": "111", "profile_id": "31"}
        with patch.object(views, "_authenticate_user", return_value=MagicMock(id=5)), \
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
             patch.object(
                 views, "_try_reacquire_idle_pool",
                 return_value=(descriptor, profile),
             ) as reacquire_mock, \
             patch.object(views, "_stream_reused_session", return_value=ok) as reuse_mock, \
             patch.object(views, "_attempt_timeshift_stream", return_value=ok) as attempt_mock, \
             patch.object(views, "_force_abandon_busy_pool") as abandon_mock:
            redis_cls.get_client.return_value = self.redis
            channel_cls.objects.get.return_value = MagicMock(
                id=8, name="Test", logo_id=None,
            )
            response = views.timeshift_proxy(
                request, "u", "p", "8", "2026-06-08:17-00", "8.ts",
            )
        self.assertIs(response, ok)
        reacquire_mock.assert_called_once()
        reuse_mock.assert_called_once()
        attempt_mock.assert_not_called()
        abandon_mock.assert_not_called()
        self.assertTrue(self.redis.exists(f"timeshift:pool:{TEST_SESSION_ID}"))

    def test_stale_idle_pool_scrub_reuses_without_reserve(self):
        """Stale busy=0 while a stream is active must not reserve again."""
        _seed_pool_session(
            self.redis, session_id=TEST_SESSION_ID, busy="0", serving_range="start",
        )
        stats_channel_id = views.stats_channel_id(8, TEST_SESSION_ID)
        request = self.factory.get(
            _proxy_url(TEST_SESSION_ID),
            HTTP_RANGE="bytes=1000-",
        )
        streams = [_make_catchup_stream(account_id=1, stream_id="111", profile_id=31)]
        ok = MagicMock(status_code=206)
        profile = MagicMock(id=31)
        descriptor = {"account_id": "1", "stream_id": "111", "profile_id": "31"}
        active_conn = self._conn(stats_channel_id, TEST_SESSION_ID)
        with patch.object(views, "_authenticate_user", return_value=MagicMock(id=5)), \
             patch.object(views, "network_access_allowed", return_value=True), \
             patch.object(views, "Channel") as channel_cls, \
             patch.object(views, "_user_can_access_channel", return_value=True), \
             patch.object(views, "get_channel_catchup_streams", return_value=streams), \
             patch.object(views, "get_programme_duration", return_value=40), \
             patch.object(views, "check_user_stream_limits", return_value=True), \
             patch.object(views, "RedisClient") as redis_cls, \
             patch.object(views, "reserve_profile_slot", return_value=(True, 1, None)) as reserve_mock, \
             patch.object(views, "release_profile_slot"), \
             patch.object(views, "get_transformed_credentials", side_effect=_fake_creds), \
             patch.object(views, "get_user_active_connections", return_value=[active_conn]), \
             patch.object(
                 views, "_try_reacquire_idle_pool",
                 return_value=(descriptor, profile),
             ) as reacquire_mock, \
             patch.object(views, "_stream_reused_session", return_value=ok), \
             patch.object(views, "_attempt_timeshift_stream", return_value=ok) as attempt_mock:
            redis_cls.get_client.return_value = self.redis
            channel_cls.objects.get.return_value = MagicMock(
                id=8, name="Test", logo_id=None,
            )
            response = views.timeshift_proxy(
                request, "u", "p", "8", "2026-06-08:17-00", "8.ts",
            )
        self.assertIs(response, ok)
        reacquire_mock.assert_called_once()
        reserve_mock.assert_not_called()
        attempt_mock.assert_not_called()

    def _pool_entry_ids(self):
        return [k for k in self.redis.store if k.startswith("timeshift:pool:")]

    def test_startup_bytes_zero_deferred_without_preempt(self):
        _seed_pool_session(
            self.redis, session_id=TEST_SESSION_ID, serving_range="start",
        )
        request = self.factory.get(
            _proxy_url(TEST_SESSION_ID),
            HTTP_RANGE="bytes=0-",
        )
        streams = [_make_catchup_stream(account_id=1, stream_id="111", profile_id=31)]
        with patch.object(views, "_authenticate_user", return_value=MagicMock(id=5)), \
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
        """Near-EOF probes without a cached CDN URL still get 503 (no preempt)."""
        _seed_pool_session(self.redis, session_id=TEST_SESSION_ID)
        request = self.factory.get(
            _proxy_url(TEST_SESSION_ID),
            HTTP_RANGE="bytes=2527702896-",
        )
        streams = [_make_catchup_stream(account_id=1, stream_id="111", profile_id=31)]
        with patch.object(views, "_authenticate_user", return_value=MagicMock(id=5)), \
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
             patch.object(views, "_try_reacquire_idle_pool") as reacquire_mock, \
             patch.object(views, "_preempt_playback_streams") as preempt_mock, \
             patch.object(views, "_open_upstream") as open_mock, \
             patch.object(views, "_attempt_timeshift_stream") as attempt_mock:
            redis_cls.get_client.return_value = self.redis
            channel_cls.objects.get.return_value = MagicMock(
                id=8, name="Test", logo_id=None,
            )
            response = views.timeshift_proxy(
                request, "u", "p", "8", "2026-06-08:17-00", "8.ts",
            )
        self.assertEqual(response.status_code, 503)
        reacquire_mock.assert_not_called()
        preempt_mock.assert_not_called()
        open_mock.assert_not_called()
        attempt_mock.assert_not_called()

    def test_eof_probe_busy_session_serves_cached_cdn_without_preempt(self):
        """Busy near-EOF duration probes answer from cached CDN, no slot churn."""
        presentation_base = 500_000_000
        presentation_length = 615_251_824
        client_start = 615_139_024
        cdn_start = presentation_base + client_start
        body = b"probe-tail"
        cdn_end = cdn_start + len(body) - 1
        archive_total = 2_527_702_896

        _seed_pool_session(self.redis, session_id=TEST_SESSION_ID)
        pool_key = TimeshiftRedisKeys.pool(TEST_SESSION_ID)
        self.redis.hset(pool_key, mapping={
            "final_url": "http://cdn.example.test/archive.ts",
            "content_length": str(archive_total),
            "presentation_byte_base": str(presentation_base),
            "presentation_length": str(presentation_length),
            "provider_user_agent": "provider-agent",
            "busy": "1",
        })

        request = self.factory.get(
            _proxy_url(TEST_SESSION_ID),
            HTTP_RANGE=f"bytes={client_start}-",
        )
        streams = [_make_catchup_stream(account_id=1, stream_id="111", profile_id=31)]
        upstream = _fake_upstream(206, body=body)
        upstream.headers["Content-Range"] = (
            f"bytes {cdn_start}-{cdn_end}/{archive_total}"
        )
        upstream.headers["Content-Length"] = str(len(body))
        upstream.raw.read = MagicMock(side_effect=[body, b""])
        with patch.object(views, "_authenticate_user", return_value=MagicMock(id=5)), \
             patch.object(views, "network_access_allowed", return_value=True), \
             patch.object(views, "Channel") as channel_cls, \
             patch.object(views, "_user_can_access_channel", return_value=True), \
             patch.object(views, "get_channel_catchup_streams", return_value=streams), \
             patch.object(views, "get_programme_duration", return_value=40), \
             patch.object(views, "check_user_stream_limits", return_value=True), \
             patch.object(views, "RedisClient") as redis_cls, \
             patch.object(views, "reserve_profile_slot") as reserve_mock, \
             patch.object(views, "release_profile_slot") as release_mock, \
             patch.object(views, "get_transformed_credentials", side_effect=_fake_creds), \
             patch.object(views, "get_user_active_connections", return_value=[]), \
             patch.object(views, "_try_reacquire_idle_pool") as reacquire_mock, \
             patch.object(views, "_preempt_playback_streams") as preempt_mock, \
             patch.object(views, "_register_stats_client") as stats_mock, \
             patch.object(views, "_attempt_timeshift_stream") as attempt_mock, \
             patch.object(views.M3UAccount.objects, "get") as account_get_mock, \
             patch.object(views, "_open_upstream", return_value=upstream) as open_mock:
            redis_cls.get_client.return_value = self.redis
            channel_cls.objects.get.return_value = MagicMock(
                id=8, name="Test", logo_id=None,
            )
            response = views.timeshift_proxy(
                request, "u", "p", "8", "2026-06-08:17-00", "8.ts",
            )

        self.assertEqual(response.status_code, 206)
        self.assertEqual(
            response["Content-Range"],
            f"bytes {client_start}-{client_start + len(body) - 1}/{presentation_length}",
        )
        self.assertEqual(response["Content-Length"], str(len(body)))
        open_mock.assert_called_once()
        open_args, open_kwargs = open_mock.call_args
        self.assertEqual(open_args[0], "http://cdn.example.test/archive.ts")
        self.assertEqual(open_args[1], "provider-agent")
        self.assertEqual(
            open_args[2],
            f"bytes={cdn_start}-{cdn_start + views._EOF_PROBE_TAIL_BYTES - 1}",
        )
        self.assertFalse(open_kwargs.get("allow_redirects", True))
        account_get_mock.assert_not_called()
        reacquire_mock.assert_not_called()
        preempt_mock.assert_not_called()
        attempt_mock.assert_not_called()
        stats_mock.assert_not_called()
        reserve_mock.assert_not_called()
        release_mock.assert_not_called()
        self.assertEqual(self.redis.hget(pool_key, "busy"), "1")
        # Drain the short probe body so the generator finishes cleanly.
        self.assertEqual(b"".join(response.streaming_content), body)
        upstream.close.assert_called()

    def test_eof_probe_stale_presentation_base_uses_absolute_range(self):
        """After return-to-start, archive-absolute EOF probes must not remap past EOF."""
        stale_base = 348_248_380
        archive_total = 870_621_184
        client_start = archive_total - 112_800
        body = b"probe-tail"

        _seed_pool_session(self.redis, session_id=TEST_SESSION_ID)
        pool_key = TimeshiftRedisKeys.pool(TEST_SESSION_ID)
        self.redis.hset(pool_key, mapping={
            "final_url": "http://cdn.example.test/archive.ts",
            "content_length": str(archive_total),
            # Stale scrub window left behind after return-to-start.
            "presentation_byte_base": str(stale_base),
            "presentation_length": str(archive_total),
            "provider_user_agent": "provider-agent",
            "busy": "1",
        })

        request = self.factory.get(
            _proxy_url(TEST_SESSION_ID),
            HTTP_RANGE=f"bytes={client_start}-",
        )
        streams = [_make_catchup_stream(account_id=1, stream_id="111", profile_id=31)]
        upstream = _fake_upstream(206, body=body)
        upstream.headers["Content-Range"] = (
            f"bytes {client_start}-{client_start + len(body) - 1}/{archive_total}"
        )
        upstream.headers["Content-Length"] = str(len(body))
        upstream.raw.read = MagicMock(side_effect=[body, b""])

        with patch.object(views, "_authenticate_user", return_value=MagicMock(id=5)), \
             patch.object(views, "network_access_allowed", return_value=True), \
             patch.object(views, "Channel") as channel_cls, \
             patch.object(views, "_user_can_access_channel", return_value=True), \
             patch.object(views, "get_channel_catchup_streams", return_value=streams), \
             patch.object(views, "get_programme_duration", return_value=40), \
             patch.object(views, "check_user_stream_limits", return_value=True), \
             patch.object(views, "RedisClient") as redis_cls, \
             patch.object(views, "reserve_profile_slot"), \
             patch.object(views, "release_profile_slot"), \
             patch.object(views, "get_transformed_credentials", side_effect=_fake_creds), \
             patch.object(views, "get_user_active_connections", return_value=[]), \
             patch.object(views, "_try_reacquire_idle_pool") as reacquire_mock, \
             patch.object(views, "_preempt_playback_streams") as preempt_mock, \
             patch.object(views, "_attempt_timeshift_stream") as attempt_mock, \
             patch.object(views.M3UAccount.objects, "get") as account_get_mock, \
             patch.object(views, "_open_upstream", return_value=upstream) as open_mock:
            redis_cls.get_client.return_value = self.redis
            channel_cls.objects.get.return_value = MagicMock(
                id=8, name="Test", logo_id=None,
            )
            response = views.timeshift_proxy(
                request, "u", "p", "8", "2026-06-08:17-00", "8.ts",
            )

        self.assertEqual(response.status_code, 206)
        open_args, _open_kwargs = open_mock.call_args
        # Must NOT be stale_base + client_start (that is past archive EOF).
        self.assertEqual(open_args[1], "provider-agent")
        self.assertEqual(
            open_args[2],
            f"bytes={client_start}-{client_start + views._EOF_PROBE_TAIL_BYTES - 1}",
        )
        account_get_mock.assert_not_called()
        reacquire_mock.assert_not_called()
        preempt_mock.assert_not_called()
        attempt_mock.assert_not_called()
        self.assertEqual(b"".join(response.streaming_content), body)

    def test_eof_probe_cdn_416_returns_416_not_503(self):
        """Unsatisfiable EOF probes must not fall through to busy-slot 503."""
        archive_total = 870_621_184
        client_start = archive_total - 112_800

        _seed_pool_session(self.redis, session_id=TEST_SESSION_ID)
        pool_key = TimeshiftRedisKeys.pool(TEST_SESSION_ID)
        self.redis.hset(pool_key, mapping={
            "final_url": "http://cdn.example.test/archive.ts",
            "content_length": str(archive_total),
            "presentation_byte_base": "0",
            "presentation_length": str(archive_total),
            "provider_user_agent": "provider-agent",
            "busy": "1",
        })

        request = self.factory.get(
            _proxy_url(TEST_SESSION_ID),
            HTTP_RANGE=f"bytes={client_start}-",
        )
        streams = [_make_catchup_stream(account_id=1, stream_id="111", profile_id=31)]
        upstream = MagicMock()
        upstream.status_code = 416
        upstream.headers = {}
        upstream.close = MagicMock()

        with patch.object(views, "_authenticate_user", return_value=MagicMock(id=5)), \
             patch.object(views, "network_access_allowed", return_value=True), \
             patch.object(views, "Channel") as channel_cls, \
             patch.object(views, "_user_can_access_channel", return_value=True), \
             patch.object(views, "get_channel_catchup_streams", return_value=streams), \
             patch.object(views, "get_programme_duration", return_value=40), \
             patch.object(views, "check_user_stream_limits", return_value=True), \
             patch.object(views, "RedisClient") as redis_cls, \
             patch.object(views, "reserve_profile_slot"), \
             patch.object(views, "release_profile_slot"), \
             patch.object(views, "get_transformed_credentials", side_effect=_fake_creds), \
             patch.object(views, "get_user_active_connections", return_value=[]), \
             patch.object(views, "_attempt_timeshift_stream") as attempt_mock, \
             patch.object(views.M3UAccount.objects, "get") as account_get_mock, \
             patch.object(views, "_open_upstream", return_value=upstream) as open_mock:
            redis_cls.get_client.return_value = self.redis
            channel_cls.objects.get.return_value = MagicMock(
                id=8, name="Test", logo_id=None,
            )
            response = views.timeshift_proxy(
                request, "u", "p", "8", "2026-06-08:17-00", "8.ts",
            )

        self.assertEqual(response.status_code, 416)
        self.assertEqual(response["Content-Range"], f"bytes */{archive_total}")
        self.assertEqual(open_mock.call_args.args[1], "provider-agent")
        account_get_mock.assert_not_called()
        attempt_mock.assert_not_called()
        upstream.close.assert_called()

    def test_scrub_opens_failover_when_pool_still_busy(self):
        _seed_pool_session(self.redis, session_id=TEST_SESSION_ID)
        request = self.factory.get(
            _proxy_url(TEST_SESSION_ID),
            HTTP_RANGE="bytes=1000-",
        )
        streams = [_make_catchup_stream(account_id=1, stream_id="111", profile_id=31)]
        ok = MagicMock(status_code=206)
        with patch.object(views, "_authenticate_user", return_value=MagicMock(id=5)), \
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
             patch.object(views, "_try_reacquire_idle_pool", return_value=None) as reacquire_mock, \
             patch.object(views, "_attempt_timeshift_stream", return_value=ok) as attempt_mock:
            redis_cls.get_client.return_value = self.redis
            channel_cls.objects.get.return_value = MagicMock(
                id=8, name="Test", logo_id=None,
            )
            response = views.timeshift_proxy(
                request, "u", "p", "8", "2026-06-08:17-00", "8.ts",
            )
        self.assertIs(response, ok)
        reacquire_mock.assert_called_once()
        attempt_mock.assert_called_once()

    def test_preempt_closes_registered_upstream(self):
        stats_channel_id = views.stats_channel_id(8, TEST_SESSION_ID)
        upstream = MagicMock()
        views._register_active_upstream(stats_channel_id, TEST_SESSION_ID, upstream)
        connections = [{
            "media_id": stats_channel_id,
            "client_id": TEST_SESSION_ID,
            "type": "timeshift",
        }]
        with patch.object(views, "get_user_active_connections", return_value=connections), \
             patch.object(views, "_set_client_stop") as stop_mock:
            views._preempt_playback_streams(self.redis, TEST_SESSION_ID, MagicMock(id=5))
        stop_mock.assert_called_once()
        upstream.close.assert_called_once()

    def test_superseded_displaced_release_is_noop(self):
        _seed_pool_session(self.redis, session_id=TEST_SESSION_ID)
        self.redis.set(views._superseded_pool_key(TEST_SESSION_ID), "1")
        with patch.object(views, "release_profile_slot") as release_mock:
            views._release_pool_session(
                self.redis, TEST_SESSION_ID, 31, release_profile=False,
            )
        release_mock.assert_not_called()
        self.assertEqual(
            self.redis.hget(f"timeshift:pool:{TEST_SESSION_ID}", "busy"),
            "1",
        )

    def test_force_abandon_marks_superseded_and_discards_pool(self):
        _seed_pool_session(self.redis, session_id=TEST_SESSION_ID)
        with patch.object(views, "release_profile_slot") as release_mock:
            views._force_abandon_busy_pool(self.redis, TEST_SESSION_ID, 31)
        self.assertIn(
            views._superseded_pool_key(TEST_SESSION_ID), self.redis.store,
        )
        self.assertNotIn(f"timeshift:pool:{TEST_SESSION_ID}", self.redis.store)
        release_mock.assert_called_once_with(31, self.redis)

    def test_superseded_final_release_clears_marker_and_frees_profile(self):
        _seed_pool_session(self.redis, session_id=TEST_SESSION_ID)
        self.redis.set(views._superseded_pool_key(TEST_SESSION_ID), "1")
        with patch.object(views, "release_profile_slot") as release_mock:
            views._release_pool_session(
                self.redis, TEST_SESSION_ID, 31, release_profile=True,
            )
        release_mock.assert_called_once_with(31, self.redis)
        self.assertNotIn(
            views._superseded_pool_key(TEST_SESSION_ID), self.redis.store,
        )

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
            dispatcharr_stream_id=10,
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
            dispatcharr_stream_id=20,
            provider_timestamp="2026",
        )
        self.assertTrue(first)
        self.assertFalse(second)
        self.assertTrue(self.redis.exists(f"timeshift:pool:{TEST_SESSION_ID}"))

    def test_create_pool_session_stores_provider_tz_name(self):
        views._create_pool_session(
            self.redis,
            session_id=TEST_SESSION_ID,
            media_id=TEST_MEDIA_ID,
            user_id=5,
            client_ip="1.2.3.4",
            client_user_agent="test-agent",
            account_id=1,
            profile_id=31,
            stream_id="111",
            dispatcharr_stream_id=10,
            provider_timestamp="2026-06-08:19-00",
            provider_tz_name="Europe/Brussels",
        )
        self.assertEqual(
            self.redis.hget(f"timeshift:pool:{TEST_SESSION_ID}", "provider_tz_name"),
            "Europe/Brussels",
        )
        self.assertEqual(
            self.redis.hget(f"timeshift:pool:{TEST_SESSION_ID}", "dispatcharr_stream_id"),
            "10",
        )

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
        with patch.object(views, "_authenticate_user", return_value=MagicMock(id=5)), \
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


class CatchupProxyTests(TestCase):
    """Native ``/proxy/catchup/{uuid}`` entry point."""

    def setUp(self):
        self.factory = APIRequestFactory()
        self.user = MagicMock(id=1, user_level=10, is_authenticated=True)
        self.channel_uuid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

    def test_requires_authentication(self):
        request = self.factory.get(
            f"/proxy/catchup/{self.channel_uuid}?start=2026-06-08T17:00:00Z",
        )
        with patch.object(views, "network_access_allowed", return_value=True):
            response = views.catchup_proxy(request, self.channel_uuid)
        self.assertEqual(response.status_code, 401)

    def test_missing_start_returns_400(self):
        request = self.factory.get(f"/proxy/catchup/{self.channel_uuid}")
        force_authenticate(request, user=self.user)
        channel = MagicMock(id=8, uuid=self.channel_uuid)
        with patch.object(views, "network_access_allowed", return_value=True), \
             patch.object(views, "Channel") as channel_cls, \
             patch.object(views, "_user_can_access_channel", return_value=True):
            channel_cls.objects.get.return_value = channel
            response = views.catchup_proxy(request, self.channel_uuid)
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"Missing start", response.content)

    def test_missing_session_id_redirects(self):
        request = self.factory.get(
            f"/proxy/catchup/{self.channel_uuid}?start=2026-06-08T17:00:00Z",
        )
        force_authenticate(request, user=self.user)
        channel = MagicMock(id=8, uuid=self.channel_uuid)
        with patch.object(views, "network_access_allowed", return_value=True), \
             patch.object(views, "Channel") as channel_cls, \
             patch.object(views, "_user_can_access_channel", return_value=True), \
             patch.object(views, "get_channel_catchup_streams",
                          return_value=[_make_catchup_stream()]), \
             patch.object(views, "get_programme_duration", return_value=40), \
             patch.object(views, "parse_catchup_timestamp", return_value=True), \
             patch.object(views, "RedisClient") as redis_cls:
            redis_cls.get_client.return_value = _FakeRedis()
            channel_cls.objects.get.return_value = channel
            response = views.catchup_proxy(request, self.channel_uuid)
        self.assertEqual(response.status_code, 301)
        self.assertIn("session_id=", response["Location"])
        self.assertIn("start=", response["Location"])

    def test_xc_entry_delegates_to_serve_catchup(self):
        request = self.factory.get(_proxy_url())
        with patch.object(views, "_authenticate_user", return_value=MagicMock(id=1)), \
             patch.object(views, "network_access_allowed", return_value=True), \
             patch.object(views, "Channel") as channel_cls, \
             patch.object(views, "_user_can_access_channel", return_value=True), \
             patch.object(views, "_serve_catchup", return_value=HttpResponse("ok")) as serve:
            channel_cls.objects.get.return_value = MagicMock(id=8)
            response = views.timeshift_proxy(
                request, "u", "p", "8", "2026-06-08:17-00", "8.ts",
            )
        self.assertEqual(response.status_code, 200)
        serve.assert_called_once()


class TimeshiftProviderFaithfulPlainGetTests(_ProxyLoopTestMixin, TestCase):
    """Contract tests for plain GET reconnect (no Range header)."""

    def setUp(self):
        self.redis = _FakeRedis()
        self.virtual_channel_id = f"{TEST_MEDIA_ID}_111"
        self.stats_channel_id = views.stats_channel_id(8, TEST_SESSION_ID)
        self.client_id = TEST_SESSION_ID
        self.user = MagicMock(id=5, username="viewer")

    @patch.object(views, "_trigger_timeshift_stats_update")
    @patch.object(views, "_open_upstream")
    def test_plain_get_does_not_send_range_to_upstream(self, mocked_open, _trigger_mock):
        ts = _make_ts_payload(188 * 7)
        mocked_open.return_value = _fake_upstream(200, body=ts)

        views._stream_from_provider(
            candidate_urls=["http://example.test/timeshift.ts"],
            user_agent="provider-agent",
            range_header=None,
            virtual_channel_id=self.virtual_channel_id,
            stats_channel_id=self.stats_channel_id,
            client_id=self.client_id,
            client_ip="1.2.3.4",
            client_user_agent="test-agent",
            user=self.user,
            channel_display_name="A&E",
            timestamp_utc="2026-06-08:17-00",
            channel_logo_id=None,
            m3u_profile_id=31,
            debug=False,
            account_id=None,
            redis_client=self.redis,
            pool_session_id=self.client_id,
            channel_id=8,
            channel_uuid="00000000-0000-0000-0000-000000000008",
            duration_minutes=40,
        )

        mocked_open.assert_called_once()
        self.assertIsNone(mocked_open.call_args.args[2])

    @patch.object(views, "_trigger_timeshift_stats_update")
    @patch.object(views, "_open_upstream")
    def test_plain_get_passes_through_provider_200_without_content_range(
        self, mocked_open, _trigger_mock,
    ):
        ts = _make_ts_payload(188 * 7)
        upstream = _fake_upstream(200, body=ts)
        upstream.headers["Content-Length"] = str(len(ts))
        mocked_open.return_value = upstream

        response = views._stream_from_provider(
            candidate_urls=["http://example.test/timeshift.ts"],
            user_agent="provider-agent",
            range_header=None,
            virtual_channel_id=self.virtual_channel_id,
            stats_channel_id=self.stats_channel_id,
            client_id=self.client_id,
            client_ip="1.2.3.4",
            client_user_agent="test-agent",
            user=self.user,
            channel_display_name="A&E",
            timestamp_utc="2026-06-08:17-00",
            channel_logo_id=None,
            m3u_profile_id=31,
            debug=False,
            account_id=None,
            redis_client=self.redis,
            pool_session_id=self.client_id,
            channel_id=8,
            channel_uuid="00000000-0000-0000-0000-000000000008",
            duration_minutes=40,
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("Content-Range", response)
        self.assertEqual(response["Accept-Ranges"], "bytes")
        self.assertEqual(response["Content-Length"], str(len(ts)))


class TimeshiftDownstreamLengthHeaderTests(TestCase):
    def test_open_ended_range_passthrough_upstream_headers(self):
        headers = views._build_downstream_length_headers(
            range_header="bytes=1000-",
            status_code=206,
            representation_length=10000,
            upstream_content_range="bytes 1000-2047/10000",
            upstream_content_length="1048",
        )
        self.assertEqual(headers["Content-Range"], "bytes 1000-2047/10000")
        self.assertEqual(headers["Content-Length"], "1048")
        self.assertEqual(headers["Accept-Ranges"], "bytes")

    def test_closed_range_passthrough_upstream_headers(self):
        headers = views._build_downstream_length_headers(
            range_header="bytes=1000-4999",
            status_code=206,
            representation_length=10000,
            upstream_content_range="bytes 1000-4999/10000",
            upstream_content_length="4000",
        )
        self.assertEqual(headers["Content-Range"], "bytes 1000-4999/10000")
        self.assertEqual(headers["Content-Length"], "4000")

    def test_206_synthesizes_range_when_upstream_omits_it(self):
        headers = views._build_downstream_length_headers(
            range_header="bytes=1000-",
            status_code=206,
            representation_length=10000,
            upstream_content_range=None,
            upstream_content_length="1048",
        )
        self.assertEqual(headers["Content-Range"], "bytes 1000-9999/10000")
        self.assertEqual(headers["Content-Length"], "1048")

    def test_full_file_response_sets_content_length_when_not_streaming(self):
        headers = views._build_downstream_length_headers(
            range_header=None,
            status_code=200,
            representation_length=10000,
            upstream_content_range=None,
            upstream_content_length="10000",
        )
        self.assertEqual(headers["Content-Length"], "10000")
        self.assertNotIn("Content-Range", headers)

    def test_streaming_plain_get_includes_content_length(self):
        headers = views._build_downstream_length_headers(
            range_header=None,
            status_code=200,
            representation_length=10000,
            upstream_content_range=None,
            upstream_content_length="10000",
            streaming=True,
        )
        self.assertEqual(headers["Content-Length"], "10000")
        self.assertEqual(headers["Accept-Ranges"], "bytes")
        self.assertNotIn("Content-Range", headers)

    def test_passthrough_includes_accept_ranges(self):
        response = views._passthrough_response(416, "bytes */10000")
        self.assertEqual(response["Content-Range"], "bytes */10000")
        self.assertEqual(response["Accept-Ranges"], "bytes")


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
