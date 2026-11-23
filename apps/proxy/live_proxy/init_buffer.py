"""Channel init readiness: chunk gate vs experimental stream-time buffer.

Non-experimental channels still promote once ``INITIAL_BEHIND_CHUNKS`` Redis
chunks exist. With experimental ingest on, promotion waits for stream-time
depth from chunk end PTS minus the oldest chunk start PTS:

- Prefer the full New Client Buffer depth.
- Once Stream Ready Minimum Buffer is met, wait up to Stream Ready Buffer
  Wait (wall clock) for the rest, then promote with whatever depth is
  available. The minimum is capped at New Client Buffer when that target is
  above 0, so a higher minimum has no separate wait.
- Never promote below the minimum. Stuck fills rely on existing init / startup
  timeouts rather than promoting a short buffer.
"""

import time
from dataclasses import dataclass

from .chunk_time_lookup import media_score_depth_seconds
from .config_helper import ConfigHelper
from .constants import ChannelMetadataField
from .redis_keys import RedisKeys
from .utils import get_logger

logger = get_logger()
# Channels that already logged a depth-read failure. Later polls stay quiet.
_depth_error_logged = set()


def clear_depth_error_log(channel_id=None):
    """Drop depth-failure silence for one channel, or all channels when omitted."""
    if channel_id is None:
        _depth_error_logged.clear()
        return
    _depth_error_logged.discard(channel_id)


def _truthy_redis_flag(raw):
    """Parse a Redis hash flag stored as ``1``/``0`` or common truthy strings.

    Returns None for a missing or unrecognized value so callers can fall back.
    """
    if raw is None:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode()
    text = str(raw).strip().lower()
    if text in ("1", "true", "yes"):
        return True
    if text in ("0", "false", "no", ""):
        return False
    return None


@dataclass(frozen=True)
class InitBufferStatus:
    """Snapshot from one readiness evaluation (for callers / logging)."""

    ready: bool
    experimental: bool
    buffer_index: int
    media_depth: float | None
    behind_seconds: float
    min_seconds: float
    max_wait_seconds: float
    chunks_needed: int = 0
    wait_elapsed: float | None = None

    def progress_label(self):
        """Short human-readable fill progress using values already measured."""
        if not self.experimental:
            return f"{self.buffer_index}/{self.chunks_needed} chunks"

        depth = self.media_depth
        if depth is None:
            return "no media scores yet"

        target = self.behind_seconds if self.behind_seconds > 0 else self.min_seconds
        label = f"{depth:.1f}/{target:.1f}s stream"
        if (
            self.behind_seconds > 0
            and self.min_seconds <= depth < self.behind_seconds
            and self.wait_elapsed is not None
        ):
            remaining = max(0.0, self.max_wait_seconds - self.wait_elapsed)
            return f"{label} (min met, max-wait {remaining:.1f}s left)"
        if depth < self.min_seconds:
            return f"{label} (min {self.min_seconds:.1f}s)"
        return label


def effective_init_min_buffer_seconds(behind_seconds, min_seconds):
    """Clamp the configured minimum so it never exceeds the join target.

    When New Client Buffer is 0 (start at live), the minimum alone gates init.
    """
    behind = max(0.0, float(behind_seconds or 0))
    minimum = max(0.0, float(min_seconds or 0))
    if behind <= 0:
        return minimum
    return min(minimum, behind)


def evaluate_init_buffer_ready(
    *,
    experimental,
    buffer_index,
    media_depth,
    behind_seconds,
    min_seconds,
    max_wait_seconds,
    min_reached_at,
    chunks_needed=None,
    now=None,
):
    """Return ``(ready, next_min_reached_at, status)`` for channel init promotion.

    Pure: every input is passed in, nothing is read from settings or Redis.

    ``media_depth`` is stream-time seconds (or None when unscored).
    ``chunks_needed`` is the chunk-count gate and is required when
    ``experimental`` is False; it is ignored otherwise.
    ``min_reached_at`` is a wall-clock timestamp set when the minimum was first
    observed; pass None until that happens. ``next_min_reached_at`` is the
    anchor for the caller to store for subsequent polls, or None when no
    max-wait clock applies (chunk gate, below the minimum, full target met, or
    no New Client Buffer to wait for).
    """
    now = time.time() if now is None else float(now)
    behind = max(0.0, float(behind_seconds or 0))
    minimum = effective_init_min_buffer_seconds(behind, min_seconds)
    max_wait = max(0.0, float(max_wait_seconds or 0))
    index = int(buffer_index or 0)

    def status(ready, depth=None, wait_elapsed=None, chunks=0):
        return InitBufferStatus(
            ready=ready,
            experimental=bool(experimental),
            buffer_index=index,
            media_depth=depth,
            behind_seconds=behind,
            min_seconds=minimum,
            max_wait_seconds=max_wait,
            chunks_needed=chunks,
            wait_elapsed=wait_elapsed,
        )

    if not experimental:
        if chunks_needed is None:
            raise ValueError("chunks_needed is required when experimental is False")
        ready = index >= chunks_needed
        return ready, None, status(ready, chunks=int(chunks_needed))

    depth = media_depth
    if depth is None:
        return False, None, status(False)

    if behind > 0 and depth >= behind:
        # Drop the max-wait anchor so a later short fill starts a fresh clock.
        return True, None, status(True, depth)

    if depth < minimum:
        return False, None, status(False, depth)

    if behind <= 0:
        # Min alone gates init; no max-wait clock.
        return True, None, status(True, depth)

    reached_at = min_reached_at if min_reached_at is not None else now
    wait_elapsed = max(0.0, now - reached_at)
    ready = wait_elapsed >= max_wait
    return ready, reached_at, status(ready, depth, wait_elapsed)


def channel_init_buffer_ready(channel_id, redis_client, stream_manager=None, now=None):
    """Return ``(ready, status)`` for the active init gate.

    Depth comes from Redis media scores, so a worker that does not own the
    ingest buffer can still promote. The max-wait anchor is stored on channel
    metadata for the same reason.

    Experimental vs chunk-count gating uses, in order: the owner
    ``stream_manager``'s frozen flag when provided, else
    ``ChannelMetadataField.EXPERIMENTAL_INGEST_BUFFER`` on metadata (written at
    owner start), else the live ``ConfigHelper`` setting for legacy channels.
    """
    if not redis_client:
        empty = InitBufferStatus(
            ready=False,
            experimental=False,
            buffer_index=0,
            media_depth=None,
            behind_seconds=0.0,
            min_seconds=0.0,
            max_wait_seconds=0.0,
        )
        return False, empty

    metadata_key = RedisKeys.channel_metadata(channel_id)
    clock_field = ChannelMetadataField.INIT_MIN_BUFFER_REACHED_AT
    experimental_field = ChannelMetadataField.EXPERIMENTAL_INGEST_BUFFER

    # Owner freeze, then Redis (written at CONNECTING), then live setting.
    experimental = ConfigHelper.experimental_ingest_buffer()
    if stream_manager is not None:
        experimental = bool(
            getattr(stream_manager, "experimental_ingest_buffer", experimental)
        )
    else:
        try:
            frozen = _truthy_redis_flag(
                redis_client.hget(metadata_key, experimental_field)
            )
            if frozen is not None:
                experimental = frozen
        except Exception:
            pass

    try:
        buffer_index = int(redis_client.get(RedisKeys.buffer_index(channel_id)) or 0)
    except (TypeError, ValueError):
        buffer_index = 0

    media_depth = None
    depth_read_failed = False
    if experimental:
        try:
            media_depth = media_score_depth_seconds(
                redis_client,
                RedisKeys.chunk_media_scores(channel_id),
                RedisKeys.buffer_discontinuities(channel_id),
                buffer_index,
                starts_key=RedisKeys.chunk_media_starts(channel_id),
            )
        except Exception as e:
            depth_read_failed = True
            media_depth = None
            if channel_id not in _depth_error_logged:
                _depth_error_logged.add(channel_id)
                logger.warning(
                    f"Init buffer depth read failed for channel {channel_id}: {e}"
                )

    min_reached_at = None
    clock_known = True
    if experimental:
        try:
            raw = redis_client.hget(metadata_key, clock_field)
            if raw:
                if isinstance(raw, bytes):
                    raw = raw.decode()
                min_reached_at = float(raw)
        except Exception:
            # Unknown anchor. Do not invent a new one below.
            clock_known = False
            min_reached_at = None

    ready, next_reached_at, status = evaluate_init_buffer_ready(
        experimental=experimental,
        buffer_index=buffer_index,
        media_depth=media_depth,
        behind_seconds=ConfigHelper.new_client_behind_seconds(),
        min_seconds=ConfigHelper.init_min_buffer_seconds(),
        max_wait_seconds=ConfigHelper.init_buffer_max_wait_seconds(),
        min_reached_at=min_reached_at,
        chunks_needed=None if experimental else ConfigHelper.initial_behind_chunks(),
        now=now,
    )

    # A failed depth or clock read must leave the stored anchor alone. An
    # empty timeline still returns no depth and clears it.
    if experimental and not depth_read_failed and clock_known:
        try:
            if next_reached_at is None:
                if min_reached_at is not None:
                    redis_client.hdel(metadata_key, clock_field)
            elif min_reached_at != next_reached_at:
                redis_client.hset(metadata_key, clock_field, str(next_reached_at))
        except Exception:
            pass

    return ready, status
