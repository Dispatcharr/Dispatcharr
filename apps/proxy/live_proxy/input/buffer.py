"""Buffer management for TS streams"""

import threading
import time
import random
from ..redis_keys import RedisKeys
from ..config_helper import ConfigHelper
from ..constants import TS_PACKET_SIZE
from .ts_discontinuity import stamp_first_packet_per_pid
from ..utils import get_logger
import gevent.event
import gevent

logger = get_logger()


class StreamBuffer:
    """Manages stream data buffering with optimized chunk storage"""

    def __init__(self, channel_id=None, redis_client=None,
                 buffer_index_key=None, buffer_chunk_prefix=None, chunk_timestamps_key=None,
                 discontinuities_key=None):
        self.channel_id = channel_id
        self.redis_client = redis_client
        self.lock = threading.Lock()
        self.index = 0
        self.TS_PACKET_SIZE = TS_PACKET_SIZE

        self.buffer_index_key = buffer_index_key or (RedisKeys.buffer_index(channel_id) if channel_id else "")
        self.buffer_prefix = buffer_chunk_prefix or (RedisKeys.buffer_chunk_prefix(channel_id) if channel_id else "")

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
        self.chunk_timestamps_key = chunk_timestamps_key or (RedisKeys.chunk_timestamps(channel_id) if channel_id else "")
        # Sidecar: chunk indices where a source discontinuity begins. Optional for
        # profile output buffers that do not participate in failover marking.
        if discontinuities_key is not None:
            self.discontinuities_key = discontinuities_key
        elif channel_id and buffer_index_key is None:
            # Default input buffer only; custom-keyed buffers opt in explicitly.
            self.discontinuities_key = RedisKeys.buffer_discontinuities(channel_id)
        else:
            self.discontinuities_key = ""

        # After mark_discontinuity(): stamp discontinuity_indicator on the first
        # packet of each PID until the first post-mark Redis chunk is written.
        self._disc_stamp_active = False
        self._disc_stamped_pids = set()
        self._disc_mark_index = 0

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
        if not chunk or self.stopping:
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
                complete_packets = bytes(combined_data[:complete_packets_size])
                self._partial_packet = bytearray(combined_data[complete_packets_size:])

                if self._disc_stamp_active:
                    complete_packets, _ = stamp_first_packet_per_pid(
                        complete_packets, self._disc_stamped_pids
                    )

                # Add completed packets to write buffer
                self._write_buffer.extend(complete_packets)

                # Only write to Redis when we have enough data for an optimized chunk
                while len(self._write_buffer) >= self.target_chunk_size:
                    chunk_data = bytes(self._write_buffer[:self.target_chunk_size])
                    del self._write_buffer[:self.target_chunk_size]
                    if self._write_chunk_unlocked(chunk_data):
                        writes_done += 1

            if writes_done > 0:
                logger.debug(f"Added {writes_done} chunks ({self.target_chunk_size} bytes each) to Redis for channel {self.channel_id} at index {self.index}")

            self.chunk_available.set()  # Signal that new data is available
            self.chunk_available.clear()  # Reset for next notification

            return True

        except Exception as e:
            logger.error(f"Error adding chunk to buffer: {e}")
            return False

    def _write_chunk_unlocked(self, chunk_data):
        """Write one packet-aligned chunk to Redis. Caller must hold self.lock.

        Index is chosen locally and published only after the chunk write
        succeeds. A prior INCR-first approach could burn an index when the
        subsequent pipeline failed, leaving a permanent hole that every
        positional reader (TS / fMP4 / HLS / profile) treats as contiguous.
        Single-writer under self.lock, so local self.index + 1 is safe.
        """
        if not chunk_data or not self.redis_client:
            return False
        chunk_index = self.index + 1
        chunk_key = f"{self.buffer_prefix}{chunk_index}"

        pipe = self.redis_client.pipeline(transaction=False)
        pipe.setex(chunk_key, self.chunk_ttl, bytes(chunk_data))
        pipe.set(self.buffer_index_key, chunk_index)

        if self.chunk_timestamps_key:
            now = time.time()
            pipe.zadd(self.chunk_timestamps_key, {str(chunk_index): now})
            pipe.zremrangebyscore(self.chunk_timestamps_key, '-inf', now - self.chunk_ttl)
            pipe.expire(self.chunk_timestamps_key, self.chunk_ttl)

        try:
            pipe.execute()
        except Exception as e:
            logger.error(
                f"Failed to write buffer chunk {chunk_index} for channel "
                f"{self.channel_id}: {e}"
            )
            return False

        self.index = chunk_index

        # First Redis chunk after a discontinuity mark finishes the in-band
        # stamping pass (PAT/PMT/A/V first packets are already in this chunk).
        if self._disc_stamp_active and chunk_index > self._disc_mark_index:
            self._disc_stamp_active = False

        return True

    def mark_discontinuity(self):
        """
        Close out the old source in Redis and arm discontinuity handling for
        the next source.

        1. Flush any complete packets still in the write buffer so the last
           old-source Redis chunk ends cleanly.
        2. Drop a trailing partial packet (cannot form a valid TS packet).
        3. Record the next chunk index in the discontinuities sidecar so
           consumers (HLS) can cut before reading it.
        4. Arm in-band stamping: the first packet of each PID in the new
           source gets discontinuity_indicator=1 (ISO 13818-1 / FFmpeg
           initial_discontinuity).

        Must be called after the old input is closed and before new bytes
        are written.
        """
        try:
            with self.lock:
                flushed = self._flush_write_buffer_unlocked()
                # Incomplete trailing bytes belong to the old source and must
                # not be prepended to the new source's first packet.
                if hasattr(self, '_partial_packet'):
                    self._partial_packet = bytearray()

                self._disc_mark_index = self.index
                next_index = self.index + 1
                self._disc_stamp_active = True
                self._disc_stamped_pids = set()
                self._record_discontinuity_unlocked(next_index)

            if flushed:
                self.chunk_available.set()
                self.chunk_available.clear()
            logger.debug(
                f"Marked stream discontinuity for channel {self.channel_id} "
                f"at buffer index {next_index} (flushed={flushed})"
            )
            return next_index
        except Exception as e:
            logger.error(
                f"Error marking discontinuity for channel {self.channel_id}: {e}",
                exc_info=True,
            )
            return None

    def _flush_write_buffer_unlocked(self):
        """Write any pending complete packets even if under target_chunk_size."""
        if not self._write_buffer:
            return False
        # Write buffer is always packet-aligned by construction.
        aligned = len(self._write_buffer) - (len(self._write_buffer) % self.TS_PACKET_SIZE)
        if aligned <= 0:
            self._write_buffer = bytearray()
            return False
        chunk_data = bytes(self._write_buffer[:aligned])
        self._write_buffer = bytearray(self._write_buffer[aligned:])
        return self._write_chunk_unlocked(chunk_data)

    def _record_discontinuity_unlocked(self, chunk_index):
        """Publish chunk_index as a discontinuity start into the sidecar set."""
        if not self.redis_client or not self.discontinuities_key:
            return
        try:
            pipe = self.redis_client.pipeline(transaction=False)
            pipe.zadd(self.discontinuities_key, {str(chunk_index): float(chunk_index)})
            # Keep the sidecar no larger than the chunk retention window.
            pipe.zremrangebyscore(
                self.discontinuities_key, '-inf', float(chunk_index) - 10000
            )
            pipe.expire(self.discontinuities_key, self.chunk_ttl)
            pipe.execute()
        except Exception as e:
            logger.error(
                f"Error recording discontinuity index {chunk_index} for "
                f"channel {self.channel_id}: {e}"
            )

    def discontinuities_in_range(self, start_index_exclusive, end_index_inclusive):
        """
        Return sorted chunk indices D where start_index_exclusive < D <= end_index_inclusive.

        These are the first Redis chunks of a new source era; consumers should
        treat the boundary before D as a discontinuity.
        """
        if (
            not self.redis_client
            or not self.discontinuities_key
            or end_index_inclusive <= start_index_exclusive
        ):
            return []
        try:
            members = self.redis_client.zrangebyscore(
                self.discontinuities_key,
                float(start_index_exclusive) + 1e-9,
                float(end_index_inclusive),
            )
            out = []
            for m in members or []:
                try:
                    out.append(int(m))
                except (TypeError, ValueError):
                    continue
            return out
        except Exception as e:
            logger.debug(
                f"Error reading discontinuities for channel {self.channel_id}: {e}"
            )
            return []

    def reset_buffer_position(self):
        """
        Reset internal buffers for a clean stream transition (failover).

        Prefer mark_discontinuity() on URL switches: it flushes complete
        packets to Redis before clearing. This method remains for callers that
        only need to drop local leftovers (e.g. after mark_discontinuity already
        flushed). Without clearing _partial_packet, bytes from the old FFmpeg
        get concatenated with the first bytes from the new FFmpeg, creating
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
                chunk_key = f"{self.buffer_prefix}{idx}"
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
                chunk_key = f"{self.buffer_prefix}{idx}"
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
            with self.lock:
                if hasattr(self, '_write_buffer') and len(self._write_buffer) > 0:
                    discarded = len(self._write_buffer)
                    self._write_buffer = bytearray()
                    if hasattr(self, '_partial_packet'):
                        self._partial_packet = bytearray()
                    logger.debug(
                        f"Discarded {discarded} bytes from local write buffer "
                        f"for channel {self.channel_id}"
                    )
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
                chunk_count += len(more_chunks)

        return chunks, client_index + chunk_count

    # Lua script that runs an atomic binary search on the Redis server.
    # Chunks expire in FIFO order (same TTL, sequential writes), so the
    # alive range is contiguous: [oldest_surviving .. buffer_head].
    # Binary search finds the boundary in O(log N) EXISTS calls with zero
    # round-trips between steps and no TOCTOU races (Lua scripts are atomic).
    #
    # ARGV[1] = key prefix  (e.g. "live:channel:<id>:input:buffer:chunk:")
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
                    self.buffer_prefix,
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

    def schedule_timer(self, delay, callback, *args, **kwargs):
        """Schedule a timer and track it for proper cleanup"""
        if self.stopping:
            return None

        timer = gevent.spawn_later(delay, callback, *args, **kwargs)
        self.fill_timers.append(timer)
        return timer
