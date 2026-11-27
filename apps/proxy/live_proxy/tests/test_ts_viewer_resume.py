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
from apps.proxy.live_proxy.redis_keys import RedisKeys

CHANNEL_ID = 'resume-channel'
APPLE_TV = ('10.1.1.50', 'UHF/2.2 AppleTV')


class _KV:
    """Minimal Redis stand-in for string keys with TTL."""

    def __init__(self):
        self.kv = {RedisKeys.channel_metadata(CHANNEL_ID): b'meta'}
        self.ttl = {}

    def get(self, key):
        return self.kv.get(key)

    def exists(self, key):
        return int(key in self.kv)

    def eval(self, _script, _numkeys, key, value, ttl):
        # Same semantics as the generator's Lua script: keep the maximum.
        current = int(self.kv.get(key, b'-1'))
        if int(value) > current:
            self.kv[key] = str(value).encode()
        self.ttl[key] = ttl
        return 1

    def positions(self):
        return {k: v for k, v in self.kv.items() if ':resume:' in k}


class _Buffer:
    def __init__(self, head, time_index, index_key=None):
        self.index = head
        self._time_index = time_index
        self.buffer_index_key = index_key or RedisKeys.buffer_index(CHANNEL_ID)

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

    def _generator(self, buffer, viewer=APPLE_TV, client_id='client-1'):
        return StreamGenerator(
            CHANNEL_ID, client_id, viewer[0], viewer[1], buffer=buffer, channel_name='HGTV',
        )

    def _start(self, buffer, viewer=APPLE_TV, client_id='client-2'):
        gen = StreamGenerator(
            CHANNEL_ID, client_id, viewer[0], viewer[1], buffer=buffer, channel_name='HGTV',
        )
        self.assertTrue(gen._setup_streaming())
        return gen

    def _previous_request_reached(self, index, viewer=APPLE_TV, buffer=None):
        gen = self._generator(buffer or _Buffer(head=index, time_index=0), viewer=viewer)
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

    def test_position_is_throttled_and_kept_as_long_as_chunks(self):
        gen = self._generator(_Buffer(head=10, time_index=0))
        gen.local_index = 10
        gen.chunks_sent = 10
        with patch(
            'apps.proxy.live_proxy.output.ts.generator.ConfigHelper.redis_chunk_ttl',
            return_value=120,
        ):
            gen._record_resume_position()
            [(key, value)] = self.redis.positions().items()
            self.assertEqual(value, b'10')
            self.assertEqual(self.redis.ttl[key], 120)

            gen.local_index = 12
            gen._record_resume_position()  # within the throttle window
            self.assertEqual(self.redis.kv[key], b'10')

            gen._record_resume_position(force=True)
            self.assertEqual(self.redis.kv[key], b'12')

    def test_closing_mid_batch_keeps_the_chunks_already_sent(self):
        gen = self._generator(_Buffer(head=20, time_index=0))
        gen.local_index = 10
        gen.proxy_server = self.server
        stream = gen._process_chunks([b'a', b'b', b'c', b'd'], 14)
        next(stream)  # chunk 11
        next(stream)  # chunk 11 written; chunk 12 handed over
        next(stream)  # chunk 12 written; chunk 13 handed over
        stream.close()  # player hung up while chunk 13 was being written
        gen._record_resume_position(force=True)

        # Chunk 12 is the last one the response finished writing.
        [value] = self.redis.positions().values()
        self.assertEqual(value, b'12')

    def test_late_cleanup_of_an_older_request_does_not_move_the_position_back(self):
        self._previous_request_reached(80)
        self._previous_request_reached(40)

        [value] = self.redis.positions().values()
        self.assertEqual(value, b'80')

    def test_non_owner_worker_uses_the_shared_buffer_head(self):
        # This worker's buffer copy says 50; the owner already wrote chunk 80.
        self._previous_request_reached(80)
        self.redis.kv[RedisKeys.buffer_index(CHANNEL_ID)] = b'80'

        gen = self._start(_Buffer(head=50, time_index=0))

        self.assertEqual(gen.local_index, 80)

    def test_transcoded_profile_buffer_has_its_own_position(self):
        profile_buffer = _Buffer(head=80, time_index=0, index_key='live:channel:x:profile:3:index')
        self._previous_request_reached(80, buffer=profile_buffer)

        gen = self._start(_Buffer(head=80, time_index=0))

        self.assertEqual(gen.local_index, 0)

    def test_no_position_is_written_after_the_channel_was_torn_down(self):
        del self.redis.kv[RedisKeys.channel_metadata(CHANNEL_ID)]

        self._previous_request_reached(30)

        self.assertEqual(self.redis.positions(), {})

    def test_nothing_is_written_before_any_chunk_was_sent(self):
        gen = self._generator(_Buffer(head=10, time_index=0))
        gen.local_index = 5
        gen._record_resume_position(force=True)
        self.assertEqual(self.redis.positions(), {})
