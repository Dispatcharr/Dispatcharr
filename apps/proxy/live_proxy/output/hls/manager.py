"""
HLS Output Manager

Feeds the shared TS Redis ring through ffmpeg's segment muxer (container
copy, no transcode) to cut keyframe-aligned TS segments, stores one segment
per Redis chunk via the shared format-parameterized output buffer, and
maintains a rolling live playlist descriptor in Redis that the playlist
view renders per request.

Mirrors the fMP4 remux manager's stdin/stdout process lifecycle: a writer
thread pipes ring chunks to ffmpeg stdin, and ffmpeg reports every finished
segment on stdout through its segment-list journal (one CSV line per
segment, carrying the measured start/end times). Segment files land in a
private scratch directory just long enough to be moved into Redis.

Playlist generation stays in our code (playlist.py) so the proxy controls
EXT-X-TARGETDURATION, the media sequence, and discontinuity tagging,
including when the writer skips ahead in the source ring or ffmpeg is
restarted across a source hiccup.

One instance per channel per cluster - coordinated via the shared
output:{fmt}:owner lock, exactly like the fMP4 remux manager.
"""

import json
import os
import select
import shutil
import tempfile
import threading
import time

from core.utils import RedisClient
from ..fmp4.buffer import FMP4StreamBuffer
from .playlist import parse_segment_list_line
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

# Consecutive ffmpeg sessions that produce zero segments before the manager
# gives up instead of spinning a crash loop on undecodable input.
MAX_BARREN_SESSIONS = 3

# Scratch files older than this are swept as orphans (an ingest that failed
# mid-way); ffmpeg itself never keeps more than the in-progress segment open.
SCRATCH_STALE_SECONDS = 60


def _ffmpeg_segment_cmd(segment_duration, out_pattern):
    """
    ffmpeg command for container-only segmenting: TS in on stdin,
    keyframe-aligned TS segments out, no transcode. ffmpeg owns keyframe
    detection, PTS wrap handling, and multi-packet PSI reassembly; the
    segment-list journal on stdout is our completion signal, one CSV line
    (filename,start,end) per finished segment, which also gives a measured
    EXTINF without any TS parsing on our side. segment_list_size 1 caps each
    journal write to the newest entry so the pipe payload stays constant
    over arbitrarily long sessions.
    """
    return [
        "ffmpeg",
        "-loglevel", "error",
        "-f", "mpegts",
        "-i", "pipe:0",
        "-c", "copy",
        "-map", "0",
        "-f", "segment",
        "-segment_format", "mpegts",
        "-segment_time", str(segment_duration),
        "-segment_list", "pipe:1",
        "-segment_list_type", "csv",
        "-segment_list_size", "1",
        out_pattern,
    ]


class HLSOutputManager:
    """
    Reads the TS Redis buffer for a channel, cuts keyframe-aligned HLS
    segments via ffmpeg, and publishes them plus a rolling playlist window
    to Redis.
    """

    def __init__(self, channel_id, ts_buffer, worker_id, fmt='hls'):
        self.channel_id = channel_id
        self.ts_buffer = ts_buffer
        self.worker_id = worker_id
        self.fmt = fmt
        self.running = False
        self._thread = None
        self._process = None
        self._writer_thread = None
        self._stderr_thread = None
        self._scratch_dir = None
        self._session_counter = 0
        self._session_ending = False
        # Next published segment follows a gap (session restart or ring
        # skip-ahead) and must carry EXT-X-DISCONTINUITY.
        self._pending_disc = False
        # Watchdog bookkeeping: stdin bytes fed since the last finished
        # segment, when that segment finished, and when input last flowed.
        self._bytes_since_segment = 0
        self._last_segment_time = 0.0
        self._last_write_time = 0.0
        self._ring_index = None

        self.segment_duration = ConfigHelper.get('HLS_SEGMENT_DURATION', DEFAULT_SEGMENT_DURATION)
        self.window_size = ConfigHelper.get('HLS_WINDOW_SIZE', DEFAULT_WINDOW_SIZE)
        # Advertised EXT-X-TARGETDURATION, computed ONCE and frozen for the life
        # of the playlist (RFC 8216 6.2.1: it MUST NOT change across reloads;
        # AVPlayer latches it at first parse and revalidates every reload).
        # ffmpeg's segment muxer cuts at the first keyframe at or after the
        # target, so 2x the target covers any keyframe cadence up to one full
        # target duration; a source with a longer GOP than that is logged when
        # it breaches the advertised value.
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
        """Acquire the output owner lock and spawn the session supervisor."""
        if not self._acquire_owner_lock():
            logger.info(f"[HLS:{self.channel_id}] Another worker owns HLS output, skipping start")
            return False

        self.running = True
        self._set_state(HLS_STATE_INITIALIZING)
        self._scratch_dir = tempfile.mkdtemp(prefix=f"dispatcharr-hls-{self.channel_id[:8]}-")

        # Start behind live so the first segments cover the same window a
        # new TS client would receive, matching fMP4 writer positioning.
        behind_seconds = ConfigHelper.new_client_behind_seconds()
        start_index = self.ts_buffer.find_chunk_index_by_time(behind_seconds) if behind_seconds > 0 else None
        if start_index is None:
            start_index = self.ts_buffer.index
        self._ring_index = start_index

        short_id = self.channel_id[:8]
        self._thread = threading.Thread(
            target=self._supervisor_loop, daemon=True,
            name=f"hls-seg-{short_id}"
        )
        self._thread.start()

        logger.info(
            f"[HLS:{self.channel_id}] Started "
            f"(target={self.segment_duration}s, window={self.window_size}, "
            f"ring index {start_index}, {behind_seconds}s behind live)"
        )
        return True

    def stop(self):
        """Stop the ffmpeg session and clean up all Redis keys."""
        if not self.running:
            return
        self.running = False
        self._session_ending = True
        logger.info(f"[HLS:{self.channel_id}] Stopping")

        # Close ffmpeg stdin - signals EOF so it flushes and exits cleanly
        try:
            if self._process and self._process.stdin:
                self._process.stdin.close()
        except Exception:
            pass

        if self._thread and self._thread.is_alive():
            try:
                self._thread.join(timeout=10)
            except Exception:
                pass

        # Kill ffmpeg if still running
        try:
            if self._process and self._process.poll() is None:
                self._process.kill()
                self._process.wait(timeout=3)
        except Exception:
            pass

        self._cleanup_redis()
        if self._scratch_dir:
            shutil.rmtree(self._scratch_dir, ignore_errors=True)
        logger.info(f"[HLS:{self.channel_id}] Stopped")

    # ------------------------------------------------------------------
    # Session supervisor
    # ------------------------------------------------------------------

    def _supervisor_loop(self):
        """
        Run ffmpeg sessions back to back while the manager is alive. A session
        ends when ffmpeg exits (EOF, source garbage, crash) or the reader's
        no-progress watchdog fires; the next session picks up at the current
        ring position and the first segment it produces is tagged as a
        discontinuity, since the output timeline has a gap.
        """
        barren_sessions = 0
        try:
            while self.running:
                produced = self._run_ffmpeg_session()
                if not self.running:
                    break
                self._pending_disc = True
                if produced == 0:
                    barren_sessions += 1
                    if barren_sessions >= MAX_BARREN_SESSIONS:
                        logger.error(
                            f"[HLS:{self.channel_id}] {barren_sessions} consecutive ffmpeg "
                            f"sessions produced no segments, giving up"
                        )
                        # Polling clients get a clean 410 instead of endless 503s.
                        self._set_state(HLS_STATE_STOPPED)
                        break
                else:
                    barren_sessions = 0
                logger.info(f"[HLS:{self.channel_id}] Restarting ffmpeg session")
                time.sleep(1.0)
        except Exception as e:
            logger.error(f"[HLS:{self.channel_id}] Supervisor error: {e}", exc_info=True)
        finally:
            logger.debug(f"[HLS:{self.channel_id}] Supervisor exited")

    def _run_ffmpeg_session(self):
        """Spawn one ffmpeg process and pump it until it ends. Returns the
        number of segments the session produced."""
        self._session_counter += 1
        self._session_ending = False
        self._bytes_since_segment = 0
        self._last_segment_time = time.time()

        # Per-session filename prefix: ffmpeg restarts its output numbering at
        # zero every session, and the completion journal is deduplicated by
        # filename, so names must never repeat across sessions.
        pattern = os.path.join(self._scratch_dir, f"s{self._session_counter:03d}-%06d.ts")

        from ...utils import posix_spawn_proc
        self._process = posix_spawn_proc(_ffmpeg_segment_cmd(self.segment_duration, pattern))
        process = self._process
        logger.info(
            f"[HLS:{self.channel_id}] ffmpeg session {self._session_counter} "
            f"started (pid={process.pid})"
        )

        short_id = self.channel_id[:8]
        self._writer_thread = threading.Thread(
            target=self._writer_loop, args=(process,), daemon=True,
            name=f"hls-writer-{short_id}"
        )
        self._stderr_thread = threading.Thread(
            target=self._stderr_loop, args=(process,), daemon=True,
            name=f"hls-stderr-{short_id}"
        )
        self._writer_thread.start()
        self._stderr_thread.start()

        produced = self._reader_loop(process)

        # Wind the session down: stop the writer, then the process.
        self._session_ending = True
        try:
            if process.stdin:
                process.stdin.close()
        except Exception:
            pass
        if self._writer_thread.is_alive():
            try:
                self._writer_thread.join(timeout=5)
            except Exception:
                pass
        try:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=3)
        except Exception:
            pass
        self._sweep_scratch(all_files=True)
        return produced

    # ------------------------------------------------------------------
    # Pump loops (per ffmpeg session)
    # ------------------------------------------------------------------

    def _write_all(self, process, data):
        """Write all bytes to ffmpeg stdin, looping on partial writes."""
        view = memoryview(data)
        offset = 0
        total = len(view)
        while offset < total:
            if not self.running or self._session_ending:
                return
            n = process.stdin.write(view[offset:])
            if n is None:
                # Pipe full (EAGAIN on non-blocking FD); yield cooperatively
                select.select([], [process.stdin], [], 1.0)
            elif n <= 0:
                raise OSError("stdin write returned no bytes")
            else:
                offset += n

    def _writer_loop(self, process):
        """Read TS chunks from the ring and write them to ffmpeg stdin."""
        logger.debug(f"[HLS:{self.channel_id}] Writer started at ring index {self._ring_index}")
        try:
            while self.running and not self._session_ending:
                chunks, new_index = self.ts_buffer.get_optimized_client_data(self._ring_index)

                if chunks:
                    self._ring_index = new_index
                    for chunk in chunks:
                        if not self.running or self._session_ending:
                            break
                        try:
                            self._write_all(process, chunk)
                            process.stdin.flush()
                            self._bytes_since_segment += len(chunk)
                            self._last_write_time = time.time()
                        except (BrokenPipeError, OSError) as e:
                            logger.warning(f"[HLS:{self.channel_id}] ffmpeg stdin error: {e}")
                            return
                else:
                    if self.ts_buffer.index > self._ring_index + 20:
                        # Fell too far behind (slow consumer / provider burst):
                        # skip forward and mark the gap for the playlist.
                        self._ring_index = self.ts_buffer.index - 5
                        self._pending_disc = True
                        logger.debug(
                            f"[HLS:{self.channel_id}] Skipped forward to ring index {self._ring_index}"
                        )
                    time.sleep(0.05)
        except Exception as e:
            logger.error(f"[HLS:{self.channel_id}] Writer loop error: {e}", exc_info=True)
        finally:
            try:
                if process.stdin:
                    process.stdin.close()
            except Exception:
                pass
            logger.debug(f"[HLS:{self.channel_id}] Writer loop exited")

    def _reader_loop(self, process):
        """
        Consume the segment-list journal on ffmpeg stdout. Every complete
        line is one finished segment: ingest the file into Redis, publish
        the playlist descriptor, and delete the file. Returns the number of
        segments ingested this session.
        """
        buf = b""
        produced = 0
        ingested = set()
        first_segment_stored = False
        # If ffmpeg keeps eating input but finishes nothing for this long, its
        # mux state is treated as wedged (e.g. a backwards PTS jump the copy
        # path cannot recover from) and the session is restarted.
        watchdog_limit = max(3 * self.segment_duration + 5, 15)

        try:
            while self.running:
                ready, _, _ = select.select([process.stdout], [], [], 1.0)
                if not ready:
                    if process.poll() is not None:
                        logger.info(
                            f"[HLS:{self.channel_id}] ffmpeg exited (code={process.returncode})"
                        )
                        break
                    now = time.time()
                    if (
                        now - self._last_segment_time > watchdog_limit
                        and self._bytes_since_segment > 512 * 1024
                        and now - self._last_write_time < 2.0
                    ):
                        # Input is actively flowing but nothing completes: the
                        # mux state is wedged. A dried-up source (last write is
                        # old) is NOT a wedge; then we just wait, like the TS path.
                        logger.warning(
                            f"[HLS:{self.channel_id}] No finished segment in {watchdog_limit}s "
                            f"despite {self._bytes_since_segment} bytes of input; restarting ffmpeg"
                        )
                        break
                    continue

                data = process.stdout.read(4096)
                if not data:
                    logger.info(f"[HLS:{self.channel_id}] ffmpeg journal EOF")
                    break
                buf += data

                while b"\n" in buf:
                    line_bytes, buf = buf.split(b"\n", 1)
                    line = line_bytes.decode(errors="replace").strip()
                    if not line:
                        continue
                    try:
                        name, start, end = parse_segment_list_line(line)
                    except ValueError:
                        logger.warning(f"[HLS:{self.channel_id}] Unparseable journal line: {line!r}")
                        continue
                    if name in ingested:
                        continue
                    ingested.add(name)
                    # The journal reports segment basenames; files live in the
                    # manager's scratch directory.
                    path = os.path.join(self._scratch_dir, os.path.basename(name))
                    duration = end - start
                    if self._ingest_segment(path, duration):
                        produced += 1
                        self._bytes_since_segment = 0
                        self._last_segment_time = time.time()
                        if not first_segment_stored:
                            first_segment_stored = True
                            self._set_state(HLS_STATE_ACTIVE)
                            logger.info(
                                f"[HLS:{self.channel_id}] First segment stored ({duration:.2f}s)"
                            )
                    self._sweep_scratch()
        except Exception as e:
            logger.error(f"[HLS:{self.channel_id}] Reader loop error: {e}", exc_info=True)
        finally:
            logger.debug(f"[HLS:{self.channel_id}] Reader loop exited ({produced} segments)")
        return produced

    def _stderr_loop(self, process):
        """Log ffmpeg stderr lines."""
        try:
            stderr_fd = process.stderr.fileno()
            buf = b""
            while self.running and not self._session_ending:
                ready, _, _ = select.select([stderr_fd], [], [], 1.0)
                if not ready:
                    if process.poll() is not None:
                        break
                    continue
                chunk = os.read(stderr_fd, 4096)
                if not chunk:
                    break
                buf += chunk
                while b"\n" in buf:
                    line_bytes, buf = buf.split(b"\n", 1)
                    line = line_bytes.decode(errors="replace").rstrip()
                    if line:
                        logger.warning(f"[HLS:{self.channel_id}] ffmpeg: {line}")
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Segment ingest
    # ------------------------------------------------------------------

    def _ingest_segment(self, path, duration):
        """Move one finished segment file into Redis and refresh the playlist
        descriptor. Returns True when the segment was stored."""
        try:
            with open(path, "rb") as fh:
                data = fh.read()
        except OSError as e:
            logger.warning(f"[HLS:{self.channel_id}] Cannot read segment {path}: {e}")
            return False
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass

        if not data:
            logger.warning(f"[HLS:{self.channel_id}] Empty segment file {path}, skipping")
            return False

        # The journal's times are authoritative (measured by ffmpeg); fall back
        # to the nominal target only when they are unusable.
        if duration <= 0 or duration > 4 * self.segment_duration:
            duration = float(self.segment_duration)
        if duration > self.adv_target:
            logger.warning(
                f"[HLS:{self.channel_id}] Segment of {duration:.2f}s exceeds the frozen "
                f"TARGETDURATION {self.adv_target} (source GOP longer than {self.segment_duration}s)"
            )

        if not self.segment_buffer.put_fragment(data):
            return False
        seq = self.segment_buffer.index
        self._window.append({
            "seq": seq,
            "dur": round(duration, 3),
            "disc": bool(self._pending_disc),
        })
        self._pending_disc = False
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
            f"{duration:.2f}s, {len(data)} bytes"
        )
        return True

    def _sweep_scratch(self, all_files=False):
        """Remove scratch files: everything on session teardown, otherwise only
        orphans old enough that no ingest can still want them."""
        if not self._scratch_dir:
            return
        cutoff = time.time() - SCRATCH_STALE_SECONDS
        try:
            with os.scandir(self._scratch_dir) as entries:
                for entry in entries:
                    try:
                        if all_files or entry.stat().st_mtime < cutoff:
                            os.unlink(entry.path)
                    except OSError:
                        pass
        except OSError:
            pass

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
