"""fMP4 buffer management - mirrors StreamBuffer but without TS packet alignment."""

import threading
import time
import gevent.event
from ...redis_keys import RedisKeys
from ...config_helper import ConfigHelper
from ...utils import get_logger

logger = get_logger()


class FMP4StreamBuffer:
    """
    Redis-backed buffer for fMP4 remux output.

    Functionally identical to StreamBuffer except:
    - Uses the fmp4:buffer:* Redis keyspace
    - No 188-byte TS packet alignment (raw byte accumulation)
    """

    def __init__(self, channel_id, redis_client=None, fmt='fmp4'):
        self.channel_id = channel_id
        self.redis_client = redis_client
        self.fmt = fmt
        self.lock = threading.Lock()
        self.index = 0

        self.buffer_index_key = RedisKeys.output_buffer_index(channel_id, fmt)
        self.buffer_prefix = RedisKeys.output_buffer_chunk_prefix(channel_id, fmt)
        self.chunk_timestamps_key = RedisKeys.output_chunk_timestamps(channel_id, fmt)
        self.chunk_ttl = ConfigHelper.redis_chunk_ttl()
        self.stopping = False

        if self.redis_client and channel_id:
            try:
                current_index = self.redis_client.get(self.buffer_index_key)
                if current_index:
                    self.index = int(current_index)
            except Exception as e:
                logger.error(f"[fMP4Buffer:{channel_id}] Error initialising from Redis: {e}")

        self.chunk_available = gevent.event.Event()

        # Lua script for time-based start positioning (same as StreamBuffer)
        _LUA = """
        local ts_key = KEYS[1]
        local target = tonumber(ARGV[1])
        local result = redis.call('ZREVRANGEBYSCORE', ts_key, target, '-inf', 'LIMIT', 0, 1)
        if #result == 0 then return -1 end
        return tonumber(result[1])
        """
        if self.redis_client:
            try:
                self._find_chunk_by_time_sha = self.redis_client.register_script(_LUA)
            except Exception:
                self._find_chunk_by_time_sha = None
        else:
            self._find_chunk_by_time_sha = None

    def put_fragment(self, data: bytes) -> bool:
        """Store a single complete fMP4 fragment directly to Redis as its own chunk."""
        if not data or not self.redis_client:
            return False
        try:
            now = time.time()
            with self.lock:
                chunk_index = self.redis_client.incr(self.buffer_index_key)
                chunk_key = RedisKeys.output_buffer_chunk(self.channel_id, self.fmt, chunk_index)
                pipe = self.redis_client.pipeline(transaction=False)
                pipe.setex(chunk_key, self.chunk_ttl, data)
                pipe.zadd(self.chunk_timestamps_key, {str(chunk_index): now})
                pipe.zremrangebyscore(self.chunk_timestamps_key, '-inf', now - self.chunk_ttl)
                pipe.expire(self.chunk_timestamps_key, self.chunk_ttl)
                pipe.execute()
                self.index = chunk_index
            self.chunk_available.set()
            self.chunk_available.clear()
            return True
        except Exception as e:
            logger.error(f"[fMP4Buffer:{self.channel_id}] Error putting fragment: {e}")
            return False

    def get_chunks(self, start_index=None):
        """Retrieve chunks from start_index up to current head. Returns (chunks, new_index)."""
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

            chunks = []
            pipe = self.redis_client.pipeline(transaction=False)
            indices = range(start_index + 1, current_index + 1)
            for i in indices:
                pipe.get(RedisKeys.output_buffer_chunk(self.channel_id, self.fmt, i))
            results = pipe.execute()

            for data in results:
                if data:
                    chunks.append(data)

            return chunks, current_index

        except Exception as e:
            logger.error(f"[fMP4Buffer:{self.channel_id}] Error getting chunks: {e}")
            return [], self.index

    def find_chunk_index_by_time(self, seconds_behind):
        """Return the fragment index that was received ~seconds_behind seconds ago.

        Returns an int (last-consumed convention: next read starts at index+1)
        or None if no suitable fragment exists.
        """
        if not self.redis_client or not self._find_chunk_by_time_sha:
            return None
        target_time = time.time() - seconds_behind
        try:
            result = self._find_chunk_by_time_sha(
                keys=[self.chunk_timestamps_key],
                args=[target_time],
            )
            if result is None or int(result) == -1:
                oldest = self.redis_client.zrange(self.chunk_timestamps_key, 0, 0)
                if oldest:
                    return max(0, int(oldest[0]) - 1)
                return None
            return max(0, int(result) - 1)
        except Exception as e:
            logger.error(f"[fMP4Buffer:{self.channel_id}] Error in find_chunk_index_by_time: {e}")
            return None

    def stop(self):
        self.stopping = True

    def cleanup_redis(self):
        """Delete all fMP4 buffer keys for this channel from Redis."""
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
        except Exception as e:
            logger.error(f"[fMP4Buffer:{self.channel_id}] Error during Redis cleanup: {e}")
