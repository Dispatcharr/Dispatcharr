"""Buffer management for TS streams"""

import threading
import logging
import time
from collections import deque
from typing import Optional, Deque
import random
from apps.proxy.config import TSConfig as Config
from .redis_keys import RedisKeys
from .config_helper import ConfigHelper
from .constants import TS_PACKET_SIZE
from .utils import get_logger
import gevent.event
import gevent  # Make sure this import is at the top

logger = get_logger()

class StreamBuffer:
    """Manages stream data buffering with optimized chunk storage"""

    def __init__(self, channel_id=None, redis_client=None):
        self.channel_id = channel_id
        self.redis_client = redis_client
        self.lock = threading.Lock()
        self.index = 0
        self.TS_PACKET_SIZE = TS_PACKET_SIZE

        # STANDARDIZED KEYS: Use RedisKeys class instead of hardcoded patterns
        self.buffer_index_key = RedisKeys.buffer_index(channel_id) if channel_id else ""
        self.buffer_prefix = RedisKeys.buffer_chunk_prefix(channel_id) if channel_id else ""

        self.chunk_ttl = ConfigHelper.redis_chunk_ttl()

        # Initialize from Redis if available
        if self.redis_client and channel_id:
            try:
                current_index = self.redis_client.get(self.buffer_index_key)
                if current_index:
                    self.index = int(current_index)
                    logger.info(f"Initialized buffer from Redis with index {self.index}")
            except Exception as e:
                logger.error(f"Error initializing buffer from Redis: {e}")

        self._write_buffer = bytearray()
        self.target_chunk_size = ConfigHelper.get('BUFFER_CHUNK_SIZE', TS_PACKET_SIZE * 5644)  # ~1MB default

        # Sorted-set key for chunk receive-timestamps (time-based positioning)
        self.chunk_timestamps_key = RedisKeys.chunk_timestamps(channel_id) if channel_id else ""

        # Register Lua scripts once — subsequent calls use EVALSHA (just the
        # SHA hash) instead of sending the full script text on every invocation.
        if self.redis_client:
            self._find_oldest_chunk_sha = self.redis_client.register_script(
                self._FIND_OLDEST_CHUNK_LUA
            )
            self._find_chunk_by_time_sha = self.redis_client.register_script(
                self._FIND_CHUNK_BY_TIME_LUA
            )
        else:
            self._find_oldest_chunk_sha = None
            self._find_chunk_by_time_sha = None

        # Track timers for proper cleanup
        self.stopping = False
        self.fill_timers = []
        self.chunk_available = gevent.event.Event()

    def add_chunk(self, chunk):
        """Add data with optimized Redis storage and TS packet alignment"""
        if not chunk:
            return False

        try:
            # Accumulate partial packets between chunks
            if not hasattr(self, '_partial_packet'):
                self._partial_packet = bytearray()

            # Lock the full operation to prevent race with reset_buffer_position
            writes_done = 0
            with self.lock:
                # Combine with any previous partial packet
                combined_data = bytearray(self._partial_packet) + bytearray(chunk)

                # Calculate complete packets
                complete_packets_size = (len(combined_data) // self.TS_PACKET_SIZE) * self.TS_PACKET_SIZE

                if complete_packets_size == 0:
                    # Not enough data for a complete packet
                    self._partial_packet = combined_data
                    return True

                # Split into complete packets and remainder
                complete_packets = combined_data[:complete_packets_size]
                self._partial_packet = combined_data[complete_packets_size:]

                # Add completed packets to write buffer
                self._write_buffer.extend(complete_packets)

                # Only write to Redis when we have enough data for an optimized chunk
                while len(self._write_buffer) >= self.target_chunk_size:
                    # Extract a full chunk
                    chunk_data = self._write_buffer[:self.target_chunk_size]
                    self._write_buffer = self._write_buffer[self.target_chunk_size:]

                    # Write optimized chunk to Redis. We need the new index from
                    # incr() to build the chunk key, so issue that first; the
                    # remaining writes are pipelined into one round trip.
                    if self.redis_client:
                        chunk_index = self.redis_client.incr(self.buffer_index_key)
                        chunk_key = RedisKeys.buffer_chunk(self.channel_id, chunk_index)

                        pipe = self.redis_client.pipeline(transaction=False)
                        pipe.setex(chunk_key, self.chunk_ttl, bytes(chunk_data))

                        if self.chunk_timestamps_key:
                            now = time.time()
                            pipe.zadd(self.chunk_timestamps_key, {str(chunk_index): now})
                            pipe.zremrangebyscore(self.chunk_timestamps_key, '-inf', now - self.chunk_ttl)
                            pipe.expire(self.chunk_timestamps_key, self.chunk_ttl)

                        pipe.execute()

                        # Update local tracking
                        self.index = chunk_index
                        writes_done += 1

            if writes_done > 0:
                logger.debug(f"Added {writes_done} chunks ({self.target_chunk_size} bytes each) to Redis for channel {self.channel_id} at index {self.index}")

            self.chunk_available.set()  # Signal that new data is available
            self.chunk_available.clear()  # Reset for next notification

            return True

        except Exception as e:
            logger.error(f"Error adding chunk to buffer: {e}")
            return False

    def reset_buffer_position(self):
        """
        Reset internal buffers for a clean stream transition (failover).

        Called by stream_manager.update_url() when switching between FFmpeg
        processes. Without this, _partial_packet from the old FFmpeg gets
        concatenated with the first bytes from the new FFmpeg, creating
        corrupted TS packets that break audio decoder sync in the client.
        """
        try:
            with self.lock:
                old_write_size = len(self._write_buffer)
                old_partial_size = len(getattr(self, '_partial_packet', b''))

                self._write_buffer = bytearray()
                if hasattr(self, '_partial_packet'):
                    self._partial_packet = bytearray()

                if old_write_size > 0 or old_partial_size > 0:
                    logger.info(
                        f"Reset buffer position for channel {self.channel_id}: "
                        f"cleared {old_write_size} bytes from write buffer, "
                        f"{old_partial_size} bytes from partial packet"
                    )
                else:
                    logger.debug(
                        f"Reset buffer position for channel {self.channel_id}: "
                        f"buffers were already clean"
                    )
        except Exception as e:
            logger.error(
                f"Error resetting buffer position for channel {self.channel_id}: {e}"
            )

    def get_chunks(self, start_index=None):
        """Get chunks from the buffer with detailed logging"""
        try:
            request_id = f"req_{random.randint(1000, 9999)}"
            logger.debug(f"[{request_id}] get_chunks called with start_index={start_index}")

            if not self.redis_client:
                logger.error("Redis not available, cannot retrieve chunks")
                return []

            # If no start_index provided, use most recent chunks
            if start_index is None:
                start_index = max(0, self.index - 10)  # Start closer to current position
                logger.debug(f"[{request_id}] No start_index provided, using {start_index}")

            # Get current index from Redis
            current_index = int(self.redis_client.get(self.buffer_index_key) or 0)

            # Calculate range of chunks to retrieve
            start_id = start_index + 1
            chunks_behind = current_index - start_id

            # Adaptive chunk retrieval based on how far behind
            if chunks_behind > 100:
                fetch_count = 15
                logger.debug(f"[{request_id}] Client very behind ({chunks_behind} chunks), fetching {fetch_count}")
            elif chunks_behind > 50:
                fetch_count = 10
                logger.debug(f"[{request_id}] Client moderately behind ({chunks_behind} chunks), fetching {fetch_count}")
            elif chunks_behind > 20:
                fetch_count = 5
                logger.debug(f"[{request_id}] Client slightly behind ({chunks_behind} chunks), fetching {fetch_count}")
            else:
                fetch_count = 3
                logger.debug(f"[{request_id}] Client up-to-date (only {chunks_behind} chunks behind), fetching {fetch_count}")

            end_id = min(current_index + 1, start_id + fetch_count)

            if start_id >= end_id:
                logger.debug(f"[{request_id}] No new chunks to fetch (start_id={start_id}, end_id={end_id})")
                return []

            # Log the range we're retrieving
            logger.debug(f"[{request_id}] Retrieving chunks {start_id} to {end_id-1} (total: {end_id-start_id})")

            # Directly fetch from Redis using pipeline for efficiency
            pipe = self.redis_client.pipeline()
            for idx in range(start_id, end_id):
                chunk_key = RedisKeys.buffer_chunk(self.channel_id, idx)
                pipe.get(chunk_key)

            results = pipe.execute()

            # Process results
            chunks = [result for result in results if result is not None]

            # Count non-None results
            found_chunks = len(chunks)
            missing_chunks = len(results) - found_chunks

            if missing_chunks > 0:
                logger.debug(f"[{request_id}] Missing {missing_chunks}/{len(results)} chunks in Redis")

            # Update local tracking
            if chunks:
                self.index = end_id - 1

            # Final log message
            chunk_sizes = [len(c) for c in chunks]
            total_bytes = sum(chunk_sizes) if chunks else 0
            logger.debug(f"[{request_id}] Returning {len(chunks)} chunks ({total_bytes} bytes)")

            return chunks

        except Exception as e:
            logger.error(f"Error getting chunks from buffer: {e}", exc_info=True)
            return []

    def get_chunks_exact(self, start_index, count):
        """Get exactly the requested number of chunks from given index"""
        try:
            if not self.redis_client:
                logger.error("Redis not available, cannot retrieve chunks")
                return []

            # Calculate range to retrieve
            start_id = start_index + 1
            end_id = start_id + count

            # Get current buffer position
            current_index = int(self.redis_client.get(self.buffer_index_key) or 0)

            # If requesting beyond current buffer, return what we have
            if start_id > current_index:
                return []

            # Cap end at current buffer position
            end_id = min(end_id, current_index + 1)

            # Directly fetch from Redis using pipeline
            pipe = self.redis_client.pipeline()
            for idx in range(start_id, end_id):
                chunk_key = RedisKeys.buffer_chunk(self.channel_id, idx)
                pipe.get(chunk_key)

            results = pipe.execute()

            # Filter out None results
            chunks = [result for result in results if result is not None]

            # Update local index if needed
            if chunks and start_id + len(chunks) - 1 > self.index:
                self.index = start_id + len(chunks) - 1

            return chunks

        except Exception as e:
            logger.error(f"Error getting exact chunks: {e}", exc_info=True)
            return []

    def stop(self):
        """Stop the buffer and cancel all timers"""
        # Set stopping flag first to prevent new timer creation
        self.stopping = True

        # Cancel all pending timers
        timers_cancelled = 0
        for timer in list(self.fill_timers):
            try:
                if timer and not timer.dead:  # Changed from timer.is_alive()
                    timer.kill()  # Changed from timer.cancel()
                    timers_cancelled += 1
            except Exception as e:
                logger.error(f"Error canceling timer: {e}")

        if timers_cancelled:
            logger.info(f"Cancelled {timers_cancelled} buffer timers for channel {self.channel_id}")

        # Clear timer list
        self.fill_timers.clear()

        try:
            # Flush any remaining data in the write buffer
            if hasattr(self, '_write_buffer') and len(self._write_buffer) > 0:
                # Ensure remaining data is aligned to TS packets
                complete_size = (len(self._write_buffer) // 188) * 188

                if complete_size > 0:
                    final_chunk = self._write_buffer[:complete_size]

                    # Write final chunk to Redis
                    with self.lock:
                        if self.redis_client:
                            try:
                                chunk_index = self.redis_client.incr(self.buffer_index_key)
                                chunk_key = f"{self.buffer_prefix}{chunk_index}"
                                self.redis_client.setex(chunk_key, self.chunk_ttl, bytes(final_chunk))
                                self.index = chunk_index
                                logger.info(f"Flushed final chunk of {len(final_chunk)} bytes to Redis")
                            except Exception as e:
                                logger.error(f"Error flushing final chunk: {e}")

                # Clear buffers
                self._write_buffer = bytearray()
                if hasattr(self, '_partial_packet'):
                    self._partial_packet = bytearray()

            # Clean up the chunk timestamps sorted set
            if self.redis_client and self.chunk_timestamps_key:
                try:
                    self.redis_client.delete(self.chunk_timestamps_key)
                except Exception as e:
                    logger.error(f"Error deleting chunk timestamps key: {e}")

        except Exception as e:
            logger.error(f"Error during buffer stop: {e}")

    def get_optimized_client_data(self, client_index):
        """Get optimal amount of data for client streaming based on position and target size"""
        # Define limits
        MIN_CHUNKS = 3                      # Minimum chunks to read for efficiency
        MAX_CHUNKS = 20                     # Safety limit to prevent memory spikes
        TARGET_SIZE = 1024 * 1024           # Target ~1MB per response (typical media buffer)
        MAX_SIZE = 2 * 1024 * 1024          # Hard cap at 2MB

        # Calculate how far behind we are
        chunks_behind = self.index - client_index

        # Determine optimal chunk count
        if chunks_behind <= MIN_CHUNKS:
            # Not much data, retrieve what's available
            chunk_count = max(1, chunks_behind)
        elif chunks_behind <= MAX_CHUNKS:
            # Reasonable amount behind, catch up completely
            chunk_count = chunks_behind
        else:
            # Way behind, retrieve MAX_CHUNKS to avoid memory pressure
            chunk_count = MAX_CHUNKS

        # Retrieve chunks
        chunks = self.get_chunks_exact(client_index, chunk_count)

        # Check if we got significantly fewer chunks than expected (likely due to expiration)
        # Only check if we expected multiple chunks and got none or very few
        if chunk_count > 3 and len(chunks) == 0 and chunks_behind > 10:
            # Chunks are missing - likely expired from Redis
            # Return empty list to signal client should skip forward
            logger.debug(f"Chunks missing for client at index {client_index}, buffer at {self.index} ({chunks_behind} behind)")
            return [], client_index

        # Check total size
        total_size = sum(len(c) for c in chunks)

        # If we're under target and have more chunks available, get more
        if total_size < TARGET_SIZE and chunks_behind > chunk_count:
            # Calculate how many more chunks we can get
            additional = min(MAX_CHUNKS - chunk_count, chunks_behind - chunk_count)
            more_chunks = self.get_chunks_exact(client_index + chunk_count, additional)

            # Check if adding more would exceed MAX_SIZE
            additional_size = sum(len(c) for c in more_chunks)
            if total_size + additional_size <= MAX_SIZE:
                chunks.extend(more_chunks)
                chunk_count += len(more_chunks)  # Fixed: count actual additional chunks retrieved

        return chunks, client_index + chunk_count

    # Lua script that runs an atomic binary search on the Redis server.
    # Chunks expire in FIFO order (same TTL, sequential writes), so the
    # alive range is contiguous: [oldest_surviving .. buffer_head].
    # Binary search finds the boundary in O(log N) EXISTS calls with zero
    # round-trips between steps and no TOCTOU races (Lua scripts are atomic).
    #
    # ARGV[1] = key prefix  (e.g. "ts_proxy:channel:<id>:buffer:chunk:")
    # ARGV[2] = low index   (client_index + 1, first chunk the client needs)
    # ARGV[3] = high index  (buffer head, most recent chunk)
    #
    # Returns: the index of the oldest existing chunk, or -1 if none exist.
    _FIND_OLDEST_CHUNK_LUA = """
    local prefix = ARGV[1]
    local low    = tonumber(ARGV[2])
    local high   = tonumber(ARGV[3])

    if redis.call('EXISTS', prefix .. high) == 0 then
        return -1
    end

    local result = high
    while low <= high do
        local mid = math.floor((low + high) / 2)
        if redis.call('EXISTS', prefix .. mid) == 1 then
            result = mid
            high = mid - 1
        else
            low = mid + 1
        end
    end
    return result
    """

    def find_oldest_available_chunk(self, client_index):
        """Find the oldest (lowest-index) chunk that still exists in Redis.

        Executes an atomic Lua binary search on the Redis server — one
        round-trip, ~log2(N) EXISTS calls, no TOCTOU between steps.

        The actual read attempt (get_optimized_client_data) is what
        authoritatively detects expiration; this method is best-effort
        positioning that self-corrects on the next iteration if the found
        chunk also expires before the client can read it.

        Args:
            client_index: The client's current local_index (last consumed chunk).

        Returns:
            int or None: The local_index value the client should jump to
                         (one before the first available chunk), or None if no
                         chunks are available at all.
        """
        if not self.redis_client:
            return None

        low = client_index + 1   # First chunk the client needs
        high = self.index        # Latest chunk written

        if low > high:
            return None

        try:
            # Uses EVALSHA under the hood — sends only the SHA hash,
            # not the full script text, on every call after the first.
            result = self._find_oldest_chunk_sha(
                args=[
                    RedisKeys.buffer_chunk_prefix(self.channel_id),
                    low,
                    high,
                ],
            )

            if result == -1:
                return None

            # Return result - 1 so local_index points to one before the
            # first available chunk (matching the "last consumed" convention).
            return int(result) - 1

        except Exception as e:
            logger.error(f"Error running find_oldest_chunk Lua script for channel {self.channel_id}: {e}")
            return None

    # ------------------------------------------------------------------
    # Lua script: atomic reverse-scan of the chunk_timestamps sorted set.
    # Finds the chunk whose receive-timestamp is closest to (but <=) a
    # target wall-clock time.  Returns the chunk index or -1.
    #
    # KEYS[1] = chunk_timestamps sorted-set key
    # ARGV[1] = target timestamp  (time.time() - desired_seconds_behind)
    # ------------------------------------------------------------------
    _FIND_CHUNK_BY_TIME_LUA = """
    local ts_key  = KEYS[1]
    local target  = tonumber(ARGV[1])

    -- ZREVRANGEBYSCORE returns members with score <= target, highest first.
    local result = redis.call('ZREVRANGEBYSCORE', ts_key, target, '-inf', 'LIMIT', 0, 1)
    if #result == 0 then
        return -1
    end
    return tonumber(result[1])
    """

    def find_chunk_index_by_time(self, seconds_behind):
        """Find the chunk index that was received approximately *seconds_behind*
        seconds ago.

        Uses an atomic Lua script against the chunk_timestamps sorted set so
        no data can expire between the lookup and the read.

        Returns:
            int or None: The chunk index to position the client at (this is
                         the *last consumed* convention, so the next read
                         starts at index+1).  None if no suitable chunk
                         exists.
        """
        if not self.redis_client or not self.chunk_timestamps_key:
            return None

        target_time = time.time() - seconds_behind

        try:
            result = self._find_chunk_by_time_sha(
                keys=[self.chunk_timestamps_key],
                args=[target_time],
            )
            if result is None or int(result) == -1:
                # No chunk old enough — fall back to the oldest available chunk
                oldest = self.redis_client.zrange(self.chunk_timestamps_key, 0, 0)
                if oldest:
                    return max(0, int(oldest[0]) - 1)  # "last consumed" convention
                return None

            # Return index - 1 so next read starts at that chunk
            return max(0, int(result) - 1)

        except Exception as e:
            logger.error(f"Error in find_chunk_index_by_time for channel {self.channel_id}: {e}")
            return None

    # Add a new method to safely create timers
    def schedule_timer(self, delay, callback, *args, **kwargs):
        """Schedule a timer and track it for proper cleanup"""
        if self.stopping:
            return None

        # Replace threading.Timer with gevent.spawn_later for better compatibility
        timer = gevent.spawn_later(delay, callback, *args, **kwargs)
        self.fill_timers.append(timer)
        return timer
