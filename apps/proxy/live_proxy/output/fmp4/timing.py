"""Continue fMP4 decode times and fragment numbers across remux restarts.

Each process starts both at zero. A client that keeps the first init then
drops audio when the clock jumps backwards. PublishedClock adds the end of
what was already published to each track's tfdt and continues the mfhd
sequence. Only those header fields change, so no box grows, and the init
is left as FFmpeg wrote it.
"""

from __future__ import annotations

import struct
import threading

from ...utils import get_logger

logger = get_logger()

# Boxes whose children are more boxes. mdat and the sample tables are not.
_CONTAINER_BOXES = frozenset({
    b"moov", b"trak", b"mdia", b"minf", b"stbl", b"mvex", b"edts",
    b"moof", b"traf",
})

_TFHD_DEFAULT_DURATION = 0x000008
_TFHD_BASE_DATA_OFFSET = 0x000001
_TFHD_SAMPLE_DESCRIPTION = 0x000002
_TRUN_DATA_OFFSET = 0x000001
_TRUN_FIRST_FLAGS = 0x000004
_TRUN_SAMPLE_DURATION = 0x000100
_TRUN_SAMPLE_SIZE = 0x000200
_TRUN_SAMPLE_FLAGS = 0x000400
_TRUN_COMPOSITION_OFFSET = 0x000800


def _iter_boxes(data: bytes, start: int = 0, end: int | None = None):
    """Yield ``(type, payload_start, payload_end)`` for each box that fits. Stop on a truncated box."""
    if end is None:
        end = len(data)
    offset = start
    while offset + 8 <= end:
        size = struct.unpack_from(">I", data, offset)[0]
        box_type = data[offset + 4:offset + 8]
        header = 8
        if size == 1:
            if offset + 16 > end:
                return
            size = struct.unpack_from(">Q", data, offset + 8)[0]
            header = 16
        elif size == 0:
            size = end - offset
        if size < header or offset + size > end:
            return
        yield box_type, offset + header, offset + size
        offset += size


def _walk_boxes(data: bytes, start: int, end: int):
    """Like ``_iter_boxes``, including boxes nested inside container boxes."""
    for box_type, payload_start, payload_end in _iter_boxes(data, start, end):
        yield box_type, payload_start, payload_end
        if box_type in _CONTAINER_BOXES:
            yield from _walk_boxes(data, payload_start, payload_end)


def _versioned_field(payload: bytes, version0_at: int, version1_at: int):
    """One big-endian 32-bit field. A version 1 box stores it later than version 0."""
    if not payload:
        return None
    at = version1_at if payload[0] == 1 else version0_at
    if len(payload) < at + 4:
        return None
    return struct.unpack_from(">I", payload, at)[0]


def init_track_timing(data: bytes) -> tuple[dict, dict]:
    """``(track_id -> timescale, track_id -> trex default sample duration)``."""
    timescales: dict[int, int] = {}
    defaults: dict[int, int] = {}
    for box_type, start, end in _iter_boxes(data):
        if box_type != b"moov":
            continue
        for child, child_start, child_end in _iter_boxes(data, start, end):
            if child == b"trak":
                track_id = None
                timescale = None
                for leaf, leaf_start, leaf_end in _walk_boxes(data, child_start, child_end):
                    payload = data[leaf_start:leaf_end]
                    if leaf == b"tkhd":
                        track_id = _versioned_field(payload, 12, 20)
                    elif leaf == b"mdhd":
                        timescale = _versioned_field(payload, 12, 20)
                if track_id and timescale:
                    timescales[track_id] = timescale
            elif child == b"mvex":
                for leaf, leaf_start, leaf_end in _iter_boxes(data, child_start, child_end):
                    if leaf != b"trex" or leaf_end - leaf_start < 20:
                        continue
                    payload = data[leaf_start:leaf_end]
                    track_id = struct.unpack_from(">I", payload, 4)[0]
                    defaults[track_id] = struct.unpack_from(">I", payload, 12)[0]
    return timescales, defaults


def _tfhd_track(payload: bytes):
    """``(track_id, default_sample_duration or None)`` from a tfhd payload."""
    if len(payload) < 8:
        return None
    flags = struct.unpack_from(">I", payload, 0)[0] & 0xFFFFFF
    track_id = struct.unpack_from(">I", payload, 4)[0]
    pos = 8
    if flags & _TFHD_BASE_DATA_OFFSET:
        pos += 8
    if flags & _TFHD_SAMPLE_DESCRIPTION:
        pos += 4
    default_duration = None
    if flags & _TFHD_DEFAULT_DURATION:
        if pos + 4 > len(payload):
            return None
        default_duration = struct.unpack_from(">I", payload, pos)[0]
    return track_id, default_duration


def _tfdt_base(payload: bytes):
    if len(payload) < 8:
        return None
    if payload[0] == 1:
        if len(payload) < 12:
            return None
        return struct.unpack_from(">Q", payload, 4)[0]
    return struct.unpack_from(">I", payload, 4)[0]


def _trun_bounds(payload: bytes, default_duration, base: int):
    """``(presentation_end, next_decode)`` in ticks.

    Presentation end adds the composition offset. ``next_decode`` is where
    the following trun in this fragment continues.
    """
    if len(payload) < 8 or default_duration is None:
        return None
    version = payload[0]
    flags = struct.unpack_from(">I", payload, 0)[0] & 0xFFFFFF
    sample_count = struct.unpack_from(">I", payload, 4)[0]
    pos = 8
    if flags & _TRUN_DATA_OFFSET:
        pos += 4
    if flags & _TRUN_FIRST_FLAGS:
        pos += 4
    dts = base
    presentation_end = base
    saw_sample = False
    for _ in range(sample_count):
        duration = default_duration
        composition = 0
        if flags & _TRUN_SAMPLE_DURATION:
            if pos + 4 > len(payload):
                break
            duration = struct.unpack_from(">I", payload, pos)[0]
            pos += 4
        if flags & _TRUN_SAMPLE_SIZE:
            pos += 4
        if flags & _TRUN_SAMPLE_FLAGS:
            pos += 4
        if flags & _TRUN_COMPOSITION_OFFSET:
            width = 8 if version == 1 else 4
            if pos + width > len(payload):
                break
            if version == 1:
                composition = struct.unpack_from(">q", payload, pos)[0]
            else:
                composition = struct.unpack_from(">i", payload, pos)[0]
            pos += width
        sample_end = dts + duration + composition
        if sample_end > presentation_end:
            presentation_end = sample_end
        dts += duration
        saw_sample = True
    if not saw_sample:
        return None
    return presentation_end, dts


def fragment_media_end(data: bytes, timescales: dict, default_durations: dict):
    """Seconds to the latest sample end, on this fragment's own clock.

    None when no sample belongs to a track whose timescale is known. After
    ``PublishedClock.patch`` the fragment's clock is the channel clock.
    """
    furthest = None
    for box_type, start, end in _iter_boxes(data):
        if box_type != b"moof":
            continue
        for child, child_start, child_end in _iter_boxes(data, start, end):
            if child != b"traf":
                continue
            track_id = None
            default_duration = None
            base = None
            presentation_end = None
            for leaf, leaf_start, leaf_end in _iter_boxes(data, child_start, child_end):
                payload = data[leaf_start:leaf_end]
                if leaf == b"tfhd":
                    parsed = _tfhd_track(payload)
                    if parsed is None:
                        continue
                    track_id, default_duration = parsed
                    if default_duration is None:
                        default_duration = default_durations.get(track_id)
                elif leaf == b"tfdt":
                    base = _tfdt_base(payload)
                elif leaf == b"trun" and track_id and base is not None:
                    bounds = _trun_bounds(payload, default_duration, base)
                    if bounds is None:
                        continue
                    sample_end, base = bounds
                    if presentation_end is None or sample_end > presentation_end:
                        presentation_end = sample_end
            timescale = timescales.get(track_id) if track_id else None
            if not timescale or presentation_end is None:
                continue
            seconds = presentation_end / timescale
            if furthest is None or seconds > furthest:
                furthest = seconds
    return furthest


class PublishedClock:
    """Channel timeline continued across remux processes.

    The lock only covers a retired reader overlapping the next. Successive
    readers do not run together.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._end = 0.0
        self._sequence = 0
        self._sequence_shift = 0
        self._tick_shift: dict[int, int] = {}
        self._timescales: dict[int, int] = {}
        self._default_durations: dict[int, int] = {}
        self._warned_overflow = False

    @property
    def end(self) -> float:
        with self._lock:
            return self._end

    def begin_era(self, init: bytes) -> float:
        """Record this process's timescales. Returns the shift in seconds, 0 for the first process."""
        try:
            timescales, defaults = init_track_timing(init)
        except Exception:
            logger.warning("Could not read track timescales from init", exc_info=True)
            timescales, defaults = {}, {}
        with self._lock:
            self._timescales = timescales
            self._default_durations = defaults
            self._sequence_shift = self._sequence
            self._tick_shift = {
                track_id: round(self._end * scale)
                for track_id, scale in timescales.items()
            }
            return self._end

    def patch(self, fragment: bytes) -> bytes:
        """Move ``fragment`` onto the channel timeline and record how far it reaches.

        Returns the same object when the shift is zero. Otherwise a copy,
        with the sequence number and each track's tfdt updated.
        """
        with self._lock:
            try:
                patched = self._shift(fragment)
                end = fragment_media_end(
                    patched, self._timescales, self._default_durations
                )
            except Exception:
                logger.debug("Could not read fragment timing", exc_info=True)
                return fragment
            if end is not None and end > self._end:
                self._end = end
            return patched

    def _shift(self, fragment: bytes) -> bytes:
        writes: list[tuple[int, bytes]] = []
        for box_type, start, end in _iter_boxes(fragment):
            if box_type != b"moof":
                continue
            children = list(_iter_boxes(fragment, start, end))
            for child, child_start, child_end in children:
                if child == b"mfhd" and child_end - child_start >= 8:
                    sequence = struct.unpack_from(">I", fragment, child_start + 4)[0]
                    shifted = sequence + self._sequence_shift
                    self._sequence = max(self._sequence, shifted)
                    if self._sequence_shift:
                        writes.append((child_start + 4, struct.pack(">I", shifted)))
                elif child == b"traf":
                    self._shift_traf(fragment, child_start, child_end, writes)
        if not writes:
            return fragment
        patched = bytearray(fragment)
        for offset, value in writes:
            patched[offset:offset + len(value)] = value
        return bytes(patched)

    def _shift_traf(self, fragment, start, end, writes) -> None:
        leaves = list(_iter_boxes(fragment, start, end))
        track_id = None
        for leaf, leaf_start, leaf_end in leaves:
            if leaf == b"tfhd":
                parsed = _tfhd_track(fragment[leaf_start:leaf_end])
                if parsed is not None:
                    track_id = parsed[0]
                break
        ticks = self._tick_shift.get(track_id, 0) if track_id else 0
        if not ticks:
            return
        for leaf, leaf_start, leaf_end in leaves:
            if leaf != b"tfdt":
                continue
            version = fragment[leaf_start]
            if version == 1 and leaf_end - leaf_start >= 12:
                base = struct.unpack_from(">Q", fragment, leaf_start + 4)[0]
                writes.append((leaf_start + 4, struct.pack(">Q", base + ticks)))
            elif version == 0 and leaf_end - leaf_start >= 8:
                base = struct.unpack_from(">I", fragment, leaf_start + 4)[0]
                if base + ticks <= 0xFFFFFFFF:
                    writes.append((leaf_start + 4, struct.pack(">I", base + ticks)))
                elif not self._warned_overflow:
                    # A 32-bit tfdt cannot hold the shift, and the box cannot grow in place.
                    self._warned_overflow = True
                    logger.warning(
                        "fMP4 decode time does not fit 32 bits, clock not continued"
                    )
            return
