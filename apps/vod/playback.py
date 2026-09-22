"""Playback history helpers shared by redirect, proxy, and player telemetry."""

import logging
import re

from django.core.cache import cache
from django.utils import timezone

from core.models import CoreSettings

from .metadata import sync_relation_declared_metadata
from .models import VODPlaybackSession
from .policies import relation_category


logger = logging.getLogger(__name__)
_HISTORY_CLEANUP_THROTTLE_KEY = "vod:playback-history-cleanup:v1"
_HISTORY_CLEANUP_INTERVAL_SECONDS = 6 * 60 * 60


def _schedule_history_cleanup_if_due():
    """Queue retention cleanup at most once per interval, never in-band."""
    if CoreSettings.get_vod_playback_history_retention_days() <= 0:
        return
    try:
        acquired = cache.add(
            _HISTORY_CLEANUP_THROTTLE_KEY,
            True,
            timeout=_HISTORY_CLEANUP_INTERVAL_SECONDS,
        )
    except Exception as exc:
        logger.warning("Could not schedule VOD history cleanup: %s", exc)
        return
    if not acquired:
        return
    try:
        from .tasks import cleanup_vod_playback_history

        cleanup_vod_playback_history.delay()
    except Exception as exc:
        cache.delete(_HISTORY_CLEANUP_THROTTLE_KEY)
        logger.warning("Could not queue VOD history cleanup: %s", exc)


def _relation_content(relation):
    if hasattr(relation, "movie"):
        return "movie", relation.movie
    if hasattr(relation, "episode"):
        return "episode", relation.episode
    return "series", relation.series


def _provider_asset_id(relation):
    return str(
        getattr(relation, "stream_id", None)
        or getattr(relation, "external_series_id", None)
        or ""
    )


def _failover_count(failover_chain):
    """Count rejected candidates before the selected source."""
    count = 0
    for step in failover_chain or []:
        if not isinstance(step, dict):
            continue
        if step.get("result") == "selected":
            break
        count += 1
    return count


def episode_history_name(value, source_name=""):
    """Keep only the provider episode title when a canonical prefix was added.

    Older rows can contain ``<series> - SxxExx - <provider episode>``.  The
    provider title normally contains its own SxxExx marker, so the prefix adds
    no information and makes history rows hard to scan.
    """
    explicit = str(source_name or "").strip()
    if explicit:
        return explicit
    text = str(value or "").strip()
    markers = list(re.finditer(r"\bS\d{1,3}E\d{1,4}\b", text, re.IGNORECASE))
    if len(markers) < 2:
        return text
    separator = text.find(" - ", markers[0].end())
    return text[separator + 3 :].strip() if separator >= 0 else text


def record_playback_selection(
    *,
    session_id,
    user,
    relation,
    mode,
    status,
    client_ip=None,
    user_agent="",
    failover_chain=None,
    custom_properties=None,
):
    """Create/update the auditable choice without probing provider media."""
    asset_type, content = _relation_content(relation)
    # Snapshot safe category/provider defaults on the exact relation. Playback
    # history remains usable even if a concurrent refresh prevents this write.
    try:
        sync_relation_declared_metadata(relation)
    except Exception as exc:
        logger.warning(
            "Could not update source metadata for playback %s (relation %s): %s",
            session_id,
            getattr(relation, "id", None),
            exc,
        )
    category = relation_category(relation)
    custom_properties = custom_properties or {}
    values = {
        "user": user if getattr(user, "is_authenticated", False) else None,
        "m3u_account": relation.m3u_account,
        "category": category,
        "content_type": asset_type,
        "canonical_id": content.id,
        "relation_id": relation.id,
        "provider_asset_id": _provider_asset_id(relation),
        # Episode names supplied by providers already contain their episode
        # identifier/title. Prefixing the canonical series again makes history
        # rows unnecessarily long and often duplicates SxxExx.
        "content_name": (
            episode_history_name(
                content.name,
                custom_properties.get("episode_name", ""),
            )
            if asset_type == "episode"
            else str(content)
        )[:500],
        "mode": mode,
        "status": status,
        "client_ip": client_ip or None,
        "user_agent": user_agent or "",
        "failover_chain": failover_chain or [],
        "failover_count": _failover_count(failover_chain),
        "custom_properties": custom_properties,
    }
    if status not in {
        VODPlaybackSession.Status.COMPLETED,
        VODPlaybackSession.Status.STOPPED,
        VODPlaybackSession.Status.FAILED,
    }:
        # A Range reconnect can revive the same session URL after a previous
        # transport request ended.  Do not leave a stale terminal timestamp on
        # a playback that is active again.
        values["ended_at"] = None
    playback, created = VODPlaybackSession.objects.update_or_create(
        session_id=session_id,
        defaults=values,
    )
    if not created and status in {
        VODPlaybackSession.Status.COMPLETED,
        VODPlaybackSession.Status.STOPPED,
        VODPlaybackSession.Status.FAILED,
    }:
        playback.ended_at = timezone.now()
        playback.save(update_fields=["ended_at"])
    if created or status in {
        VODPlaybackSession.Status.COMPLETED,
        VODPlaybackSession.Status.STOPPED,
        VODPlaybackSession.Status.FAILED,
    }:
        _schedule_history_cleanup_if_due()
    return playback
