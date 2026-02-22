import logging
from datetime import date
from time import monotonic
from typing import Optional

from celery import shared_task
from django.db import IntegrityError
from django.utils import timezone

from apps.m3u.models import M3UAccount
from apps.media_servers.models import MediaServerIntegration, MediaServerSyncRun
from apps.media_servers.providers import (
    ProviderEpisode,
    ProviderMovie,
    ProviderSeries,
    get_provider_client,
)
from apps.vod.models import (
    Episode,
    M3UEpisodeRelation,
    M3UMovieRelation,
    M3USeriesRelation,
    M3UVODCategoryRelation,
    Movie,
    Series,
    VODCategory,
    VODLogo,
)
from core.utils import send_websocket_update

logger = logging.getLogger(__name__)

MEDIA_SERVER_ACCOUNT_PREFIX = 'Media Server'
MEDIA_SERVER_ACCOUNT_PRIORITY = 1000
UNCATEGORIZED_NAME = 'Uncategorized'
STAGE_DISCOVERY = 'discovery'
STAGE_IMPORT = 'import'
STAGE_CLEANUP = 'cleanup'
SYNC_WS_UPDATE_INTERVAL_SECONDS = 1.0


class SyncCancelled(Exception):
    pass


def _default_sync_stages() -> dict:
    return {
        STAGE_DISCOVERY: {'status': 'pending', 'processed': 0, 'total': 0},
        STAGE_IMPORT: {'status': 'pending', 'processed': 0, 'total': 0},
        STAGE_CLEANUP: {'status': 'pending', 'processed': 0, 'total': 0},
    }


def _sync_run_payload(sync_run: MediaServerSyncRun) -> dict:
    return {
        'id': sync_run.id,
        'integration': sync_run.integration_id,
        'integration_name': sync_run.integration.name,
        'provider_type': sync_run.integration.provider_type,
        'status': sync_run.status,
        'summary': sync_run.summary,
        'stages': sync_run.stages or {},
        'processed_items': sync_run.processed_items,
        'total_items': sync_run.total_items,
        'created_items': sync_run.created_items,
        'updated_items': sync_run.updated_items,
        'removed_items': sync_run.removed_items,
        'skipped_items': sync_run.skipped_items,
        'error_count': sync_run.error_count,
        'message': sync_run.message,
        'extra': sync_run.extra,
        'task_id': sync_run.task_id,
        'created_at': sync_run.created_at.isoformat() if sync_run.created_at else None,
        'updated_at': sync_run.updated_at.isoformat() if sync_run.updated_at else None,
        'started_at': sync_run.started_at.isoformat() if sync_run.started_at else None,
        'finished_at': sync_run.finished_at.isoformat() if sync_run.finished_at else None,
    }


def _broadcast_sync_run_update(
    sync_run: MediaServerSyncRun,
    ws_state: dict[str, float],
    *,
    force: bool = False,
) -> None:
    now = monotonic()
    if not force and now - ws_state.get('last_sent', 0.0) < SYNC_WS_UPDATE_INTERVAL_SECONDS:
        return
    ws_state['last_sent'] = now
    send_websocket_update(
        'updates',
        'update',
        {
            'type': 'media_server_sync_updated',
            'sync_run': _sync_run_payload(sync_run),
        },
    )


def _update_sync_stage(
    sync_run: MediaServerSyncRun,
    stage_key: str,
    *,
    status: Optional[str] = None,
    processed: Optional[int] = None,
    total: Optional[int] = None,
) -> None:
    stages = sync_run.stages or {}
    stage = stages.get(stage_key) or {'status': 'pending', 'processed': 0, 'total': 0}
    if status is not None:
        stage['status'] = status
    if processed is not None:
        stage['processed'] = processed
    if total is not None:
        stage['total'] = total
    stages[stage_key] = stage
    sync_run.stages = stages
    sync_run.save(update_fields=['stages', 'updated_at'])


def _update_sync_metrics(
    sync_run: MediaServerSyncRun,
    *,
    processed_items: int,
    total_items: int,
    created_items: int,
    updated_items: int,
    removed_items: int,
    skipped_items: int,
    error_count: int,
    extra: Optional[dict] = None,
) -> None:
    sync_run.processed_items = processed_items
    sync_run.total_items = total_items
    sync_run.created_items = created_items
    sync_run.updated_items = updated_items
    sync_run.removed_items = removed_items
    sync_run.skipped_items = skipped_items
    sync_run.error_count = error_count
    if extra is not None:
        sync_run.extra = extra
    sync_run.save(
        update_fields=[
            'processed_items',
            'total_items',
            'created_items',
            'updated_items',
            'removed_items',
            'skipped_items',
            'error_count',
            'extra',
            'updated_at',
        ]
    )


def _is_http_stream(url: Optional[str]) -> bool:
    value = str(url or '').strip().lower()
    return value.startswith('http://') or value.startswith('https://')


def _set_sync_state(
    integration: MediaServerIntegration,
    *,
    status: str,
    message: str,
    update_synced_at: bool = False,
) -> None:
    integration.last_sync_status = status
    integration.last_sync_message = message[:2000]
    update_fields = ['last_sync_status', 'last_sync_message', 'updated_at']
    if update_synced_at:
        integration.last_synced_at = timezone.now()
        update_fields.append('last_synced_at')
    integration.save(update_fields=update_fields)


def _account_name(integration: MediaServerIntegration) -> str:
    return f'{MEDIA_SERVER_ACCOUNT_PREFIX} {integration.id}: {integration.name}'


def ensure_integration_vod_account(integration: MediaServerIntegration) -> M3UAccount:
    custom_markers = {
        'managed_source': 'media_server',
        'integration_id': integration.id,
        'integration_name': integration.name,
        'provider': integration.provider_type,
    }
    desired_name = _account_name(integration)
    expected_active = bool(integration.enabled and integration.add_to_vod)

    account = integration.vod_account
    if not account:
        account = M3UAccount.objects.filter(
            custom_properties__managed_source='media_server',
            custom_properties__integration_id=integration.id,
        ).first()

    if not account:
        account = M3UAccount.objects.create(
            name=desired_name,
            account_type=M3UAccount.Types.STADNARD,
            is_active=expected_active,
            locked=True,
            refresh_interval=0,
            priority=MEDIA_SERVER_ACCOUNT_PRIORITY,
            custom_properties=custom_markers,
        )
    else:
        updates = []
        if account.name != desired_name:
            account.name = desired_name
            updates.append('name')
        if account.is_active != expected_active:
            account.is_active = expected_active
            updates.append('is_active')
        if not account.locked:
            account.locked = True
            updates.append('locked')
        if account.refresh_interval != 0:
            account.refresh_interval = 0
            updates.append('refresh_interval')
        if account.priority != MEDIA_SERVER_ACCOUNT_PRIORITY:
            account.priority = MEDIA_SERVER_ACCOUNT_PRIORITY
            updates.append('priority')
        merged_custom_properties = dict(account.custom_properties or {})
        merged_custom_properties.update(custom_markers)
        if merged_custom_properties != (account.custom_properties or {}):
            account.custom_properties = merged_custom_properties
            updates.append('custom_properties')
        if updates:
            account.save(update_fields=updates)

    if integration.vod_account_id != account.id:
        integration.vod_account = account
        integration.save(update_fields=['vod_account', 'updated_at'])

    return account


def _normalize_external_id(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    normalized = str(value).strip()
    if normalized in {'', '0'}:
        return None
    return normalized


def _set_if_blank(obj, field: str, value) -> bool:
    if value in (None, '', [], {}):
        return False
    current = getattr(obj, field)
    if current in (None, '', [], {}):
        setattr(obj, field, value)
        return True
    return False


def _first_if_unique(queryset):
    matches = list(queryset[:2])
    if len(matches) == 1:
        return matches[0]
    return None


def _pick_best_name_year_match(queryset):
    """
    Pick a deterministic fallback when title/year has multiple matches.

    Preference order:
    1) Entry without external IDs (matches the name/year-only uniqueness bucket)
    2) Lowest primary key for stable behavior
    """
    match = queryset.filter(tmdb_id__isnull=True, imdb_id__isnull=True).order_by('id').first()
    if match:
        return match
    return queryset.order_by('id').first()


def _ensure_logo(*, title: str, poster_url: str) -> Optional[VODLogo]:
    url = (poster_url or '').strip()
    if not url:
        return None
    logo, _ = VODLogo.objects.get_or_create(
        url=url,
        defaults={'name': title[:255] or 'Media'},
    )
    return logo


def _should_update_logo(*, current_logo: Optional[VODLogo], next_logo: Optional[VODLogo]) -> bool:
    if not next_logo:
        return False
    if not current_logo:
        return True
    if current_logo.id == next_logo.id:
        return False

    current_is_http = _is_http_stream(str(getattr(current_logo, 'url', '') or '').strip())
    next_is_http = _is_http_stream(str(getattr(next_logo, 'url', '') or '').strip())

    # Keep existing behavior for HTTP->HTTP updates, but allow local/non-HTTP
    # artwork to replace TMDB URLs when it becomes available.
    if current_is_http and next_is_http:
        return False
    return True


def _normalize_air_date(value: Optional[str]) -> Optional[date]:
    raw = str(value or '').strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


def _find_existing_movie(provider_movie: ProviderMovie) -> Optional[Movie]:
    tmdb_id = _normalize_external_id(provider_movie.tmdb_id)
    imdb_id = _normalize_external_id(provider_movie.imdb_id)

    if tmdb_id:
        movie = Movie.objects.filter(tmdb_id=tmdb_id).first()
        if movie:
            return movie

    if imdb_id:
        movie = Movie.objects.filter(imdb_id=imdb_id).first()
        if movie:
            return movie

    if provider_movie.title and provider_movie.year:
        name_year_matches = Movie.objects.filter(
            name__iexact=provider_movie.title,
            year=provider_movie.year,
        )
        unique_match = _first_if_unique(name_year_matches)
        if unique_match:
            return unique_match
        return _pick_best_name_year_match(name_year_matches)

    return None


def _sync_movie(provider_movie: ProviderMovie) -> tuple[Movie, bool, bool]:
    tmdb_id = _normalize_external_id(provider_movie.tmdb_id)
    imdb_id = _normalize_external_id(provider_movie.imdb_id)
    logo = _ensure_logo(title=provider_movie.title, poster_url=provider_movie.poster_url)

    movie = _find_existing_movie(provider_movie)
    created = False
    updated = False

    if not movie:
        genre_string = ', '.join(provider_movie.genres or [])
        try:
            movie = Movie.objects.create(
                name=provider_movie.title,
                description=provider_movie.description or '',
                year=provider_movie.year,
                rating=provider_movie.rating or '',
                genre=genre_string,
                duration_secs=provider_movie.duration_secs,
                tmdb_id=tmdb_id,
                imdb_id=imdb_id,
                logo=logo,
                custom_properties={},
            )
            created = True
        except IntegrityError:
            movie = _find_existing_movie(provider_movie)
            if not movie:
                raise

    if movie and not created:
        updated |= _set_if_blank(movie, 'name', provider_movie.title)
        updated |= _set_if_blank(movie, 'description', provider_movie.description or '')
        updated |= _set_if_blank(movie, 'year', provider_movie.year)
        updated |= _set_if_blank(movie, 'rating', provider_movie.rating or '')
        updated |= _set_if_blank(movie, 'genre', ', '.join(provider_movie.genres or []))
        updated |= _set_if_blank(movie, 'tmdb_id', tmdb_id)
        updated |= _set_if_blank(movie, 'imdb_id', imdb_id)

        if movie.duration_secs in (None, 0) and provider_movie.duration_secs:
            movie.duration_secs = provider_movie.duration_secs
            updated = True

        if _should_update_logo(current_logo=movie.logo, next_logo=logo):
            movie.logo = logo
            updated = True

        if updated:
            movie.save()

    return movie, created, updated


def _find_existing_series(provider_series: ProviderSeries) -> Optional[Series]:
    tmdb_id = _normalize_external_id(provider_series.tmdb_id)
    imdb_id = _normalize_external_id(provider_series.imdb_id)

    if tmdb_id:
        series = Series.objects.filter(tmdb_id=tmdb_id).first()
        if series:
            return series

    if imdb_id:
        series = Series.objects.filter(imdb_id=imdb_id).first()
        if series:
            return series

    if provider_series.title and provider_series.year:
        name_year_matches = Series.objects.filter(
            name__iexact=provider_series.title,
            year=provider_series.year,
        )
        unique_match = _first_if_unique(name_year_matches)
        if unique_match:
            return unique_match
        return _pick_best_name_year_match(name_year_matches)

    return None


def _sync_series(provider_series: ProviderSeries) -> tuple[Series, bool, bool]:
    tmdb_id = _normalize_external_id(provider_series.tmdb_id)
    imdb_id = _normalize_external_id(provider_series.imdb_id)
    logo = _ensure_logo(title=provider_series.title, poster_url=provider_series.poster_url)

    series = _find_existing_series(provider_series)
    created = False
    updated = False

    if not series:
        genre_string = ', '.join(provider_series.genres or [])
        try:
            series = Series.objects.create(
                name=provider_series.title,
                description=provider_series.description or '',
                year=provider_series.year,
                rating=provider_series.rating or '',
                genre=genre_string,
                tmdb_id=tmdb_id,
                imdb_id=imdb_id,
                logo=logo,
                custom_properties={},
            )
            created = True
        except IntegrityError:
            series = _find_existing_series(provider_series)
            if not series:
                raise

    if series and not created:
        updated |= _set_if_blank(series, 'name', provider_series.title)
        updated |= _set_if_blank(series, 'description', provider_series.description or '')
        updated |= _set_if_blank(series, 'year', provider_series.year)
        updated |= _set_if_blank(series, 'rating', provider_series.rating or '')
        updated |= _set_if_blank(series, 'genre', ', '.join(provider_series.genres or []))
        updated |= _set_if_blank(series, 'tmdb_id', tmdb_id)
        updated |= _set_if_blank(series, 'imdb_id', imdb_id)

        if _should_update_logo(current_logo=series.logo, next_logo=logo):
            series.logo = logo
            updated = True

        if updated:
            series.save()

    return series, created, updated


def _find_existing_episode(series: Series, provider_episode: ProviderEpisode) -> Optional[Episode]:
    tmdb_id = _normalize_external_id(provider_episode.tmdb_id)
    imdb_id = _normalize_external_id(provider_episode.imdb_id)

    if tmdb_id:
        episode = Episode.objects.filter(tmdb_id=tmdb_id).first()
        if episode:
            return episode

    if imdb_id:
        episode = Episode.objects.filter(imdb_id=imdb_id).first()
        if episode:
            return episode

    season_number = provider_episode.season_number
    episode_number = provider_episode.episode_number
    if season_number is not None and episode_number is not None:
        return Episode.objects.filter(
            series=series,
            season_number=season_number,
            episode_number=episode_number,
        ).first()

    title = (provider_episode.title or '').strip()
    if title:
        return _first_if_unique(Episode.objects.filter(series=series, name__iexact=title))

    return None


def _sync_episode(
    series: Series,
    provider_episode: ProviderEpisode,
) -> tuple[Episode, bool, bool]:
    tmdb_id = _normalize_external_id(provider_episode.tmdb_id)
    imdb_id = _normalize_external_id(provider_episode.imdb_id)

    episode = _find_existing_episode(series, provider_episode)
    created = False
    updated = False

    if not episode:
        try:
            episode = Episode.objects.create(
                name=provider_episode.title,
                description=provider_episode.description or '',
                air_date=_normalize_air_date(provider_episode.air_date),
                rating=provider_episode.rating or '',
                duration_secs=provider_episode.duration_secs,
                series=series,
                season_number=provider_episode.season_number,
                episode_number=provider_episode.episode_number,
                tmdb_id=tmdb_id,
                imdb_id=imdb_id,
                custom_properties={},
            )
            created = True
        except IntegrityError:
            episode = _find_existing_episode(series, provider_episode)
            if not episode:
                raise

    if episode and not created:
        updated |= _set_if_blank(episode, 'name', provider_episode.title)
        updated |= _set_if_blank(episode, 'description', provider_episode.description or '')
        updated |= _set_if_blank(episode, 'air_date', _normalize_air_date(provider_episode.air_date))
        updated |= _set_if_blank(episode, 'rating', provider_episode.rating or '')
        updated |= _set_if_blank(episode, 'duration_secs', provider_episode.duration_secs)
        updated |= _set_if_blank(episode, 'tmdb_id', tmdb_id)
        updated |= _set_if_blank(episode, 'imdb_id', imdb_id)

        if episode.series_id != series.id:
            episode.series = series
            updated = True

        if episode.season_number is None and provider_episode.season_number is not None:
            episode.season_number = provider_episode.season_number
            updated = True

        if episode.episode_number is None and provider_episode.episode_number is not None:
            episode.episode_number = provider_episode.episode_number
            updated = True

        if updated:
            episode.save()

    return episode, created, updated


def _category_name(integration: MediaServerIntegration, source_category: str) -> str:
    category = (source_category or UNCATEGORIZED_NAME).strip() or UNCATEGORIZED_NAME
    composite_name = f'{integration.name} - {category}'
    return composite_name[:255]


def _ensure_category(
    integration: MediaServerIntegration,
    account: M3UAccount,
    source_category: str,
    *,
    category_type: str,
    cache: dict[str, VODCategory],
) -> VODCategory:
    name = _category_name(integration, source_category)
    cache_key = f'{category_type}:{name}'
    category = cache.get(cache_key)
    if category:
        return category

    category, _ = VODCategory.objects.get_or_create(
        name=name,
        category_type=category_type,
    )
    M3UVODCategoryRelation.objects.get_or_create(
        m3u_account=account,
        category=category,
        defaults={
            'enabled': True,
            'custom_properties': {
                'managed_source': 'media_server',
                'integration_id': integration.id,
            },
        },
    )
    cache[cache_key] = category
    return category


def _movie_relation_custom_properties(
    integration: MediaServerIntegration,
    provider_movie: ProviderMovie,
) -> dict:
    payload = {
        'managed_source': 'media_server',
        'source': 'media_server',
        'integration_id': integration.id,
        'integration_name': integration.name,
        'provider': integration.provider_type,
        'provider_item_id': provider_movie.external_id,
        'provider_library': provider_movie.category_name,
        'poster_url': provider_movie.poster_url,
        'file_path': provider_movie.local_path,
        'file_name': provider_movie.local_file_name,
        'file_size_bytes': provider_movie.local_file_size,
    }
    if _is_http_stream(provider_movie.stream_url):
        payload['direct_source'] = provider_movie.stream_url
    return payload


def _series_relation_custom_properties(
    integration: MediaServerIntegration,
    provider_series: ProviderSeries,
) -> dict:
    return {
        'managed_source': 'media_server',
        'source': 'media_server',
        'integration_id': integration.id,
        'integration_name': integration.name,
        'provider': integration.provider_type,
        'provider_item_id': provider_series.external_id,
        'provider_library': provider_series.category_name,
        'poster_url': provider_series.poster_url,
        'episodes_fetched': True,
        'detailed_fetched': True,
    }


def _episode_relation_custom_properties(
    integration: MediaServerIntegration,
    provider_series: ProviderSeries,
    provider_episode: ProviderEpisode,
) -> dict:
    payload = {
        'managed_source': 'media_server',
        'source': 'media_server',
        'integration_id': integration.id,
        'integration_name': integration.name,
        'provider': integration.provider_type,
        'provider_item_id': provider_episode.external_id,
        'provider_series_item_id': provider_series.external_id,
        'provider_library': provider_series.category_name,
        'poster_url': provider_series.poster_url,
        'file_path': provider_episode.local_path,
        'file_name': provider_episode.local_file_name,
        'file_size_bytes': provider_episode.local_file_size,
    }
    if _is_http_stream(provider_episode.stream_url):
        payload['direct_source'] = provider_episode.stream_url
    return payload


def _delete_orphan_series(series_ids: list[int]) -> None:
    if not series_ids:
        return
    for series in Series.objects.filter(id__in=series_ids):
        if series.m3u_relations.exists():
            continue
        if series.episodes.filter(m3u_relations__isnull=False).exists():
            continue
        series.delete()


def cleanup_integration_vod(integration: MediaServerIntegration) -> None:
    account = integration.vod_account
    if not account:
        return

    movie_ids = list(
        M3UMovieRelation.objects.filter(m3u_account=account).values_list('movie_id', flat=True)
    )
    series_ids = list(
        M3USeriesRelation.objects.filter(m3u_account=account).values_list('series_id', flat=True)
    )
    episode_ids = list(
        M3UEpisodeRelation.objects.filter(m3u_account=account).values_list('episode_id', flat=True)
    )

    account.delete()

    if movie_ids:
        Movie.objects.filter(
            id__in=movie_ids,
            m3u_relations__isnull=True,
        ).delete()

    if episode_ids:
        Episode.objects.filter(
            id__in=episode_ids,
            m3u_relations__isnull=True,
        ).delete()

    _delete_orphan_series(series_ids)


@shared_task(bind=True)
def sync_media_server_integration(self, integration_id: int, sync_run_id: Optional[int] = None):
    try:
        integration = MediaServerIntegration.objects.get(id=integration_id)
    except MediaServerIntegration.DoesNotExist:
        logger.warning('Media server integration %s not found', integration_id)
        return f'Integration {integration_id} not found'

    scan_started = timezone.now()
    ws_state = {'last_sent': 0.0}

    sync_run = None
    if sync_run_id:
        sync_run = (
            MediaServerSyncRun.objects.select_related('integration')
            .filter(id=sync_run_id, integration_id=integration.id)
            .first()
        )
    if not sync_run:
        sync_run = MediaServerSyncRun.objects.create(
            integration=integration,
            status=MediaServerSyncRun.Status.QUEUED,
            summary='Scheduled sync',
            message='Sync queued.',
            stages=_default_sync_stages(),
        )

    if sync_run.status == MediaServerSyncRun.Status.CANCELLED:
        return f'Sync run {sync_run.id} already cancelled'

    sync_run.task_id = getattr(self.request, 'id', '') or sync_run.task_id
    sync_run.status = MediaServerSyncRun.Status.RUNNING
    sync_run.summary = 'Sync running'
    sync_run.message = 'Sync started.'
    sync_run.started_at = scan_started
    sync_run.finished_at = None
    if not isinstance(sync_run.stages, dict) or not sync_run.stages:
        sync_run.stages = _default_sync_stages()
    sync_run.save(
        update_fields=[
            'task_id',
            'status',
            'summary',
            'message',
            'started_at',
            'finished_at',
            'stages',
            'updated_at',
        ]
    )
    _update_sync_stage(sync_run, STAGE_DISCOVERY, status='running', processed=0, total=0)
    _update_sync_stage(sync_run, STAGE_IMPORT, status='pending', processed=0, total=0)
    _update_sync_stage(sync_run, STAGE_CLEANUP, status='pending', processed=0, total=0)
    _broadcast_sync_run_update(sync_run, ws_state, force=True)

    _set_sync_state(
        integration,
        status=MediaServerIntegration.SyncStatus.RUNNING,
        message='Sync started',
    )

    if not integration.add_to_vod:
        message = 'Integration is configured not to add content to VOD.'
        sync_run.status = MediaServerSyncRun.Status.COMPLETED
        sync_run.summary = 'Sync skipped'
        sync_run.message = message
        sync_run.finished_at = timezone.now()
        sync_run.save(update_fields=['status', 'summary', 'message', 'finished_at', 'updated_at'])
        _update_sync_stage(sync_run, STAGE_DISCOVERY, status='completed', processed=0, total=0)
        _update_sync_stage(sync_run, STAGE_IMPORT, status='skipped', processed=0, total=0)
        _update_sync_stage(sync_run, STAGE_CLEANUP, status='skipped', processed=0, total=0)
        _broadcast_sync_run_update(sync_run, ws_state, force=True)
        _set_sync_state(
            integration,
            status=MediaServerIntegration.SyncStatus.SUCCESS,
            message=message,
            update_synced_at=True,
        )
        return message

    if not integration.enabled:
        message = 'Integration is disabled.'
        sync_run.status = MediaServerSyncRun.Status.FAILED
        sync_run.summary = 'Sync failed'
        sync_run.message = message
        sync_run.error_count = 1
        sync_run.finished_at = timezone.now()
        sync_run.save(
            update_fields=[
                'status',
                'summary',
                'message',
                'error_count',
                'finished_at',
                'updated_at',
            ]
        )
        _update_sync_stage(sync_run, STAGE_DISCOVERY, status='failed', processed=0, total=0)
        _update_sync_stage(sync_run, STAGE_IMPORT, status='skipped', processed=0, total=0)
        _update_sync_stage(sync_run, STAGE_CLEANUP, status='skipped', processed=0, total=0)
        _broadcast_sync_run_update(sync_run, ws_state, force=True)
        _set_sync_state(
            integration,
            status=MediaServerIntegration.SyncStatus.ERROR,
            message=message,
        )
        return message

    account = ensure_integration_vod_account(integration)
    category_cache: dict[str, VODCategory] = {}

    created_movies = 0
    updated_movies = 0
    created_movie_relations = 0
    updated_movie_relations = 0
    processed_movies = 0
    skipped_movies = 0

    created_series = 0
    updated_series = 0
    created_series_relations = 0
    updated_series_relations = 0
    processed_series = 0
    skipped_series = 0

    created_episodes = 0
    updated_episodes = 0
    created_episode_relations = 0
    updated_episode_relations = 0
    processed_episodes = 0
    skipped_episodes = 0

    removed_movie_relations = 0
    removed_series_relations = 0
    removed_episode_relations = 0

    cleanup_step = 0
    cleanup_total_steps = 6
    cancel_check_counter = 0
    last_metric_flush = 0.0

    def _metrics_extra() -> dict:
        return {
            'movies': {
                'processed': processed_movies,
                'created': created_movies,
                'updated': updated_movies,
                'relations_created': created_movie_relations,
                'relations_updated': updated_movie_relations,
                'skipped': skipped_movies,
                'relations_removed': removed_movie_relations,
            },
            'series': {
                'processed': processed_series,
                'created': created_series,
                'updated': updated_series,
                'relations_created': created_series_relations,
                'relations_updated': updated_series_relations,
                'skipped': skipped_series,
                'relations_removed': removed_series_relations,
            },
            'episodes': {
                'processed': processed_episodes,
                'created': created_episodes,
                'updated': updated_episodes,
                'relations_created': created_episode_relations,
                'relations_updated': updated_episode_relations,
                'skipped': skipped_episodes,
                'relations_removed': removed_episode_relations,
            },
        }

    def _flush_metrics(
        *,
        force: bool = False,
        stage_status: Optional[str] = None,
    ) -> None:
        nonlocal last_metric_flush
        now = monotonic()
        if not force and now - last_metric_flush < 1.0:
            return
        last_metric_flush = now
        processed_items = processed_movies + processed_series + processed_episodes
        created_items = created_movies + created_series + created_episodes
        updated_items = updated_movies + updated_series + updated_episodes
        skipped_items = skipped_movies + skipped_series + skipped_episodes
        removed_items = (
            removed_movie_relations + removed_series_relations + removed_episode_relations
        )
        total_items = processed_items
        if not force and sync_run.status == MediaServerSyncRun.Status.RUNNING:
            total_items = processed_items + 1 if processed_items > 0 else 0

        _update_sync_metrics(
            sync_run,
            processed_items=processed_items,
            total_items=total_items,
            created_items=created_items,
            updated_items=updated_items,
            removed_items=removed_items,
            skipped_items=skipped_items,
            error_count=sync_run.error_count,
            extra=_metrics_extra(),
        )
        effective_stage_status = stage_status
        if not effective_stage_status:
            if sync_run.status == MediaServerSyncRun.Status.RUNNING:
                effective_stage_status = 'running'
            else:
                effective_stage_status = (
                    (sync_run.stages or {}).get(STAGE_IMPORT, {}).get('status')
                    or 'completed'
                )
        _update_sync_stage(
            sync_run,
            STAGE_IMPORT,
            status=effective_stage_status,
            processed=processed_items,
            total=total_items,
        )
        _broadcast_sync_run_update(sync_run, ws_state, force=force)

    def _check_cancel() -> None:
        nonlocal cancel_check_counter
        cancel_check_counter += 1
        if cancel_check_counter % 25 != 0 and sync_run.status != MediaServerSyncRun.Status.CANCELLED:
            return
        sync_run.refresh_from_db(fields=['status'])
        if sync_run.status == MediaServerSyncRun.Status.CANCELLED:
            raise SyncCancelled('Sync cancelled by user.')

    try:
        with get_provider_client(integration) as client:
            _check_cancel()
            try:
                client.ping()
            except FileNotFoundError as exc:
                if (
                    integration.provider_type
                    == MediaServerIntegration.ProviderTypes.LOCAL
                ):
                    logger.warning(
                        'Local sync continuing with missing path(s) for integration %s: %s',
                        integration.id,
                        exc,
                    )
                else:
                    raise
            libraries = client.list_libraries()

            if integration.selected_library_ids:
                allowed = integration.selected_library_ids
                libraries = [library for library in libraries if library.id in allowed]

            library_total = len(libraries)
            _update_sync_stage(
                sync_run,
                STAGE_DISCOVERY,
                status='completed',
                processed=library_total,
                total=library_total,
            )
            _update_sync_stage(sync_run, STAGE_IMPORT, status='running', processed=0, total=0)
            _broadcast_sync_run_update(sync_run, ws_state, force=True)

            movie_libraries = [
                library for library in libraries if library.content_type in {'movie', 'mixed'}
            ]
            series_libraries = [
                library for library in libraries if library.content_type in {'series', 'mixed'}
            ]

            for provider_movie in client.iter_movies(movie_libraries):
                _check_cancel()
                processed_movies += 1
                if not provider_movie.stream_url and not provider_movie.local_path:
                    skipped_movies += 1
                    _flush_metrics(force=False)
                    continue

                category = _ensure_category(
                    integration,
                    account,
                    provider_movie.category_name,
                    category_type='movie',
                    cache=category_cache,
                )
                movie, created, updated = _sync_movie(provider_movie)
                if created:
                    created_movies += 1
                elif updated:
                    updated_movies += 1

                stream_id = f'{integration.provider_type}:{provider_movie.external_id}'
                _, relation_created = M3UMovieRelation.objects.update_or_create(
                    m3u_account=account,
                    stream_id=stream_id,
                    defaults={
                        'movie': movie,
                        'category': category,
                        'container_extension': provider_movie.container_extension,
                        'custom_properties': _movie_relation_custom_properties(
                            integration, provider_movie
                        ),
                        'last_seen': scan_started,
                    },
                )
                if relation_created:
                    created_movie_relations += 1
                else:
                    updated_movie_relations += 1
                _flush_metrics(force=False)

            for provider_series in client.iter_series(series_libraries):
                _check_cancel()
                processed_series += 1
                if not provider_series.episodes:
                    skipped_series += 1
                    _flush_metrics(force=False)
                    continue

                category = _ensure_category(
                    integration,
                    account,
                    provider_series.category_name,
                    category_type='series',
                    cache=category_cache,
                )
                series, created, updated = _sync_series(provider_series)
                if created:
                    created_series += 1
                elif updated:
                    updated_series += 1

                external_series_id = f'{integration.provider_type}:{provider_series.external_id}'
                _, relation_created = M3USeriesRelation.objects.update_or_create(
                    m3u_account=account,
                    external_series_id=external_series_id,
                    defaults={
                        'series': series,
                        'category': category,
                        'custom_properties': _series_relation_custom_properties(
                            integration, provider_series
                        ),
                        'last_seen': scan_started,
                        'last_episode_refresh': scan_started,
                    },
                )
                if relation_created:
                    created_series_relations += 1
                else:
                    updated_series_relations += 1
                _flush_metrics(force=False)

                for provider_episode in provider_series.episodes:
                    _check_cancel()
                    processed_episodes += 1
                    if not provider_episode.stream_url and not provider_episode.local_path:
                        skipped_episodes += 1
                        _flush_metrics(force=False)
                        continue

                    episode, episode_created, episode_updated = _sync_episode(
                        series,
                        provider_episode,
                    )
                    if episode_created:
                        created_episodes += 1
                    elif episode_updated:
                        updated_episodes += 1

                    episode_stream_id = (
                        f'{integration.provider_type}:{provider_episode.external_id}'
                    )
                    _, episode_relation_created = M3UEpisodeRelation.objects.update_or_create(
                        m3u_account=account,
                        stream_id=episode_stream_id,
                        defaults={
                            'episode': episode,
                            'container_extension': provider_episode.container_extension,
                            'custom_properties': _episode_relation_custom_properties(
                                integration,
                                provider_series,
                                provider_episode,
                            ),
                            'last_seen': scan_started,
                        },
                    )
                    if episode_relation_created:
                        created_episode_relations += 1
                    else:
                        updated_episode_relations += 1
                    _flush_metrics(force=False)

        _flush_metrics(force=True)
        processed_items = processed_movies + processed_series + processed_episodes
        _update_sync_stage(
            sync_run,
            STAGE_IMPORT,
            status='completed',
            processed=processed_items,
            total=processed_items,
        )

        _check_cancel()
        _update_sync_stage(
            sync_run,
            STAGE_CLEANUP,
            status='running',
            processed=cleanup_step,
            total=cleanup_total_steps,
        )
        _broadcast_sync_run_update(sync_run, ws_state, force=True)

        stale_movie_relation_ids = []
        stale_movie_ids = []
        for relation in M3UMovieRelation.objects.filter(
            m3u_account=account,
            last_seen__lt=scan_started,
        ).only('id', 'movie_id', 'custom_properties'):
            stale_movie_relation_ids.append(relation.id)
            stale_movie_ids.append(relation.movie_id)

        stale_series_relation_ids = []
        stale_series_ids = []
        for relation in M3USeriesRelation.objects.filter(
            m3u_account=account,
            last_seen__lt=scan_started,
        ).only('id', 'series_id', 'custom_properties'):
            stale_series_relation_ids.append(relation.id)
            stale_series_ids.append(relation.series_id)

        stale_episode_relation_ids = []
        stale_episode_ids = []
        for relation in M3UEpisodeRelation.objects.filter(
            m3u_account=account,
            last_seen__lt=scan_started,
        ).only('id', 'episode_id', 'custom_properties'):
            stale_episode_relation_ids.append(relation.id)
            stale_episode_ids.append(relation.episode_id)
        cleanup_step += 1
        _update_sync_stage(
            sync_run,
            STAGE_CLEANUP,
            status='running',
            processed=cleanup_step,
            total=cleanup_total_steps,
        )
        _check_cancel()

        if stale_movie_relation_ids:
            removed_movie_relations, _ = M3UMovieRelation.objects.filter(
                id__in=stale_movie_relation_ids
            ).delete()
        cleanup_step += 1
        _update_sync_stage(sync_run, STAGE_CLEANUP, processed=cleanup_step, total=cleanup_total_steps)
        _check_cancel()

        if stale_series_relation_ids:
            removed_series_relations, _ = M3USeriesRelation.objects.filter(
                id__in=stale_series_relation_ids
            ).delete()
        cleanup_step += 1
        _update_sync_stage(sync_run, STAGE_CLEANUP, processed=cleanup_step, total=cleanup_total_steps)
        _check_cancel()

        if stale_episode_relation_ids:
            removed_episode_relations, _ = M3UEpisodeRelation.objects.filter(
                id__in=stale_episode_relation_ids
            ).delete()
        cleanup_step += 1
        _update_sync_stage(sync_run, STAGE_CLEANUP, processed=cleanup_step, total=cleanup_total_steps)
        _check_cancel()

        if stale_movie_ids:
            Movie.objects.filter(
                id__in=stale_movie_ids,
                m3u_relations__isnull=True,
            ).delete()
        cleanup_step += 1
        _update_sync_stage(sync_run, STAGE_CLEANUP, processed=cleanup_step, total=cleanup_total_steps)
        _check_cancel()

        if stale_episode_ids:
            Episode.objects.filter(
                id__in=stale_episode_ids,
                m3u_relations__isnull=True,
            ).delete()

        _delete_orphan_series(stale_series_ids)
        cleanup_step += 1
        _update_sync_stage(
            sync_run,
            STAGE_CLEANUP,
            status='completed',
            processed=cleanup_step,
            total=cleanup_total_steps,
        )

        summary = (
            f'Movies: {processed_movies} processed '
            f'({created_movies} created, {updated_movies} updated, {skipped_movies} skipped). '
            f'Movie relations: {created_movie_relations} created, '
            f'{updated_movie_relations} updated, {removed_movie_relations} removed. '
            f'Series: {processed_series} processed '
            f'({created_series} created, {updated_series} updated, {skipped_series} skipped). '
            f'Series relations: {created_series_relations} created, '
            f'{updated_series_relations} updated, {removed_series_relations} removed. '
            f'Episodes: {processed_episodes} processed '
            f'({created_episodes} created, {updated_episodes} updated, {skipped_episodes} skipped). '
            f'Episode relations: {created_episode_relations} created, '
            f'{updated_episode_relations} updated, {removed_episode_relations} removed.'
        )

        processed_items = processed_movies + processed_series + processed_episodes
        created_items = created_movies + created_series + created_episodes
        updated_items = updated_movies + updated_series + updated_episodes
        skipped_items = skipped_movies + skipped_series + skipped_episodes
        removed_items = (
            removed_movie_relations + removed_series_relations + removed_episode_relations
        )
        _update_sync_metrics(
            sync_run,
            processed_items=processed_items,
            total_items=processed_items,
            created_items=created_items,
            updated_items=updated_items,
            removed_items=removed_items,
            skipped_items=skipped_items,
            error_count=sync_run.error_count,
            extra=_metrics_extra(),
        )

        sync_run.status = MediaServerSyncRun.Status.COMPLETED
        sync_run.summary = 'Sync completed'
        sync_run.message = summary
        sync_run.finished_at = timezone.now()
        sync_run.save(update_fields=['status', 'summary', 'message', 'finished_at', 'updated_at'])
        _broadcast_sync_run_update(sync_run, ws_state, force=True)

        _set_sync_state(
            integration,
            status=MediaServerIntegration.SyncStatus.SUCCESS,
            message=summary,
            update_synced_at=True,
        )
        return summary
    except SyncCancelled as exc:
        logger.info(
            'Media server sync cancelled for integration %s (%s)',
            integration.id,
            integration.name,
        )
        stages = sync_run.stages or {}
        for stage_key in (STAGE_DISCOVERY, STAGE_IMPORT, STAGE_CLEANUP):
            stage = stages.get(stage_key) or {'status': 'pending', 'processed': 0, 'total': 0}
            current_status = str(stage.get('status') or 'pending')
            if current_status == 'pending':
                stage['status'] = 'skipped'
            elif current_status == 'running':
                stage['status'] = 'cancelled'
            stages[stage_key] = stage
        sync_run.stages = stages
        sync_run.status = MediaServerSyncRun.Status.CANCELLED
        sync_run.summary = 'Sync cancelled'
        sync_run.message = str(exc)
        sync_run.finished_at = timezone.now()
        sync_run.save(update_fields=['stages', 'status', 'summary', 'message', 'finished_at', 'updated_at'])
        _flush_metrics(force=True, stage_status='cancelled')
        _broadcast_sync_run_update(sync_run, ws_state, force=True)

        _set_sync_state(
            integration,
            status=MediaServerIntegration.SyncStatus.ERROR,
            message='Sync cancelled by user.',
        )
        return 'Sync cancelled by user.'
    except Exception as exc:
        logger.exception(
            'Media server sync failed for integration %s (%s)',
            integration.id,
            integration.name,
        )
        stages = sync_run.stages or {}
        for stage_key in (STAGE_DISCOVERY, STAGE_IMPORT, STAGE_CLEANUP):
            stage = stages.get(stage_key) or {'status': 'pending', 'processed': 0, 'total': 0}
            current_status = str(stage.get('status') or 'pending')
            if current_status == 'running':
                stage['status'] = 'failed'
            elif current_status == 'pending':
                stage['status'] = 'skipped'
            stages[stage_key] = stage
        sync_run.stages = stages
        sync_run.status = MediaServerSyncRun.Status.FAILED
        sync_run.summary = 'Sync failed'
        sync_run.message = f'Sync failed: {exc}'
        sync_run.error_count = (sync_run.error_count or 0) + 1
        sync_run.finished_at = timezone.now()
        sync_run.save(
            update_fields=[
                'stages',
                'status',
                'summary',
                'message',
                'error_count',
                'finished_at',
                'updated_at',
            ]
        )
        _flush_metrics(force=True, stage_status='failed')
        _broadcast_sync_run_update(sync_run, ws_state, force=True)

        _set_sync_state(
            integration,
            status=MediaServerIntegration.SyncStatus.ERROR,
            message=f'Sync failed: {exc}',
        )
        return f'Sync failed: {exc}'
