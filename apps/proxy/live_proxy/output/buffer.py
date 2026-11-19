"""
Redis-backed output buffer for remux/segment managers.

Mirrors the input StreamBuffer's chunk/index/timestamp model, but stores
opaque byte blobs (no 188-byte TS alignment). Used by fMP4 (one fragment
per chunk) and HLS (one media segment per chunk) via the shared
output:{fmt}:buffer:* keyspace.

When a remux/transcode process is replaced mid-session, ``mark_discontinuity``
records the next chunk index so clients can cut before reading the new era.
An open fMP4 response is given the new init there and stays connected.
"""

import threading
import time

import gevent.event

from ..chunk_time_lookup import (
    FIND_CHUNK_BEHIND_HEAD_LUA,
    HEAD_SCORE_LOOKBACK,
    last_consumed_from_lua_result,
    media_score_min_index,
)
from ..discontinuity_sidecar import DiscontinuitySidecarMixin
from ..redis_keys import RedisKeys
from ..config_helper import ConfigHelper
from ..utils import get_logger

logger = get_logger()


class OutputStreamBuffer(DiscontinuitySidecarMixin):
    """Format-parameterized Redis chunk store for a channel's output."""

    def __init__(self, channel_id, redis_client=None, fmt='fmp4'):
        self.channel_id = channel_id
        self.redis_client = redis_client
        self.fmt = fmt
        self.lock = threading.Lock()
        self.index = 0

        self.buffer_index_key = RedisKeys.output_buffer_index(channel_id, fmt)
        self.buffer_prefix = RedisKeys.output_buffer_chunk_prefix(channel_id, fmt)
        self.chunk_timestamps_key = RedisKeys.output_chunk_timestamps(channel_id, fmt)
        self.discontinuities_key = RedisKeys.output_buffer_discontinuities(
            channel_id, fmt
        )
        self.chunk_ttl = ConfigHelper.redis_chunk_ttl()
        self.stopping = False

        if self.redis_client and channel_id:
            try:
                current_index = self.redis_client.get(self.buffer_index_key)
                if current_index:
                    self.index = int(current_index)
            except Exception as e:
                logger.error(
                    f"[OutputBuffer:{fmt}:{channel_id}] Error initialising from Redis: {e}"
                )

        self.chunk_available = gevent.event.Event()

        if self.redis_client:
            try:
                self._find_chunk_behind_sha = self.redis_client.register_script(
                    FIND_CHUNK_BEHIND_HEAD_LUA
                )
            except Exception:
                self._find_chunk_behind_sha = None
        else:
            self._find_chunk_behind_sha = None

    def put_chunk(self, data: bytes, score=None) -> bool:
        """Store one complete output unit (fragment, segment, ...) as its own Redis chunk.

        ``score`` defaults to wall ``time.time()`` (HLS playlist TTL prune).
        fMP4 remux passes ``PublishedClock.end`` so clients join by stream time
        behind the buffer head. An explicit score is media time and is pruned
        by chunk index, not by treating it as a unix timestamp.
        """
        if not data or not self.redis_client:
            return False
        try:
            media_score = score is not None
            if score is None:
                score = time.time()
            else:
                score = float(score)
            with self.lock:
                # Local index + publish-after-write: avoids permanent holes when
                # an INCR succeeds but the chunk pipeline fails (same contract
                # as StreamBuffer; single writer under self.lock).
                chunk_index = self.index + 1
                chunk_key = RedisKeys.output_buffer_chunk(self.channel_id, self.fmt, chunk_index)
                pipe = self.redis_client.pipeline(transaction=False)
                pipe.setex(chunk_key, self.chunk_ttl, data)
                pipe.set(self.buffer_index_key, chunk_index)
                pipe.zadd(self.chunk_timestamps_key, {str(chunk_index): score})
                if media_score:
                    # Media time cannot expire by score. One member ages out of
                    # the retention window per chunk; drop it directly (no scan).
                    min_keep = media_score_min_index(chunk_index, self.chunk_ttl)
                    if min_keep > 0:
                        pipe.zrem(self.chunk_timestamps_key, str(min_keep - 1))
                else:
                    pipe.zremrangebyscore(
                        self.chunk_timestamps_key, '-inf', score - self.chunk_ttl
                    )
                pipe.expire(self.chunk_timestamps_key, self.chunk_ttl)
                try:
                    pipe.execute()
                except Exception as e:
                    logger.error(
                        f"[OutputBuffer:{self.fmt}:{self.channel_id}] "
                        f"Failed to write chunk {chunk_index}: {e}"
                    )
                    return False
                self.index = chunk_index
            self.chunk_available.set()
            self.chunk_available.clear()
            return True
        except Exception as e:
            logger.error(f"[OutputBuffer:{self.fmt}:{self.channel_id}] Error putting chunk: {e}")
            return False

    def _discontinuity_label(self) -> str:
        return f"channel {self.channel_id} ({self.fmt} output)"

    def mark_discontinuity(self):
        """Record that the next chunk starts a new output era.

        Must be called after the old process has stopped writing and before the
        replacement writes its first chunk. Returns the discontinuity chunk
        index, or None on failure.
        """
        try:
            with self.lock:
                next_index = self.index + 1
                self._record_discontinuity_unlocked(next_index)
            logger.debug(
                f"[OutputBuffer:{self.fmt}:{self.channel_id}] "
                f"Marked discontinuity at index {next_index}"
            )
            return next_index
        except Exception as e:
            logger.error(
                f"[OutputBuffer:{self.fmt}:{self.channel_id}] "
                f"Error marking discontinuity: {e}",
                exc_info=True,
            )
            return None

    def get_chunks_indexed(self, start_index=None):
        """Retrieve ``(chunk_index, data)`` pairs from start_index to head."""
        try:
            if not self.redis_client:
                return [], self.index

            current_index = self.redis_client.get(self.buffer_index_key)
            if not current_index:
                return [], self.index

            current_index = int(current_index)

            if start_index is None:
                start_index = max(0, current_index - 5)

            if start_index >= current_index:
                return [], current_index

            indices = list(range(start_index + 1, current_index + 1))
            pipe = self.redis_client.pipeline(transaction=False)
            for i in indices:
                pipe.get(RedisKeys.output_buffer_chunk(self.channel_id, self.fmt, i))
            results = pipe.execute()

            indexed = []
            for i, data in zip(indices, results):
                if data:
                    indexed.append((i, data))

            return indexed, current_index

        except Exception as e:
            logger.error(f"[OutputBuffer:{self.fmt}:{self.channel_id}] Error getting chunks: {e}")
            return [], self.index

    def find_chunk_index_behind(self, seconds_behind):
        """Return the chunk index approximately *seconds_behind* the buffer head.

        Uses the zset score of the head chunk (wall time or PublishedClock end)
        minus ``seconds_behind``. Last-consumed convention: next read starts
        at index+1. None if no suitable chunk exists.
        """
        if not self.redis_client or not self._find_chunk_behind_sha:
            return None
        disc_key = self.discontinuities_key or self.buffer_index_key
        use_disc = 1 if self.discontinuities_key else 0
        try:
            result = self._find_chunk_behind_sha(
                keys=[
                    self.chunk_timestamps_key,
                    self.buffer_index_key,
                    disc_key,
                ],
                args=[seconds_behind, HEAD_SCORE_LOOKBACK, use_disc],
            )
            return last_consumed_from_lua_result(result)
        except Exception as e:
            logger.error(
                f"[OutputBuffer:{self.fmt}:{self.channel_id}] "
                f"Error in find_chunk_index_behind: {e}"
            )
            return None

    def surviving_chunk_scores(self):
        """Map chunk index -> write timestamp for chunks still tracked in Redis.

        The zset is pruned to chunk_ttl on write for wall scores; members here
        are the segments that should still be fetchable (subject to key TTL
        race on the oldest).
        """
        if not self.redis_client or not self.chunk_timestamps_key:
            return {}
        try:
            members = self.redis_client.zrange(
                self.chunk_timestamps_key, 0, -1, withscores=True
            )
            out = {}
            for member, score in members or []:
                try:
                    idx = int(member)
                except (TypeError, ValueError):
                    continue
                out[idx] = float(score)
            return out
        except Exception as e:
            logger.debug(
                f"[OutputBuffer:{self.fmt}:{self.channel_id}] "
                f"Error listing surviving chunks: {e}"
            )
            return {}

    def stop(self):
        self.stopping = True

    def cleanup_redis(self):
        """Delete all output buffer keys for this channel/format from Redis."""
        if not self.redis_client:
            return
        try:
            prefix = self.buffer_prefix
            cursor = 0
            while True:
                cursor, keys = self.redis_client.scan(cursor, match=f"{prefix}*", count=200)
                if keys:
                    self.redis_client.delete(*keys)
                if cursor == 0:
                    break
            self.redis_client.delete(self.buffer_index_key)
            try:
                self.redis_client.delete(self.chunk_timestamps_key)
            except Exception:
                pass
            try:
                self.redis_client.delete(self.discontinuities_key)
            except Exception:
                pass
        except Exception as e:
            logger.error(
                f"[OutputBuffer:{self.fmt}:{self.channel_id}] Error during Redis cleanup: {e}"
            )
