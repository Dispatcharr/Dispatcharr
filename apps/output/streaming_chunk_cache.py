"""Bounded streaming with immutable Redis builds and commit-linked EPG revisions."""

import json
import logging
import time
import uuid

from django.http import StreamingHttpResponse
from redis.exceptions import RedisError

logger = logging.getLogger(__name__)

STATUS_BUILDING = "building"
STATUS_READY = "ready"
DEFAULT_CACHE_TTL = 300
DEFAULT_LOCK_TTL = 120
DEFAULT_POLL_INTERVAL = 0.05
DEFAULT_MAX_FOLLOWER_WAIT = 5

# Build UUIDs are never reused. A lost producer can finish its own source but
# cannot append a suffix to expired data or publish/release a replacement build.
_CLAIM = """
if redis.call('exists', KEYS[1]) == 1 then return 0 end
if not redis.call('set', KEYS[2], ARGV[1], 'NX', 'EX', ARGV[2]) then return 0 end
redis.call('set', KEYS[3], 'building', 'EX', ARGV[2])
return 1
"""
_APPEND = """
if redis.call('get', KEYS[1]) ~= ARGV[1] or redis.call('get', KEYS[2]) ~= 'building' then return 0 end
if redis.call('llen', KEYS[3]) ~= tonumber(ARGV[2]) then return 0 end
redis.call('rpush', KEYS[3], ARGV[3])
redis.call('expire', KEYS[1], ARGV[4])
redis.call('expire', KEYS[2], ARGV[4])
redis.call('expire', KEYS[3], ARGV[4])
return 1
"""
_PUBLISH = """
if redis.call('get', KEYS[1]) ~= ARGV[1] or redis.call('get', KEYS[2]) ~= 'building' then return 0 end
if redis.call('llen', KEYS[3]) ~= tonumber(ARGV[2]) then return 0 end
redis.call('set', KEYS[2], 'ready', 'EX', ARGV[5])
redis.call('expire', KEYS[3], ARGV[5])
redis.call('set', KEYS[4], ARGV[3], 'EX', ARGV[4])
redis.call('del', KEYS[1])
return 1
"""
_RELEASE = """
if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) end
return 0
"""
_READ = """
if redis.call('get', KEYS[1]) ~= 'ready' then return {0} end
if redis.call('llen', KEYS[2]) ~= tonumber(ARGV[2]) then return {0} end
local chunk = redis.call('lindex', KEYS[2], ARGV[1])
if not chunk then return {0} end
redis.call('expire', KEYS[1], ARGV[3])
redis.call('expire', KEYS[2], ARGV[3])
return {1, chunk}
"""


def _chunks_key(base_key):
    return f"{base_key}:chunks"


def _ready_key(base_key):
    return f"{base_key}:ready"


def _status_key(base_key):
    return f"{base_key}:status"


def _lock_key(base_key):
    return f"{base_key}:lock"


def _encode_chunk(chunk):
    return chunk if isinstance(chunk, bytes) else chunk.encode("utf-8")


def _poll_wait(interval):
    from core.utils import _is_gevent_monkey_patched

    if _is_gevent_monkey_patched():
        import gevent

        gevent.sleep(interval)
    else:
        time.sleep(interval)


def _get_redis():
    from django_redis import get_redis_connection

    return get_redis_connection("default")


class _Build:
    """Owned iterator whose close releases its lease even before first iteration."""

    def __init__(self, redis, base_key, source, *, cache_ttl, lock_ttl):
        self.redis = redis
        self.base = base_key
        self.owner = uuid.uuid4().hex
        self.key = f"{base_key}:build:{self.owner}"
        self.cache_ttl = cache_ttl
        self.lock_ttl = lock_ttl
        self.source = source
        self.iterator = self._stream()

    def claim(self):
        return bool(self.redis.eval(_CLAIM, 3, _ready_key(self.base), _lock_key(self.base),
                                    _status_key(self.key), self.owner, self.lock_ttl))

    def __iter__(self):
        return self

    def __next__(self):
        return next(self.iterator)

    def close(self):
        try:
            self.iterator.close()
        finally:
            self._release()

    def _release(self):
        try:
            self.redis.eval(_RELEASE, 1, _lock_key(self.base), self.owner)
        except RedisError:
            logger.warning("Could not release XMLTV cache build lease", exc_info=True)

    def _append(self, offset, chunk):
        return self.redis.eval(_APPEND, 3, _lock_key(self.base), _status_key(self.key), _chunks_key(self.key),
                               self.owner, offset, chunk, self.lock_ttl)

    def _publish(self, count, byte_length):
        manifest = json.dumps({"id": self.owner, "count": count, "bytes": byte_length})
        return self.redis.eval(_PUBLISH, 4, _lock_key(self.base), _status_key(self.key), _chunks_key(self.key),
                               _ready_key(self.base), self.owner, count, manifest, self.cache_ttl,
                               max(self.cache_ttl, DEFAULT_LOCK_TTL))

    def _stream(self):
        iterator = None
        count, byte_length, caching = 0, 0, True
        try:
            iterator = iter(self.source())
            for chunk in iterator:
                chunk = _encode_chunk(chunk)
                if caching:
                    caching = self._cache_chunk(count, chunk)
                count += 1
                byte_length += len(chunk)
                yield chunk
            if caching:
                self._finish(count, byte_length)
        finally:
            try:
                close = getattr(iterator, "close", None)
                if close:
                    close()
            finally:
                self._release()

    def _cache_chunk(self, offset, chunk):
        try:
            if self._append(offset, chunk):
                return True
            logger.warning("XMLTV cache build lost ownership or chunks; continuing source uncached")
        except RedisError:
            logger.warning("XMLTV cache write failed; continuing source uncached", exc_info=True)
        self._release()
        return False

    def _finish(self, count, byte_length):
        try:
            if not self._publish(count, byte_length):
                logger.warning("XMLTV cache build no longer eligible for publication")
        except RedisError:
            logger.warning("XMLTV cache publication failed", exc_info=True)


def _read_chunk(redis, build_key, manifest, offset, retention):
    result = redis.eval(_READ, 2, _status_key(build_key), _chunks_key(build_key), offset, manifest["count"], retention)
    if not result[0]:
        raise RuntimeError("XMLTV cache snapshot expired or lost chunks during transfer")
    return _encode_chunk(result[1])


def _stream_ready(redis, build_key, manifest, first, retention):
    # The exact byte count is sent in Content-Length. Backend loss after headers
    # must abort an incomplete transfer, never masquerade as normal end-of-file.
    if first is not None:
        yield first
    for offset in range(1, manifest["count"]):
        yield _read_chunk(redis, build_key, manifest, offset, retention)


def _manifest(raw):
    value = json.loads(raw)
    valid = (isinstance(value, dict) and isinstance(value.get("id"), str)
             and len(value["id"]) == 32 and all(c in "0123456789abcdef" for c in value["id"])
             and type(value.get("count")) is int and value["count"] >= 0
             and type(value.get("bytes")) is int and value["bytes"] >= 0)
    if not valid:
        raise ValueError("Invalid XMLTV cache manifest")
    return value


def _select_ready(redis, base_key, retention):
    raw = redis.get(_ready_key(base_key))
    if raw is None:
        return None
    try:
        manifest = _manifest(raw)
        build_key = f"{base_key}:build:{manifest['id']}"
        first = _read_chunk(redis, build_key, manifest, 0, retention) if manifest["count"] else None
    except (ValueError, TypeError, RuntimeError):
        redis.eval(_RELEASE, 1, _ready_key(base_key), raw)
        return None
    return _stream_ready(redis, build_key, manifest, first, retention), manifest["bytes"]


def _select_stream(redis, base_key, source, *, cache_ttl, lock_ttl, poll_interval, max_follower_wait):
    deadline = time.monotonic() + max_follower_wait
    build = _Build(redis, base_key, source, cache_ttl=cache_ttl, lock_ttl=lock_ttl)
    while True:
        ready = _select_ready(redis, base_key, max(cache_ttl, DEFAULT_LOCK_TTL))
        if ready is not None:
            return ready
        if build.claim():
            return build, None
        if time.monotonic() >= deadline:
            logger.debug("XMLTV cache producer still busy; streaming independent source")
            return source(), None
        _poll_wait(poll_interval)


def stream_cached_response(
    cache_key,
    source,
    *,
    content_type="application/xml",
    filename=None,
    cache_ttl=DEFAULT_CACHE_TTL,
    lock_ttl=DEFAULT_LOCK_TTL,
    poll_interval=DEFAULT_POLL_INTERVAL,
    max_follower_wait=DEFAULT_MAX_FOLLOWER_WAIT,
    redis=None,
):
    """Stream a source or replay one complete, immutable cache build.

    The leader streams immediately. Followers wait before headers for a ready
    build (up to max_follower_wait), then use an independent source if needed.
    Ready readers retain data per chunk and send an exact Content-Length, so
    even a reader stalled beyond retention fails detectably instead of ending
    with a successful truncated body. Memory remains bounded to one chunk.
    """
    try:
        redis = redis if redis is not None else _get_redis()
        stream, length = _select_stream(redis, cache_key, source, cache_ttl=cache_ttl, lock_ttl=lock_ttl,
                                        poll_interval=poll_interval, max_follower_wait=max_follower_wait)
    except RedisError:
        logger.warning("XMLTV cache unavailable; streaming source uncached", exc_info=True)
        stream, length = source(), None
    response = StreamingHttpResponse(stream, content_type=content_type)
    if length is not None:
        response["Content-Length"] = str(length)
    if filename:
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response["Cache-Control"] = "no-cache"
    return response


def invalidate_epg_chunk_cache():
    """Retire EPG selections without deleting data used by active exports.

    The database revision follows the caller's transaction and does not depend
    on Redis. New requests use the new namespace; old builds expire naturally.
    Return False and log if the revision could not be advanced.
    """
    from apps.epg.services import advance_epg_revision

    try:
        advance_epg_revision()
        return True
    except Exception:
        logger.warning("Failed to advance EPG export revision", exc_info=True)
        return False


def invalidate_m3u_content_cache():
    """
    Drop Django-cache M3U playlist entries (`m3u_content:*`).

    Channel list, names, numbers, logos, and stream URLs can change when an
    M3U account finishes refreshing (including auto channel sync). The playlist
    cache key does not include those inputs, so clear it on refresh completion.
    """
    try:
        from django.core.cache import cache

        delete_pattern = getattr(cache, "delete_pattern", None)
        if not callable(delete_pattern):
            logger.warning(
                "Cache backend has no delete_pattern; skipping M3U content cache invalidate"
            )
            return
        deleted = delete_pattern("m3u_content:*")
        if deleted:
            logger.debug("Invalidated %s m3u_content cache key(s)", deleted)
    except Exception:
        logger.warning("Failed to invalidate M3U content cache", exc_info=True)


def invalidate_output_caches_after_m3u_refresh():
    """Clear M3U playlist and XMLTV caches after a successful M3U refresh."""
    invalidate_m3u_content_cache()
    invalidate_epg_chunk_cache()
