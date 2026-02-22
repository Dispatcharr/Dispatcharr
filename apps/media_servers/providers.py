import hashlib
import os
from dataclasses import dataclass
from typing import Iterable, Optional
from urllib.parse import urlencode, urljoin, urlparse

import requests

from apps.media_servers.models import MediaServerIntegration
from apps.media_servers.local_classification import (
    LocalClassificationResult,
    classify_media_entry,
)
from apps.media_servers.local_metadata import (
    enrich_episode_metadata_with_tmdb,
    enrich_movie_metadata_with_tmdb,
    enrich_series_metadata_with_tmdb,
    find_local_artwork_files,
    find_movie_nfo_metadata,
    find_series_nfo_metadata,
    find_episode_nfo_metadata,
    has_tmdb_api_key,
    parse_nfo_episode_entries,
)


def _extract_extension_from_path(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    parsed = urlparse(value)
    _, ext = os.path.splitext(parsed.path)
    if not ext:
        return None
    return ext.lstrip('.').lower() or None


def _safe_int(value) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _find_artwork_in_parent_dirs(
    start_dir: str,
    *,
    stop_dir: Optional[str] = None,
) -> tuple[Optional[str], Optional[str]]:
    current = os.path.abspath(start_dir)
    stop = os.path.abspath(stop_dir) if stop_dir else None
    while True:
        poster, backdrop = find_local_artwork_files(current)
        if poster or backdrop:
            return poster, backdrop

        parent = os.path.dirname(current)
        if parent == current:
            break

        if stop:
            try:
                if os.path.commonpath([stop, parent]) != stop:
                    break
            except ValueError:
                break

        current = parent

    return None, None


@dataclass
class ProviderLibrary:
    id: str
    name: str
    content_type: str = 'movie'


@dataclass
class ProviderMovie:
    external_id: str
    title: str
    category_name: str
    stream_url: str
    year: Optional[int] = None
    description: str = ''
    rating: str = ''
    duration_secs: Optional[int] = None
    genres: list[str] = None
    poster_url: str = ''
    tmdb_id: Optional[str] = None
    imdb_id: Optional[str] = None
    container_extension: Optional[str] = None
    local_path: Optional[str] = None
    local_file_name: Optional[str] = None
    local_file_size: Optional[int] = None

    def __post_init__(self):
        if self.genres is None:
            self.genres = []


@dataclass
class ProviderEpisode:
    external_id: str
    title: str
    series_external_id: str
    stream_url: str
    season_number: Optional[int] = None
    episode_number: Optional[int] = None
    description: str = ''
    rating: str = ''
    duration_secs: Optional[int] = None
    air_date: Optional[str] = None
    tmdb_id: Optional[str] = None
    imdb_id: Optional[str] = None
    container_extension: Optional[str] = None
    local_path: Optional[str] = None
    local_file_name: Optional[str] = None
    local_file_size: Optional[int] = None


@dataclass
class ProviderSeries:
    external_id: str
    title: str
    category_name: str
    year: Optional[int] = None
    description: str = ''
    rating: str = ''
    genres: list[str] = None
    poster_url: str = ''
    tmdb_id: Optional[str] = None
    imdb_id: Optional[str] = None
    episodes: list[ProviderEpisode] = None

    def __post_init__(self):
        if self.genres is None:
            self.genres = []
        if self.episodes is None:
            self.episodes = []


class BaseMediaServerClient:
    timeout_seconds = 30

    def __init__(self, integration: MediaServerIntegration):
        self.integration = integration
        self.base_url = (integration.base_url or '').rstrip('/')
        self.api_token = (integration.api_token or '').strip()
        self.verify_ssl = integration.verify_ssl
        self.session = requests.Session()
        self.session.headers.update(
            {
                'User-Agent': 'Dispatcharr/MediaServerSync',
            }
        )

    def close(self):
        self.session.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    def _build_url(self, path: str, params: Optional[dict] = None) -> str:
        if path.startswith('http://') or path.startswith('https://'):
            base = path
        else:
            base = urljoin(f'{self.base_url}/', path.lstrip('/'))
        if not params:
            return base
        encoded = urlencode({k: v for k, v in params.items() if v is not None}, doseq=True)
        return f'{base}?{encoded}' if encoded else base

    def _get_json(self, path: str, params: Optional[dict] = None, headers: Optional[dict] = None):
        response = self.session.get(
            self._build_url(path),
            params=params,
            headers=headers,
            timeout=self.timeout_seconds,
            verify=self.verify_ssl,
        )
        response.raise_for_status()
        return response.json()

    def ping(self) -> None:
        raise NotImplementedError

    def list_libraries(self) -> list[ProviderLibrary]:
        raise NotImplementedError

    def iter_movies(self, libraries: list[ProviderLibrary]) -> Iterable[ProviderMovie]:
        raise NotImplementedError

    def iter_series(self, libraries: list[ProviderLibrary]) -> Iterable[ProviderSeries]:
        return []


class PlexClient(BaseMediaServerClient):
    page_size = 200

    def _with_token(self, params: Optional[dict] = None) -> dict:
        payload = dict(params or {})
        if self.api_token:
            payload['X-Plex-Token'] = self.api_token
        return payload

    def ping(self) -> None:
        self._get_json(
            '/library/sections',
            params=self._with_token(),
            headers={'Accept': 'application/json'},
        )

    def list_libraries(self) -> list[ProviderLibrary]:
        payload = self._get_json(
            '/library/sections',
            params=self._with_token(),
            headers={'Accept': 'application/json'},
        )
        directories = (payload.get('MediaContainer') or {}).get('Directory') or []
        libraries = []
        for entry in directories:
            section_type = str(entry.get('type', '')).lower()
            if section_type == 'movie':
                content_type = 'movie'
            elif section_type in {'show', 'tv'}:
                content_type = 'series'
            else:
                continue
            library_id = str(entry.get('key', '')).strip()
            name = str(entry.get('title', '')).strip()
            if library_id and name:
                libraries.append(
                    ProviderLibrary(id=library_id, name=name, content_type=content_type)
                )
        return libraries

    def iter_movies(self, libraries: list[ProviderLibrary]) -> Iterable[ProviderMovie]:
        for library in libraries:
            if library.content_type not in {'movie', 'mixed'}:
                continue
            start = 0
            while True:
                payload = self._get_json(
                    f'/library/sections/{library.id}/all',
                    params=self._with_token(
                        {
                            'type': 1,
                            'includeGuids': 1,
                            'X-Plex-Container-Start': start,
                            'X-Plex-Container-Size': self.page_size,
                        }
                    ),
                    headers={'Accept': 'application/json'},
                )
                container = payload.get('MediaContainer') or {}
                metadata = container.get('Metadata') or []
                if not metadata:
                    break

                for item in metadata:
                    movie = self._parse_movie(item, library.name)
                    if movie:
                        yield movie

                fetched = len(metadata)
                start += fetched
                total_size = _safe_int(container.get('totalSize'))
                if total_size is not None and start >= total_size:
                    break
                if fetched < self.page_size:
                    break

    def iter_series(self, libraries: list[ProviderLibrary]) -> Iterable[ProviderSeries]:
        for library in libraries:
            if library.content_type not in {'series', 'mixed'}:
                continue

            start = 0
            while True:
                payload = self._get_json(
                    f'/library/sections/{library.id}/all',
                    params=self._with_token(
                        {
                            'type': 2,
                            'includeGuids': 1,
                            'X-Plex-Container-Start': start,
                            'X-Plex-Container-Size': self.page_size,
                        }
                    ),
                    headers={'Accept': 'application/json'},
                )
                container = payload.get('MediaContainer') or {}
                metadata = container.get('Metadata') or []
                if not metadata:
                    break

                for show in metadata:
                    parsed = self._parse_series(show, library.name)
                    if not parsed:
                        continue
                    series_id, provider_series = parsed
                    episodes = list(self._iter_series_episodes(series_id))
                    if not episodes:
                        continue
                    provider_series.episodes = episodes
                    yield provider_series

                fetched = len(metadata)
                start += fetched
                total_size = _safe_int(container.get('totalSize'))
                if total_size is not None and start >= total_size:
                    break
                if fetched < self.page_size:
                    break

    def _parse_movie(self, item: dict, category_name: str) -> Optional[ProviderMovie]:
        external_id = str(item.get('ratingKey') or '').strip()
        title = str(item.get('title') or item.get('originalTitle') or '').strip()
        if not external_id or not title:
            return None

        stream_url = ''
        container_ext = None
        media_entries = item.get('Media') or []
        if media_entries:
            primary_media = media_entries[0]
            container_ext = str(primary_media.get('container') or '').strip().lower() or None
            parts = primary_media.get('Part') or []
            if parts:
                primary_part = parts[0]
                part_key = primary_part.get('key')
                if not container_ext:
                    container_ext = _extract_extension_from_path(
                        primary_part.get('file') or part_key
                    )
                if part_key:
                    stream_url = self._build_url(
                        part_key,
                        params=self._with_token({'download': '1'}),
                    )
        if not stream_url:
            return None

        tmdb_id, imdb_id = self._extract_external_ids(item)
        poster_url = ''
        thumb = item.get('thumb')
        if thumb:
            poster_url = self._build_url(thumb, params=self._with_token())

        duration_millis = _safe_int(item.get('duration'))
        duration_secs = int(duration_millis / 1000) if duration_millis else None

        genres = []
        for genre in item.get('Genre') or []:
            tag = str(genre.get('tag') or '').strip()
            if tag:
                genres.append(tag)

        rating_raw = item.get('rating') or item.get('audienceRating') or ''
        rating = str(rating_raw).strip()

        return ProviderMovie(
            external_id=external_id,
            title=title,
            category_name=category_name,
            stream_url=stream_url,
            year=_safe_int(item.get('year')),
            description=str(item.get('summary') or '').strip(),
            rating=rating,
            duration_secs=duration_secs,
            genres=genres,
            poster_url=poster_url,
            tmdb_id=tmdb_id,
            imdb_id=imdb_id,
            container_extension=container_ext,
        )

    def _extract_external_ids(self, item: dict) -> tuple[Optional[str], Optional[str]]:
        imdb_id = None
        tmdb_id = None

        values = []
        guid_value = item.get('guid')
        if guid_value:
            values.append(guid_value)
        for entry in item.get('Guid') or []:
            guid_id = entry.get('id')
            if guid_id:
                values.append(guid_id)

        for value in values:
            raw = str(value).strip()
            if raw.startswith('imdb://') and not imdb_id:
                imdb_id = raw.replace('imdb://', '', 1).strip() or None
            elif raw.startswith('tmdb://') and not tmdb_id:
                tmdb_id = raw.replace('tmdb://', '', 1).strip() or None

        return tmdb_id, imdb_id

    def _parse_series(
        self,
        item: dict,
        category_name: str,
    ) -> Optional[tuple[str, ProviderSeries]]:
        series_id = str(item.get('ratingKey') or '').strip()
        title = str(item.get('title') or item.get('originalTitle') or '').strip()
        if not series_id or not title:
            return None

        tmdb_id, imdb_id = self._extract_external_ids(item)
        poster_url = ''
        thumb = item.get('thumb')
        if thumb:
            poster_url = self._build_url(thumb, params=self._with_token())

        genres = []
        for genre in item.get('Genre') or []:
            tag = str(genre.get('tag') or '').strip()
            if tag:
                genres.append(tag)

        rating_raw = item.get('rating') or item.get('audienceRating') or ''
        rating = str(rating_raw).strip()

        provider_series = ProviderSeries(
            external_id=series_id,
            title=title,
            category_name=category_name,
            year=_safe_int(item.get('year')),
            description=str(item.get('summary') or '').strip(),
            rating=rating,
            genres=genres,
            poster_url=poster_url,
            tmdb_id=tmdb_id,
            imdb_id=imdb_id,
        )
        return (series_id, provider_series)

    def _iter_series_episodes(self, series_id: str) -> Iterable[ProviderEpisode]:
        start = 0
        while True:
            payload = self._get_json(
                f'/library/metadata/{series_id}/allLeaves',
                params=self._with_token(
                    {
                        'includeGuids': 1,
                        'X-Plex-Container-Start': start,
                        'X-Plex-Container-Size': self.page_size,
                    }
                ),
                headers={'Accept': 'application/json'},
            )
            container = payload.get('MediaContainer') or {}
            metadata = container.get('Metadata') or []
            if not metadata:
                break

            for item in metadata:
                episode = self._parse_episode(item, series_id)
                if episode:
                    yield episode

            fetched = len(metadata)
            start += fetched
            total_size = _safe_int(container.get('totalSize'))
            if total_size is not None and start >= total_size:
                break
            if fetched < self.page_size:
                break

    def _parse_episode(self, item: dict, series_external_id: str) -> Optional[ProviderEpisode]:
        external_id = str(item.get('ratingKey') or '').strip()
        title = str(item.get('title') or '').strip()
        if not external_id or not title:
            return None

        stream_url = ''
        container_ext = None
        media_entries = item.get('Media') or []
        if media_entries:
            primary_media = media_entries[0]
            container_ext = str(primary_media.get('container') or '').strip().lower() or None
            parts = primary_media.get('Part') or []
            if parts:
                primary_part = parts[0]
                part_key = primary_part.get('key')
                if not container_ext:
                    container_ext = _extract_extension_from_path(
                        primary_part.get('file') or part_key
                    )
                if part_key:
                    stream_url = self._build_url(
                        part_key,
                        params=self._with_token({'download': '1'}),
                    )

        if not stream_url:
            return None

        tmdb_id, imdb_id = self._extract_external_ids(item)
        duration_millis = _safe_int(item.get('duration'))
        duration_secs = int(duration_millis / 1000) if duration_millis else None

        air_date = str(item.get('originallyAvailableAt') or '').strip() or None
        rating_raw = item.get('rating') or item.get('audienceRating') or ''
        rating = str(rating_raw).strip()

        return ProviderEpisode(
            external_id=external_id,
            title=title,
            series_external_id=series_external_id,
            stream_url=stream_url,
            season_number=_safe_int(item.get('parentIndex')),
            episode_number=_safe_int(item.get('index')),
            description=str(item.get('summary') or '').strip(),
            rating=rating,
            duration_secs=duration_secs,
            air_date=air_date,
            tmdb_id=tmdb_id,
            imdb_id=imdb_id,
            container_extension=container_ext,
        )


class EmbyCompatibleClient(BaseMediaServerClient):
    page_size = 200

    def __init__(self, integration: MediaServerIntegration):
        super().__init__(integration)
        if not self.api_token and integration.username and integration.password:
            self._authenticate_with_credentials(
                username=integration.username,
                password=integration.password,
            )
        if self.api_token:
            self.session.headers.update({'X-Emby-Token': self.api_token})

    def _authenticate_with_credentials(self, *, username: str, password: str) -> None:
        headers = {
            'X-Emby-Authorization': (
                'MediaBrowser Client="Dispatcharr", Device="Dispatcharr", '
                'DeviceId="dispatcharr-media-server", Version="1.0.0"'
            )
        }
        payload = {
            'Username': username,
            'Pw': password,
            'Password': password,
        }
        response = self.session.post(
            self._build_url('/Users/AuthenticateByName'),
            json=payload,
            headers=headers,
            timeout=self.timeout_seconds,
            verify=self.verify_ssl,
        )
        response.raise_for_status()
        data = response.json()
        token = str(data.get('AccessToken') or '').strip()
        if token:
            self.api_token = token

    def _with_api_key(self, params: Optional[dict] = None) -> dict:
        payload = dict(params or {})
        if self.api_token:
            payload['api_key'] = self.api_token
        return payload

    def ping(self) -> None:
        self._get_json('/System/Info/Public', params=self._with_api_key())

    def list_libraries(self) -> list[ProviderLibrary]:
        items = self._fetch_virtual_folders()
        libraries = []
        user_id = self._resolve_user_id()

        for entry in items:
            library_id = str(entry.get('ItemId') or entry.get('Id') or '').strip()
            name = str(entry.get('Name') or '').strip()
            collection_type = str(entry.get('CollectionType') or '').strip().lower()
            if not library_id or not name:
                continue

            content_type = self._detect_library_content_type(
                library_id=library_id,
                collection_type=collection_type,
                user_id=user_id,
            )
            if not content_type:
                continue

            libraries.append(
                ProviderLibrary(id=library_id, name=name, content_type=content_type)
            )

        return libraries

    def _detect_library_content_type(
        self,
        *,
        library_id: str,
        collection_type: str,
        user_id: Optional[str],
    ) -> Optional[str]:
        excluded_collection_types = {
            'music',
            'musicvideos',
            'books',
            'audiobooks',
            'photos',
            'playlists',
            'livetv',
            'podcasts',
            'channels',
            'trailers',
        }
        movie_collection_types = {'movies', 'boxsets', 'homevideos'}
        series_collection_types = {'tvshows', 'series', 'shows', 'tv'}

        if collection_type in excluded_collection_types:
            return None
        if collection_type in movie_collection_types:
            return 'movie'
        if collection_type in series_collection_types:
            return 'series'
        if collection_type == 'mixed':
            return 'mixed'

        has_movies = self._library_has_movies(library_id=library_id, user_id=user_id)
        has_series = self._library_has_series(library_id=library_id, user_id=user_id)

        if has_movies and has_series:
            return 'mixed'
        if has_movies:
            return 'movie'
        if has_series:
            return 'series'
        return None

    def _library_has_movies(self, *, library_id: str, user_id: Optional[str]) -> bool:
        try:
            items, _ = self._fetch_movies_page(
                library_id=library_id,
                start_index=0,
                limit=1,
                user_id=user_id,
            )
            return bool(items)
        except requests.RequestException:
            return False

    def _library_has_series(self, *, library_id: str, user_id: Optional[str]) -> bool:
        try:
            items, _ = self._fetch_series_page(
                library_id=library_id,
                start_index=0,
                limit=1,
                user_id=user_id,
            )
            return bool(items)
        except requests.RequestException:
            return False

    def iter_movies(self, libraries: list[ProviderLibrary]) -> Iterable[ProviderMovie]:
        user_id = self._resolve_user_id()
        for library in libraries:
            if library.content_type not in {'movie', 'mixed'}:
                continue
            start = 0
            while True:
                items, total = self._fetch_movies_page(
                    library_id=library.id,
                    start_index=start,
                    limit=self.page_size,
                    user_id=user_id,
                )
                if not items:
                    break
                for entry in items:
                    movie = self._parse_movie(entry, library.name)
                    if movie:
                        yield movie
                fetched = len(items)
                start += fetched
                if total is not None and start >= total:
                    break
                if fetched < self.page_size:
                    break

    def iter_series(self, libraries: list[ProviderLibrary]) -> Iterable[ProviderSeries]:
        user_id = self._resolve_user_id()
        for library in libraries:
            if library.content_type not in {'series', 'mixed'}:
                continue

            start = 0
            while True:
                items, total = self._fetch_series_page(
                    library_id=library.id,
                    start_index=start,
                    limit=self.page_size,
                    user_id=user_id,
                )
                if not items:
                    break

                for entry in items:
                    parsed = self._parse_series(entry, library.name)
                    if not parsed:
                        continue
                    series_id, provider_series = parsed
                    episodes = list(
                        self._iter_series_episodes(
                            series_id=series_id,
                            user_id=user_id,
                        )
                    )
                    if not episodes:
                        continue
                    provider_series.episodes = episodes
                    yield provider_series

                fetched = len(items)
                start += fetched
                if total is not None and start >= total:
                    break
                if fetched < self.page_size:
                    break

    def _fetch_virtual_folders(self) -> list[dict]:
        candidates = ['/Library/VirtualFolders', '/Library/MediaFolders']
        for path in candidates:
            payload = self._get_json(path, params=self._with_api_key())
            if isinstance(payload, list):
                if payload:
                    return payload
                continue
            if isinstance(payload, dict):
                items = payload.get('Items')
                if isinstance(items, list) and items:
                    return items
                if path == '/Library/VirtualFolders' and isinstance(payload.get('Items'), list):
                    return payload['Items']
        return []

    def _resolve_user_id(self) -> Optional[str]:
        user_endpoints = [
            ('/Users', self._with_api_key()),
            ('/Users/Query', self._with_api_key({'Limit': 1})),
        ]
        for path, params in user_endpoints:
            try:
                payload = self._get_json(path, params=params)
            except requests.RequestException:
                continue
            if isinstance(payload, dict):
                items = payload.get('Items')
                if items:
                    user_id = items[0].get('Id')
                    if user_id:
                        return str(user_id)
            elif isinstance(payload, list) and payload:
                user_id = payload[0].get('Id')
                if user_id:
                    return str(user_id)
        return None

    def _fetch_movies_page(
        self,
        library_id: str,
        start_index: int,
        limit: int,
        user_id: Optional[str],
    ) -> tuple[list[dict], Optional[int]]:
        params = self._with_api_key(
            {
                'Recursive': 'true',
                'IncludeItemTypes': 'Movie',
                'ParentId': library_id,
                'Fields': 'ProviderIds,Overview,Path,MediaSources,RunTimeTicks,CommunityRating,Genres,ProductionYear',
                'StartIndex': start_index,
                'Limit': limit,
            }
        )

        endpoint = f'/Users/{user_id}/Items' if user_id else '/Items'
        try:
            payload = self._get_json(endpoint, params=params)
        except requests.RequestException:
            if user_id:
                payload = self._get_json('/Items', params=params)
            else:
                raise
        items = payload.get('Items') if isinstance(payload, dict) else []
        total = _safe_int(payload.get('TotalRecordCount')) if isinstance(payload, dict) else None
        return (items or [], total)

    def _fetch_series_page(
        self,
        library_id: str,
        start_index: int,
        limit: int,
        user_id: Optional[str],
    ) -> tuple[list[dict], Optional[int]]:
        params = self._with_api_key(
            {
                'Recursive': 'true',
                'IncludeItemTypes': 'Series',
                'ParentId': library_id,
                'Fields': 'ProviderIds,Overview,Path,CommunityRating,Genres,ProductionYear',
                'StartIndex': start_index,
                'Limit': limit,
            }
        )

        endpoint = f'/Users/{user_id}/Items' if user_id else '/Items'
        try:
            payload = self._get_json(endpoint, params=params)
        except requests.RequestException:
            if user_id:
                payload = self._get_json('/Items', params=params)
            else:
                raise
        items = payload.get('Items') if isinstance(payload, dict) else []
        total = _safe_int(payload.get('TotalRecordCount')) if isinstance(payload, dict) else None
        return (items or [], total)

    def _fetch_episodes_page(
        self,
        series_id: str,
        start_index: int,
        limit: int,
        user_id: Optional[str],
    ) -> tuple[list[dict], Optional[int]]:
        params = self._with_api_key(
            {
                'Recursive': 'true',
                'IncludeItemTypes': 'Episode',
                'ParentId': series_id,
                'Fields': (
                    'ProviderIds,Overview,Path,MediaSources,RunTimeTicks,'
                    'CommunityRating,ProductionYear,ParentIndexNumber,IndexNumber,PremiereDate'
                ),
                'StartIndex': start_index,
                'Limit': limit,
            }
        )

        endpoint = f'/Users/{user_id}/Items' if user_id else '/Items'
        try:
            payload = self._get_json(endpoint, params=params)
        except requests.RequestException:
            if user_id:
                payload = self._get_json('/Items', params=params)
            else:
                raise
        items = payload.get('Items') if isinstance(payload, dict) else []
        total = _safe_int(payload.get('TotalRecordCount')) if isinstance(payload, dict) else None
        return (items or [], total)

    def _parse_movie(self, item: dict, category_name: str) -> Optional[ProviderMovie]:
        external_id = str(item.get('Id') or '').strip()
        title = str(item.get('Name') or '').strip()
        if not external_id or not title:
            return None

        stream_url, container = self._build_stream_url(item)
        if not stream_url:
            return None

        provider_ids = item.get('ProviderIds') or {}
        tmdb_id = str(
            provider_ids.get('Tmdb')
            or provider_ids.get('TMDb')
            or ''
        ).strip() or None
        imdb_id = str(
            provider_ids.get('Imdb')
            or provider_ids.get('IMDb')
            or ''
        ).strip() or None

        run_ticks = _safe_int(item.get('RunTimeTicks'))
        duration_secs = int(run_ticks / 10_000_000) if run_ticks else None

        rating_value = item.get('CommunityRating') or ''
        rating = str(rating_value).strip()

        genres = [str(genre).strip() for genre in item.get('Genres') or [] if str(genre).strip()]

        poster_url = self._build_url(
            f'/Items/{external_id}/Images/Primary',
            params=self._with_api_key({'quality': 90}),
        )

        if not container:
            container = _extract_extension_from_path(item.get('Path'))

        return ProviderMovie(
            external_id=external_id,
            title=title,
            category_name=category_name,
            stream_url=stream_url,
            year=_safe_int(item.get('ProductionYear')),
            description=str(item.get('Overview') or '').strip(),
            rating=rating,
            duration_secs=duration_secs,
            genres=genres,
            poster_url=poster_url,
            tmdb_id=tmdb_id,
            imdb_id=imdb_id,
            container_extension=container,
        )

    def _parse_series(
        self,
        item: dict,
        category_name: str,
    ) -> Optional[tuple[str, ProviderSeries]]:
        external_id = str(item.get('Id') or '').strip()
        title = str(item.get('Name') or '').strip()
        if not external_id or not title:
            return None

        provider_ids = item.get('ProviderIds') or {}
        tmdb_id = str(
            provider_ids.get('Tmdb')
            or provider_ids.get('TMDb')
            or ''
        ).strip() or None
        imdb_id = str(
            provider_ids.get('Imdb')
            or provider_ids.get('IMDb')
            or ''
        ).strip() or None

        rating_value = item.get('CommunityRating') or ''
        rating = str(rating_value).strip()
        genres = [str(genre).strip() for genre in item.get('Genres') or [] if str(genre).strip()]
        poster_url = self._build_url(
            f'/Items/{external_id}/Images/Primary',
            params=self._with_api_key({'quality': 90}),
        )

        provider_series = ProviderSeries(
            external_id=external_id,
            title=title,
            category_name=category_name,
            year=_safe_int(item.get('ProductionYear')),
            description=str(item.get('Overview') or '').strip(),
            rating=rating,
            genres=genres,
            poster_url=poster_url,
            tmdb_id=tmdb_id,
            imdb_id=imdb_id,
        )
        return (external_id, provider_series)

    def _iter_series_episodes(
        self,
        *,
        series_id: str,
        user_id: Optional[str],
    ) -> Iterable[ProviderEpisode]:
        start = 0
        while True:
            items, total = self._fetch_episodes_page(
                series_id=series_id,
                start_index=start,
                limit=self.page_size,
                user_id=user_id,
            )
            if not items:
                break

            for item in items:
                episode = self._parse_episode(item, series_id)
                if episode:
                    yield episode

            fetched = len(items)
            start += fetched
            if total is not None and start >= total:
                break
            if fetched < self.page_size:
                break

    def _parse_episode(self, item: dict, series_external_id: str) -> Optional[ProviderEpisode]:
        external_id = str(item.get('Id') or '').strip()
        title = str(item.get('Name') or '').strip()
        if not external_id or not title:
            return None

        stream_url, container = self._build_stream_url(item)
        if not stream_url:
            return None

        provider_ids = item.get('ProviderIds') or {}
        tmdb_id = str(
            provider_ids.get('Tmdb')
            or provider_ids.get('TMDb')
            or ''
        ).strip() or None
        imdb_id = str(
            provider_ids.get('Imdb')
            or provider_ids.get('IMDb')
            or ''
        ).strip() or None

        run_ticks = _safe_int(item.get('RunTimeTicks'))
        duration_secs = int(run_ticks / 10_000_000) if run_ticks else None
        rating_value = item.get('CommunityRating') or ''
        rating = str(rating_value).strip()
        premiere = str(item.get('PremiereDate') or '').strip()
        air_date = premiere[:10] if premiere else None

        return ProviderEpisode(
            external_id=external_id,
            title=title,
            series_external_id=series_external_id,
            stream_url=stream_url,
            season_number=_safe_int(item.get('ParentIndexNumber')),
            episode_number=_safe_int(item.get('IndexNumber')),
            description=str(item.get('Overview') or '').strip(),
            rating=rating,
            duration_secs=duration_secs,
            air_date=air_date,
            tmdb_id=tmdb_id,
            imdb_id=imdb_id,
            container_extension=container,
        )

    def _build_stream_url(self, item: dict) -> tuple[Optional[str], Optional[str]]:
        external_id = str(item.get('Id') or '').strip()
        if not external_id:
            return (None, None)

        params = self._with_api_key({'Static': 'true'})
        container = None
        media_sources = item.get('MediaSources') or []
        if media_sources:
            primary = media_sources[0]
            media_source_id = primary.get('Id')
            if media_source_id:
                params['MediaSourceId'] = media_source_id
            container = str(primary.get('Container') or '').strip().lower() or None
            if not container:
                container = _extract_extension_from_path(primary.get('Path'))

        stream_url = self._build_url(f'/Videos/{external_id}/stream', params=params)
        return (stream_url, container)


class EmbyClient(EmbyCompatibleClient):
    pass


class JellyfinClient(EmbyCompatibleClient):
    pass


class LocalClient(BaseMediaServerClient):
    VIDEO_EXTENSIONS = {
        '.mkv',
        '.mp4',
        '.m4v',
        '.avi',
        '.mov',
        '.wmv',
        '.mpg',
        '.mpeg',
        '.ts',
        '.m2ts',
        '.webm',
    }

    def __init__(self, integration: MediaServerIntegration):
        super().__init__(integration)
        self._location_by_id = self._load_locations()

    def close(self):
        self.session.close()

    def _load_locations(self) -> dict[str, dict]:
        provider_config = (
            self.integration.provider_config
            if isinstance(self.integration.provider_config, dict)
            else {}
        )
        raw_locations = provider_config.get('locations', [])
        if not isinstance(raw_locations, list):
            raw_locations = []

        locations: dict[str, dict] = {}
        for index, raw in enumerate(raw_locations, start=1):
            if not isinstance(raw, dict):
                continue
            raw_path = str(raw.get('path') or '').strip()
            if not raw_path:
                continue
            path = os.path.abspath(os.path.expanduser(raw_path))
            content_type = str(raw.get('content_type') or 'movie').strip().lower()
            if content_type not in {'movie', 'series', 'mixed'}:
                content_type = 'movie'
            include_subdirectories = bool(raw.get('include_subdirectories', True))
            name = str(raw.get('name') or '').strip() or os.path.basename(path) or path
            location_id = str(raw.get('id') or '').strip()
            if not location_id:
                location_id = hashlib.sha1(
                    f'{path}:{content_type}:{index}'.encode('utf-8')
                ).hexdigest()[:16]
            locations[location_id] = {
                'id': location_id,
                'name': name,
                'path': path,
                'content_type': content_type,
                'include_subdirectories': include_subdirectories,
            }
        return locations

    def _iter_location_files(self, base_path: str, include_subdirectories: bool):
        if include_subdirectories:
            for root, _dirs, files in os.walk(base_path):
                for file_name in files:
                    yield os.path.join(root, file_name)
            return
        for entry in os.scandir(base_path):
            if entry.is_file():
                yield entry.path

    def _is_media_file(self, file_name: str) -> bool:
        _base, ext = os.path.splitext(file_name)
        return ext.lower() in self.VIDEO_EXTENSIONS

    def _file_size(self, path: str) -> Optional[int]:
        try:
            return os.path.getsize(path)
        except OSError:
            return None

    def _relative_parent_path(self, full_path: str, base_path: str) -> str:
        try:
            relative = os.path.relpath(os.path.dirname(full_path), base_path)
        except ValueError:
            return ''
        return '' if relative == '.' else relative

    def _episode_nfo_path(self, file_path: str) -> str | None:
        directory = os.path.dirname(file_path)
        base_name = os.path.splitext(os.path.basename(file_path))[0]
        for candidate_name in (f'{base_name}.nfo', 'episode.nfo'):
            candidate = os.path.join(directory, candidate_name)
            if os.path.isfile(candidate):
                return candidate
        return None

    def ping(self) -> None:
        if not self._location_by_id:
            raise ValueError('Local provider requires at least one location.')
        if not has_tmdb_api_key():
            raise ValueError(
                'Local provider requires a TMDB API key. '
                'Configure it in Settings > Stream Settings.'
            )
        missing = [
            location['path']
            for location in self._location_by_id.values()
            if not os.path.isdir(location['path'])
        ]
        if missing:
            raise FileNotFoundError(
                f'Local path(s) not found: {", ".join(missing)}'
            )

    def list_libraries(self) -> list[ProviderLibrary]:
        libraries = []
        for location in self._location_by_id.values():
            libraries.append(
                ProviderLibrary(
                    id=location['id'],
                    name=location['name'],
                    content_type=location['content_type'],
                )
            )
        return libraries

    def iter_movies(self, libraries: list[ProviderLibrary]) -> Iterable[ProviderMovie]:
        for library in libraries:
            if library.content_type not in {'movie', 'mixed'}:
                continue
            location = self._location_by_id.get(library.id)
            if not location:
                continue

            base_path = location['path']
            if not os.path.isdir(base_path):
                continue

            for full_path in self._iter_location_files(
                base_path,
                include_subdirectories=location['include_subdirectories'],
            ):
                file_name = os.path.basename(full_path)
                if not self._is_media_file(file_name):
                    continue

                relative_path = self._relative_parent_path(full_path, base_path)
                classification = classify_media_entry(
                    'movie' if library.content_type == 'movie' else 'mixed',
                    relative_path=relative_path,
                    file_name=file_name,
                )
                if classification.detected_type != 'movie':
                    continue

                metadata, _metadata_error = find_movie_nfo_metadata(full_path)
                metadata = metadata or {}
                local_poster, local_backdrop = find_local_artwork_files(
                    os.path.dirname(full_path)
                )
                if local_poster:
                    metadata['poster_url'] = local_poster
                if local_backdrop:
                    metadata['backdrop_url'] = local_backdrop
                metadata, _tmdb_error = enrich_movie_metadata_with_tmdb(
                    metadata,
                    title=classification.title or os.path.splitext(file_name)[0],
                    year=classification.year,
                )
                title = (
                    str(metadata.get('title') or '').strip()
                    or classification.title
                    or os.path.splitext(file_name)[0]
                )
                movie_hash_source = f'{location["id"]}:{full_path}'
                external_id = hashlib.sha1(
                    movie_hash_source.encode('utf-8')
                ).hexdigest()
                extension = os.path.splitext(file_name)[1].lstrip('.').lower() or None

                yield ProviderMovie(
                    external_id=external_id,
                    title=title,
                    category_name=library.name,
                    stream_url='',
                    year=_safe_int(metadata.get('year')) or classification.year,
                    description=str(metadata.get('description') or '').strip(),
                    rating=str(metadata.get('rating') or '').strip(),
                    duration_secs=_safe_int(metadata.get('duration_secs')),
                    genres=[
                        str(entry).strip()
                        for entry in (metadata.get('genres') or [])
                        if str(entry).strip()
                    ],
                    poster_url=str(metadata.get('poster_url') or '').strip(),
                    tmdb_id=str(metadata.get('tmdb_id') or '').strip() or None,
                    imdb_id=str(metadata.get('imdb_id') or '').strip() or None,
                    container_extension=extension,
                    local_path=full_path,
                    local_file_name=file_name,
                    local_file_size=self._file_size(full_path),
                )

    def iter_series(self, libraries: list[ProviderLibrary]) -> Iterable[ProviderSeries]:
        for library in libraries:
            if library.content_type not in {'series', 'mixed'}:
                continue
            location = self._location_by_id.get(library.id)
            if not location:
                continue

            base_path = location['path']
            if not os.path.isdir(base_path):
                continue

            series_map: dict[str, ProviderSeries] = {}
            series_episode_ids: dict[str, set[str]] = {}

            for full_path in self._iter_location_files(
                base_path,
                include_subdirectories=location['include_subdirectories'],
            ):
                file_name = os.path.basename(full_path)
                if not self._is_media_file(file_name):
                    continue

                relative_path = self._relative_parent_path(full_path, base_path)
                classification: LocalClassificationResult = classify_media_entry(
                    'series',
                    relative_path=relative_path,
                    file_name=file_name,
                )
                if classification.detected_type != 'episode':
                    continue

                series_title = classification.title or os.path.splitext(file_name)[0]
                series_key = (
                    f'{location["id"]}:'
                    f'{series_title.strip().lower()}:'
                    f'{classification.year or ""}'
                )
                provider_series = series_map.get(series_key)
                if not provider_series:
                    series_meta, _series_error = find_series_nfo_metadata(
                        full_path,
                        base_path=base_path,
                    )
                    series_meta = series_meta or {}
                    local_poster, local_backdrop = _find_artwork_in_parent_dirs(
                        os.path.dirname(full_path),
                        stop_dir=base_path,
                    )
                    if local_poster:
                        series_meta['poster_url'] = local_poster
                    if local_backdrop:
                        series_meta['backdrop_url'] = local_backdrop
                    series_meta, _tmdb_error = enrich_series_metadata_with_tmdb(
                        series_meta,
                        title=series_title,
                        year=classification.year,
                    )
                    external_series_id = hashlib.sha1(
                        series_key.encode('utf-8')
                    ).hexdigest()
                    provider_series = ProviderSeries(
                        external_id=external_series_id,
                        title=(
                            str(series_meta.get('title') or '').strip()
                            or series_title
                        ),
                        category_name=library.name,
                        year=_safe_int(series_meta.get('year')) or classification.year,
                        description=str(series_meta.get('description') or '').strip(),
                        rating=str(series_meta.get('rating') or '').strip(),
                        genres=[
                            str(entry).strip()
                            for entry in (series_meta.get('genres') or [])
                            if str(entry).strip()
                        ],
                        poster_url=str(series_meta.get('poster_url') or '').strip(),
                        tmdb_id=str(series_meta.get('tmdb_id') or '').strip() or None,
                        imdb_id=str(series_meta.get('imdb_id') or '').strip() or None,
                    )
                    series_map[series_key] = provider_series
                    series_episode_ids[series_key] = set()

                episode_numbers = []
                if classification.episode is not None:
                    episode_numbers.append(classification.episode)
                if classification.episode_list:
                    episode_numbers.extend(
                        [value for value in classification.episode_list if value is not None]
                    )
                seen_episode_numbers = set()
                deduped_episode_numbers = []
                for value in episode_numbers:
                    if value in seen_episode_numbers:
                        continue
                    seen_episode_numbers.add(value)
                    deduped_episode_numbers.append(value)
                episode_numbers = deduped_episode_numbers or [classification.episode]

                episode_title_map: dict[int, str] = {}
                if len(episode_numbers) <= 1:
                    nfo_path = self._episode_nfo_path(full_path)
                    if nfo_path:
                        nfo_entries, _nfo_error = parse_nfo_episode_entries(nfo_path)
                        nfo_entries = [
                            entry for entry in nfo_entries if entry.get('episode') is not None
                        ]
                        if len(nfo_entries) > 1:
                            episode_numbers = []
                            for entry in nfo_entries:
                                ep_num = entry.get('episode')
                                if ep_num in episode_numbers:
                                    continue
                                episode_numbers.append(ep_num)
                                if entry.get('title'):
                                    episode_title_map[ep_num] = str(entry['title']).strip()
                            if classification.season is None:
                                seasons = {
                                    entry.get('season')
                                    for entry in nfo_entries
                                    if entry.get('season') is not None
                                }
                                if len(seasons) == 1:
                                    classification.season = seasons.pop()

                extension = os.path.splitext(file_name)[1].lstrip('.').lower() or None
                for episode_number in episode_numbers:
                    if episode_number is None:
                        continue
                    episode_key = (
                        f'{full_path}:{classification.season or ""}:{episode_number}'
                    )
                    external_episode_id = hashlib.sha1(
                        episode_key.encode('utf-8')
                    ).hexdigest()
                    if external_episode_id in series_episode_ids[series_key]:
                        continue

                    episode_meta, _episode_error = find_episode_nfo_metadata(
                        full_path,
                        season_number=classification.season,
                        episode_number=episode_number,
                    )
                    episode_meta = episode_meta or {}
                    episode_meta, _tmdb_error = enrich_episode_metadata_with_tmdb(
                        episode_meta,
                        series_tmdb_id=provider_series.tmdb_id,
                        series_title=provider_series.title,
                        series_year=provider_series.year,
                        season_number=classification.season,
                        episode_number=episode_number,
                    )
                    episode_title = (
                        str(episode_meta.get('title') or '').strip()
                        or episode_title_map.get(episode_number)
                        or classification.episode_title
                        or os.path.splitext(file_name)[0]
                    )

                    provider_series.episodes.append(
                        ProviderEpisode(
                            external_id=external_episode_id,
                            title=episode_title,
                            series_external_id=provider_series.external_id,
                            stream_url='',
                            season_number=classification.season,
                            episode_number=episode_number,
                            description=str(episode_meta.get('description') or '').strip(),
                            rating=str(episode_meta.get('rating') or '').strip(),
                            duration_secs=_safe_int(episode_meta.get('duration_secs')),
                            air_date=str(episode_meta.get('air_date') or '').strip() or None,
                            tmdb_id=str(episode_meta.get('tmdb_id') or '').strip() or None,
                            imdb_id=str(episode_meta.get('imdb_id') or '').strip() or None,
                            container_extension=extension,
                            local_path=full_path,
                            local_file_name=file_name,
                            local_file_size=self._file_size(full_path),
                        )
                    )
                    series_episode_ids[series_key].add(external_episode_id)

            for provider_series in series_map.values():
                provider_series.episodes.sort(
                    key=lambda entry: (
                        entry.season_number if entry.season_number is not None else 10_000,
                        entry.episode_number if entry.episode_number is not None else 10_000,
                        entry.external_id,
                    )
                )
                if provider_series.episodes:
                    yield provider_series


def get_provider_client(integration: MediaServerIntegration) -> BaseMediaServerClient:
    provider = integration.provider_type
    if provider == MediaServerIntegration.ProviderTypes.PLEX:
        return PlexClient(integration)
    if provider == MediaServerIntegration.ProviderTypes.EMBY:
        return EmbyClient(integration)
    if provider == MediaServerIntegration.ProviderTypes.JELLYFIN:
        return JellyfinClient(integration)
    if provider == MediaServerIntegration.ProviderTypes.LOCAL:
        return LocalClient(integration)
    raise ValueError(f'Unsupported provider type: {provider}')
