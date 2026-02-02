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
