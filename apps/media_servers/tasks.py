import logging
from datetime import date
from typing import Optional

from celery import shared_task
from django.db import IntegrityError
from django.utils import timezone

from apps.m3u.models import M3UAccount
from apps.media_servers.models import MediaServerIntegration
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

logger = logging.getLogger(__name__)

MEDIA_SERVER_ACCOUNT_PREFIX = 'Media Server'
MEDIA_SERVER_ACCOUNT_PRIORITY = 1000
UNCATEGORIZED_NAME = 'Uncategorized'


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

        if not movie.logo and logo:
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

        if not series.logo and logo:
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
    return {
        'managed_source': 'media_server',
        'source': 'media_server',
        'integration_id': integration.id,
        'integration_name': integration.name,
        'provider': integration.provider_type,
        'provider_item_id': provider_movie.external_id,
        'provider_library': provider_movie.category_name,
        'direct_source': provider_movie.stream_url,
        'poster_url': provider_movie.poster_url,
    }


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
    return {
        'managed_source': 'media_server',
        'source': 'media_server',
        'integration_id': integration.id,
        'integration_name': integration.name,
        'provider': integration.provider_type,
        'provider_item_id': provider_episode.external_id,
        'provider_series_item_id': provider_series.external_id,
        'provider_library': provider_series.category_name,
        'direct_source': provider_episode.stream_url,
        'poster_url': provider_series.poster_url,
    }


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
def sync_media_server_integration(self, integration_id: int):
    try:
        integration = MediaServerIntegration.objects.get(id=integration_id)
    except MediaServerIntegration.DoesNotExist:
        logger.warning('Media server integration %s not found', integration_id)
        return f'Integration {integration_id} not found'

    _set_sync_state(
        integration,
        status=MediaServerIntegration.SyncStatus.RUNNING,
        message='Sync started',
    )

    if not integration.add_to_vod:
        message = 'Integration is configured not to add content to VOD.'
        _set_sync_state(
            integration,
            status=MediaServerIntegration.SyncStatus.SUCCESS,
            message=message,
            update_synced_at=True,
        )
        return message

    if not integration.enabled:
        message = 'Integration is disabled.'
        _set_sync_state(
            integration,
            status=MediaServerIntegration.SyncStatus.ERROR,
            message=message,
        )
        return message

    scan_started = timezone.now()
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

    try:
        with get_provider_client(integration) as client:
            client.ping()
            libraries = client.list_libraries()

            if integration.selected_library_ids:
                allowed = integration.selected_library_ids
                libraries = [library for library in libraries if library.id in allowed]

            movie_libraries = [
                library for library in libraries if library.content_type in {'movie', 'mixed'}
            ]
            series_libraries = [
                library for library in libraries if library.content_type in {'series', 'mixed'}
            ]

            for provider_movie in client.iter_movies(movie_libraries):
                processed_movies += 1
                if not provider_movie.stream_url:
                    skipped_movies += 1
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

            for provider_series in client.iter_series(series_libraries):
                processed_series += 1
                if not provider_series.episodes:
                    skipped_series += 1
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

                for provider_episode in provider_series.episodes:
                    processed_episodes += 1
                    if not provider_episode.stream_url:
                        skipped_episodes += 1
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

        stale_movie_relation_ids = []
        stale_movie_ids = []
        for relation in M3UMovieRelation.objects.filter(
            m3u_account=account,
            last_seen__lt=scan_started,
        ).only('id', 'movie_id', 'custom_properties'):
            custom_props = relation.custom_properties or {}
            if (
                custom_props.get('managed_source') == 'media_server'
                and custom_props.get('integration_id') == integration.id
            ):
                stale_movie_relation_ids.append(relation.id)
                stale_movie_ids.append(relation.movie_id)

        stale_series_relation_ids = []
        stale_series_ids = []
        for relation in M3USeriesRelation.objects.filter(
            m3u_account=account,
            last_seen__lt=scan_started,
        ).only('id', 'series_id', 'custom_properties'):
            custom_props = relation.custom_properties or {}
            if (
                custom_props.get('managed_source') == 'media_server'
                and custom_props.get('integration_id') == integration.id
            ):
                stale_series_relation_ids.append(relation.id)
                stale_series_ids.append(relation.series_id)

        stale_episode_relation_ids = []
        stale_episode_ids = []
        for relation in M3UEpisodeRelation.objects.filter(
            m3u_account=account,
            last_seen__lt=scan_started,
        ).only('id', 'episode_id', 'custom_properties'):
            custom_props = relation.custom_properties or {}
            if (
                custom_props.get('managed_source') == 'media_server'
                and custom_props.get('integration_id') == integration.id
            ):
                stale_episode_relation_ids.append(relation.id)
                stale_episode_ids.append(relation.episode_id)

        removed_movie_relations = 0
        if stale_movie_relation_ids:
            removed_movie_relations, _ = M3UMovieRelation.objects.filter(
                id__in=stale_movie_relation_ids
            ).delete()

        removed_series_relations = 0
        if stale_series_relation_ids:
            removed_series_relations, _ = M3USeriesRelation.objects.filter(
                id__in=stale_series_relation_ids
            ).delete()

        removed_episode_relations = 0
        if stale_episode_relation_ids:
            removed_episode_relations, _ = M3UEpisodeRelation.objects.filter(
                id__in=stale_episode_relation_ids
            ).delete()

        if stale_movie_ids:
            Movie.objects.filter(
                id__in=stale_movie_ids,
                m3u_relations__isnull=True,
            ).delete()

        if stale_episode_ids:
            Episode.objects.filter(
                id__in=stale_episode_ids,
                m3u_relations__isnull=True,
            ).delete()

        _delete_orphan_series(stale_series_ids)

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
        _set_sync_state(
            integration,
            status=MediaServerIntegration.SyncStatus.SUCCESS,
            message=summary,
            update_synced_at=True,
        )
        return summary
    except Exception as exc:
        logger.exception(
            'Media server sync failed for integration %s (%s)',
            integration.id,
            integration.name,
        )
        _set_sync_state(
            integration,
            status=MediaServerIntegration.SyncStatus.ERROR,
            message=f'Sync failed: {exc}',
        )
        return f'Sync failed: {exc}'
