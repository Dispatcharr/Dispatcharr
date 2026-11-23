"""Buffer management for TS streams"""

import threading
import time
from ..chunk_time_lookup import (
    FIND_CHUNK_BEHIND_HEAD_LUA,
    eval_behind_head_join,
    media_score_min_index,
)
from ..discontinuity_sidecar import DiscontinuitySidecarMixin
from ..join_trim import (
    KEYFRAME_LOOKBACK_MAX_CHUNKS,
    KEYFRAME_LOOKBACK_SECONDS,
    discover_layout_in_chunks,
    discover_video_layout,
    merge_parameter_sets_from_chunks,
    prepare_join_chunk,
    resolve_join_cut,
)
from ..psi_scan import PsiScanCache
from ..redis_keys import RedisKeys
from ..config_helper import ConfigHelper
from ..constants import TS_PACKET_SIZE
from ..ts_clock import (
    advance_unwrapped_media,
    last_clock_on_pid_with_offset,
    packet_random_access,
    sample_media_clock,
)
from .ts_discontinuity import stamp_first_packet_per_pid
from ..utils import get_logger
import gevent.event
import gevent

logger = get_logger()


class StreamBuffer(DiscontinuitySidecarMixin):
    """Manages stream data buffering with optimized chunk storage"""

    # Recent chunks whose in-memory (offset, media, is_rap) map is retained,
    # counted in chunk indexes behind the head. Redis only keeps the end score
    # per chunk; this is the owner-side detail for mid-chunk join trim and
    # future splice/reconnect work, so it stays small.
    MEDIA_MAP_KEEP_CHUNKS = 32
    # Time-cap for undersized Redis chunks (PTS span when sampled, else wall).
    # High bitrate still hits ~256KB first; this is for low-bitrate / radio.
    MAX_COALESCE_SECONDS = 6.0

    def __init__(self, channel_id=None, redis_client=None,
                 buffer_index_key=None, buffer_chunk_prefix=None, chunk_timestamps_key=None,
                 discontinuities_key=None, chunk_media_scores_key=None):
        self.channel_id = channel_id
        self.redis_client = redis_client
        self.lock = threading.Lock()
        self.index = 0
        self.TS_PACKET_SIZE = TS_PACKET_SIZE

        self.buffer_index_key = buffer_index_key or (RedisKeys.buffer_index(channel_id) if channel_id else "")
        self.buffer_prefix = buffer_chunk_prefix or (RedisKeys.buffer_chunk_prefix(channel_id) if channel_id else "")

        self.chunk_ttl = ConfigHelper.redis_chunk_ttl()

        # PAT/PMT locations per chunk, shared by every output reading this
        # buffer so each chunk is scanned once, not once per output.
        self.psi_scan_cache = PsiScanCache()

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
        self._coalesce_started_at = None

        # Sorted-set key for chunk receive-timestamps (wall-clock join fallback)
        self.chunk_timestamps_key = chunk_timestamps_key or (RedisKeys.chunk_timestamps(channel_id) if channel_id else "")
        # Stream-time scores (PTS/PCR). Only written when media indexing is on.
        if chunk_media_scores_key is not None:
            self.chunk_media_scores_key = chunk_media_scores_key
        elif channel_id and buffer_index_key is None:
            self.chunk_media_scores_key = RedisKeys.chunk_media_scores(channel_id)
        else:
            self.chunk_media_scores_key = ""
        # Start-of-chunk PTS for the default input buffer. Empty on output rings.
        if self.chunk_media_scores_key and channel_id and buffer_index_key is None and chunk_media_scores_key is None:
            self.chunk_media_starts_key = RedisKeys.chunk_media_starts(channel_id)
        else:
            self.chunk_media_starts_key = ""
        # When True and the ingest sparse map did not cover this chunk, publish
        # an end score from a cheap tail clock sample (output-profile rings).
        # Input ingest leaves this False so unscored stretches stay unscored.
        self.media_score_from_chunk_end = False
        # Locked clock for media_score_from_chunk_end so successive chunks stay
        # on one PID (avoids audio/video jitter between end scores).
        self._media_score_pid = None
        self._media_score_kind = None
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

        # Experimental ingest: score each chunk by end-of-chunk media time so
        # joins use stream time behind the head. Samples are passed through from
        # the ingest hook (no second TS parse): (offset into _write_buffer,
        # media seconds, is_rap) triples, consumed as chunks flush to Redis.
        self.media_index_enabled = False
        self._coalesce_media_map = []
        # chunk index -> its (offset in chunk, media seconds, is_rap) triples,
        # newest MEDIA_MAP_KEEP_CHUNKS only. Insertion ordered so trimming is O(1).
        self._chunk_media_maps = {}
        # Continuous media timeline for Redis scores / sparse maps. Raw PTS/PCR
        # wraps every ~26.5h; the join zset must stay monotonic within an era.
        self._media_unwrap_raw = None
        self._media_unwrap_value = None

        # Register Lua scripts once — subsequent calls use EVALSHA (just the
        # SHA hash) instead of sending the full script text on every invocation.
        if self.redis_client:
            self._find_oldest_chunk_sha = self.redis_client.register_script(
                self._FIND_OLDEST_CHUNK_LUA
            )
            self._find_chunk_by_time_sha = self.redis_client.register_script(
                self._FIND_CHUNK_BY_TIME_LUA
            )
            self._find_chunk_behind_sha = self.redis_client.register_script(
                FIND_CHUNK_BEHIND_HEAD_LUA
            )
        else:
            self._find_oldest_chunk_sha = None
            self._find_chunk_by_time_sha = None
            self._find_chunk_behind_sha = None

        # Track timers for proper cleanup
        self.stopping = False
        self.fill_timers = []
        self.chunk_available = gevent.event.Event()
        # Optional callable(packet_bytes, wall=...) for ingest lag. Wall is
        # stamped when this socket payload arrives; the bytes are the complete
        # TS packets formed from that payload. Called outside self.lock after
        # those packets are extended onto _write_buffer and before Redis flush,
        # so note_media_clock can record the sample (or skip if failover
        # already flushed the append).
        self.on_packets_received = None
        self._hook_failure_logged = False

    def enable_media_index(self, enabled=True):
        """Turn stream-time chunk scoring on or off (experimental ingest).

        Either direction drops the published scores: a new session must not
        read the previous one's, and readers must stop joining on a timeline
        nobody maintains. Only the owning writer calls this; readers on other
        workers decide from the setting (see ``_media_join_active``).
        """
        enabled = bool(enabled) and bool(self.chunk_media_scores_key)
        if enabled == self.media_index_enabled:
            return
        self.media_index_enabled = enabled
        self.clear_media_scores()

    def chunk_media_map(self, chunk_index):
        """In-memory ``(offset, media_seconds, is_rap)`` triples for a recent chunk, or ()."""
        return tuple(self._chunk_media_maps.get(int(chunk_index), ()))

    def _clear_media_maps(self):
        self._coalesce_media_map = []
        self._chunk_media_maps = {}
        self._media_unwrap_raw = None
        self._media_unwrap_value = None
        self._media_score_pid = None
        self._media_score_kind = None

    def _unwrap_media_unlocked(self, raw):
        """Map a raw PTS/PCR second onto the continuous score timeline.

        Caller holds ``self.lock`` (or is the sole writer of unwrap state).
        """
        self._media_unwrap_raw, self._media_unwrap_value = advance_unwrapped_media(
            raw, self._media_unwrap_raw, self._media_unwrap_value
        )
        return self._media_unwrap_value

    def _end_score_from_chunk_tail(self, chunk_data):
        """Last PTS/PCR in ``chunk_data``, locked to one PID for the era.

        Used by output-profile rings (no ingest sparse map). Staying on one
        PID keeps successive end scores monotonic aside from true wraps.
        """
        media = None
        if self._media_score_pid is not None and self._media_score_kind is not None:
            media, _off = last_clock_on_pid_with_offset(
                chunk_data, self._media_score_pid, self._media_score_kind
            )
        if media is None:
            media, kind, pid = sample_media_clock(chunk_data)
            if media is None:
                return None
            self._media_score_pid = pid
            self._media_score_kind = kind
        return self._unwrap_media_unlocked(media)

    def note_media_clock(self, media, append_len, offset_in_append=None):
        """Record one ingest sample onto the in-flight coalesce map.

        Called from the packet-receive hook after a successful PTS/PCR sample,
        so the clock is parsed once, by ingest. ``append_len`` is the size of
        the socket read the sample came from and ``offset_in_append`` is the
        clock packet's offset in it (end of the read when unknown). Those bytes
        are already in ``_write_buffer``; if failover flushed or cleared them
        first the sample is dropped. ``is_rap`` is taken from the clock
        packet's adaptation-field random_access_indicator when present. Media
        is stored on the continuous (wrap-unwrapped) timeline used for Redis
        scores so mid-chunk trim and the join script share one clock.
        """
        if not self.media_index_enabled:
            return
        if offset_in_append is None:
            offset_in_append = append_len - self.TS_PACKET_SIZE
        with self.lock:
            buffered = len(self._write_buffer)
            if buffered < append_len:
                return
            abs_off = buffered - append_len + offset_in_append
            # RAP on the locked clock packet marks a join keyframe candidate.
            # The locked PID is whichever elementary stream ingest bound first
            # (often video, but may be audio or a PCR PID).
            is_rap = False
            end = abs_off + self.TS_PACKET_SIZE
            if abs_off >= 0 and end <= buffered:
                packet = self._write_buffer[abs_off:end]
                if len(packet) == self.TS_PACKET_SIZE and packet[0] == 0x47:
                    is_rap = packet_random_access(packet)
            unwrapped = self._unwrap_media_unlocked(media)
            self._coalesce_media_map.append((abs_off, unwrapped, is_rap))

    def _take_coalesce_media_for_chunk(self, chunk_len):
        """Pop the triples that fall in the next ``chunk_len`` bytes; rebase the rest.

        The caller has already removed those bytes from ``_write_buffer``, so
        the samples go whether or not the Redis write succeeds. Keeping them
        after a failed write would leave stale offsets pointing into the next
        chunk.
        """
        samples = self._coalesce_media_map
        if not samples:
            return samples
        self._coalesce_media_map = [
            (off - chunk_len, media, is_rap)
            for off, media, is_rap in samples
            if off >= chunk_len
        ]
        return [sample for sample in samples if sample[0] < chunk_len]

    def _coalesce_span_seconds_unlocked(self, now=None):
        """Seconds held in the coalesce buffer: max of PTS span and wall age.

        PTS needs at least two samples. Wall age covers non-experimental and
        pre-score feeds so either clock can trip the flush.
        """
        now = time.time() if now is None else float(now)
        wall_span = 0.0
        started = self._coalesce_started_at
        if started is not None:
            wall_span = max(0.0, now - float(started))

        media_span = 0.0
        samples = self._coalesce_media_map
        if len(samples) >= 2:
            media_span = max(0.0, float(samples[-1][1]) - float(samples[0][1]))

        return max(wall_span, media_span)

    def _coalesce_due_unlocked(self, now=None):
        """True when the undersized coalesce buffer should publish to Redis."""
        if not self._write_buffer:
            return False
        return self._coalesce_span_seconds_unlocked(now) >= self.MAX_COALESCE_SECONDS

    def _flush_ready_chunks_unlocked(self, now=None):
        """Flush full-size chunks, then a time-capped undersized remainder.

        Caller holds ``self.lock``. Returns how many chunks reached Redis.
        """
        now = time.time() if now is None else float(now)
        buffered_before = len(self._write_buffer)
        written = self._flush_full_chunks_unlocked()
        if self._write_buffer and len(self._write_buffer) < buffered_before:
            # Remainder is new since this flush, not since the buffer was last
            # empty. Key off shrink (bytes leave even when Redis rejects).
            self._coalesce_started_at = now
        if self._write_buffer and self._coalesce_due_unlocked(now):
            if self._flush_write_buffer_unlocked():
                written += 1
        if not self._write_buffer:
            self._coalesce_started_at = None
        return written

    def add_chunk(self, chunk):
        """Add data with optimized Redis storage and TS packet alignment"""
        if not chunk or self.stopping:
            return False

        hook = self.on_packets_received
        arrival_wall = time.time()

        try:
            # Accumulate partial packets between chunks
            if not hasattr(self, '_partial_packet'):
                self._partial_packet = bytearray()

            # Lock the full operation to prevent race with reset_buffer_position
            writes_done = 0
            sample_packets = None
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

                # Ingest sample uses only what this socket read completed, not
                # the Redis-sized coalesce waiting in _write_buffer.
                if hook is not None:
                    sample_packets = complete_packets

                # Add completed packets to write buffer
                if complete_packets and not self._write_buffer:
                    self._coalesce_started_at = arrival_wall
                self._write_buffer.extend(complete_packets)

                # With a hook, flush after sampling so PTS span can tip the cap.
                if hook is None:
                    writes_done = self._flush_ready_chunks_unlocked(now=arrival_wall)

            if sample_packets is not None:
                try:
                    hook(sample_packets, wall=arrival_wall)
                except Exception as e:
                    # A broken hook must never stall ingest. Say so once at
                    # warning level (it silently disables detection), then
                    # keep later repeats quiet.
                    if not self._hook_failure_logged:
                        self._hook_failure_logged = True
                        logger.warning(
                            f"Packet receive hook failed for channel {self.channel_id}: {e}",
                            exc_info=True,
                        )
                        self.on_packets_received = None
                    else:
                        logger.debug(
                            f"Packet receive hook failed for channel {self.channel_id}: {e}"
                        )

                # Flush under the lock: failover can clear the coalesce buffer
                # on another thread between the hook and this write.
                with self.lock:
                    writes_done = self._flush_ready_chunks_unlocked(
                        now=arrival_wall
                    )

            if writes_done > 0:
                logger.debug(
                    f"Added {writes_done} chunk(s) to Redis for channel "
                    f"{self.channel_id} at index {self.index}"
                )

            self.chunk_available.set()  # Signal that new data is available
            self.chunk_available.clear()  # Reset for next notification

            return True

        except Exception as e:
            logger.error(f"Error adding chunk to buffer: {e}")
            return False

    def _flush_full_chunks_unlocked(self):
        """Write every full target-size chunk waiting in ``_write_buffer``.

        Caller holds ``self.lock``. Returns how many reached Redis.
        """
        written = 0
        while len(self._write_buffer) >= self.target_chunk_size:
            chunk_data = bytes(self._write_buffer[:self.target_chunk_size])
            del self._write_buffer[:self.target_chunk_size]
            if self._write_chunk_unlocked(chunk_data):
                written += 1
        return written

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

        media_map = None
        end_score = None
        start_score = None
        if self.media_index_enabled:
            # The caller already removed these bytes from _write_buffer, so
            # take their samples now, whether or not Redis accepts the chunk.
            media_map = self._take_coalesce_media_for_chunk(len(chunk_data))
            if media_map:
                start_score = media_map[0][1]
                end_score = media_map[-1][1]
            elif self.media_score_from_chunk_end:
                # Output-profile path: no ingest samples, score the last PTS/PCR
                # on the locked clock PID in this chunk's tail.
                end_score = self._end_score_from_chunk_tail(chunk_data)
            if end_score is not None:
                pipe.zadd(
                    self.chunk_media_scores_key,
                    {str(chunk_index): float(end_score)},
                )
            if start_score is not None and self.chunk_media_starts_key:
                pipe.zadd(
                    self.chunk_media_starts_key,
                    {str(chunk_index): float(start_score)},
                )
            # Refresh TTL even on unscored chunks so a quiet stretch cannot
            # expire the join index while the channel is live.
            pipe.expire(self.chunk_media_scores_key, self.chunk_ttl)
            if self.chunk_media_starts_key:
                pipe.expire(self.chunk_media_starts_key, self.chunk_ttl)
            # One member ages out of the retention window per chunk. Dropping
            # it directly is O(log N); no scan of the set.
            min_keep = media_score_min_index(chunk_index, self.chunk_ttl)
            if min_keep > 0:
                pipe.zrem(self.chunk_media_scores_key, str(min_keep - 1))
                if self.chunk_media_starts_key:
                    pipe.zrem(self.chunk_media_starts_key, str(min_keep - 1))

        try:
            pipe.execute()
        except Exception as e:
            logger.error(
                f"Failed to write buffer chunk {chunk_index} for channel "
                f"{self.channel_id}: {e}"
            )
            return False

        self.index = chunk_index
        if media_map:
            maps = self._chunk_media_maps
            maps[chunk_index] = media_map
            floor = chunk_index - self.MEDIA_MAP_KEEP_CHUNKS
            while True:
                oldest = next(iter(maps))
                if oldest > floor:
                    break
                del maps[oldest]

        # First Redis chunk after a discontinuity mark finishes the in-band
        # stamping pass (PAT/PMT/A/V first packets are already in this chunk).
        if self._disc_stamp_active and chunk_index > self._disc_mark_index:
            self._disc_stamp_active = False

        return True

    def clear_media_scores(self):
        """Drop stream-time join scores (discontinuity or ingest timeline reset)."""
        with self.lock:
            self._clear_media_maps()
            self._delete_media_scores_key_unlocked()

    def _delete_media_scores_key_unlocked(self):
        """Delete the Redis media-score zset. Caller holds ``self.lock`` or accepts the race."""
        if not self.redis_client or not self.chunk_media_scores_key:
            return
        try:
            if self.chunk_media_starts_key:
                self.redis_client.delete(
                    self.chunk_media_scores_key, self.chunk_media_starts_key
                )
            else:
                self.redis_client.delete(self.chunk_media_scores_key)
        except Exception as e:
            logger.warning(
                f"Failed to clear media scores for channel {self.channel_id}: {e}"
            )

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
                self._coalesce_started_at = None
                # Incomplete trailing bytes belong to the old source and must
                # not be prepended to the new source's first packet.
                if hasattr(self, '_partial_packet'):
                    self._partial_packet = bytearray()

                self._disc_mark_index = self.index
                next_index = self.index + 1
                self._disc_stamp_active = True
                self._disc_stamped_pids = set()
                self._record_discontinuity_unlocked(next_index)
                # New era gets a fresh media timeline. Clear under this same
                # lock (clear_media_scores also takes the lock).
                self._clear_media_maps()
                self._delete_media_scores_key_unlocked()

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

    def reset_buffer_position(self):
        """
        Reset internal buffers for a clean stream transition (failover).

        Prefer mark_discontinuity() on URL switches: it flushes complete
        packets to Redis before clearing. This method remains as a fallback
        when that mark fails, and for callers that only need to drop local
        leftovers after a successful mark. Without clearing _partial_packet,
        bytes from the old FFmpeg get concatenated with the first bytes from
        the new FFmpeg, creating corrupted TS packets that break audio decoder
        sync in the client.

        Also clears local media maps / unwrap state and deletes Redis media
        scores so a reset-only failover cannot keep joining on the previous
        stream-time timeline. Idempotent if mark_discontinuity already did.
        """
        try:
            with self.lock:
                old_write_size = len(self._write_buffer)
                old_partial_size = len(getattr(self, '_partial_packet', b''))

                self._write_buffer = bytearray()
                self._coalesce_started_at = None
                if hasattr(self, '_partial_packet'):
                    self._partial_packet = bytearray()
                # Same media-timeline wipe as mark_discontinuity's score clear,
                # without flushing or recording a discontinuity sidecar entry.
                self._clear_media_maps()
                self._delete_media_scores_key_unlocked()

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

    def _get_chunks_exact_indexed(self, start_index, count):
        """Return [(redis_index, bytes), ...] for the chunks that still exist.

        Missing keys are omitted. The index is the real Redis chunk number, so
        a hole in the middle does not renumber the chunks that follow it.
        Returns None when the read failed, and an empty list when every
        requested key is absent or the range is past the buffer head.
        """
        try:
            if not self.redis_client:
                logger.error("Redis not available, cannot retrieve chunks")
                return None

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

            # Keep the Redis index with each hit. A missing key is a hole,
            # not a shift of every later chunk.
            indexed = [
                (idx, result)
                for idx, result in zip(range(start_id, end_id), results)
                if result is not None
            ]

            # Update local index if needed
            if indexed and indexed[-1][0] > self.index:
                self.index = indexed[-1][0]

            return indexed

        except Exception as e:
            logger.error(f"Error getting exact chunks: {e}", exc_info=True)
            return None

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
                    self._coalesce_started_at = None
                    if hasattr(self, '_partial_packet'):
                        self._partial_packet = bytearray()
                    logger.debug(
                        f"Discarded {discarded} bytes from local write buffer "
                        f"for channel {self.channel_id}"
                    )
        except Exception as e:
            logger.error(f"Error during buffer stop: {e}")

    def get_optimized_client_data(self, client_index):
        """Get optimal amount of data for client streaming based on position and target size."""
        indexed, new_index = self.get_optimized_client_data_indexed(client_index)
        return [data for _idx, data in indexed], new_index

    def get_optimized_client_data_indexed(self, client_index):
        """Same batch as get_optimized_client_data, with each chunk's Redis index.

        Returns ([(index, bytes), ...], new_index). ``new_index`` is the end of
        the requested range, including holes, so the caller does not read the
        same gap again. A first batch under about 1MB is followed by more
        batches until that target, the 2MB cap, the per-call chunk ceiling,
        or the buffer head.
        """
        # Define limits
        MIN_CHUNKS = 3                      # Minimum chunks to read for efficiency
        MAX_CHUNKS = 20                     # Max chunks per Redis read
        MAX_CHUNKS_PER_CALL = 100           # Ceiling across top-up batches (bounds round-trips)
        TARGET_SIZE = 1024 * 1024           # Keep reading small chunks until ~1MB
        MAX_SIZE = 2 * 1024 * 1024          # Do not append a further batch past this

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
            # Way behind. First read is one batch; the loop below tops up
            # when those chunks are still under the size target.
            chunk_count = MAX_CHUNKS

        # Retrieve chunks. Each entry is (redis_index, bytes); holes are omitted.
        indexed = self._get_chunks_exact_indexed(client_index, chunk_count)
        if indexed is None:
            # Transient Redis failure: keep the caller's index so the next
            # attempt retries the same range instead of skipping past it.
            return [], client_index

        # Check if we got significantly fewer chunks than expected (likely due to expiration)
        # Only check if we expected multiple chunks and got none or very few
        if not indexed and chunk_count > 3 and chunks_behind > 10:
            # Chunks are missing. Signal the caller to skip forward.
            logger.debug(f"Chunks missing for client at index {client_index}, buffer at {self.index} ({chunks_behind} behind)")
            return [], client_index

        # Check total size
        total_size = sum(len(c) for _idx, c in indexed)

        # The first batch is capped at MAX_CHUNKS, so a run of small chunks
        # can sit under the 1MB target with more data still buffered. Keep
        # reading one batch at a time. A failed read (None) stops without
        # skipping ahead; an empty one is a hole and is advanced over.
        while (
            total_size < TARGET_SIZE
            and chunks_behind > chunk_count
            and chunk_count < MAX_CHUNKS_PER_CALL
        ):
            additional = min(
                MAX_CHUNKS,
                chunks_behind - chunk_count,
                MAX_CHUNKS_PER_CALL - chunk_count,
            )
            more_chunks = self._get_chunks_exact_indexed(
                client_index + chunk_count, additional
            )
            if more_chunks is None:
                break
            additional_size = sum(len(c) for _idx, c in more_chunks)
            if total_size + additional_size > MAX_SIZE:
                break
            indexed.extend(more_chunks)
            total_size += additional_size
            # Requested span, not hit count, so a hole is not read again.
            chunk_count += additional

        return indexed, client_index + chunk_count

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

    def find_chunk_index_behind(self, seconds_behind):
        """Find the chunk index approximately *seconds_behind* the buffer head.

        Stream-time path (experimental ingest scoring): one behind-head Lua
        round trip on ``chunk_media_scores``. Otherwise the wall-clock join
        script on ``chunk_timestamps`` (also one round trip). Index-only
        callers (for example fMP4 remux seeding) use this; MPEG-TS clients
        that need mid-chunk trim should call ``resolve_join_position``.

        Returns:
            int or None: Last-consumed index (next read starts at index+1),
            or None if no suitable chunk exists.
        """
        last_consumed, _target = self.resolve_join_position(seconds_behind)
        return last_consumed

    def resolve_join_position(self, seconds_behind):
        """Return ``(last_consumed, target_media)`` for a behind-head join.

        ``target_media`` is set only for stream-time joins so the first chunk
        can be mid-chunk trimmed. Wall-clock joins return ``(index, None)``.
        Either element may be None when positioning is unavailable.
        """
        if self._media_join_active():
            last_consumed, target = self._find_media_join(seconds_behind)
            if last_consumed is not None:
                return last_consumed, target
        return self.find_chunk_index_by_time(seconds_behind), None

    def prepare_first_join_chunk(self, chunk_index, chunk_data, target_media):
        """Trim the first delivered chunk to ``target_media`` (keyframe when possible).

        Uses the owner-side sparse map when present; otherwise scans this one
        chunk once. PAT/PMT often ride only with keyframes, so a chunk can
        carry none; the stream layout is then learned from older chunks. When
        the opening keyframe is in a prior Redis chunk (GOP spanning a
        boundary), priors are chosen by end-score in about two seconds of
        media before ``target_media`` (join depth unchanged), fetched once,
        and prepended from the RAP. When the opening keyframe lacks SPS/PPS
        (VPS), the same prior fetch supplies in-band parameter sets. Safe
        no-op when ``target_media`` is None. Skips Redis entirely when the
        in-chunk cut already lands on a keyframe that carries decoder init,
        and for any keyframe that does not need H.264/HEVC parameter sets.
        """
        if target_media is None or not chunk_data:
            return chunk_data
        chunk_index = int(chunk_index)
        media_map = self.chunk_media_map(chunk_index)
        priors = None
        video_pid, stream_type = discover_video_layout(chunk_data)
        if video_pid is None:
            priors = self._load_join_prior_chunks(
                chunk_index, target_media=target_media
            )
            video_pid, stream_type = discover_layout_in_chunks(priors)
        cut = resolve_join_cut(
            chunk_data,
            target_media,
            media_map=media_map,
            video_pid=video_pid,
            stream_type=stream_type,
        )
        if cut["skip_prior_fetch"]:
            return prepare_join_chunk(
                chunk_data, target_media, media_map=media_map, cut=cut
            )

        if priors is None:
            priors = self._load_join_prior_chunks(
                chunk_index, target_media=target_media
            )
        extra = None
        if cut["needs_prior_for_params"]:
            extra = merge_parameter_sets_from_chunks(
                priors, cut["video_pid"], cut["stream_type"]
            )
        return prepare_join_chunk(
            chunk_data,
            target_media,
            media_map=media_map,
            cut=cut,
            prior_chunks=priors if cut["needs_prior_for_kf"] else None,
            extra_param_sets=extra,
        )

    def _join_era_floor(self, chunk_index):
        """First chunk index of the current discontinuity era (inclusive)."""
        era_floor = 1
        if not self.discontinuities_key:
            return era_floor
        try:
            discs = self.discontinuities_in_range(0, chunk_index)
            if discs:
                # Disc index D is the first chunk of the new source era.
                era_floor = max(era_floor, max(discs))
        except Exception as e:
            logger.debug(
                f"Join prior discontinuity lookup failed for channel "
                f"{self.channel_id}: {e}"
            )
        return era_floor

    def _join_prior_indexes(self, chunk_index, target_media=None):
        """Prior chunk indexes newest-first for RAP / decoder-init lookback.

        Scores are end-of-chunk media times taken from the last sampled clock,
        so a chunk can run slightly past its recorded end, and some chunks are
        unscored. The span therefore starts at the newest chunk that appears to
        end before ``target - KEYFRAME_LOOKBACK_SECONDS`` (join depth
        unchanged), as a one-chunk margin, and runs contiguously through
        ``chunk_index - 1``. Unscored chunks inside that span are included,
        never skipped. With no such chunk (a short or newly scored buffer) the
        span reaches back to the discontinuity era. Always bounded by the era
        and ``KEYFRAME_LOOKBACK_MAX_CHUNKS``.
        """
        chunk_index = int(chunk_index)
        era_floor = self._join_era_floor(chunk_index)
        if era_floor >= chunk_index:
            return []

        newest = chunk_index - 1
        oldest = era_floor
        if (
            target_media is not None
            and self.redis_client
            and self.chunk_media_scores_key
        ):
            try:
                floor = float(target_media) - float(KEYFRAME_LOOKBACK_SECONDS)
                before = self.redis_client.zrevrangebyscore(
                    self.chunk_media_scores_key, floor, "-inf", start=0, num=1
                )
                if before:
                    oldest = max(oldest, int(before[0]))
            except Exception as e:
                logger.debug(
                    f"Join prior score window failed for channel "
                    f"{self.channel_id}: {e}"
                )

        oldest = max(oldest, newest - KEYFRAME_LOOKBACK_MAX_CHUNKS + 1)
        return list(range(newest, oldest - 1, -1))

    def _load_join_prior_chunks(self, chunk_index, target_media=None):
        """Chunk bytes newest-first, contiguous with ``chunk_index``.

        Stops at the first missing chunk: chunks expire oldest first, so
        anything beyond a gap is stale, and joining across it would put a hole
        in the delivered timeline.
        """
        if not self.redis_client or not self.buffer_prefix:
            return []
        indices = self._join_prior_indexes(chunk_index, target_media=target_media)
        if not indices:
            return []
        try:
            pipe = self.redis_client.pipeline(transaction=False)
            for idx in indices:
                pipe.get(f"{self.buffer_prefix}{idx}")
            values = pipe.execute()
        except Exception as e:
            logger.debug(
                f"Join prior chunk load failed for channel {self.channel_id}: {e}"
            )
            return []
        priors = []
        for data in values:
            if not data:
                break
            priors.append(data)
        return priors

    def _media_join_active(self):
        """True when a stream-time join is worth trying.

        The owning writer sets ``media_index_enabled``. A reader on another
        worker never enables indexing (that clears the published scores), so it
        follows the experimental setting, which is cached in-process. With the
        feature off this costs no Redis call, so the default join stays a
        single wall-clock script.
        """
        return bool(self.chunk_media_scores_key) and (
            self.media_index_enabled or ConfigHelper.experimental_ingest_buffer()
        )

    def _find_media_join(self, seconds_behind):
        """Stream-time ``(last_consumed, target_media)``, or ``(None, None)``."""
        if not self.redis_client or not self._find_chunk_behind_sha:
            return None, None
        try:
            return eval_behind_head_join(
                self._find_chunk_behind_sha,
                self.chunk_media_scores_key,
                self.buffer_index_key,
                self.discontinuities_key,
                seconds_behind,
                use_discontinuity=bool(self.discontinuities_key),
            )
        except Exception as e:
            logger.error(
                f"Error in media find_chunk_index_behind for channel "
                f"{self.channel_id}: {e}"
            )
            return None, None

    def schedule_timer(self, delay, callback, *args, **kwargs):
        """Schedule a timer and track it for proper cleanup"""
        if self.stopping:
            return None

        timer = gevent.spawn_later(delay, callback, *args, **kwargs)
        self.fill_timers.append(timer)
        return timer
