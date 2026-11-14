"""
Output Profile Transcode Manager

Reads from the shared TS Redis buffer, pipes data through a user-defined
transcoding command (pipe:0 stdin → pipe:1 stdout), and writes the output
chunks to a Redis-backed StreamBuffer under:

    live:channel:{channel_id}:output:mpegts:p{profile_id}:buffer:*

One transcode process runs per active (channel, profile) pair across the
entire cluster. The TS-owning worker starts the process; non-owning workers
create a read-only StreamBuffer pointing at the same Redis keys.

A long-running FFmpeg does not rewrite its output PMT when the codecs of its
input change mid-stream, so the process is replaced at the exact boundary where
the input PMT/ES layout changes or the input buffer marks a source
discontinuity. The old process gets a short, bounded window to finish what it
already holds; the replacement then starts on the new data and emits a fresh
PAT/PMT.
"""

import logging
import os
import select
import threading
import time
from core.utils import RedisClient
from ...input.buffer import StreamBuffer
from ...redis_keys import RedisKeys
from ...config_helper import ConfigHelper
from ...utils import get_logger
from ..pipe_restart import (
    ProcessSlot,
    RestartOutcome,
    replace_piped_process,
    write_all,
)
from ..ts_feed import feed_chunk_with_layout_watch, run_ts_buffer_writer
from ..ts_pmt import PmtLayoutWatcher

logger = get_logger()

PROFILE_STATE_ACTIVE = "active"
PROFILE_STATE_STOPPED = "stopped"

# Orphan backstop TTL; refreshed while the transcode is alive, deleted on stop.
PROFILE_KEY_TTL = 3600
PROFILE_TTL_REFRESH_INTERVAL = 60


class OutputProfileManager:
    """
    Reads the TS Redis buffer for a channel, transcodes via a user-supplied
    command, and writes output chunks into a profile-namespaced StreamBuffer.
    """

    def __init__(self, channel_id, profile_id, command, ts_buffer, worker_id):
        """
        Args:
            channel_id: Channel UUID string.
            profile_id: OutputProfile PK (int).
            command: List from OutputProfile.build_command().
            ts_buffer: Source StreamBuffer (the channel's raw TS input buffer).
            worker_id: This worker's ID string for owner-lock coordination.
        """
        self.channel_id = channel_id
        self.profile_id = profile_id
        self.command = command
        self.ts_buffer = ts_buffer
        self.worker_id = worker_id
        self.running = False
        # Always the live process: the server treats a dead _process as a
        # crashed profile, so restarts swap it only after the replacement spawns.
        self._process = None
        self._slot = None
        self._writer_thread = None
        self._reader_thread = None
        self._stderr_thread = None
        self._redis = RedisClient.get_client()
        self.output_buffer = None  # assigned in start()
        self._last_ttl_refresh = 0.0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> bool:
        """
        Acquire the owner lock, spawn the transcode process and threads.
        Returns True if this worker started the process, False if another
        worker already owns it (caller should still use output_buffer for reads).
        """
        logger.debug(
            f"[Profile:{self.profile_id}:{self.channel_id[:8]}] start() called"
        )
        if not self._acquire_owner_lock():
            logger.info(
                f"[Profile:{self.profile_id}:{self.channel_id[:8]}] "
                "Another worker owns transcode, using shared buffer"
            )
            self.output_buffer = self._make_buffer()
            return False

        self.output_buffer = self._make_buffer()

        try:
            from ...utils import posix_spawn_proc
            self._process = posix_spawn_proc(self.command)
        except (FileNotFoundError, OSError) as e:
            logger.error(
                f"[Profile:{self.profile_id}:{self.channel_id[:8]}] "
                f"Failed to start transcode process: {e}"
            )
            self._release_owner_lock()
            return False

        self._slot = ProcessSlot(self._process)
        self.running = True
        self._set_state(PROFILE_STATE_ACTIVE)

        short = f"{self.channel_id[:8]}:p{self.profile_id}"
        self._writer_thread = threading.Thread(
            target=self._writer_loop, daemon=True,
            name=f"profile-writer-{short}"
        )
        self._start_slot_threads(self._slot)
        self._writer_thread.start()

        logger.info(
            f"[Profile:{self.profile_id}:{self.channel_id[:8]}] "
            f"Transcode started (pid={self._process.pid})"
        )
        return True

    def stop(self):
        """Stop the transcode process and clean up all Redis keys."""
        if not self.running:
            return
        self.running = False
        logger.info(
            f"[Profile:{self.profile_id}:{self.channel_id[:8]}] Stopping transcode"
        )

        try:
            if self._process and self._process.stdin:
                self._process.stdin.close()
        except Exception:
            pass

        for t in (self._writer_thread, self._reader_thread):
            if t and t.is_alive():
                try:
                    t.join(timeout=5)
                except Exception:
                    pass

        try:
            if self._process and self._process.poll() is None:
                self._process.kill()
                self._process.wait(timeout=3)
        except Exception:
            pass

        self._cleanup_redis()
        logger.info(
            f"[Profile:{self.profile_id}:{self.channel_id[:8]}] Transcode stopped"
        )

    # ------------------------------------------------------------------
    # Internal threads
    # ------------------------------------------------------------------

    def _start_slot_threads(self, slot):
        """Start the stdout/stderr consumers bound to one process slot."""
        short = f"{self.channel_id[:8]}:p{self.profile_id}"
        slot.reader = threading.Thread(
            target=self._reader_loop, args=(slot,), daemon=True,
            name=f"profile-reader-{short}"
        )
        slot.stderr = threading.Thread(
            target=self._stderr_loop, args=(slot,), daemon=True,
            name=f"profile-stderr-{short}"
        )
        self._reader_thread = slot.reader
        self._stderr_thread = slot.stderr
        slot.reader.start()
        slot.stderr.start()

    def _write_stdin(self, data: bytes) -> bool:
        """Write to the current process. Returns False when the writer must stop."""
        try:
            write_all(self._process, data, is_running=lambda: self.running)
            self._process.stdin.flush()
        except (BrokenPipeError, OSError) as e:
            logger.warning(
                f"[Profile:{self.profile_id}:{self.channel_id[:8]}] "
                f"Stdin error: {e}"
            )
            self.running = False
            return False
        return True

    def _writer_loop(self):
        """Read TS chunks from Redis and write to the transcode process stdin."""
        behind_seconds = ConfigHelper.new_client_behind_seconds()
        watcher = PmtLayoutWatcher(
            scan_cache=getattr(self.ts_buffer, "psi_scan_cache", None)
        )
        label = f"[Profile:{self.profile_id}:{self.channel_id[:8]}]"

        try:
            run_ts_buffer_writer(
                is_running=lambda: self.running,
                ts_buffer=self.ts_buffer,
                behind_seconds=behind_seconds,
                watcher=watcher,
                feed_chunk=lambda data, watcher, chunk_index=None: (
                    feed_chunk_with_layout_watch(
                        data, watcher, self._write_stdin,
                        self._restart_transcode, chunk_index,
                    )
                ),
                on_discontinuity=lambda reason: self._restart_transcode(reason=reason),
                log_debug=lambda msg: logger.debug(f"{label} {msg}"),
            )
        except Exception as e:
            logger.error(f"{label} Writer loop error: {e}", exc_info=True)
        finally:
            try:
                if self._process and self._process.stdin:
                    self._process.stdin.close()
            except Exception:
                pass
            logger.debug(f"{label} Writer loop exited")

    def _restart_transcode(self, reason: str, flush: bytes = b"") -> RestartOutcome:
        """Replace the transcode process at a stream boundary.

        Runs on the writer thread, the only thread that writes stdin. See
        ``replace_piped_process`` for the spawn/drain/retire contract.
        """
        if not self.running or self._slot is None:
            return RestartOutcome.STOP

        short = f"{self.channel_id[:8]}"
        label = f"[Profile:{self.profile_id}:{short}]"

        def spawn():
            from ...utils import posix_spawn_proc
            return posix_spawn_proc(self.command)

        def set_current(process, slot):
            self._process = process
            self._slot = slot

        def after_old_retired():
            if self.output_buffer:
                try:
                    self.output_buffer.mark_discontinuity()
                except Exception as e:
                    logger.warning(f"{label} Failed to mark output discontinuity: {e}")

        outcome = replace_piped_process(
            is_running=lambda: self.running,
            current_slot=self._slot,
            spawn=spawn,
            set_current=set_current,
            start_slot_threads=self._start_slot_threads,
            after_old_retired=after_old_retired,
            flush=flush,
            log_warning=lambda msg: logger.warning(f"{label} {msg}"),
            log_error=lambda msg: logger.error(f"{label} {msg}"),
            log_info=lambda msg: logger.info(f"{label} {msg}"),
            reason=reason,
            noun="transcode",
        )
        if outcome == RestartOutcome.STOP and self.running:
            # Dead process, or the pre-boundary flush could not be written.
            # stop() during the swap has already cleared running.
            self.running = False
        return outcome

    def _reader_loop(self, slot):
        """Read chunks from process stdout and write to the output StreamBuffer."""
        read_size = 65536
        process = slot.process
        logger.debug(
            f"[Profile:{self.profile_id}:{self.channel_id[:8]}] Reader started"
        )

        try:
            while self.running and not slot.abandoned.is_set():
                self._refresh_redis_ttls()
                ready, _, _ = select.select([process.stdout], [], [], 1.0)
                if not ready:
                    if process.poll() is not None:
                        logger.info(
                            f"[Profile:{self.profile_id}:{self.channel_id[:8]}] "
                            f"Process exited (code={process.returncode})"
                        )
                        break
                    continue

                # FileIO.read returns None on EAGAIN. It does not raise. b"" is EOF.
                # Treating None as EOF would drop the output on a stale select.
                data = process.stdout.read(read_size)
                if data is None:
                    continue
                if not data:
                    logger.log(
                        logging.DEBUG if slot.closing.is_set() else logging.INFO,
                        f"[Profile:{self.profile_id}:{self.channel_id[:8]}] stdout EOF"
                    )
                    break

                if slot.abandoned.is_set():
                    break  # retired between select and this check
                self.output_buffer.add_chunk(data)

        except Exception as e:
            logger.error(
                f"[Profile:{self.profile_id}:{self.channel_id[:8]}] "
                f"Reader loop error: {e}", exc_info=True
            )
        finally:
            # EOF after an intentional stdin close is a restart, not the end of
            # the stream: the shared output ring lives on for the replacement.
            if self.output_buffer and not slot.closing.is_set():
                self.output_buffer.stop()
            logger.info(
                f"[Profile:{self.profile_id}:{self.channel_id[:8]}] Reader loop exited"
            )

    def _stderr_loop(self, slot):
        """Log process stderr at WARNING level."""
        process = slot.process
        try:
            stderr_fd = process.stderr.fileno()
            buf = b""
            while self.running and not slot.abandoned.is_set():
                ready, _, _ = select.select([stderr_fd], [], [], 1.0)
                if not ready:
                    if process.poll() is not None:
                        break
                    continue
                try:
                    chunk = os.read(stderr_fd, 4096)
                except BlockingIOError:
                    continue
                if not chunk:
                    break
                buf += chunk
                while b'\n' in buf:
                    line_bytes, buf = buf.split(b'\n', 1)
                    line = line_bytes.decode(errors="replace").rstrip()
                    if line:
                        logger.warning(
                            f"[Profile:{self.profile_id}:{self.channel_id[:8]}] {line}"
                        )
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Redis helpers
    # ------------------------------------------------------------------

    def _profile_fmt(self) -> str:
        return f"mpegts:p{self.profile_id}"

    def _make_buffer(self) -> StreamBuffer:
        """Create a StreamBuffer wired to this profile's Redis key namespace."""
        fmt = self._profile_fmt()
        return StreamBuffer(
            channel_id=self.channel_id,
            redis_client=RedisClient.get_buffer(),
            buffer_index_key=RedisKeys.output_buffer_index(self.channel_id, fmt),
            buffer_chunk_prefix=RedisKeys.output_buffer_chunk_prefix(self.channel_id, fmt),
            chunk_timestamps_key=RedisKeys.output_chunk_timestamps(self.channel_id, fmt),
            discontinuities_key=RedisKeys.output_buffer_discontinuities(
                self.channel_id, fmt
            ),
        )

    def _acquire_owner_lock(self) -> bool:
        if not self._redis:
            return True
        owner_key = RedisKeys.output_owner(self.channel_id, self._profile_fmt())
        acquired = self._redis.set(owner_key, self.worker_id, nx=True, ex=PROFILE_KEY_TTL)
        if acquired:
            return True
        existing = self._redis.get(owner_key)
        return existing == self.worker_id

    def _release_owner_lock(self):
        if self._redis:
            try:
                self._redis.delete(RedisKeys.output_owner(self.channel_id, self._profile_fmt()))
            except Exception:
                pass

    def _set_state(self, state: str):
        if self._redis:
            self._redis.setex(
                RedisKeys.output_state(self.channel_id, self._profile_fmt()),
                PROFILE_KEY_TTL,
                state,
            )

    def _refresh_redis_ttls(self):
        """Extend orphan-backstop TTLs while this transcode is alive.

        Rate-limited so long sessions keep owner/state without per-chunk Redis chatter.
        """
        now = time.time()
        if now - self._last_ttl_refresh < PROFILE_TTL_REFRESH_INTERVAL:
            return
        self._last_ttl_refresh = now
        if not self._redis:
            return
        try:
            fmt = self._profile_fmt()
            pipe = self._redis.pipeline()
            pipe.expire(RedisKeys.output_owner(self.channel_id, fmt), PROFILE_KEY_TTL)
            pipe.expire(RedisKeys.output_state(self.channel_id, fmt), PROFILE_KEY_TTL)
            pipe.execute()
        except Exception as e:
            logger.debug(
                f"[Profile:{self.profile_id}:{self.channel_id[:8]}] "
                f"TTL refresh failed: {e}"
            )

    def _cleanup_redis(self):
        """Delete all output:mpegts:p{profile_id}:* Redis keys for this (channel, profile) pair."""
        if not self._redis:
            return
        fmt = self._profile_fmt()
        try:
            keys = [
                RedisKeys.output_state(self.channel_id, fmt),
                RedisKeys.output_owner(self.channel_id, fmt),
                RedisKeys.output_buffer_index(self.channel_id, fmt),
                RedisKeys.output_chunk_timestamps(self.channel_id, fmt),
                RedisKeys.output_buffer_discontinuities(self.channel_id, fmt),
            ]
            self._redis.delete(*keys)

            # Delete all chunk keys via scan
            buf_client = RedisClient.get_buffer()
            if buf_client:
                prefix = RedisKeys.output_buffer_chunk_prefix(self.channel_id, fmt)
                cursor = 0
                while True:
                    cursor, chunk_keys = buf_client.scan(cursor, match=f"{prefix}*", count=200)
                    if chunk_keys:
                        buf_client.delete(*chunk_keys)
                    if cursor == 0:
                        break
        except Exception as e:
            logger.error(
                f"[Profile:{self.profile_id}:{self.channel_id[:8]}] "
                f"Redis cleanup error: {e}"
            )
