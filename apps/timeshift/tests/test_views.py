"""Tests for the timeshift proxy view, focused on upstream status mapping."""

from unittest.mock import MagicMock, patch

from django.test import RequestFactory, TestCase

from apps.timeshift import views
from apps.proxy.live_proxy.input.http_streamer import find_ts_sync as _find_ts_sync, _TS_PACKET_SIZE


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
    def test_upstream_500_short_circuits_loop(self, mocked_open):
        mocked_open.return_value = _fake_upstream(500)
        response = views._stream_from_provider(**self.kwargs)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(mocked_open.call_count, 1)

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

    @patch.object(views, "_open_upstream")
    def test_cache_promotes_winning_index_to_first(self, mocked_open):
        """Once a candidate succeeds for an account, the next request reorders
        the list so the cached winner is tried first — saving cascade
        overhead on fast-forward."""
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
