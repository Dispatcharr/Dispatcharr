from celery import shared_task, current_app, group
from django.utils import timezone
from django.db import transaction, IntegrityError
from django.db.models import Count, F, Q
from apps.m3u.models import M3UAccount
from apps.m3u.utils import parse_is_adult
from core.xtream_codes import Client as XtreamCodesClient
from core.utils import (
    TaskLockRenewer,
    acquire_task_lock,
    is_task_lock_held,
    release_task_lock,
)
from .models import (
    VODCategory, Series, Movie, Episode, VODLogo,
    M3USeriesRelation, M3UMovieRelation, M3UEpisodeRelation,
    M3UVODCategoryRelation, VODMovieProfileSelection,
    VODSeriesProfileSelection, VODPlaybackSession,
)
from datetime import datetime, timedelta
import hashlib
import logging
import json
import re
import time
import unicodedata

logger = logging.getLogger(__name__)

VOD_PROFILE_REBUILD_AFTER_REFRESH_KEY = (
    "vod_profile_selection:rebuild_after_provider_refresh"
)

TMDB_ENRICHMENT_LOCK_NAME = "vod_tmdb_enrichment"
TMDB_ENRICHMENT_LOCK_ID = "global"
TMDB_PROGRESS_INTERVAL = 25
TMDB_ENRICHMENT_LOCK_VALUE = "locked"


def _import_source_metadata(category_relation, container_extension=None):
    """Snapshot operator-owned category defaults onto one source relation."""
    from .metadata import normalize_source_metadata

    metadata = dict(
        getattr(category_relation, "metadata_defaults", None) or {}
    )
    if container_extension:
        metadata["container_extension"] = str(container_extension).lower()
    return normalize_source_metadata(metadata)


def _episode_import_metadata(relation, category_metadata):
    """Add trustworthy episode video facts to the category metadata snapshot."""
    from .metadata import normalize_source_metadata, relation_declared_metadata

    return normalize_source_metadata(
        {**category_metadata, **relation_declared_metadata(relation)}
    )


VOD_PROFILE_FINGERPRINT_FIELDS = (
    "stream_id",
    "series_id",
    "category_id",
    "name",
    "title",
    "tmdb",
    "tmdb_id",
    "imdb",
    "imdb_id",
    "year",
    "releaseDate",
    "release_date",
    "container_extension",
    "bitrate",
    "file_size",
    "duration",
    "duration_secs",
    "plot",
    "description",
    "rating",
    "genre",
    "stream_icon",
    "cover",
    "cover_big",
    "backdrop_path",
    "trailer",
    "youtube_trailer",
    "director",
    "actors",
    "cast",
    "crew",
    "country",
    "origin_country",
    "age",
    "age_rating",
)

VOD_PROVIDER_METADATA_SCHEMA = 2


@shared_task
def cleanup_vod_playback_history():
    """Delete playback audit rows outside their configured retention window."""
    from core.models import CoreSettings
    from .models import VODPlaybackSession

    retention_days = CoreSettings.get_vod_playback_history_retention_days()
    if retention_days <= 0:
        return {"retention_days": 0, "deleted_sessions": 0}

    cutoff = timezone.now() - timedelta(days=retention_days)
    deleted, _ = VODPlaybackSession.objects.filter(
        started_at__lt=cutoff
    ).delete()
    logger.info(
        "VOD playback history cleanup removed %s rows older than %s days",
        deleted,
        retention_days,
    )
    return {"retention_days": retention_days, "deleted_sessions": deleted}


def _merge_canonical_tmdb_duplicate(
    model,
    source_id,
    target_id,
    *,
    set_override=False,
):
    """Move every durable reference to one canonical title and remove its duplicate."""
    if source_id == target_id:
        return 0
    with transaction.atomic():
        source = model.objects.select_for_update().filter(pk=source_id).first()
        target = model.objects.select_for_update().filter(pk=target_id).first()
        if source is None or target is None:
            return 0
        target_tmdb_id = str(target.tmdb_match_id or target.tmdb_id or "")

        if model is Movie:
            relation_ids = list(
                M3UMovieRelation.objects.filter(movie_id=source.id).values_list(
                    "id", flat=True
                )
            )
            if relation_ids:
                relation_update = {"movie_id": target.id}
                if set_override:
                    relation_update["tmdb_override_id"] = target_tmdb_id
                M3UMovieRelation.objects.filter(pk__in=relation_ids).update(
                    **relation_update
                )
            VODMovieProfileSelection.objects.filter(movie_id=source.id).update(
                movie_id=target.id
            )
            content_type = "movie"
        else:
            relations = list(
                M3USeriesRelation.objects.filter(series_id=source.id).order_by("id")
            )
            relation_ids = [relation.id for relation in relations]
            for relation in relations:
                episode_relations = list(
                    relation.episode_relations.select_related("episode").order_by("id")
                )
                for episode_relation in episode_relations:
                    source_episode = episode_relation.episode
                    target_episode = Episode.objects.filter(
                        series_id=target.id,
                        season_number=source_episode.season_number,
                        episode_number=source_episode.episode_number,
                    ).order_by("id").first()
                    if target_episode is None:
                        target_episode = Episode.objects.create(
                            series_id=target.id,
                            name=source_episode.name,
                            description=source_episode.description,
                            air_date=source_episode.air_date,
                            rating=source_episode.rating,
                            duration_secs=source_episode.duration_secs,
                            season_number=source_episode.season_number,
                            episode_number=source_episode.episode_number,
                            tmdb_id=source_episode.tmdb_id,
                            imdb_id=source_episode.imdb_id,
                            custom_properties=source_episode.custom_properties,
                            library_added_at=source_episode.library_added_at,
                        )
                    M3UEpisodeRelation.objects.filter(
                        pk=episode_relation.pk
                    ).update(episode_id=target_episode.id)
                relation_update = {"series_id": target.id}
                if set_override:
                    relation_update["tmdb_override_id"] = target_tmdb_id
                M3USeriesRelation.objects.filter(pk=relation.id).update(
                    **relation_update
                )
            VODSeriesProfileSelection.objects.filter(series_id=source.id).update(
                series_id=target.id
            )
            content_type = "series"

        VODPlaybackSession.objects.filter(
            content_type=content_type,
            canonical_id=source.id,
        ).update(canonical_id=target.id)
        source.delete()
        return len(relation_ids)


def _merge_duplicate_tmdb_canonicals(model):
    """Collapse canonical rows that resolve to the same curated TMDB ID."""
    merged = 0
    target_ids = set()
    duplicate_ids = list(
        model.objects.exclude(tmdb_match_id="")
        .values("tmdb_match_id")
        .annotate(row_count=Count("id"))
        .filter(row_count__gt=1)
        .values_list("tmdb_match_id", flat=True)
    )
    for tmdb_id in duplicate_ids:
        candidates = list(
            model.objects.filter(tmdb_match_id=tmdb_id)
            .annotate(source_count=Count("m3u_relations"))
            .order_by("id")
        )
        if len(candidates) < 2:
            continue
        candidates.sort(
            key=lambda content: (
                content.tmdb_status != "matched",
                -content.source_count,
                content.id,
            )
        )
        target = candidates[0]
        target_ids.add(target.id)
        for source in candidates[1:]:
            if not model.objects.filter(pk=source.id).exists():
                continue
            _merge_canonical_tmdb_duplicate(model, source.id, target.id)
            merged += 1
    return merged, target_ids


def _filter_manual_tmdb_selection(queryset, media_type, filters):
    """Restrict a manual batch to the exact canonical VOD list selection.

    The list filter owns a few relation-aware predicates (account, category,
    source languages and technical properties). Reuse that query here so a
    select-all action cannot silently extend beyond what the administrator saw.
    The import is deliberately local: api_views already imports task entry
    points during application startup.
    """
    filters = filters if isinstance(filters, dict) else {}
    from .api_views import _filtered_vod_content

    movies, series = _filtered_vod_content(filters)
    selected = movies if media_type == "movie" else series
    return queryset.filter(id__in=selected.values("id"))


def _set_tmdb_state(status, *, task_id=None, progress=None, error=None, **dates):
    from .models import VODMetadataState

    defaults = {"status": status}
    if task_id is not None:
        defaults["task_id"] = task_id
    if progress is not None:
        defaults["progress"] = progress
    if error is not None:
        defaults["error"] = error
    defaults.update(dates)
    VODMetadataState.objects.update_or_create(pk=1, defaults=defaults)


def enqueue_tmdb_enrichment(
    *,
    force=False,
    search_missing=None,
    rebuild_profiles=False,
    trigger_reason="Manual TMDB metadata refresh",
    movie_ids=None,
    series_ids=None,
    selection_filters=None,
    exclude_movie_ids=None,
    exclude_series_ids=None,
):
    """Publish at most one durable global enrichment task."""
    from .models import VODMetadataState

    now = timezone.now()
    with transaction.atomic():
        state, _ = VODMetadataState.objects.select_for_update().get_or_create(pk=1)
        active = state.status in {
            VODMetadataState.Status.QUEUED,
            VODMetadataState.Status.RUNNING,
        }
        # A worker/container may disappear without writing a terminal state.
        # Six hours is far beyond a normal batch but still permits recovery.
        fresh = state.updated_at and state.updated_at >= now - timedelta(hours=6)
        if active and fresh:
            update_fields = ["updated_at"]
            if rebuild_profiles and not state.rebuild_profiles_after_completion:
                state.rebuild_profiles_after_completion = True
                update_fields.append("rebuild_profiles_after_completion")
            # The active worker has already snapshotted its work set. Record
            # one follow-up pass so a provider refresh or manual ID correction
            # arriving during that pass cannot be lost.
            if not state.rerun_requested:
                state.rerun_requested = True
                update_fields.append("rerun_requested")
            state.save(update_fields=update_fields)
            return {"queued": False, "task_id": state.task_id, "status": state.status}
        state.status = VODMetadataState.Status.QUEUED
        state.task_id = ""
        state.rebuild_profiles_after_completion = bool(rebuild_profiles)
        state.rerun_requested = False
        state.progress = {
            "phase": "Waiting for worker",
            "percent": 0,
            "trigger_reason": trigger_reason,
        }
        state.started_at = now
        state.completed_at = None
        state.error = ""
        state.save()

        def publish():
            try:
                result = enrich_vod_metadata.delay(
                    force=force,
                    search_missing=search_missing,
                    rebuild_profiles=rebuild_profiles,
                    trigger_reason=trigger_reason,
                    movie_ids=movie_ids,
                    series_ids=series_ids,
                    selection_filters=selection_filters,
                    exclude_movie_ids=exclude_movie_ids,
                    exclude_series_ids=exclude_series_ids,
                )
                VODMetadataState.objects.filter(
                    pk=1,
                    status=VODMetadataState.Status.QUEUED,
                ).update(task_id=result.id)
            except Exception as exc:
                logger.exception("Could not enqueue TMDB metadata enrichment")
                _set_tmdb_state(
                    VODMetadataState.Status.FAILED,
                    progress={"phase": "Could not publish background task", "percent": 100},
                    error=str(exc)[:2000],
                    completed_at=timezone.now(),
                )

        transaction.on_commit(publish)
    return {"queued": True, "task_id": "", "status": "queued"}


@shared_task
def reconcile_vod_metadata_queue():
    """End a stale TMDB status after a worker or broker restart.

    This task only repairs durable status. It never starts enrichment merely
    because an administrator opened the VOD page.
    """
    from celery.result import AsyncResult
    from .models import VODMetadataState

    state = VODMetadataState.objects.filter(pk=1).first()
    if state is None or state.status not in {
        VODMetadataState.Status.QUEUED,
        VODMetadataState.Status.RUNNING,
    }:
        return {"repaired": False}

    now = timezone.now()
    task_state = ""
    if state.task_id:
        try:
            task_state = str(AsyncResult(state.task_id).state or "")
        except Exception:
            task_state = "UNKNOWN"
    terminal = task_state in {"SUCCESS", "FAILURE", "REVOKED"}
    unpublished = (
        state.status == VODMetadataState.Status.QUEUED
        and not state.task_id
        and state.updated_at < now - timedelta(minutes=2)
    )
    lost_running_worker = False
    if (
        state.status == VODMetadataState.Status.RUNNING
        and state.updated_at < now - timedelta(minutes=10)
    ):
        try:
            lost_running_worker = not is_task_lock_held(
                TMDB_ENRICHMENT_LOCK_NAME,
                TMDB_ENRICHMENT_LOCK_ID,
            )
        except Exception:
            # An unavailable Redis instance is not evidence that the worker
            # disappeared; leave the durable state untouched and retry later.
            lost_running_worker = False
    if not (terminal or unpublished or lost_running_worker):
        return {"repaired": False, "task_state": task_state}

    reason = (
        "The TMDB background task ended without recording completion. "
        "Start the metadata refresh again; already enriched titles will be skipped."
    )
    _set_tmdb_state(
        VODMetadataState.Status.FAILED,
        task_id=state.task_id,
        progress={"phase": "TMDB metadata refresh was interrupted", "percent": 100},
        error=reason,
        completed_at=now,
    )
    return {"repaired": True, "task_state": task_state}


@shared_task(bind=True, track_started=True)
def enrich_vod_metadata(
    self,
    *,
    force=False,
    search_missing=None,
    rebuild_profiles=False,
    trigger_reason="Manual TMDB metadata refresh",
    movie_ids=None,
    series_ids=None,
    selection_filters=None,
    exclude_movie_ids=None,
    exclude_series_ids=None,
):
    """Enrich canonical movies and series in one resumable TMDB batch."""
    from core.models import CoreSettings
    from .models import Movie, Series, VODMetadataState
    from .tmdb import (
        Client as TMDBClient,
        TMDBAuthenticationError,
        TMDBError,
        TMDBNotFound,
        apply_manual_overrides,
        canonical_fields_from_metadata,
        clean_lookup_title,
    )
    from django.db.models.fields.json import KeyTransform

    if not acquire_task_lock(TMDB_ENRICHMENT_LOCK_NAME, TMDB_ENRICHMENT_LOCK_ID):
        return {"skipped": "TMDB enrichment is already running"}
    lock_renewer = TaskLockRenewer(
        TMDB_ENRICHMENT_LOCK_NAME,
        TMDB_ENRICHMENT_LOCK_ID,
    )
    lock_renewer.start()
    started_at = timezone.now()
    changed_movies = 0
    changed_series = 0
    changed_movie_ids = set()
    changed_series_ids = set()
    rerun_after = False
    try:
        token = CoreSettings.get_tmdb_api_token()
        if not token:
            raise ValueError("Configure a TMDB API read access token first")
        languages = CoreSettings.get_tmdb_languages()
        match_missing = CoreSettings.get_tmdb_match_missing()
        should_search_missing = (
            match_missing if search_missing is None else bool(search_missing)
        )
        title_rules = CoreSettings.get_tmdb_title_rules()
        year_rules = CoreSettings.get_tmdb_year_rules()
        # Keep only the lightweight identity columns in memory. In particular,
        # do not load every existing tmdb_metadata JSON document just to find
        # the relatively small incremental work set.
        work = []
        query_fields = (
            "id",
            "name",
            "display_name",
            "clean_title",
            "year",
            "tmdb_id",
            "tmdb_match_id",
            "tmdb_enrichment_signature",
        )
        for model, media_type, relation_name in (
            (Movie, "movie", "m3u_relations"),
            (Series, "tv", "m3u_relations"),
        ):
            queryset = (
                model.objects.filter(
                    **{f"{relation_name}__m3u_account__is_active": True}
                )
                .annotate(
                    manual_overrides=KeyTransform(
                        "_manual_overrides", "tmdb_metadata"
                    )
                )
                .distinct()
                .values(*query_fields, "manual_overrides")
                .order_by("id")
            )
            selected_ids = movie_ids if media_type == "movie" else series_ids
            if selected_ids is not None:
                queryset = queryset.filter(id__in=selected_ids)
            if selection_filters is not None:
                queryset = _filter_manual_tmdb_selection(
                    queryset, media_type, selection_filters
                )
            excluded_ids = (
                exclude_movie_ids if media_type == "movie" else exclude_series_ids
            )
            if excluded_ids:
                queryset = queryset.exclude(id__in=excluded_ids)
            for content in queryset.iterator(chunk_size=1000):
                if force or not content["tmdb_enrichment_signature"]:
                    work.append((model, media_type, content))

        total = len(work)
        counters = {
            "processed": 0,
            "total": total,
            "matched": 0,
            "enriched": 0,
            "not_found": 0,
            "ambiguous": 0,
            "missing_id": 0,
            "errors": 0,
        }

        def progress(phase, current=None):
            processed = counters["processed"]
            percent = round((processed / total) * 100) if total else 100
            _set_tmdb_state(
                VODMetadataState.Status.RUNNING,
                task_id=str(self.request.id or ""),
                progress={
                    "phase": phase,
                    "percent": percent,
                    "current": current or "",
                    "trigger_reason": trigger_reason,
                    **counters,
                },
                error="",
                started_at=started_at,
                completed_at=None,
            )

        progress("Preparing TMDB metadata batch")
        client = TMDBClient(token)
        consecutive_errors = 0
        for model, media_type, content in work:
            content_id = content["id"]
            content_name = content["name"]
            lookup_title = content["clean_title"] or clean_lookup_title(
                content_name,
                display_name=content["display_name"],
                year=content["year"],
                rules=title_rules,
                year_rules=year_rules,
            )
            tmdb_id = str(
                content["tmdb_match_id"] or content["tmdb_id"] or ""
            ).strip()
            match_method = (
                "stored_tmdb_match"
                if content["tmdb_match_id"]
                else ("provider_tmdb_id" if tmdb_id else "")
            )
            metadata = {}
            search_status = None
            candidate_count = 0
            try:
                if not tmdb_id and should_search_missing:
                    tmdb_id, search_status, candidate_count = client.search_outcome(
                        lookup_title,
                        content["year"],
                        media_type,
                        languages[0],
                    )
                    if tmdb_id:
                        match_method = "exact_title_year"
                if not tmdb_id:
                    metadata = {
                        "schema": 1,
                        "status": (
                            search_status
                            if should_search_missing and search_status
                            else "missing_id"
                        ),
                        "candidate_count": (
                            candidate_count
                            if should_search_missing
                            else 0
                        ),
                        "localized": {},
                        "fetched_at": timezone.now().isoformat(),
                    }
                    counters["missing_id"] += 1
                    if search_status == "ambiguous":
                        counters["ambiguous"] += 1
                    elif search_status == "not_found":
                        counters["not_found"] += 1
                else:
                    metadata = client.details(
                        tmdb_id,
                        media_type,
                        languages,
                        match_method=match_method,
                    )
                    metadata["status"] = "matched"
                    counters["matched"] += int(not content["tmdb_id"])
                    counters["enriched"] += 1
                metadata = apply_manual_overrides(
                    metadata,
                    content.get("manual_overrides"),
                )
                consecutive_errors = 0
            except TMDBNotFound:
                metadata = {
                    "schema": 1,
                    "status": "not_found",
                    "id": tmdb_id,
                    "localized": {},
                    "fetched_at": timezone.now().isoformat(),
                }
                metadata = apply_manual_overrides(
                    metadata,
                    content.get("manual_overrides"),
                )
                counters["not_found"] += 1
                consecutive_errors = 0
            except TMDBAuthenticationError:
                raise
            except TMDBError as exc:
                # Request failures remain retryable on the next automatic run.
                counters["errors"] += 1
                counters["processed"] += 1
                consecutive_errors += 1
                if counters["processed"] % TMDB_PROGRESS_INTERVAL == 0:
                    progress("Fetching TMDB metadata", content_name)
                logger.warning(
                    "TMDB enrichment failed for %s %s: %s",
                    media_type,
                    content_id,
                    exc,
                )
                if consecutive_errors >= 10:
                    raise RuntimeError(
                        "TMDB failed repeatedly; stopping the batch for a later retry"
                    ) from exc
                continue

            update = {
                "clean_title": lookup_title[:255],
                "tmdb_metadata": metadata,
                "tmdb_match_id": str(metadata.get("id") or ""),
                "tmdb_imdb_id": str(metadata.get("imdb_id") or ""),
                "tmdb_poster_url": str(metadata.get("poster_url") or ""),
                "tmdb_backdrop_url": str(metadata.get("backdrop_url") or ""),
                "tmdb_status": metadata.get("status") or "",
                "tmdb_enriched_at": timezone.now(),
                "tmdb_enrichment_signature": TMDB_ENRICHMENT_LOCK_VALUE,
            }
            if metadata.get("status") == "matched":
                update.update(
                    canonical_fields_from_metadata(
                        metadata,
                        languages[0],
                        media_type,
                    )
                )
            model.objects.filter(pk=content_id).update(**update)
            if media_type == "movie":
                changed_movies += 1
                changed_movie_ids.add(content_id)
            else:
                changed_series += 1
                changed_series_ids.add(content_id)
            counters["processed"] += 1
            if (
                counters["processed"] % TMDB_PROGRESS_INTERVAL == 0
                or counters["processed"] == total
            ):
                progress("Fetching TMDB metadata", content_name)

        merged_movies, merged_movie_targets = _merge_duplicate_tmdb_canonicals(
            Movie
        )
        merged_series, merged_series_targets = _merge_duplicate_tmdb_canonicals(
            Series
        )
        if merged_movies:
            changed_movies += merged_movies
            changed_movie_ids.update(merged_movie_targets)
        if merged_series:
            changed_series += merged_series
            changed_series_ids.update(merged_series_targets)

        completed_at = timezone.now()
        _set_tmdb_state(
            VODMetadataState.Status.COMPLETE,
            task_id=str(self.request.id or ""),
            progress={
                "phase": "TMDB metadata is up to date",
                "percent": 100,
                "trigger_reason": trigger_reason,
                **counters,
            },
            error="",
            started_at=started_at,
            completed_at=completed_at,
        )
        rerun_after = bool(
            VODMetadataState.objects.filter(pk=1, rerun_requested=True).update(
                rerun_requested=False
            )
        )
        must_rebuild_profiles = bool(
            rebuild_profiles
            or VODMetadataState.objects.filter(
                pk=1,
                rebuild_profiles_after_completion=True,
            ).exists()
        )
        # A provider refresh that landed during this pass needs one more
        # incremental TMDB scan. Keep the rebuild request pending so clients
        # switch only after that final scan has enriched the newest catalog.
        if must_rebuild_profiles and not rerun_after:
            from .profile_selection import enqueue_all_profile_selection_rebuilds

            enqueue_all_profile_selection_rebuilds(
                trigger_reason="A changed provider catalog was enriched with TMDB metadata"
            )
            VODMetadataState.objects.filter(pk=1).update(
                rebuild_profiles_after_completion=False
            )
        if changed_movies or changed_series:
            from .catalog_cache import bump_catalog_generation
            from core.utils import send_websocket_update

            # Artwork and external IDs change XC and VOD responses, but do not
            # start an output build unless this pass belongs to a changed
            # provider catalog. Manual enrichment leaves the completed output
            # active and asks the administrator to rebuild explicitly.
            bump_catalog_generation(invalidate_selections=False)
            send_websocket_update(
                "updates",
                "update",
                {
                    "type": "vod_library_updated",
                    "changed_movies": changed_movies,
                    "changed_series": changed_series,
                },
                collect_garbage=False,
            )
            if not must_rebuild_profiles:
                from .profile_selection import (
                    mark_profile_selections_outdated,
                    profile_ids_using_canonical_content,
                )

                mark_profile_selections_outdated(
                    trigger_reason="Canonical VOD metadata was enriched manually",
                    policy_ids=profile_ids_using_canonical_content(
                        movie_ids=changed_movie_ids,
                        series_ids=changed_series_ids,
                    ),
                )
        return {
            **counters,
            "changed_movies": changed_movies,
            "changed_series": changed_series,
        }
    except Exception as exc:
        logger.exception("TMDB metadata enrichment failed")
        _set_tmdb_state(
            VODMetadataState.Status.FAILED,
            task_id=str(self.request.id or ""),
            progress={"phase": "TMDB metadata refresh failed", "percent": 100},
            error=str(exc)[:2000],
            started_at=started_at,
            completed_at=timezone.now(),
        )
        must_rebuild_profiles = bool(
            rebuild_profiles
            or VODMetadataState.objects.filter(
                pk=1,
                rebuild_profiles_after_completion=True,
            ).exists()
        )
        if must_rebuild_profiles:
            from .profile_selection import enqueue_all_profile_selection_rebuilds

            enqueue_all_profile_selection_rebuilds(
                trigger_reason="Provider catalog changed; TMDB enrichment failed"
            )
            VODMetadataState.objects.filter(pk=1).update(
                rebuild_profiles_after_completion=False
            )
        rerun_after = bool(
            VODMetadataState.objects.filter(pk=1, rerun_requested=True).update(
                rerun_requested=False
            )
        )
        raise
    finally:
        lock_renewer.stop()
        release_task_lock(TMDB_ENRICHMENT_LOCK_NAME, TMDB_ENRICHMENT_LOCK_ID)
        if rerun_after:
            pending_profile_rebuild = bool(
                rebuild_profiles
                or VODMetadataState.objects.filter(
                    pk=1,
                    rebuild_profiles_after_completion=True,
                ).exists()
            )
            enqueue_tmdb_enrichment(
                search_missing=search_missing,
                rebuild_profiles=pending_profile_rebuild,
                trigger_reason="VOD metadata changed during the previous TMDB pass",
            )


def _provider_vod_fingerprint(rows):
    """Return an order-independent digest of output-relevant provider rows.

    XC providers do not guarantee row ordering. XORing fixed SHA-256 row
    digests lets scheduled refreshes cheaply recognize an unchanged catalog
    without retaining another copy of a potentially very large VOD response.
    """
    digest = bytearray(32)
    for row in rows:
        if not isinstance(row, dict):
            continue
        payload = {
            key: row.get(key)
            for key in VOD_PROFILE_FINGERPRINT_FIELDS
            if row.get(key) not in (None, "", [], {})
        }
        row_digest = hashlib.sha256(
            json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ).encode("utf-8")
        ).digest()
        for index, value in enumerate(row_digest):
            digest[index] ^= value
    return f"{len(rows)}:{bytes(digest).hex()}"


def _remember_profile_rebuild_after_vod_refresh():
    """Record one catalog invalidation without publishing a premature task.

    The 60-second profile watchdog publishes this only after no provider is in
    FETCHING/PARSING anymore. This also covers refresh jobs already waiting in
    the same Celery queue, which have not set their account status yet.
    """
    from .catalog_cache import safe_cache_set

    safe_cache_set(
        VOD_PROFILE_REBUILD_AFTER_REFRESH_KEY,
        True,
        timeout=6 * 60 * 60,
    )


def _enqueue_deferred_profile_rebuild_after_vod_refreshes():
    """Publish profile and enrichment work after every running refresh ended."""
    from django.core.cache import cache

    from .catalog_cache import safe_cache_get

    if M3UAccount.objects.filter(
        is_active=True,
        status__in=[M3UAccount.Status.FETCHING, M3UAccount.Status.PARSING],
    ).exists():
        return False
    if not safe_cache_get(VOD_PROFILE_REBUILD_AFTER_REFRESH_KEY, False):
        return False

    try:
        cache.delete(VOD_PROFILE_REBUILD_AFTER_REFRESH_KEY)
    except Exception:
        pass

    from core.models import CoreSettings

    from .profile_selection import enqueue_all_profile_selection_rebuilds

    # Enrichment processes only new or explicitly unlocked canonical titles.
    # When enabled, let that pass finish before rebuilding profiles so clients
    # switch once to the final catalog. Without a configured enrichment pass,
    # the cleanup stage locks new titles and the changed source catalog is
    # rebuilt immediately.
    if (
        CoreSettings.get_tmdb_auto_enrich()
        and CoreSettings.get_tmdb_api_token()
    ):
        result = enqueue_tmdb_enrichment(
            rebuild_profiles=True,
            trigger_reason="A completed provider VOD refresh changed the catalog",
        )
        return result["queued"] or result["status"] in {"queued", "running"}

    return enqueue_all_profile_selection_rebuilds(
        trigger_reason=(
            "One or more completed VOD provider refreshes changed the source "
            "catalog"
        )
    )


@shared_task(bind=True, max_retries=180, track_started=True)
def rebuild_vod_profile_selection(self, policy_id):
    """Prepare one reusable VOD output profile outside request handling."""
    from apps.m3u.models import M3UAccount
    from .models import VODAccessPolicy
    from .profile_selection import (
        SINGLE_PROFILE_TASK_NAME,
        _set_pending_profiles_progress,
    )

    _set_pending_profiles_progress(
        VODAccessPolicy.objects.filter(pk=policy_id),
        "Starting VOD profile catalog build",
        0,
        queue="celery",
        task_id=str(self.request.id or ""),
        task_name=SINGLE_PROFILE_TASK_NAME,
        batch=False,
        attempt=int(getattr(self.request, "retries", 0) or 0) + 1,
    )

    if M3UAccount.objects.filter(
        is_active=True,
        status__in=[M3UAccount.Status.FETCHING, M3UAccount.Status.PARSING],
    ).exists():
        _set_pending_profiles_progress(
            VODAccessPolicy.objects.filter(pk=policy_id),
            "Waiting for an active M3U/VOD refresh",
            0,
            queue="celery",
            task_id=str(self.request.id or ""),
            task_name=SINGLE_PROFILE_TASK_NAME,
            batch=False,
            attempt=int(getattr(self.request, "retries", 0) or 0) + 1,
        )
        raise self.retry(countdown=10)
    from .profile_selection import (
        CatalogChangedDuringBuild,
        ProfileBuildAlreadyRunning,
        ProfileBuildNotPending,
        build_vod_profile_selection,
    )

    try:
        return build_vod_profile_selection(policy_id, require_pending=True)
    except ProfileBuildNotPending as exc:
        # A second Celery delivery may arrive after the authoritative build has
        # already activated its generation. Treat it as a harmless no-op.
        return {"skipped": str(exc)}
    except (CatalogChangedDuringBuild, ProfileBuildAlreadyRunning) as exc:
        raise self.retry(exc=exc, countdown=5)


@shared_task(bind=True, max_retries=180, track_started=True)
def rebuild_all_vod_profile_selections(self):
    """Refresh all active VOD profiles after a completed catalog import."""
    from apps.m3u.models import M3UAccount
    from .models import VODAccessPolicy
    from .profile_selection import (
        BATCH_PROFILE_TASK_NAME,
        _set_pending_profiles_progress,
    )

    _set_pending_profiles_progress(
        VODAccessPolicy.objects.filter(is_active=True),
        "VOD profile catalog batch started",
        0,
        include_batch_position=True,
        queue="celery",
        task_id=str(self.request.id or ""),
        task_name=BATCH_PROFILE_TASK_NAME,
        batch=True,
        attempt=int(getattr(self.request, "retries", 0) or 0) + 1,
    )

    if M3UAccount.objects.filter(
        is_active=True,
        status__in=[M3UAccount.Status.FETCHING, M3UAccount.Status.PARSING],
    ).exists():
        _set_pending_profiles_progress(
            VODAccessPolicy.objects.filter(is_active=True),
            "Waiting for an active M3U/VOD refresh",
            0,
            include_batch_position=True,
            queue="celery",
            task_id=str(self.request.id or ""),
            task_name=BATCH_PROFILE_TASK_NAME,
            batch=True,
            attempt=int(getattr(self.request, "retries", 0) or 0) + 1,
        )
        raise self.retry(countdown=10)
    from django.core.cache import cache
    from .profile_selection import (
        BATCH_PROFILE_TASK_NAME,
        CatalogChangedDuringBuild,
        PROFILE_REBUILD_ENQUEUE_KEY,
        PROFILE_REBUILD_LOCK_TIMEOUT,
        ProfileBuildAlreadyRunning,
        ProfileBuildNotPending,
        _set_pending_profiles_progress,
        build_vod_profile_selection,
    )

    results = {}
    retry_exc = None

    def release_owned_rebuild_lock():
        """Never let an older duplicate task remove a newer task's lock."""
        try:
            owner = cache.get(PROFILE_REBUILD_ENQUEUE_KEY)
            task_id = self.request.id
            if owner is None:
                return
            if owner == "1" or not task_id or str(owner) == str(task_id):
                cache.delete(PROFILE_REBUILD_ENQUEUE_KEY)
        except Exception:
            pass

    for policy_id in VODAccessPolicy.objects.filter(
        is_active=True,
        selection_status=VODAccessPolicy.SelectionStatus.PENDING,
    ).values_list("id", flat=True):
        try:
            results[str(policy_id)] = build_vod_profile_selection(
                policy_id, require_pending=True
            )
        except ProfileBuildNotPending as exc:
            results[str(policy_id)] = {"skipped": str(exc)}
        except (CatalogChangedDuringBuild, ProfileBuildAlreadyRunning) as exc:
            retry_exc = exc
            results[str(policy_id)] = {"error": str(exc)}
            break
        except Exception as exc:
            logger.warning(
                "VOD profile %s could not be prepared: %s", policy_id, exc
            )
            results[str(policy_id)] = {"error": str(exc)}
    if retry_exc is not None:
        # Keep the debounce lock across Celery retries. Releasing it here used
        # to allow a second batch task to race the retry and toggle one profile
        # repeatedly between Pending and Building.
        try:
            cache.set(
                PROFILE_REBUILD_ENQUEUE_KEY,
                self.request.id or "retrying",
                timeout=PROFILE_REBUILD_LOCK_TIMEOUT,
            )
        except Exception:
            pass
        raise self.retry(exc=retry_exc, countdown=5)
    release_owned_rebuild_lock()
    # An invalidation can arrive after this task has already prepared an early
    # profile. The debounce lock intentionally suppresses another task while we
    # are running, so schedule one follow-up pass for any profile left pending.
    if VODAccessPolicy.objects.filter(
        is_active=True,
        selection_status=VODAccessPolicy.SelectionStatus.PENDING,
    ).exists():
        try:
            acquired = cache.add(
                PROFILE_REBUILD_ENQUEUE_KEY,
                "1",
                timeout=PROFILE_REBUILD_LOCK_TIMEOUT,
            )
        except Exception:
            acquired = True
        if acquired:
            result = self.apply_async(countdown=1)
            try:
                cache.set(
                    PROFILE_REBUILD_ENQUEUE_KEY,
                    result.id,
                    timeout=PROFILE_REBUILD_LOCK_TIMEOUT,
                )
            except Exception:
                pass
            _set_pending_profiles_progress(
                VODAccessPolicy.objects.filter(is_active=True),
                "Waiting in Celery queue",
                0,
                include_batch_position=True,
                queue="celery",
                task_id=result.id,
                task_name=BATCH_PROFILE_TASK_NAME,
                queued_at=timezone.now().isoformat(),
                batch=True,
            )
    return results


@shared_task
def reconcile_vod_profile_selection_queue():
    """Repair profile builds whose delivery was lost or already completed.

    Catalog reads must remain read-only. This periodic watchdog replaces the
    old API-list side effect and also repairs the inconsistent state where a
    profile says Pending although its recorded Celery task is already final.
    """
    from celery.result import AsyncResult
    from django.core.cache import cache
    from django.utils.dateparse import parse_datetime

    from .models import VODAccessPolicy
    from .profile_selection import (
        BATCH_PROFILE_TASK_NAME,
        PROFILE_REBUILD_ENQUEUE_KEY,
        _progress_payload,
        enqueue_all_profile_selection_rebuilds,
    )

    # READY is authoritative. Code/schema changes must not masquerade as a
    # user save merely because a newly calculated signature differs from the
    # signature stored by an older version. Profile saves and completed VOD
    # imports explicitly move affected profiles to Pending; this watchdog only
    # recovers work which was already Pending/Building and then got stranded.
    repaired_ready = 0

    try:
        rebuild_lock_owner = cache.get(PROFILE_REBUILD_ENQUEUE_KEY)
    except Exception:
        rebuild_lock_owner = None

    terminal_states = {"SUCCESS", "FAILURE", "REVOKED"}
    cutoff = timezone.now() - timedelta(minutes=2)
    stranded = []
    pending_profiles = VODAccessPolicy.objects.filter(
        is_active=True,
        selection_status=VODAccessPolicy.SelectionStatus.PENDING,
    ).filter(
        Q(selection_started_at__isnull=True) | Q(selection_started_at__lt=cutoff)
    )
    for policy in pending_profiles:
        task_id = (policy.selection_progress or {}).get("task_id")
        if not task_id:
            stranded.append((policy.pk, ""))
            continue
        try:
            task_state = str(AsyncResult(task_id).state or "PENDING")
        except Exception:
            task_state = "UNKNOWN"
        progress = policy.selection_progress or {}
        is_batch = bool(progress.get("batch"))
        lock_matches_task = str(rebuild_lock_owner or "") == str(task_id)
        # In the AIO image both the broker and result backend live in an
        # in-memory Redis process. After a container restart the database can
        # still say Pending while Celery has forgotten both the message and
        # its task result. A batch lock is written alongside publication, so a
        # missing/mismatched lock plus PENDING is reliable restart evidence.
        task_was_lost = (
            task_state == "PENDING" and is_batch and not lock_matches_task
        )
        if task_state in terminal_states or task_was_lost:
            stranded.append((policy.pk, str(task_id)))

    if stranded:
        recovery_started_at = timezone.now()
        for policy_id, _task_id in stranded:
            policy = VODAccessPolicy.objects.filter(pk=policy_id).values(
                "selection_progress"
            ).first()
            progress = (policy or {}).get("selection_progress") or {}
            original_reason = progress.get(
                "original_trigger_reason"
            ) or progress.get("trigger_reason")
            VODAccessPolicy.objects.filter(
                pk=policy_id,
                is_active=True,
                selection_status=VODAccessPolicy.SelectionStatus.PENDING,
            ).update(
                selection_started_at=recovery_started_at,
                selection_error="",
                selection_progress=_progress_payload(
                    "Recovering unpublished catalog task",
                    0,
                    queue="celery",
                    task_name=BATCH_PROFILE_TASK_NAME,
                    batch=True,
                    trigger_reason=(
                        "Automatic recovery: the previous Celery task is no "
                        "longer available after a service restart"
                    ),
                    original_trigger_reason=original_reason,
                ),
            )

    # A worker can be restarted after claiming a profile, leaving the database
    # in Building forever. Progress writes carry a heartbeat; recover only
    # builds with no heartbeat for a generous interval, and give the old build
    # generation a token that prevents it from activating after recovery.
    stalled_cutoff = timezone.now() - timedelta(minutes=15)
    stalled_building = []
    for policy in VODAccessPolicy.objects.filter(
        is_active=True,
        selection_status=VODAccessPolicy.SelectionStatus.BUILDING,
    ):
        progress = policy.selection_progress or {}
        updated_at = parse_datetime(str(progress.get("updated_at") or ""))
        if updated_at is not None and timezone.is_naive(updated_at):
            updated_at = timezone.make_aware(updated_at)
        heartbeat = updated_at or policy.selection_started_at
        if heartbeat is None or heartbeat < stalled_cutoff:
            stalled_building.append(
                (policy.pk, str(progress.get("task_id") or ""))
            )

    if stalled_building:
        for policy_id, _task_id in stalled_building:
            policy = VODAccessPolicy.objects.filter(pk=policy_id).values(
                "selection_progress"
            ).first()
            progress = (policy or {}).get("selection_progress") or {}
            original_reason = progress.get(
                "original_trigger_reason"
            ) or progress.get("trigger_reason")
            VODAccessPolicy.objects.filter(
                pk=policy_id,
                is_active=True,
                selection_status=VODAccessPolicy.SelectionStatus.BUILDING,
            ).update(
                selection_status=VODAccessPolicy.SelectionStatus.PENDING,
                selection_started_at=timezone.now(),
                selection_error="",
                selection_progress=_progress_payload(
                    "Recovering interrupted catalog build",
                    0,
                    queue="celery",
                    task_name=BATCH_PROFILE_TASK_NAME,
                    batch=True,
                    build_generation=f"recovery-{time.time_ns()}",
                    trigger_reason=(
                        "Automatic recovery: the previous VOD profile build "
                        "stopped reporting progress"
                    ),
                    original_trigger_reason=original_reason,
                ),
            )

    republished = False
    if stranded or stalled_building:
        try:
            lock_owner = cache.get(PROFILE_REBUILD_ENQUEUE_KEY)
            recorded_task_ids = {
                task_id
                for _, task_id in stranded + stalled_building
                if task_id
            }
            if lock_owner is None or str(lock_owner) in recorded_task_ids | {"1"}:
                cache.delete(PROFILE_REBUILD_ENQUEUE_KEY)
        except Exception:
            pass
    if stranded or stalled_building:
        republished = enqueue_all_profile_selection_rebuilds(pending_only=True)

    if republished:
        # The recovered global batch already consumes the newest catalog
        # generation, including any provider changes remembered while the old
        # task was stranded. Publishing a second batch here would duplicate
        # the same work and overwrite its task identity in the UI.
        try:
            cache.delete(VOD_PROFILE_REBUILD_AFTER_REFRESH_KEY)
        except Exception:
            pass
        deferred_refresh_published = False
    else:
        deferred_refresh_published = (
            _enqueue_deferred_profile_rebuild_after_vod_refreshes()
        )

    return {
        "stale_ready_requeued": repaired_ready,
        "stranded_pending": [policy_id for policy_id, _ in stranded],
        "stalled_building": [
            policy_id for policy_id, _ in stalled_building
        ],
        "republished": republished,
        "deferred_refresh_published": deferred_refresh_published,
    }


def _send_vod_refresh_progress(
    account_id,
    *,
    started_at,
    phase,
    progress,
    items_processed=None,
    items_total=None,
    provider_items_total=None,
):
    """Persist and broadcast coarse VOD refresh progress without per-row writes."""
    from apps.m3u.tasks import send_m3u_update

    elapsed = max(time.monotonic() - started_at, 0)
    progress = max(0, min(int(progress), 99))
    remaining = None
    if progress > 1 and elapsed > 0:
        remaining = max((elapsed / progress) * (100 - progress), 0)

    item_summary = ""
    if items_processed is not None and items_total is not None:
        item_summary = f" ({items_processed:,}/{items_total:,} eligible)"
        if (
            provider_items_total is not None
            and provider_items_total != items_total
        ):
            item_summary += f" · {provider_items_total:,} provider items"
    remaining_summary = (
        f" · approximately {max(round(remaining), 1)}s remaining"
        if remaining is not None
        else ""
    )
    message = f"VOD refresh: {phase}{item_summary}{remaining_summary}"
    M3UAccount.objects.filter(id=account_id).update(
        status=M3UAccount.Status.PARSING,
        last_message=message,
    )
    send_m3u_update(
        account_id,
        "vod_refresh",
        progress,
        status="processing",
        message=message,
        phase=phase,
        items_processed=items_processed,
        items_total=items_total,
        provider_items_total=provider_items_total,
        elapsed_time=elapsed,
        time_remaining=remaining,
    )


def _provider_vod_identity(item, id_field):
    """Return a usable provider ID/name pair, or ``None`` for a bad row.

    Xtream providers may explicitly return ``null`` or whitespace for required
    model identifiers. Reject those rows before building any
    model instances so one malformed item cannot roll back the whole batch.
    """
    if not isinstance(item, dict):
        return None
    raw_id = item.get(id_field)
    raw_name = item.get('name')
    provider_id = str(raw_id).strip() if raw_id is not None else ''
    name = str(raw_name).strip() if raw_name is not None else ''
    if not provider_id or not name:
        return None
    return provider_id, name


def _provider_category_id(item):
    """Return a normalized Xtream category ID, or ``None`` when absent."""
    if not isinstance(item, dict):
        return None
    raw_category_id = item.get('category_id')
    if raw_category_id is None:
        return None
    category_id = str(raw_category_id).strip()
    return category_id or None


def _empty_categories_should_abort(categories_data, account, category_type):
    """True when an empty provider response would wipe existing group selections."""
    if categories_data:
        return False
    return M3UVODCategoryRelation.objects.filter(
        m3u_account=account,
        category__category_type=category_type,
    ).exclude(category__name='Uncategorized').exists()


def _retain_enabled_vod_rows(rows, categories_by_provider, relations):
    """Compact a provider catalog in place to rows from enabled categories.

    Xtream's unscoped catalog endpoints return every provider item. Filtering
    before chunk processing avoids model construction and database lookups for
    disabled categories while retaining the single-request provider behavior.
    Non-empty provider category IDs that were ignored by discovery rules are
    skipped rather than being misclassified as Uncategorized.
    """
    provider_total = len(rows)
    enabled_provider_ids = set()

    for provider_id, category in categories_by_provider.items():
        if provider_id == '__uncategorized__':
            continue
        relation = relations.get(category.id)
        if relation is not None and relation.enabled:
            enabled_provider_ids.add(str(provider_id).strip())

    uncategorized = categories_by_provider.get('__uncategorized__')
    uncategorized_relation = (
        relations.get(uncategorized.id) if uncategorized is not None else None
    )
    uncategorized_enabled = bool(
        uncategorized_relation is not None and uncategorized_relation.enabled
    )

    write_index = 0
    skipped_disabled_or_unknown = 0
    for row in rows:
        if not isinstance(row, dict):
            skipped_disabled_or_unknown += 1
            continue
        provider_category_id = _provider_category_id(row)
        keep = (
            provider_category_id in enabled_provider_ids
            if provider_category_id
            else uncategorized_enabled
        )
        if keep:
            rows[write_index] = row
            write_index += 1
        else:
            skipped_disabled_or_unknown += 1

    del rows[write_index:]
    return {
        'provider_total': provider_total,
        'eligible_total': write_index,
        'skipped_total': skipped_disabled_or_unknown,
    }


def _title_match_key(value):
    text = unicodedata.normalize("NFKC", str(value or ""))
    return re.sub(r"\s+", " ", text).strip().casefold()


def _canonical_title_tiers(content):
    """Return primary, secondary, cleaned and provider title candidates."""
    primary = (
        [_title_match_key(content.display_name)]
        if content.display_name
        else []
    )
    metadata = content.tmdb_metadata if isinstance(content.tmdb_metadata, dict) else {}
    localized = metadata.get("localized") or {}
    secondary = []
    if isinstance(localized, dict):
        secondary = [
            _title_match_key(row.get("title"))
            for row in localized.values()
            if isinstance(row, dict) and row.get("title")
        ]
    primary_keys = set(primary)
    return (
        list(dict.fromkeys(value for value in primary if value)),
        list(
            dict.fromkeys(
                value
                for value in secondary
                if value and value not in primary_keys
            )
        ),
        [_title_match_key(content.clean_title)] if content.clean_title else [],
        [_title_match_key(content.name)] if content.name else [],
    )


def lookup_by_clean_title_year(model, title_year_pairs):
    """Return only unambiguous exact canonical title/year matches.

    Titles without a validated year are deliberately excluded. Primary,
    secondary, cleaned and provider titles are checked in that order. A key
    shared by two canonical rows in the same tier is ambiguous and absent.
    """
    wanted = {
        (_title_match_key(title), year)
        for title, year in title_year_pairs
        if _title_match_key(title) and year is not None
    }
    if not wanted:
        return {}
    years = {year for _, year in wanted}
    wanted_titles = {title for title, _ in wanted}
    from django.db.models.fields.json import KeyTextTransform
    from django.db.models.functions import Lower
    from core.models import CoreSettings

    annotations = {
        "_match_primary_title": Lower("display_name"),
        "_match_clean_title": Lower("clean_title"),
        "_match_provider_title": Lower("name"),
    }
    candidate_filter = (
        Q(_match_primary_title__in=wanted_titles)
        | Q(_match_clean_title__in=wanted_titles)
        | Q(_match_provider_title__in=wanted_titles)
    )
    localized = KeyTextTransform("localized", F("tmdb_metadata"))
    for index, language in enumerate(CoreSettings.get_tmdb_languages()):
        annotation = f"_match_localized_title_{index}"
        annotations[annotation] = Lower(
            KeyTextTransform(
                "title",
                KeyTextTransform(language, localized),
            )
        )
        candidate_filter |= Q(**{f"{annotation}__in": wanted_titles})

    tier_matches = [{} for _ in range(4)]
    candidates = (
        model.objects.filter(year__in=years)
        .annotate(**annotations)
        .filter(candidate_filter)
    )
    for content in candidates.only(
        "id",
        "name",
        "display_name",
        "clean_title",
        "year",
        "tmdb_id",
        "tmdb_match_id",
        "imdb_id",
        "tmdb_metadata",
    ):
        for tier, values in enumerate(_canonical_title_tiers(content)):
            for title_key in values:
                key = (title_key, content.year)
                if key not in wanted:
                    continue
                tier_matches[tier].setdefault(key, {})[content.pk] = content
    matches = {}
    for key in wanted:
        for candidates_by_key in tier_matches:
            candidates = list(candidates_by_key.get(key, {}).values())
            if len(candidates) == 1:
                matches[key] = candidates[0]
                break
            if len(candidates) > 1:
                break
    return matches


def _compatible_title_year_match(content, *, tmdb_id=None, imdb_id=None):
    """Reject a fallback candidate carrying a conflicting external identity."""
    candidate_tmdb_ids = {
        str(value)
        for value in (content.tmdb_id, content.tmdb_match_id)
        if value not in (None, "", 0, "0")
    }
    candidate_imdb_id = str(content.imdb_id or "").strip()
    if tmdb_id and candidate_tmdb_ids and str(tmdb_id) not in candidate_tmdb_ids:
        return False
    if imdb_id and candidate_imdb_id and str(imdb_id) != candidate_imdb_id:
        return False
    return True


def _coalesce_batch_title_year_entries(entries):
    """Merge compatible list rows that only differ by available identifiers.

    A fresh provider import can contain the same cleaned title/year once with
    an external ID and once without one. Database fallback matching cannot see
    either not-yet-created canonical, so resolve that safe case inside the
    batch before models and source relations are built. Conflicting TMDB or
    IMDb identities are deliberately kept separate.
    """
    grouped = {}
    for key, data in entries.items():
        props = data.get("props") or {}
        year = props.get("year")
        title_key = _title_match_key(props.get("clean_title"))
        if title_key and year is not None:
            grouped.setdefault((title_key, year), []).append(key)

    for keys in grouped.values():
        if len(keys) < 2:
            continue
        tmdb_ids = {
            str((entries[key].get("props") or {}).get("tmdb_id"))
            for key in keys
            if (entries[key].get("props") or {}).get("tmdb_id")
        }
        imdb_ids = {
            str((entries[key].get("props") or {}).get("imdb_id"))
            for key in keys
            if (entries[key].get("props") or {}).get("imdb_id")
        }
        if len(tmdb_ids) > 1 or len(imdb_ids) > 1:
            continue
        target_key = next(
            (key for key in keys if str(key).startswith("tmdb_")),
            next(
                (key for key in keys if str(key).startswith("imdb_")),
                keys[0],
            ),
        )
        target = entries[target_key]
        for source_key in keys:
            if source_key == target_key or source_key not in entries:
                continue
            source = entries.pop(source_key)
            merge_blank_vod_list_props(target["props"], source["props"])
            for source_id, occurrence in source.get("occurrences", {}).items():
                target["occurrences"].setdefault(source_id, occurrence)
            if not target.get("logo_url") and source.get("logo_url"):
                target["logo_url"] = source["logo_url"]


def _category_title_cleanup(category_relation):
    properties = getattr(category_relation, "custom_properties", None) or {}
    return properties.get("title_cleanup") if isinstance(properties, dict) else None


def category_cleanup_rules_for_content(model, content_rows):
    """Resolve the category rule belonging to each canonical provider title."""
    rows = list(content_rows)
    names = {
        int(row["id"] if isinstance(row, dict) else row.id): str(
            (row.get("name") if isinstance(row, dict) else row.name) or ""
        ).strip()
        for row in rows
    }
    if not names:
        return {}
    if model is Movie:
        relation_model = M3UMovieRelation
        content_field = "movie_id"
    elif model is Series:
        relation_model = M3USeriesRelation
        content_field = "series_id"
    else:
        return {}
    relations = list(
        relation_model.objects.filter(**{f"{content_field}__in": names})
        .only(
            "id", content_field, "m3u_account_id", "category_id",
            "custom_properties",
        )
        .order_by("id")
    )
    category_keys = {
        (relation.m3u_account_id, relation.category_id)
        for relation in relations
        if relation.category_id
    }
    category_rules = {
        (row.m3u_account_id, row.category_id): _category_title_cleanup(row)
        for row in M3UVODCategoryRelation.objects.filter(
            m3u_account_id__in={key[0] for key in category_keys},
            category_id__in={key[1] for key in category_keys},
        ).only("m3u_account_id", "category_id", "custom_properties")
    } if category_keys else {}
    resolved = {}
    decided = set()
    for relation in relations:
        content_id = getattr(relation, content_field)
        if content_id in decided:
            continue
        properties = relation.custom_properties or {}
        basic = properties.get("basic_data") or {}
        provider_title = str(
            basic.get("name") or basic.get("title") or ""
        ).strip()
        if provider_title != names.get(content_id):
            continue
        decided.add(content_id)
        rule = category_rules.get(
            (relation.m3u_account_id, relation.category_id)
        )
        if rule:
            resolved[content_id] = rule
    return resolved


def refresh_canonical_clean_titles(
    movie_ids=(),
    series_ids=(),
    *,
    lock_processed=False,
):
    """Apply the configured prefix cleanup to imported canonical titles.

    A successful TMDB enrichment owns the clean title.  All other rows derive
    it from the provider-backed canonical title and the explicit prefix list.
    This keeps output formatting deterministic even when automatic TMDB lookup
    is disabled.
    """
    from core.models import CoreSettings
    from .tmdb import clean_lookup_title

    rules = CoreSettings.get_tmdb_title_rules()
    year_rules = CoreSettings.get_tmdb_year_rules()
    updated_count = 0
    for model, ids in ((Movie, movie_ids), (Series, series_ids)):
        ids = list(dict.fromkeys(ids))
        if not ids:
            continue
        for offset in range(0, len(ids), 500):
            contents = list(model.objects.filter(
                pk__in=ids[offset : offset + 500],
                tmdb_enrichment_signature="",
            ).only(
                "id",
                "name",
                "display_name",
                "clean_title",
                "year",
                "tmdb_status",
                "tmdb_enrichment_signature",
            ))
            group_rules = category_cleanup_rules_for_content(model, contents)
            updates = []
            for content in contents:
                if content.tmdb_status == "matched" and content.display_name:
                    clean_title = content.display_name.strip()
                else:
                    clean_title = clean_lookup_title(
                        content.name,
                        display_name=content.display_name,
                        year=content.year,
                        rules=rules,
                        year_rules=year_rules,
                        group_rule=group_rules.get(content.id),
                    )
                clean_title = clean_title[:255]
                title_changed = clean_title != content.clean_title
                if title_changed:
                    content.clean_title = clean_title
                    updated_count += 1
                if lock_processed:
                    content.tmdb_enrichment_signature = TMDB_ENRICHMENT_LOCK_VALUE
                if title_changed or lock_processed:
                    updates.append(content)
            if updates:
                fields = ["clean_title"]
                if lock_processed:
                    fields.append("tmdb_enrichment_signature")
                model.objects.bulk_update(updates, fields, batch_size=500)
    return updated_count


@shared_task(bind=True, max_retries=120, default_retry_delay=30)
def refresh_vod_content(self, account_id):
    """Run a VOD import without overlapping another catalog refresh."""
    if not acquire_task_lock("refresh_single_m3u_account", account_id):
        logger.info(
            "Account %s already has a catalog refresh running; retrying VOD refresh",
            account_id,
        )
        raise self.retry(countdown=30)

    lock_renewer = TaskLockRenewer("refresh_single_m3u_account", account_id)
    lock_renewer.start()
    try:
        return _refresh_vod_content_impl(account_id)
    finally:
        lock_renewer.stop()
        release_task_lock("refresh_single_m3u_account", account_id)


def _refresh_vod_content_impl(account_id):
    """Refresh VOD content for an M3U account with batch processing for improved performance"""
    # Import here to avoid circular import
    from apps.m3u.tasks import send_m3u_update

    try:
        account = M3UAccount.objects.select_related("user_agent").get(id=account_id, is_active=True)

        if account.account_type != M3UAccount.Types.XC:
            logger.warning(f"VOD refresh called for non-XC account {account_id}")
            return "VOD refresh only available for XtreamCodes accounts"

        logger.info(f"Starting batch VOD refresh for account {account.name}")
        # Include titles whose source may disappear during this scan. They can
        # remain canonical through another provider and need their field-level
        # provider projection recalculated after cleanup.
        affected_movie_ids = set(
            M3UMovieRelation.objects.filter(m3u_account_id=account_id)
            .values_list("movie_id", flat=True)
        )
        affected_series_ids = set(
            M3USeriesRelation.objects.filter(m3u_account_id=account_id)
            .values_list("series_id", flat=True)
        )
        start_time = timezone.now()
        progress_started_at = time.monotonic()

        # The Live import has already returned the account to SUCCESS before
        # this independent VOD task starts.  Keep the account in PARSING for
        # the complete VOD mutation window so profile workers wait for a stable
        # catalog instead of repeatedly switching between Pending and Building.
        M3UAccount.objects.filter(pk=account_id).update(
            status=M3UAccount.Status.PARSING,
            last_message="VOD refresh in progress...",
        )

        # Send start notification
        _send_vod_refresh_progress(
            account_id,
            started_at=progress_started_at,
            phase="Fetching categories",
            progress=1,
        )

        with XtreamCodesClient(
            account.server_url,
            account.username,
            account.password,
            account.get_user_agent_string()
        ) as client:

            category_maps = refresh_categories(account.id, client)
            if category_maps is None:
                message = (
                    f"Provider returned no VOD categories for account {account.name}; "
                    "aborting VOD refresh to preserve existing category selections"
                )
                logger.warning(message)
                M3UAccount.objects.filter(id=account_id).update(
                    status=M3UAccount.Status.ERROR,
                    last_message=f"VOD refresh failed: {message}",
                )
                send_m3u_update(account_id, "vod_refresh", 100, status="error",
                               message=f"VOD refresh failed: {message}")
                return f"VOD refresh failed: {message}"

            movie_categories, series_categories = category_maps
            _send_vod_refresh_progress(
                account_id,
                started_at=progress_started_at,
                phase="Categories loaded",
                progress=8,
            )

            logger.debug("Fetching relations for filtering category filtering")
            relations = { rel.category_id: rel for rel in M3UVODCategoryRelation.objects
                .filter(m3u_account=account)
                .select_related("category", "m3u_account")
            }

            # Refresh movies with batch processing (pass scan start time)
            movie_catalog = refresh_movies(
                client,
                account,
                movie_categories,
                relations,
                scan_start_time=start_time,
                progress_started_at=progress_started_at,
            )

            # Refresh series with batch processing (pass scan start time)
            series_catalog = refresh_series(
                client,
                account,
                series_categories,
                relations,
                scan_start_time=start_time,
                progress_started_at=progress_started_at,
            )

        # Cleanup orphaned VOD content after refresh (scoped to this account only)
        logger.info(f"Starting cleanup of orphaned VOD content for account {account.name}")
        _send_vod_refresh_progress(
            account_id,
            started_at=progress_started_at,
            phase="Cleaning up",
            progress=97,
        )
        cleanup_result = cleanup_orphaned_vod_content(
            account_id=account_id,
            scan_start_time=start_time,
            stale_days=account.stale_stream_days,
        )
        logger.info(f"VOD cleanup completed: {cleanup_result}")

        # Provider rows are already in memory during import. Use their compact,
        # order-independent signatures to avoid rebuilding every user profile
        # after a scheduled scan that did not change selectable VOD content.
        movie_fingerprint = (
            movie_catalog.get("fingerprint")
            if isinstance(movie_catalog, dict)
            else None
        )
        series_fingerprint = (
            series_catalog.get("fingerprint")
            if isinstance(series_catalog, dict)
            else None
        )
        fingerprints_available = bool(movie_fingerprint and series_fingerprint)
        current_fingerprint = (
            hashlib.sha256(
                (
                    f"schema:{VOD_PROVIDER_METADATA_SCHEMA}|"
                    f"movie:{movie_fingerprint}|"
                    f"series:{series_fingerprint}"
                ).encode("utf-8")
            ).hexdigest()
            if fingerprints_available
            else ""
        )
        latest_properties = (
            M3UAccount.objects.filter(pk=account.pk)
            .values_list("custom_properties", flat=True)
            .first()
            or {}
        )
        previous_fingerprint = latest_properties.get(
            "vod_profile_catalog_fingerprint", ""
        )
        catalog_changed = (
            not fingerprints_available
            or not previous_fingerprint
            or previous_fingerprint != current_fingerprint
        )

        if catalog_changed:
            _send_vod_refresh_progress(
                account_id,
                started_at=progress_started_at,
                phase="Merging provider metadata",
                progress=98,
            )
            affected_movie_ids.update(
                M3UMovieRelation.objects.filter(m3u_account_id=account_id)
                .values_list("movie_id", flat=True)
            )
            affected_series_ids.update(
                M3USeriesRelation.objects.filter(m3u_account_id=account_id)
                .values_list("series_id", flat=True)
            )
            from .provider_metadata import (
                reconcile_movie_provider_metadata,
                reconcile_series_provider_metadata,
            )

            reconciled_movies = reconcile_movie_provider_metadata(
                affected_movie_ids
            )
            reconciled_series = reconcile_series_provider_metadata(
                affected_series_ids
            )
            from core.models import CoreSettings

            lock_after_cleanup = not (
                CoreSettings.get_tmdb_auto_enrich()
                and CoreSettings.get_tmdb_api_token()
            )
            refreshed_clean_titles = refresh_canonical_clean_titles(
                affected_movie_ids,
                affected_series_ids,
                lock_processed=lock_after_cleanup,
            )
            logger.info(
                "Reconciled canonical provider metadata for %d movies and %d series; "
                "updated %d clean titles",
                reconciled_movies,
                reconciled_series,
                refreshed_clean_titles,
            )

        if current_fingerprint:
            updated_properties = {
                **latest_properties,
                "vod_profile_catalog_fingerprint": current_fingerprint,
                "vod_catalog_counts": {
                    "movies": movie_catalog,
                    "series": series_catalog,
                },
            }
            M3UAccount.objects.filter(pk=account.pk).update(
                custom_properties=updated_properties
            )

        if catalog_changed:
            # Most import writes use bulk_create/bulk_update and intentionally
            # skip model signals. Invalidate once per changed completed scan.
            from apps.vod.catalog_cache import bump_catalog_generation
            bump_catalog_generation()
            _remember_profile_rebuild_after_vod_refresh()
        else:
            logger.info(
                "VOD output catalog for account %s is unchanged; profile rebuild skipped",
                account.name,
            )

        end_time = timezone.now()
        duration = (end_time - start_time).total_seconds()
        logger.info(
            "Batch VOD refresh completed for account %s in %.2f seconds",
            account.name,
            duration,
        )

        # Send completion notification
        success_message = f"VOD refresh completed in {duration:.2f} seconds"
        latest_properties = (
            M3UAccount.objects.filter(pk=account_id)
            .values_list("custom_properties", flat=True)
            .first()
            or {}
        )
        updated_properties = {
            **latest_properties,
            "refresh_timings": {
                **(latest_properties.get("refresh_timings") or {}),
                "vod_seconds": round(duration, 2),
                "vod_completed_at": end_time.isoformat(),
            },
        }
        M3UAccount.objects.filter(id=account_id).update(
            status=M3UAccount.Status.SUCCESS,
            last_message=success_message,
            custom_properties=updated_properties,
        )
        send_m3u_update(account_id, "vod_refresh", 100, status="success",
                       message=success_message)

        return f"Batch VOD refresh completed for account {account.name} in {duration:.2f} seconds"

    except Exception as e:
        import traceback
        logger.error(f"Error refreshing VOD for account {account_id}: {str(e)}")
        logger.error(f"Full traceback:\n{traceback.format_exc()}")

        # Send error notification
        error_message = f"VOD refresh failed: {str(e)}"
        M3UAccount.objects.filter(id=account_id).update(
            status=M3UAccount.Status.ERROR,
            last_message=error_message,
        )
        send_m3u_update(account_id, "vod_refresh", 100, status="error",
                       message=error_message)

        return f"VOD refresh failed: {str(e)}"

def refresh_categories(account_id, client=None):
    account = M3UAccount.objects.select_related("user_agent").get(id=account_id, is_active=True)

    if not client:
        client = XtreamCodesClient(
            account.server_url,
            account.username,
            account.password,
            account.get_user_agent_string()
        )
    logger.info(f"Refreshing movie categories for account {account.name}")

    # First, get the category list to properly map category IDs and names
    logger.info("Fetching movie categories from provider...")
    categories_data = client.get_vod_categories()
    if _empty_categories_should_abort(categories_data, account, 'movie'):
        logger.warning(
            f"Provider returned no movie categories for account {account.id} "
            f"({account.name}); aborting VOD refresh to preserve existing category selections"
        )
        return None
    movie_item_names = _discovery_item_names(
        client, account, "movie", categories_data
    )
    category_map = batch_create_categories(
        categories_data,
        'movie',
        account,
        item_names_by_provider_id=movie_item_names,
    )

    # Map provider category IDs to persisted category objects.
    movies_category_id_map = {}
    for cat_data in categories_data:
        cat_name = cat_data.get('category_name', 'Unknown')
        provider_cat_id = _provider_category_id(cat_data)
        our_category = category_map.get(cat_name)
        if provider_cat_id is not None and our_category:
            movies_category_id_map[provider_cat_id] = our_category

    # Get the category list to properly map category IDs and names
    logger.info("Fetching series categories from provider...")
    categories_data = client.get_series_categories()
    if _empty_categories_should_abort(categories_data, account, 'series'):
        logger.warning(
            f"Provider returned no series categories for account {account.id} "
            f"({account.name}); aborting VOD refresh to preserve existing category selections"
        )
        return None
    series_item_names = _discovery_item_names(
        client, account, "series", categories_data
    )
    category_map = batch_create_categories(
        categories_data,
        'series',
        account,
        item_names_by_provider_id=series_item_names,
    )

    # Map provider category IDs to persisted category objects.
    series_category_id_map = {}
    for cat_data in categories_data:
        cat_name = cat_data.get('category_name', 'Unknown')
        provider_cat_id = _provider_category_id(cat_data)
        our_category = category_map.get(cat_name)
        if provider_cat_id is not None and our_category:
            series_category_id_map[provider_cat_id] = our_category

    return movies_category_id_map, series_category_id_map

def refresh_movies(
    client,
    account,
    categories_by_provider,
    relations,
    scan_start_time=None,
    progress_started_at=None,
):
    """Refresh movie content using single API call for all movies"""
    logger.info(f"Refreshing movies for account {account.name}")

    # Ensure "Uncategorized" category exists for movies without a category
    uncategorized_category, created = VODCategory.objects.get_or_create(
        name="Uncategorized",
        category_type="movie",
        defaults={}
    )

    # Ensure there's a relation for the Uncategorized category
    account_custom_props = account.custom_properties or {}
    auto_enable_new = False

    uncategorized_relation, rel_created = M3UVODCategoryRelation.objects.get_or_create(
        category=uncategorized_category,
        m3u_account=account,
        defaults={
            'enabled': auto_enable_new,
            'custom_properties': {}
        }
    )

    if created:
        logger.info(f"Created 'Uncategorized' category for movies")
    if rel_created:
        logger.info(f"Created relation for 'Uncategorized' category (enabled={auto_enable_new})")

    # Add uncategorized category to relations dict for easy access
    relations[uncategorized_category.id] = uncategorized_relation

    # Add to categories_by_provider with a special key for items without category
    categories_by_provider['__uncategorized__'] = uncategorized_category

    # Get all movies in a single API call
    logger.info("Fetching all movies from provider...")
    all_movies_data = client.get_vod_streams()  # No category_id = get all movies

    catalog_counts = _retain_enabled_vod_rows(
        all_movies_data,
        categories_by_provider,
        relations,
    )

    # Process only enabled movie categories in chunks. The provider total is
    # still reported separately so the UI explains the reduction.
    chunk_size = 1000
    total_movies = len(all_movies_data)
    provider_total_movies = catalog_counts['provider_total']
    total_chunks = (total_movies + chunk_size - 1) // chunk_size if total_movies > 0 else 0

    logger.info(
        "Movie catalog filtered from %d provider rows to %d enabled rows",
        provider_total_movies,
        total_movies,
    )

    if progress_started_at is not None:
        _send_vod_refresh_progress(
            account.id,
            started_at=progress_started_at,
            phase="Processing movies",
            progress=10,
            items_processed=0,
            items_total=total_movies,
            provider_items_total=provider_total_movies,
        )

    for i in range(0, total_movies, chunk_size):
        chunk = all_movies_data[i:i + chunk_size]
        chunk_num = (i // chunk_size) + 1

        logger.info(f"Processing movie chunk {chunk_num}/{total_chunks} ({len(chunk)} movies)")
        process_movie_batch(account, chunk, categories_by_provider, relations, scan_start_time)
        if progress_started_at is not None:
            completed = min(i + len(chunk), total_movies)
            progress = 10 + round((completed / max(total_movies, 1)) * 40)
            _send_vod_refresh_progress(
                account.id,
                started_at=progress_started_at,
                phase="Processing movies",
                progress=progress,
                items_processed=completed,
                items_total=total_movies,
                provider_items_total=provider_total_movies,
            )

    if progress_started_at is not None and total_movies == 0:
        _send_vod_refresh_progress(
            account.id,
            started_at=progress_started_at,
            phase="Processing movies",
            progress=50,
            items_processed=0,
            items_total=0,
            provider_items_total=provider_total_movies,
        )

    fingerprint = _provider_vod_fingerprint(all_movies_data)
    del all_movies_data
    logger.info(
        "Completed processing %d eligible movies in %d chunks (%d provider rows)",
        total_movies,
        total_chunks,
        provider_total_movies,
    )
    return {
        "provider_total": provider_total_movies,
        "selected_total": total_movies,
        "fingerprint": fingerprint,
    }


def refresh_series(
    client,
    account,
    categories_by_provider,
    relations,
    scan_start_time=None,
    progress_started_at=None,
):
    """Refresh series content using single API call for all series"""
    logger.info(f"Refreshing series for account {account.name}")

    # Ensure "Uncategorized" category exists for series without a category
    uncategorized_category, created = VODCategory.objects.get_or_create(
        name="Uncategorized",
        category_type="series",
        defaults={}
    )

    # Ensure there's a relation for the Uncategorized category
    account_custom_props = account.custom_properties or {}
    auto_enable_new = False

    uncategorized_relation, rel_created = M3UVODCategoryRelation.objects.get_or_create(
        category=uncategorized_category,
        m3u_account=account,
        defaults={
            'enabled': auto_enable_new,
            'custom_properties': {}
        }
    )

    if created:
        logger.info(f"Created 'Uncategorized' category for series")
    if rel_created:
        logger.info(f"Created relation for 'Uncategorized' category (enabled={auto_enable_new})")

    # Add uncategorized category to relations dict for easy access
    relations[uncategorized_category.id] = uncategorized_relation

    # Add to categories_by_provider with a special key for items without category
    categories_by_provider['__uncategorized__'] = uncategorized_category

    # Get all series in a single API call
    logger.info("Fetching all series from provider...")
    all_series_data = client.get_series()  # No category_id = get all series

    catalog_counts = _retain_enabled_vod_rows(
        all_series_data,
        categories_by_provider,
        relations,
    )

    # Process only enabled series categories in chunks.
    chunk_size = 1000
    total_series = len(all_series_data)
    provider_total_series = catalog_counts['provider_total']
    total_chunks = (total_series + chunk_size - 1) // chunk_size if total_series > 0 else 0

    logger.info(
        "Series catalog filtered from %d provider rows to %d enabled rows",
        provider_total_series,
        total_series,
    )

    if progress_started_at is not None:
        _send_vod_refresh_progress(
            account.id,
            started_at=progress_started_at,
            phase="Processing series",
            progress=52,
            items_processed=0,
            items_total=total_series,
            provider_items_total=provider_total_series,
        )

    for i in range(0, total_series, chunk_size):
        chunk = all_series_data[i:i + chunk_size]
        chunk_num = (i // chunk_size) + 1

        logger.info(f"Processing series chunk {chunk_num}/{total_chunks} ({len(chunk)} series)")
        process_series_batch(account, chunk, categories_by_provider, relations, scan_start_time)
        if progress_started_at is not None:
            completed = min(i + len(chunk), total_series)
            progress = 52 + round((completed / max(total_series, 1)) * 43)
            _send_vod_refresh_progress(
                account.id,
                started_at=progress_started_at,
                phase="Processing series",
                progress=progress,
                items_processed=completed,
                items_total=total_series,
                provider_items_total=provider_total_series,
            )

    if progress_started_at is not None and total_series == 0:
        _send_vod_refresh_progress(
            account.id,
            started_at=progress_started_at,
            phase="Processing series",
            progress=95,
            items_processed=0,
            items_total=0,
            provider_items_total=provider_total_series,
        )

    fingerprint = _provider_vod_fingerprint(all_series_data)
    del all_series_data
    logger.info(
        "Completed processing %d eligible series in %d chunks (%d provider rows)",
        total_series,
        total_chunks,
        provider_total_series,
    )
    return {
        "provider_total": provider_total_series,
        "selected_total": total_series,
        "fingerprint": fingerprint,
    }


def _discovery_item_names(client, account, scope, categories_data):
    """Fetch contained names only when a content-aware rule needs them."""
    if not account.group_rules.filter(
        scope=scope,
        match_field="item_name",
        enabled=True,
    ).exists():
        return {}

    provider_rows = (
        client.get_vod_streams() if scope == "movie" else client.get_series()
    )
    names = {}
    for row in provider_rows:
        provider_category_id = _provider_category_id(row) or ""
        names.setdefault(provider_category_id, []).append(str(row.get("name") or ""))
    return names


def batch_create_categories(
    categories_data,
    category_type,
    account,
    *,
    item_names_by_provider_id=None,
):
    """Create categories in batch and return a mapping"""
    category_names = [cat.get('category_name', 'Unknown') for cat in categories_data]
    provider_id_by_name = {
        cat.get('category_name', 'Unknown'): str(cat.get('category_id') or '')
        for cat in categories_data
    }

    relations_to_create = []

    # Get existing categories
    logger.debug(f"Starting VOD {category_type} category refresh")
    existing_categories = {
        cat.name: cat for cat in VODCategory.objects.filter(
            name__in=category_names,
            category_type=category_type
        )
    }

    logger.debug(f"Found {len(existing_categories)} existing categories")

    # Check if we should auto-enable new categories based on account settings
    account_custom_props = account.custom_properties or {}
    if category_type == 'movie':
        auto_enable_new = False
    else:  # series
        auto_enable_new = False

    from apps.m3u.group_rules import account_group_rules, evaluate_group_rules
    from apps.m3u.account_templates import template_group_selection_map

    discovery_rules = account_group_rules(account, category_type)
    template_selections = template_group_selection_map(account, category_type)
    item_names_by_provider_id = item_names_by_provider_id or {}
    existing_relation_names = set(
        M3UVODCategoryRelation.objects.filter(
            m3u_account=account,
            category__category_type=category_type,
            category__name__in=category_names,
        ).values_list("category__name", flat=True)
    )
    decisions = {}
    kept_names = []
    for name in category_names:
        if name in existing_relation_names:
            kept_names.append(name)
            continue
        if str(name).strip().casefold() in template_selections:
            kept_names.append(name)
            continue
        provider_id = provider_id_by_name.get(name, "")
        decision = evaluate_group_rules(
            discovery_rules,
            group_name=name,
            item_names=item_names_by_provider_id.get(provider_id, []),
            default_enabled=auto_enable_new,
        )
        decisions[name] = decision
        if not decision.ignored:
            kept_names.append(name)
        else:
            logger.info(
                "Ignoring new %s category '%s' for account %s by discovery rule %s",
                category_type,
                name,
                account.id,
                decision.matched_rule_id,
            )

    def new_relation_properties(decision, selection):
        properties = {}
        if decision and decision.matched_rule_id:
            properties["discovery_rule_id"] = decision.matched_rule_id
        cleanup = (selection or {}).get("title_cleanup") or {}
        if cleanup:
            properties["title_cleanup"] = dict(cleanup)
        return properties

    category_names = kept_names
    existing_categories = {
        name: category
        for name, category in existing_categories.items()
        if name in category_names
    }

    # Create missing categories in batch
    new_categories = []

    for name in category_names:
        if name not in existing_categories:
            # Always create new categories
            new_categories.append(VODCategory(name=name, category_type=category_type))
        elif name not in existing_relation_names:
            # Existing category - create relationship with enabled based on auto_enable setting
            # (category exists globally but is new to this account)
            decision = decisions.get(name)
            selection = template_selections.get(str(name).strip().casefold())
            relations_to_create.append(
                M3UVODCategoryRelation(
                    category=existing_categories[name],
                    m3u_account=account,
                    custom_properties=new_relation_properties(
                        decision, selection
                    ),
                    enabled=(
                        bool(selection.get("enabled", False))
                        if selection
                        else decision.enabled if decision else auto_enable_new
                    ),
                    metadata_defaults=(
                        selection.get("metadata_defaults") or {}
                        if selection
                        else (decision.metadata_defaults or {}) if decision else {}
                    ),
                )
            )

    logger.debug(f"{len(new_categories)} new categories found")
    logger.debug(f"{len(relations_to_create)} existing categories found for account")

    if new_categories:
        logger.debug("Creating new categories...")
        created_categories = list(VODCategory.bulk_create_and_fetch(new_categories, ignore_conflicts=True))

        # Create relations for newly created categories with enabled based on auto_enable setting
        for cat in created_categories:
            decision = decisions.get(cat.name)
            selection = template_selections.get(
                str(cat.name).strip().casefold()
            )
            enabled = (
                bool(selection.get("enabled", False))
                if selection
                else decision.enabled if decision else auto_enable_new
            )
            if not enabled:
                logger.info(f"New {category_type} category '{cat.name}' created but DISABLED - auto_enable_new_groups is disabled for account {account.id}")

            relations_to_create.append(
                M3UVODCategoryRelation(
                    category=cat,
                    m3u_account=account,
                    custom_properties=new_relation_properties(
                        decision, selection
                    ),
                    enabled=enabled,
                    metadata_defaults=(
                        selection.get("metadata_defaults") or {}
                        if selection
                        else (decision.metadata_defaults or {}) if decision else {}
                    ),
                )
            )

        # Convert to dictionary for easy lookup
        newly_created = {cat.name: cat for cat in created_categories}
        existing_categories.update(newly_created)

    # Create missing relations
    logger.debug("Updating category account relations...")
    M3UVODCategoryRelation.objects.bulk_create(relations_to_create, ignore_conflicts=True)

    # Delete orphaned category relationships (categories no longer in the M3U source)
    # Exclude "Uncategorized" from cleanup as it's a special category we manage
    current_category_ids = set(existing_categories[name].id for name in category_names)
    existing_relations = M3UVODCategoryRelation.objects.filter(
        m3u_account=account,
        category__category_type=category_type
    ).select_related('category')

    relations_to_delete = [
        rel for rel in existing_relations
        if rel.category_id not in current_category_ids and rel.category.name != "Uncategorized"
    ]

    if relations_to_delete:
        M3UVODCategoryRelation.objects.filter(
            id__in=[rel.id for rel in relations_to_delete]
        ).delete()
        logger.info(f"Deleted {len(relations_to_delete)} orphaned {category_type} category relationships for account {account.id}: {[rel.category.name for rel in relations_to_delete]}")

        # Check if any of the deleted relationships left categories with no remaining associations
        orphaned_category_ids = []
        for rel in relations_to_delete:
            category = rel.category

            # Check if this category has any remaining M3U account relationships
            remaining_relationships = M3UVODCategoryRelation.objects.filter(
                category=category
            ).exists()

            # If no relationships remain, it's safe to delete the category
            if not remaining_relationships:
                orphaned_category_ids.append(category.id)
                logger.debug(f"Category '{category.name}' has no remaining associations and will be deleted")

        # Delete orphaned categories
        if orphaned_category_ids:
            VODCategory.objects.filter(id__in=orphaned_category_ids).delete()
            logger.info(f"Deleted {len(orphaned_category_ids)} orphaned {category_type} categories with no remaining associations")

    # 🔑 Fetch all relations for this account, for all categories
    # relations = { rel.id: rel for rel in M3UVODCategoryRelation.objects
    #     .filter(category__in=existing_categories.values(), m3u_account=account)
    #     .select_related("category", "m3u_account")
    # }

    # Attach relations to category objects
    # for rel in relations:
    #     existing_categories[rel.category.name]['relation'] = {
    #         "relation_id": rel.id,
    #         "category_id": rel.category_id,
    #         "account_id": rel.m3u_account_id,
    #     }


    return existing_categories



@shared_task
def process_movie_batch(account, batch, categories, relations, scan_start_time=None):
    """Process a batch of movies using simple bulk operations like M3U processing"""
    logger.info(f"Processing movie batch of {len(batch)} movies for account {account.name}")

    movies_to_create = []
    movies_to_update = []
    relations_to_create = []
    relations_to_update = []

    movie_keys = {}  # For deduplication like M3U stream_hashes
    skipped_invalid = []
    from core.models import CoreSettings

    title_rules = CoreSettings.get_tmdb_title_rules()
    year_rules = CoreSettings.get_tmdb_year_rules()

    # Process each movie in the batch
    for movie_data in batch:
        identity = _provider_vod_identity(movie_data, 'stream_id')
        if identity is None:
            skipped_invalid.append(
                movie_data.get('stream_id') if isinstance(movie_data, dict) else None
            )
            continue

        try:
            stream_id, name = identity

            # Get category with proper error handling
            category = None

            provider_cat_id = _provider_category_id(movie_data)
            movie_data['_provider_category_id'] = provider_cat_id
            movie_data['_category_id'] = None

            logger.debug(f"Checking for existing provider category ID {provider_cat_id}")
            if provider_cat_id in categories:
                category = categories[provider_cat_id]
                movie_data['_category_id'] = category.id
                logger.debug(f"Found category {category.name} (ID: {category.id}) for movie {name}")

                relation = relations.get(category.id, None)
                if relation and not relation.enabled:
                    logger.debug("Skipping disabled category")
                    continue
            elif provider_cat_id is None:
                # Assign only genuinely uncategorized rows. A non-empty
                # unknown ID belongs to a category intentionally omitted by
                # discovery rules and must never leak into Uncategorized.
                logger.debug(f"No category ID provided for movie {name}, assigning to 'Uncategorized'")
                category = categories.get('__uncategorized__')
                if category:
                    movie_data['_category_id'] = category.id
                    # Check if uncategorized is disabled
                    relation = relations.get(category.id, None)
                    if relation and not relation.enabled:
                        logger.debug("Skipping disabled 'Uncategorized' category")
                        continue
            else:
                logger.debug(
                    "Skipping movie %s from unknown or ignored provider category %s",
                    name,
                    provider_cat_id,
                )
                continue

            # Extract metadata
            year = extract_year_from_data(
                movie_data, 'name', year_rules=year_rules
            )
            tmdb_id = movie_data.get('tmdb_id') or movie_data.get('tmdb')
            imdb_id = movie_data.get('imdb_id') or movie_data.get('imdb')

            # Clean empty string IDs and zero values (some providers use 0 to indicate no ID)
            if tmdb_id == '' or tmdb_id == 0 or tmdb_id == '0':
                tmdb_id = None
            if imdb_id == '' or imdb_id == 0 or imdb_id == '0':
                imdb_id = None

            category_relation = relations.get(category.id) if category else None
            from .tmdb import clean_lookup_title

            clean_title = clean_lookup_title(
                name,
                year=year,
                rules=title_rules,
                year_rules=year_rules,
                group_rule=_category_title_cleanup(category_relation),
            ) or name

            # Prefer external IDs, then an exact cleaned-title/year identity.
            if tmdb_id:
                movie_key = f"tmdb_{tmdb_id}"
            elif imdb_id:
                movie_key = f"imdb_{imdb_id}"
            elif year is not None:
                movie_key = f"title_{_title_match_key(clean_title)}_{year}"
            else:
                movie_key = f"source_{stream_id}"

            # Canonical metadata is deduplicated, but every upstream stream
            # remains a source relation. This avoids silently dropping another
            # category carrying the same TMDB/IMDB title in the same batch.
            if movie_key in movie_keys:
                movie_keys[movie_key]['occurrences'].setdefault(stream_id, {
                    'category': category,
                    'movie_data': movie_data,
                })
                incoming_props, incoming_logo = build_movie_list_props(
                    movie_data, name, clean_title, year, tmdb_id, imdb_id,
                )
                merge_blank_vod_list_props(movie_keys[movie_key]['props'], incoming_props)
                if not movie_keys[movie_key].get('logo_url') and incoming_logo:
                    movie_keys[movie_key]['logo_url'] = incoming_logo
                continue

            movie_props, logo_url = build_movie_list_props(
                movie_data, name, clean_title, year, tmdb_id, imdb_id,
            )

            movie_keys[movie_key] = {
                'props': movie_props,
                'logo_url': logo_url,  # Keep logo URL for later processing
                'occurrences': {
                    stream_id: {
                        'category': category,
                        'movie_data': movie_data,
                    }
                },
            }

        except Exception as e:
            logger.error(f"Error preparing movie {movie_data.get('name', 'Unknown')}: {str(e)}")

    if skipped_invalid:
        logger.warning(
            "Skipped %d movie rows with a blank provider ID or name "
            "(sample IDs: %s)",
            len(skipped_invalid),
            skipped_invalid[:10],
        )

    _coalesce_batch_title_year_entries(movie_keys)

    # Collect all logo URLs and create logos in batch
    logo_urls = set()
    logo_url_to_name = {}  # Map logo URLs to movie names
    for data in movie_keys.values():
        logo_url = data.get('logo_url')
        if logo_url and len(logo_url) <= 500:  # Ignore overly long URLs (likely embedded image data)
            logo_urls.add(logo_url)
            # Map this logo URL to the movie name (use first occurrence if multiple movies share same logo)
            if logo_url not in logo_url_to_name:
                movie_name = data['props'].get('name', 'Unknown Movie')
                logo_url_to_name[logo_url] = movie_name

    # Get existing logos
    existing_logos = {
        logo.url: logo for logo in VODLogo.objects.filter(url__in=logo_urls)
    } if logo_urls else {}

    # Create missing logos
    logos_to_create = []
    for logo_url in logo_urls:
        if logo_url not in existing_logos:
            movie_name = logo_url_to_name.get(logo_url, 'Unknown Movie')
            logos_to_create.append(VODLogo(url=logo_url, name=movie_name))

    if logos_to_create:
        try:
            VODLogo.objects.bulk_create(logos_to_create, ignore_conflicts=True)
            # Refresh existing_logos with newly created ones
            new_logo_urls = [logo.url for logo in logos_to_create]
            newly_created = {
                logo.url: logo for logo in VODLogo.objects.filter(url__in=new_logo_urls)
            }
            existing_logos.update(newly_created)
            logger.info(f"Created {len(newly_created)} new VOD logos for movies")
        except Exception as e:
            logger.warning(f"Failed to create VOD logos: {e}")

    # Get existing movies from the provider identity keys.
    existing_movies = {}

    # Query by TMDB IDs
    tmdb_keys = [k for k in movie_keys.keys() if k.startswith('tmdb_')]
    tmdb_ids = [k.replace('tmdb_', '') for k in tmdb_keys]
    if tmdb_ids:
        for movie in Movie.objects.filter(
            Q(tmdb_id__in=tmdb_ids) | Q(tmdb_match_id__in=tmdb_ids)
        ).order_by("id"):
            for tmdb_id in {movie.tmdb_id, movie.tmdb_match_id}:
                if tmdb_id in tmdb_ids:
                    existing_movies.setdefault(f"tmdb_{tmdb_id}", movie)

    # Query by IMDB IDs
    imdb_keys = [k for k in movie_keys.keys() if k.startswith('imdb_')]
    imdb_ids = [k.replace('imdb_', '') for k in imdb_keys]
    if imdb_ids:
        for movie in Movie.objects.filter(imdb_id__in=imdb_ids):
            existing_movies[f"imdb_{movie.imdb_id}"] = movie

    # If an external ID did not resolve, or the provider supplied no ID, use
    # one unambiguous exact cleaned-title/year match. Never match by name alone.
    title_matches = lookup_by_clean_title_year(
        Movie,
        [
            (data['props'].get('clean_title'), data['props'].get('year'))
            for data in movie_keys.values()
        ],
    )
    for movie_key, data in movie_keys.items():
        if movie_key in existing_movies:
            continue
        props = data['props']
        candidate = title_matches.get(
            (_title_match_key(props.get('clean_title')), props.get('year'))
        )
        if candidate and _compatible_title_year_match(
            candidate,
            tmdb_id=props.get('tmdb_id'),
            imdb_id=props.get('imdb_id'),
        ):
            existing_movies[movie_key] = candidate

    # Get existing relations
    stream_ids = [
        stream_id
        for data in movie_keys.values()
        for stream_id in data['occurrences']
    ]
    existing_relations = {
        rel.stream_id: rel for rel in M3UMovieRelation.objects.filter(
            m3u_account=account,
            stream_id__in=stream_ids
        ).select_related('movie')
    }
    for movie_key, data in movie_keys.items():
        if movie_key in existing_movies:
            continue
        relation_targets = {
            existing_relations[stream_id].movie_id
            for stream_id in data['occurrences']
            if stream_id in existing_relations
        }
        if len(relation_targets) == 1:
            existing_movies[movie_key] = next(
                existing_relations[stream_id].movie
                for stream_id in data['occurrences']
                if stream_id in existing_relations
            )
    movie_override_ids = {
        rel.tmdb_override_id for rel in existing_relations.values()
        if rel.tmdb_override_id
    }
    movie_override_targets = {
        str(movie.tmdb_match_id or movie.tmdb_id): movie
        for movie in Movie.objects.filter(
            Q(tmdb_match_id__in=movie_override_ids)
            | Q(tmdb_id__in=movie_override_ids)
        )
    }

    # Process each movie
    for movie_key, data in movie_keys.items():
        movie_props = data['props']
        logo_url = data.get('logo_url')

        if movie_key in existing_movies:
            # Update existing movie
            movie = existing_movies[movie_key]
            updated = False
            canonical_uses_tmdb = bool(
                movie.tmdb_match_id or movie.tmdb_status == "matched"
            )

            for field, value in movie_props.items():
                if canonical_uses_tmdb:
                    continue
                if field == 'custom_properties':
                    # Merge custom_properties: fill director/actors/release_date
                    # only when empty; apply other non-blank list keys.
                    existing_cp = movie.custom_properties or {}
                    incoming_cp = value or {}
                    merged = dict(existing_cp)
                    for k, v in incoming_cp.items():
                        if k in ('director', 'actors', 'release_date'):
                            if not existing_cp.get(k):
                                merged[k] = v
                        elif not is_blank_vod_value(v):
                            merged[k] = v
                    if merged != existing_cp:
                        movie.custom_properties = merged
                        updated = True
                elif should_apply_provider_list_field(getattr(movie, field), value):
                    setattr(movie, field, value)
                    updated = True

            # Handle logo assignment for existing movies
            logo_updated = False
            if not canonical_uses_tmdb:
                if logo_url and len(logo_url) <= 500:
                    if logo_url in existing_logos:
                        new_logo = existing_logos[logo_url]
                        if movie.logo_id != new_logo.id:
                            movie._logo_to_update = new_logo
                            logo_updated = True
                    elif movie.logo_id:
                        logger.warning(f"Logo URL provided but logo not found in database for movie '{movie.name}', clearing logo reference")
                        movie._logo_to_update = None
                        logo_updated = True
                elif (not logo_url or len(logo_url) > 500) and movie.logo_id:
                    # Clear logo if no logo URL provided or URL is too long
                    movie._logo_to_update = None
                    logo_updated = True

            if updated or logo_updated:
                movies_to_update.append(movie)
        else:
            # Create new movie
            movie = Movie(**movie_props)

            # Assign logo if available
            if logo_url and len(logo_url) <= 500 and logo_url in existing_logos:
                movie.logo = existing_logos[logo_url]

            movies_to_create.append(movie)

        for stream_id, occ in data['occurrences'].items():
            category = occ['category']
            movie_data = occ['movie_data']
            category_relation = relations.get(category.id)
            declared_metadata = _import_source_metadata(
                category_relation,
                movie_data.get('container_extension', 'mp4'),
            )

            if stream_id in existing_relations:
                # Update existing relation
                relation = existing_relations[stream_id]
                relation.movie = (
                    movie_override_targets.get(relation.tmdb_override_id)
                    if relation.tmdb_override_id
                    else movie
                ) or movie
                relation.category = category
                relation.container_extension = movie_data.get('container_extension', 'mp4')
                # Merge so list sync updates basic_data without dropping detail
                # payloads or detailed_fetched / related flags.
                existing_rel_cp = relation.custom_properties or {}
                relation.custom_properties = {
                    **existing_rel_cp,
                    'basic_data': movie_data,
                }
                relation.declared_metadata = declared_metadata
                relation.last_seen = scan_start_time or timezone.now()  # Mark as seen during this scan
                relations_to_update.append(relation)
            else:
                # Create new relation
                relation = M3UMovieRelation(
                    m3u_account=account,
                    movie=movie,
                    category=category,
                    stream_id=stream_id,
                    container_extension=movie_data.get('container_extension', 'mp4'),
                    custom_properties={
                        'basic_data': movie_data,
                        'detailed_fetched': False
                    },
                    declared_metadata=declared_metadata,
                    last_seen=scan_start_time or timezone.now()  # Mark as seen during this scan
                )
                relations_to_create.append(relation)

    # Execute batch operations
    logger.info(f"Executing batch operations: {len(movies_to_create)} movies to create, {len(movies_to_update)} to update")

    try:
        with transaction.atomic():
            # First, create new movies and get their IDs
            created_movies = {}
            if movies_to_create:
                # Bulk query to check which movies already exist
                tmdb_ids = [m.tmdb_id for m in movies_to_create if m.tmdb_id]
                imdb_ids = [m.imdb_id for m in movies_to_create if m.imdb_id]
                title_year_pairs = [
                    (m.clean_title, m.year)
                    for m in movies_to_create
                    if m.year is not None
                ]

                existing_by_tmdb = {}
                if tmdb_ids:
                    for existing_movie in Movie.objects.filter(
                        Q(tmdb_id__in=tmdb_ids)
                        | Q(tmdb_match_id__in=tmdb_ids)
                    ).order_by("id"):
                        for tmdb_id in {
                            existing_movie.tmdb_id,
                            existing_movie.tmdb_match_id,
                        }:
                            if tmdb_id in tmdb_ids:
                                existing_by_tmdb.setdefault(
                                    tmdb_id,
                                    existing_movie,
                                )
                existing_by_imdb = {m.imdb_id: m for m in Movie.objects.filter(imdb_id__in=imdb_ids)} if imdb_ids else {}

                existing_by_title_year = lookup_by_clean_title_year(
                    Movie, title_year_pairs
                )

                # Check each movie against the bulk query results
                movies_actually_created = []
                for movie in movies_to_create:
                    existing = None
                    if movie.tmdb_id and movie.tmdb_id in existing_by_tmdb:
                        existing = existing_by_tmdb[movie.tmdb_id]
                    elif movie.imdb_id and movie.imdb_id in existing_by_imdb:
                        existing = existing_by_imdb[movie.imdb_id]
                    if existing is None and movie.year is not None:
                        candidate = existing_by_title_year.get(
                            (_title_match_key(movie.clean_title), movie.year)
                        )
                        if candidate and _compatible_title_year_match(
                            candidate,
                            tmdb_id=movie.tmdb_id,
                            imdb_id=movie.imdb_id,
                        ):
                            existing = candidate

                    if existing:
                        created_movies[id(movie)] = existing
                    else:
                        movies_actually_created.append(movie)
                        created_movies[id(movie)] = movie

                # Bulk create only movies that don't exist
                if movies_actually_created:
                    Movie.objects.bulk_create(movies_actually_created)

            # Update existing movies
            if movies_to_update:
                # First, update all fields except logo to avoid unsaved related object issues
                Movie.objects.bulk_update(movies_to_update, [
                    'clean_title', 'description', 'rating', 'genre', 'year', 'tmdb_id', 'imdb_id',
                    'duration_secs', 'is_adult', 'custom_properties'
                ])

                # Handle logo updates separately to avoid bulk_update issues
                for movie in movies_to_update:
                    if hasattr(movie, '_logo_to_update'):
                        movie.logo = movie._logo_to_update
                        movie.save(update_fields=['logo'])

            # Update relations to reference the correct movie objects (with PKs)
            for relation in relations_to_create:
                if id(relation.movie) in created_movies:
                    relation.movie = created_movies[id(relation.movie)]

            for relation in relations_to_update:
                if id(relation.movie) in created_movies:
                    relation.movie = created_movies[id(relation.movie)]

            # All movies now have PKs, safe to bulk create/update relations
            if relations_to_create:
                M3UMovieRelation.objects.bulk_create(relations_to_create, ignore_conflicts=True)

            if relations_to_update:
                M3UMovieRelation.objects.bulk_update(relations_to_update, [
                    'movie', 'category', 'container_extension', 'custom_properties',
                    'declared_metadata', 'last_seen'
                ])

        logger.info("Movie batch processing completed successfully!")
        return f"Movie batch processed: {len(movies_to_create)} created, {len(movies_to_update)} updated"

    except Exception:
        logger.exception("Movie batch processing failed")
        raise


@shared_task
def process_series_batch(account, batch, categories, relations, scan_start_time=None):
    """Process a batch of series using simple bulk operations like M3U processing"""
    logger.info(f"Processing series batch of {len(batch)} series for account {account.name}")

    series_to_create = []
    series_to_update = []
    relations_to_create = []
    relations_to_update = []
    series_keys = {}  # For deduplication like M3U stream_hashes
    skipped_invalid = []
    from core.models import CoreSettings

    title_rules = CoreSettings.get_tmdb_title_rules()
    year_rules = CoreSettings.get_tmdb_year_rules()

    # Process each series in the batch
    for series_data in batch:
        identity = _provider_vod_identity(series_data, 'series_id')
        if identity is None:
            skipped_invalid.append(
                series_data.get('series_id') if isinstance(series_data, dict) else None
            )
            continue

        try:
            series_id, name = identity

            # Get category with proper error handling
            category = None

            provider_cat_id = _provider_category_id(series_data)
            series_data['_provider_category_id'] = provider_cat_id
            series_data['_category_id'] = None

            if provider_cat_id in categories:
                category = categories[provider_cat_id]
                series_data['_category_id'] = category.id
                logger.debug(f"Found category {category.name} (ID: {category.id}) for series {name}")
                relation = relations.get(category.id, None)

                if relation and not relation.enabled:
                    logger.debug("Skipping disabled category")
                    continue
            elif provider_cat_id is None:
                # Assign only genuinely uncategorized rows. Unknown non-empty
                # IDs are omitted categories, not Uncategorized content.
                logger.debug(f"No category ID provided for series {name}, assigning to 'Uncategorized'")
                category = categories.get('__uncategorized__')
                if category:
                    series_data['_category_id'] = category.id
                    # Check if uncategorized is disabled
                    relation = relations.get(category.id, None)
                    if relation and not relation.enabled:
                        logger.debug("Skipping disabled 'Uncategorized' category")
                        continue
            else:
                logger.debug(
                    "Skipping series %s from unknown or ignored provider category %s",
                    name,
                    provider_cat_id,
                )
                continue

            # Extract metadata
            year = extract_year_from_data(
                series_data, 'name', year_rules=year_rules
            )

            tmdb_id = series_data.get('tmdb') or series_data.get('tmdb_id')
            imdb_id = series_data.get('imdb') or series_data.get('imdb_id')

            # Clean empty string IDs and zero values (some providers use 0 to indicate no ID)
            if tmdb_id == '' or tmdb_id == 0 or tmdb_id == '0':
                tmdb_id = None
            if imdb_id == '' or imdb_id == 0 or imdb_id == '0':
                imdb_id = None

            category_relation = relations.get(category.id) if category else None
            from .tmdb import clean_lookup_title

            clean_title = clean_lookup_title(
                name,
                year=year,
                rules=title_rules,
                year_rules=year_rules,
                group_rule=_category_title_cleanup(category_relation),
            ) or name

            # Prefer external IDs, then an exact cleaned-title/year identity.
            if tmdb_id:
                series_key = f"tmdb_{tmdb_id}"
            elif imdb_id:
                series_key = f"imdb_{imdb_id}"
            elif year is not None:
                series_key = f"title_{_title_match_key(clean_title)}_{year}"
            else:
                series_key = f"source_{series_id}"

            # Keep one canonical Series row while retaining every concrete
            # upstream series/category relation in the batch.
            if series_key in series_keys:
                series_keys[series_key]['occurrences'].setdefault(series_id, {
                    'category': category,
                    'series_data': series_data,
                })
                incoming_props, incoming_logo = build_series_list_props(
                    series_data, name, clean_title, year, tmdb_id, imdb_id,
                )
                merge_blank_vod_list_props(series_keys[series_key]['props'], incoming_props)
                if not series_keys[series_key].get('logo_url') and incoming_logo:
                    series_keys[series_key]['logo_url'] = incoming_logo
                continue

            series_props, logo_url = build_series_list_props(
                series_data, name, clean_title, year, tmdb_id, imdb_id,
            )

            series_keys[series_key] = {
                'props': series_props,
                'logo_url': logo_url,  # Keep logo URL for later processing
                'occurrences': {
                    series_id: {
                        'category': category,
                        'series_data': series_data,
                    }
                },
            }

        except Exception as e:
            logger.error(f"Error preparing series {series_data.get('name', 'Unknown')}: {str(e)}")

    if skipped_invalid:
        logger.warning(
            "Skipped %d series rows with a blank provider ID or name "
            "(sample IDs: %s)",
            len(skipped_invalid),
            skipped_invalid[:10],
        )

    _coalesce_batch_title_year_entries(series_keys)

    # Collect all logo URLs and create logos in batch
    logo_urls = set()
    logo_url_to_name = {}  # Map logo URLs to series names
    for data in series_keys.values():
        logo_url = data.get('logo_url')
        if logo_url and len(logo_url) <= 500:  # Ignore overly long URLs (likely embedded image data)
            logo_urls.add(logo_url)
            # Map this logo URL to the series name (use first occurrence if multiple series share same logo)
            if logo_url not in logo_url_to_name:
                series_name = data['props'].get('name', 'Unknown Series')
                logo_url_to_name[logo_url] = series_name

    # Get existing logos
    existing_logos = {
        logo.url: logo for logo in VODLogo.objects.filter(url__in=logo_urls)
    } if logo_urls else {}

    # Create missing logos
    logos_to_create = []
    for logo_url in logo_urls:
        if logo_url not in existing_logos:
            series_name = logo_url_to_name.get(logo_url, 'Unknown Series')
            logos_to_create.append(VODLogo(url=logo_url, name=series_name))

    if logos_to_create:
        try:
            VODLogo.objects.bulk_create(logos_to_create, ignore_conflicts=True)
            # Refresh existing_logos with newly created ones
            new_logo_urls = [logo.url for logo in logos_to_create]
            newly_created = {
                logo.url: logo for logo in VODLogo.objects.filter(url__in=new_logo_urls)
            }
            existing_logos.update(newly_created)
            logger.info(f"Created {len(newly_created)} new VOD logos for series")
        except Exception as e:
            logger.warning(f"Failed to create VOD logos: {e}")

    # Get existing series from the provider identity keys.
    existing_series = {}

    # Query by TMDB IDs
    tmdb_keys = [k for k in series_keys.keys() if k.startswith('tmdb_')]
    tmdb_ids = [k.replace('tmdb_', '') for k in tmdb_keys]
    if tmdb_ids:
        for series in Series.objects.filter(
            Q(tmdb_id__in=tmdb_ids) | Q(tmdb_match_id__in=tmdb_ids)
        ).order_by("id"):
            for tmdb_id in {series.tmdb_id, series.tmdb_match_id}:
                if tmdb_id in tmdb_ids:
                    existing_series.setdefault(f"tmdb_{tmdb_id}", series)

    # Query by IMDB IDs
    imdb_keys = [k for k in series_keys.keys() if k.startswith('imdb_')]
    imdb_ids = [k.replace('imdb_', '') for k in imdb_keys]
    if imdb_ids:
        for series in Series.objects.filter(imdb_id__in=imdb_ids):
            existing_series[f"imdb_{series.imdb_id}"] = series

    title_matches = lookup_by_clean_title_year(
        Series,
        [
            (data['props'].get('clean_title'), data['props'].get('year'))
            for data in series_keys.values()
        ],
    )
    for series_key, data in series_keys.items():
        if series_key in existing_series:
            continue
        props = data['props']
        candidate = title_matches.get(
            (_title_match_key(props.get('clean_title')), props.get('year'))
        )
        if candidate and _compatible_title_year_match(
            candidate,
            tmdb_id=props.get('tmdb_id'),
            imdb_id=props.get('imdb_id'),
        ):
            existing_series[series_key] = candidate

    # Get existing relations
    series_ids = [
        series_id
        for data in series_keys.values()
        for series_id in data['occurrences']
    ]
    existing_relations = {
        rel.external_series_id: rel for rel in M3USeriesRelation.objects.filter(
            m3u_account=account,
            external_series_id__in=series_ids
        ).select_related('series')
    }
    for series_key, data in series_keys.items():
        if series_key in existing_series:
            continue
        relation_targets = {
            existing_relations[series_id].series_id
            for series_id in data['occurrences']
            if series_id in existing_relations
        }
        if len(relation_targets) == 1:
            existing_series[series_key] = next(
                existing_relations[series_id].series
                for series_id in data['occurrences']
                if series_id in existing_relations
            )
    series_override_ids = {
        rel.tmdb_override_id for rel in existing_relations.values()
        if rel.tmdb_override_id
    }
    series_override_targets = {
        str(series.tmdb_match_id or series.tmdb_id): series
        for series in Series.objects.filter(
            Q(tmdb_match_id__in=series_override_ids)
            | Q(tmdb_id__in=series_override_ids)
        )
    }

    # Process each series
    for series_key, data in series_keys.items():
        series_props = data['props']
        logo_url = data.get('logo_url')

        if series_key in existing_series:
            # Update existing series
            series = existing_series[series_key]
            updated = False
            canonical_uses_tmdb = bool(
                series.tmdb_match_id or series.tmdb_status == "matched"
            )

            for field, value in series_props.items():
                if canonical_uses_tmdb:
                    continue
                if field == 'custom_properties':
                    existing_cp = series.custom_properties or {}
                    incoming_cp = value or {}
                    merged = dict(existing_cp)
                    for k, v in incoming_cp.items():
                        if not is_blank_vod_value(v):
                            merged[k] = v
                    if merged != existing_cp:
                        series.custom_properties = merged
                        updated = True
                elif should_apply_provider_list_field(getattr(series, field), value):
                    setattr(series, field, value)
                    updated = True

            # Handle logo assignment for existing series
            logo_updated = False
            if not canonical_uses_tmdb:
                if logo_url and len(logo_url) <= 500:
                    if logo_url in existing_logos:
                        new_logo = existing_logos[logo_url]
                        if series.logo_id != new_logo.id:
                            series._logo_to_update = new_logo
                            logo_updated = True
                    elif series.logo_id:
                        # Logo URL exists but logo creation failed or logo not found
                        # Clear the orphaned logo reference
                        logger.warning(f"Logo URL provided but logo not found in database for series '{series.name}', clearing logo reference")
                        series._logo_to_update = None
                        logo_updated = True
                elif (not logo_url or len(logo_url) > 500) and series.logo_id:
                    # Clear logo if no logo URL provided or URL is too long
                    series._logo_to_update = None
                    logo_updated = True

            if updated or logo_updated:
                series_to_update.append(series)
        else:
            # Create new series
            series = Series(**series_props)

            # Assign logo if available
            if logo_url and len(logo_url) <= 500 and logo_url in existing_logos:
                series.logo = existing_logos[logo_url]

            series_to_create.append(series)

        for series_id, occ in data['occurrences'].items():
            category = occ['category']
            series_data = occ['series_data']
            category_relation = relations.get(category.id)
            declared_metadata = _import_source_metadata(category_relation)

            if series_id in existing_relations:
                # Update existing relation
                relation = existing_relations[series_id]
                relation.series = (
                    series_override_targets.get(relation.tmdb_override_id)
                    if relation.tmdb_override_id
                    else series
                ) or series
                relation.category = category
                # Merge so list sync updates basic_data without dropping detail
                # payloads or detailed_fetched / episodes_fetched flags.
                existing_rel_cp = relation.custom_properties or {}
                relation.custom_properties = {
                    **existing_rel_cp,
                    'basic_data': series_data,
                }
                relation.declared_metadata = declared_metadata
                relation.last_seen = scan_start_time or timezone.now()  # Mark as seen during this scan
                relations_to_update.append(relation)
            else:
                # Create new relation
                relation = M3USeriesRelation(
                    m3u_account=account,
                    series=series,
                    category=category,
                    external_series_id=series_id,
                    custom_properties={
                        'basic_data': series_data,
                        'detailed_fetched': False,
                        'episodes_fetched': False,
                    },
                    declared_metadata=declared_metadata,
                    last_seen=scan_start_time or timezone.now()  # Mark as seen during this scan
                )
                relations_to_create.append(relation)

    # Execute batch operations
    logger.info(f"Executing batch operations: {len(series_to_create)} series to create, {len(series_to_update)} to update")

    try:
        with transaction.atomic():
            # First, create new series and get their IDs
            created_series = {}
            if series_to_create:
                # Bulk query to check which series already exist
                tmdb_ids = [s.tmdb_id for s in series_to_create if s.tmdb_id]
                imdb_ids = [s.imdb_id for s in series_to_create if s.imdb_id]
                title_year_pairs = [
                    (s.clean_title, s.year)
                    for s in series_to_create
                    if s.year is not None
                ]

                existing_by_tmdb = {}
                if tmdb_ids:
                    for existing_series_row in Series.objects.filter(
                        Q(tmdb_id__in=tmdb_ids)
                        | Q(tmdb_match_id__in=tmdb_ids)
                    ).order_by("id"):
                        for tmdb_id in {
                            existing_series_row.tmdb_id,
                            existing_series_row.tmdb_match_id,
                        }:
                            if tmdb_id in tmdb_ids:
                                existing_by_tmdb.setdefault(
                                    tmdb_id,
                                    existing_series_row,
                                )
                existing_by_imdb = {s.imdb_id: s for s in Series.objects.filter(imdb_id__in=imdb_ids)} if imdb_ids else {}

                existing_by_title_year = lookup_by_clean_title_year(
                    Series, title_year_pairs
                )

                # Check each series against the bulk query results
                series_actually_created = []
                for series in series_to_create:
                    existing = None
                    if series.tmdb_id and series.tmdb_id in existing_by_tmdb:
                        existing = existing_by_tmdb[series.tmdb_id]
                    elif series.imdb_id and series.imdb_id in existing_by_imdb:
                        existing = existing_by_imdb[series.imdb_id]
                    if existing is None and series.year is not None:
                        candidate = existing_by_title_year.get(
                            (_title_match_key(series.clean_title), series.year)
                        )
                        if candidate and _compatible_title_year_match(
                            candidate,
                            tmdb_id=series.tmdb_id,
                            imdb_id=series.imdb_id,
                        ):
                            existing = candidate

                    if existing:
                        created_series[id(series)] = existing
                    else:
                        series_actually_created.append(series)
                        created_series[id(series)] = series

                # Bulk create only series that don't exist
                if series_actually_created:
                    Series.objects.bulk_create(series_actually_created)

            # Update existing series
            if series_to_update:
                # First, update all fields except logo to avoid unsaved related object issues
                Series.objects.bulk_update(series_to_update, [
                    'clean_title', 'description', 'rating', 'genre', 'year', 'tmdb_id', 'imdb_id',
                    'custom_properties'
                ])

                # Handle logo updates separately to avoid bulk_update issues
                for series in series_to_update:
                    if hasattr(series, '_logo_to_update'):
                        series.logo = series._logo_to_update
                        series.save(update_fields=['logo'])

            # Update relations to reference the correct series objects (with PKs)
            for relation in relations_to_create:
                if id(relation.series) in created_series:
                    relation.series = created_series[id(relation.series)]

            for relation in relations_to_update:
                if id(relation.series) in created_series:
                    relation.series = created_series[id(relation.series)]

            # All series now have PKs, safe to bulk create/update relations
            if relations_to_create:
                M3USeriesRelation.objects.bulk_create(relations_to_create, ignore_conflicts=True)

            if relations_to_update:
                M3USeriesRelation.objects.bulk_update(relations_to_update, [
                    'series', 'category', 'custom_properties',
                    'declared_metadata', 'last_seen'
                ])

        logger.info("Series batch processing completed successfully!")
        return f"Series batch processed: {len(series_to_create)} created, {len(series_to_update)} updated"

    except Exception:
        logger.exception("Series batch processing failed")
        raise


# Helper functions for year and date extraction

def extract_duration_from_data(movie_data):
    """Extract duration in seconds from movie data"""
    duration_secs = None

    # Try to extract duration from various possible fields
    if movie_data.get('duration_secs'):
        duration_secs = int(movie_data.get('duration_secs'))
    elif movie_data.get('duration'):
        # Handle duration that might be in different formats
        duration_str = str(movie_data.get('duration'))
        if duration_str.isdigit():
            duration_secs = int(duration_str) * 60  # Assume minutes if just a number
        else:
            # Try to parse time format like "01:30:00"
            try:
                time_parts = duration_str.split(':')
                if len(time_parts) == 3:
                    hours, minutes, seconds = map(int, time_parts)
                    duration_secs = (hours * 3600) + (minutes * 60) + seconds
                elif len(time_parts) == 2:
                    minutes, seconds = map(int, time_parts)
                    duration_secs = minutes * 60 + seconds
            except (ValueError, AttributeError):
                pass

    return duration_secs


def normalize_rating(rating_value):
    """Normalize rating value by converting commas to decimals and validating as float"""
    if not rating_value:
        return None

    try:
        # Convert to string for processing
        rating_str = str(rating_value).strip()

        if not rating_str or rating_str == '':
            return None

        # Replace comma with decimal point (European format)
        rating_str = rating_str.replace(',', '.')

        # Try to convert to float
        rating_float = float(rating_str)

        # Return as string to maintain compatibility with existing code
        # but ensure it's a valid numeric format
        return str(rating_float)
    except (ValueError, TypeError, AttributeError):
        # If conversion fails, discard the rating
        logger.debug(f"Invalid rating value discarded: {rating_value}")
        return None


def extract_year(date_string):
    """Extract year from date string"""
    if not date_string:
        return None
    try:
        return int(date_string.split('-')[0])
    except (ValueError, IndexError):
        return None


def extract_year_from_title(title, year_rules=None):
    """Extract a year with the shared configurable title parser."""
    from .tmdb import extract_year_from_title as extract_configured_year

    return extract_configured_year(title, rules=year_rules)


def extract_year_from_data(data, title_key='name', *, year_rules=None):
    """Extract year from various data sources with fallback options"""
    try:
        # First try the year field
        year = data.get('year')
        if year and str(year).strip() and str(year).strip() != '':
            try:
                year_int = int(year)
                if 1900 <= year_int <= datetime.now().year + 5:
                    return year_int
            except (ValueError, TypeError):
                pass

        # Try releaseDate or release_date fields
        for date_field in ['releaseDate', 'release_date']:
            date_value = data.get(date_field)
            if date_value and isinstance(date_value, str) and date_value.strip():
                # Extract year from date format like "2011-09-19"
                try:
                    year_str = date_value.split('-')[0].strip()
                    if year_str:
                        year = int(year_str)
                        if 1900 <= year <= datetime.now().year + 5:
                            return year
                except (ValueError, IndexError):
                    continue

        # Finally try extracting from title
        title = data.get(title_key, '')
        if title and title.strip():
            return extract_year_from_title(title, year_rules=year_rules)

    except Exception:
        # Don't fail processing if year extraction fails
        pass

    return None


def extract_date_from_data(data):
    """Extract date from various data sources with fallback options"""
    try:
        for date_field in ['air_date', 'releasedate', 'release_date']:
            date_value = data.get(date_field)
            if date_value and isinstance(date_value, str) and date_value.strip():
                parsed = parse_date(date_value)
                if parsed:
                    return parsed
    except Exception:
        # Don't fail processing if date extraction fails
        pass
    return None


def parse_date(date_string):
    """Parse date string into a datetime object"""
    if not date_string:
        return None
    try:
        # Try to parse ISO format first
        return datetime.fromisoformat(date_string)
    except ValueError:
        # Fallback to parsing with strptime for common formats
        try:
            return datetime.strptime(date_string, '%Y-%m-%d')
        except ValueError:
            return None  # Return None if parsing fails


# Episode processing and other advanced features

def refresh_series_episodes(account, series, external_series_id, episodes_data=None):
    """Refresh episodes for a series - only called on-demand"""
    try:
        series_relation = M3USeriesRelation.objects.filter(
            m3u_account=account,
            external_series_id=external_series_id,
        ).first()
        detailed_series_info = None
        if not episodes_data:
            # Fetch detailed series info including episodes
            with XtreamCodesClient(
                account.server_url,
                account.username,
                account.password,
                account.get_user_agent_string()
            ) as client:
                series_info = client.get_series_info(external_series_id)
                if series_info:
                    # Update series with detailed info
                    info = series_info.get('info', {})
                    if isinstance(info, dict) and info:
                        detailed_series_info = clean_custom_properties(info)
                    if (
                        isinstance(info, dict)
                        and info
                        and not (
                            series_relation and series_relation.tmdb_override_id
                        )
                    ):
                        # Only update fields if new value is non-empty and either no existing value or existing value is empty
                        updated = False
                        if should_update_field(series.description, info.get('plot')):
                            series.description = extract_string_from_array_or_string(info.get('plot'))
                            updated = True
                        normalized_rating = normalize_rating(info.get('rating'))
                        if normalized_rating and (not series.rating or not str(series.rating).strip()):
                            series.rating = normalized_rating
                            updated = True
                        if should_update_field(series.genre, info.get('genre')):
                            series.genre = extract_string_from_array_or_string(info.get('genre'))
                            updated = True

                        year = extract_year_from_data(info)
                        if year and not series.year:
                            series.year = year
                            updated = True

                        if updated:
                            series.save()

                    episodes_data = series_info.get('episodes', {})
                else:
                    episodes_data = {}

        # Process all episodes in batch
        batch_process_episodes(account, series, episodes_data, series_relation=series_relation)

        if series_relation:
            custom_props = series_relation.custom_properties or {}
            if detailed_series_info:
                custom_props['detailed_info'] = detailed_series_info
            custom_props['episodes_fetched'] = True
            custom_props['detailed_fetched'] = True
            series_relation.custom_properties = custom_props
            series_relation.last_episode_refresh = timezone.now()
            # Provider details and episodes are lazy inspector data. They must
            # not alter a prepared output profile merely because it was opened.
            series_relation._skip_vod_profile_invalidation = True
            series_relation.save(
                update_fields=["custom_properties", "last_episode_refresh"]
            )
            from .metadata import sync_relation_declared_metadata

            sync_relation_declared_metadata(
                series_relation,
                notify_profile_change=False,
            )
            from .provider_metadata import reconcile_series_provider_metadata

            if reconcile_series_provider_metadata([series_relation.series_id]):
                from .catalog_cache import bump_catalog_generation

                bump_catalog_generation(invalidate_selections=False)

    except Exception as e:
        logger.error(f"Error refreshing episodes for series {series.name}: {str(e)}")


def batch_process_episodes(account, series, episodes_data, scan_start_time=None, series_relation=None):
    """Process episodes in batches for better performance.

    Note: Multiple streams can represent the same episode (e.g., different languages
    or qualities). Each stream has a unique stream_id, but they share the same
    season/episode number. We create one Episode record per (series, season, episode)
    and multiple M3UEpisodeRelation records pointing to it.

    series_relation, when provided, is stored as a FK on each M3UEpisodeRelation so
    that CASCADE correctly removes episode relations when their parent series relation
    is deleted, and so that stale-stream cleanup is scoped precisely to relations that
    came from this specific provider query.
    """
    if not episodes_data:
        return

    # XC panels encode seasons as a PHP array keyed by season number. When keys are
    # contiguous from 0 (common with Season 0 specials), json_encode emits a JSON
    # array instead of an object. Accept both shapes and use the key/index as the
    # season number.
    if isinstance(episodes_data, dict):
        season_items = episodes_data.items()
    elif isinstance(episodes_data, list):
        season_items = enumerate(episodes_data)
    else:
        logger.warning(
            f"Unexpected episodes_data type {type(episodes_data).__name__} "
            f"for series {series.name}; skipping"
        )
        return

    # Flatten episodes data
    all_episodes_data = []
    for season_num, season_episodes in season_items:
        if not isinstance(season_episodes, list):
            continue
        for episode_data in season_episodes:
            if not isinstance(episode_data, dict):
                continue
            episode_data['_season_number'] = int(season_num)
            all_episodes_data.append(episode_data)

    if not all_episodes_data:
        return

    logger.info(f"Batch processing {len(all_episodes_data)} episodes for series {series.name}")

    # Extract episode identifiers
    # Note: episode_keys may have duplicates when multiple streams represent same episode
    episode_keys = set()  # Use set to track unique episode keys
    episode_ids = []
    for episode_data in all_episodes_data:
        season_num = episode_data['_season_number']
        episode_num = episode_data.get('episode_num', 0)
        episode_keys.add((series.id, season_num, episode_num))
        episode_ids.append(str(episode_data.get('id')))

    # Pre-fetch existing episodes
    existing_episodes = {}
    for episode in Episode.objects.filter(series=series):
        key = (episode.series_id, episode.season_number, episode.episode_number)
        existing_episodes[key] = episode

    # Pre-fetch existing episode relations
    existing_relations = {
        rel.stream_id: rel for rel in M3UEpisodeRelation.objects.filter(
            m3u_account=account,
            stream_id__in=episode_ids
        ).select_related('episode')
    }

    # Prepare batch operations
    episodes_to_create = []
    episodes_to_update = []
    relations_to_create = []
    relations_to_update = []

    category_relation = None
    if series_relation and series_relation.category_id:
        category_relation = M3UVODCategoryRelation.objects.filter(
            m3u_account=account,
            category_id=series_relation.category_id,
        ).only("metadata_defaults").first()

    # Track episodes we're creating in this batch to avoid duplicates
    # Key: (series_id, season_number, episode_number) -> Episode object
    episodes_pending_creation = {}

    for episode_data in all_episodes_data:
        try:
            episode_id = str(episode_data.get('id'))
            episode_name = episode_data.get('title', 'Unknown Episode')
            # Ensure season and episode numbers are integers (API may return strings)
            try:
                season_number = int(episode_data['_season_number'])
            except (ValueError, TypeError) as e:
                logger.warning(f"Invalid season_number '{episode_data.get('_season_number')}' for episode '{episode_name}': {e}")
                season_number = 0
            try:
                episode_number = int(episode_data.get('episode_num', 0))
            except (ValueError, TypeError) as e:
                logger.warning(f"Invalid episode_num '{episode_data.get('episode_num')}' for episode '{episode_name}': {e}")
                episode_number = 0
            info = episode_data.get('info', {})
            container_extension = episode_data.get('container_extension', 'mp4')
            declared_metadata = _import_source_metadata(
                category_relation,
                container_extension,
            )

            # Extract episode metadata
            description = info.get('plot') or info.get('overview', '') if info else ''
            rating = normalize_rating(info.get('rating')) if info else None
            air_date = extract_date_from_data(info) if info else None
            duration_secs = info.get('duration_secs') if info else None
            tmdb_id = info.get('tmdb_id') if info else None
            imdb_id = info.get('imdb_id') if info else None

            # Prepare custom properties
            custom_props = {}
            if info:
                if info.get('crew'):
                    custom_props['crew'] = info.get('crew')
                if info.get('movie_image'):
                    movie_image = extract_string_from_array_or_string(info.get('movie_image'))
                    if movie_image:
                        custom_props['movie_image'] = movie_image
                backdrop = extract_string_from_array_or_string(info.get('backdrop_path'))
                if backdrop:
                    custom_props['backdrop_path'] = [backdrop]

            # Find existing episode - check DB first, then pending creations
            episode_key = (series.id, season_number, episode_number)
            episode = existing_episodes.get(episode_key)

            # Check if we already have this episode pending creation (multiple streams for same episode)
            if not episode and episode_key in episodes_pending_creation:
                episode = episodes_pending_creation[episode_key]
                logger.debug(f"Reusing pending episode for S{season_number}E{episode_number} (stream_id: {episode_id})")

            if episode:
                # Update existing episode
                updated = False
                if episode_name != episode.name:
                    episode.name = episode_name
                    updated = True
                if description != episode.description:
                    episode.description = description
                    updated = True
                if rating != episode.rating:
                    episode.rating = rating
                    updated = True
                if air_date != episode.air_date:
                    episode.air_date = air_date
                    updated = True
                if duration_secs != episode.duration_secs:
                    episode.duration_secs = duration_secs
                    updated = True
                if tmdb_id != episode.tmdb_id:
                    episode.tmdb_id = tmdb_id
                    updated = True
                if imdb_id != episode.imdb_id:
                    episode.imdb_id = imdb_id
                    updated = True
                if custom_props != episode.custom_properties:
                    episode.custom_properties = custom_props if custom_props else None
                    updated = True

                # Only add to update list if episode has a PK (exists in DB) and isn't already in list
                # Episodes pending creation don't have PKs yet and will be created via bulk_create
                if updated and episode.pk and episode not in episodes_to_update:
                    episodes_to_update.append(episode)
            else:
                # Create new episode
                episode = Episode(
                    series=series,
                    name=episode_name,
                    description=description,
                    air_date=air_date,
                    rating=rating,
                    duration_secs=duration_secs,
                    season_number=season_number,
                    episode_number=episode_number,
                    tmdb_id=tmdb_id,
                    imdb_id=imdb_id,
                    custom_properties=custom_props if custom_props else None
                )
                episodes_to_create.append(episode)
                # Track this episode so subsequent streams with same season/episode can reuse it
                episodes_pending_creation[episode_key] = episode

            # Handle episode relation
            if episode_id in existing_relations:
                # Update existing relation
                relation = existing_relations[episode_id]
                relation.episode = episode
                relation.series_relation = series_relation
                relation.container_extension = container_extension
                relation.custom_properties = {
                    'info': episode_data,
                    'season_number': season_number,
                }
                relation.declared_metadata = _episode_import_metadata(
                    relation, declared_metadata
                )
                relation.last_seen = scan_start_time or timezone.now()  # Mark as seen during this scan
                relations_to_update.append(relation)
            else:
                # Create new relation
                relation = M3UEpisodeRelation(
                    m3u_account=account,
                    episode=episode,
                    series_relation=series_relation,
                    stream_id=episode_id,
                    container_extension=container_extension,
                    custom_properties={
                        'info': episode_data,
                        'season_number': season_number,
                    },
                    declared_metadata=declared_metadata,
                    last_seen=scan_start_time or timezone.now()  # Mark as seen during this scan
                )
                relation.declared_metadata = _episode_import_metadata(
                    relation, declared_metadata
                )
                relations_to_create.append(relation)

        except Exception as e:
            logger.error(f"Error preparing episode {episode_data.get('title', 'Unknown')}: {str(e)}")

    # Execute batch operations
    with transaction.atomic():
        # Create new episodes - use ignore_conflicts in case of race conditions
        if episodes_to_create:
            Episode.objects.bulk_create(episodes_to_create, ignore_conflicts=True)

            # Re-fetch the created episodes to get their PKs
            # We need to do this because bulk_create with ignore_conflicts doesn't set PKs
            created_episode_keys = [
                (ep.series_id, ep.season_number, ep.episode_number)
                for ep in episodes_to_create
            ]
            db_episodes = Episode.objects.filter(series=series)
            episode_pk_map = {
                (ep.series_id, ep.season_number, ep.episode_number): ep
                for ep in db_episodes
            }

            # Update relations to point to the actual DB episodes with PKs
            for relation in relations_to_create:
                ep = relation.episode
                key = (ep.series_id, ep.season_number, ep.episode_number)
                if key in episode_pk_map:
                    relation.episode = episode_pk_map[key]

        # Filter out relations with unsaved episodes (no PK)
        # This can happen if bulk_create had a conflict and ignore_conflicts=True didn't save the episode
        valid_relations_to_create = []
        for relation in relations_to_create:
            if relation.episode.pk is not None:
                valid_relations_to_create.append(relation)
            else:
                season_num = relation.episode.season_number
                episode_num = relation.episode.episode_number
                logger.warning(
                    f"Skipping relation for episode S{season_num}E{episode_num} "
                    f"- episode not saved to database"
                )
        relations_to_create = valid_relations_to_create

        # Update existing episodes
        if episodes_to_update:
            Episode.objects.bulk_update(episodes_to_update, [
                'name', 'description', 'air_date', 'rating', 'duration_secs',
                'tmdb_id', 'imdb_id', 'custom_properties'
            ])

        # Create new episode relations - use ignore_conflicts for stream_id duplicates
        if relations_to_create:
            M3UEpisodeRelation.objects.bulk_create(relations_to_create, ignore_conflicts=True)

        # Update existing episode relations
        if relations_to_update:
            M3UEpisodeRelation.objects.bulk_update(relations_to_update, [
                'episode', 'series_relation', 'container_extension',
                'custom_properties', 'declared_metadata', 'last_seen'
            ])

        # Delete relations for streams no longer returned by the provider.
        # Scope to this series_relation FK (post-migration rows) plus any legacy NULL rows
        # for the same account+series (pre-migration rows whose stream is now gone — the
        # update path only backfills the FK for streams still present in the response).
        # Falls back to account+series scope when series_relation is None (shouldn't occur).
        if series_relation is not None:
            stale_qs = M3UEpisodeRelation.objects.filter(
                Q(series_relation=series_relation) |
                Q(series_relation__isnull=True, m3u_account=account, episode__series=series)
            )
        else:
            stale_qs = M3UEpisodeRelation.objects.filter(
                m3u_account=account,
                episode__series=series
            )
        removed_count = stale_qs.exclude(stream_id__in=episode_ids).delete()[0]
        if removed_count:
            logger.info(f"Removed {removed_count} episode relations no longer present in provider for series {series.name}")

    logger.info(f"Batch processed episodes: {len(episodes_to_create)} new, {len(episodes_to_update)} updated, "
                f"{len(relations_to_create)} new relations, {len(relations_to_update)} updated relations")


@shared_task
def batch_refresh_series_episodes(account_id, series_ids=None):
    """
    Batch refresh episodes for multiple series.
    If series_ids is None, refresh all series that haven't been refreshed recently.
    """
    try:
        account = M3UAccount.objects.select_related("user_agent").get(id=account_id, is_active=True)

        if account.account_type != M3UAccount.Types.XC:
            logger.warning(f"Episode refresh called for non-XC account {account_id}")
            return "Episode refresh only available for XtreamCodes accounts"

        # Determine which series to refresh
        if series_ids:
            series_relations = M3USeriesRelation.objects.filter(
                m3u_account=account,
                series__id__in=series_ids
            ).select_related('series')
        else:
            # Refresh series that haven't been refreshed in the last 24 hours
            cutoff_time = timezone.now() - timezone.timedelta(hours=24)
            series_relations = M3USeriesRelation.objects.filter(
                m3u_account=account,
                last_episode_refresh__lt=cutoff_time
            ).select_related('series')

        logger.info(f"Batch refreshing episodes for {series_relations.count()} series")

        with XtreamCodesClient(
            account.server_url,
            account.username,
            account.password,
            account.get_user_agent_string()
        ) as client:

            refreshed_count = 0
            for relation in series_relations:
                try:
                    refresh_series_episodes(
                        account,
                        relation.series,
                        relation.external_series_id
                    )
                    refreshed_count += 1
                except Exception as e:
                    logger.error(f"Error refreshing episodes for series {relation.series.name}: {str(e)}")

        logger.info(f"Batch episode refresh completed for {refreshed_count} series")
        return f"Batch episode refresh completed for {refreshed_count} series"

    except Exception as e:
        logger.error(f"Error in batch episode refresh for account {account_id}: {str(e)}")
        return f"Batch episode refresh failed: {str(e)}"


@shared_task
def cleanup_orphaned_vod_content(stale_days=0, scan_start_time=None, account_id=None):
    """Clean up VOD content that has no M3U relations or has stale relations"""
    from datetime import timedelta

    # Use scan start time as reference, or current time if not provided
    reference_time = scan_start_time or timezone.now()

    # Calculate cutoff date for stale relations
    cutoff_date = reference_time - timedelta(days=stale_days)

    # Build base query filters
    base_filters = {'last_seen__lt': cutoff_date}
    if account_id:
        base_filters['m3u_account_id'] = account_id
        logger.info(f"Cleaning up stale VOD content for account {account_id}")
    else:
        logger.info("Cleaning up stale VOD content across all accounts")

    # Clean up stale movie relations (haven't been seen in the specified days)
    stale_movie_relations = M3UMovieRelation.objects.filter(**base_filters)
    stale_movie_count = stale_movie_relations.count()
    stale_movie_relations.delete()

    # Clean up stale series relations.
    # Episode relations are removed via CASCADE on the series_relation FK.
    stale_series_relations = M3USeriesRelation.objects.filter(**base_filters)
    stale_series_count = stale_series_relations.count()
    stale_series_relations.delete()

    # Clean up movies with no relations (orphaned)
    # Safe to delete even during account-specific cleanup because if ANY account
    # has a relation, m3u_relations will not be null
    orphaned_movies = Movie.objects.filter(m3u_relations__isnull=True)
    orphaned_movie_count = orphaned_movies.count()
    if orphaned_movie_count > 0:
        logger.info(f"Deleting {orphaned_movie_count} orphaned movies with no M3U relations")
        try:
            orphaned_movies.delete()
        except IntegrityError:
            # A concurrent refresh created a relation between the query and
            # DELETE. Let the next cleanup run handle it.
            logger.warning(
                "Skipped some orphaned movie deletions due to concurrent modifications; "
                "they will be retried on the next cleanup run."
            )
            orphaned_movie_count = 0

    # Clean up series with no relations (orphaned)
    orphaned_series = Series.objects.filter(m3u_relations__isnull=True)
    orphaned_series_count = orphaned_series.count()
    if orphaned_series_count > 0:
        logger.info(f"Deleting {orphaned_series_count} orphaned series with no M3U relations")
        try:
            orphaned_series.delete()
        except IntegrityError:
            logger.warning(
                "Skipped some orphaned series deletions due to concurrent modifications; "
                "they will be retried on the next cleanup run."
            )
            orphaned_series_count = 0

    result = (f"Cleaned up {stale_movie_count} stale movie relations, "
              f"{stale_series_count} stale series relations, "
              f"{orphaned_movie_count} orphaned movies, and "
              f"{orphaned_series_count} orphaned series")

    logger.info(result)
    return result


def handle_movie_id_conflicts(current_movie, relation, tmdb_id_to_set, imdb_id_to_set):
    """
    Handle potential duplicate key conflicts when setting tmdb_id or imdb_id.

    Since this is called when a user is actively accessing movie details, we always
    preserve the current movie (user's selection) and merge the existing one into it.
    This prevents breaking the user's current viewing experience.

    Returns:
        tuple: (movie_to_use, relation_was_updated)
    """
    from django.db import IntegrityError

    existing_movie_with_tmdb = None
    existing_movie_with_imdb = None

    # Check for existing movies with these IDs
    if tmdb_id_to_set:
        try:
            existing_movie_with_tmdb = Movie.objects.get(tmdb_id=tmdb_id_to_set)
        except Movie.DoesNotExist:
            pass

    if imdb_id_to_set:
        try:
            existing_movie_with_imdb = Movie.objects.get(imdb_id=imdb_id_to_set)
        except Movie.DoesNotExist:
            pass

    # If no conflicts, proceed normally
    if not existing_movie_with_tmdb and not existing_movie_with_imdb:
        return current_movie, False

    # Determine which existing movie has the conflicting ID (prefer TMDB match)
    existing_movie = existing_movie_with_tmdb or existing_movie_with_imdb

    # CRITICAL: Check if the existing movie is actually the same as the current movie
    # This can happen if the current movie already has the ID we're trying to set
    if existing_movie.id == current_movie.id:
        logger.debug(f"Current movie {current_movie.id} already has the target ID, no conflict resolution needed")
        return current_movie, False

    logger.info(f"ID conflict detected: Merging existing movie '{existing_movie.name}' (ID: {existing_movie.id}) into current movie '{current_movie.name}' (ID: {current_movie.id}) to preserve user selection")

    # FIRST: Clear the conflicting ID from the existing movie before any merging
    if existing_movie_with_tmdb and tmdb_id_to_set:
        logger.info(f"Clearing tmdb_id from existing movie {existing_movie.id} to avoid constraint violation")
        existing_movie.tmdb_id = None
        existing_movie.save(update_fields=['tmdb_id'])

    if existing_movie_with_imdb and imdb_id_to_set:
        logger.info(f"Clearing imdb_id from existing movie {existing_movie.id} to avoid constraint violation")
        existing_movie.imdb_id = None
        existing_movie.save(update_fields=['imdb_id'])

    # THEN: Merge data from existing movie into current movie (now safe to set IDs)
    merge_movie_data(source_movie=existing_movie, target_movie=current_movie,
                     tmdb_id_to_set=tmdb_id_to_set, imdb_id_to_set=imdb_id_to_set)

    # Transfer all relations from existing movie to current movie
    existing_relations = existing_movie.m3u_relations.all()
    if existing_relations.exists():
        logger.info(f"Transferring {existing_relations.count()} relations from existing movie {existing_movie.id} to current movie {current_movie.id}")
        existing_relations.update(movie=current_movie)

    # Now safe to delete the existing movie since all its relations have been transferred
    logger.info(f"Deleting existing movie {existing_movie.id} '{existing_movie.name}' after merging data and transferring relations")
    existing_movie.delete()

    return current_movie, False  # No relation update needed since we kept current movie


def merge_movie_data(source_movie, target_movie, tmdb_id_to_set=None, imdb_id_to_set=None):
    """
    Merge valuable data from source_movie into target_movie.
    Only overwrites target fields that are empty/None with non-empty source values.

    Args:
        source_movie: Movie to copy data from
        target_movie: Movie to copy data to
        tmdb_id_to_set: TMDB ID to set on target (overrides source tmdb_id)
        imdb_id_to_set: IMDB ID to set on target (overrides source imdb_id)
    """
    updated = False

    # Basic fields - only fill if target is empty
    if not target_movie.description and source_movie.description:
        target_movie.description = source_movie.description
        updated = True
        logger.debug(f"Merged description from movie {source_movie.id} to {target_movie.id}")

    if not target_movie.year and source_movie.year:
        target_movie.year = source_movie.year
        updated = True
        logger.debug(f"Merged year from movie {source_movie.id} to {target_movie.id}")

    if not target_movie.rating and source_movie.rating:
        target_movie.rating = source_movie.rating
        updated = True
        logger.debug(f"Merged rating from movie {source_movie.id} to {target_movie.id}")

    if not target_movie.genre and source_movie.genre:
        target_movie.genre = source_movie.genre
        updated = True
        logger.debug(f"Merged genre from movie {source_movie.id} to {target_movie.id}")

    if not target_movie.duration_secs and source_movie.duration_secs:
        target_movie.duration_secs = source_movie.duration_secs
        updated = True
        logger.debug(f"Merged duration_secs from movie {source_movie.id} to {target_movie.id}")

    if not target_movie.logo and source_movie.logo:
        target_movie.logo = source_movie.logo
        updated = True
        logger.debug(f"Merged logo from movie {source_movie.id} to {target_movie.id}")

    # Handle external IDs - use the specific IDs we want to set, or fall back to source
    if not target_movie.tmdb_id:
        if tmdb_id_to_set:
            target_movie.tmdb_id = tmdb_id_to_set
            updated = True
            logger.debug(f"Set tmdb_id {tmdb_id_to_set} on movie {target_movie.id}")
        elif source_movie.tmdb_id:
            target_movie.tmdb_id = source_movie.tmdb_id
            updated = True
            logger.debug(f"Merged tmdb_id from movie {source_movie.id} to {target_movie.id}")

    if not target_movie.imdb_id:
        if imdb_id_to_set:
            target_movie.imdb_id = imdb_id_to_set
            updated = True
            logger.debug(f"Set imdb_id {imdb_id_to_set} on movie {target_movie.id}")
        elif source_movie.imdb_id:
            target_movie.imdb_id = source_movie.imdb_id
            updated = True
            logger.debug(f"Merged imdb_id from movie {source_movie.id} to {target_movie.id}")

    # Merge custom properties
    target_props = target_movie.custom_properties or {}
    source_props = source_movie.custom_properties or {}

    for key, value in source_props.items():
        if value and not target_props.get(key):
            target_props[key] = value
            updated = True
            logger.debug(f"Merged custom property '{key}' from movie {source_movie.id} to {target_movie.id}")

    if updated:
        target_movie.custom_properties = target_props
        target_movie.save()
        logger.info(f"Successfully merged data from movie {source_movie.id} into {target_movie.id}")


def handle_series_id_conflicts(current_series, relation, tmdb_id_to_set, imdb_id_to_set):
    """
    Handle potential duplicate key conflicts when setting tmdb_id or imdb_id for series.

    Since this is called when a user is actively accessing series details, we always
    preserve the current series (user's selection) and merge the existing one into it.
    This prevents breaking the user's current viewing experience.

    Returns:
        tuple: (series_to_use, relation_was_updated)
    """
    from django.db import IntegrityError

    existing_series_with_tmdb = None
    existing_series_with_imdb = None

    # Check for existing series with these IDs
    if tmdb_id_to_set:
        try:
            existing_series_with_tmdb = Series.objects.get(tmdb_id=tmdb_id_to_set)
        except Series.DoesNotExist:
            pass

    if imdb_id_to_set:
        try:
            existing_series_with_imdb = Series.objects.get(imdb_id=imdb_id_to_set)
        except Series.DoesNotExist:
            pass

    # If no conflicts, proceed normally
    if not existing_series_with_tmdb and not existing_series_with_imdb:
        return current_series, False

    # Determine which existing series has the conflicting ID (prefer TMDB match)
    existing_series = existing_series_with_tmdb or existing_series_with_imdb

    # CRITICAL: Check if the existing series is actually the same as the current series
    # This can happen if the current series already has the ID we're trying to set
    if existing_series.id == current_series.id:
        logger.debug(f"Current series {current_series.id} already has the target ID, no conflict resolution needed")
        return current_series, False

    logger.info(f"ID conflict detected: Merging existing series '{existing_series.name}' (ID: {existing_series.id}) into current series '{current_series.name}' (ID: {current_series.id}) to preserve user selection")

    # FIRST: Clear the conflicting ID from the existing series before any merging
    if existing_series_with_tmdb and tmdb_id_to_set:
        logger.info(f"Clearing tmdb_id from existing series {existing_series.id} to avoid constraint violation")
        existing_series.tmdb_id = None
        existing_series.save(update_fields=['tmdb_id'])

    if existing_series_with_imdb and imdb_id_to_set:
        logger.info(f"Clearing imdb_id from existing series {existing_series.id} to avoid constraint violation")
        existing_series.imdb_id = None
        existing_series.save(update_fields=['imdb_id'])

    # THEN: Merge data from existing series into current series (now safe to set IDs)
    merge_series_data(source_series=existing_series, target_series=current_series,
                      tmdb_id_to_set=tmdb_id_to_set, imdb_id_to_set=imdb_id_to_set)

    # Transfer all relations from existing series to current series
    existing_relations = existing_series.m3u_relations.all()
    if existing_relations.exists():
        logger.info(f"Transferring {existing_relations.count()} relations from existing series {existing_series.id} to current series {current_series.id}")
        existing_relations.update(series=current_series)

    # Now safe to delete the existing series since all its relations have been transferred
    logger.info(f"Deleting existing series {existing_series.id} '{existing_series.name}' after merging data and transferring relations")
    existing_series.delete()

    return current_series, False  # No relation update needed since we kept current series


def merge_series_data(source_series, target_series, tmdb_id_to_set=None, imdb_id_to_set=None):
    """
    Merge valuable data from source_series into target_series.
    Only overwrites target fields that are empty/None with non-empty source values.

    Args:
        source_series: Series to copy data from
        target_series: Series to copy data to
        tmdb_id_to_set: TMDB ID to set on target (overrides source tmdb_id)
        imdb_id_to_set: IMDB ID to set on target (overrides source imdb_id)
    """
    updated = False

    # Basic fields - only fill if target is empty
    if not target_series.description and source_series.description:
        target_series.description = source_series.description
        updated = True
        logger.debug(f"Merged description from series {source_series.id} to {target_series.id}")

    if not target_series.year and source_series.year:
        target_series.year = source_series.year
        updated = True
        logger.debug(f"Merged year from series {source_series.id} to {target_series.id}")

    if not target_series.rating and source_series.rating:
        target_series.rating = source_series.rating
        updated = True
        logger.debug(f"Merged rating from series {source_series.id} to {target_series.id}")

    if not target_series.genre and source_series.genre:
        target_series.genre = source_series.genre
        updated = True
        logger.debug(f"Merged genre from series {source_series.id} to {target_series.id}")

    if not target_series.logo and source_series.logo:
        target_series.logo = source_series.logo
        updated = True
        logger.debug(f"Merged logo from series {source_series.id} to {target_series.id}")

    # Handle external IDs - use the specific IDs we want to set, or fall back to source
    if not target_series.tmdb_id:
        if tmdb_id_to_set:
            target_series.tmdb_id = tmdb_id_to_set
            updated = True
            logger.debug(f"Set tmdb_id {tmdb_id_to_set} on series {target_series.id}")
        elif source_series.tmdb_id:
            target_series.tmdb_id = source_series.tmdb_id
            updated = True
            logger.debug(f"Merged tmdb_id from series {source_series.id} to {target_series.id}")

    if not target_series.imdb_id:
        if imdb_id_to_set:
            target_series.imdb_id = imdb_id_to_set
            updated = True
            logger.debug(f"Set imdb_id {imdb_id_to_set} on series {target_series.id}")
        elif source_series.imdb_id:
            target_series.imdb_id = source_series.imdb_id
            updated = True
            logger.debug(f"Merged imdb_id from series {source_series.id} to {target_series.id}")

    # Merge custom properties
    target_props = target_series.custom_properties or {}
    source_props = source_series.custom_properties or {}

    for key, value in source_props.items():
        if value and not target_props.get(key):
            target_props[key] = value
            updated = True
            logger.debug(f"Merged custom property '{key}' from series {source_series.id} to {target_series.id}")

    if updated:
        target_series.custom_properties = target_props
        target_series.save()
        logger.info(f"Successfully merged data from series {source_series.id} into {target_series.id}")


def is_non_empty_string(value):
    """
    Helper function to safely check if a value is a non-empty string.
    Returns True only if value is a string and has non-whitespace content.
    """
    return isinstance(value, str) and value.strip()


def extract_string_from_array_or_string(value):
    """
    Helper function to extract a string value from either a string or array.
    Returns the first non-null string from an array, or the string itself.
    Returns None if no valid string is found.
    """
    if isinstance(value, str):
        return value.strip() if value.strip() else None
    elif isinstance(value, list) and value:
        # Find first non-null, non-empty string in the array
        for item in value:
            if isinstance(item, str) and item.strip():
                return item.strip()
            elif item is not None and str(item).strip():
                return str(item).strip()
    return None


def clean_custom_properties(custom_props):
    """
    Remove null, empty, or invalid values from custom_properties dict.
    Only keeps properties that have meaningful values.
    """
    if not custom_props:
        return None

    cleaned = {}
    for key, value in custom_props.items():
        # Handle fields that should extract clean strings
        if key in ['youtube_trailer', 'actors', 'director', 'cast']:
            clean_value = extract_string_from_array_or_string(value)
            if clean_value:
                cleaned[key] = clean_value
        # Handle backdrop_path which should remain as array format
        elif key == 'backdrop_path':
            clean_value = extract_string_from_array_or_string(value)
            if clean_value:
                cleaned[key] = [clean_value]
        else:
            # For other properties, keep them if they're not None and not empty
            if value is not None and value != '' and value != []:
                # If it's a list with only null values, skip it
                if isinstance(value, list) and all(item is None for item in value):
                    continue
                cleaned[key] = value

    return cleaned if cleaned else None


def should_update_field(existing_value, new_value):
    """
    Helper function to determine if we should update a field.
    Returns True if:
    - new_value is a non-empty string (or contains one if it's an array) AND
    - existing_value is None, empty string, array with null/empty values, or non-string
    """
    # Extract actual string values from arrays if needed
    new_string = extract_string_from_array_or_string(new_value)
    existing_string = extract_string_from_array_or_string(existing_value)

    return new_string is not None and (existing_string is None or not existing_string)


def is_blank_vod_value(value):
    """Return True for None, empty string, empty list, or all-null/empty list items."""
    if value is None or value == '' or value == []:
        return True
    if isinstance(value, list) and all(item is None or item == '' for item in value):
        return True
    return False


def should_apply_provider_list_field(existing_value, new_value):
    """Return True when a non-blank list-API value should replace the stored field.

    Blank or missing provider values are ignored so detail filled from
    get_vod_info is not cleared by sparse get_vod_streams / get_series rows.
    """
    if is_blank_vod_value(new_value):
        return False
    return existing_value != new_value


def merge_blank_vod_list_props(existing_props, incoming_props):
    """Fill blank keys on existing_props from incoming_props (in place)."""
    for field, value in incoming_props.items():
        if field == 'custom_properties':
            existing_cp = existing_props.get('custom_properties') or {}
            incoming_cp = value or {}
            merged = dict(existing_cp)
            for k, v in incoming_cp.items():
                if not is_blank_vod_value(v) and is_blank_vod_value(merged.get(k)):
                    merged[k] = v
            existing_props['custom_properties'] = merged or None
        elif field not in existing_props or (
            is_blank_vod_value(existing_props.get(field)) and not is_blank_vod_value(value)
        ):
            existing_props[field] = value


def build_movie_list_props(
    movie_data, name, clean_title, year, tmdb_id, imdb_id
):
    """Build Movie list-sync props and logo URL from a provider row."""
    description = movie_data.get('description') or movie_data.get('plot') or ''
    rating = normalize_rating(movie_data.get('rating') or movie_data.get('vote_average'))
    genre = movie_data.get('genre') or movie_data.get('category_name') or ''
    duration_secs = extract_duration_from_data(movie_data)
    trailer_raw = movie_data.get('trailer') or movie_data.get('youtube_trailer') or ''
    trailer = extract_string_from_array_or_string(trailer_raw) if trailer_raw else None
    logo_url = movie_data.get('stream_icon') or ''

    director = extract_string_from_array_or_string(
        movie_data.get('director') or ''
    )
    actors_raw = movie_data.get('actors') or movie_data.get('cast') or ''
    if isinstance(actors_raw, list):
        actors = ', '.join(s.strip() for s in actors_raw if s and str(s).strip()) or None
    else:
        actors = actors_raw.strip() if actors_raw else None
    release_date = movie_data.get('release_date') or movie_data.get('releasedate') or ''

    custom_props = {}
    if trailer:
        custom_props['youtube_trailer'] = trailer
    if director:
        custom_props['director'] = director
    if actors:
        custom_props['actors'] = actors
    if release_date:
        custom_props['release_date'] = release_date

    movie_props = {
        'name': name,
        'clean_title': clean_title,
        'year': year,
        'tmdb_id': tmdb_id,
        'imdb_id': imdb_id,
        'description': description,
        'rating': rating,
        'genre': genre,
        'duration_secs': duration_secs,
        'custom_properties': custom_props or None,
    }
    # Only set is_adult when the provider actually reports it. Movies are
    # shared across providers (matched by TMDB/IMDB/cleaned title and year), and many
    # providers omit this key entirely; defaulting it to False here would
    # let a sparse provider row silently clear a flag another provider set.
    if 'is_adult' in movie_data:
        movie_props['is_adult'] = parse_is_adult(movie_data['is_adult'])

    return movie_props, logo_url


def build_series_list_props(
    series_data, name, clean_title, year, tmdb_id, imdb_id
):
    """Build Series list-sync props and logo URL from a provider row."""
    description = series_data.get('plot', '')
    rating = normalize_rating(series_data.get('rating'))
    genre = series_data.get('genre', '')
    logo_url = series_data.get('cover') or ''

    additional_metadata = {}
    for key in ['backdrop_path', 'poster_path', 'original_name', 'first_air_date', 'last_air_date',
               'episode_run_time', 'status', 'type', 'cast', 'director', 'country', 'language',
               'releaseDate', 'youtube_trailer', 'category_id', 'age', 'seasons']:
        value = series_data.get(key)
        if value:
            if key == 'cast':
                if isinstance(value, list):
                    clean_value = ', '.join(s.strip() for s in value if s and str(s).strip()) or None
                else:
                    clean_value = extract_string_from_array_or_string(value)
                if clean_value:
                    additional_metadata[key] = clean_value
            elif key in ['poster_path', 'youtube_trailer', 'director']:
                clean_value = extract_string_from_array_or_string(value)
                if clean_value:
                    additional_metadata[key] = clean_value
            elif key == 'backdrop_path':
                clean_value = extract_string_from_array_or_string(value)
                if clean_value:
                    additional_metadata[key] = [clean_value]
            else:
                if value is not None and value != '' and value != []:
                    additional_metadata[key] = value

    series_props = {
        'name': name,
        'clean_title': clean_title,
        'year': year,
        'tmdb_id': tmdb_id,
        'imdb_id': imdb_id,
        'description': description,
        'rating': rating,
        'genre': genre,
        'custom_properties': additional_metadata if additional_metadata else None,
    }
    return series_props, logo_url


@shared_task
def refresh_movie_advanced_data(m3u_movie_relation_id, force_refresh=False):
    """
    Fetch advanced movie data from provider and update Movie and M3UMovieRelation.

    Provider movie files are stable source records. Fetch their advanced data
    once and keep it until an administrator explicitly requests a refresh.
    """
    try:
        relation = M3UMovieRelation.objects.select_related('movie', 'm3u_account__user_agent').get(id=m3u_movie_relation_id)
        now = timezone.now()
        detailed_fetched = (relation.custom_properties or {}).get('detailed_fetched', False)
        if not force_refresh and detailed_fetched:
            return "Advanced data already fetched, skipping."

        account = relation.m3u_account
        movie = relation.movie

        from core.xtream_codes import Client as XtreamCodesClient

        with XtreamCodesClient(
            server_url=account.server_url,
            username=account.username,
            password=account.password,
            user_agent=account.get_user_agent_string()
        ) as client:
            vod_info = client.get_vod_info(relation.stream_id)
            if vod_info and 'info' in vod_info:
                info_raw = vod_info.get('info', {})

                # Handle case where 'info' might be a list instead of dict
                if isinstance(info_raw, list):
                    # If it's a list, try to use the first item or create empty dict
                    info = info_raw[0] if info_raw and isinstance(info_raw[0], dict) else {}
                    logger.warning(f"VOD info for stream {relation.stream_id} returned list instead of dict, using first item")
                elif isinstance(info_raw, dict):
                    info = info_raw
                else:
                    info = {}
                    logger.warning(f"VOD info for stream {relation.stream_id} returned unexpected type: {type(info_raw)}")

                movie_data_raw = vod_info.get('movie_data', {})

                # Handle case where 'movie_data' might be a list instead of dict
                if isinstance(movie_data_raw, list):
                    movie_data = movie_data_raw[0] if movie_data_raw and isinstance(movie_data_raw[0], dict) else {}
                    logger.warning(f"VOD movie_data for stream {relation.stream_id} returned list instead of dict, using first item")
                elif isinstance(movie_data_raw, dict):
                    movie_data = movie_data_raw
                else:
                    movie_data = {}
                    logger.warning(f"VOD movie_data for stream {relation.stream_id} returned unexpected type: {type(movie_data_raw)}")

                if relation.tmdb_override_id:
                    # This concrete provider source was deliberately moved to
                    # another canonical title. Keep provider detail on the
                    # relation, but never let the provider's old IDs or text
                    # overwrite the selected TMDB-backed canonical record.
                    relation_custom_props = relation.custom_properties or {}
                    cleaned_info = clean_custom_properties(info) if info else None
                    cleaned_movie_data = (
                        clean_custom_properties(movie_data) if movie_data else None
                    )
                    if cleaned_info:
                        relation_custom_props['detailed_info'] = cleaned_info
                    if cleaned_movie_data:
                        relation_custom_props['movie_data'] = cleaned_movie_data
                    relation_custom_props['detailed_fetched'] = True
                    relation.custom_properties = relation_custom_props
                    relation.last_advanced_refresh = now
                    relation._skip_vod_profile_invalidation = True
                    relation.save(
                        update_fields=['custom_properties', 'last_advanced_refresh']
                    )
                    from .metadata import sync_relation_declared_metadata

                    sync_relation_declared_metadata(
                        relation,
                        notify_profile_change=False,
                    )
                    from .catalog_cache import bump_catalog_generation

                    # The provider payload belongs to this concrete source.
                    # A manual TMDB assignment must keep the selected canonical
                    # record entirely under canonical/TMDB control.
                    bump_catalog_generation(invalidate_selections=False)
                    return "Advanced source data refreshed; canonical override preserved."

                # Update Movie fields if changed
                updated = False
                custom_props = movie.custom_properties or {}
                if info.get('plot') and info.get('plot') != movie.description:
                    movie.description = info.get('plot')
                    updated = True
                normalized_rating = normalize_rating(info.get('rating'))
                if normalized_rating and normalized_rating != movie.rating:
                    movie.rating = normalized_rating
                    updated = True
                if info.get('genre') and info.get('genre') != movie.genre:
                    movie.genre = info.get('genre')
                    updated = True
                if info.get('duration_secs'):
                    duration_secs = int(info.get('duration_secs'))
                    if duration_secs != movie.duration_secs:
                        movie.duration_secs = duration_secs
                        updated = True
                # Check for releasedate or release_date
                release_date_value = info.get('releasedate') or info.get('release_date')
                if release_date_value:
                    try:
                        year = int(str(release_date_value).split('-')[0])
                        if year != movie.year:
                            movie.year = year
                            updated = True
                    except Exception:
                        pass
                # Handle TMDB/IMDB ID updates with duplicate key protection
                tmdb_id_to_set = info.get('tmdb_id') if info.get('tmdb_id') and info.get('tmdb_id') != movie.tmdb_id else None
                imdb_id_to_set = info.get('imdb_id') if info.get('imdb_id') and info.get('imdb_id') != movie.imdb_id else None

                logger.debug(f"Movie {movie.id} current IDs: tmdb_id={movie.tmdb_id}, imdb_id={movie.imdb_id}")
                logger.debug(f"IDs to set: tmdb_id={tmdb_id_to_set}, imdb_id={imdb_id_to_set}")

                if tmdb_id_to_set or imdb_id_to_set:
                    # Check for existing movies with these IDs and handle duplicates
                    updated_movie, relation_updated = handle_movie_id_conflicts(
                        movie, relation, tmdb_id_to_set, imdb_id_to_set
                    )
                    if relation_updated:
                        # Continue with the canonical movie now used by the relation.
                        movie = updated_movie
                        logger.info(f"Relation updated, now working with movie {movie.id}")
                    else:
                        # No relation update, safe to set the IDs
                        if tmdb_id_to_set:
                            movie.tmdb_id = tmdb_id_to_set
                            updated = True
                            logger.debug(f"Set tmdb_id {tmdb_id_to_set} on movie {movie.id}")
                        if imdb_id_to_set:
                            movie.imdb_id = imdb_id_to_set
                            updated = True
                            logger.debug(f"Set imdb_id {imdb_id_to_set} on movie {movie.id}")
                if should_update_field(custom_props.get('youtube_trailer'), info.get('trailer')):
                    custom_props['youtube_trailer'] = extract_string_from_array_or_string(info.get('trailer'))
                    updated = True
                if should_update_field(custom_props.get('youtube_trailer'), info.get('youtube_trailer')):
                    custom_props['youtube_trailer'] = extract_string_from_array_or_string(info.get('youtube_trailer'))
                    updated = True
                if should_update_field(custom_props.get('backdrop_path'), info.get('backdrop_path')):
                    backdrop_url = extract_string_from_array_or_string(info.get('backdrop_path'))
                    custom_props['backdrop_path'] = [backdrop_url] if backdrop_url else None
                    updated = True
                for actors_key in ('actors', 'cast'):
                    actors_raw = info.get(actors_key)
                    if should_update_field(custom_props.get('actors'), actors_raw):
                        if isinstance(actors_raw, list):
                            custom_props['actors'] = ', '.join(s.strip() for s in actors_raw if s and str(s).strip()) or None
                        else:
                            custom_props['actors'] = extract_string_from_array_or_string(actors_raw)
                        updated = True
                        break
                if should_update_field(custom_props.get('director'), info.get('director')):
                    custom_props['director'] = extract_string_from_array_or_string(info.get('director'))
                    updated = True
                if updated:
                    # Clean custom_properties before saving to remove null/empty values
                    movie.custom_properties = clean_custom_properties(custom_props)
                    try:
                        movie.save()
                    except Exception as save_error:
                        # Retry without conflicting provider IDs if the canonical
                        # conflict resolution still races another writer.
                        logger.error(f"Failed to save movie {movie.id} after conflict resolution: {str(save_error)}")
                        if 'tmdb_id' in str(save_error) and movie.tmdb_id:
                            logger.warning(f"Clearing tmdb_id {movie.tmdb_id} from movie {movie.id} due to save error")
                            movie.tmdb_id = None
                        if 'imdb_id' in str(save_error) and movie.imdb_id:
                            logger.warning(f"Clearing imdb_id {movie.imdb_id} from movie {movie.id} due to save error")
                            movie.imdb_id = None
                        try:
                            movie.save()
                            logger.info(f"Successfully saved movie {movie.id} after clearing problematic IDs")
                        except Exception as final_error:
                            logger.error(f"Final save attempt failed for movie {movie.id}: {str(final_error)}")
                            raise

                # Update relation custom_properties and last_advanced_refresh
                relation_custom_props = relation.custom_properties or {}

                # Clean the detailed_info before saving to avoid storing null/empty arrays
                cleaned_info = clean_custom_properties(info) if info else None
                cleaned_movie_data = clean_custom_properties(movie_data) if movie_data else None

                if cleaned_info:
                    relation_custom_props['detailed_info'] = cleaned_info
                if cleaned_movie_data:
                    relation_custom_props['movie_data'] = cleaned_movie_data
                relation_custom_props['detailed_fetched'] = True

                relation.custom_properties = relation_custom_props
                relation.last_advanced_refresh = now
                # Lazy provider details update the inspector cache only; they
                # must not change or invalidate prepared output catalogs.
                relation._skip_vod_profile_invalidation = True
                relation.save(update_fields=['custom_properties', 'last_advanced_refresh'])
                from .metadata import sync_relation_declared_metadata

                sync_relation_declared_metadata(
                    relation,
                    notify_profile_change=False,
                )
                from .provider_metadata import reconcile_movie_provider_metadata

                if reconcile_movie_provider_metadata([relation.movie_id]):
                    from .catalog_cache import bump_catalog_generation

                    bump_catalog_generation(invalidate_selections=False)

        return "Advanced data refreshed."
    except Exception as e:
        logger.error(f"Error refreshing advanced movie data for relation {m3u_movie_relation_id}: {str(e)}")
        return f"Error: {str(e)}"
