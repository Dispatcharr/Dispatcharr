"""Per-user DVR disk quota enforcement.

A quota is a soft cap (stored as ``custom_properties.dvr_quota_mb`` on the
User) on how much storage a request-tier user's OWNED recordings may
occupy. Two enforcement points:

  - Blocked at schedule time (``RecordingViewSet.create``) if the user is
    already at/over quota when they try to schedule a new recording.
  - Evicted after a recording finishes and its real size becomes known
    (``tasks.py``'s ``run_recording`` finalize step) -- a DVR recording's
    final size can't be known before it airs, so blocking alone can't
    catch "this recording put me over quota."

Eviction only ever removes the SAME user's own oldest finished
recordings, and reuses the same reassign-instead-of-delete rule as a
manual delete: if another user still wants a recording being evicted,
ownership is handed to them instead of the file being deleted.
"""

import logging
import os

logger = logging.getLogger(__name__)

_QUOTA_KEY = "dvr_quota_mb"

# A recording's DVR pipeline has finished and its on-disk size is final.
_FINISHED_STATUSES = ("completed", "stopped", "interrupted")


def get_user_dvr_quota_bytes(user):
    """Bytes, or None if unlimited (custom_properties.dvr_quota_mb unset or <= 0)."""
    props = getattr(user, "custom_properties", None) or {}
    raw = props.get(_QUOTA_KEY)
    try:
        mb = int(raw)
    except (TypeError, ValueError):
        return None
    if mb <= 0:
        return None
    return mb * 1024 * 1024


def _recording_file_size(recording):
    cp = recording.custom_properties or {}
    bytes_written = cp.get("bytes_written")
    if isinstance(bytes_written, (int, float)) and bytes_written > 0:
        return int(bytes_written)

    file_path = cp.get("file_path")
    if not file_path:
        return 0
    try:
        from apps.channels.api_views import _resolve_recording_storage_path

        resolved = _resolve_recording_storage_path(file_path)
    except Exception:
        resolved = None
    if not resolved:
        return 0
    try:
        return os.path.getsize(resolved)
    except OSError:
        return 0


def _owned_recordings_queryset(user):
    from apps.channels.models import Recording

    return Recording.objects.filter(requests__user=user, requests__is_owner=True)


def get_user_dvr_usage_bytes(user):
    return sum(_recording_file_size(r) for r in _owned_recordings_queryset(user))


def user_dvr_quota_exceeded(user):
    """True if the user is already at/over their quota (before adding
    anything new) -- used to block scheduling a further recording."""
    quota = get_user_dvr_quota_bytes(user)
    if quota is None:
        return False
    return get_user_dvr_usage_bytes(user) >= quota


def _delete_recording_files(recording):
    """Best-effort removal of a recording's file/HLS dir from disk."""
    from apps.channels.api_views import _resolve_recording_storage_path

    cp = recording.custom_properties or {}
    file_path = _resolve_recording_storage_path(cp.get("file_path"))
    hls_dir = _resolve_recording_storage_path(cp.get("_hls_dir"))
    if file_path:
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
        except Exception as ex:
            logger.warning(f"Quota eviction: failed to delete {file_path}: {ex}")
    if hls_dir:
        try:
            import shutil

            if os.path.isdir(hls_dir):
                shutil.rmtree(hls_dir)
        except Exception as ex:
            logger.warning(f"Quota eviction: failed to delete HLS dir {hls_dir}: {ex}")


def _remove_or_reassign(recording, user):
    """Same rule as a manual owner delete: reassign to the next requester
    if someone else still wants it, otherwise hard-delete the row + files."""
    from apps.channels.models import RecordingRequest

    other_requesters = recording.requests.exclude(user=user).exists()
    if other_requesters:
        RecordingRequest.objects.filter(recording=recording, user=user).delete()
        recording.promote_next_owner()
        return "reassigned"

    _delete_recording_files(recording)
    recording.delete()
    return "deleted"


def evict_oldest_owned_recordings_until_under_quota(user):
    """Delete/reassign the user's own oldest finished recordings until
    usage is back under quota. Never touches an in-progress or upcoming
    recording. Returns a list of {"id", "action"} entries for what was
    evicted (for logging/websocket notification)."""
    quota = get_user_dvr_quota_bytes(user)
    if quota is None:
        return []

    owned = list(
        _owned_recordings_queryset(user)
        .filter(custom_properties__status__in=list(_FINISHED_STATUSES))
        .order_by("start_time")
    )
    usage = get_user_dvr_usage_bytes(user)
    evicted = []
    for recording in owned:
        if usage < quota:
            break
        recording_id = recording.id
        size = _recording_file_size(recording)
        try:
            # _remove_or_reassign may call recording.delete(), which clears
            # recording.id on the instance -- capture it beforehand.
            action = _remove_or_reassign(recording, user)
        except Exception as ex:
            logger.warning(
                f"Quota eviction: failed to remove recording {recording_id}: {ex}"
            )
            continue
        usage -= size
        evicted.append({"id": recording_id, "action": action})
    return evicted
