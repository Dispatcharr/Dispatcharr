"""
fMP4 Remux Manager

Reads from the shared TS Redis buffer, pipes data through FFmpeg for container
remux to fragmented MP4, parses the init segment out of the first output bytes,
stores it in Redis, and writes subsequent fMP4 fragment chunks to FMP4StreamBuffer.

One instance per channel per cluster - coordinated via Redis fmp4:owner lock.
"""

import select
import subprocess
import threading
import time
import struct
from core.utils import RedisClient
from .buffer import FMP4StreamBuffer
from ...redis_keys import RedisKeys
from ...config_helper import ConfigHelper
from ...utils import get_logger

logger = get_logger()

# fMP4 remux states stored in Redis
FMP4_STATE_INITIALIZING = "initializing"
FMP4_STATE_ACTIVE = "active"
FMP4_STATE_STOPPED = "stopped"

# FFmpeg command for container-only remux: TS in, fMP4 out, no transcode
# The aac_adtstoasc BSF is required when source audio is AAC (converts ADTS framing
# to the raw format MP4 requires). For other codecs (AC3, EAC3, MP3, etc.) it errors;
# _handle_bsf_error detects that and retries with FFMPEG_REMUX_CMD_NO_BSF.
FFMPEG_REMUX_CMD = [
    "ffmpeg",
    "-loglevel", "error",
    "-f", "mpegts",
    "-i", "pipe:0",
    "-c", "copy",
    "-map", "0",
    "-bsf:a", "aac_adtstoasc",
    "-use_editlist", "0",
    "-flush_packets", "1",
    "-f", "mp4",
    "-movflags", "frag_keyframe+delay_moov+default_base_moof",
    "pipe:1",
]
FFMPEG_REMUX_CMD_NO_BSF = [
    "ffmpeg",
    "-loglevel", "error",
    "-f", "mpegts",
    "-i", "pipe:0",
    "-c", "copy",
    "-use_editlist", "0",
    "-flush_packets", "1",
    "-f", "mp4",
    "-movflags", "frag_keyframe+delay_moov+default_base_moof",
    "pipe:1",
]

# Timeout waiting for init segment before giving up (seconds)
INIT_SEGMENT_TIMEOUT = 15

# MP4 box type for the first media fragment
MOOF_BOX_TYPE = b"moof"

# Redis TTL for init segment and buffer state keys
FMP4_KEY_TTL = 3600


def _find_moof_offset(data: bytes, start: int = 0) -> int:
    """
    Scan `data` for the start of the first 'moof' box at or after `start`.
    Returns the byte offset of the box or -1 if not found.
    MP4 boxes: [4-byte big-endian length][4-byte type][payload...]
    """
    offset = start
    while offset + 8 <= len(data):
        try:
            box_size = struct.unpack_from(">I", data, offset)[0]
            box_type = data[offset + 4: offset + 8]
            if box_type == MOOF_BOX_TYPE:
                return offset
            if box_size < 8:
                offset += 1
            else:
                offset += box_size
        except struct.error:
            break
    return -1


class FMP4RemuxManager:
    """
    Reads the TS Redis buffer for a channel, remuxes to fMP4 via FFmpeg,
    and writes fMP4 chunks to FMP4StreamBuffer.
    """

    def __init__(self, channel_id, ts_buffer, worker_id, fmt='fmp4'):
        self.channel_id = channel_id
        self.ts_buffer = ts_buffer
        self.worker_id = worker_id
        self.fmt = fmt
        self.running = False
        self._process = None
        self._reader_thread = None
        self._writer_thread = None
        self._stderr_thread = None
        self.fmp4_buffer = FMP4StreamBuffer(
            channel_id, redis_client=RedisClient.get_buffer(), fmt=fmt
        )
        self._redis = RedisClient.get_client()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self):
        """Acquire the fmp4:owner lock and spawn the remux greenlets."""
        if not self._acquire_owner_lock():
            logger.info(f"[fMP4Remux:{self.channel_id}] Another worker owns fMP4 remux, skipping start")
            return False

        self.running = True
        self._set_state(FMP4_STATE_INITIALIZING)

        self._process = subprocess.Popen(
            FFMPEG_REMUX_CMD,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        short_id = self.channel_id[:8]
        self._reader_thread = threading.Thread(
            target=self._reader_loop, daemon=True,
            name=f"fmp4-reader-{short_id}"
        )
        self._writer_thread = threading.Thread(
            target=self._writer_loop, daemon=True,
            name=f"fmp4-writer-{short_id}"
        )
        self._stderr_thread = threading.Thread(
            target=self._stderr_loop, daemon=True,
            name=f"fmp4-stderr-{short_id}"
        )
        self._reader_thread.start()
        self._writer_thread.start()
        self._stderr_thread.start()

        logger.info(f"[fMP4Remux:{self.channel_id}] Started (pid={self._process.pid})")
        return True

    def stop(self):
        """Gracefully stop the remux process and clean up all Redis keys."""
        if not self.running:
            return
        self.running = False
        logger.info(f"[fMP4Remux:{self.channel_id}] Stopping")

        # Close FFmpeg stdin - signals EOF so it flushes and exits cleanly
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

        # Kill FFmpeg if still running
        try:
            if self._process and self._process.poll() is None:
                self._process.kill()
                self._process.wait(timeout=3)
        except Exception:
            pass

        self._cleanup_redis()
        logger.info(f"[fMP4Remux:{self.channel_id}] Stopped")

    # ------------------------------------------------------------------
    # Internal loops
    # ------------------------------------------------------------------

    def _write_all(self, data: bytes):
        """Write all bytes to FFmpeg stdin, looping on partial writes."""
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
        """Read TS chunks from Redis and write to FFmpeg stdin."""
        # Start behind live so the fMP4 buffer is pre-populated by the time
        # the first client connects, matching TS client positioning behavior.
        behind_seconds = ConfigHelper.new_client_behind_seconds()
        start_index = self.ts_buffer.find_chunk_index_by_time(behind_seconds) if behind_seconds > 0 else None
        if start_index is None:
            start_index = self.ts_buffer.index
        local_index = start_index
        logger.debug(f"[fMP4Remux:{self.channel_id}] Writer started at buffer index {local_index} ({behind_seconds}s behind live)")

        try:
            while self.running:
                chunks, new_index = self.ts_buffer.get_optimized_client_data(local_index)

                if chunks:
                    local_index = new_index
                    logger.debug(
                        f"[fMP4Remux:{self.channel_id}] Writer: {len(chunks)} chunk(s) "
                        f"-> stdin (index now {local_index})"
                    )
                    for chunk in chunks:
                        if not self.running:
                            break
                        try:
                            self._write_all(chunk)
                            self._process.stdin.flush()
                        except (BrokenPipeError, OSError) as e:
                            logger.warning(
                                f"[fMP4Remux:{self.channel_id}] FFmpeg stdin error: {e}"
                            )
                            self.running = False
                            return
                else:
                    if self.ts_buffer.index > local_index + 20:
                        local_index = self.ts_buffer.index - 5
                    time.sleep(0.05)

        except Exception as e:
            logger.error(f"[fMP4Remux:{self.channel_id}] Writer loop error: {e}", exc_info=True)
        finally:
            try:
                if self._process and self._process.stdin:
                    self._process.stdin.close()
            except Exception:
                pass
            logger.debug(f"[fMP4Remux:{self.channel_id}] Writer loop exited")

    def _flush_complete_fragments(self, frag_buf: bytearray) -> None:
        """
        Extract complete moof+mdat(+...) fragments from `frag_buf` (modifies in-place)
        and store each one as a single Redis chunk via put_fragment.
        A fragment ends where the next moof box begins.
        """
        while len(frag_buf) >= 8:
            if frag_buf[4:8] != b'moof':
                # Stream no longer aligned to a moof - drop bytes until we find one
                next_moof = _find_moof_offset(bytes(frag_buf), start=1)
                if next_moof < 0:
                    frag_buf.clear()
                    return
                del frag_buf[:next_moof]
                continue

            try:
                moof_size = struct.unpack_from(">I", frag_buf, 0)[0]
            except struct.error:
                break

            if moof_size < 8:
                break

            # Find where the NEXT moof box starts (= end of this fragment)
            next_moof = _find_moof_offset(bytes(frag_buf), start=moof_size)
            if next_moof < 0:
                break  # Current fragment not complete yet

            fragment = bytes(frag_buf[:next_moof])
            del frag_buf[:next_moof]
            self.fmp4_buffer.put_fragment(fragment)
            logger.debug(
                f"[fMP4Remux:{self.channel_id}] Fragment {self.fmp4_buffer.index}: "
                f"{len(fragment)} bytes"
            )

    def _reader_loop(self):
        """Read FFmpeg stdout, parse init segment, then feed each complete fMP4 fragment to the buffer."""
        init_buf = bytearray()
        init_stored = False
        frag_buf = bytearray()
        read_size = 65536

        logger.debug(f"[fMP4Remux:{self.channel_id}] Reader started")

        try:
            while self.running:
                ready, _, _ = select.select([self._process.stdout], [], [], 1.0)
                if not ready:
                    if self._process.poll() is not None:
                        logger.info(
                            f"[fMP4Remux:{self.channel_id}] FFmpeg exited "
                            f"(code={self._process.returncode})"
                        )
                        break
                    continue

                data = self._process.stdout.read(read_size)
                if not data:
                    logger.info(f"[fMP4Remux:{self.channel_id}] FFmpeg stdout EOF")
                    break

                if not init_stored:
                    init_buf.extend(data)
                    moof_offset = _find_moof_offset(bytes(init_buf))

                    if moof_offset >= 0:
                        init_segment = bytes(init_buf[:moof_offset])
                        frag_buf.extend(init_buf[moof_offset:])
                        init_buf = bytearray()

                        self._store_init_segment(init_segment)
                        self._set_state(FMP4_STATE_ACTIVE)
                        init_stored = True
                        logger.info(
                            f"[fMP4Remux:{self.channel_id}] Init segment stored "
                            f"({len(init_segment)} bytes)"
                        )
                        self._flush_complete_fragments(frag_buf)

                    elif len(init_buf) > 10 * 1024 * 1024:
                        logger.error(
                            f"[fMP4Remux:{self.channel_id}] No moof in first 10 MB, aborting"
                        )
                        self.running = False
                        break
                else:
                    frag_buf.extend(data)
                    self._flush_complete_fragments(frag_buf)

        except Exception as e:
            logger.error(f"[fMP4Remux:{self.channel_id}] Reader loop error: {e}", exc_info=True)
        finally:
            if frag_buf and init_stored:
                self.fmp4_buffer.put_fragment(bytes(frag_buf))
            logger.info(f"[fMP4Remux:{self.channel_id}] Reader loop exited")

    def _stderr_loop(self):
        """Log FFmpeg stderr lines. Detect BSF codec mismatch and trigger a no-BSF retry."""
        try:
            for raw_line in self._process.stderr:
                line = raw_line.decode(errors="replace").rstrip()
                if line:
                    logger.warning(f"[fMP4Remux:{self.channel_id}] FFmpeg: {line}")
                if "aac_adtstoasc" in line and "is not supported by the bitstream filter" in line:
                    threading.Thread(
                        target=self._handle_bsf_error, daemon=True,
                        name=f"fmp4-bsf-retry-{self.channel_id[:8]}"
                    ).start()
                    return
        except Exception:
            pass

    def _handle_bsf_error(self):
        """Restart FFmpeg without the aac_adtstoasc BSF for non-AAC audio streams."""
        logger.warning(f"[fMP4Remux:{self.channel_id}] Non-AAC audio detected, retrying without BSF")
        self.running = False
        try:
            if self._process and self._process.poll() is None:
                self._process.kill()
                self._process.wait(timeout=3)
        except Exception:
            pass

        for t in (self._reader_thread, self._writer_thread):
            if t and t.is_alive():
                try:
                    t.join(timeout=5)
                except Exception:
                    pass

        self._set_state(FMP4_STATE_INITIALIZING)
        self._process = subprocess.Popen(
            FFMPEG_REMUX_CMD_NO_BSF,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.running = True

        if not self.running:
            # stop() was called while we were restarting - clean up immediately
            try:
                self._process.kill()
                self._process.wait(timeout=3)
            except Exception:
                pass
            self._cleanup_redis()
            return

        short_id = self.channel_id[:8]
        self._reader_thread = threading.Thread(
            target=self._reader_loop, daemon=True,
            name=f"fmp4-reader-{short_id}"
        )
        self._writer_thread = threading.Thread(
            target=self._writer_loop, daemon=True,
            name=f"fmp4-writer-{short_id}"
        )
        self._stderr_thread = threading.Thread(
            target=self._stderr_loop, daemon=True,
            name=f"fmp4-stderr-{short_id}"
        )
        self._reader_thread.start()
        self._writer_thread.start()
        self._stderr_thread.start()
        logger.info(f"[fMP4Remux:{self.channel_id}] Restarted without BSF (pid={self._process.pid})")

    # ------------------------------------------------------------------
    # Redis helpers
    # ------------------------------------------------------------------

    def _acquire_owner_lock(self) -> bool:
        if not self._redis:
            return True
        owner_key = RedisKeys.output_owner(self.channel_id, self.fmt)
        acquired = self._redis.set(owner_key, self.worker_id, nx=True, ex=FMP4_KEY_TTL)
        if acquired:
            return True
        existing = self._redis.get(owner_key)
        return existing == self.worker_id

    def _set_state(self, state: str):
        if self._redis:
            self._redis.setex(RedisKeys.output_state(self.channel_id, self.fmt), FMP4_KEY_TTL, state)

    def _store_init_segment(self, data: bytes):
        redis_buf = RedisClient.get_buffer()
        if redis_buf:
            redis_buf.setex(RedisKeys.output_init(self.channel_id, self.fmt), FMP4_KEY_TTL, data)

    def _cleanup_redis(self):
        """Delete all output buffer Redis keys for this channel."""
        if not self._redis:
            return
        try:
            keys_to_delete = [
                RedisKeys.output_init(self.channel_id, self.fmt),
                RedisKeys.output_state(self.channel_id, self.fmt),
                RedisKeys.output_owner(self.channel_id, self.fmt),
            ]
            self._redis.delete(*keys_to_delete)
            self.fmp4_buffer.cleanup_redis()
        except Exception as e:
            logger.error(f"[fMP4Remux:{self.channel_id}] Error during Redis cleanup: {e}")
