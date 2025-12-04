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
            writes_done = 0
            with self.lock:
                while len(self._write_buffer) >= self.target_chunk_size:
                    # Extract a full chunk
                    chunk_data = self._write_buffer[:self.target_chunk_size]
                    self._write_buffer = self._write_buffer[self.target_chunk_size:]

                    # Write optimized chunk to Redis
                    if self.redis_client:
                        chunk_index = self.redis_client.incr(self.buffer_index_key)
                        chunk_key = RedisKeys.buffer_chunk(self.channel_id, chunk_index)
                        self.redis_client.setex(chunk_key, self.chunk_ttl, bytes(chunk_data))

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

    # Add a new method to safely create timers
    def schedule_timer(self, delay, callback, *args, **kwargs):
        """Schedule a timer and track it for proper cleanup"""
        if self.stopping:
            return None

        # Replace threading.Timer with gevent.spawn_later for better compatibility
        timer = gevent.spawn_later(delay, callback, *args, **kwargs)
        self.fill_timers.append(timer)
        return timer
