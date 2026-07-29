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
# Retain 10 segments (~40s) in the rolling live window. A player starts
# near the live edge regardless of window length, so a longer window adds
# no latency; it only keeps older segments available so a client that
# briefly falls behind (a stall, a slow network hiccup) can still fetch the
# segment it is on instead of getting a 404 once it has rolled off.
DEFAULT_WINDOW_SIZE = 10

# Demand self-check. HLS clients are pull-based: there is no long-lived
# response whose teardown reports the disconnect, so the manager itself
# periodically verifies that at least one live client record still names
# this output, and retires through the server's shared demand accounting
# when none has for two consecutive checks.
DEMAND_CHECK_INTERVAL = 10
DEMAND_GRACE_CHECKS = 2


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
        # Set by the input side (StreamManager.update_url) when the upstream
        # switched; the next emitted segment is marked as a discontinuity.
        self._switch_pending = False

        self.segment_duration = ConfigHelper.get('HLS_SEGMENT_DURATION', DEFAULT_SEGMENT_DURATION)
        self.window_size = ConfigHelper.get('HLS_WINDOW_SIZE', DEFAULT_WINDOW_SIZE)
        # Advertised EXT-X-TARGETDURATION, computed ONCE and frozen for the life
        # of the playlist (RFC 8216 6.2.1: it MUST NOT change across reloads;
        # AVPlayer latches it at first parse and revalidates every reload). 2x
        # the cut target gives one GOP of headroom past the cut threshold so a
        # normal segment never exceeds it; the segmenter force-cuts anything that
        # would, keeping the frozen value truthful (RFC 8216 4.3.3.1).
        self.adv_target = int(2 * self.segment_duration + 0.999)

        # Same Redis-backed chunk store the fMP4 manager uses; it is
        # format-parameterized by design ("adding a new output format only
        # requires a new manager" - redis_keys.py). One HLS segment per
        # chunk; the chunk index doubles as the HLS media sequence number.
        self.segment_buffer = FMP4StreamBuffer(
            channel_id, redis_client=RedisClient.get_buffer(), fmt=fmt
        )
        # Size the chunk TTL to the advertised window plus ~one playlist of
        # post-removal availability (RFC 8216 6.2.2): a listed segment must stay
        # fetchable while in the playlist and for about a playlist duration after
        # it rolls off. A short default TTL cannot back a 10-segment window of
        # 5-6.5s segments, which 404s the window tail during stall recovery.
        try:
            self.segment_buffer.chunk_ttl = max(
                self.segment_buffer.chunk_ttl,
                int(self.window_size * (self.segment_duration + 3) + 30),
            )
        except Exception:
            pass
        self._redis = RedisClient.get_client()
        self._window = []
        # Seed the rolling window + frozen target from an existing descriptor so
        # a mid-session worker restart/takeover does not clobber the playlist to
        # a fresh window (MEDIA-SEQUENCE must never regress; RFC 8216 6.2.2). The
        # FMP4StreamBuffer already restores its chunk index from Redis, so the
        # seeded window's seqs line up with the segments still in the buffer.
        if self._redis:
            try:
                existing = self._redis.get(RedisKeys.output_playlist(self.channel_id, self.fmt))
                if existing:
                    prior = json.loads(existing)
                    if prior.get("window"):
                        self._window = prior["window"]
                    if prior.get("adv_target"):
                        self.adv_target = prior["adv_target"]
            except Exception:
                pass

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

    def notify_stream_switch(self):
        """Input-side signal: the upstream stream changed (manual switch or
        automatic failover). The next emitted segment must carry
        EXT-X-DISCONTINUITY (RFC 8216 4.3.2.3)."""
        self._switch_pending = True

    # ------------------------------------------------------------------
    # Segmenter loop
    # ------------------------------------------------------------------

    def _segmenter_loop(self):
        """Read TS chunks from Redis and feed them through the segmenter."""
        segmenter = TSSegmenter(
            target_duration=self.segment_duration,
            max_segment_duration=self.adv_target,
        )

        # Start behind live so the first segments cover the same window a
        # new TS client would receive, matching fMP4 writer positioning.
        behind_seconds = ConfigHelper.new_client_behind_seconds()
        start_index = self.ts_buffer.find_chunk_index_by_time(behind_seconds) if behind_seconds > 0 else None
        if start_index is None:
            start_index = self.ts_buffer.index
        local_index = start_index
        first_segment_stored = False
        last_demand_check = time.time()
        idle_demand_checks = 0
        logger.debug(
            f"[HLS:{self.channel_id}] Segmenter started at buffer index "
            f"{local_index} ({behind_seconds}s behind live)"
        )

        try:
            while self.running:
                if self._switch_pending:
                    self._switch_pending = False
                    # Hard cut: close the open segment from pre-switch bytes
                    # only; the next segment starts at a post-switch keyframe
                    # and carries the discontinuity tag.
                    tail = segmenter.flag_discontinuity()
                    if tail is not None:
                        self._store_segment(tail)
                    logger.info(
                        f"[HLS:{self.channel_id}] Input stream switched; segment "
                        f"cut, next segment will be marked as a discontinuity"
                    )

                now = time.time()
                if now - last_demand_check >= DEMAND_CHECK_INTERVAL:
                    last_demand_check = now
                    if self._has_hls_demand():
                        idle_demand_checks = 0
                    else:
                        idle_demand_checks += 1
                        if idle_demand_checks >= DEMAND_GRACE_CHECKS:
                            logger.info(
                                f"[HLS:{self.channel_id}] No {self.fmt} clients for "
                                f"{idle_demand_checks * DEMAND_CHECK_INTERVAL}s; retiring output"
                            )
                            self._retire()
                            break

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
                        # skip forward and mark the gap for the playlist. The
                        # open segment is hard-cut so pre-gap and post-gap
                        # data never share a segment.
                        local_index = self.ts_buffer.index - 5
                        tail = segmenter.flag_discontinuity()
                        if tail is not None:
                            self._store_segment(tail)
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
                    "adv_target": self.adv_target,
                }
                self._redis.setex(
                    RedisKeys.output_playlist(self.channel_id, self.fmt),
                    HLS_KEY_TTL,
                    json.dumps(playlist_state),
                )
            except Exception as e:
                logger.error(f"[HLS:{self.channel_id}] Error updating playlist state: {e}")

        # Heartbeat the owner lock and state key (both set once with ex=3600 and
        # otherwise never refreshed): a stream longer than an hour would silently
        # lose mutual exclusion and let a second worker start a duplicate
        # segmenter, breaking MEDIA-SEQUENCE monotonicity. If ownership has moved,
        # stop cleanly rather than fight the new owner.
        self._heartbeat_ownership()

        logger.debug(
            f"[HLS:{self.channel_id}] Segment {seq}: "
            f"{segment.duration:.2f}s, {len(segment.data)} bytes"
            f"{' [discontinuity]' if segment.discontinuity else ''}"
        )

    # ------------------------------------------------------------------
    # Demand accounting (pull-based clients)
    # ------------------------------------------------------------------

    def _has_hls_demand(self):
        """True when at least one live client record consumes this manager's
        output. Mirrors the per-format accounting in handle_client_disconnect;
        set entries whose metadata hash has expired are ghosts and do not
        count as demand."""
        if not self._redis:
            return True  # cannot verify; err on the side of running
        try:
            client_ids = list(self._redis.smembers(RedisKeys.clients(self.channel_id)))
            if not client_ids:
                return False
            pipe = self._redis.pipeline(transaction=False)
            for cid in client_ids:
                pipe.hget(RedisKeys.client_metadata(self.channel_id, cid), "output_format")
                pipe.hget(RedisKeys.client_metadata(self.channel_id, cid), "output_profile_id")
            results = pipe.execute()
            for i in range(0, len(results), 2):
                fmt = results[i]
                if not fmt:
                    continue  # expired hash: a ghost entry, not demand
                fmt = fmt.decode() if isinstance(fmt, bytes) else fmt
                pid = results[i + 1]
                pid = (pid.decode() if isinstance(pid, bytes) else pid) if pid else ''
                manager_key = fmt
                if pid:
                    try:
                        manager_key = f"{fmt}:p{int(pid)}"
                    except ValueError:
                        pass
                if manager_key == self.fmt:
                    return True
            return False
        except Exception as e:
            logger.debug(f"[HLS:{self.channel_id}] Demand check failed: {e}")
            return True

    def _retire(self):
        """No consumers remain: prune expired client-set entries, then hand
        teardown to the server's shared demand accounting so this manager is
        stopped AND deregistered (and the channel shuts down when nothing
        else remains), exactly as a streaming client's disconnect would."""
        try:
            from ...client_manager import ClientManager
            ClientManager.remove_ghost_clients(self._redis, self.channel_id)
        except Exception:
            pass
        try:
            # Import locally: server imports this module at load time. This
            # runs in the manager's own thread; stop() tolerates the resulting
            # self-join (the RuntimeError is caught) and the loop exits right
            # after this call returns.
            from ...server import ProxyServer
            ProxyServer.get_instance().handle_client_disconnect(self.channel_id)
        except Exception as e:
            logger.error(f"[HLS:{self.channel_id}] Error during retirement: {e}")

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

    def _heartbeat_ownership(self):
        """Re-extend the owner lock + state TTL while we still own them; stop the
        loop if another worker has taken over. Called once per stored segment."""
        if not self._redis:
            return
        try:
            owner_key = RedisKeys.output_owner(self.channel_id, self.fmt)
            if self._redis.get(owner_key) == self.worker_id:
                self._redis.expire(owner_key, HLS_KEY_TTL)
                self._redis.expire(RedisKeys.output_state(self.channel_id, self.fmt), HLS_KEY_TTL)
            else:
                logger.info(f"[HLS:{self.channel_id}] Output ownership moved to another worker; stopping")
                self.running = False
        except Exception as e:
            logger.error(f"[HLS:{self.channel_id}] Ownership heartbeat error: {e}")

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
