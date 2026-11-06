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

import enum
import logging
import select
import threading
import time
from core.utils import RedisClient
from ...input.buffer import StreamBuffer
from ...redis_keys import RedisKeys
from ...config_helper import ConfigHelper
from ...utils import get_logger
from ..ts_pmt import PmtLayoutWatcher

logger = get_logger()

PROFILE_STATE_ACTIVE = "active"
PROFILE_STATE_STOPPED = "stopped"

# Orphan backstop TTL; refreshed while the transcode is alive, deleted on stop.
PROFILE_KEY_TTL = 3600
PROFILE_TTL_REFRESH_INTERVAL = 60

# Total time the old process gets on a restart to take the input written up to
# the boundary and flush its remaining output before it is killed. Measured
# drain time after stdin close with the seeded profile shapes: ~2 ms (stream
# copy), ~90 ms (AAC encode), ~110-130 ms (x264 veryfast). The cap leaves
# headroom over that while keeping a wedged encoder from stalling failover.
_DRAIN_TIMEOUT_SECONDS = 0.25

# After the old process is killed its pipes hit EOF immediately, so its reader
# threads exit almost at once; this only bounds a reader stuck in a slow write.
_RETIRE_JOIN_SECONDS = 1.0

class _Restart(enum.Enum):
    """Outcome of ``_restart_transcode``.

    STOP:     the writer must end (manager stopping, or the process had died).
    REPLACED: a new process now owns stdin.
    KEPT:     the spawn failed and the current process continues; the layout
              change should be retried when the next PMT arrives.
    """

    STOP = enum.auto()
    REPLACED = enum.auto()
    KEPT = enum.auto()


class _ProcessSlot:
    """A spawned transcode process plus the flags its reader threads obey.

    closing:   stdin was closed on purpose; EOF on stdout is expected and must
               not stop the shared output buffer.
    abandoned: the process was retired; stop forwarding its output.
    """

    __slots__ = ("process", "closing", "abandoned", "reader", "stderr")

    def __init__(self, process):
        self.process = process
        self.closing = threading.Event()
        self.abandoned = threading.Event()
        self.reader = None
        self.stderr = None


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

        self._slot = _ProcessSlot(self._process)
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

    def _write_all(self, data: bytes, deadline=None, process=None):
        """Write all bytes to process stdin, looping on partial writes.

        With a monotonic ``deadline`` the write gives up when it passes and
        returns False; otherwise it blocks until the pipe takes everything.
        """
        process = process or self._process
        view = memoryview(data)
        offset = 0
        total = len(view)
        while offset < total:
            if not self.running:
                return False
            if deadline is not None and time.monotonic() >= deadline:
                return False
            n = process.stdin.write(view[offset:])
            if n is None:
                # Pipe full (EAGAIN on non-blocking FD); yield cooperatively
                wait = 1.0
                if deadline is not None:
                    wait = max(0.0, min(wait, deadline - time.monotonic()))
                select.select([], [process.stdin], [], wait)
            elif n <= 0:
                raise OSError("stdin write returned no bytes")
            else:
                offset += n
        return True

    def _write_stdin(self, data: bytes) -> bool:
        """Write to the current process. Returns False when the writer must stop."""
        try:
            self._write_all(data)
            self._process.stdin.flush()
        except (BrokenPipeError, OSError) as e:
            logger.warning(
                f"[Profile:{self.profile_id}:{self.channel_id[:8]}] "
                f"Stdin error: {e}"
            )
            self.running = False
            return False
        return True

    def _feed(self, data: bytes, watcher: PmtLayoutWatcher) -> bool:
        """Write one input chunk, replacing the process at each PMT layout change.

        The bytes before the changed PMT belong to the old layout and go to the
        old process; the new process starts with the PAT then the changed PMT.
        Returns False when the writer loop must stop.
        """
        while data:
            change_at = watcher.find_layout_change(data)
            if change_at is None:
                return self._write_stdin(data)
            head, data = data[:change_at], data[change_at:]
            outcome = self._restart_transcode(
                reason="PMT/ES layout change", flush=head
            )
            if outcome == _Restart.STOP:
                return False
            if outcome == _Restart.KEPT:
                # Spawn failed: head was written to the process we kept.
                # Revert the fingerprint so a later copy of this PMT retries
                # the replacement, and send the remainder as ordinary input.
                watcher.revert_layout_change()
                return self._write_stdin(data)
            watcher.accept_layout_change()
            # The new process must see the PAT, then the whole PMT section
            # (which may have started in an earlier chunk), before the media.
            data = watcher.pat_packet + watcher.leading_section + data
        return True

    def _writer_loop(self):
        """Read TS chunks from Redis and write to the transcode process stdin."""
        behind_seconds = ConfigHelper.new_client_behind_seconds()
        start_index = self.ts_buffer.find_chunk_index_by_time(behind_seconds) if behind_seconds > 0 else None
        if start_index is None:
            start_index = self.ts_buffer.index
        local_index = start_index
        watcher = PmtLayoutWatcher()
        logger.debug(
            f"[Profile:{self.profile_id}:{self.channel_id[:8]}] "
            f"Writer started at index {local_index}"
        )

        try:
            while self.running:
                indexed, new_index = self.ts_buffer.get_optimized_client_data_indexed(
                    local_index
                )

                if indexed:
                    # Use each chunk's real Redis index. A hole in the middle
                    # must not slide the following chunks onto the wrong
                    # discontinuity mark.
                    disc_at = set(
                        self.ts_buffer.discontinuities_in_range(local_index, new_index)
                    )
                    prev_index = local_index
                    for chunk_index, chunk in indexed:
                        if not self.running:
                            break
                        if any(prev_index < disc <= chunk_index for disc in disc_at):
                            outcome = self._restart_transcode(
                                reason=f"input discontinuity at index {chunk_index}"
                            )
                            if outcome == _Restart.STOP:
                                return
                            if outcome == _Restart.REPLACED:
                                watcher.reset()
                        if not self._feed(chunk, watcher):
                            return
                        prev_index = chunk_index
                    local_index = new_index
                else:
                    if self.ts_buffer.index > local_index + 20:
                        skip_to = self.ts_buffer.index - 5
                        # Source switches inside the skipped range never reach
                        # the loop above, so restart for them here.
                        if self.ts_buffer.discontinuities_in_range(local_index, skip_to):
                            outcome = self._restart_transcode(
                                reason="input discontinuity in skipped range"
                            )
                            if outcome == _Restart.STOP:
                                return
                            if outcome == _Restart.REPLACED:
                                watcher.reset()
                        local_index = skip_to
                    time.sleep(0.05)

        except Exception as e:
            logger.error(
                f"[Profile:{self.profile_id}:{self.channel_id[:8]}] "
                f"Writer loop error: {e}", exc_info=True
            )
        finally:
            try:
                if self._process and self._process.stdin:
                    self._process.stdin.close()
            except Exception:
                pass
            logger.debug(
                f"[Profile:{self.profile_id}:{self.channel_id[:8]}] Writer loop exited"
            )

    def _restart_transcode(self, reason: str, flush: bytes = b"") -> _Restart:
        """Replace the transcode process at a stream boundary.

        Runs on the writer thread, the only thread that writes stdin.

        The replacement is spawned first and swapped in before the old process
        is touched, so ``self._process`` is never a dead process (the server
        treats that as a crashed profile and tears the whole profile down).

        The old process then gets until ``_DRAIN_TIMEOUT_SECONDS`` to take
        ``flush`` (the input up to the boundary), see EOF and emit what it still
        holds; its output is forwarded to the shared buffer. Whatever is still
        running after that is killed so a wedged encoder cannot stall failover.
        The output buffer is marked discontinuous only once the old reader has
        stopped, so no old-era bytes land after the marker.

        Returns ``_Restart.STOP`` when the writer must stop: the manager is
        stopping, or the current process had already died. A dead process means
        its reader already stopped the shared output buffer (which then refuses
        writes), so replacing it would silently discard all later output; leave
        that to the server's dead-process recycling instead.

        Returns ``_Restart.KEPT`` when the replacement cannot be spawned: the
        current process is kept and ``flush`` is written to it. The caller
        should revert any layout-change fingerprint so a later PMT can retry.

        Returns ``_Restart.REPLACED`` when the new process is running.
        """
        if not self.running:
            return _Restart.STOP

        short = f"{self.channel_id[:8]}"
        if self._slot.process.poll() is not None:
            logger.warning(
                f"[Profile:{self.profile_id}:{short}] "
                f"Transcode already exited ({reason}); leaving restart to the server"
            )
            self.running = False
            return _Restart.STOP

        try:
            from ...utils import posix_spawn_proc
            new_process = posix_spawn_proc(self.command)
        except (FileNotFoundError, OSError) as e:
            logger.error(
                f"[Profile:{self.profile_id}:{short}] "
                f"Failed to restart transcode ({reason}), keeping current process: {e}"
            )
            # The caller has already split off `flush` (input before the
            # boundary). Nothing else will write it, so it has to go to the
            # process we are keeping.
            if flush and not self._write_stdin(flush):
                return _Restart.STOP
            return _Restart.KEPT

        logger.info(
            f"[Profile:{self.profile_id}:{short}] Restarting transcode ({reason})"
        )
        started = time.monotonic()
        deadline = started + _DRAIN_TIMEOUT_SECONDS
        old = self._slot
        new = _ProcessSlot(new_process)
        self._process = new_process
        self._slot = new

        old.closing.set()
        if flush:
            try:
                self._write_all(flush, deadline=deadline, process=old.process)
            except (BrokenPipeError, OSError):
                pass  # the old process is already gone
        try:
            old.process.stdin.close()
        except Exception:
            pass
        if old.reader and old.reader.is_alive():
            old.reader.join(timeout=max(0.0, deadline - time.monotonic()))
        drained = not (old.reader and old.reader.is_alive())

        old.abandoned.set()
        try:
            if old.process.poll() is None:
                old.process.kill()
                old.process.wait(timeout=1)
        except Exception:
            pass
        for t in (old.reader, old.stderr):
            if t and t.is_alive():
                try:
                    t.join(timeout=_RETIRE_JOIN_SECONDS)
                except Exception:
                    pass

        if not self.running:
            # stop() ran while we were swapping; it only knows the new process.
            try:
                new_process.kill()
            except Exception:
                pass
            return _Restart.STOP

        if self.output_buffer:
            try:
                self.output_buffer.mark_discontinuity()
            except Exception as e:
                logger.warning(
                    f"[Profile:{self.profile_id}:{short}] "
                    f"Failed to mark output discontinuity: {e}"
                )

        self._start_slot_threads(new)
        logger.info(
            f"[Profile:{self.profile_id}:{short}] "
            f"Transcode restarted (pid={new_process.pid}, {reason}, "
            f"old process {'drained' if drained else 'killed'} in "
            f"{(time.monotonic() - started) * 1000:.0f} ms)"
        )
        return _Restart.REPLACED

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

                data = process.stdout.read(read_size)
                if not data:
                    logger.log(
                        logging.DEBUG if slot.closing.is_set() else logging.INFO,
                        f"[Profile:{self.profile_id}:{self.channel_id[:8]}] stdout EOF"
                    )
                    break

                if slot.abandoned.is_set():
                    break  # retired while blocked in the read
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
        import os as _os
        import select as _select
        process = slot.process
        try:
            stderr_fd = process.stderr.fileno()
            buf = b""
            while self.running and not slot.abandoned.is_set():
                ready, _, _ = _select.select([stderr_fd], [], [], 1.0)
                if not ready:
                    if process.poll() is not None:
                        break
                    continue
                chunk = _os.read(stderr_fd, 4096)
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
