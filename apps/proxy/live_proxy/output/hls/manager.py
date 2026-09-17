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
from ..buffer import OutputStreamBuffer
from .segmenter import TSSegmenter
from ...redis_keys import RedisKeys
from ...config_helper import ConfigHelper
from ...utils import get_logger

logger = get_logger()

# Output manager states stored in Redis (shared vocabulary with fMP4)
HLS_STATE_INITIALIZING = "initializing"
HLS_STATE_ACTIVE = "active"
HLS_STATE_STOPPED = "stopped"

# Redis TTL for state/playlist keys
HLS_KEY_TTL = 3600
# The owner lock is refreshed every DEMAND_CHECK_INTERVAL, so it can expire
# soon after its holder does. A long-lived lock left behind by a dead worker
# makes ensure_output_format believe the output is still being produced
# elsewhere, and nothing restarts the segmenter until the key finally expires.
HLS_OWNER_TTL = 60

# HLS segmenter knobs (code-level ConfigHelper / TSConfig attrs). Not exposed
# in the DB-backed Proxy Settings UI; add CoreSettings keys later if needed.
DEFAULT_SEGMENT_DURATION = 4
# Target Redis retention depth for finished HLS segments (used to size chunk
# TTL). The advertised playlist window tracks whatever is still in Redis
# (minus a segment about to expire), not this fixed count.
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
        # True only while this instance holds the output owner lock. Redis
        # cleanup is gated on it: if ownership moved to another worker, its
        # playlist and segments live under the same keys and must not be
        # deleted on our way out.
        self._owns_output = False
        self._stopped = False

        self.segment_duration = ConfigHelper.get('HLS_SEGMENT_DURATION', DEFAULT_SEGMENT_DURATION)
        self.window_size = ConfigHelper.get('HLS_WINDOW_SIZE', DEFAULT_WINDOW_SIZE)
        # Frozen EXT-X-TARGETDURATION for this playlist (RFC 8216 6.2.1: MUST
        # NOT change across reloads). Cut target + ~one GOP (~2s) of headroom
        # covers the normal keyframe overrun past the cut threshold. 2x target
        # was also truthful but inflated live latency roughly in proportion.
        self.adv_target = int(self.segment_duration + 2 + 0.999)
        # Preferred client join offset; same setting the segmenter uses when
        # seeding from the input buffer. Frozen for the playlist lifetime so
        # EXT-X-START does not change across reloads (RFC 8216 6.2.1).
        self.start_behind = float(ConfigHelper.new_client_behind_seconds() or 0)

        # Same Redis-backed chunk store other output managers use; it is
        # format-parameterized by design ("adding a new output format only
        # requires a new manager" - redis_keys.py). One HLS segment per
        # chunk; the chunk index doubles as the HLS media sequence number.
        self.segment_buffer = OutputStreamBuffer(
            channel_id, redis_client=RedisClient.get_buffer(), fmt=fmt
        )
        # Size the chunk TTL for post-removal availability (RFC 8216 6.2.2):
        # after a segment rolls off it must stay fetchable for roughly the
        # segment duration plus the longest playlist that contained it. Floor
        # from window_size so retention stays deep enough for stall recovery.
        try:
            self.segment_buffer.chunk_ttl = max(
                self.segment_buffer.chunk_ttl,
                int(self.window_size * (self.segment_duration + 3) + 30),
            )
        except Exception:
            pass
        self._redis = RedisClient.get_client()
        self._window = []
        # EXT-X-DISCONTINUITY tags that have already slid out of the window.
        self._disc_sequence = 0
        # Playlist "ts" is last segment production, not last Redis write, so
        # prune-only republishes do not mask a stalled producer as live.
        self._last_segment_ts = None
        # Seed the rolling window + frozen target from an existing descriptor so
        # a mid-session worker restart/takeover does not clobber the playlist to
        # a fresh window (MEDIA-SEQUENCE must never regress; RFC 8216 6.2.2). The
        # OutputStreamBuffer already restores its chunk index from Redis, so the
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
                    if prior.get("start_behind") is not None:
                        self.start_behind = float(prior["start_behind"])
                    self._disc_sequence = int(prior.get("disc_seq") or 0)
                    if prior.get("ts") is not None:
                        self._last_segment_ts = float(prior["ts"])
                    self._prune_playlist_window()
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

        # __init__ pruned any seeded window in memory only; publish now that we own.
        if self._last_segment_ts is not None:
            self._write_playlist_state()

        short_id = self.channel_id[:8]
        self._thread = threading.Thread(
            target=self._segmenter_loop, daemon=True,
            name=f"hls-seg-{short_id}"
        )
        self._thread.start()

        logger.info(
            f"[HLS:{self.channel_id}] Started "
            f"(target={self.segment_duration}s, redis_ttl={self.segment_buffer.chunk_ttl}s)"
        )
        return True

    def stop(self):
        """Stop the segmenter thread and clean up all Redis keys.

        Also runs when the loop has already exited on its own (ownership loss,
        an unhandled error) so those cases still release the Redis keys and the
        stored segments instead of leaving them to time out.
        """
        if self._stopped:
            return
        self._stopped = True
        self.running = False
        logger.info(f"[HLS:{self.channel_id}] Stopping")

        if self._thread and self._thread.is_alive():
            try:
                self._thread.join(timeout=2)
            except Exception:
                pass

        if self._owns_output:
            self._cleanup_redis()
        else:
            logger.info(
                f"[HLS:{self.channel_id}] Not the output owner; leaving Redis keys "
                f"for the worker that is"
            )
        logger.info(f"[HLS:{self.channel_id}] Stopped")

    # ------------------------------------------------------------------
    # Segmenter loop
    # ------------------------------------------------------------------

    def _segmenter_loop(self):
        """Read TS chunks from Redis and feed them through the segmenter."""
        segmenter = TSSegmenter(
            target_duration=self.segment_duration,
            max_segment_duration=self.adv_target,
        )
        if self._window:
            # Seeded from a previous owner's descriptor: our first segment
            # continues its media sequence but not its byte stream or its PTS
            # timeline, so it has to be tagged (RFC 8216 4.3.2.3).
            segmenter.flag_discontinuity()

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
                now = time.time()
                if now - last_demand_check >= DEMAND_CHECK_INTERVAL:
                    last_demand_check = now
                    # On the timer rather than per segment so the lock is also
                    # renewed while the input is stalled and no segments are
                    # being produced.
                    self._heartbeat_ownership()
                    if not self.running:
                        break
                    # Drop expired advertised URIs while the input is stalled.
                    if self._prune_playlist_window() and self._last_segment_ts is not None:
                        self._write_playlist_state()
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
                            if not self.running:
                                break
                            # A client tuned in while we were deciding: the
                            # server's authoritative accounting saw it and
                            # kept this manager alive, so keep segmenting
                            # for the newcomer instead of exiting and
                            # leaving a registered manager with a dead loop.
                            logger.info(
                                f"[HLS:{self.channel_id}] New {self.fmt} client "
                                f"arrived during retirement; resuming"
                            )
                            idle_demand_checks = 0

                chunks, new_index = self.ts_buffer.get_optimized_client_data(local_index)

                if chunks:
                    # Chunks are local_index+1 .. local_index+len(chunks) when
                    # nothing has expired (same assumption as the buffer reader).
                    # Advance by what we actually feed so a discontinuity cut
                    # lands on the real boundary, not a padded new_index.
                    end_index = local_index + len(chunks)
                    disc_at = set(
                        self.ts_buffer.discontinuities_in_range(
                            local_index, end_index
                        )
                    )
                    chunk_index = local_index
                    for chunk in chunks:
                        if not self.running:
                            break
                        chunk_index += 1
                        if chunk_index in disc_at:
                            self._cut_for_discontinuity(
                                segmenter,
                                reason=f"buffer index {chunk_index}",
                            )
                        for segment in segmenter.feed(chunk):
                            self._store_segment(segment)
                            if not first_segment_stored:
                                first_segment_stored = True
                                self._set_state(HLS_STATE_ACTIVE)
                                logger.info(
                                    f"[HLS:{self.channel_id}] First segment stored "
                                    f"({segment.duration:.2f}s, {len(segment.data)} bytes)"
                                )
                    local_index = chunk_index
                else:
                    if self.ts_buffer.index > local_index + 20:
                        # Fell too far behind (slow consumer / provider burst):
                        # skip forward and mark the gap for the playlist. The
                        # open segment is hard-cut so pre-gap and post-gap
                        # data never share a segment.
                        local_index = self.ts_buffer.index - 5
                        self._cut_for_discontinuity(segmenter, reason="buffer skip-ahead")
                        logger.debug(
                            f"[HLS:{self.channel_id}] Skipped forward to index {local_index}"
                        )
                    time.sleep(0.05)

        except Exception as e:
            logger.error(f"[HLS:{self.channel_id}] Segmenter loop error: {e}", exc_info=True)
        finally:
            logger.debug(f"[HLS:{self.channel_id}] Segmenter loop exited")

    def _cut_for_discontinuity(self, segmenter, reason=""):
        """Hard-cut the open segment; the next started segment is tagged."""
        tail = segmenter.flag_discontinuity()
        if tail is not None:
            self._store_segment(tail)
        logger.debug(
            f"[HLS:{self.channel_id}] Discontinuity cut"
            f"{f' ({reason})' if reason else ''}; next segment will be marked"
        )

    def _prune_playlist_window(self):
        """Align the advertised window with segments still in Redis (RFC 8216 6.2.2).

        Returns True when the window or discontinuity sequence changed.
        """
        before = (len(self._window), self._disc_sequence,
                  self._window[0]["seq"] if self._window else None)
        scores = {}
        try:
            scores = self.segment_buffer.surviving_chunk_scores()
        except Exception:
            scores = {}
        if not scores:
            # Lookup failed: cap growth so _window cannot run away while
            # put_chunk() still succeeds. Normal path is the TTL prune below.
            max_entries = int(self.segment_buffer.chunk_ttl / max(self.segment_duration, 1)) + 5
            changed = False
            while len(self._window) > max_entries:
                if self._window.pop(0).get("disc"):
                    self._disc_sequence += 1
                changed = True
            return changed

        live = set(scores)
        # Prefix-only: mid-window holes would corrupt DISCONTINUITY-SEQUENCE.
        while self._window and self._window[0]["seq"] not in live:
            if self._window.pop(0).get("disc"):
                self._disc_sequence += 1

        # Omit leading chunks within one segment of TTL expiry; keep a sole entry.
        now = time.time()
        while len(self._window) > 1:
            written_at = scores[self._window[0]["seq"]]
            remaining = self.segment_buffer.chunk_ttl - (now - written_at)
            if remaining >= self.segment_duration:
                break
            if self._window.pop(0).get("disc"):
                self._disc_sequence += 1

        after = (len(self._window), self._disc_sequence,
                 self._window[0]["seq"] if self._window else None)
        return after != before

    def _write_playlist_state(self):
        """Publish the current window descriptor to Redis."""
        if not self._redis:
            return
        try:
            playlist_state = {
                "window": self._window,
                "target": self.segment_duration,
                "adv_target": self.adv_target,
                "start_behind": self.start_behind,
                "disc_seq": self._disc_sequence,
                "ts": self._last_segment_ts if self._last_segment_ts is not None else time.time(),
            }
            self._redis.setex(
                RedisKeys.output_playlist(self.channel_id, self.fmt),
                HLS_KEY_TTL,
                json.dumps(playlist_state),
            )
        except Exception as e:
            logger.error(f"[HLS:{self.channel_id}] Error updating playlist state: {e}")

    def _store_segment(self, segment):
        """Store one finished segment and refresh the playlist descriptor."""
        if not self.segment_buffer.put_chunk(segment.data):
            return
        seq = self.segment_buffer.index
        self._window.append({
            "seq": seq,
            "dur": round(segment.duration, 3),
            "disc": bool(segment.discontinuity),
        })
        self._last_segment_ts = time.time()
        self._prune_playlist_window()
        self._write_playlist_state()

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
        else remains), exactly as a streaming client's disconnect would.

        The server is the arbiter: if a client tuned in between our demand
        check and this call, the accounting keeps the manager registered and
        does NOT stop it; the caller must then keep the loop running
        (self.running stays True) rather than exit."""
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
            self._owns_output = True
            return True
        owner_key = RedisKeys.output_owner(self.channel_id, self.fmt)
        acquired = self._redis.set(owner_key, self.worker_id, nx=True, ex=HLS_OWNER_TTL)
        if not acquired and self._redis.get(owner_key) != self.worker_id:
            return False
        self._owns_output = True
        return True

    def _set_state(self, state: str):
        if self._redis:
            self._redis.setex(RedisKeys.output_state(self.channel_id, self.fmt), HLS_KEY_TTL, state)

    def _heartbeat_ownership(self):
        """Re-extend the owner lock + state TTL while we still own them; stop the
        loop if another worker has taken over.

        Without this, a stream outliving the key TTL would silently lose mutual
        exclusion and let a second worker start a duplicate segmenter, breaking
        MEDIA-SEQUENCE monotonicity.
        """
        if not self._redis:
            return
        try:
            owner_key = RedisKeys.output_owner(self.channel_id, self.fmt)
            if self._redis.get(owner_key) == self.worker_id:
                self._redis.expire(owner_key, HLS_OWNER_TTL)
                self._redis.expire(RedisKeys.output_state(self.channel_id, self.fmt), HLS_KEY_TTL)
            else:
                logger.info(f"[HLS:{self.channel_id}] Output ownership moved to another worker; stopping")
                self._owns_output = False
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
