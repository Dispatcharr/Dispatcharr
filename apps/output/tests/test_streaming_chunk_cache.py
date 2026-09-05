import json
import threading
import time
import uuid

import redis as redis_library
from django.conf import settings
from django.test import TransactionTestCase

from apps.output.streaming_chunk_cache import (
    STATUS_BUILDING,
    STATUS_READY,
    _chunks_key,
    _lock_key,
    _ready_key,
    _status_key,
    stream_cached_response,
)


def _consume(response):
    return b"".join(response.streaming_content).decode("utf-8")


class StreamingChunkCacheTests(TransactionTestCase):
    def setUp(self):
        self.redis = redis_library.Redis(host=settings.REDIS_HOST, port=settings.REDIS_PORT, db=15)
        self.key = f"epg_content:unit-{uuid.uuid4().hex}"

    def tearDown(self):
        keys = list(self.redis.scan_iter(match=self.key + "*"))
        if keys:
            self.redis.delete(*keys)

    def test_leader_caches_chunks_and_sets_ready(self):
        redis = self.redis
        calls = []

        def source():
            calls.append(1)
            yield "<tv>"
            yield "</tv>"

        body = _consume(stream_cached_response(self.key, source, redis=redis))

        self.assertEqual(body, "<tv></tv>")
        self.assertEqual(calls, [1])
        manifest = json.loads(redis.get(_ready_key(self.key)))
        build_key = f"{self.key}:build:{manifest['id']}"
        self.assertEqual(redis.get(_status_key(build_key)), STATUS_READY.encode())
        self.assertEqual(manifest["count"], 2)
        self.assertEqual(redis.llen(_chunks_key(build_key)), 2)
        self.assertFalse(redis.exists(_lock_key(self.key)))

    def test_cache_hit_skips_source(self):
        redis = self.redis
        calls = []

        def source():
            calls.append(1)
            yield "<tv>"
            yield "</tv>"

        _consume(stream_cached_response(self.key, source, redis=redis))
        calls.clear()
        body = _consume(stream_cached_response(self.key, source, redis=redis))

        self.assertEqual(body, "<tv></tv>")
        self.assertEqual(calls, [])

    def test_follower_reads_leader_chunks_without_rebuilding(self):
        redis = self.redis
        base = self.key
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
                stream_cached_response(
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
            stream_cached_response(
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
        redis = self.redis
        build_calls = []
        barrier = threading.Barrier(2)
        results = {}

        def source():
            build_calls.append(threading.current_thread().name)
            yield "x"

        def worker():
            barrier.wait()
            results[threading.current_thread().name] = _consume(
                stream_cached_response(
                    self.key,
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

    def test_invalidation_advances_revision_without_deleting_old_chunks(self):
        from apps.epg.services import get_epg_revision
        from apps.output.streaming_chunk_cache import invalidate_epg_chunk_cache

        revision = get_epg_revision()
        self.redis.set(self.key + ":ready", "retained")
        self.redis.rpush(self.key + ":chunks", b"<tv/>")
        self.assertTrue(invalidate_epg_chunk_cache())
        self.assertNotEqual(get_epg_revision(), revision)
        self.assertTrue(self.redis.exists(self.key + ":ready"))
        self.assertTrue(self.redis.exists(self.key + ":chunks"))

    def test_invalidate_m3u_content_cache_uses_django_delete_pattern(self):
        from unittest.mock import MagicMock, patch

        from apps.output.streaming_chunk_cache import invalidate_m3u_content_cache

        mock_cache = MagicMock()
        mock_cache.delete_pattern.return_value = 3

        with patch(
            "django.core.cache.cache",
            mock_cache,
        ):
            invalidate_m3u_content_cache()

        mock_cache.delete_pattern.assert_called_once_with("m3u_content:*")

    def test_invalidate_m3u_content_cache_clears_real_django_keys(self):
        from django.core.cache import cache

        from apps.output.streaming_chunk_cache import invalidate_m3u_content_cache

        cache.set("m3u_content:all:anonymous:origin=http://x", "#EXTM3U\n", 60)
        cache.set("unrelated:key", "keep", 60)

        invalidate_m3u_content_cache()

        self.assertIsNone(cache.get("m3u_content:all:anonymous:origin=http://x"))
        self.assertEqual(cache.get("unrelated:key"), "keep")
        cache.delete("unrelated:key")

    def test_invalidate_output_caches_after_m3u_refresh_clears_both(self):
        from unittest.mock import patch

        from apps.output.streaming_chunk_cache import (
            invalidate_output_caches_after_m3u_refresh,
        )

        with (
            patch(
                "apps.output.streaming_chunk_cache.invalidate_m3u_content_cache"
            ) as mock_m3u,
            patch(
                "apps.output.streaming_chunk_cache.invalidate_epg_chunk_cache"
            ) as mock_epg,
        ):
            invalidate_output_caches_after_m3u_refresh()

        mock_m3u.assert_called_once_with()
        mock_epg.assert_called_once_with()
