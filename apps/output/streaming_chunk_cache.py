"""Single-flight Redis chunk cache for large streaming HTTP responses."""

import logging
import time

from django.http import StreamingHttpResponse

logger = logging.getLogger(__name__)

STATUS_BUILDING = "building"
STATUS_READY = "ready"
STATUS_ERROR = "error"

DEFAULT_CACHE_TTL = 300
DEFAULT_LOCK_TTL = 120
DEFAULT_POLL_INTERVAL = 0.05
DEFAULT_MAX_FOLLOWER_WAIT = 600


def _chunks_key(base_key):
    return f"{base_key}:chunks"


def _ready_key(base_key):
    return f"{base_key}:ready"


def _status_key(base_key):
    return f"{base_key}:status"


def _lock_key(base_key):
    return f"{base_key}:lock"


def _decode_chunk(chunk):
    if chunk is None:
        return None
    if isinstance(chunk, bytes):
        return chunk.decode("utf-8")
    return chunk


def _encode_chunk(chunk):
    if isinstance(chunk, bytes):
        return chunk
    return chunk.encode("utf-8")


def _poll_wait(interval):
    try:
        from core.utils import _is_gevent_monkey_patched

        if _is_gevent_monkey_patched():
            import gevent

            gevent.sleep(interval)
            return
    except ImportError:
        pass
    time.sleep(interval)


def _get_redis():
    from django_redis import get_redis_connection

    return get_redis_connection("default")


def _get_status(redis, base_key):
    raw = redis.get(_status_key(base_key))
    if raw is None:
        return None
    return _decode_chunk(raw)


def _clear_build_keys(redis, base_key):
    redis.delete(
        _chunks_key(base_key),
        _status_key(base_key),
        _ready_key(base_key),
        _lock_key(base_key),
    )


def _try_acquire_lock(redis, base_key, lock_ttl):
    return bool(redis.set(_lock_key(base_key), "1", nx=True, ex=lock_ttl))


def _refresh_build_ttl(redis, base_key, lock_ttl):
    redis.expire(_lock_key(base_key), lock_ttl)
    redis.expire(_status_key(base_key), lock_ttl)
    redis.expire(_chunks_key(base_key), lock_ttl)


def _stream_ready(redis, base_key):
    offset = 0
    chunks_key = _chunks_key(base_key)
    while True:
        chunk = redis.lindex(chunks_key, offset)
        if chunk is None:
            break
        yield _decode_chunk(chunk)
        offset += 1


def _stream_build(redis, base_key, source, cache_ttl, lock_ttl):
    """Leader: stream to client and append each chunk to Redis."""
    chunks_key = _chunks_key(base_key)
    status_key = _status_key(base_key)
    try:
        from django.core.cache import cache as django_cache

        django_cache.delete(base_key)  # clear any non-chunked entry under this key
        redis.delete(chunks_key, _ready_key(base_key))
        redis.set(status_key, STATUS_BUILDING, ex=lock_ttl)
        refresh_interval = max(1, lock_ttl // 4)
        last_refresh = 0.0
        for chunk in source():
            redis.rpush(chunks_key, _encode_chunk(chunk))
            now = time.monotonic()
            if now - last_refresh >= refresh_interval:
                _refresh_build_ttl(redis, base_key, lock_ttl)
                last_refresh = now
            yield chunk
        redis.set(status_key, STATUS_READY)
        redis.set(_ready_key(base_key), "1")
        redis.expire(chunks_key, cache_ttl)
        redis.expire(status_key, cache_ttl)
        redis.expire(_ready_key(base_key), cache_ttl)
        logger.debug("Cached response in %s chunks", redis.llen(chunks_key))
    except Exception:
        logger.exception("Chunk cache build failed for %s", base_key)
        redis.delete(chunks_key)
        redis.set(status_key, STATUS_ERROR, ex=60)
        raise
    finally:
        redis.delete(_lock_key(base_key))


def _stream_follow(redis, base_key, source, cache_ttl, lock_ttl, poll_interval, max_follower_wait):
    """Follower: read chunks as the leader writes them."""
    offset = 0
    deadline = time.monotonic() + max_follower_wait
    idle_polls = 0
    chunks_key = _chunks_key(base_key)
    lock_key = _lock_key(base_key)

    while True:
        chunk = redis.lindex(chunks_key, offset)
        if chunk is not None:
            idle_polls = 0
            yield _decode_chunk(chunk)
            offset += 1
            continue

        status = _get_status(redis, base_key)
        if status == STATUS_READY:
            break

        if status == STATUS_ERROR:
            _clear_build_keys(redis, base_key)
            if offset == 0 and _try_acquire_lock(redis, base_key, lock_ttl):
                yield from _stream_build(redis, base_key, source, cache_ttl, lock_ttl)
                return
            raise RuntimeError("Chunk cache build failed")

        if time.monotonic() >= deadline:
            if offset == 0 and _try_acquire_lock(redis, base_key, lock_ttl):
                logger.warning("Chunk cache follower timed out; rebuilding %s", base_key)
                yield from _stream_build(redis, base_key, source, cache_ttl, lock_ttl)
                return
            logger.warning("Chunk cache follower timed out after partial read for %s", base_key)
            break

        lock_active = bool(redis.exists(lock_key))
        if status != STATUS_BUILDING and not lock_active:
            idle_polls += 1
            if offset == 0 and idle_polls >= max(1, int(1.0 / poll_interval)):
                if _try_acquire_lock(redis, base_key, lock_ttl):
                    logger.warning("Chunk cache leader lost; rebuilding %s", base_key)
                    yield from _stream_build(redis, base_key, source, cache_ttl, lock_ttl)
                    return
        else:
            idle_polls = 0

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
    """
    Stream a large response with single-flight Redis chunk caching.

    ``source`` must be a callable returning a chunk iterator. Only the leader
    invokes it; concurrent followers replay chunks already written to Redis, so
    the expensive ``source`` runs at most once per ``cache_key``.
    """
    if redis is None:
        redis = _get_redis()

    if redis.get(_ready_key(cache_key)):
        logger.debug("Serving response from chunk cache")
        stream = _stream_ready(redis, cache_key)
    else:
        status = _get_status(redis, cache_key)
        if status == STATUS_ERROR:
            _clear_build_keys(redis, cache_key)

        if _try_acquire_lock(redis, cache_key, lock_ttl):
            logger.debug("Building response (cache leader)")
            stream = _stream_build(redis, cache_key, source, cache_ttl, lock_ttl)
        else:
            logger.debug("Following in-flight cache build")
            stream = _stream_follow(
                redis,
                cache_key,
                source,
                cache_ttl,
                lock_ttl,
                poll_interval,
                max_follower_wait,
            )

    response = StreamingHttpResponse(stream, content_type=content_type)
    if filename:
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response["Cache-Control"] = "no-cache"
    return response
