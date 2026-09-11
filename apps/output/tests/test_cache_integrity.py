"""Regressions against real Redis, including invalidation during consumption."""
import json
import threading
import time
import uuid
from unittest.mock import patch

import redis as redis_library
from django.conf import settings
from django.test import TransactionTestCase

from apps.epg.services import get_epg_revision
from apps.output import streaming_chunk_cache as cache


def consume(response):
    try:
        return b"".join(response.streaming_content)
    finally:
        response.close()


class CacheIntegrityTests(TransactionTestCase):
    def setUp(self):
        self.redis = redis_library.Redis(host=settings.REDIS_HOST, port=settings.REDIS_PORT, db=14)
        self.prefix = f"epg_content:test-{uuid.uuid4().hex}"
        self.chunks = ["<tv>", "<programme><title>Épisode</title></programme>", "</tv>"]

    def tearDown(self):
        keys = list(self.redis.scan_iter(match=self.prefix + "*"))
        if keys:
            self.redis.delete(*keys)

    def response(self, source=None, *, key=None, **kwargs):
        return cache.stream_cached_response(key or self.prefix, source or (lambda: iter(self.chunks)), redis=self.redis, **kwargs)

    def test_invalidation_does_not_delete_an_active_cached_reader(self):
        key = self.prefix + ":" + get_epg_revision()
        expected = consume(self.response(key=key))
        response = self.response(key=key)
        stream = iter(response.streaming_content)
        first = next(stream)
        with patch.object(cache, "_get_redis", return_value=self.redis):
            cache.invalidate_epg_chunk_cache()
        self.assertEqual(first + b"".join(stream), expected)
        response.close()

    def test_invalidated_producer_cannot_republish_into_new_revision(self):
        previous_revision = get_epg_revision()
        key = self.prefix + ":" + previous_revision
        response = self.response(key=key)
        stream = iter(response.streaming_content)
        first = next(stream)
        with patch.object(cache, "_get_redis", return_value=self.redis):
            cache.invalidate_epg_chunk_cache()
        revision = get_epg_revision()
        self.assertNotEqual(revision, previous_revision)
        replacement = b"<tv><programme><title>New</title></programme></tv>"
        new_key = self.prefix + ":" + revision
        self.assertEqual(consume(self.response(lambda: iter([replacement]), key=new_key)), replacement)
        self.assertEqual(first + b"".join(stream), "".join(self.chunks).encode())
        response.close()
        self.assertEqual(consume(self.response(key=new_key)), replacement)

    def test_ready_response_has_exact_byte_length(self):
        expected = consume(self.response())
        response = self.response()
        self.assertEqual(int(response["Content-Length"]), len(expected))
        self.assertEqual(consume(response), expected)

    def test_redis_unavailable_before_headers_uses_original_source(self):
        with patch.object(self.redis, "get", side_effect=redis_library.ConnectionError("offline")):
            self.assertEqual(consume(self.response()), "".join(self.chunks).encode())

    def test_redis_append_failure_does_not_interrupt_original_producer(self):
        response = self.response()
        stream = iter(response.streaming_content)
        first = next(stream)
        with patch.object(self.redis, "eval", side_effect=redis_library.ConnectionError("offline")), \
                patch.object(self.redis, "rpush", side_effect=redis_library.ConnectionError("offline")):
            self.assertEqual(first + b"".join(stream), "".join(self.chunks).encode())
        response.close()
        self.assertFalse(self.redis.exists(cache._ready_key(self.prefix)))

    def test_expired_lease_does_not_allow_old_owner_to_release_replacement(self):
        original = self.response()
        stream = iter(original.streaming_content)
        first = next(stream)
        self.redis.delete(cache._lock_key(self.prefix))
        replacement = self.response(lambda: iter(["<tv>", "new", "</tv>"]))
        replacement_owner = self.redis.get(cache._lock_key(self.prefix))
        self.assertEqual(first + b"".join(stream), "".join(self.chunks).encode())
        original.close()
        self.assertEqual(self.redis.get(cache._lock_key(self.prefix)), replacement_owner)
        self.assertEqual(consume(replacement), b"<tv>new</tv>")

    def test_close_before_first_iteration_releases_build(self):
        response = self.response()
        self.assertTrue(self.redis.exists(cache._lock_key(self.prefix)))
        response.close()
        self.assertFalse(self.redis.exists(cache._lock_key(self.prefix)))

    def test_source_factory_exception_releases_claim_immediately(self):
        def broken_source():
            raise ValueError("source failed before yielding")
        response = self.response(broken_source)
        with self.assertRaises(ValueError):
            next(iter(response.streaming_content))
        self.assertFalse(self.redis.exists(cache._lock_key(self.prefix)))
        response.close()

    def test_ready_selection_expiry_does_not_expire_active_reader_data(self):
        expected = consume(self.response(cache_ttl=1))
        response = self.response(cache_ttl=1)
        stream = iter(response.streaming_content)
        first = next(stream)
        deadline = time.monotonic() + 3
        while self.redis.exists(cache._ready_key(self.prefix)) and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertFalse(self.redis.exists(cache._ready_key(self.prefix)))
        self.assertEqual(first + b"".join(stream), expected)
        response.close()

    def test_expired_build_cannot_recreate_a_suffix_cache(self):
        response = self.response(lock_ttl=1)
        stream = iter(response.streaming_content)
        first = next(stream)
        deadline = time.monotonic() + 3
        while self.redis.exists(cache._lock_key(self.prefix)) and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertFalse(self.redis.exists(cache._lock_key(self.prefix)))
        self.assertEqual(first + b"".join(stream), "".join(self.chunks).encode())
        self.assertFalse(self.redis.exists(cache._ready_key(self.prefix)))
        response.close()

    def test_publication_error_does_not_interrupt_source(self):
        response = self.response()
        with patch.object(cache._Build, "_publish", side_effect=redis_library.ConnectionError("offline")):
            self.assertEqual(consume(response), "".join(self.chunks).encode())
        self.assertFalse(self.redis.exists(cache._ready_key(self.prefix)))

    def test_follower_timeout_uses_an_independent_source_before_headers(self):
        leader = self.response()
        fallback = self.response(lambda: iter(["<tv>fallback</tv>"]), max_follower_wait=0.01, poll_interval=0.005)
        self.assertEqual(consume(fallback), b"<tv>fallback</tv>")
        self.assertNotIn("Content-Length", fallback)
        leader.close()

    def test_deleted_chunk_data_never_means_successful_eof(self):
        consume(self.response())
        response = self.response()
        self.assertIn("Content-Length", response)
        stream = iter(response.streaming_content)
        next(stream)
        manifest = json.loads(self.redis.get(cache._ready_key(self.prefix)))
        self.redis.delete(cache._chunks_key(self.prefix + ":build:" + manifest["id"]))
        with self.assertRaises(RuntimeError):
            b"".join(stream)
        response.close()

    def test_follower_waits_for_complete_build_before_getting_length(self):
        started, release = threading.Event(), threading.Event()
        errors, responses = [], []
        def source():
            yield "<tv>"
            started.set()
            if not release.wait(3):
                raise RuntimeError("test barrier expired")
            yield "</tv>"
        def producer():
            try:
                responses.append(consume(self.response(source)))
            except Exception as exc:
                errors.append(exc)
        thread = threading.Thread(target=producer)
        thread.start()
        self.assertTrue(started.wait(3))
        release.set()
        follower = self.response(lambda: self.fail("follower unexpectedly rebuilt"))
        self.assertIn("Content-Length", follower)
        self.assertEqual(consume(follower), b"<tv></tv>")
        thread.join(3)
        self.assertEqual(errors, [])
        self.assertEqual(responses, [b"<tv></tv>"])
