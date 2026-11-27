"""A player that reopens the stream must not get content it already showed.

Seen in production: the upstream stalled, the player opened a second request
for the same channel, and the proxy placed it "25 s behind live". The buffer
was younger than 25 s, so that meant chunk 0, and ~15 s of video played again.
The proxy now remembers how far each viewer (client IP + user agent) got and
never starts that viewer earlier than that.
"""

import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import TestCase

from apps.proxy.live_proxy.output.ts.generator import StreamGenerator

CHANNEL_ID = 'resume-channel'
APPLE_TV = ('10.1.1.50', 'UHF/2.2 AppleTV')


class _KV:
    """Minimal Redis stand-in for string keys with TTL."""

    def __init__(self):
        self.kv = {}
        self.ttl = {}

    def get(self, key):
        return self.kv.get(key)

    def setex(self, key, ttl, value):
        self.kv[key] = str(value).encode()
        self.ttl[key] = ttl


class _Buffer:
    def __init__(self, head, time_index):
        self.index = head
        self._time_index = time_index

    def find_chunk_index_by_time(self, _seconds):
        return self._time_index

    def find_oldest_available_chunk(self, _index):
        return 0


class TsViewerResumeTests(TestCase):
    def setUp(self):
        self.redis = _KV()
        self.server = MagicMock()
        self.server.redis_client = self.redis
        self.server.stream_managers = {}
        self.enterContext(patch(
            'apps.proxy.live_proxy.output.ts.generator.ProxyServer.get_instance',
            return_value=self.server,
        ))
        self.enterContext(patch(
            'apps.proxy.live_proxy.output.ts.generator.ConfigHelper.new_client_behind_seconds',
            return_value=25,
        ))

    def _start(self, buffer, viewer=APPLE_TV, client_id='client-2'):
        gen = StreamGenerator(
            CHANNEL_ID, client_id, viewer[0], viewer[1], buffer=buffer, channel_name='HGTV',
        )
        self.assertTrue(gen._setup_streaming())
        return gen

    def _previous_request_reached(self, index, viewer=APPLE_TV):
        gen = StreamGenerator(
            CHANNEL_ID, 'client-1', viewer[0], viewer[1],
            buffer=_Buffer(head=index, time_index=0), channel_name='HGTV',
        )
        gen.local_index = index
        gen.chunks_sent = index
        gen._record_resume_position(force=True)

    def test_first_request_uses_time_based_position(self):
        gen = self._start(_Buffer(head=25, time_index=0))
        self.assertEqual(gen.local_index, 0)

    def test_reopened_request_resumes_where_the_viewer_stopped(self):
        self._previous_request_reached(38)

        gen = self._start(_Buffer(head=38, time_index=0))

        self.assertEqual(gen.local_index, 38)

    def test_other_viewer_is_not_affected(self):
        self._previous_request_reached(38)

        gen = self._start(_Buffer(head=38, time_index=0), viewer=('10.1.1.51', 'VLC/3.0'))

        self.assertEqual(gen.local_index, 0)

    def test_old_position_never_moves_the_viewer_further_back(self):
        # The viewer left long ago: the time-based start is already newer.
        self._previous_request_reached(40)

        gen = self._start(_Buffer(head=400, time_index=300))

        self.assertEqual(gen.local_index, 300)

    def test_position_beyond_buffer_head_is_ignored(self):
        # Left over from a previous run of the channel whose index was higher.
        self._previous_request_reached(500)

        gen = self._start(_Buffer(head=30, time_index=0))

        self.assertEqual(gen.local_index, 0)

    def test_position_is_written_with_a_short_ttl_and_throttled(self):
        gen = StreamGenerator(
            CHANNEL_ID, 'client-1', *APPLE_TV, buffer=_Buffer(head=10, time_index=0),
            channel_name='HGTV',
        )
        gen.local_index = 10
        gen.chunks_sent = 10
        gen._record_resume_position()
        [(key, value)] = self.redis.kv.items()
        self.assertEqual(value, b'10')
        self.assertLessEqual(self.redis.ttl[key], 120)

        gen.local_index = 12
        gen._record_resume_position()  # within the throttle window
        self.assertEqual(self.redis.kv[key], b'10')

        gen._record_resume_position(force=True)
        self.assertEqual(self.redis.kv[key], b'12')

    def test_nothing_is_written_before_any_chunk_was_sent(self):
        gen = StreamGenerator(
            CHANNEL_ID, 'client-1', *APPLE_TV, buffer=_Buffer(head=10, time_index=0),
            channel_name='HGTV',
        )
        gen.local_index = 5
        gen._record_resume_position(force=True)
        self.assertEqual(self.redis.kv, {})
