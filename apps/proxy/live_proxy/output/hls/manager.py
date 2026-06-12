"""
HLS Output Manager

Reads from the shared TS Redis buffer, splits the stream into
keyframe-aligned TS segments (pure packet copy, no remux, no subprocess;
see segmenter.py), stores one segment per Redis chunk via the shared
format-parameterized output buffer, and maintains a rolling live playlist
descriptor in Redis that the playlist view renders per request.

One instance per channel per cluster - coordinated via the shared
output:{fmt}:owner lock, exactly like the fMP4 remux manager.
"""

import json
import threading
import time

from core.utils import RedisClient
from ..fmp4.buffer import FMP4StreamBuffer
from .segmenter import TSSegmenter
from ...redis_keys import RedisKeys
from ...config_helper import ConfigHelper
from ...utils import get_logger

logger = get_logger()

# Output manager states stored in Redis (shared vocabulary with fMP4)
HLS_STATE_INITIALIZING = "initializing"
HLS_STATE_ACTIVE = "active"
HLS_STATE_STOPPED = "stopped"

# Redis TTL for state/owner/playlist keys
HLS_KEY_TTL = 3600

# Defaults; both overridable via proxy settings
DEFAULT_SEGMENT_DURATION = 4
DEFAULT_WINDOW_SIZE = 6


class HLSOutputManager:
    """
    Reads the TS Redis buffer for a channel, cuts keyframe-aligned HLS
    segments, and publishes them plus a rolling playlist window to Redis.
    """

    def __init__(self, channel_id, ts_buffer, worker_id, fmt='hls'):
        self.channel_id = channel_id
        self.ts_buffer = ts_buffer
        self.worker_id = worker_id
        self.fmt = fmt
        self.running = False
        self._thread = None

        self.segment_duration = ConfigHelper.get('HLS_SEGMENT_DURATION', DEFAULT_SEGMENT_DURATION)
        self.window_size = ConfigHelper.get('HLS_WINDOW_SIZE', DEFAULT_WINDOW_SIZE)

        # Same Redis-backed chunk store the fMP4 manager uses; it is
        # format-parameterized by design ("adding a new output format only
        # requires a new manager" - redis_keys.py). One HLS segment per
        # chunk; the chunk index doubles as the HLS media sequence number.
        self.segment_buffer = FMP4StreamBuffer(
            channel_id, redis_client=RedisClient.get_buffer(), fmt=fmt
        )
        self._redis = RedisClient.get_client()
        self._window = []

    # ------------------------------------------------------------------
    # Public API (same surface as FMP4RemuxManager)
    # ------------------------------------------------------------------

    def start(self):
        """Acquire the output owner lock and spawn the segmenter thread."""
        if not self._acquire_owner_lock():
            logger.info(f"[HLS:{self.channel_id}] Another worker owns HLS output, skipping start")
            return False

        self.running = True
        self._set_state(HLS_STATE_INITIALIZING)

        short_id = self.channel_id[:8]
        self._thread = threading.Thread(
            target=self._segmenter_loop, daemon=True,
            name=f"hls-seg-{short_id}"
        )
        self._thread.start()

        logger.info(
            f"[HLS:{self.channel_id}] Started "
            f"(target={self.segment_duration}s, window={self.window_size})"
        )
        return True

    def stop(self):
        """Stop the segmenter thread and clean up all Redis keys."""
        if not self.running:
            return
        self.running = False
        logger.info(f"[HLS:{self.channel_id}] Stopping")

        if self._thread and self._thread.is_alive():
            try:
                self._thread.join(timeout=2)
            except Exception:
                pass

        self._cleanup_redis()
        logger.info(f"[HLS:{self.channel_id}] Stopped")

    # ------------------------------------------------------------------
    # Segmenter loop
    # ------------------------------------------------------------------

    def _segmenter_loop(self):
        """Read TS chunks from Redis and feed them through the segmenter."""
        segmenter = TSSegmenter(target_duration=self.segment_duration)

        # Start behind live so the first segments cover the same window a
        # new TS client would receive, matching fMP4 writer positioning.
        behind_seconds = ConfigHelper.new_client_behind_seconds()
        start_index = self.ts_buffer.find_chunk_index_by_time(behind_seconds) if behind_seconds > 0 else None
        if start_index is None:
            start_index = self.ts_buffer.index
        local_index = start_index
        first_segment_stored = False
        logger.debug(
            f"[HLS:{self.channel_id}] Segmenter started at buffer index "
            f"{local_index} ({behind_seconds}s behind live)"
        )

        try:
            while self.running:
                chunks, new_index = self.ts_buffer.get_optimized_client_data(local_index)

                if chunks:
                    local_index = new_index
                    for chunk in chunks:
                        if not self.running:
                            break
                        for segment in segmenter.feed(chunk):
                            self._store_segment(segment)
                            if not first_segment_stored:
                                first_segment_stored = True
                                self._set_state(HLS_STATE_ACTIVE)
                                logger.info(
                                    f"[HLS:{self.channel_id}] First segment stored "
                                    f"({segment.duration:.2f}s, {len(segment.data)} bytes)"
                                )
                else:
                    if self.ts_buffer.index > local_index + 20:
                        # Fell too far behind (slow consumer / provider burst):
                        # skip forward and mark the gap for the playlist.
                        local_index = self.ts_buffer.index - 5
                        segmenter.flag_discontinuity()
                        logger.debug(
                            f"[HLS:{self.channel_id}] Skipped forward to index {local_index}"
                        )
                    time.sleep(0.05)

        except Exception as e:
            logger.error(f"[HLS:{self.channel_id}] Segmenter loop error: {e}", exc_info=True)
        finally:
            logger.debug(f"[HLS:{self.channel_id}] Segmenter loop exited")

    def _store_segment(self, segment):
        """Store one finished segment and refresh the playlist descriptor."""
        if not self.segment_buffer.put_fragment(segment.data):
            return
        seq = self.segment_buffer.index
        self._window.append({
            "seq": seq,
            "dur": round(segment.duration, 3),
            "disc": bool(segment.discontinuity),
        })
        if len(self._window) > self.window_size:
            self._window = self._window[-self.window_size:]

        if self._redis:
            try:
                playlist_state = {
                    "window": self._window,
                    "target": self.segment_duration,
                }
                self._redis.setex(
                    RedisKeys.output_playlist(self.channel_id, self.fmt),
                    HLS_KEY_TTL,
                    json.dumps(playlist_state),
                )
            except Exception as e:
                logger.error(f"[HLS:{self.channel_id}] Error updating playlist state: {e}")

        logger.debug(
            f"[HLS:{self.channel_id}] Segment {seq}: "
            f"{segment.duration:.2f}s, {len(segment.data)} bytes"
            f"{' [discontinuity]' if segment.discontinuity else ''}"
        )

    # ------------------------------------------------------------------
    # Redis helpers (mirror FMP4RemuxManager)
    # ------------------------------------------------------------------

    def _acquire_owner_lock(self) -> bool:
        if not self._redis:
            return True
        owner_key = RedisKeys.output_owner(self.channel_id, self.fmt)
        acquired = self._redis.set(owner_key, self.worker_id, nx=True, ex=HLS_KEY_TTL)
        if acquired:
            return True
        existing = self._redis.get(owner_key)
        return existing == self.worker_id

    def _set_state(self, state: str):
        if self._redis:
            self._redis.setex(RedisKeys.output_state(self.channel_id, self.fmt), HLS_KEY_TTL, state)

    def _cleanup_redis(self):
        """Delete all HLS output Redis keys for this channel."""
        if not self._redis:
            return
        try:
            keys_to_delete = [
                RedisKeys.output_state(self.channel_id, self.fmt),
                RedisKeys.output_owner(self.channel_id, self.fmt),
                RedisKeys.output_playlist(self.channel_id, self.fmt),
            ]
            self._redis.delete(*keys_to_delete)
            self.segment_buffer.cleanup_redis()
        except Exception as e:
            logger.error(f"[HLS:{self.channel_id}] Error during Redis cleanup: {e}")
