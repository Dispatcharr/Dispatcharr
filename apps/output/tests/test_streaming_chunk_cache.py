import threading
import time
from unittest import TestCase

from apps.output.streaming_chunk_cache import (
    EPG_CACHE_GENERATION_KEY,
    STATUS_BUILDING,
    STATUS_READY,
    _chunks_key,
    _lock_key,
    _ready_key,
    _status_key,
    stream_cached_response,
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

    def incr(self, key):
        value = int(self._strings.get(key, 0)) + 1
        self._strings[key] = str(value).encode("utf-8")
        return value

    def rpush(self, key, value):
        self._lists.setdefault(key, []).append(value)

    def lindex(self, key, offset):
        items = self._lists.get(key, [])
        if offset < len(items):
            return items[offset]
        return None

    def llen(self, key):
        return len(self._lists.get(key, []))

    def scan_iter(self, match=None, count=None):  # noqa: ARG002
        self._purge_expired()
        import fnmatch

        keys = list(self._strings) + list(self._lists)
        if match:
            # Redis glob: * matches anything
            pattern = match
            for key in keys:
                if fnmatch.fnmatch(key, pattern):
                    yield key
        else:
            yield from keys


def _consume(response):
    return b"".join(response.streaming_content).decode("utf-8")


class StreamingChunkCacheTests(TestCase):
    def test_leader_caches_chunks_and_sets_ready(self):
        redis = FakeRedis()
        calls = []

        def source():
            calls.append(1)
            yield "<tv>"
            yield "</tv>"

        body = _consume(stream_cached_response("cache:test", source, redis=redis))

        self.assertEqual(body, "<tv></tv>")
        self.assertEqual(calls, [1])
        self.assertEqual(redis.get(_ready_key("cache:test")), "1")
        self.assertEqual(redis.get(_status_key("cache:test")), STATUS_READY)
        self.assertEqual(redis.llen(_chunks_key("cache:test")), 2)
        self.assertFalse(redis.exists(_lock_key("cache:test")))

    def test_cache_hit_skips_source(self):
        redis = FakeRedis()
        calls = []

        def source():
            calls.append(1)
            yield "<tv>"
            yield "</tv>"

        _consume(stream_cached_response("cache:test", source, redis=redis))
        calls.clear()
        body = _consume(stream_cached_response("cache:test", source, redis=redis))

        self.assertEqual(body, "<tv></tv>")
        self.assertEqual(calls, [])

    def test_follower_reads_leader_chunks_without_rebuilding(self):
        redis = FakeRedis()
        base = "cache:follow"
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
                stream_cached_response(
                    "cache:race",
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

    def test_invalidate_epg_chunk_cache_advances_generation_without_deleting(self):
        from unittest.mock import patch

        from apps.output.streaming_chunk_cache import invalidate_epg_chunk_cache

        redis = FakeRedis()
        redis.set("epg_content:all:anonymous:d=0:g=0:ready", "1")
        redis.rpush("epg_content:all:anonymous:d=0:g=0:chunks", b"<tv/>")

        with patch(
            "apps.output.streaming_chunk_cache._get_redis",
            return_value=redis,
        ):
            invalidate_epg_chunk_cache()
            invalidate_epg_chunk_cache()

        self.assertEqual(redis.get(EPG_CACHE_GENERATION_KEY), b"2")
        # Retired entries are left to expire so in-flight readers keep their data.
        self.assertTrue(redis.exists("epg_content:all:anonymous:d=0:g=0:ready"))
        self.assertTrue(redis.exists("epg_content:all:anonymous:d=0:g=0:chunks"))

    def test_generation_key_retires_cached_response(self):
        redis = FakeRedis()
        versions = iter(["old", "new"])

        def source():
            yield f"<tv>{next(versions)}</tv>"

        def fetch():
            return _consume(
                stream_cached_response(
                    "epg_content:test",
                    source,
                    redis=redis,
                    generation_key=EPG_CACHE_GENERATION_KEY,
                )
            )

        self.assertEqual(fetch(), "<tv>old</tv>")
        self.assertEqual(fetch(), "<tv>old</tv>")
        redis.incr(EPG_CACHE_GENERATION_KEY)
        self.assertEqual(fetch(), "<tv>new</tv>")

    def _invalidate_epg_cache(self, redis):
        from unittest.mock import patch

        from apps.output.streaming_chunk_cache import invalidate_epg_chunk_cache

        with patch(
            "apps.output.streaming_chunk_cache._get_redis",
            return_value=redis,
        ):
            invalidate_epg_chunk_cache()

    def _invalidate_during_build(self, redis, source, invalidate_after):
        """Run a leader build, invalidating the EPG cache after N chunks."""
        response = stream_cached_response(
            "epg_content:test",
            source,
            redis=redis,
            generation_key=EPG_CACHE_GENERATION_KEY,
        )
        body = []
        for index, chunk in enumerate(response.streaming_content, start=1):
            body.append(chunk)
            if index == invalidate_after:
                self._invalidate_epg_cache(redis)
        return b"".join(body).decode("utf-8")

    def test_invalidate_during_build_never_caches_partial_document(self):
        """Regression for #1650: a mid-build invalidation must not publish
        a chunk list missing the XML header and opening <tv> element."""
        redis = FakeRedis()
        document = ["<?xml?>", "<tv>", "<channel/>", "<programme/>", "<programme/>", "</tv>"]

        def source():
            yield from document

        in_flight = self._invalidate_during_build(redis, source, invalidate_after=3)
        later = _consume(
            stream_cached_response(
                "epg_content:test",
                source,
                redis=redis,
                generation_key=EPG_CACHE_GENERATION_KEY,
            )
        )

        self.assertEqual(in_flight, "".join(document))
        self.assertEqual(later, "".join(document))
        # The retired build finished intact under its own key.
        self.assertEqual(redis.llen(_chunks_key("epg_content:test:g=0")), len(document))

    def test_new_leader_after_invalidate_does_not_share_chunk_list(self):
        """A request arriving after invalidation builds under a new key, so two
        leaders can never interleave chunks into one list."""
        redis = FakeRedis()
        document = ["<tv>", "<a/>", "<b/>", "</tv>"]

        def source():
            yield from document

        old_leader = iter(
            stream_cached_response(
                "epg_content:test",
                source,
                redis=redis,
                generation_key=EPG_CACHE_GENERATION_KEY,
            ).streaming_content
        )
        old_body = [next(old_leader), next(old_leader)]

        self._invalidate_epg_cache(redis)
        new_leader = iter(
            stream_cached_response(
                "epg_content:test",
                source,
                redis=redis,
                generation_key=EPG_CACHE_GENERATION_KEY,
            ).streaming_content
        )
        new_body = [next(new_leader), next(new_leader)]
        old_body.extend(old_leader)
        new_body.extend(new_leader)

        expected = "".join(document)
        self.assertEqual(b"".join(old_body).decode("utf-8"), expected)
        self.assertEqual(b"".join(new_body).decode("utf-8"), expected)
        self.assertEqual(redis.llen(_chunks_key("epg_content:test:g=0")), len(document))
        self.assertEqual(redis.llen(_chunks_key("epg_content:test:g=1")), len(document))
        self.assertFalse(redis.exists(_lock_key("epg_content:test:g=1")))

    def test_follower_mid_read_survives_invalidate(self):
        """A follower partway through reading an in-flight build still gets
        the complete document after invalidation."""
        redis = FakeRedis()
        document = ["<tv>", "<a/>", "<b/>", "</tv>"]

        def source():
            yield from document

        def forbidden_source():
            raise AssertionError("follower must not rebuild")
            yield  # pragma: no cover

        leader = iter(
            stream_cached_response(
                "epg_content:test",
                source,
                redis=redis,
                generation_key=EPG_CACHE_GENERATION_KEY,
            ).streaming_content
        )
        leader_body = [next(leader), next(leader)]
        follower = iter(
            stream_cached_response(
                "epg_content:test",
                forbidden_source,
                redis=redis,
                poll_interval=0.01,
                generation_key=EPG_CACHE_GENERATION_KEY,
            ).streaming_content
        )
        follower_body = [next(follower), next(follower)]

        self._invalidate_epg_cache(redis)
        leader_body.extend(leader)
        follower_body.extend(follower)

        expected = "".join(document)
        self.assertEqual(b"".join(leader_body).decode("utf-8"), expected)
        self.assertEqual(b"".join(follower_body).decode("utf-8"), expected)

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
