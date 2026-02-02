"""
Centralized plugin event serialization.

Each event type has a serializer that knows how to extract relevant data
from the object. Call sites just pass the event name and object.

Event levels control which events are emitted (cumulative):
- NONE: No events emitted
- CRITICAL: Critical events only (errors, security failures)
- SYSTEM: CRITICAL + system lifecycle events (auth, plugins, startup)
- FULL: SYSTEM + all operational events (channels, streams, VOD, etc.)

Events in DISABLED_EVENTS are never emitted regardless of level.

Configuration priority:
1. DISPATCHARR_EVENT_LEVEL environment variable
2. CoreSettings system_settings.event_level
3. Default: FULL
"""
import logging
import os
import re
import threading
import time

logger = logging.getLogger(__name__)

# =============================================================================
# EVENT LEVEL CONFIGURATION
# =============================================================================
# This is the single source of truth for which events are emitted at each level.
# Levels are CUMULATIVE: SYSTEM includes CRITICAL, FULL includes SYSTEM.
# Every event in EVENT_SERIALIZERS must appear in exactly one of these sets.
# =============================================================================

# CRITICAL: Security failures, errors that need immediate attention
CRITICAL_EVENTS = {
    "auth.login_failed",
    "channel.error",
    "epg.refresh_failed",
    "m3u.refresh_failed",
    "recording.interrupted",
}

# SYSTEM: Authentication, plugin lifecycle, system startup/shutdown
# (These are emitted at SYSTEM level and above, cumulative with CRITICAL)
SYSTEM_EVENTS = {
    "auth.login",
    "auth.logout",
    "system.startup",
    "system.shutdown",
    "plugin.enabled",
    "plugin.disabled",
    "plugin.configured",
}

# FULL: All operational events - channels, streams, recordings, VOD, EPG, M3U
# (These are only emitted at FULL level)
FULL_EVENTS = {
    # Recording events
    "recording.scheduled",
    "recording.started",
    "recording.completed",
    "recording.cancelled",
    "recording.deleted",
    "recording.changed",
    "recording.comskip_completed",
    "recording.bulk_cancelled",
    # EPG events
    "epg.source_created",
    "epg.source_deleted",
    "epg.source_enabled",
    "epg.source_disabled",
    "epg.refresh_started",
    "epg.refresh_completed",
    # M3U events
    "m3u.source_created",
    "m3u.source_deleted",
    "m3u.source_enabled",
    "m3u.source_disabled",
    "m3u.refresh_started",
    "m3u.refresh_completed",
    # Channel lifecycle events
    "channel.created",
    "channel.deleted",
    "channel.updated",
    "channel.stream_added",
    "channel.stream_removed",
    # Channel runtime events
    "channel.client_connected",
    "channel.client_disconnected",
    "channel.stream_started",
    "channel.stream_stopped",
    "channel.buffering",
    "channel.failover",
    "channel.reconnected",
    "channel.stream_switched",
    # Stream events
    "stream.created",
    "stream.updated",
    "stream.deleted",
    # Channel group events
    "channel_group.created",
    "channel_group.updated",
    "channel_group.deleted",
    # Channel profile events
    "channel_profile.created",
    "channel_profile.updated",
    "channel_profile.deleted",
    # Recording rule events
    "recording_rule.created",
    "recording_rule.updated",
    "recording_rule.deleted",
    # VOD events
    "vod.movie_created",
    "vod.movie_deleted",
    "vod.series_created",
    "vod.series_deleted",
    "vod.episode_created",
    "vod.episode_deleted",
}

# DISABLED: Events that have serializers but are intentionally never emitted
# Use this for deprecated events or events reserved for future use
DISABLED_EVENTS = set()

# =============================================================================
# END EVENT LEVEL CONFIGURATION
# =============================================================================

# Event level constants (higher = more verbose)
EVENT_LEVEL_NONE = 0
EVENT_LEVEL_CRITICAL = 10
EVENT_LEVEL_SYSTEM = 20
EVENT_LEVEL_FULL = 30

EVENT_LEVELS = {
    "NONE": EVENT_LEVEL_NONE,
    "CRITICAL": EVENT_LEVEL_CRITICAL,
    "SYSTEM": EVENT_LEVEL_SYSTEM,
    "FULL": EVENT_LEVEL_FULL,
}

# Level name lookup for API responses
EVENT_LEVEL_NAMES = {v: k for k, v in EVENT_LEVELS.items()}


def _build_event_level_map():
    """Build the event-to-level mapping from the configuration sets."""
    level_map = {}
    for event in CRITICAL_EVENTS:
        level_map[event] = EVENT_LEVEL_CRITICAL
    for event in SYSTEM_EVENTS:
        level_map[event] = EVENT_LEVEL_SYSTEM
    for event in FULL_EVENTS:
        level_map[event] = EVENT_LEVEL_FULL
    return level_map


EVENT_LEVEL_MAP = _build_event_level_map()


# =============================================================================
# EVENT LEVEL CACHING
# =============================================================================
_event_level_cache = None
_event_level_cache_time = 0
_EVENT_LEVEL_CACHE_TTL = 60  # Cache for 60 seconds
_event_level_cache_lock = threading.Lock()


def get_event_level():
    """
    Get the configured event level with caching.

    Priority:
    1. DISPATCHARR_EVENT_LEVEL environment variable (no caching - always fresh)
    2. CoreSettings system_settings.event_level (cached for 60 seconds)
    3. Default: FULL

    Thread-safe: uses a lock to prevent race conditions on cache access.
    """
    global _event_level_cache, _event_level_cache_time

    # Check environment variable first (highest priority, no caching needed)
    env_level = os.environ.get("DISPATCHARR_EVENT_LEVEL", "").upper()
    if env_level and env_level in EVENT_LEVELS:
        return EVENT_LEVELS[env_level]

    with _event_level_cache_lock:
        # Check cache (inside lock to prevent race conditions)
        current_time = time.time()
        if _event_level_cache is not None and (current_time - _event_level_cache_time) < _EVENT_LEVEL_CACHE_TTL:
            return _event_level_cache

        # Cache miss - check CoreSettings (avoid import at module level to prevent circular imports)
        try:
            from core.models import CoreSettings
            settings_level = CoreSettings.get_system_settings().get("event_level", "").upper()
            if settings_level and settings_level in EVENT_LEVELS:
                result = EVENT_LEVELS[settings_level]
                _event_level_cache = result
                _event_level_cache_time = current_time
                return result
        except Exception:
            # Database may not be ready yet (migrations, etc.)
            pass

        # Default to FULL and cache it
        _event_level_cache = EVENT_LEVEL_FULL
        _event_level_cache_time = current_time
        return EVENT_LEVEL_FULL


def invalidate_event_level_cache():
    """Invalidate the event level cache. Call this when settings change."""
    global _event_level_cache, _event_level_cache_time
    with _event_level_cache_lock:
        _event_level_cache = None
        _event_level_cache_time = 0


def should_emit_event(event_name: str) -> bool:
    """
    Check if an event should be emitted based on the configured level.

    Returns False if:
    - Event is in DISABLED_EVENTS
    - Configured level is NONE
    - Event's level is higher than configured level
    - Event is unknown (not in any level set)
    """
    # Never emit disabled events
    if event_name in DISABLED_EVENTS:
        return False

    configured_level = get_event_level()
    if configured_level == EVENT_LEVEL_NONE:
        return False

    # Unknown events are not emitted (fail closed)
    event_level = EVENT_LEVEL_MAP.get(event_name)
    if event_level is None:
        logger.warning(f"Unknown event '{event_name}' - not configured in any level set")
        return False

    return event_level <= configured_level


def validate_event_configuration():
    """
    Validate that every event in EVENT_SERIALIZERS is configured in exactly one level set.

    This should be called at application startup to catch configuration errors early.

    Raises:
        ValueError: If any event is missing from level sets or appears in multiple sets.
    """
    all_configured = CRITICAL_EVENTS | SYSTEM_EVENTS | FULL_EVENTS | DISABLED_EVENTS

    # Check for events in multiple sets
    sets_to_check = [
        ("CRITICAL_EVENTS", CRITICAL_EVENTS),
        ("SYSTEM_EVENTS", SYSTEM_EVENTS),
        ("FULL_EVENTS", FULL_EVENTS),
        ("DISABLED_EVENTS", DISABLED_EVENTS),
    ]

    for i, (name1, set1) in enumerate(sets_to_check):
        for name2, set2 in sets_to_check[i + 1:]:
            overlap = set1 & set2
            if overlap:
                raise ValueError(
                    f"Events appear in multiple level sets ({name1} and {name2}): {overlap}"
                )

    # Check for events with serializers but no level configuration
    missing = set(EVENT_SERIALIZERS.keys()) - all_configured
    if missing:
        raise ValueError(
            f"Events have serializers but no level configuration: {missing}. "
            f"Add them to CRITICAL_EVENTS, SYSTEM_EVENTS, FULL_EVENTS, or DISABLED_EVENTS."
        )

    # Check for level configurations without serializers (warning only)
    extra = all_configured - set(EVENT_SERIALIZERS.keys())
    if extra:
        logger.warning(
            f"Events configured in level sets but have no serializer: {extra}"
        )

    logger.info(
        f"Event configuration validated: {len(CRITICAL_EVENTS)} critical, "
        f"{len(SYSTEM_EVENTS)} system, {len(FULL_EVENTS)} full, "
        f"{len(DISABLED_EVENTS)} disabled"
    )


# =============================================================================
# ERROR MESSAGE SANITIZATION
# =============================================================================

def _sanitize_error_message(error: str, max_length: int = 500) -> str:
    """
    Sanitize error messages to remove sensitive information.

    Removes:
    - File paths
    - Credentials from URLs
    - Truncates long messages
    """
    if not error:
        return error

    error = str(error)

    # Remove file paths (Unix and Windows style)
    error = re.sub(r'(/[^\s:]+)+', '[PATH]', error)
    error = re.sub(r'([A-Za-z]:\\[^\s:]+)+', '[PATH]', error)

    # Remove credentials from URLs (user:pass@host pattern)
    error = re.sub(
        r'(https?://)[^:]+:[^@]+@',
        r'\1[CREDENTIALS]@',
        error
    )

    # Truncate very long errors
    if len(error) > max_length:
        error = error[:max_length] + "... [truncated]"

    return error


# =============================================================================
# GENERIC SERIALIZER FACTORIES
# =============================================================================

def _make_simple_serializer(id_field: str, name_field: str, extra_fields: list = None):
    """
    Factory for creating simple id+name serializers.

    Args:
        id_field: Name of the ID field in the output (e.g., "stream_id")
        name_field: Name of the name field in the output (e.g., "stream_name")
        extra_fields: Optional list of (attr_name, output_key) tuples for additional fields
    """
    extra_fields = extra_fields or []

    def serializer(obj, **ctx):
        result = {
            id_field: obj.id,
            name_field: obj.name,
        }
        for attr_name, output_key in extra_fields:
            result[output_key] = getattr(obj, attr_name, None)
        return result

    return serializer


def _make_context_serializer(fields: list):
    """
    Factory for creating serializers that pull all data from context.

    Args:
        fields: List of field names to extract from context
    """
    def serializer(obj, **ctx):
        return {field: ctx.get(field) for field in fields}

    return serializer


# =============================================================================
# RECORDING SERIALIZERS (Complex - need custom implementations)
# =============================================================================

def _serialize_recording_scheduled(recording, **ctx):
    # Use context if provided (avoids N+1 queries), otherwise access directly
    return {
        "recording_id": recording.id,
        "channel_id": recording.channel_id,
        "channel_name": ctx.get("channel_name") or (recording.channel.name if recording.channel else None),
        "start_time": str(recording.start_time),
        "end_time": str(recording.end_time),
        "program_name": ctx.get("program_name") or (
            recording.airing.programme.title
            if recording.airing and recording.airing.programme
            else None
        ),
    }


def _serialize_recording_started(recording, **ctx):
    # May receive a Recording object or just context with IDs
    if recording:
        return {
            "recording_id": recording.id,
            "channel_id": recording.channel_id,
            "channel_name": ctx.get("channel_name") or (recording.channel.name if recording.channel else None),
            "start_time": str(recording.start_time),
            "end_time": str(recording.end_time),
        }
    # Fallback for when we only have context data
    return {
        "recording_id": ctx.get("recording_id"),
        "channel_id": ctx.get("channel_id"),
        "channel_name": ctx.get("channel_name"),
        "start_time": ctx.get("start_time"),
        "end_time": ctx.get("end_time"),
    }


def _serialize_recording_completed(recording, **ctx):
    cp = recording.custom_properties or {} if recording else {}
    return {
        "recording_id": recording.id if recording else ctx.get("recording_id"),
        "channel_id": ctx.get("channel_id") or (recording.channel_id if recording else None),
        "channel_name": ctx.get("channel_name"),
        "file_path": cp.get("file_path") or ctx.get("file_path"),
        "duration_seconds": ctx.get("duration_seconds"),
    }


def _serialize_recording_interrupted(recording, **ctx):
    cp = recording.custom_properties or {} if recording else {}
    return {
        "recording_id": recording.id if recording else ctx.get("recording_id"),
        "channel_id": ctx.get("channel_id") or (recording.channel_id if recording else None),
        "channel_name": ctx.get("channel_name"),
        "file_path": cp.get("file_path") or ctx.get("file_path"),
        "reason": _sanitize_error_message(ctx.get("reason") or cp.get("interrupted_reason")),
    }


def _serialize_recording_cancelled(recording, **ctx):
    return {
        "recording_id": recording.id,
        "channel_id": recording.channel_id,
        "channel_name": ctx.get("channel_name") or (recording.channel.name if recording.channel else None),
        "start_time": str(recording.start_time),
        "end_time": str(recording.end_time),
    }


def _serialize_recording_deleted(recording, **ctx):
    cp = recording.custom_properties or {}
    return {
        "recording_id": recording.id,
        "channel_id": recording.channel_id,
        "channel_name": ctx.get("channel_name") or (recording.channel.name if recording.channel else None),
        "file_path": cp.get("file_path"),
        "status": cp.get("status"),
    }


def _serialize_recording_changed(recording, **ctx):
    return {
        "recording_id": recording.id,
        "channel_id": recording.channel_id,
        "start_time": str(recording.start_time),
        "end_time": str(recording.end_time),
        "previous_start_time": ctx.get("previous_start_time"),
        "previous_end_time": ctx.get("previous_end_time"),
    }


def _serialize_recording_comskip_completed(recording, **ctx):
    return {
        "recording_id": recording.id if recording else ctx.get("recording_id"),
        "commercials_found": ctx.get("commercials_found"),
        "segments_kept": ctx.get("segments_kept"),
    }


def _serialize_recording_bulk_cancelled(obj, **ctx):
    return {
        "count": ctx.get("count"),
    }


# =============================================================================
# EPG SERIALIZERS
# =============================================================================

def _serialize_epg_source_created(source, **ctx):
    return {
        "source_id": source.id,
        "source_name": source.name,
        "source_type": source.source_type,
    }


def _serialize_epg_source_deleted(source, **ctx):
    return {
        "source_id": source.id if source else ctx.get("source_id"),
        "source_name": source.name if source else ctx.get("source_name"),
    }


# Simple id+name serializers for EPG enable/disable/refresh
_serialize_epg_source_enabled = _make_simple_serializer("source_id", "source_name")
_serialize_epg_source_disabled = _make_simple_serializer("source_id", "source_name")
_serialize_epg_refresh_started = _make_simple_serializer("source_id", "source_name")


def _serialize_epg_refresh_completed(source, **ctx):
    return {
        "source_id": source.id,
        "source_name": source.name,
        "channel_count": ctx.get("channel_count"),
        "program_count": ctx.get("program_count"),
    }


def _serialize_epg_refresh_failed(source, **ctx):
    return {
        "source_id": source.id if source else ctx.get("source_id"),
        "source_name": source.name if source else ctx.get("source_name"),
        "error": _sanitize_error_message(ctx.get("error")),
    }


# =============================================================================
# M3U SERIALIZERS
# =============================================================================

def _serialize_m3u_source_created(account, **ctx):
    # Security: Only expose safe fields - never username, password, server_url
    return {
        "account_id": account.id,
        "account_name": account.name,
        "account_type": account.account_type,
    }


def _serialize_m3u_source_deleted(account, **ctx):
    return {
        "account_id": account.id if account else ctx.get("account_id"),
        "account_name": account.name if account else ctx.get("account_name"),
    }


# Simple id+name serializers for M3U enable/disable/refresh
_serialize_m3u_source_enabled = _make_simple_serializer("account_id", "account_name")
_serialize_m3u_source_disabled = _make_simple_serializer("account_id", "account_name")
_serialize_m3u_refresh_started = _make_simple_serializer("account_id", "account_name")


def _serialize_m3u_refresh_completed(account, **ctx):
    return {
        "account_id": account.id,
        "account_name": account.name,
        "streams_created": ctx.get("streams_created"),
        "streams_updated": ctx.get("streams_updated"),
    }


def _serialize_m3u_refresh_failed(account, **ctx):
    return {
        "account_id": account.id if account else ctx.get("account_id"),
        "account_name": account.name if account else ctx.get("account_name"),
        "error": _sanitize_error_message(ctx.get("error")),
    }


# =============================================================================
# CHANNEL SERIALIZERS
# =============================================================================

def _serialize_channel_created(channel, **ctx):
    # Use context for related object names to avoid N+1 queries
    return {
        "channel_id": channel.id,
        "channel_number": channel.channel_number,
        "channel_name": channel.name,
        "channel_uuid": str(channel.uuid),
        "channel_group_id": channel.channel_group_id,
        "channel_group_name": ctx.get("channel_group_name") or (
            channel.channel_group.name if channel.channel_group_id and hasattr(channel, '_channel_group_cache') else None
        ),
    }


def _serialize_channel_deleted(channel, **ctx):
    return {
        "channel_id": channel.id,
        "channel_number": channel.channel_number,
        "channel_name": channel.name,
        "channel_uuid": str(channel.uuid),
    }


def _serialize_channel_updated(channel, **ctx):
    return {
        "channel_id": channel.id,
        "channel_number": channel.channel_number,
        "channel_name": channel.name,
        "channel_uuid": str(channel.uuid),
    }


def _serialize_channel_stream_added(channel, **ctx):
    return {
        "channel_id": channel.id,
        "channel_name": channel.name,
        "stream_ids": ctx.get("stream_ids", []),
    }


def _serialize_channel_stream_removed(channel, **ctx):
    return {
        "channel_id": channel.id,
        "channel_name": channel.name,
        "stream_ids": ctx.get("stream_ids", []),
    }


# =============================================================================
# PLUGIN SERIALIZERS (Security: Never include settings)
# =============================================================================

def _serialize_plugin_enabled(plugin, **ctx):
    return {
        "plugin_key": plugin.key,
        "plugin_name": plugin.name,
    }


def _serialize_plugin_disabled(plugin, **ctx):
    return {
        "plugin_key": plugin.key,
        "plugin_name": plugin.name,
    }


def _serialize_plugin_configured(plugin, **ctx):
    return {
        "plugin_key": plugin.key,
        "plugin_name": plugin.name,
        # Security: Don't include actual settings - may contain sensitive data
    }


# =============================================================================
# STREAM SERIALIZERS (Security: Never include URL - may contain credentials)
# =============================================================================

def _serialize_stream_created(stream, **ctx):
    # Security: Explicitly do NOT include stream.url - may contain credentials
    return {
        "stream_id": stream.id,
        "stream_name": stream.name,
        "tvg_id": stream.tvg_id,
        "is_custom": stream.is_custom,
        "m3u_account_id": stream.m3u_account_id,
    }


# Simple serializers for stream update/delete (no URL exposure)
_serialize_stream_updated = _make_simple_serializer("stream_id", "stream_name")
_serialize_stream_deleted = _make_simple_serializer("stream_id", "stream_name")


# =============================================================================
# CHANNEL GROUP SERIALIZERS
# =============================================================================

_serialize_channel_group_created = _make_simple_serializer("group_id", "group_name")
_serialize_channel_group_updated = _make_simple_serializer("group_id", "group_name")
_serialize_channel_group_deleted = _make_simple_serializer("group_id", "group_name")


# =============================================================================
# CHANNEL PROFILE SERIALIZERS
# =============================================================================

_serialize_channel_profile_created = _make_simple_serializer("profile_id", "profile_name")
_serialize_channel_profile_updated = _make_simple_serializer("profile_id", "profile_name")
_serialize_channel_profile_deleted = _make_simple_serializer("profile_id", "profile_name")


# =============================================================================
# RECORDING RULE SERIALIZERS
# =============================================================================

def _serialize_recording_rule_created(rule, **ctx):
    return {
        "rule_id": rule.id,
        "rule_name": rule.name,
        "channel_id": rule.channel_id,
        "channel_name": ctx.get("channel_name") or (rule.channel.name if rule.channel else None),
        "days_of_week": rule.days_of_week,
        "start_time": str(rule.start_time),
        "end_time": str(rule.end_time),
        "enabled": rule.enabled,
    }


def _serialize_recording_rule_updated(rule, **ctx):
    return {
        "rule_id": rule.id,
        "rule_name": rule.name,
        "channel_id": rule.channel_id,
    }


def _serialize_recording_rule_deleted(rule, **ctx):
    return {
        "rule_id": rule.id,
        "rule_name": rule.name,
        "channel_id": rule.channel_id,
    }


# =============================================================================
# VOD SERIALIZERS
# =============================================================================

def _serialize_vod_movie_created(movie, **ctx):
    return {
        "movie_id": movie.id,
        "movie_name": movie.name,
        "year": movie.year,
    }


_serialize_vod_movie_deleted = _make_simple_serializer("movie_id", "movie_name")


def _serialize_vod_series_created(series, **ctx):
    return {
        "series_id": series.id,
        "series_name": series.name,
        "year": series.year,
    }


_serialize_vod_series_deleted = _make_simple_serializer("series_id", "series_name")


def _serialize_vod_episode_created(episode, **ctx):
    return {
        "episode_id": episode.id,
        "episode_name": episode.name,
        "series_id": episode.series_id,
        "series_name": ctx.get("series_name") or (episode.series.name if episode.series else None),
        "season_number": episode.season_number,
        "episode_number": episode.episode_number,
    }


def _serialize_vod_episode_deleted(episode, **ctx):
    return {
        "episode_id": episode.id,
        "episode_name": episode.name,
        "series_id": episode.series_id,
    }


# =============================================================================
# SYSTEM SERIALIZERS
# =============================================================================

def _serialize_system_startup(obj, **ctx):
    return {
        "version": ctx.get("version"),
    }


def _serialize_system_shutdown(obj, **ctx):
    return {}


# =============================================================================
# CHANNEL RUNTIME EVENT SERIALIZERS (Context-based)
# =============================================================================

_serialize_channel_client_connected = _make_context_serializer(["channel_id", "channel_name"])
_serialize_channel_client_disconnected = _make_context_serializer(["channel_id", "channel_name"])
_serialize_channel_stream_started = _make_context_serializer(["channel_id", "channel_name", "stream_id"])
_serialize_channel_stream_stopped = _make_context_serializer(["channel_id", "channel_name"])


def _serialize_channel_error(obj, **ctx):
    return {
        "channel_id": ctx.get("channel_id"),
        "channel_name": ctx.get("channel_name"),
        "error": _sanitize_error_message(ctx.get("error")),
    }


_serialize_channel_buffering = _make_context_serializer(["channel_id", "channel_name", "buffer_size"])


def _serialize_channel_failover(obj, **ctx):
    return {
        "channel_id": ctx.get("channel_id"),
        "channel_name": ctx.get("channel_name"),
        "from_stream_id": ctx.get("from_stream_id"),
        "to_stream_id": ctx.get("to_stream_id"),
        "reason": _sanitize_error_message(ctx.get("reason")),
    }


_serialize_channel_reconnected = _make_context_serializer(["channel_id", "channel_name", "stream_id", "attempt"])
_serialize_channel_stream_switched = _make_context_serializer(["channel_id", "channel_name", "from_stream_id", "to_stream_id"])


# =============================================================================
# AUTH SERIALIZERS
# =============================================================================

_serialize_auth_login = _make_context_serializer(["user_id", "username"])
_serialize_auth_logout = _make_context_serializer(["user_id", "username"])


def _serialize_auth_login_failed(obj, **ctx):
    return {
        "username": ctx.get("username"),
        "reason": _sanitize_error_message(ctx.get("reason")),
    }


# =============================================================================
# EVENT SERIALIZERS REGISTRY
# =============================================================================

EVENT_SERIALIZERS = {
    # Recording events
    "recording.scheduled": _serialize_recording_scheduled,
    "recording.started": _serialize_recording_started,
    "recording.completed": _serialize_recording_completed,
    "recording.interrupted": _serialize_recording_interrupted,
    "recording.cancelled": _serialize_recording_cancelled,
    "recording.deleted": _serialize_recording_deleted,
    "recording.changed": _serialize_recording_changed,
    "recording.comskip_completed": _serialize_recording_comskip_completed,
    "recording.bulk_cancelled": _serialize_recording_bulk_cancelled,
    # EPG events
    "epg.source_created": _serialize_epg_source_created,
    "epg.source_deleted": _serialize_epg_source_deleted,
    "epg.source_enabled": _serialize_epg_source_enabled,
    "epg.source_disabled": _serialize_epg_source_disabled,
    "epg.refresh_started": _serialize_epg_refresh_started,
    "epg.refresh_completed": _serialize_epg_refresh_completed,
    "epg.refresh_failed": _serialize_epg_refresh_failed,
    # M3U events
    "m3u.source_created": _serialize_m3u_source_created,
    "m3u.source_deleted": _serialize_m3u_source_deleted,
    "m3u.source_enabled": _serialize_m3u_source_enabled,
    "m3u.source_disabled": _serialize_m3u_source_disabled,
    "m3u.refresh_started": _serialize_m3u_refresh_started,
    "m3u.refresh_completed": _serialize_m3u_refresh_completed,
    "m3u.refresh_failed": _serialize_m3u_refresh_failed,
    # Channel events
    "channel.created": _serialize_channel_created,
    "channel.deleted": _serialize_channel_deleted,
    "channel.updated": _serialize_channel_updated,
    "channel.stream_added": _serialize_channel_stream_added,
    "channel.stream_removed": _serialize_channel_stream_removed,
    # Plugin events
    "plugin.enabled": _serialize_plugin_enabled,
    "plugin.disabled": _serialize_plugin_disabled,
    "plugin.configured": _serialize_plugin_configured,
    # Stream events
    "stream.created": _serialize_stream_created,
    "stream.updated": _serialize_stream_updated,
    "stream.deleted": _serialize_stream_deleted,
    # ChannelGroup events
    "channel_group.created": _serialize_channel_group_created,
    "channel_group.updated": _serialize_channel_group_updated,
    "channel_group.deleted": _serialize_channel_group_deleted,
    # ChannelProfile events
    "channel_profile.created": _serialize_channel_profile_created,
    "channel_profile.updated": _serialize_channel_profile_updated,
    "channel_profile.deleted": _serialize_channel_profile_deleted,
    # RecurringRecordingRule events
    "recording_rule.created": _serialize_recording_rule_created,
    "recording_rule.updated": _serialize_recording_rule_updated,
    "recording_rule.deleted": _serialize_recording_rule_deleted,
    # VOD events
    "vod.movie_created": _serialize_vod_movie_created,
    "vod.movie_deleted": _serialize_vod_movie_deleted,
    "vod.series_created": _serialize_vod_series_created,
    "vod.series_deleted": _serialize_vod_series_deleted,
    "vod.episode_created": _serialize_vod_episode_created,
    "vod.episode_deleted": _serialize_vod_episode_deleted,
    # System events
    "system.startup": _serialize_system_startup,
    "system.shutdown": _serialize_system_shutdown,
    # Channel runtime events
    "channel.client_connected": _serialize_channel_client_connected,
    "channel.client_disconnected": _serialize_channel_client_disconnected,
    "channel.stream_started": _serialize_channel_stream_started,
    "channel.stream_stopped": _serialize_channel_stream_stopped,
    "channel.error": _serialize_channel_error,
    "channel.buffering": _serialize_channel_buffering,
    "channel.failover": _serialize_channel_failover,
    "channel.reconnected": _serialize_channel_reconnected,
    "channel.stream_switched": _serialize_channel_stream_switched,
    # Auth events
    "auth.login": _serialize_auth_login,
    "auth.login_failed": _serialize_auth_login_failed,
    "auth.logout": _serialize_auth_logout,
}


# =============================================================================
# EVENT METADATA
# =============================================================================

# Event descriptions for API documentation
EVENT_DESCRIPTIONS = {
    # Critical events
    "auth.login_failed": "Failed login attempt",
    "channel.error": "Channel playback error",
    "epg.refresh_failed": "EPG refresh failed",
    "m3u.refresh_failed": "M3U refresh failed",
    "recording.interrupted": "Recording stopped unexpectedly",
    # System events
    "auth.login": "Successful login",
    "auth.logout": "User logged out",
    "system.startup": "Application started",
    "system.shutdown": "Application shutting down",
    "plugin.enabled": "Plugin was enabled",
    "plugin.disabled": "Plugin was disabled",
    "plugin.configured": "Plugin settings changed",
    # Full events - Recording
    "recording.scheduled": "Recording scheduled",
    "recording.started": "Recording started",
    "recording.completed": "Recording completed successfully",
    "recording.cancelled": "Scheduled recording cancelled",
    "recording.deleted": "Completed recording deleted",
    "recording.changed": "Recording times changed",
    "recording.comskip_completed": "Commercial skip processing completed",
    "recording.bulk_cancelled": "Multiple recordings cancelled",
    # Full events - EPG
    "epg.source_created": "EPG source created",
    "epg.source_deleted": "EPG source deleted",
    "epg.source_enabled": "EPG source enabled",
    "epg.source_disabled": "EPG source disabled",
    "epg.refresh_started": "EPG refresh started",
    "epg.refresh_completed": "EPG refresh completed",
    # Full events - M3U
    "m3u.source_created": "M3U source created",
    "m3u.source_deleted": "M3U source deleted",
    "m3u.source_enabled": "M3U source enabled",
    "m3u.source_disabled": "M3U source disabled",
    "m3u.refresh_started": "M3U refresh started",
    "m3u.refresh_completed": "M3U refresh completed",
    # Full events - Channel
    "channel.created": "Channel created",
    "channel.deleted": "Channel deleted",
    "channel.updated": "Channel updated",
    "channel.stream_added": "Streams added to channel",
    "channel.stream_removed": "Streams removed from channel",
    "channel.client_connected": "Client connected to channel",
    "channel.client_disconnected": "Client disconnected from channel",
    "channel.stream_started": "Channel stream started",
    "channel.stream_stopped": "Channel stream stopped",
    "channel.buffering": "Channel buffering",
    "channel.failover": "Channel failed over to backup stream",
    "channel.reconnected": "Channel reconnected",
    "channel.stream_switched": "Channel switched streams",
    # Full events - Stream
    "stream.created": "Stream created",
    "stream.updated": "Stream updated",
    "stream.deleted": "Stream deleted",
    # Full events - Channel Group
    "channel_group.created": "Channel group created",
    "channel_group.updated": "Channel group updated",
    "channel_group.deleted": "Channel group deleted",
    # Full events - Channel Profile
    "channel_profile.created": "Channel profile created",
    "channel_profile.updated": "Channel profile updated",
    "channel_profile.deleted": "Channel profile deleted",
    # Full events - Recording Rule
    "recording_rule.created": "Recording rule created",
    "recording_rule.updated": "Recording rule updated",
    "recording_rule.deleted": "Recording rule deleted",
    # Full events - VOD
    "vod.movie_created": "VOD movie created",
    "vod.movie_deleted": "VOD movie deleted",
    "vod.series_created": "VOD series created",
    "vod.series_deleted": "VOD series deleted",
    "vod.episode_created": "VOD episode created",
    "vod.episode_deleted": "VOD episode deleted",
}

# Event field schemas for API documentation
# Maps event names to the list of fields returned in the event payload
EVENT_FIELDS = {
    # Critical events
    "auth.login_failed": ["username", "ip_address", "reason"],
    "channel.error": ["channel_id", "channel_name", "error", "stream_id"],
    "epg.refresh_failed": ["source_id", "source_name", "error"],
    "m3u.refresh_failed": ["account_id", "account_name", "error"],
    "recording.interrupted": ["recording_id", "channel_id", "channel_name", "file_path", "error", "duration_seconds"],
    # System events
    "auth.login": ["user_id", "username", "ip_address"],
    "auth.logout": ["user_id", "username"],
    "system.startup": ["version", "timestamp"],
    "system.shutdown": ["reason"],
    "plugin.enabled": ["plugin_key", "plugin_name"],
    "plugin.disabled": ["plugin_key", "plugin_name"],
    "plugin.configured": ["plugin_key", "plugin_name"],
    # Recording events
    "recording.scheduled": ["recording_id", "channel_id", "channel_name", "start_time", "end_time", "program_name"],
    "recording.started": ["recording_id", "channel_id", "channel_name", "start_time", "end_time"],
    "recording.completed": ["recording_id", "channel_id", "channel_name", "file_path", "duration_seconds"],
    "recording.cancelled": ["recording_id", "channel_id", "channel_name", "start_time"],
    "recording.deleted": ["recording_id", "channel_id", "channel_name", "file_path"],
    "recording.changed": ["recording_id", "channel_id", "channel_name", "new_start_time", "new_end_time"],
    "recording.comskip_completed": ["recording_id", "segments_found"],
    "recording.bulk_cancelled": ["cancelled_count", "recording_ids"],
    # EPG events
    "epg.source_created": ["source_id", "source_name", "source_type"],
    "epg.source_deleted": ["source_id", "source_name"],
    "epg.source_enabled": ["source_id", "source_name"],
    "epg.source_disabled": ["source_id", "source_name"],
    "epg.refresh_started": ["source_id", "source_name"],
    "epg.refresh_completed": ["source_id", "source_name", "programs_count"],
    # M3U events
    "m3u.source_created": ["account_id", "account_name", "account_type"],
    "m3u.source_deleted": ["account_id", "account_name"],
    "m3u.source_enabled": ["account_id", "account_name"],
    "m3u.source_disabled": ["account_id", "account_name"],
    "m3u.refresh_started": ["account_id", "account_name"],
    "m3u.refresh_completed": ["account_id", "account_name", "streams_count"],
    # Channel events
    "channel.created": ["channel_id", "channel_number", "channel_name", "channel_uuid", "channel_group_id", "channel_group_name"],
    "channel.deleted": ["channel_id", "channel_number", "channel_name", "channel_uuid"],
    "channel.updated": ["channel_id", "channel_number", "channel_name", "channel_uuid", "channel_group_id", "channel_group_name"],
    "channel.stream_added": ["channel_id", "channel_name", "stream_ids"],
    "channel.stream_removed": ["channel_id", "channel_name", "stream_ids"],
    "channel.client_connected": ["channel_id", "channel_name", "client_ip"],
    "channel.client_disconnected": ["channel_id", "channel_name", "client_ip"],
    "channel.stream_started": ["channel_id", "channel_name", "stream_id", "stream_name"],
    "channel.stream_stopped": ["channel_id", "channel_name"],
    "channel.buffering": ["channel_id", "channel_name", "buffer_percent"],
    "channel.failover": ["channel_id", "channel_name", "from_stream_id", "to_stream_id"],
    "channel.reconnected": ["channel_id", "channel_name", "stream_id"],
    "channel.stream_switched": ["channel_id", "channel_name", "from_stream_id", "to_stream_id"],
    # Stream events
    "stream.created": ["stream_id", "stream_name", "stream_url", "account_id", "account_name"],
    "stream.updated": ["stream_id", "stream_name"],
    "stream.deleted": ["stream_id", "stream_name"],
    # Channel Group events
    "channel_group.created": ["group_id", "group_name"],
    "channel_group.updated": ["group_id", "group_name"],
    "channel_group.deleted": ["group_id", "group_name"],
    # Channel Profile events
    "channel_profile.created": ["profile_id", "profile_name"],
    "channel_profile.updated": ["profile_id", "profile_name"],
    "channel_profile.deleted": ["profile_id", "profile_name"],
    # Recording Rule events
    "recording_rule.created": ["rule_id", "rule_name", "channel_id", "channel_name"],
    "recording_rule.updated": ["rule_id", "rule_name"],
    "recording_rule.deleted": ["rule_id", "rule_name"],
    # VOD events
    "vod.movie_created": ["movie_id", "movie_name", "year"],
    "vod.movie_deleted": ["movie_id", "movie_name"],
    "vod.series_created": ["series_id", "series_name"],
    "vod.series_deleted": ["series_id", "series_name"],
    "vod.episode_created": ["episode_id", "episode_name", "series_id", "series_name", "season_number", "episode_number"],
    "vod.episode_deleted": ["episode_id", "episode_name"],
}


def get_event_catalog():
    """
    Get the full event catalog for API discovery.

    Returns a dict with all events, their levels, descriptions, and field schemas.
    """
    catalog = {}
    for event_name in EVENT_SERIALIZERS.keys():
        level_num = EVENT_LEVEL_MAP.get(event_name, EVENT_LEVEL_FULL)
        catalog[event_name] = {
            "level": EVENT_LEVEL_NAMES.get(level_num, "UNKNOWN"),
            "description": EVENT_DESCRIPTIONS.get(event_name, ""),
            "fields": EVENT_FIELDS.get(event_name, []),
        }
    return catalog


# =============================================================================
# EMIT FUNCTION
# =============================================================================

# Lazy-loaded pubsub manager to avoid import on every emit call
_pubsub_manager = None


def _get_pubsub():
    """Get the pubsub manager, initializing lazily on first use."""
    global _pubsub_manager
    if _pubsub_manager is None:
        from core.redis_pubsub import get_pubsub_manager
        _pubsub_manager = get_pubsub_manager()
    return _pubsub_manager


def _do_emit(event_name: str, data: dict):
    """Actually emit the event to pubsub. Called after transaction commits."""
    try:
        pubsub = _get_pubsub()
        pubsub.emit(event_name, data)
    except Exception as e:
        logger.warning(f"Failed to emit {event_name} event: {e}")


def emit(event_name: str, obj=None, on_commit: bool = True, **context):
    """
    Emit a plugin event with automatic serialization.

    By default, events are emitted after the current database transaction commits
    using Django's transaction.on_commit(). This prevents "phantom events" where
    an event is emitted but the corresponding database changes are rolled back.

    Events are filtered based on the configured event level:
    - DISPATCHARR_EVENT_LEVEL env var (highest priority)
    - CoreSettings system_settings.event_level
    - Default: FULL

    Args:
        event_name: The event name (e.g., "recording.completed")
        obj: The primary object (Recording, EPGSource, M3UAccount, etc.)
        on_commit: If True (default), emit after transaction commits.
                   If False, emit immediately (use for non-transactional contexts).
        **context: Additional context data for the serializer
    """
    # Check if this event should be emitted based on configured level
    if not should_emit_event(event_name):
        logger.debug(f"Event '{event_name}' suppressed by event level configuration")
        return

    try:
        serializer = EVENT_SERIALIZERS.get(event_name)
        if serializer:
            data = serializer(obj, **context)
        else:
            logger.warning(f"No serializer for event '{event_name}', using raw context")
            data = {"id": getattr(obj, "id", None), **context}

        if on_commit:
            # Defer emission until after transaction commits
            # This prevents emitting events for rolled-back transactions
            from django.db import transaction
            transaction.on_commit(lambda: _do_emit(event_name, data))
        else:
            # Emit immediately (for non-transactional contexts like Celery tasks)
            _do_emit(event_name, data)
    except Exception as e:
        logger.warning(f"Failed to prepare {event_name} event: {e}")
