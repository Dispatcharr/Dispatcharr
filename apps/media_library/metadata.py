import logging
from typing import Any, Dict, Optional, Tuple

import requests
from dateutil import parser as date_parser
from django.core.cache import cache
from django.utils import timezone

from apps.media_library.models import ArtworkAsset, MediaItem
from apps.media_library.utils import normalize_title

logger = logging.getLogger(__name__)

IMAGE_BASE_URL = "https://image.tmdb.org/t/p/original"
MOVIEDB_SEARCH_URL = "https://movie-db.org/api.php"
MOVIEDB_EPISODE_URL = "https://movie-db.org/episode.php"
MOVIEDB_CREDITS_URL = "https://movie-db.org/credits.php"
METADATA_CACHE_TIMEOUT = 60 * 60 * 6
MOVIEDB_HEALTH_CACHE_KEY = "movie-db:health"
MOVIEDB_HEALTH_SUCCESS_TTL = 60 * 15
MOVIEDB_HEALTH_FAILURE_TTL = 60 * 2

_REQUESTS_SESSION = requests.Session()
_REQUESTS_SESSION.mount(
    "https://",
    requests.adapters.HTTPAdapter(pool_connections=20, pool_maxsize=40, max_retries=3),
)

_MOVIEDB_SEARCH_CACHE: dict[tuple[str, ...], tuple[dict | None, str | None]] = {}
_MOVIEDB_CREDITS_CACHE: dict[tuple[str, str], tuple[dict | None, str | None]] = {}

GENRE_ID_MAP: dict[int, str] = {
    12: "Adventure",
    14: "Fantasy",
    16: "Animation",
    18: "Drama",
    27: "Horror",
    28: "Action",
    35: "Comedy",
    36: "History",
    37: "Western",
    53: "Thriller",
    80: "Crime",
    99: "Documentary",
    878: "Science Fiction",
    9648: "Mystery",
    10402: "Music",
    10749: "Romance",
    10751: "Family",
    10752: "War",
    10759: "Action & Adventure",
    10762: "Kids",
    10763: "News",
    10764: "Reality",
    10765: "Sci-Fi & Fantasy",
    10766: "Soap",
    10767: "Talk",
    10768: "War & Politics",
    10770: "TV Movie",
}


def _get_library_metadata_prefs(media_item: MediaItem) -> dict[str, Any]:
    prefs: dict[str, Any] = {"language": None, "region": None}
    library = getattr(media_item, "library", None)
    if not library:
        return prefs

    prefs["language"] = (library.metadata_language or "").strip() or None
    prefs["region"] = (library.metadata_country or "").strip() or None

    options = library.metadata_options or {}
    if isinstance(options, dict):
        if options.get("language"):
            prefs["language"] = str(options["language"]).strip() or prefs["language"]
        if options.get("region"):
            prefs["region"] = str(options["region"]).strip() or prefs["region"]

    return prefs


def _metadata_cache_key(media_item: MediaItem, prefs: dict[str, Any] | None = None) -> str:
    normalized = normalize_title(media_item.title) or media_item.normalized_title or ""
    key_parts = [
        "movie-db",
        str(media_item.item_type or ""),
        normalized,
        str(media_item.release_year or ""),
    ]
    if media_item.movie_db_id:
        key_parts.append(f"id:{media_item.movie_db_id}")
    if media_item.item_type == MediaItem.TYPE_EPISODE:
        season = media_item.season_number or ""
        episode = media_item.episode_number or ""
        key_parts.append(f"s{season}e{episode}")
        parent = getattr(media_item, "parent", None)
        if parent and parent.movie_db_id:
            key_parts.append(f"parent:{parent.movie_db_id}")

    if prefs:
        language = (prefs.get("language") or "").strip()
        region = (prefs.get("region") or "").strip()
        if language or region:
            key_parts.append(f"lang:{language}")
            key_parts.append(f"region:{region}")

    return "media-metadata:" + ":".join(key_parts)


def build_image_url(path: Optional[str]) -> Optional[str]:
    if not path:
        return None
    return f"{IMAGE_BASE_URL}{path}"


def _to_serializable(obj):
    if isinstance(obj, dict):
        return {key: _to_serializable(value) for key, value in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_to_serializable(item) for item in obj]
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    return str(obj)


def check_movie_db_health(*, use_cache: bool = True) -> Tuple[bool, str | None]:
    if use_cache:
        cached = cache.get(MOVIEDB_HEALTH_CACHE_KEY)
        if cached is not None:
            return cached

    try:
        response = _REQUESTS_SESSION.get(
            MOVIEDB_SEARCH_URL,
            params={"type": "tv", "query": "The Simpsons"},
            timeout=5,
        )
    except requests.RequestException as exc:
        message = f"Movie-DB request failed: {exc}"
        cache.set(MOVIEDB_HEALTH_CACHE_KEY, (False, message), MOVIEDB_HEALTH_FAILURE_TTL)
        return False, message

    if response.status_code != 200:
        message = f"Movie-DB returned status {response.status_code}."
        cache.set(MOVIEDB_HEALTH_CACHE_KEY, (False, message), MOVIEDB_HEALTH_FAILURE_TTL)
        return False, message

    try:
        payload = response.json()
    except ValueError:
        message = "Movie-DB returned an unexpected response format."
        cache.set(MOVIEDB_HEALTH_CACHE_KEY, (False, message), MOVIEDB_HEALTH_FAILURE_TTL)
        return False, message

    results = []
    if isinstance(payload, dict):
        results = payload.get("results") or []
    elif isinstance(payload, list):
        results = payload

    if not results:
        message = "Movie-DB did not return any results."
        cache.set(MOVIEDB_HEALTH_CACHE_KEY, (False, message), MOVIEDB_HEALTH_FAILURE_TTL)
        return False, message

    cache.set(MOVIEDB_HEALTH_CACHE_KEY, (True, None), MOVIEDB_HEALTH_SUCCESS_TTL)
    return True, None


def _parse_release_year(value: Optional[str]) -> Optional[int]:
    if not value:
        return None
    try:
        return date_parser.parse(value).year
    except (ValueError, TypeError):
        return None


def _php_value_from_string(value: str):
    lowered = value.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered in {"null", ""}:
        return None
    try:
        if "." in value:
            return float(value)
        return int(value)
    except ValueError:
        return value


def _convert_numeric_container(value):
    if isinstance(value, dict):
        converted = {k: _convert_numeric_container(v) for k, v in value.items()}
        numeric = True
        indices: list[int] = []
        for key in converted.keys():
            try:
                indices.append(int(key))
            except (TypeError, ValueError):
                numeric = False
                break
        if numeric:
            return [converted[str(idx)] for idx in sorted(indices)]
        return converted
    if isinstance(value, list):
        return [_convert_numeric_container(item) for item in value]
    return value


def _parse_php_array_lines(lines: list[str], idx: int = 0):
    def parse_body(current_idx: int):
        result: dict[str, Any] = {}
        while current_idx < len(lines):
            token = lines[current_idx]
            if token == ")":
                return result, current_idx + 1
            if token.startswith("[") and "] =>" in token:
                key_part, value_part = token.split("] =>", 1)
                key = key_part[1:].strip()
                value = value_part.strip()
                if value == "Array":
                    sub_value, next_idx = _parse_php_array_lines(lines, current_idx + 1)
                    result[key] = sub_value
                    current_idx = next_idx
                    continue
                result[key] = _php_value_from_string(value)
            current_idx += 1
        return result, current_idx

    if idx >= len(lines):
        return {}, idx

    token = lines[idx]
    if token.lower() == "array":
        idx += 1
    if idx < len(lines) and lines[idx] == "(":
        idx += 1
        parsed, idx = parse_body(idx)
        return _convert_numeric_container(parsed), idx
    return {}, idx


def _parse_movie_db_php_response(payload: str) -> Optional[dict | list]:
    if not payload:
        return None
    stripped = payload.replace("<pre>", "").replace("</pre>", "").strip()
    if not stripped.lower().startswith("array"):
        return None
    lines = [line.strip() for line in stripped.splitlines() if line.strip()]
    parsed, _ = _parse_php_array_lines(lines, 0)
    return parsed


def _extract_imdb_id(payload: dict | None) -> Optional[str]:
    if not payload or not isinstance(payload, dict):
        return None
    for key in ("imdb_id", "imdbId", "imdbID"):
        value = payload.get(key)
        if value:
            return str(value)
    external = payload.get("external_ids") or {}
    if isinstance(external, dict):
        for key in ("imdb_id", "imdbId", "imdbID"):
            value = external.get(key)
            if value:
                return str(value)
    return None


def _candidate_year(payload: dict) -> Optional[int]:
    release_date = (
        payload.get("release_date")
        or payload.get("first_air_date")
        or payload.get("air_date")
    )
    return _parse_release_year(release_date)


def _movie_db_title(payload: dict) -> str:
    return (
        payload.get("title")
        or payload.get("name")
        or payload.get("original_title")
        or payload.get("original_name")
        or ""
    )


def _select_movie_db_candidate(
    results: list[dict],
    title: str,
    *,
    year: Optional[int] = None,
    prefs: dict[str, Any] | None = None,
) -> Optional[dict]:
    if not results:
        return None
    normalized_query = normalize_title(title)
    language = (prefs or {}).get("language")
    region = (prefs or {}).get("region")
    best_score = None
    best_result = None
    for idx, result in enumerate(results):
        if not isinstance(result, dict):
            continue
        normalized_title = normalize_title(_movie_db_title(result))
        score = 0
        if normalized_query and normalized_title == normalized_query:
            score += 6
        elif normalized_query and (
            normalized_query in normalized_title or normalized_title in normalized_query
        ):
            score += 3
        if year:
            candidate_year = _candidate_year(result)
            if candidate_year and candidate_year == year:
                score += 2
        if language and result.get("original_language") == language:
            score += 2
        if region:
            origin_country = result.get("origin_country") or []
            if isinstance(origin_country, str):
                origin_country = [origin_country]
            if region in origin_country:
                score += 2
        if result.get("poster_path"):
            score += 2
        elif result.get("backdrop_path"):
            score += 1
        # Keep earlier results when scores tie.
        score = (score, -idx)
        if best_score is None or score > best_score:
            best_score = score
            best_result = result
    return best_result or (results[0] if results else None)


def _movie_db_search(
    media_type: str,
    title: str,
    *,
    year: Optional[int] = None,
    prefs: dict[str, Any] | None = None,
) -> tuple[Optional[dict], Optional[str]]:
    language = (prefs or {}).get("language") or ""
    region = (prefs or {}).get("region") or ""
    normalized_key = (
        media_type,
        (title or "").strip().lower(),
        str(year or ""),
        str(language),
        str(region),
    )
    if normalized_key in _MOVIEDB_SEARCH_CACHE:
        return _MOVIEDB_SEARCH_CACHE[normalized_key]

    try:
        response = _REQUESTS_SESSION.get(
            MOVIEDB_SEARCH_URL,
            params={"type": media_type, "query": title},
            timeout=6,
        )
    except requests.RequestException as exc:
        message = f"Movie-DB search failed: {exc}"
        logger.warning(message)
        _MOVIEDB_SEARCH_CACHE[normalized_key] = (None, message)
        return None, message

    if response.status_code != 200:
        message = f"Movie-DB search returned status {response.status_code}."
        logger.debug(message)
        _MOVIEDB_SEARCH_CACHE[normalized_key] = (None, message)
        return None, message

    try:
        payload = response.json()
    except ValueError:
        message = "Movie-DB search returned an unexpected response format."
        logger.debug(message)
        _MOVIEDB_SEARCH_CACHE[normalized_key] = (None, message)
        return None, message

    results = []
    if isinstance(payload, dict):
        results = payload.get("results") or []
    elif isinstance(payload, list):
        results = payload

    if not results:
        message = "Movie-DB search returned no matches."
        logger.debug(message)
        _MOVIEDB_SEARCH_CACHE[normalized_key] = (None, message)
        return None, message

    candidate = _select_movie_db_candidate(
        results, title, year=year, prefs=prefs
    )
    _MOVIEDB_SEARCH_CACHE[normalized_key] = (candidate, None)
    return candidate, None


def _map_genre_ids(genre_ids: Any) -> list[str]:
    if not genre_ids or not isinstance(genre_ids, (list, tuple, set)):
        return []
    genres: list[str] = []
    seen: set[str] = set()
    for entry in genre_ids:
        try:
            genre_id = int(entry)
        except (TypeError, ValueError):
            continue
        name = GENRE_ID_MAP.get(genre_id)
        if not name or name in seen:
            continue
        genres.append(name)
        seen.add(name)
    return genres


def _movie_db_fetch_credits(
    media_type: str, content_id: Any
) -> tuple[Optional[dict], Optional[str]]:
    if not content_id:
        return None, "Movie-DB credits require an id."
    normalized_key = (media_type, str(content_id))
    if normalized_key in _MOVIEDB_CREDITS_CACHE:
        return _MOVIEDB_CREDITS_CACHE[normalized_key]

    params = {"id": content_id, "media_type": media_type}
    try:
        response = _REQUESTS_SESSION.get(
            MOVIEDB_CREDITS_URL,
            params=params,
            timeout=6,
        )
    except requests.RequestException as exc:
        message = f"Movie-DB credits lookup failed: {exc}"
        logger.warning(message)
        _MOVIEDB_CREDITS_CACHE[normalized_key] = (None, message)
        return None, message

    if response.status_code != 200 and media_type == "movie":
        try:
            response = _REQUESTS_SESSION.get(
                MOVIEDB_CREDITS_URL,
                params={"movie_id": content_id},
                timeout=6,
            )
        except requests.RequestException as exc:
            message = f"Movie-DB credits lookup failed: {exc}"
            logger.warning(message)
            _MOVIEDB_CREDITS_CACHE[normalized_key] = (None, message)
            return None, message

    if response.status_code != 200:
        message = f"Movie-DB credits returned status {response.status_code}."
        logger.debug(message)
        _MOVIEDB_CREDITS_CACHE[normalized_key] = (None, message)
        return None, message

    try:
        payload = response.json()
    except ValueError:
        message = "Movie-DB credits returned an unexpected response format."
        logger.debug(message)
        _MOVIEDB_CREDITS_CACHE[normalized_key] = (None, message)
        return None, message

    if not isinstance(payload, dict):
        message = "Movie-DB credits returned an unexpected payload."
        logger.debug(message)
        _MOVIEDB_CREDITS_CACHE[normalized_key] = (None, message)
        return None, message

    _MOVIEDB_CREDITS_CACHE[normalized_key] = (payload, None)
    return payload, None


def _normalize_credits(payload: dict | None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not payload:
        return [], []
    cast_entries = payload.get("cast") or []
    crew_entries = payload.get("crew") or []

    cast: list[dict[str, Any]] = []
    for member in cast_entries[:12]:
        if not isinstance(member, dict):
            continue
        name = member.get("name") or member.get("original_name")
        if not name:
            continue
        cast.append(
            {
                "name": name,
                "character": member.get("character"),
                "profile_url": build_image_url(member.get("profile_path")),
            }
        )

    crew: list[dict[str, Any]] = []
    for member in crew_entries[:15]:
        if not isinstance(member, dict):
            continue
        name = member.get("name") or member.get("original_name")
        if not name:
            continue
        crew.append(
            {
                "name": name,
                "job": member.get("job"),
                "department": member.get("department"),
                "profile_url": build_image_url(member.get("profile_path")),
            }
        )

    return cast, crew


def _movie_db_fetch_episode_details(
    tv_id: Any, season: int, episode: int
) -> tuple[Optional[dict], Optional[str]]:
    try:
        response = _REQUESTS_SESSION.get(
            MOVIEDB_EPISODE_URL,
            params={"tvId": tv_id, "season": season, "episode": episode},
            timeout=6,
        )
    except requests.RequestException as exc:
        message = f"Movie-DB episode lookup failed: {exc}"
        logger.warning(message)
        return None, message

    if response.status_code != 200:
        message = f"Movie-DB episode endpoint returned status {response.status_code}."
        logger.debug(message)
        return None, message

    parsed = _parse_movie_db_php_response(response.text)
    if not parsed or not isinstance(parsed, dict):
        message = "Movie-DB episode endpoint returned an unexpected payload."
        logger.debug(message)
        return None, message

    return _convert_numeric_container(parsed), None


def fetch_movie_db_metadata(
    media_item: MediaItem,
    *,
    use_cache: bool = True,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    if media_item.item_type not in {
        MediaItem.TYPE_MOVIE,
        MediaItem.TYPE_SHOW,
        MediaItem.TYPE_EPISODE,
    }:
        return None, "Movie-DB does not support this media type."

    prefs = _get_library_metadata_prefs(media_item)
    cache_key = _metadata_cache_key(media_item, prefs)
    if use_cache:
        cached = cache.get(cache_key)
        if cached:
            return cached, None

    if media_item.item_type == MediaItem.TYPE_MOVIE:
        candidate, message = _movie_db_search(
            "movie",
            media_item.title,
            year=media_item.release_year,
            prefs=prefs,
        )
        if not candidate:
            return None, message

        movie_id = candidate.get("id")
        genres = _map_genre_ids(candidate.get("genre_ids"))
        credits_payload, _ = _movie_db_fetch_credits("movie", movie_id)
        cast, crew = _normalize_credits(credits_payload)
        imdb_id = _extract_imdb_id(candidate)
        release_date = candidate.get("release_date") or candidate.get("first_air_date")
        release_year = _parse_release_year(release_date) or media_item.release_year
        metadata = _to_serializable(
            {
                "movie_db_id": str(movie_id or media_item.movie_db_id or ""),
                "imdb_id": imdb_id,
                "title": candidate.get("title")
                or candidate.get("name")
                or media_item.title,
                "synopsis": candidate.get("overview") or media_item.synopsis,
                "tagline": candidate.get("tagline") or media_item.tagline,
                "release_year": release_year,
                "poster": build_image_url(candidate.get("poster_path")),
                "backdrop": build_image_url(candidate.get("backdrop_path")),
                "runtime_minutes": candidate.get("runtime"),
                "genres": genres,
                "cast": cast,
                "crew": crew,
                "source": "movie-db",
                "raw": candidate,
            }
        )
        if use_cache:
            cache.set(cache_key, metadata, METADATA_CACHE_TIMEOUT)
        return metadata, None

    if media_item.item_type == MediaItem.TYPE_SHOW:
        candidate, message = _movie_db_search(
            "tv",
            media_item.title,
            year=media_item.release_year,
            prefs=prefs,
        )
        if not candidate:
            return None, message
        tv_id = candidate.get("id")
        genres = _map_genre_ids(candidate.get("genre_ids"))
        credits_payload, _ = _movie_db_fetch_credits("tv", tv_id)
        cast, crew = _normalize_credits(credits_payload)
        imdb_id = _extract_imdb_id(candidate)
        release_date = candidate.get("first_air_date") or candidate.get("release_date")
        release_year = _parse_release_year(release_date) or media_item.release_year
        metadata = _to_serializable(
            {
                "movie_db_id": str(candidate.get("id") or media_item.movie_db_id or ""),
                "imdb_id": imdb_id,
                "title": candidate.get("name")
                or candidate.get("title")
                or media_item.title,
                "synopsis": candidate.get("overview") or media_item.synopsis,
                "tagline": candidate.get("tagline") or media_item.tagline,
                "release_year": release_year,
                "poster": build_image_url(candidate.get("poster_path")),
                "backdrop": build_image_url(candidate.get("backdrop_path")),
                "runtime_minutes": candidate.get("episode_run_time"),
                "genres": genres,
                "cast": cast,
                "crew": crew,
                "movie_db_tv_id": str(tv_id) if tv_id is not None else None,
                "source": "movie-db",
                "raw": candidate,
            }
        )
        if use_cache:
            cache.set(cache_key, metadata, METADATA_CACHE_TIMEOUT)
        return metadata, None

    parent_series = media_item.parent or MediaItem.objects.filter(
        pk=media_item.parent_id
    ).first()
    if not parent_series:
        return None, "Unable to determine parent series for episode."

    tv_id = parent_series.movie_db_id or None
    if not tv_id and isinstance(parent_series.metadata, dict):
        tv_id = parent_series.metadata.get("movie_db_tv_id")
        if tv_id and not parent_series.movie_db_id:
            parent_series.movie_db_id = str(tv_id)
            parent_series.save(update_fields=["movie_db_id", "updated_at"])

    if not tv_id:
        series_candidate, message = _movie_db_search(
            "tv",
            parent_series.title,
            year=parent_series.release_year or media_item.release_year,
            prefs=prefs,
        )
        if not series_candidate:
            return None, message
        tv_id = series_candidate.get("id")
        if tv_id is not None:
            tv_id_str = str(tv_id)
            update_fields = []
            if not parent_series.movie_db_id:
                parent_series.movie_db_id = tv_id_str
                update_fields.append("movie_db_id")
            if isinstance(parent_series.metadata, dict):
                updated_metadata = dict(parent_series.metadata)
            else:
                updated_metadata = {}
            updated_metadata["movie_db_tv_id"] = tv_id_str
            parent_series.metadata = updated_metadata
            update_fields.append("metadata")
            update_fields.append("updated_at")
            parent_series.save(update_fields=update_fields)

    if tv_id is None:
        return None, "Movie-DB did not return a tvId for this series."

    if media_item.season_number is None or media_item.episode_number is None:
        return None, "Episode numbers are required for Movie-DB lookup."

    try:
        season_number = int(media_item.season_number)
        episode_number = int(media_item.episode_number)
    except (TypeError, ValueError):
        return None, "Episode numbers are required for Movie-DB lookup."

    episode_details, message = _movie_db_fetch_episode_details(
        tv_id, season_number, episode_number
    )
    if not episode_details:
        return None, message

    release_year = (
        _parse_release_year(episode_details.get("air_date"))
        or media_item.release_year
    )
    guest_stars = episode_details.get("guest_stars") or []
    crew_entries = episode_details.get("crew") or []

    cast: list[dict[str, Any]] = []
    for star in guest_stars:
        if not isinstance(star, dict):
            continue
        name = star.get("name") or star.get("original_name")
        if not name:
            continue
        cast.append(
            {
                "name": name,
                "character": star.get("character"),
                "profile_url": build_image_url(star.get("profile_path")),
            }
        )

    crew: list[dict[str, Any]] = []
    for member in crew_entries:
        if not isinstance(member, dict):
            continue
        name = member.get("name") or member.get("original_name")
        if not name:
            continue
        crew.append(
            {
                "name": name,
                "job": member.get("job"),
                "department": member.get("department"),
                "profile_url": build_image_url(member.get("profile_path")),
            }
        )

    metadata = _to_serializable(
        {
            "movie_db_id": str(episode_details.get("id") or media_item.movie_db_id or ""),
            "title": episode_details.get("name") or media_item.title,
            "synopsis": episode_details.get("overview") or media_item.synopsis,
            "release_year": release_year,
            "poster": build_image_url(episode_details.get("still_path")),
            "backdrop": build_image_url(episode_details.get("still_path")),
            "runtime_minutes": episode_details.get("runtime"),
            "genres": [],
            "cast": cast,
            "crew": crew,
            "movie_db_tv_id": str(tv_id) if tv_id is not None else None,
            "source": "movie-db",
            "raw": episode_details,
        }
    )

    if use_cache:
        cache.set(cache_key, metadata, METADATA_CACHE_TIMEOUT)
    return metadata, None


def apply_metadata(media_item: MediaItem, metadata: Dict[str, Any]) -> MediaItem:
    changed = False
    update_fields: list[str] = []

    movie_db_id = metadata.get("movie_db_id")
    if movie_db_id and movie_db_id != media_item.movie_db_id:
        media_item.movie_db_id = movie_db_id
        update_fields.append("movie_db_id")
        changed = True

    imdb_id = metadata.get("imdb_id")
    if imdb_id and imdb_id != media_item.imdb_id:
        media_item.imdb_id = imdb_id
        update_fields.append("imdb_id")
        changed = True

    title = metadata.get("title")
    if title and title != media_item.title:
        media_item.title = title
        update_fields.append("title")
        changed = True

    synopsis = metadata.get("synopsis")
    if synopsis and synopsis != media_item.synopsis:
        media_item.synopsis = synopsis
        update_fields.append("synopsis")
        changed = True

    tagline = metadata.get("tagline")
    if tagline and tagline != media_item.tagline:
        media_item.tagline = tagline
        update_fields.append("tagline")
        changed = True

    release_year = metadata.get("release_year")
    if release_year and release_year != media_item.release_year:
        try:
            media_item.release_year = int(release_year)
        except (TypeError, ValueError):
            media_item.release_year = media_item.release_year
        else:
            changed = True
            update_fields.append("release_year")

    runtime_minutes = metadata.get("runtime_minutes")
    if runtime_minutes:
        new_runtime_ms = int(float(runtime_minutes) * 60 * 1000)
        if media_item.runtime_ms != new_runtime_ms:
            media_item.runtime_ms = new_runtime_ms
            update_fields.append("runtime_ms")
            changed = True

    genres = metadata.get("genres")
    if genres and genres != media_item.genres:
        media_item.genres = genres
        update_fields.append("genres")
        changed = True

    cast = metadata.get("cast")
    if cast and cast != media_item.cast:
        media_item.cast = cast
        update_fields.append("cast")
        changed = True

    crew = metadata.get("crew")
    if crew and crew != media_item.crew:
        media_item.crew = crew
        update_fields.append("crew")
        changed = True

    poster = metadata.get("poster")
    if poster and poster != media_item.poster_url:
        media_item.poster_url = poster
        update_fields.append("poster_url")
        changed = True

    backdrop = metadata.get("backdrop")
    if backdrop and backdrop != media_item.backdrop_url:
        media_item.backdrop_url = backdrop
        update_fields.append("backdrop_url")
        changed = True

    raw_payload = metadata.get("raw")
    if raw_payload and raw_payload != media_item.metadata:
        media_item.metadata = raw_payload
        update_fields.append("metadata")
        changed = True

    new_source = metadata.get("source", media_item.metadata_source or "unknown")
    if new_source and new_source != media_item.metadata_source:
        media_item.metadata_source = new_source
        update_fields.append("metadata_source")
        changed = True

    if changed or not media_item.metadata_last_synced_at:
        media_item.metadata_last_synced_at = timezone.now()
        if "metadata_last_synced_at" not in update_fields:
            update_fields.append("metadata_last_synced_at")

    if update_fields:
        update_fields = list(dict.fromkeys(update_fields + ["updated_at"]))
        media_item.save(update_fields=update_fields)

    if poster:
        ArtworkAsset.objects.update_or_create(
            media_item=media_item,
            asset_type=ArtworkAsset.TYPE_POSTER,
            source=metadata.get("source", "movie-db"),
            defaults={"external_url": poster},
        )
    if backdrop:
        ArtworkAsset.objects.update_or_create(
            media_item=media_item,
            asset_type=ArtworkAsset.TYPE_BACKDROP,
            source=metadata.get("source", "movie-db"),
            defaults={"external_url": backdrop},
        )

    return media_item


def sync_metadata(media_item: MediaItem, *, force: bool = False) -> Optional[MediaItem]:
    movie_db_ok, movie_db_message = check_movie_db_health()
    if not movie_db_ok:
        if movie_db_message:
            logger.debug("Metadata sync skipped for %s: %s", media_item, movie_db_message)
        return None

    metadata, error = fetch_movie_db_metadata(media_item, use_cache=not force)
    if not metadata:
        if error:
            logger.debug("Metadata sync skipped for %s: %s", media_item, error)
        return None
    return apply_metadata(media_item, metadata)
