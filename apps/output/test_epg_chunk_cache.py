import threading
import time
from unittest import TestCase

from apps.output.epg_chunk_cache import (
    STATUS_BUILDING,
    STATUS_READY,
    _chunks_key,
    _lock_key,
    _ready_key,
    _status_key,
    stream_epg_response,
)


class FakeRedis:
    """Minimal Redis stand-in for chunk-cache unit tests."""

    def __init__(self):
        self._strings = {}
        self._lists = {}
        self._expires_at = {}

    def _purge_expired(self):
        now = time.monotonic()
        expired = [key for key, deadline in self._expires_at.items() if deadline <= now]
        for key in expired:
            self._strings.pop(key, None)
            self._lists.pop(key, None)
            self._expires_at.pop(key, None)

    def get(self, key):
        self._purge_expired()
        return self._strings.get(key)

    def set(self, key, value, nx=False, ex=None):
        self._purge_expired()
        if nx and key in self._strings:
            return None
        self._strings[key] = value
        if ex is not None:
            self._expires_at[key] = time.monotonic() + ex
        return True

    def delete(self, *keys):
        for key in keys:
            self._strings.pop(key, None)
            self._lists.pop(key, None)
            self._expires_at.pop(key, None)

    def exists(self, key):
        self._purge_expired()
        return key in self._strings or key in self._lists

    def expire(self, key, ttl):
        if key in self._strings or key in self._lists:
            self._expires_at[key] = time.monotonic() + ttl
        return True

    def rpush(self, key, value):
        self._lists.setdefault(key, []).append(value)

    def lindex(self, key, offset):
        items = self._lists.get(key, [])
        if offset < len(items):
            return items[offset]
        return None

    def llen(self, key):
        return len(self._lists.get(key, []))


def _consume(response):
    return b"".join(response.streaming_content).decode("utf-8")


class EPGChunkCacheTests(TestCase):
    def test_leader_caches_chunks_and_sets_ready(self):
        redis = FakeRedis()
        calls = []

        def source():
            calls.append(1)
            yield "<tv>"
            yield "</tv>"

        body = _consume(stream_epg_response("epg:test", source, redis=redis))

        self.assertEqual(body, "<tv></tv>")
        self.assertEqual(calls, [1])
        self.assertEqual(redis.get(_ready_key("epg:test")), "1")
        self.assertEqual(redis.get(_status_key("epg:test")), STATUS_READY)
        self.assertEqual(redis.llen(_chunks_key("epg:test")), 2)
        self.assertFalse(redis.exists(_lock_key("epg:test")))

    def test_cache_hit_skips_source(self):
        redis = FakeRedis()
        calls = []

        def source():
            calls.append(1)
            yield "<tv>"
            yield "</tv>"

        _consume(stream_epg_response("epg:test", source, redis=redis))
        calls.clear()
        body = _consume(stream_epg_response("epg:test", source, redis=redis))

        self.assertEqual(body, "<tv></tv>")
        self.assertEqual(calls, [])

    def test_follower_reads_leader_chunks_without_rebuilding(self):
        redis = FakeRedis()
        base = "epg:follow"
        leader_started = threading.Event()
        rebuild_calls = []

        def slow_source():
            rebuild_calls.append(1)
            leader_started.set()
            yield "a"
            time.sleep(0.05)
            yield "b"

        def forbidden_source():
            rebuild_calls.append(2)
            yield "SHOULD_NOT_RUN"

        def leader():
            _consume(
                stream_epg_response(
                    base,
                    slow_source,
                    redis=redis,
                    poll_interval=0.01,
                )
            )

        leader_thread = threading.Thread(target=leader)
        leader_thread.start()
        leader_started.wait(timeout=5)
        follower_body = _consume(
            stream_epg_response(
                base,
                forbidden_source,
                redis=redis,
                poll_interval=0.01,
            )
        )
        leader_thread.join(timeout=5)

        self.assertEqual(follower_body, "ab")
        self.assertEqual(rebuild_calls, [1])

    def test_only_one_leader_when_two_clients_start_together(self):
        redis = FakeRedis()
        build_calls = []
        barrier = threading.Barrier(2)
        results = {}

        def source():
            build_calls.append(threading.current_thread().name)
            yield "x"

        def worker():
            barrier.wait()
            results[threading.current_thread().name] = _consume(
                stream_epg_response(
                    "epg:race",
                    source,
                    redis=redis,
                    poll_interval=0.01,
                )
            )

        threads = [
            threading.Thread(target=worker, name="t1"),
            threading.Thread(target=worker, name="t2"),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        self.assertEqual(results["t1"], "x")
        self.assertEqual(results["t2"], "x")
        self.assertEqual(len(build_calls), 1)
