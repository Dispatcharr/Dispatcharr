"""
Output Profile Transcode Manager

Reads from the shared TS Redis buffer, pipes data through a user-defined
transcoding command (pipe:0 stdin → pipe:1 stdout), and writes the output
chunks to a Redis-backed StreamBuffer under:

    live:channel:{channel_id}:profile:{profile_id}:buffer:*

One transcode process runs per active (channel, profile) pair across the
entire cluster. The TS-owning worker starts the process; non-owning workers
create a read-only StreamBuffer pointing at the same Redis keys.
"""

import functools
import select
import threading
import time
from core.utils import RedisClient
from ...input.buffer import OUTPUT_FLUSH_AGE_S, StreamBuffer
from ...redis_keys import RedisKeys
from ...config_helper import ConfigHelper
from ...utils import get_logger
from ..pipe_write import write_all

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
        self._process = None
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

        self.running = True
        self._set_state(PROFILE_STATE_ACTIVE)

        short = f"{self.channel_id[:8]}:p{self.profile_id}"
        self._writer_thread = threading.Thread(
            target=self._writer_loop, daemon=True,
            name=f"profile-writer-{short}"
        )
        self._reader_thread = threading.Thread(
            target=self._reader_loop, daemon=True,
            name=f"profile-reader-{short}"
        )
        self._stderr_thread = threading.Thread(
            target=self._stderr_loop, daemon=True,
            name=f"profile-stderr-{short}"
        )
        self._writer_thread.start()
        self._reader_thread.start()
        self._stderr_thread.start()

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

    def _write_all(self, data: bytes, stop_check=None):
        """Write all bytes to the encoder stdin; see pipe_write.write_all."""
        write_all(self._process.stdin, data, lambda: self.running, stop_check)

    def _writer_loop(self):
        """Read TS chunks from Redis and write to the transcode process stdin."""
        behind_seconds = ConfigHelper.new_client_behind_seconds()
        start_index = self.ts_buffer.find_chunk_index_by_time(behind_seconds) if behind_seconds > 0 else None
        if start_index is None:
            start_index = self.ts_buffer.index
        local_index = start_index

        def stop_check(after_index, mid_skip):
            # A full pipe: stop the chunk if the source switched after this batch was read.
            skip = self.ts_buffer.switch_marks.skip_after(after_index)
            if skip is None:
                return False
            mid_skip.append(skip)
            return True

        logger.debug(
            f"[Profile:{self.profile_id}:{self.channel_id[:8]}] "
            f"Writer started at index {local_index}"
        )

        try:
            while self.running:
                batch = self.ts_buffer.read_client_batch(local_index)
                chunks = batch.chunks

                if chunks:
                    local_index = batch.next_index
                    if batch.switch_mark is not None and self.output_buffer:
                        # Clients of this profile then skip what the encoder made from the old source.
                        self.output_buffer.record_output_discontinuity()
                    mid_skip = []
                    stop = functools.partial(stop_check, batch.next_index - 1, mid_skip)

                    for chunk in chunks:
                        if not self.running:
                            break
                        try:
                            self._write_all(chunk, stop)
                            self._process.stdin.flush()
                        except (BrokenPipeError, OSError) as e:
                            logger.warning(
                                f"[Profile:{self.profile_id}:{self.channel_id[:8]}] "
                                f"Stdin error: {e}"
                            )
                            self.running = False
                            return
                        # A switch after the read: the rest of the batch is the old source.
                        skip = mid_skip[0] if mid_skip else self.ts_buffer.switch_marks.skip_after(batch.next_index - 1)
                        if skip is not None:
                            logger.info(
                                f"[Profile:{self.profile_id}:{self.channel_id}] Source switch: "
                                f"dropping the rest of the batch, resuming at index {skip}"
                            )
                            local_index = skip
                            break
                else:
                    if self.ts_buffer.index > local_index + 20:
                        local_index = self.ts_buffer.index - 5
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

    def _reader_loop(self):
        """Read chunks from process stdout and write to the output StreamBuffer."""
        read_size = 65536
        logger.debug(
            f"[Profile:{self.profile_id}:{self.channel_id[:8]}] Reader started"
        )

        try:
            while self.running:
                self._refresh_redis_ttls()
                ready, _, _ = select.select([self._process.stdout], [], [], 1.0)
                if not ready:
                    if self._process.poll() is not None:
                        logger.info(
                            f"[Profile:{self.profile_id}:{self.channel_id[:8]}] "
                            f"Process exited (code={self._process.returncode})"
                        )
                        break
                    self.output_buffer.flush_pending(OUTPUT_FLUSH_AGE_S)
                    continue

                data = self._process.stdout.read(read_size)
                if not data:
                    logger.info(
                        f"[Profile:{self.profile_id}:{self.channel_id[:8]}] stdout EOF"
                    )
                    break

                self.output_buffer.add_chunk(data)
                self.output_buffer.flush_pending(OUTPUT_FLUSH_AGE_S)

        except Exception as e:
            logger.error(
                f"[Profile:{self.profile_id}:{self.channel_id[:8]}] "
                f"Reader loop error: {e}", exc_info=True
            )
        finally:
            if self.output_buffer:
                self.output_buffer.stop()
            logger.info(
                f"[Profile:{self.profile_id}:{self.channel_id[:8]}] Reader loop exited"
            )

    def _stderr_loop(self):
        """Log process stderr at WARNING level."""
        import os as _os
        import select as _select
        try:
            stderr_fd = self._process.stderr.fileno()
            buf = b""
            while self.running:
                ready, _, _ = _select.select([stderr_fd], [], [], 1.0)
                if not ready:
                    if self._process.poll() is not None:
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

    def _make_buffer(self) -> StreamBuffer:
        """Create a StreamBuffer wired to this profile's Redis key namespace."""
        fmt = f"mpegts:p{self.profile_id}"
        return StreamBuffer(
            channel_id=self.channel_id,
            redis_client=RedisClient.get_buffer(),
            buffer_index_key=RedisKeys.output_buffer_index(self.channel_id, fmt),
            buffer_chunk_prefix=RedisKeys.output_buffer_chunk_prefix(self.channel_id, fmt),
            chunk_timestamps_key=RedisKeys.output_chunk_timestamps(self.channel_id, fmt),
            discontinuities_key=RedisKeys.output_discontinuities(self.channel_id, fmt),
        )

    def _acquire_owner_lock(self) -> bool:
        if not self._redis:
            return True
        owner_key = RedisKeys.output_owner(self.channel_id, f"mpegts:p{self.profile_id}")
        acquired = self._redis.set(owner_key, self.worker_id, nx=True, ex=PROFILE_KEY_TTL)
        if acquired:
            return True
        existing = self._redis.get(owner_key)
        return existing == self.worker_id

    def _release_owner_lock(self):
        if self._redis:
            try:
                self._redis.delete(RedisKeys.output_owner(self.channel_id, f"mpegts:p{self.profile_id}"))
            except Exception:
                pass

    def _set_state(self, state: str):
        if self._redis:
            self._redis.setex(
                RedisKeys.output_state(self.channel_id, f"mpegts:p{self.profile_id}"),
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
            fmt = f"mpegts:p{self.profile_id}"
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
        fmt = f"mpegts:p{self.profile_id}"
        try:
            keys = [
                RedisKeys.output_state(self.channel_id, fmt),
                RedisKeys.output_owner(self.channel_id, fmt),
                RedisKeys.output_buffer_index(self.channel_id, fmt),
                RedisKeys.output_chunk_timestamps(self.channel_id, fmt),
                RedisKeys.output_discontinuities(self.channel_id, fmt),
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
