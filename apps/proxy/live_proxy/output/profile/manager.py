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

import select
import subprocess
import threading
import time
from core.utils import RedisClient
from ...input.buffer import StreamBuffer
from ...redis_keys import RedisKeys
from ...config_helper import ConfigHelper
from ...utils import get_logger

logger = get_logger()

PROFILE_STATE_ACTIVE = "active"
PROFILE_STATE_STOPPED = "stopped"

PROFILE_KEY_TTL = 3600


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

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> bool:
        """
        Acquire the owner lock, spawn the transcode process and threads.
        Returns True if this worker started the process, False if another
        worker already owns it (caller should still use output_buffer for reads).
        """
        if not self._acquire_owner_lock():
            logger.info(
                f"[Profile:{self.profile_id}:{self.channel_id[:8]}] "
                "Another worker owns transcode, using shared buffer"
            )
            self.output_buffer = self._make_buffer()
            return False

        self.output_buffer = self._make_buffer()

        try:
            self._process = subprocess.Popen(
                self.command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
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

    def _write_all(self, data: bytes):
        """Write all bytes to process stdin, looping on partial writes."""
        view = memoryview(data)
        offset = 0
        total = len(view)
        while offset < total:
            if not self.running:
                return
            n = self._process.stdin.write(view[offset:])
            if n is None or n <= 0:
                raise OSError("stdin write returned no bytes")
            offset += n

    def _writer_loop(self):
        """Read TS chunks from Redis and write to the transcode process stdin."""
        behind_seconds = ConfigHelper.new_client_behind_seconds()
        start_index = self.ts_buffer.find_chunk_index_by_time(behind_seconds) if behind_seconds > 0 else None
        if start_index is None:
            start_index = self.ts_buffer.index
        local_index = start_index
        logger.debug(
            f"[Profile:{self.profile_id}:{self.channel_id[:8]}] "
            f"Writer started at index {local_index}"
        )

        try:
            while self.running:
                chunks, new_index = self.ts_buffer.get_optimized_client_data(local_index)

                if chunks:
                    local_index = new_index
                    for chunk in chunks:
                        if not self.running:
                            break
                        try:
                            self._write_all(chunk)
                            self._process.stdin.flush()
                        except (BrokenPipeError, OSError) as e:
                            logger.warning(
                                f"[Profile:{self.profile_id}:{self.channel_id[:8]}] "
                                f"Stdin error: {e}"
                            )
                            self.running = False
                            return
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
                ready, _, _ = select.select([self._process.stdout], [], [], 1.0)
                if not ready:
                    if self._process.poll() is not None:
                        logger.info(
                            f"[Profile:{self.profile_id}:{self.channel_id[:8]}] "
                            f"Process exited (code={self._process.returncode})"
                        )
                        break
                    continue

                data = self._process.stdout.read(read_size)
                if not data:
                    logger.info(
                        f"[Profile:{self.profile_id}:{self.channel_id[:8]}] stdout EOF"
                    )
                    break

                self.output_buffer.add_chunk(data)

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
        try:
            for raw_line in self._process.stderr:
                line = raw_line.decode(errors="replace").rstrip()
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
