"""Deduplicated provider detail requests outside HTTP request handling."""

import logging
import uuid

from django.core.cache import cache

from .models import M3UMovieRelation, M3USeriesRelation

logger = logging.getLogger(__name__)
TTL = 3600


def keys(kind, pk):
    if kind not in {"movie", "series"}:
        raise ValueError("Unsupported provider content type.")
    return (
        f"vod-provider-detail:{kind}:{pk}:lock",
        f"vod-provider-detail:{kind}:{pk}:status",
    )


def queue_provider_refresh(kind, pk, *, required, force=False):
    if not required:
        return "completed"
    lock, status = keys(kind, pk)
    try:
        current = cache.get(status) or {}
        if cache.get(lock):
            return "pending"
        if current.get("status") == "failed" and not force:
            return "failed"
        token = uuid.uuid4().hex
        if not cache.add(lock, token, timeout=TTL):
            return "pending"
        cache.set(status, {"status": "pending", "token": token}, timeout=TTL)
        from .tasks import refresh_library_provider_details

        try:
            refresh_library_provider_details.delay(kind, pk, token)
        except Exception:  # noqa: BLE001 -- imported data must survive broker failures
            if cache.get(lock) == token:
                cache.delete(lock)
                cache.set(status, {"status": "failed", "token": token}, timeout=TTL)
            logger.warning(
                "Could not queue provider details for %s relation %s", kind, pk
            )
            return "failed"
        return "pending"
    except Exception:  # noqa: BLE001 -- optional cache cannot break detail responses
        logger.warning("Provider detail cache is unavailable")
        return "unavailable"


def run_provider_refresh(kind, pk, token):
    lock, status = keys(kind, pk)
    try:
        if cache.get(lock) != token:
            return "obsolete"
    except Exception:  # noqa: BLE001 -- a cache outage must not start untracked work
        logger.warning("Provider detail cache is unavailable")
        return "unavailable"
    result = "failed"
    try:
        model = M3UMovieRelation if kind == "movie" else M3USeriesRelation
        source = (
            model.objects.select_related("m3u_account", kind)
            .filter(pk=pk, m3u_account__is_active=True)
            .first()
        )
        if source:
            from .tasks import refresh_movie_advanced_data, refresh_series_episodes

            before = (
                source.last_advanced_refresh
                if kind == "movie"
                else source.last_episode_refresh
            )
            if kind == "movie":
                refresh_movie_advanced_data(pk, force_refresh=True)
            else:
                refresh_series_episodes(
                    source.m3u_account, source.series, source.external_series_id
                )
            source.refresh_from_db()
            after = (
                source.last_advanced_refresh
                if kind == "movie"
                else source.last_episode_refresh
            )
            props = source.custom_properties or {}
            if (
                after
                and after != before
                and props.get("detailed_fetched")
                and (kind == "movie" or props.get("episodes_fetched"))
            ):
                result = "completed"
        else:
            result = "unavailable"
    except Exception:  # noqa: BLE001 -- contain optional provider failures in the worker
        logger.warning("Provider detail refresh failed for %s relation %s", kind, pk)
    finally:
        try:
            if cache.get(lock) == token:
                cache.set(status, {"status": result, "token": token}, timeout=TTL)
                cache.delete(lock)
        except Exception:  # noqa: BLE001 -- expiring lock remains recoverable
            logger.warning("Could not update provider detail refresh status")
    return result
