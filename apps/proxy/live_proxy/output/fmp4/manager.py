"""One fMP4 remux per channel. TS in from the shared buffer, fragments to Redis.

Copy-mode FFmpeg exits when the elementary stream layout changes, so a
discontinuity or PMT change replaces the process there and publishes a new
init. The open response stays connected and is given that init before the
new fragments.

Each process starts fragment numbers and decode times at zero. Fragments
are moved onto one channel timeline before publish (timing.PublishedClock).

The writer spawns once a chunk has carried a program map, and that map
selects the command. Chunks read before the map are written to that process.
A missing ffmpeg binary still fails in start().
"""

import logging
import os
import select
import shutil
import threading
import time
import struct

from apps.proxy.ts_psi import (
    DESCRIPTOR_AC3,
    DESCRIPTOR_DTS,
    DESCRIPTOR_EAC3,
    DESCRIPTOR_REGISTRATION,
    REGISTRATION_AC3,
    REGISTRATION_DTS1,
    REGISTRATION_DTS2,
    REGISTRATION_DTS3,
    REGISTRATION_EAC3,
    STREAM_TYPE_AAC_ADTS,
    STREAM_TYPE_AAC_LATM,
    STREAM_TYPE_AC3,
    STREAM_TYPE_DTS,
    STREAM_TYPE_EAC3,
    STREAM_TYPE_MPEG1_AUDIO,
    STREAM_TYPE_MPEG2_AUDIO,
    STREAM_TYPE_MPEG4_AUDIO,
    STREAM_TYPE_PRIVATE_DATA,
    STREAM_TYPE_SAMPLE_AES_AAC,
    STREAM_TYPE_SAMPLE_AES_AC3,
    STREAM_TYPE_SAMPLE_AES_EAC3,
)
from core.utils import RedisClient
from ..buffer import OutputStreamBuffer
from ..pipe_restart import (
    RETIRE_JOIN_SECONDS,
    ProcessSlot,
    RestartOutcome,
    replace_piped_process,
    write_all,
)
from ..ts_feed import feed_chunk_with_layout_watch, run_ts_buffer_writer
from ..ts_pmt import PmtLayoutWatcher
from .timing import PublishedClock
from ...redis_keys import RedisKeys
from ...config_helper import ConfigHelper
from ...utils import get_logger

logger = get_logger()

# fMP4 remux states stored in Redis
FMP4_STATE_INITIALIZING = "initializing"
FMP4_STATE_ACTIVE = "active"
FMP4_STATE_STOPPED = "stopped"

# Types FFmpeg numbers as audio from the type alone. A type missing here
# shifts every later -bsf:a index. Private PES counts only with an audio
# descriptor. Blu-ray types are left out: FFmpeg applies them only for an
# HDMV registration, which this fingerprint does not carry.
_AUDIO_STREAM_TYPES = frozenset({
    STREAM_TYPE_MPEG1_AUDIO,
    STREAM_TYPE_MPEG2_AUDIO,
    STREAM_TYPE_AAC_ADTS,
    STREAM_TYPE_AAC_LATM,
    STREAM_TYPE_MPEG4_AUDIO,
    STREAM_TYPE_AC3,
    STREAM_TYPE_EAC3,
    STREAM_TYPE_DTS,
    STREAM_TYPE_SAMPLE_AES_AC3,
    STREAM_TYPE_SAMPLE_AES_EAC3,
    STREAM_TYPE_SAMPLE_AES_AAC,
})
_PRIVATE_AUDIO_DESCRIPTOR_TAGS = frozenset({
    DESCRIPTOR_AC3,
    DESCRIPTOR_EAC3,
    DESCRIPTOR_DTS,
})
_PRIVATE_AUDIO_REGISTRATIONS = frozenset({
    REGISTRATION_AC3,
    REGISTRATION_EAC3,
    REGISTRATION_DTS1,
    REGISTRATION_DTS2,
    REGISTRATION_DTS3,
})

# Container copy. FFmpeg does not add aac_adtstoasc for an MPEG-TS input, and
# a global -bsf:a exits when the program also carries AC-3. A mixed program
# names the filter per ADTS AAC audio index instead. DVB subtitles, DVB
# teletext, and unknown data streams are left unmapped: copying one fails
# while this muxer writes its header, and the output is empty. Captions
# inside the video bitstream are copied with the video. The '?' selectors
# still open an audio-only or video-only program.
_REMUX_INPUT_ARGS = [
    "ffmpeg",
    "-loglevel", "error",
    "-f", "mpegts",
    "-i", "pipe:0",
    "-c", "copy",
    "-map", "0:v?",
    "-map", "0:a?",
    # An empty mapped PID holds the muxer for FFmpeg's default 10s.
    "-max_interleave_delta", "100K",
]
_REMUX_OUTPUT_ARGS = [
    "-use_editlist", "0",
    "-flush_packets", "1",
    "-f", "mp4",
    "-movflags", "frag_keyframe+delay_moov+default_base_moof",
    "pipe:1",
]
FFMPEG_REMUX_CMD = [
    *_REMUX_INPUT_ARGS,
    "-bsf:a", "aac_adtstoasc",
    *_REMUX_OUTPUT_ARGS,
]
FFMPEG_REMUX_CMD_NO_BSF = [*_REMUX_INPUT_ARGS, *_REMUX_OUTPUT_ARGS]

# Timeout waiting for init segment before giving up (seconds)
INIT_SEGMENT_TIMEOUT = 15

# MP4 box type for the first media fragment
MOOF_BOX_TYPE = b"moof"

# Redis TTL for init segment and buffer state keys (orphan backstop).
# Refreshed while the remux is alive; deleted on graceful stop.
FMP4_KEY_TTL = 3600
FMP4_TTL_REFRESH_INTERVAL = 60

# Chunks kept while no program map is known for the current source. Past this,
# the oldest are dropped so a source that never sends a map cannot grow without bound.
_PRE_PMT_BYTE_LIMIT = 8 * 1024 * 1024


def _is_audio_stream(stream_type, descriptors) -> bool:
    """True when FFmpeg will give this elementary stream an audio index."""
    if stream_type in _AUDIO_STREAM_TYPES:
        return True
    if stream_type != STREAM_TYPE_PRIVATE_DATA:
        return False
    for tag, detail in descriptors:
        if tag in _PRIVATE_AUDIO_DESCRIPTOR_TAGS:
            return True
        if tag == DESCRIPTOR_REGISTRATION and detail in _PRIVATE_AUDIO_REGISTRATIONS:
            return True
    return False


def remux_command_for_layout(fingerprint):
    """Remux argv for one PMT fingerprint.

    All ADTS AAC uses one global filter. Mixed audio names ``-bsf:a:N`` on
    each ADTS index, in PMT order. LATM is left unfiltered: the filter
    refuses it and MP4 cannot hold aac_latm. A missing fingerprint still
    selects the AAC command. The remux does not spawn until a PMT is seen.
    """
    if fingerprint is None:
        return list(FFMPEG_REMUX_CMD)
    aac_indexes = []
    audio_count = 0
    for stream_type, _es_pid, descriptors in fingerprint[1]:
        if not _is_audio_stream(stream_type, descriptors):
            continue
        if stream_type == STREAM_TYPE_AAC_ADTS:
            aac_indexes.append(audio_count)
        audio_count += 1
    if not aac_indexes:
        return list(FFMPEG_REMUX_CMD_NO_BSF)
    if len(aac_indexes) == audio_count:
        return list(FFMPEG_REMUX_CMD)
    filters = []
    for index in aac_indexes:
        filters.extend([f"-bsf:a:{index}", "aac_adtstoasc"])
    return [*_REMUX_INPUT_ARGS, *filters, *_REMUX_OUTPUT_ARGS]


def _find_moof_offset(data, start: int = 0) -> int:
    """Byte offset of the first moof at or after ``start``, or -1.

    Reads ``data`` in place, so the reader can pass its buffer without copying it.
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
    def __init__(self, channel_id, ts_buffer, worker_id, fmt='fmp4'):
        self.channel_id = channel_id
        self.ts_buffer = ts_buffer
        self.worker_id = worker_id
        self.fmt = fmt
        self.running = False
        # Always the live process: swapped only after a replacement spawns.
        self._process = None
        self._slot = None
        self._writer_thread = None
        self._command = list(FFMPEG_REMUX_CMD)
        self._bsf_retry = False
        # aac_adtstoasc was refused for this layout, so the PMT cannot turn it back on.
        self._filter_rejected = False
        # Discontinuity waiting on the new source's PMT before the process is replaced.
        self._restart_pending = None
        # Chunks read while no program map is known. Written once that map selects the command.
        self._held_chunks = []
        self._held_bytes = 0
        self._held_trimmed = False
        self._stopped = False
        self._clock = PublishedClock()
        self.fmp4_buffer = OutputStreamBuffer(
            channel_id, redis_client=RedisClient.get_buffer(), fmt=fmt
        )
        self._redis = RedisClient.get_client()
        self._last_ttl_refresh = 0.0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self):
        """Take the owner lock and start the writer. The process spawns once a chunk carries a program map."""
        if not self._acquire_owner_lock():
            logger.info(f"[fMP4Remux:{self.channel_id}] Another worker owns fMP4 remux, skipping start")
            return False

        self._command = list(FFMPEG_REMUX_CMD)
        self._bsf_retry = False
        self._filter_rejected = False
        self._restart_pending = None
        self._held_chunks = []
        self._held_bytes = 0
        self._held_trimmed = False
        self._stopped = False
        self._process = None
        self._slot = None
        self._clock = PublishedClock()
        self._set_state(FMP4_STATE_INITIALIZING)

        if not self._remux_binary_ready():
            return False

        self.running = True

        short_id = self.channel_id[:8]
        self._writer_thread = threading.Thread(
            target=self._writer_loop, daemon=True,
            name=f"fmp4-writer-{short_id}"
        )
        self._writer_thread.start()

        logger.info(
            f"[fMP4Remux:{self.channel_id}] Started, waiting for the first program map"
        )
        return True

    def output_process_healthy(self) -> bool:
        """True while this remux should stay registered.

        No process yet is the wait for a program map, which is healthy.
        A remux that stopped feeding, or whose process has exited, is replaced.
        """
        if not self.running:
            return False
        return self._process is None or self._process.poll() is None

    def _remux_binary_ready(self) -> bool:
        """False when ffmpeg cannot be executed. The process itself is spawned later."""
        executable = shutil.which(self._command[0]) or self._command[0]
        if os.path.isfile(executable) and os.access(executable, os.X_OK):
            return True
        logger.error(
            f"[fMP4Remux:{self.channel_id}] Failed to start remux: "
            f"cannot execute {self._command[0]!r}"
        )
        self._cleanup_redis()
        return False

    def _spawn_process(self):
        # Imported here so the spawn can be replaced in tests.
        from ...utils import posix_spawn_proc
        return posix_spawn_proc(self._command)

    def _spawn_initial(self) -> bool:
        if not self.running or self._stopped or self._process is not None:
            return False
        try:
            process = self._spawn_process()
        except (FileNotFoundError, OSError) as e:
            logger.error(f"[fMP4Remux:{self.channel_id}] Failed to start remux: {e}")
            self.running = False
            return False
        if not self.running or self._stopped:
            try:
                process.kill()
            except Exception:
                pass
            return False
        self._set_current_slot(process, ProcessSlot(process))
        self._start_slot_threads(self._slot)
        logger.info(f"[fMP4Remux:{self.channel_id}] Remux process started (pid={process.pid})")
        return True

    def stop(self):
        """Stop the process and clear its Redis keys, including when it has already exited.

        A dead process left registered would keep the owner lock and the old init.
        """
        if self._stopped:
            return
        self._stopped = True
        self.running = False
        logger.info(f"[fMP4Remux:{self.channel_id}] Stopping")
        self._join_and_kill()
        self._cleanup_redis()
        logger.info(f"[fMP4Remux:{self.channel_id}] Stopped")

    def _join_and_kill(self):
        try:
            if self._process and self._process.stdin:
                self._process.stdin.close()
        except Exception:
            pass

        if self._writer_thread and self._writer_thread.is_alive():
            try:
                self._writer_thread.join(timeout=5)
            except Exception:
                pass
        if self._slot and self._slot.reader and self._slot.reader.is_alive():
            try:
                self._slot.reader.join(timeout=5)
            except Exception:
                pass

        try:
            if self._process and self._process.poll() is None:
                self._process.kill()
                self._process.wait(timeout=3)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Internal loops
    # ------------------------------------------------------------------

    def _start_slot_threads(self, slot):
        short_id = self.channel_id[:8]
        slot.reader = threading.Thread(
            target=self._reader_loop, args=(slot,), daemon=True,
            name=f"fmp4-reader-{short_id}"
        )
        slot.stderr = threading.Thread(
            target=self._stderr_loop, args=(slot,), daemon=True,
            name=f"fmp4-stderr-{short_id}"
        )
        slot.reader.start()
        slot.stderr.start()

    def _hold_for_pmt(self, chunk: bytes) -> None:
        self._held_chunks.append(chunk)
        self._held_bytes += len(chunk)
        while self._held_bytes > _PRE_PMT_BYTE_LIMIT and len(self._held_chunks) > 1:
            oldest = self._held_chunks.pop(0)
            self._held_bytes -= len(oldest)
            if not self._held_trimmed:
                self._held_trimmed = True
                logger.warning(
                    f"[fMP4Remux:{self.channel_id}] "
                    f"Still waiting for a program map, dropped the oldest held chunks"
                )

    def _write_held(self) -> bool:
        held = self._held_chunks
        self._held_chunks = []
        self._held_bytes = 0
        for chunk in held:
            if not self._write_stdin(chunk):
                return False
        return True

    def _write_stdin(self, data: bytes) -> bool:
        try:
            write_all(self._process, data, is_running=lambda: self.running)
            self._process.stdin.flush()
        except (BrokenPipeError, OSError) as e:
            logger.warning(f"[fMP4Remux:{self.channel_id}] FFmpeg stdin error: {e}")
            # Leave running set. Stderr may still ask for a retry without the filter.
            return False
        return True

    def _command_for(self, fingerprint):
        """Remux argv for a layout, keeping off a filter FFmpeg already refused."""
        if self._filter_rejected:
            return list(FFMPEG_REMUX_CMD_NO_BSF)
        return remux_command_for_layout(fingerprint)

    def _command_matches_layout(self, watcher: PmtLayoutWatcher) -> bool:
        """Replace the process before this chunk is written, when the PMT wants another command."""
        if watcher.fingerprint is None:
            return True
        desired = self._command_for(watcher.fingerprint)
        if desired == self._command:
            return True
        previous = self._command
        self._command = desired
        self._bsf_retry = False
        outcome = self._restart_remux(reason="audio codec requires remux mode change")
        if outcome == RestartOutcome.KEPT:
            self._command = previous
        return outcome != RestartOutcome.STOP

    def _apply_pending_restart(self, fingerprint) -> RestartOutcome:
        """Spawn the replacement deferred at the discontinuity, now that the new PMT is known.

        Until then the old process stays registered, so the server does not
        see a dead process. It has received nothing from the new source.
        """
        reason, self._restart_pending = self._restart_pending, None
        self._filter_rejected = False
        previous = self._command
        self._command = remux_command_for_layout(fingerprint)
        self._bsf_retry = False
        outcome = self._restart_remux(reason)
        if outcome == RestartOutcome.KEPT:
            self._command = previous
        return outcome

    def _feed(self, data: bytes, watcher: PmtLayoutWatcher, chunk_index=None) -> bool:
        def restart(reason, flush=b""):
            self._filter_rejected = False
            if self._process is None:
                # Nothing has spawned yet, so there is no output era to mark.
                self._restart_pending = None
                if watcher.fingerprint is not None:
                    self._command = remux_command_for_layout(watcher.fingerprint)
                    self._bsf_retry = False
                return RestartOutcome.REPLACED
            if self._restart_pending is not None:
                # These bytes belong to the layout this PMT replaces. The
                # default command is AAC, which is wrong when they are not.
                prefix = watcher.fingerprint_before_change
                if self._apply_pending_restart(prefix) == RestartOutcome.STOP:
                    return RestartOutcome.STOP
                # Chunks held from before this map belong ahead of its prefix.
                if not self._write_held():
                    return RestartOutcome.STOP
            if watcher.fingerprint is not None:
                self._command = remux_command_for_layout(watcher.fingerprint)
                self._bsf_retry = False
            return self._restart_remux(reason, flush=flush)

        def write_stdin(chunk: bytes) -> bool:
            if self._process is None:
                self._restart_pending = None
                if watcher.fingerprint is None:
                    self._hold_for_pmt(chunk)
                    return True
                self._command = self._command_for(watcher.fingerprint)
                self._bsf_retry = False
                if not self._spawn_initial():
                    return False
                if not self._write_held():
                    return False
            elif self._restart_pending is not None:
                if watcher.fingerprint is None:
                    self._hold_for_pmt(chunk)
                    return True
                outcome = self._apply_pending_restart(watcher.fingerprint)
                if outcome == RestartOutcome.STOP:
                    return False
                if not self._write_held():
                    return False
            if not self._command_matches_layout(watcher):
                return False
            return self._write_stdin(chunk)

        return feed_chunk_with_layout_watch(
            data, watcher, write_stdin, restart, chunk_index
        )

    def _writer_loop(self):
        behind_seconds = ConfigHelper.new_client_behind_seconds()
        watcher = PmtLayoutWatcher(
            scan_cache=getattr(self.ts_buffer, "psi_scan_cache", None)
        )
        label = f"[fMP4Remux:{self.channel_id}]"

        def on_discontinuity(reason):
            # Defer the spawn until the next write has seen the new PMT.
            # Chunks held from the previous source belong to its map.
            self._held_chunks = []
            self._held_bytes = 0
            self._restart_pending = reason
            return RestartOutcome.REPLACED

        def before_poll(local_index, watcher_arg):
            # Respawn without the filter and reread so the new process sees the PAT/PMT.
            if not self._bsf_retry:
                return None
            self._bsf_retry = False
            self._filter_rejected = True
            self._held_chunks = []
            self._held_bytes = 0
            self._command = list(FFMPEG_REMUX_CMD_NO_BSF)
            outcome = self._restart_remux(
                reason="Non-AAC audio detected, retrying without BSF"
            )
            if outcome == RestartOutcome.STOP:
                return False
            if outcome != RestartOutcome.REPLACED:
                return None
            watcher_arg.reset()
            rewind = (
                self.ts_buffer.find_chunk_index_by_time(behind_seconds)
                if behind_seconds > 0
                else None
            )
            new_index = rewind if rewind is not None else self.ts_buffer.index
            logger.debug(f"{label} BSF retry rewound writer to index {new_index}")
            return new_index

        def on_feed_failure() -> bool:
            if self._stopped:
                return False
            if self._wait_for_bsf_retry():
                return True
            if self._stopped:
                return False
            self.running = False
            return False

        try:
            run_ts_buffer_writer(
                is_running=lambda: self.running,
                ts_buffer=self.ts_buffer,
                behind_seconds=behind_seconds,
                watcher=watcher,
                feed_chunk=self._feed,
                on_discontinuity=on_discontinuity,
                before_poll=before_poll,
                on_feed_failure=on_feed_failure,
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

    def _wait_for_bsf_retry(self, timeout: float = 0.25) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._bsf_retry or self._stopped:
                break
            time.sleep(0.01)
        return self._bsf_retry and not self._stopped

    def _restart_remux(self, reason: str, flush: bytes = b"") -> RestartOutcome:
        if not self.running or self._stopped:
            return RestartOutcome.STOP
        if self._slot is None:
            return RestartOutcome.STOP
        if self._slot.process.poll() is not None:
            # A dead fMP4 process has not stopped the output buffer, so replace it.
            return self._replace_dead_process(reason)

        channel = self.channel_id

        def after_old_retired():
            self._clear_init_segment()
            self._set_state(FMP4_STATE_INITIALIZING)
            try:
                self.fmp4_buffer.mark_discontinuity()
            except Exception as e:
                logger.warning(
                    f"[fMP4Remux:{channel}] Failed to mark output discontinuity: {e}"
                )

        outcome = replace_piped_process(
            is_running=lambda: self.running,
            current_slot=self._slot,
            spawn=self._spawn_process,
            set_current=self._set_current_slot,
            start_slot_threads=self._start_slot_threads,
            after_old_retired=after_old_retired,
            flush=flush,
            log_warning=lambda msg: logger.warning(f"[fMP4Remux:{channel}] {msg}"),
            log_error=lambda msg: logger.error(f"[fMP4Remux:{channel}] {msg}"),
            log_info=lambda msg: logger.info(f"[fMP4Remux:{channel}] {msg}"),
            reason=reason,
            noun="remux",
        )
        if outcome == RestartOutcome.STOP and self.running:
            self.running = False
        return outcome

    def _replace_dead_process(self, reason: str) -> RestartOutcome:
        old = self._slot
        if old is not None:
            old.closing.set()
            old.abandoned.set()
            if old.reader and old.reader.is_alive():
                old.reader.join(timeout=RETIRE_JOIN_SECONDS)
        if not self.running or self._stopped:
            return RestartOutcome.STOP
        try:
            new_process = self._spawn_process()
        except (FileNotFoundError, OSError) as e:
            logger.error(
                f"[fMP4Remux:{self.channel_id}] "
                f"Failed to restart remux ({reason}): {e}"
            )
            self.running = False
            return RestartOutcome.STOP

        self._set_current_slot(new_process, ProcessSlot(new_process))
        self._clear_init_segment()
        self._set_state(FMP4_STATE_INITIALIZING)
        try:
            self.fmp4_buffer.mark_discontinuity()
        except Exception as e:
            logger.warning(
                f"[fMP4Remux:{self.channel_id}] Failed to mark output discontinuity: {e}"
            )
        self._start_slot_threads(self._slot)
        logger.info(
            f"[fMP4Remux:{self.channel_id}] "
            f"Remux restarted after exit (pid={new_process.pid}, {reason})"
        )
        return RestartOutcome.REPLACED

    def _set_current_slot(self, process, slot):
        self._process = process
        self._slot = slot

    def _flush_complete_fragments(self, frag_buf: bytearray) -> None:
        """Publish each complete fragment. One ends where the next moof begins."""
        while len(frag_buf) >= 8:
            if frag_buf[4:8] != b'moof':
                next_moof = _find_moof_offset(frag_buf, start=1)
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

            next_moof = _find_moof_offset(frag_buf, start=moof_size)
            if next_moof < 0:
                break

            fragment = self._clock.patch(bytes(frag_buf[:next_moof]))
            del frag_buf[:next_moof]
            self.fmp4_buffer.put_chunk(fragment)
            logger.debug(
                f"[fMP4Remux:{self.channel_id}] Fragment {self.fmp4_buffer.index}: "
                f"{len(fragment)} bytes"
            )

    def _reader_loop(self, slot):
        """Read stdout. Bytes before the first moof are the init. Each later moof starts a fragment."""
        init_buf = bytearray()
        init_stored = False
        frag_buf = bytearray()
        read_size = 65536
        process = slot.process

        logger.debug(f"[fMP4Remux:{self.channel_id}] Reader started")

        try:
            while self.running and not slot.abandoned.is_set():
                self._refresh_redis_ttls()
                ready, _, _ = select.select([process.stdout], [], [], 1.0)
                if not ready:
                    if process.poll() is not None:
                        logger.info(
                            f"[fMP4Remux:{self.channel_id}] FFmpeg exited "
                            f"(code={process.returncode})"
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
                        f"[fMP4Remux:{self.channel_id}] FFmpeg stdout EOF",
                    )
                    break

                if slot.abandoned.is_set():
                    break

                if not init_stored:
                    init_buf.extend(data)
                    moof_offset = _find_moof_offset(init_buf)

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
            if frag_buf and init_stored and not slot.abandoned.is_set():
                self.fmp4_buffer.put_chunk(self._clock.patch(bytes(frag_buf)))
            # Leave running set. The writer replaces a dead process, and clearing it here would race that.
            logger.info(f"[fMP4Remux:{self.channel_id}] Reader loop exited")

    def _stderr_loop(self, slot):
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
                        logger.warning(f"[fMP4Remux:{self.channel_id}] FFmpeg: {line}")
                    if (
                        "aac_adtstoasc" in line
                        and "not supported" in line
                        and "bitstream filter" in line
                        and "-bsf:a" in self._command
                    ):
                        # Only a global -bsf:a has a fallback. A per-stream refusal
                        # means the audio index was wrong, and "-bsf:a" in the
                        # command list does not match "-bsf:a:N". The writer
                        # restarts so stdin stays on one thread.
                        self._bsf_retry = True
                        return
        except Exception:
            pass

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
        shift = self._clock.begin_era(data)
        if shift:
            logger.info(
                f"[fMP4Remux:{self.channel_id}] "
                f"Media clock continues at {shift:.3f}s"
            )
        redis_buf = RedisClient.get_buffer()
        if redis_buf:
            redis_buf.setex(RedisKeys.output_init(self.channel_id, self.fmt), FMP4_KEY_TTL, data)

    def _clear_init_segment(self):
        redis_buf = RedisClient.get_buffer()
        if redis_buf:
            try:
                redis_buf.delete(RedisKeys.output_init(self.channel_id, self.fmt))
            except Exception:
                pass

    def _refresh_redis_ttls(self):
        """Refresh owner, state, and init TTLs, but not on every fragment."""
        now = time.time()
        if now - self._last_ttl_refresh < FMP4_TTL_REFRESH_INTERVAL:
            return
        self._last_ttl_refresh = now
        if not self._redis:
            return
        try:
            owner_key = RedisKeys.output_owner(self.channel_id, self.fmt)
            state_key = RedisKeys.output_state(self.channel_id, self.fmt)
            pipe = self._redis.pipeline()
            pipe.expire(owner_key, FMP4_KEY_TTL)
            pipe.expire(state_key, FMP4_KEY_TTL)
            pipe.execute()
            redis_buf = RedisClient.get_buffer()
            if redis_buf is not None:
                redis_buf.expire(
                    RedisKeys.output_init(self.channel_id, self.fmt), FMP4_KEY_TTL
                )
        except Exception as e:
            logger.debug(
                f"[fMP4Remux:{self.channel_id}] TTL refresh failed: {e}"
            )

    def _cleanup_redis(self):
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
