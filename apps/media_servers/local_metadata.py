import os
import xml.etree.ElementTree as ET
from typing import Any, Optional

import requests

from core.models import CoreSettings
from apps.media_servers.local_classification import normalize_title


TMDB_API_BASE_URL = 'https://api.themoviedb.org/3'
TMDB_IMAGE_BASE_URL = 'https://image.tmdb.org/t/p/original'
TMDB_TIMEOUT_SECONDS = 6
_TMDB_SESSION = requests.Session()
_TMDB_SEARCH_CACHE: dict[tuple[str, str, str], tuple[Optional[dict], Optional[str]]] = {}
_TMDB_DETAIL_CACHE: dict[tuple[str, str], tuple[Optional[dict], Optional[str]]] = {}
_TMDB_EPISODE_CACHE: dict[tuple[str, int, int], tuple[Optional[dict], Optional[str]]] = {}


def _get_tmdb_api_key() -> Optional[str]:
    value = (
        CoreSettings._get_group("media_library_settings", {}).get("tmdb_api_key")
        or os.environ.get('TMDB_API_KEY')
    )
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def has_tmdb_api_key() -> bool:
    return bool(_get_tmdb_api_key())


def prefer_nfo_metadata() -> bool:
    """Return the administrator-selected metadata priority for local scans."""
    value = CoreSettings._get_group("media_library_settings", {}).get(
        "prefer_nfo",
        True,
    )
    return value is not False


def _build_tmdb_image_url(path: str | None) -> Optional[str]:
    raw = str(path or '').strip()
    if not raw:
        return None
    if raw.startswith('http://') or raw.startswith('https://'):
        return raw
    if not raw.startswith('/'):
        raw = f'/{raw}'
    return f'{TMDB_IMAGE_BASE_URL}{raw}'


def _parse_release_year(value: str | None) -> Optional[int]:
    raw = str(value or '').strip()
    if len(raw) < 4:
        return None
    try:
        return int(raw[:4])
    except (TypeError, ValueError):
        return None


def _tmdb_title(payload: dict) -> str:
    return str(payload.get('title') or payload.get('name') or '').strip()


def _tmdb_candidate_year(payload: dict) -> Optional[int]:
    return _parse_release_year(
        payload.get('release_date') or payload.get('first_air_date')
    )


def _select_tmdb_candidate(
    results: list[dict],
    title: str,
    *,
    year: Optional[int] = None,
) -> Optional[dict]:
    if not results:
        return None
    normalized_query = normalize_title(title)
    if not normalized_query:
        return None

    exact = [
        result
        for result in results
        if isinstance(result, dict)
        and normalize_title(_tmdb_title(result)) == normalized_query
    ]
    if year is not None:
        exact = [
            result
            for result in exact
            if _tmdb_candidate_year(result) == year
        ]
    return exact[0] if len(exact) == 1 else None


def _tmdb_request(path: str, *, params: dict[str, Any]) -> tuple[Optional[dict], Optional[str]]:
    try:
        response = _TMDB_SESSION.get(
            f'{TMDB_API_BASE_URL}{path}',
            params=params,
            timeout=TMDB_TIMEOUT_SECONDS,
        )
    except requests.RequestException:
        # requests exceptions may include the request URL, which contains the
        # configured TMDB API key. Never persist or return that detail.
        return None, 'TMDB request failed.'

    if response.status_code != 200:
        return None, f'TMDB returned status {response.status_code}.'

    try:
        payload = response.json()
    except ValueError:
        return None, 'TMDB returned invalid JSON.'

    if not isinstance(payload, dict):
        return None, 'TMDB returned an unexpected payload.'

    return payload, None


def _tmdb_search(
    media_type: str,
    title: str,
    *,
    year: Optional[int],
    api_key: str,
) -> tuple[Optional[dict], Optional[str]]:
    normalized_title = str(title or '').strip()
    if not normalized_title:
        return None, 'Title is required for TMDB search.'

    cache_key = (
        media_type,
        normalized_title.lower(),
        str(year or ''),
    )
    if cache_key in _TMDB_SEARCH_CACHE:
        return _TMDB_SEARCH_CACHE[cache_key]

    params: dict[str, Any] = {'api_key': api_key, 'query': normalized_title}
    if media_type == 'movie' and year:
        params['year'] = year
    if media_type == 'tv' and year:
        params['first_air_date_year'] = year

    payload, error = _tmdb_request(f'/search/{media_type}', params=params)
    if error:
        _TMDB_SEARCH_CACHE[cache_key] = (None, error)
        return None, error

    results = payload.get('results') or []
    if not isinstance(results, list) or not results:
        message = 'TMDB search returned no matches.'
        _TMDB_SEARCH_CACHE[cache_key] = (None, message)
        return None, message

    candidate = _select_tmdb_candidate(results, normalized_title, year=year)
    if candidate is None:
        message = 'TMDB search did not produce one unambiguous title/year match.'
        _TMDB_SEARCH_CACHE[cache_key] = (None, message)
        return None, message
    _TMDB_SEARCH_CACHE[cache_key] = (candidate, None)
    return candidate, None


def _tmdb_find_by_imdb_id(
    imdb_id: str,
    *,
    media_type: str,
    api_key: str,
) -> tuple[Optional[dict], Optional[str]]:
    normalized = str(imdb_id or '').strip()
    if not normalized:
        return None, 'IMDb ID is missing.'

    payload, error = _tmdb_request(
        f'/find/{normalized}',
        params={'api_key': api_key, 'external_source': 'imdb_id'},
    )
    if error:
        return None, error

    result_key = 'movie_results' if media_type == 'movie' else 'tv_results'
    results = payload.get(result_key) or []
    if not isinstance(results, list) or len(results) != 1:
        return None, 'TMDB find did not produce one unambiguous match.'

    first = results[0]
    if not isinstance(first, dict):
        return None, 'TMDB find returned an unexpected payload.'
    return first, None


def _tmdb_fetch_details(
    media_type: str,
    content_id: str,
    *,
    api_key: str,
) -> tuple[Optional[dict], Optional[str]]:
    normalized_id = str(content_id or '').strip()
    if not normalized_id:
        return None, 'TMDB content ID is missing.'

    cache_key = (media_type, normalized_id)
    if cache_key in _TMDB_DETAIL_CACHE:
        return _TMDB_DETAIL_CACHE[cache_key]

    payload, error = _tmdb_request(
        f'/{media_type}/{normalized_id}',
        params={'api_key': api_key, 'append_to_response': 'external_ids'},
    )
    if error:
        _TMDB_DETAIL_CACHE[cache_key] = (None, error)
        return None, error

    _TMDB_DETAIL_CACHE[cache_key] = (payload, None)
    return payload, None


def _tmdb_fetch_episode_details(
    tv_id: str,
    *,
    season_number: int,
    episode_number: int,
    api_key: str,
) -> tuple[Optional[dict], Optional[str]]:
    normalized_id = str(tv_id or '').strip()
    if not normalized_id:
        return None, 'TMDB series ID is missing.'

    cache_key = (normalized_id, season_number, episode_number)
    if cache_key in _TMDB_EPISODE_CACHE:
        return _TMDB_EPISODE_CACHE[cache_key]

    payload, error = _tmdb_request(
        f'/tv/{normalized_id}/season/{season_number}/episode/{episode_number}',
        params={'api_key': api_key, 'append_to_response': 'external_ids'},
    )
    if error:
        _TMDB_EPISODE_CACHE[cache_key] = (None, error)
        return None, error

    _TMDB_EPISODE_CACHE[cache_key] = (payload, None)
    return payload, None


def _as_year(value: Any) -> Optional[int]:
    if value in (None, ''):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _rating_to_text(value: Any) -> Optional[str]:
    if value in (None, ''):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return str(number).rstrip('0').rstrip('.')


def _set_metadata_value(
    payload: dict,
    key: str,
    value: Any,
    *,
    prefer_existing: bool,
) -> None:
    if value in (None, '', [], {}):
        return
    if not prefer_existing or payload.get(key) in (None, '', [], {}):
        payload[key] = value


def _apply_metadata_values(
    payload: dict,
    values: dict[str, Any],
    *,
    prefer_existing: bool,
) -> None:
    for key, value in values.items():
        _set_metadata_value(
            payload,
            key,
            value,
            prefer_existing=prefer_existing,
        )


def enrich_movie_metadata_with_tmdb(
    metadata: dict | None,
    *,
    title: str,
    year: Optional[int] = None,
    prefer_existing: bool = True,
) -> tuple[dict, Optional[str]]:
    payload = dict(metadata or {})
    api_key = _get_tmdb_api_key()
    if not api_key:
        return payload, 'TMDB API key is missing.'

    details = None
    last_error = None
    tmdb_id = str(payload.get('tmdb_id') or '').strip()
    imdb_id = str(payload.get('imdb_id') or '').strip()

    if tmdb_id:
        details, last_error = _tmdb_fetch_details('movie', tmdb_id, api_key=api_key)

    if details is None and imdb_id:
        candidate, last_error = _tmdb_find_by_imdb_id(
            imdb_id,
            media_type='movie',
            api_key=api_key,
        )
        if candidate and candidate.get('id'):
            details, last_error = _tmdb_fetch_details(
                'movie',
                str(candidate.get('id')),
                api_key=api_key,
            )

    if details is None:
        if prefer_existing:
            search_title = (
                str(payload.get('title') or '').strip()
                or str(title or '').strip()
            )
            search_year = _as_year(payload.get('year')) or year
        else:
            search_title = (
                str(title or '').strip()
                or str(payload.get('title') or '').strip()
            )
            search_year = year or _as_year(payload.get('year'))
        candidate, last_error = _tmdb_search(
            'movie',
            search_title,
            year=search_year,
            api_key=api_key,
        )
        if candidate and candidate.get('id'):
            details, last_error = _tmdb_fetch_details(
                'movie',
                str(candidate.get('id')),
                api_key=api_key,
            )

    if not isinstance(details, dict):
        return payload, last_error

    genres = [
        str(entry.get('name')).strip()
        for entry in (details.get('genres') or [])
        if isinstance(entry, dict) and str(entry.get('name') or '').strip()
    ]
    runtime_minutes = _as_year(details.get('runtime'))

    external_ids = (
        details.get('external_ids')
        if isinstance(details.get('external_ids'), dict)
        else {}
    )
    values = {
        'title': str(details.get('title') or '').strip(),
        'description': str(details.get('overview') or '').strip(),
        'year': _parse_release_year(details.get('release_date')),
        'rating': _rating_to_text(details.get('vote_average')),
        'genres': genres,
        'poster_url': _build_tmdb_image_url(details.get('poster_path')),
        'backdrop_url': _build_tmdb_image_url(details.get('backdrop_path')),
        'tmdb_id': str(details.get('id') or '').strip(),
        'imdb_id': str(external_ids.get('imdb_id') or '').strip(),
    }
    if runtime_minutes and runtime_minutes > 0:
        values['duration_secs'] = runtime_minutes * 60
    _apply_metadata_values(
        payload,
        values,
        prefer_existing=prefer_existing,
    )

    return payload, None


def enrich_series_metadata_with_tmdb(
    metadata: dict | None,
    *,
    title: str,
    year: Optional[int] = None,
    prefer_existing: bool = True,
) -> tuple[dict, Optional[str]]:
    payload = dict(metadata or {})
    api_key = _get_tmdb_api_key()
    if not api_key:
        return payload, 'TMDB API key is missing.'

    details = None
    last_error = None
    tmdb_id = str(payload.get('tmdb_id') or '').strip()

    if tmdb_id:
        details, last_error = _tmdb_fetch_details('tv', tmdb_id, api_key=api_key)

    if details is None:
        if prefer_existing:
            search_title = (
                str(payload.get('title') or '').strip()
                or str(title or '').strip()
            )
            search_year = _as_year(payload.get('year')) or year
        else:
            search_title = (
                str(title or '').strip()
                or str(payload.get('title') or '').strip()
            )
            search_year = year or _as_year(payload.get('year'))
        candidate, last_error = _tmdb_search(
            'tv',
            search_title,
            year=search_year,
            api_key=api_key,
        )
        if candidate and candidate.get('id'):
            details, last_error = _tmdb_fetch_details(
                'tv',
                str(candidate.get('id')),
                api_key=api_key,
            )

    if not isinstance(details, dict):
        return payload, last_error

    genres = [
        str(entry.get('name')).strip()
        for entry in (details.get('genres') or [])
        if isinstance(entry, dict) and str(entry.get('name') or '').strip()
    ]
    runtime_entries = details.get('episode_run_time') or []
    runtime_minutes = None
    if isinstance(runtime_entries, list) and runtime_entries:
        runtime_minutes = _as_year(runtime_entries[0])

    external_ids = (
        details.get('external_ids')
        if isinstance(details.get('external_ids'), dict)
        else {}
    )
    values = {
        'title': str(details.get('name') or '').strip(),
        'description': str(details.get('overview') or '').strip(),
        'year': _parse_release_year(details.get('first_air_date')),
        'rating': _rating_to_text(details.get('vote_average')),
        'genres': genres,
        'poster_url': _build_tmdb_image_url(details.get('poster_path')),
        'backdrop_url': _build_tmdb_image_url(details.get('backdrop_path')),
        'tmdb_id': str(details.get('id') or '').strip(),
        'imdb_id': str(external_ids.get('imdb_id') or '').strip(),
    }
    if runtime_minutes and runtime_minutes > 0:
        values['duration_secs'] = runtime_minutes * 60
    _apply_metadata_values(
        payload,
        values,
        prefer_existing=prefer_existing,
    )

    return payload, None


def enrich_episode_metadata_with_tmdb(
    metadata: dict | None,
    *,
    series_tmdb_id: Optional[str],
    series_title: str,
    series_year: Optional[int],
    season_number: Optional[int],
    episode_number: Optional[int],
    prefer_existing: bool = True,
) -> tuple[dict, Optional[str]]:
    payload = dict(metadata or {})
    api_key = _get_tmdb_api_key()
    if not api_key:
        return payload, 'TMDB API key is missing.'

    if season_number is None or episode_number is None:
        return payload, 'Episode numbers are required for TMDB lookup.'

    tv_id = str(series_tmdb_id or '').strip()
    last_error = None
    if not tv_id:
        candidate, last_error = _tmdb_search(
            'tv',
            str(series_title or '').strip(),
            year=series_year,
            api_key=api_key,
        )
        if candidate and candidate.get('id'):
            tv_id = str(candidate.get('id'))

    if not tv_id:
        return payload, last_error or 'TMDB series lookup returned no matches.'

    details, last_error = _tmdb_fetch_episode_details(
        tv_id,
        season_number=int(season_number),
        episode_number=int(episode_number),
        api_key=api_key,
    )
    if not isinstance(details, dict):
        return payload, last_error

    runtime_minutes = _as_year(details.get('runtime'))
    external_ids = (
        details.get('external_ids')
        if isinstance(details.get('external_ids'), dict)
        else {}
    )
    values = {
        'title': str(details.get('name') or '').strip(),
        'description': str(details.get('overview') or '').strip(),
        'rating': _rating_to_text(details.get('vote_average')),
        'year': _parse_release_year(details.get('air_date')),
        'air_date': str(details.get('air_date') or '').strip(),
        'poster_url': _build_tmdb_image_url(details.get('still_path')),
        'tmdb_id': str(details.get('id') or '').strip(),
        'imdb_id': str(external_ids.get('imdb_id') or '').strip(),
    }
    if runtime_minutes and runtime_minutes > 0:
        values['duration_secs'] = runtime_minutes * 60
    _apply_metadata_values(
        payload,
        values,
        prefer_existing=prefer_existing,
    )

    return payload, None


def _is_http_url(value: str | None) -> bool:
    if not value:
        return False
    return value.startswith('http://') or value.startswith('https://')


def _normalize_xml_tag(tag: Any) -> str:
    if not isinstance(tag, str):
        return ''
    return tag.rsplit('}', 1)[-1].lower()


def _safe_xml_text(node: ET.Element | None) -> Optional[str]:
    if node is None:
        return None
    text = (node.text or '').strip()
    return text or None


def _find_child_text(node: ET.Element, *tags: str) -> Optional[str]:
    target = {tag.lower() for tag in tags if tag}
    for child in list(node):
        if _normalize_xml_tag(child.tag) in target:
            value = _safe_xml_text(child)
            if value:
                return value
    return None


def _parse_xml_int(value: str | None) -> Optional[int]:
    if not value:
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _parse_xml_float(value: str | None) -> Optional[float]:
    if not value:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _nfo_list(root: ET.Element, tag: str) -> list[str]:
    results = []
    target = tag.lower()
    for node in root.iter():
        if _normalize_xml_tag(node.tag) != target:
            continue
        text = _safe_xml_text(node)
        if text and text not in results:
            results.append(text)
    return results


def _nfo_unique_ids(root: ET.Element) -> tuple[Optional[str], Optional[str]]:
    imdb_id = None
    tmdb_id = None

    for node in root.iter():
        if _normalize_xml_tag(node.tag) != 'uniqueid':
            continue
        value = _safe_xml_text(node)
        if not value:
            continue
        id_type = str((node.attrib or {}).get('type') or '').strip().lower()
        if id_type in {'imdb', 'imdb_id'} and not imdb_id:
            imdb_id = value
        elif id_type in {'tmdb', 'themoviedb'} and not tmdb_id:
            tmdb_id = value
        elif not imdb_id and value.startswith('tt'):
            imdb_id = value
        elif not tmdb_id and value.isdigit():
            tmdb_id = value

    if not imdb_id:
        imdb_id = _find_child_text(root, 'imdbid')
    if not tmdb_id:
        tmdb_id = _find_child_text(root, 'tmdbid')

    return imdb_id, tmdb_id


def _nfo_rating(root: ET.Element) -> Optional[str]:
    # Prefer numeric ratings from <rating>, <userrating>, then <value>.
    rating = _find_child_text(root, 'rating', 'userrating')
    if rating:
        normalized = _parse_xml_float(rating)
        if normalized is not None:
            return str(normalized).rstrip('0').rstrip('.')

    for node in root.iter():
        if _normalize_xml_tag(node.tag) != 'rating':
            continue
        value = _find_child_text(node, 'value')
        normalized = _parse_xml_float(value)
        if normalized is not None:
            return str(normalized).rstrip('0').rstrip('.')
    return None


def _nfo_runtime_secs(root: ET.Element) -> Optional[int]:
    runtime = _find_child_text(root, 'runtime')
    minutes = _parse_xml_int(runtime)
    if minutes and minutes > 0:
        return int(minutes * 60)
    return None


def _nfo_art(root: ET.Element) -> tuple[Optional[str], Optional[str]]:
    poster = None
    backdrop = None

    poster = _find_child_text(root, 'thumb')
    fanart = root.find('fanart')
    if fanart is not None:
        for child in list(fanart):
            if _normalize_xml_tag(child.tag) in {'thumb', 'fanart'}:
                value = _safe_xml_text(child)
                if value:
                    backdrop = value
                    break

    if not backdrop:
        backdrop = _find_child_text(root, 'fanart', 'backdrop')
    return poster, backdrop


def _strip_xml_preamble(payload: str) -> str:
    if not payload:
        return ''
    value = payload.lstrip('\ufeff').strip()
    if value.startswith('<?xml'):
        idx = value.find('?>')
        if idx != -1:
            value = value[idx + 2 :].strip()
    return value


def _extract_nfo_root_xml(payload: str) -> Optional[str]:
    cleaned = _strip_xml_preamble(payload)
    if not cleaned:
        return None
    lower = cleaned.lower()
    for tag in ('movie', 'tvshow', 'episodedetails', 'episode'):
        start = lower.find(f'<{tag}')
        if start == -1:
            continue
        end = lower.find(f'</{tag}>', start)
        if end == -1:
            continue
        end += len(f'</{tag}>')
        return cleaned[start:end]
    return cleaned


def _parse_nfo_roots(nfo_path: str) -> tuple[list[ET.Element], Optional[str]]:
    try:
        with open(nfo_path, 'r', encoding='utf-8', errors='replace') as handle:
            payload = handle.read()
    except OSError as exc:
        return [], f'Unable to read NFO: {exc}'

    xml_payload = _extract_nfo_root_xml(payload)
    if not xml_payload:
        return [], 'NFO is empty.'

    roots: list[ET.Element] = []
    try:
        root = ET.fromstring(xml_payload)
        roots.append(root)
    except ET.ParseError:
        wrapped = f'<root>{xml_payload}</root>'
        try:
            wrapper = ET.fromstring(wrapped)
        except ET.ParseError as exc:
            return [], f'Invalid XML: {exc}'
        roots.extend(list(wrapper))

    return roots, None


def _find_nfo_in_directory(
    directory: str,
    *,
    preferred_names: list[str],
    allow_single_fallback: bool = True,
) -> Optional[str]:
    try:
        entries = [entry for entry in os.listdir(directory) if entry.lower().endswith('.nfo')]
    except OSError:
        return None

    entries_by_lower = {entry.lower(): entry for entry in entries}
    for name in preferred_names:
        matched = entries_by_lower.get(name.lower())
        if matched:
            return os.path.join(directory, matched)

    if allow_single_fallback and len(entries) == 1:
        return os.path.join(directory, entries[0])
    return None


def _iter_parent_dirs(start_dir: str, stop_dir: Optional[str] = None):
    current = os.path.abspath(os.path.expanduser(start_dir))
    stop = os.path.abspath(os.path.expanduser(stop_dir)) if stop_dir else None

    while True:
        yield current
        if stop and os.path.normcase(current) == os.path.normcase(stop):
            break
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


def find_local_artwork_files(directory: str | None) -> tuple[Optional[str], Optional[str]]:
    if not directory:
        return None, None
    try:
        entries = [entry for entry in os.listdir(directory) if entry]
    except OSError:
        return None, None

    entries_by_lower = {entry.lower(): entry for entry in entries}
    poster_name = entries_by_lower.get('poster.jpg')
    fanart_name = entries_by_lower.get('fanart.jpg')

    poster_path = os.path.join(directory, poster_name) if poster_name else None
    fanart_path = os.path.join(directory, fanart_name) if fanart_name else None
    return poster_path, fanart_path


def _resolve_artwork_path(
    value: Optional[str],
    *,
    directory: str,
) -> Optional[str]:
    if not value:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    if _is_http_url(normalized):
        return normalized
    if os.path.isabs(normalized):
        return normalized if os.path.exists(normalized) else None
    candidate = os.path.join(directory, normalized)
    return candidate if os.path.exists(candidate) else None


def _build_metadata_payload(root: ET.Element, *, directory: str, fallback_title: str) -> dict:
    imdb_id, tmdb_id = _nfo_unique_ids(root)
    title = _find_child_text(root, 'title', 'originaltitle') or fallback_title
    description = _find_child_text(root, 'plot', 'outline') or ''
    rating = _nfo_rating(root) or ''
    release_year = _parse_xml_int(_find_child_text(root, 'year'))
    genres = _nfo_list(root, 'genre')
    poster, backdrop = _nfo_art(root)
    poster = _resolve_artwork_path(poster, directory=directory)
    backdrop = _resolve_artwork_path(backdrop, directory=directory)
    runtime_secs = _nfo_runtime_secs(root)

    local_poster, local_backdrop = find_local_artwork_files(directory)
    if local_poster:
        poster = local_poster
    if local_backdrop:
        backdrop = local_backdrop

    return {
        'title': title,
        'description': description,
        'rating': rating,
        'year': release_year,
        'genres': genres,
        'poster_url': poster,
        'backdrop_url': backdrop,
        'tmdb_id': tmdb_id,
        'imdb_id': imdb_id,
        'duration_secs': runtime_secs,
    }


def parse_nfo_episode_entries(nfo_path: str) -> tuple[list[dict[str, Any]], Optional[str]]:
    roots, error = _parse_nfo_roots(nfo_path)
    if error:
        return [], error

    entries: list[dict[str, Any]] = []
    for root in roots:
        if _normalize_xml_tag(root.tag) not in {'episodedetails', 'episode'}:
            continue
        entries.append(
            {
                'season': _parse_xml_int(_find_child_text(root, 'season', 'displayseason')),
                'episode': _parse_xml_int(_find_child_text(root, 'episode', 'displayepisode')),
                'title': _find_child_text(root, 'title', 'originaltitle'),
                'plot': _find_child_text(root, 'plot', 'outline'),
            }
        )
    return entries, None


def find_movie_nfo_metadata(file_path: str) -> tuple[Optional[dict], Optional[str]]:
    directory = os.path.dirname(file_path)
    base_name = os.path.splitext(os.path.basename(file_path))[0]
    nfo_path = _find_nfo_in_directory(
        directory,
        preferred_names=[f'{base_name}.nfo', 'movie.nfo'],
        allow_single_fallback=True,
    )
    if not nfo_path:
        return None, 'No movie NFO found.'

    roots, error = _parse_nfo_roots(nfo_path)
    if error:
        return None, error

    root = next((entry for entry in roots if _normalize_xml_tag(entry.tag) == 'movie'), roots[0] if roots else None)
    if root is None:
        return None, 'Movie NFO did not contain a usable root node.'
    return _build_metadata_payload(root, directory=directory, fallback_title=base_name), None


def find_series_nfo_metadata(file_path: str, *, base_path: Optional[str] = None) -> tuple[Optional[dict], Optional[str]]:
    directory = os.path.dirname(file_path)
    base_name = os.path.splitext(os.path.basename(file_path))[0]

    for parent in _iter_parent_dirs(directory, stop_dir=base_path):
        nfo_path = _find_nfo_in_directory(
            parent,
            preferred_names=['tvshow.nfo'],
            allow_single_fallback=False,
        )
        if not nfo_path:
            continue
        roots, error = _parse_nfo_roots(nfo_path)
        if error:
            return None, error
        root = next(
            (entry for entry in roots if _normalize_xml_tag(entry.tag) == 'tvshow'),
            roots[0] if roots else None,
        )
        if root is None:
            return None, 'TV show NFO did not contain a usable root node.'
        return _build_metadata_payload(root, directory=parent, fallback_title=base_name), None

    return None, 'No tvshow.nfo found.'


def find_episode_nfo_metadata(
    file_path: str,
    *,
    season_number: Optional[int] = None,
    episode_number: Optional[int] = None,
) -> tuple[Optional[dict], Optional[str]]:
    directory = os.path.dirname(file_path)
    base_name = os.path.splitext(os.path.basename(file_path))[0]
    nfo_path = _find_nfo_in_directory(
        directory,
        preferred_names=[f'{base_name}.nfo', 'episode.nfo'],
        allow_single_fallback=False,
    )
    if not nfo_path:
        return None, 'No episode NFO found.'

    roots, error = _parse_nfo_roots(nfo_path)
    if error:
        return None, error

    candidates = [entry for entry in roots if _normalize_xml_tag(entry.tag) in {'episodedetails', 'episode'}]
    if not candidates:
        return None, 'Episode NFO did not contain episode nodes.'

    selected = None
    for root in candidates:
        season = _parse_xml_int(_find_child_text(root, 'season', 'displayseason'))
        episode = _parse_xml_int(_find_child_text(root, 'episode', 'displayepisode'))
        if season_number is not None and season != season_number:
            continue
        if episode_number is not None and episode != episode_number:
            continue
        selected = root
        break
    if selected is None:
        selected = candidates[0]

    payload = _build_metadata_payload(selected, directory=directory, fallback_title=base_name)
    payload['season_number'] = _parse_xml_int(_find_child_text(selected, 'season', 'displayseason'))
    payload['episode_number'] = _parse_xml_int(_find_child_text(selected, 'episode', 'displayepisode'))
    return payload, None
