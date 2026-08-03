from __future__ import annotations

import hashlib
import logging
import os
import shutil
from datetime import date
from pathlib import Path
from time import monotonic
from typing import Any, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests
from celery import shared_task
from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.m3u.models import M3UAccount
from apps.media_servers.models import MediaServerIntegration, MediaServerSyncRun
from apps.media_servers.path_security import resolve_import_path
from apps.media_servers.providers import (
    MediaProviderSession,
    ProviderEpisode,
    ProviderLibrary,
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
from core.utils import (
    RedisClient,
    send_websocket_update,
)

logger = logging.getLogger(__name__)

MEDIA_SERVER_ACCOUNT_PREFIX = 'Media Library'
MEDIA_SERVER_ACCOUNT_PRIORITY = 1000
UNCATEGORIZED_NAME = 'Uncategorized'
STAGE_DISCOVERY = 'discovery'
STAGE_IMPORT = 'import'
STAGE_CLEANUP = 'cleanup'
SYNC_WS_UPDATE_INTERVAL_SECONDS = 1.0


class SyncCancelled(Exception):
    pass


class AmbiguousContentMatch(Exception):
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
        'source': sync_run.integration_id,
        'integration': sync_run.integration_id,
        'integration_name': sync_run.integration.name,
        'provider_type': sync_run.integration.provider_type,
        'status': sync_run.status,
        'summary': sync_run.summary,
        'stages': sync_run.stages or {},
        'scope_results': sync_run.scope_results or {},
        'processed_items': sync_run.processed_items,
        'total_items': sync_run.total_items,
        'created_items': sync_run.created_items,
        'updated_items': sync_run.updated_items,
        'removed_items': sync_run.removed_items,
        'skipped_items': sync_run.skipped_items,
        'ambiguous_items': sync_run.ambiguous_items,
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
        {'type': 'media_library_import_updated', 'sync_run': _sync_run_payload(sync_run)},
    )


def _update_sync_stage(
    sync_run: MediaServerSyncRun,
    stage_key: str,
    *,
    status: Optional[str] = None,
    processed: Optional[int] = None,
    total: Optional[int] = None,
) -> None:
    stages = dict(sync_run.stages or {})
    stage = dict(stages.get(stage_key) or {'status': 'pending', 'processed': 0, 'total': 0})
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
    ambiguous_items: int,
    error_count: int,
    extra: Optional[dict] = None,
) -> None:
    sync_run.processed_items = processed_items
    sync_run.total_items = total_items
    sync_run.created_items = created_items
    sync_run.updated_items = updated_items
    sync_run.removed_items = removed_items
    sync_run.skipped_items = skipped_items
    sync_run.ambiguous_items = ambiguous_items
    sync_run.error_count = error_count
    if extra is not None:
        sync_run.extra = extra
    sync_run.save(
        update_fields=[
            'processed_items', 'total_items', 'created_items', 'updated_items',
            'removed_items', 'skipped_items', 'ambiguous_items', 'error_count',
            'extra', 'updated_at',
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
    fields = ['last_sync_status', 'last_sync_message', 'updated_at']
    if update_synced_at:
        integration.last_synced_at = timezone.now()
        fields.append('last_synced_at')
    integration.save(update_fields=fields)


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


def _assert_identifiers_compatible(obj, *, tmdb_id, imdb_id) -> None:
    for field, incoming in (('tmdb_id', tmdb_id), ('imdb_id', imdb_id)):
        current = _normalize_external_id(getattr(obj, field, None))
        if current and incoming and current != incoming:
            raise AmbiguousContentMatch(
                f'Existing provider relation has a conflicting {field} value'
            )


def _set_if_blank(obj, field: str, value) -> bool:
    if value in (None, '', [], {}):
        return False
    current = getattr(obj, field)
    if current in (None, '', [], {}):
        setattr(obj, field, value)
        return True
    return False


def _first_if_unique(queryset, *, description: str = 'content'):
    matches = list(queryset[:2])
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise AmbiguousContentMatch(f'Multiple {description} candidates matched')
    return None


def _pick_best_name_year_match(queryset):
    return _first_if_unique(queryset, description='title/year')


def _artwork_headers(
    integration: MediaServerIntegration,
    source_url: str,
) -> dict[str, str]:
    if not integration.api_token:
        return {}
    provider_origin = urlsplit(integration.base_url)
    artwork_origin = urlsplit(source_url)
    if (
        provider_origin.scheme != artwork_origin.scheme
        or provider_origin.netloc != artwork_origin.netloc
    ):
        return {}
    if integration.provider_type == MediaServerIntegration.ProviderTypes.PLEX:
        return {'X-Plex-Token': integration.api_token}
    if integration.provider_type in {
        MediaServerIntegration.ProviderTypes.EMBY,
        MediaServerIntegration.ProviderTypes.JELLYFIN,
    }:
        return {'X-Emby-Token': integration.api_token}
    return {}


def _cache_artwork(
    integration: MediaServerIntegration,
    source: str,
) -> Optional[str]:
    source = str(source or '').strip()
    if not source:
        return None

    artwork_root = Path(settings.MEDIA_LIBRARY_ARTWORK_ROOT).resolve()
    artwork_root.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(
        f'{integration.id}:{source}'.encode('utf-8')
    ).hexdigest()
    temporary = artwork_root / f'.{digest}.tmp'

    try:
        if _is_http_stream(source):
            with MediaProviderSession() as session:
                with session.get(
                    source,
                    headers=_artwork_headers(integration, source),
                    timeout=(10, 30),
                    verify=integration.verify_ssl,
                    stream=True,
                ) as response:
                    response.raise_for_status()
                    content_type = str(
                        response.headers.get('Content-Type') or ''
                    ).lower()
                    extension = '.png' if 'png' in content_type else '.jpg'
                    destination = artwork_root / f'{digest}{extension}'
                    total = 0
                    with temporary.open('wb') as output:
                        for chunk in response.iter_content(64 * 1024):
                            if not chunk:
                                continue
                            total += len(chunk)
                            if total > 20 * 1024 * 1024:
                                raise ValueError('Artwork exceeds the 20 MiB limit')
                            output.write(chunk)
            os.replace(temporary, destination)
            return str(destination)

        resolved = resolve_import_path(source, must_exist=True, require_directory=False)
        extension = resolved.suffix.lower()
        if extension not in {'.jpg', '.jpeg', '.png', '.webp'}:
            extension = '.jpg'
        destination = artwork_root / f'{digest}{extension}'
        shutil.copy2(resolved, temporary)
        os.replace(temporary, destination)
        return str(destination)
    except (OSError, ValueError, requests.RequestException):
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            logger.warning(
                'Unable to remove temporary artwork for media library source %s',
                integration.id,
            )
        logger.warning(
            'Unable to cache artwork for media library source %s',
            integration.id,
        )
        return None


def _ensure_logo(
    integration: MediaServerIntegration,
    *,
    title: str,
    poster_url: str,
) -> Optional[VODLogo]:
    url = _cache_artwork(integration, poster_url)
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

    tmdb_match = (
        _first_if_unique(
            Movie.objects.filter(tmdb_id=tmdb_id),
            description='movie TMDB ID',
        )
        if tmdb_id else None
    )
    imdb_match = (
        _first_if_unique(
            Movie.objects.filter(imdb_id=imdb_id),
            description='movie IMDb ID',
        )
        if imdb_id else None
    )
    if tmdb_match and imdb_match and tmdb_match.pk != imdb_match.pk:
        raise AmbiguousContentMatch('TMDB and IMDb identifiers matched different movies')
    if tmdb_match or imdb_match:
        return tmdb_match or imdb_match
    if tmdb_id or imdb_id:
        return None

    if provider_movie.title and provider_movie.year:
        name_year_matches = Movie.objects.filter(
            name__iexact=provider_movie.title,
            year=provider_movie.year,
        )
        return _pick_best_name_year_match(name_year_matches)

    return None


def _sync_movie(
    integration: MediaServerIntegration,
    provider_movie: ProviderMovie,
    *,
    existing: Optional[Movie] = None,
) -> tuple[Movie, bool, bool]:
    tmdb_id = _normalize_external_id(provider_movie.tmdb_id)
    imdb_id = _normalize_external_id(provider_movie.imdb_id)
    if existing:
        _assert_identifiers_compatible(
            existing,
            tmdb_id=tmdb_id,
            imdb_id=imdb_id,
        )
    logo = _ensure_logo(
        integration,
        title=provider_movie.title,
        poster_url=provider_movie.poster_url,
    )

    movie = existing or _find_existing_movie(provider_movie)
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

    tmdb_match = (
        _first_if_unique(
            Series.objects.filter(tmdb_id=tmdb_id),
            description='series TMDB ID',
        )
        if tmdb_id else None
    )
    imdb_match = (
        _first_if_unique(
            Series.objects.filter(imdb_id=imdb_id),
            description='series IMDb ID',
        )
        if imdb_id else None
    )
    if tmdb_match and imdb_match and tmdb_match.pk != imdb_match.pk:
        raise AmbiguousContentMatch('TMDB and IMDb identifiers matched different series')
    if tmdb_match or imdb_match:
        return tmdb_match or imdb_match
    if tmdb_id or imdb_id:
        return None

    if provider_series.title and provider_series.year:
        name_year_matches = Series.objects.filter(
            name__iexact=provider_series.title,
            year=provider_series.year,
        )
        return _pick_best_name_year_match(name_year_matches)

    return None


def _sync_series(
    integration: MediaServerIntegration,
    provider_series: ProviderSeries,
    *,
    existing: Optional[Series] = None,
) -> tuple[Series, bool, bool]:
    tmdb_id = _normalize_external_id(provider_series.tmdb_id)
    imdb_id = _normalize_external_id(provider_series.imdb_id)
    if existing:
        _assert_identifiers_compatible(
            existing,
            tmdb_id=tmdb_id,
            imdb_id=imdb_id,
        )
    logo = _ensure_logo(
        integration,
        title=provider_series.title,
        poster_url=provider_series.poster_url,
    )

    series = existing or _find_existing_series(provider_series)
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

    tmdb_match = (
        _first_if_unique(
            Episode.objects.filter(tmdb_id=tmdb_id),
            description='episode TMDB ID',
        )
        if tmdb_id else None
    )
    imdb_match = (
        _first_if_unique(
            Episode.objects.filter(imdb_id=imdb_id),
            description='episode IMDb ID',
        )
        if imdb_id else None
    )
    if tmdb_match and imdb_match and tmdb_match.pk != imdb_match.pk:
        raise AmbiguousContentMatch(
            'TMDB and IMDb identifiers matched different episodes'
        )
    if tmdb_match or imdb_match:
        return tmdb_match or imdb_match
    if tmdb_id or imdb_id:
        return None

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
        return _first_if_unique(
            Episode.objects.filter(series=series, name__iexact=title),
            description='episode title',
        )

    return None


def _sync_episode(
    series: Series,
    provider_episode: ProviderEpisode,
    *,
    existing: Optional[Episode] = None,
) -> tuple[Episode, bool, bool]:
    tmdb_id = _normalize_external_id(provider_episode.tmdb_id)
    imdb_id = _normalize_external_id(provider_episode.imdb_id)

    if existing:
        _assert_identifiers_compatible(
            existing,
            tmdb_id=tmdb_id,
            imdb_id=imdb_id,
        )
    episode = existing or _find_existing_episode(series, provider_episode)
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


def _sanitize_source_url(url: str) -> str:
    value = str(url or '').strip()
    if not _is_http_stream(value):
        return ''
    split = urlsplit(value)
    blocked = {
        'access_token', 'api_key', 'apikey', 'auth', 'password', 'token',
        'x-emby-token', 'x-plex-token',
    }
    query = [
        (key, value)
        for key, value in parse_qsl(split.query, keep_blank_values=True)
        if key.lower() not in blocked
    ]
    return urlunsplit((split.scheme, split.netloc, split.path, urlencode(query), ''))


def _movie_relation_custom_properties(
    integration: MediaServerIntegration,
    provider_movie: ProviderMovie,
    *,
    logo: Optional[VODLogo] = None,
) -> dict:
    payload = {
        'managed_source': 'media_server',
        'source': 'media_server',
        'integration_id': integration.id,
        'integration_name': integration.name,
        'provider': integration.provider_type,
        'provider_item_id': provider_movie.external_id,
        'provider_library': provider_movie.category_name,
        'provider_library_id': provider_movie.library_id,
        'poster_logo_id': getattr(logo, 'id', None),
        'file_path': provider_movie.local_path,
        'file_name': provider_movie.local_file_name,
        'file_size_bytes': provider_movie.local_file_size,
    }
    source_url = _sanitize_source_url(provider_movie.stream_url)
    if source_url:
        payload['source_url'] = source_url
    return payload


def _series_relation_custom_properties(
    integration: MediaServerIntegration,
    provider_series: ProviderSeries,
    *,
    logo: Optional[VODLogo] = None,
) -> dict:
    return {
        'managed_source': 'media_server',
        'source': 'media_server',
        'integration_id': integration.id,
        'integration_name': integration.name,
        'provider': integration.provider_type,
        'provider_item_id': provider_series.external_id,
        'provider_library': provider_series.category_name,
        'provider_library_id': provider_series.library_id,
        'poster_logo_id': getattr(logo, 'id', None),
        'episodes_fetched': True,
        'detailed_fetched': True,
    }


def _episode_relation_custom_properties(
    integration: MediaServerIntegration,
    provider_series: ProviderSeries,
    provider_episode: ProviderEpisode,
    *,
    logo: Optional[VODLogo] = None,
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
        'provider_library_id': provider_episode.library_id or provider_series.library_id,
        'poster_logo_id': getattr(logo, 'id', None),
        'file_path': provider_episode.local_path,
        'file_name': provider_episode.local_file_name,
        'file_size_bytes': provider_episode.local_file_size,
    }
    source_url = _sanitize_source_url(provider_episode.stream_url)
    if source_url:
        payload['source_url'] = source_url
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


def _delete_unused_categories(category_ids: list[int]) -> None:
    for category in VODCategory.objects.filter(id__in=category_ids):
        if category.m3u_relations.exists():
            continue
        if M3UMovieRelation.objects.filter(category=category).exists():
            continue
        if M3USeriesRelation.objects.filter(category=category).exists():
            continue
        category.delete()


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
    category_ids = list(
        M3UVODCategoryRelation.objects.filter(
            m3u_account=account
        ).values_list('category_id', flat=True)
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
    _delete_unused_categories(category_ids)

def _remove_stale_relations(
    account: M3UAccount,
    *,
    scan_started,
    authoritative_library_ids: set[str],
) -> dict[str, int]:
    common = {
        'm3u_account': account,
        'last_seen__lt': scan_started,
        'custom_properties__provider_library_id__in': sorted(authoritative_library_ids),
    }
    movie_relations = list(
        M3UMovieRelation.objects.filter(**common).values_list('id', 'movie_id')
    )
    series_relations = list(
        M3USeriesRelation.objects.filter(**common).values_list('id', 'series_id')
    )
    episode_relations = list(
        M3UEpisodeRelation.objects.filter(**common).values_list('id', 'episode_id')
    )

    movie_ids = [row[1] for row in movie_relations]
    series_ids = [row[1] for row in series_relations]
    episode_ids = [row[1] for row in episode_relations]

    if episode_relations:
        M3UEpisodeRelation.objects.filter(id__in=[row[0] for row in episode_relations]).delete()
    if movie_relations:
        M3UMovieRelation.objects.filter(id__in=[row[0] for row in movie_relations]).delete()
    if series_relations:
        M3USeriesRelation.objects.filter(id__in=[row[0] for row in series_relations]).delete()

    if movie_ids:
        Movie.objects.filter(id__in=movie_ids, m3u_relations__isnull=True).delete()
    if episode_ids:
        Episode.objects.filter(id__in=episode_ids, m3u_relations__isnull=True).delete()
    _delete_orphan_series(series_ids)

    unused_category_relations = []
    for category_relation in M3UVODCategoryRelation.objects.filter(
        m3u_account=account
    ).select_related('category'):
        category = category_relation.category
        if M3UMovieRelation.objects.filter(
            m3u_account=account,
            category=category,
        ).exists():
            continue
        if M3USeriesRelation.objects.filter(
            m3u_account=account,
            category=category,
        ).exists():
            continue
        unused_category_relations.append(
            (category_relation.id, category.id)
        )
    if unused_category_relations:
        M3UVODCategoryRelation.objects.filter(
            id__in=[row[0] for row in unused_category_relations]
        ).delete()
        _delete_unused_categories(
            [row[1] for row in unused_category_relations]
        )

    return {
        'movies': len(movie_relations),
        'series': len(series_relations),
        'episodes': len(episode_relations),
    }


def _mark_remaining_stages(sync_run: MediaServerSyncRun, status: str) -> None:
    stages = dict(sync_run.stages or _default_sync_stages())
    for key in (STAGE_DISCOVERY, STAGE_IMPORT, STAGE_CLEANUP):
        stage = dict(stages.get(key) or {'status': 'pending', 'processed': 0, 'total': 0})
        if stage['status'] == 'running':
            stage['status'] = status
        elif stage['status'] == 'pending':
            stage['status'] = 'skipped'
        stages[key] = stage
    sync_run.stages = stages


@shared_task(bind=True)
def sync_media_server_integration(
    self,
    integration_id: int,
    sync_run_id: Optional[int] = None,
):
    integration = (
        MediaServerIntegration.objects.filter(id=integration_id).first()
    )
    if not integration:
        logger.warning('Media library source %s no longer exists', integration_id)
        return f'Source {integration_id} not found'

    sync_run = None
    if sync_run_id:
        sync_run = MediaServerSyncRun.objects.filter(
            id=sync_run_id,
            integration=integration,
        ).first()
    if not sync_run:
        try:
            sync_run = MediaServerSyncRun.objects.create(
                integration=integration,
                status=MediaServerSyncRun.Status.QUEUED,
                summary='Scheduled import',
                message='Import queued.',
                stages=_default_sync_stages(),
            )
        except IntegrityError:
            active = MediaServerSyncRun.objects.filter(
                integration=integration,
                status__in=('pending', 'queued', 'running'),
            ).order_by('-created_at').first()
            return f'Import already active ({active.id if active else "unknown"})'

    if sync_run.status == MediaServerSyncRun.Status.CANCELLED:
        return f'Import run {sync_run.id} was cancelled before starting'

    redis_lock = RedisClient.get_client().lock(
        f'media_library_import:{integration.id}',
        timeout=24 * 60 * 60,
        blocking_timeout=0,
    )
    if not redis_lock.acquire(blocking=False):
        if sync_run.status != MediaServerSyncRun.Status.RUNNING:
            sync_run.status = MediaServerSyncRun.Status.FAILED
            sync_run.summary = 'Import not started'
            sync_run.message = 'Another import is already running for this source.'
            sync_run.error_count = 1
            sync_run.finished_at = timezone.now()
            sync_run.save()
        return sync_run.message

    scan_started = timezone.now()
    ws_state = {'last_sent': 0.0}
    last_lock_refresh = monotonic()
    counts = {
        'movies_processed': 0, 'movies_created': 0, 'movies_updated': 0,
        'movie_relations_created': 0, 'movie_relations_updated': 0,
        'series_processed': 0, 'series_created': 0, 'series_updated': 0,
        'series_relations_created': 0, 'series_relations_updated': 0,
        'episodes_processed': 0, 'episodes_created': 0, 'episodes_updated': 0,
        'episode_relations_created': 0, 'episode_relations_updated': 0,
        'skipped': 0, 'ambiguous': 0, 'errors': 0,
        'removed_movies': 0, 'removed_series': 0, 'removed_episodes': 0,
    }
    last_flush = 0.0

    def totals() -> tuple[int, int, int, int, int]:
        processed = (
            counts['movies_processed'] + counts['series_processed']
            + counts['episodes_processed']
        )
        created = (
            counts['movies_created'] + counts['series_created']
            + counts['episodes_created']
        )
        updated = (
            counts['movies_updated'] + counts['series_updated']
            + counts['episodes_updated']
        )
        removed = (
            counts['removed_movies'] + counts['removed_series']
            + counts['removed_episodes']
        )
        return processed, created, updated, removed, counts['skipped']

    def flush(*, force: bool = False) -> None:
        nonlocal last_flush
        now = monotonic()
        if not force and now - last_flush < 1.0:
            return
        last_flush = now
        processed, created, updated, removed, skipped = totals()
        _update_sync_metrics(
            sync_run,
            processed_items=processed,
            total_items=processed,
            created_items=created,
            updated_items=updated,
            removed_items=removed,
            skipped_items=skipped,
            ambiguous_items=counts['ambiguous'],
            error_count=counts['errors'],
            extra={'counts': counts},
        )
        _update_sync_stage(
            sync_run,
            STAGE_IMPORT,
            status='running',
            processed=processed,
            total=processed,
        )
        _broadcast_sync_run_update(sync_run, ws_state, force=force)

    def check_cancel() -> None:
        nonlocal last_lock_refresh
        now = monotonic()
        if now - last_lock_refresh >= 300:
            try:
                redis_lock.extend(24 * 60 * 60, replace_ttl=True)
            except Exception as exc:
                raise RuntimeError(
                    'The distributed import lock was lost.'
                ) from exc
            last_lock_refresh = now
        sync_run.refresh_from_db(fields=['status', 'cancellation_requested_at'])
        if (
            sync_run.status == MediaServerSyncRun.Status.CANCELLED
            or sync_run.cancellation_requested_at
        ):
            raise SyncCancelled('Import cancelled by administrator.')

    try:
        sync_run.task_id = getattr(self.request, 'id', '') or sync_run.task_id
        sync_run.status = MediaServerSyncRun.Status.RUNNING
        sync_run.summary = 'Import running'
        sync_run.message = 'Discovering configured libraries.'
        sync_run.started_at = scan_started
        sync_run.finished_at = None
        sync_run.stages = _default_sync_stages()
        sync_run.save()
        _update_sync_stage(sync_run, STAGE_DISCOVERY, status='running')
        _set_sync_state(
            integration,
            status=MediaServerIntegration.SyncStatus.RUNNING,
            message='Import started.',
        )
        _broadcast_sync_run_update(sync_run, ws_state, force=True)

        if not integration.enabled:
            raise ValueError('Media library source is disabled.')
        if not integration.add_to_vod:
            raise ValueError('Media library source is not configured to add content to VOD.')

        account = ensure_integration_vod_account(integration)
        category_cache: dict[str, VODCategory] = {}

        with get_provider_client(integration) as client:
            check_cancel()
            client.ping()
            if not integration.api_token and getattr(client, 'api_token', ''):
                # Emby/Jellyfin username authentication returns a reusable
                # server token. Persist it server-side so later proxy workers
                # can authenticate without passing credentials through Celery.
                integration.api_token = client.api_token
                integration.save(update_fields=['api_token', 'updated_at'])
            available_libraries = client.list_libraries()
            available_by_id = {library.id: library for library in available_libraries}
            requested_ids = integration.selected_library_ids
            if requested_ids:
                missing_ids = sorted(requested_ids - set(available_by_id))
                if missing_ids:
                    raise ValueError(
                        'Configured library locations are unavailable: '
                        + ', '.join(missing_ids)
                    )
                libraries = [available_by_id[value] for value in sorted(requested_ids)]
            else:
                libraries = available_libraries

            libraries = [
                ProviderLibrary(
                    id=library.id,
                    name=library.name,
                    content_type=integration.content_type_for_library(
                        library.id,
                        library.content_type,
                    ),
                )
                for library in libraries
            ]

            if not libraries:
                raise ValueError('No supported libraries are configured for this source.')

            authoritative_ids = {library.id for library in libraries}
            sync_run.scope_results = {
                library.id: {
                    'name': library.name,
                    'content_type': library.content_type,
                    'status': 'running',
                }
                for library in libraries
            }
            sync_run.save(update_fields=['scope_results', 'updated_at'])
            _update_sync_stage(
                sync_run,
                STAGE_DISCOVERY,
                status='completed',
                processed=len(libraries),
                total=len(libraries),
            )
            _update_sync_stage(sync_run, STAGE_IMPORT, status='running')
            _broadcast_sync_run_update(sync_run, ws_state, force=True)

            movie_libraries = [
                library for library in libraries
                if library.content_type in {'movie', 'mixed'}
            ]
            series_libraries = [
                library for library in libraries
                if library.content_type in {'series', 'mixed'}
            ]

            for provider_movie in client.iter_movies(movie_libraries):
                check_cancel()
                counts['movies_processed'] += 1
                if not provider_movie.stream_url and not provider_movie.local_path:
                    counts['skipped'] += 1
                    flush()
                    continue
                stream_id = f'{integration.provider_type}:{provider_movie.external_id}'
                try:
                    with transaction.atomic():
                        existing_relation = M3UMovieRelation.objects.filter(
                            m3u_account=account,
                            stream_id=stream_id,
                        ).select_related('movie').first()
                        category = _ensure_category(
                            integration,
                            account,
                            provider_movie.category_name,
                            category_type='movie',
                            cache=category_cache,
                        )
                        movie, created, updated = _sync_movie(
                            integration,
                            provider_movie,
                            existing=existing_relation.movie if existing_relation else None,
                        )
                        if created:
                            counts['movies_created'] += 1
                        elif updated:
                            counts['movies_updated'] += 1
                        _, relation_created = M3UMovieRelation.objects.update_or_create(
                            m3u_account=account,
                            stream_id=stream_id,
                            defaults={
                                'movie': movie,
                                'category': category,
                                'container_extension': provider_movie.container_extension,
                                'custom_properties': _movie_relation_custom_properties(
                                    integration, provider_movie, logo=movie.logo
                                ),
                                'last_advanced_refresh': scan_started,
                                'last_seen': scan_started,
                            },
                        )
                        counts[
                            'movie_relations_created' if relation_created
                            else 'movie_relations_updated'
                        ] += 1
                except AmbiguousContentMatch:
                    counts['ambiguous'] += 1
                    counts['skipped'] += 1
                except Exception:
                    counts['errors'] += 1
                    logger.exception(
                        'Movie import failed for source %s item %s',
                        integration.id,
                        provider_movie.external_id,
                    )
                flush()

            for provider_series in client.iter_series(series_libraries):
                check_cancel()
                counts['series_processed'] += 1
                if not provider_series.episodes:
                    counts['skipped'] += 1
                    flush()
                    continue
                series_stream_id = (
                    f'{integration.provider_type}:{provider_series.external_id}'
                )
                try:
                    with transaction.atomic():
                        existing_series_relation = M3USeriesRelation.objects.filter(
                            m3u_account=account,
                            external_series_id=series_stream_id,
                        ).select_related('series').first()
                        category = _ensure_category(
                            integration,
                            account,
                            provider_series.category_name,
                            category_type='series',
                            cache=category_cache,
                        )
                        series, created, updated = _sync_series(
                            integration,
                            provider_series,
                            existing=(
                                existing_series_relation.series
                                if existing_series_relation else None
                            ),
                        )
                        if created:
                            counts['series_created'] += 1
                        elif updated:
                            counts['series_updated'] += 1
                        series_relation, relation_created = (
                            M3USeriesRelation.objects.update_or_create(
                                m3u_account=account,
                                external_series_id=series_stream_id,
                                defaults={
                                    'series': series,
                                    'category': category,
                                    'custom_properties': (
                                        _series_relation_custom_properties(
                                            integration,
                                            provider_series,
                                            logo=series.logo,
                                        )
                                    ),
                                    'last_seen': scan_started,
                                    'last_episode_refresh': scan_started,
                                },
                            )
                        )
                        counts[
                            'series_relations_created' if relation_created
                            else 'series_relations_updated'
                        ] += 1
                except AmbiguousContentMatch:
                    counts['ambiguous'] += 1
                    counts['skipped'] += 1
                    continue
                except Exception:
                    counts['errors'] += 1
                    logger.exception(
                        'Series import failed for source %s item %s',
                        integration.id,
                        provider_series.external_id,
                    )
                    continue

                for provider_episode in provider_series.episodes:
                    check_cancel()
                    counts['episodes_processed'] += 1
                    if not provider_episode.stream_url and not provider_episode.local_path:
                        counts['skipped'] += 1
                        flush()
                        continue
                    episode_stream_id = (
                        f'{integration.provider_type}:{provider_episode.external_id}'
                    )
                    try:
                        with transaction.atomic():
                            existing_episode_relation = (
                                M3UEpisodeRelation.objects.filter(
                                    m3u_account=account,
                                    stream_id=episode_stream_id,
                                ).select_related('episode').first()
                            )
                            episode, created, updated = _sync_episode(
                                series,
                                provider_episode,
                                existing=(
                                    existing_episode_relation.episode
                                    if existing_episode_relation else None
                                ),
                            )
                            if created:
                                counts['episodes_created'] += 1
                            elif updated:
                                counts['episodes_updated'] += 1
                            _, relation_created = (
                                M3UEpisodeRelation.objects.update_or_create(
                                    m3u_account=account,
                                    stream_id=episode_stream_id,
                                    defaults={
                                        'episode': episode,
                                        'series_relation': series_relation,
                                        'container_extension': (
                                            provider_episode.container_extension
                                        ),
                                        'custom_properties': (
                                            _episode_relation_custom_properties(
                                                integration,
                                                provider_series,
                                                provider_episode,
                                                logo=series.logo,
                                            )
                                        ),
                                        'last_seen': scan_started,
                                    },
                                )
                            )
                            counts[
                                'episode_relations_created' if relation_created
                                else 'episode_relations_updated'
                            ] += 1
                    except AmbiguousContentMatch:
                        counts['ambiguous'] += 1
                        counts['skipped'] += 1
                    except Exception:
                        counts['errors'] += 1
                        logger.exception(
                            'Episode import failed for source %s item %s',
                            integration.id,
                            provider_episode.external_id,
                        )
                    flush()

        flush(force=True)
        processed, _, _, _, _ = totals()
        _update_sync_stage(
            sync_run,
            STAGE_IMPORT,
            status='completed' if not counts['errors'] else 'failed',
            processed=processed,
            total=processed,
        )
        if counts['errors']:
            raise RuntimeError(
                f'{counts["errors"]} item(s) failed; stale cleanup was not performed.'
            )

        check_cancel()
        _update_sync_stage(sync_run, STAGE_CLEANUP, status='running', total=3)
        removed = _remove_stale_relations(
            account,
            scan_started=scan_started,
            authoritative_library_ids=authoritative_ids,
        )
        counts['removed_movies'] = removed['movies']
        counts['removed_series'] = removed['series']
        counts['removed_episodes'] = removed['episodes']
        _update_sync_stage(
            sync_run,
            STAGE_CLEANUP,
            status='completed',
            processed=3,
            total=3,
        )

        scopes = dict(sync_run.scope_results or {})
        for scope in scopes.values():
            scope['status'] = 'completed'
            scope['authoritative'] = True
        sync_run.scope_results = scopes
        flush(force=True)

        processed, created, updated, removed_total, skipped = totals()
        summary = (
            f'{processed} items processed; {created} created; {updated} updated; '
            f'{removed_total} stale relations removed; {skipped} skipped; '
            f'{counts["ambiguous"]} ambiguous.'
        )
        sync_run.status = MediaServerSyncRun.Status.COMPLETED
        sync_run.summary = 'Import completed'
        sync_run.message = summary
        sync_run.finished_at = timezone.now()
        sync_run.save()
        _set_sync_state(
            integration,
            status=MediaServerIntegration.SyncStatus.SUCCESS,
            message=summary,
            update_synced_at=True,
        )
        _broadcast_sync_run_update(sync_run, ws_state, force=True)

        from apps.media_servers.export_tasks import queue_automatic_exports
        transaction.on_commit(
            lambda: queue_automatic_exports.delay(f'import:{integration.id}')
        )
        return summary
    except SyncCancelled as exc:
        _mark_remaining_stages(sync_run, 'cancelled')
        scopes = dict(sync_run.scope_results or {})
        for scope in scopes.values():
            if scope.get('status') == 'running':
                scope['status'] = 'cancelled'
                scope['authoritative'] = False
        sync_run.scope_results = scopes
        sync_run.status = MediaServerSyncRun.Status.CANCELLED
        sync_run.summary = 'Import cancelled'
        sync_run.message = str(exc)
        sync_run.finished_at = timezone.now()
        sync_run.save()
        _set_sync_state(
            integration,
            status=MediaServerIntegration.SyncStatus.ERROR,
            message='Import cancelled.',
        )
        _broadcast_sync_run_update(sync_run, ws_state, force=True)
        return str(exc)
    except Exception as exc:
        if isinstance(exc, requests.RequestException):
            failure_message = 'The provider request failed.'
            logger.error(
                'Media library provider request failed for source %s',
                integration.id,
            )
        else:
            failure_message = str(exc)
            logger.exception(
                'Media library import failed for source %s',
                integration.id,
            )
        _mark_remaining_stages(sync_run, 'failed')
        scopes = dict(sync_run.scope_results or {})
        for scope in scopes.values():
            if scope.get('status') == 'running':
                scope['status'] = 'failed'
                scope['authoritative'] = False
        sync_run.scope_results = scopes
        sync_run.status = MediaServerSyncRun.Status.FAILED
        sync_run.summary = 'Import failed'
        sync_run.message = failure_message[:4000]
        sync_run.error_count = max(sync_run.error_count, counts['errors'], 1)
        sync_run.finished_at = timezone.now()
        sync_run.save()
        _set_sync_state(
            integration,
            status=MediaServerIntegration.SyncStatus.ERROR,
            message=failure_message,
        )
        _broadcast_sync_run_update(sync_run, ws_state, force=True)
        raise
    finally:
        try:
            redis_lock.release()
        except Exception:
            logger.warning(
                'Media library import lock for source %s was already released',
                integration.id,
            )
