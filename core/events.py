"""
Centralized plugin event serialization.

Each event type has a serializer that knows how to extract relevant data
from the object. Call sites just pass the event name and object.
"""
import logging

logger = logging.getLogger(__name__)


def _serialize_recording_scheduled(recording, **ctx):
    return {
        "recording_id": recording.id,
        "channel_id": recording.channel_id,
        "channel_name": recording.channel.name if recording.channel else None,
        "start_time": str(recording.start_time),
        "end_time": str(recording.end_time),
        "program_name": (
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
            "channel_name": recording.channel.name if recording.channel else None,
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
        "reason": ctx.get("reason") or cp.get("interrupted_reason"),
    }


def _serialize_recording_cancelled(recording, **ctx):
    return {
        "recording_id": recording.id,
        "channel_id": recording.channel_id,
        "channel_name": recording.channel.name if recording.channel else None,
        "start_time": str(recording.start_time),
        "end_time": str(recording.end_time),
    }


def _serialize_recording_deleted(recording, **ctx):
    cp = recording.custom_properties or {}
    return {
        "recording_id": recording.id,
        "channel_id": recording.channel_id,
        "channel_name": recording.channel.name if recording.channel else None,
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


def _serialize_epg_source_enabled(source, **ctx):
    return {
        "source_id": source.id,
        "source_name": source.name,
    }


def _serialize_epg_source_disabled(source, **ctx):
    return {
        "source_id": source.id,
        "source_name": source.name,
    }


def _serialize_epg_refresh_started(source, **ctx):
    return {
        "source_id": source.id,
        "source_name": source.name,
    }


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
        "error": ctx.get("error"),
    }


def _serialize_m3u_source_created(account, **ctx):
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


def _serialize_m3u_source_enabled(account, **ctx):
    return {
        "account_id": account.id,
        "account_name": account.name,
    }


def _serialize_m3u_source_disabled(account, **ctx):
    return {
        "account_id": account.id,
        "account_name": account.name,
    }


def _serialize_m3u_refresh_started(account, **ctx):
    return {
        "account_id": account.id,
        "account_name": account.name,
    }


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
        "error": ctx.get("error"),
    }


def _serialize_channel_created(channel, **ctx):
    return {
        "channel_id": channel.id,
        "channel_number": channel.channel_number,
        "channel_name": channel.name,
        "channel_uuid": str(channel.uuid),
        "channel_group_id": channel.channel_group_id,
        "channel_group_name": channel.channel_group.name if channel.channel_group else None,
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
        "changed_fields": ctx.get("changed_fields", []),
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


def _serialize_plugin_installed(plugin, **ctx):
    return {
        "plugin_key": plugin.key,
        "plugin_name": plugin.name,
        "plugin_version": plugin.version,
    }


def _serialize_plugin_uninstalled(plugin, **ctx):
    return {
        "plugin_key": plugin.key,
        "plugin_name": plugin.name,
    }


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
        # Don't include actual settings - may contain sensitive data
    }


# Stream serializers
def _serialize_stream_created(stream, **ctx):
    return {
        "stream_id": stream.id,
        "stream_name": stream.name,
        "stream_url": stream.url,
        "tvg_id": stream.tvg_id,
        "is_custom": stream.is_custom,
        "m3u_account_id": stream.m3u_account_id,
    }


def _serialize_stream_updated(stream, **ctx):
    return {
        "stream_id": stream.id,
        "stream_name": stream.name,
        "changed_fields": ctx.get("changed_fields", []),
    }


def _serialize_stream_deleted(stream, **ctx):
    return {
        "stream_id": stream.id,
        "stream_name": stream.name,
    }


# ChannelGroup serializers
def _serialize_channel_group_created(group, **ctx):
    return {
        "group_id": group.id,
        "group_name": group.name,
    }


def _serialize_channel_group_updated(group, **ctx):
    return {
        "group_id": group.id,
        "group_name": group.name,
    }


def _serialize_channel_group_deleted(group, **ctx):
    return {
        "group_id": group.id,
        "group_name": group.name,
    }


# ChannelProfile serializers
def _serialize_channel_profile_created(profile, **ctx):
    return {
        "profile_id": profile.id,
        "profile_name": profile.name,
    }


def _serialize_channel_profile_updated(profile, **ctx):
    return {
        "profile_id": profile.id,
        "profile_name": profile.name,
    }


def _serialize_channel_profile_deleted(profile, **ctx):
    return {
        "profile_id": profile.id,
        "profile_name": profile.name,
    }


# RecurringRecordingRule serializers
def _serialize_recording_rule_created(rule, **ctx):
    return {
        "rule_id": rule.id,
        "rule_name": rule.name,
        "channel_id": rule.channel_id,
        "channel_name": rule.channel.name if rule.channel else None,
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
        "changed_fields": ctx.get("changed_fields", []),
    }


def _serialize_recording_rule_deleted(rule, **ctx):
    return {
        "rule_id": rule.id,
        "rule_name": rule.name,
        "channel_id": rule.channel_id,
    }


# VOD serializers
def _serialize_vod_movie_added(movie, **ctx):
    return {
        "movie_id": movie.id,
        "movie_name": movie.name,
        "year": movie.year,
    }


def _serialize_vod_movie_removed(movie, **ctx):
    return {
        "movie_id": movie.id,
        "movie_name": movie.name,
    }


def _serialize_vod_series_added(series, **ctx):
    return {
        "series_id": series.id,
        "series_name": series.name,
        "year": series.year,
    }


def _serialize_vod_series_removed(series, **ctx):
    return {
        "series_id": series.id,
        "series_name": series.name,
    }


def _serialize_vod_episode_added(episode, **ctx):
    return {
        "episode_id": episode.id,
        "episode_name": episode.name,
        "series_id": episode.series_id,
        "series_name": episode.series.name if episode.series else None,
        "season_number": episode.season_number,
        "episode_number": episode.episode_number,
    }


def _serialize_vod_episode_removed(episode, **ctx):
    return {
        "episode_id": episode.id,
        "episode_name": episode.name,
        "series_id": episode.series_id,
    }


# System serializers
def _serialize_system_startup(obj, **ctx):
    return {
        "version": ctx.get("version"),
    }


def _serialize_system_shutdown(obj, **ctx):
    return {}


# Channel runtime event serializers (for log_system_event)
def _serialize_channel_client_connected(obj, **ctx):
    return {
        "channel_id": ctx.get("channel_id"),
        "channel_name": ctx.get("channel_name"),
        "client_ip": ctx.get("client_ip"),
    }


def _serialize_channel_client_disconnected(obj, **ctx):
    return {
        "channel_id": ctx.get("channel_id"),
        "channel_name": ctx.get("channel_name"),
        "client_ip": ctx.get("client_ip"),
    }


def _serialize_channel_stream_started(obj, **ctx):
    return {
        "channel_id": ctx.get("channel_id"),
        "channel_name": ctx.get("channel_name"),
        "stream_id": ctx.get("stream_id"),
    }


def _serialize_channel_stream_stopped(obj, **ctx):
    return {
        "channel_id": ctx.get("channel_id"),
        "channel_name": ctx.get("channel_name"),
    }


def _serialize_channel_error(obj, **ctx):
    return {
        "channel_id": ctx.get("channel_id"),
        "channel_name": ctx.get("channel_name"),
        "error": ctx.get("error"),
    }


def _serialize_auth_login(obj, **ctx):
    return {
        "user_id": ctx.get("user_id"),
        "username": ctx.get("username"),
    }


def _serialize_auth_login_failed(obj, **ctx):
    return {
        "username": ctx.get("username"),
        "reason": ctx.get("reason"),
    }


def _serialize_auth_logout(obj, **ctx):
    return {
        "user_id": ctx.get("user_id"),
        "username": ctx.get("username"),
    }


EVENT_SERIALIZERS = {
    "recording.scheduled": _serialize_recording_scheduled,
    "recording.started": _serialize_recording_started,
    "recording.completed": _serialize_recording_completed,
    "recording.interrupted": _serialize_recording_interrupted,
    "recording.cancelled": _serialize_recording_cancelled,
    "recording.deleted": _serialize_recording_deleted,
    "recording.changed": _serialize_recording_changed,
    "recording.comskip_completed": _serialize_recording_comskip_completed,
    "recording.bulk_cancelled": _serialize_recording_bulk_cancelled,
    "epg.source_created": _serialize_epg_source_created,
    "epg.source_deleted": _serialize_epg_source_deleted,
    "epg.source_enabled": _serialize_epg_source_enabled,
    "epg.source_disabled": _serialize_epg_source_disabled,
    "epg.refresh_started": _serialize_epg_refresh_started,
    "epg.refresh_completed": _serialize_epg_refresh_completed,
    "epg.refresh_failed": _serialize_epg_refresh_failed,
    "m3u.source_created": _serialize_m3u_source_created,
    "m3u.source_deleted": _serialize_m3u_source_deleted,
    "m3u.source_enabled": _serialize_m3u_source_enabled,
    "m3u.source_disabled": _serialize_m3u_source_disabled,
    "m3u.refresh_started": _serialize_m3u_refresh_started,
    "m3u.refresh_completed": _serialize_m3u_refresh_completed,
    "m3u.refresh_failed": _serialize_m3u_refresh_failed,
    "channel.created": _serialize_channel_created,
    "channel.deleted": _serialize_channel_deleted,
    "channel.updated": _serialize_channel_updated,
    "channel.stream_added": _serialize_channel_stream_added,
    "channel.stream_removed": _serialize_channel_stream_removed,
    "plugin.installed": _serialize_plugin_installed,
    "plugin.uninstalled": _serialize_plugin_uninstalled,
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
    "vod.movie_added": _serialize_vod_movie_added,
    "vod.movie_removed": _serialize_vod_movie_removed,
    "vod.series_added": _serialize_vod_series_added,
    "vod.series_removed": _serialize_vod_series_removed,
    "vod.episode_added": _serialize_vod_episode_added,
    "vod.episode_removed": _serialize_vod_episode_removed,
    # System events
    "system.startup": _serialize_system_startup,
    "system.shutdown": _serialize_system_shutdown,
    # Channel runtime events
    "channel.client_connected": _serialize_channel_client_connected,
    "channel.client_disconnected": _serialize_channel_client_disconnected,
    "channel.stream_started": _serialize_channel_stream_started,
    "channel.stream_stopped": _serialize_channel_stream_stopped,
    "channel.error": _serialize_channel_error,
    # Auth events
    "auth.login": _serialize_auth_login,
    "auth.login_failed": _serialize_auth_login_failed,
    "auth.logout": _serialize_auth_logout,
}


def emit(event_name: str, obj=None, **context):
    """
    Emit a plugin event with automatic serialization.

    Args:
        event_name: The event name (e.g., "recording.completed")
        obj: The primary object (Recording, EPGSource, M3UAccount, etc.)
        **context: Additional context data for the serializer
    """
    try:
        from core.redis_pubsub import get_pubsub_manager

        serializer = EVENT_SERIALIZERS.get(event_name)
        if serializer:
            data = serializer(obj, **context)
        else:
            logger.warning(f"No serializer for event '{event_name}', using raw context")
            data = {"id": getattr(obj, "id", None), **context}

        pubsub = get_pubsub_manager()
        pubsub.emit(event_name, data)
    except Exception as e:
        logger.debug(f"Failed to emit {event_name} event: {e}")
