import logging
from typing import Any, Dict, Optional, Tuple

import requests
import tmdbsimple as tmdb
from dateutil import parser as date_parser
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from apps.media_library.models import ArtworkAsset, MediaItem
from core.models import CoreSettings

logger = logging.getLogger(__name__)

TMDB_API_KEY_SETTING = "tmdb-api-key"
TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p/original"
METADATA_CACHE_TIMEOUT = 60 * 60 * 6  # 6 hours
TMDB_VALIDATION_CACHE_SUCCESS_TTL = 60 * 30  # 30 minutes
TMDB_VALIDATION_CACHE_FAILURE_TTL = 60 * 5  # 5 minutes
MOVIEDB_SEARCH_URL = "https://movie-db.org/api.php"
MOVIEDB_HEALTH_CACHE_KEY = "movie-db:health"
MOVIEDB_HEALTH_SUCCESS_TTL = 60 * 15  # 15 minutes
MOVIEDB_HEALTH_FAILURE_TTL = 60 * 2  # 2 minutes
_REQUESTS_SESSION = requests.Session()
_REQUESTS_SESSION.mount(
    "https://",
    requests.adapters.HTTPAdapter(pool_connections=20, pool_maxsize=40, max_retries=3),
)
tmdb.REQUESTS_SESSION = _REQUESTS_SESSION


def validate_tmdb_api_key(api_key: str, *, use_cache: bool = True) -> tuple[bool, str | None]:
    """
    Validate a TMDB API key by calling the configuration endpoint.

    Returns a tuple of (is_valid, message). On success, message is None.
    """
    normalized_key = (api_key or "").strip()
    if not normalized_key:
        return False, "TMDB API key is required."

    cache_key = f"tmdb-key-validation:{normalized_key}"
    if use_cache:
        cached = cache.get(cache_key)
        if cached is not None:
            return cached.get("valid", False), cached.get("message")

    try:
        response = _REQUESTS_SESSION.get(
            "https://api.themoviedb.org/3/configuration",
            params={"api_key": normalized_key},
            timeout=5,
        )
    except requests.RequestException as exc:
        logger.warning("Unable to validate TMDB API key due to network error: %s", exc)
        message = "Could not reach TMDB to validate the API key."
        return False, message

    if response.status_code == 200:
        if use_cache:
            cache.set(
                cache_key,
                {"valid": True, "message": None},
                TMDB_VALIDATION_CACHE_SUCCESS_TTL,
            )
        return True, None

    if response.status_code == 401:
        message = "TMDB rejected the API key (HTTP 401 Unauthorized)."
    else:
        message = f"TMDB returned status {response.status_code} while validating the API key."

    if use_cache:
        cache.set(
            cache_key,
            {"valid": False, "message": message},
            TMDB_VALIDATION_CACHE_FAILURE_TTL,
        )
    return False, message


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


def get_tmdb_api_key() -> Optional[str]:
    # Prefer CoreSettings, fallback to environment variable
    try:
        setting = CoreSettings.objects.get(key=TMDB_API_KEY_SETTING)
        if setting.value:
            return setting.value.strip()
    except CoreSettings.DoesNotExist:
        pass

    return getattr(settings, "TMDB_API_KEY", None)


def _configure_tmdb(api_key: str | None) -> bool:
    if not api_key:
        logger.debug("TMDB API key missing; skipping remote metadata fetch")
        return False

    if tmdb.API_KEY != api_key:
        # we only set when changed
        tmdb.API_KEY = api_key
    return True


def build_image_url(path: Optional[str]) -> Optional[str]:
    if not path:
        return None
    return f"{TMDB_IMAGE_BASE}{path}"


def _to_serializable(obj):
    """Ensure TMDB data is safe to store in JSON fields."""
    if isinstance(obj, dict):
        return {key: _to_serializable(value) for key, value in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_to_serializable(item) for item in obj]
    # Keep primitive JSON types; convert everything else to string
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    return str(obj)


def fetch_tmdb_metadata(media_item: MediaItem) -> Optional[Dict[str, Any]]:
    api_key = get_tmdb_api_key()
    if not _configure_tmdb(api_key):
        return None

    normalized = (media_item.normalized_title or "").replace(" ", "_")
    cache_key_parts = [
        str(media_item.item_type),
        normalized,
        str(media_item.release_year or ""),
    ]
    if media_item.tmdb_id:
        cache_key_parts.append(f"id:{media_item.tmdb_id}")
    cache_key = f"media-metadata:{':'.join(cache_key_parts)}"
    cached = cache.get(cache_key)
    if cached:
        return cached

    info = None
    credits = None
    tmdb_id = media_item.tmdb_id

    if tmdb_id:
        try:
            lookup_id = int(tmdb_id)
        except (TypeError, ValueError):
            lookup_id = tmdb_id

        try:
            if media_item.is_movie:
                movie = tmdb.Movies(lookup_id)
                info = movie.info(append_to_response="credits,images")
                credits = info.get("credits", {})
            elif media_item.item_type == MediaItem.TYPE_SHOW:
                tv = tmdb.TV(lookup_id)
                info = tv.info(append_to_response="credits,images")
                credits = info.get("credits", {})
        except Exception:  # noqa: BLE001
            logger.exception(
                "Failed to retrieve TMDB info for %s using id %s", media_item, tmdb_id
            )
            info = None
            credits = None

    if info is None or credits is None:
        search = tmdb.Search()
        try:
            if media_item.is_movie:
                response = search.movie(query=media_item.title, year=media_item.release_year)
                results = response.get("results", [])
            elif media_item.item_type == MediaItem.TYPE_SHOW:
                response = search.tv(
                    query=media_item.title, first_air_date_year=media_item.release_year
                )
                results = response.get("results", [])
            else:
                results = []
        except Exception:  # noqa: BLE001
            logger.exception("TMDB lookup failed for %s", media_item)
            return None

        if not results:
            logger.debug("No TMDB matches found for %s", media_item.title)
            return None

        best_match = results[0]
        tmdb_id = best_match.get("id")
        if not tmdb_id:
            return None

        try:
            if media_item.is_movie:
                movie = tmdb.Movies(tmdb_id)
                info = movie.info(append_to_response="credits,images")
                credits = info.get("credits", {})
            elif media_item.item_type == MediaItem.TYPE_SHOW:
                tv = tmdb.TV(tmdb_id)
                info = tv.info(append_to_response="credits,images")
                credits = info.get("credits", {})
            else:
                return None
        except Exception:  # noqa: BLE001
            logger.exception("Failed to retrieve TMDB info for %s", media_item)
            return None

    if not tmdb_id and info:
        tmdb_id = info.get("id")

    genres = [g.get("name") for g in info.get("genres", []) if g.get("name")]
    runtime = None
    if media_item.is_movie:
        runtime = info.get("runtime")
    elif media_item.item_type == MediaItem.TYPE_SHOW:
        episode_run_time = info.get("episode_run_time") or []
        runtime = episode_run_time[0] if episode_run_time else None

    cast = []
    for cast_member in credits.get("cast", [])[:12]:
        name = cast_member.get("name")
        if not name:
            continue
        cast.append(
            {
                "name": name,
                "character": cast_member.get("character"),
                "profile_url": build_image_url(cast_member.get("profile_path")),
            }
        )

    crew = []
    for member in credits.get("crew", [])[:15]:
        name = member.get("name")
        job = member.get("job")
        if not name:
            continue
        crew.append(
            {
                "name": name,
                "job": job,
                "department": member.get("department"),
                "profile_url": build_image_url(member.get("profile_path")),
            }
        )

    release_year = media_item.release_year
    release_date = info.get("release_date") or info.get("first_air_date")
    if release_date:
        try:
            release_year = date_parser.parse(release_date).year
        except (ValueError, TypeError):  # noqa: PERF203
            release_year = media_item.release_year

    metadata = _to_serializable(
        {
            "tmdb_id": str(tmdb_id) if tmdb_id is not None else media_item.tmdb_id,
            "imdb_id": info.get("imdb_id") or media_item.imdb_id,
            "title": info.get("title") or info.get("name") or media_item.title,
            "synopsis": info.get("overview") or media_item.synopsis,
            "tagline": info.get("tagline") or media_item.tagline,
            "release_year": release_year,
            "genres": genres,
            "runtime_minutes": runtime,
            "poster": build_image_url(info.get("poster_path")),
            "backdrop": build_image_url(info.get("backdrop_path")),
            "cast": cast,
            "crew": crew,
            "source": "tmdb",
            "raw": info,
        }
    )

    cache.set(cache_key, metadata, METADATA_CACHE_TIMEOUT)
    return metadata


def _parse_release_year(value: Optional[str]) -> Optional[int]:
    if not value:
        return None
    try:
        return date_parser.parse(value).year
    except (ValueError, TypeError):
        return None


def fetch_movie_db_metadata(media_item: MediaItem) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    if media_item.item_type not in {
        MediaItem.TYPE_MOVIE,
        MediaItem.TYPE_SHOW,
        MediaItem.TYPE_EPISODE,
    }:
        return None, "Movie-DB fallback does not support this media type."

    media_type = "movie" if media_item.is_movie else "tv"
    try:
        response = _REQUESTS_SESSION.get(
            MOVIEDB_SEARCH_URL,
            params={"type": media_type, "query": media_item.title},
            timeout=6,
        )
    except requests.RequestException as exc:
        message = f"Movie-DB search failed: {exc}"
        logger.warning(message)
        return None, message

    if response.status_code != 200:
        message = f"Movie-DB search returned status {response.status_code}."
        logger.debug(message)
        return None, message

    try:
        payload = response.json()
    except ValueError:
        message = "Movie-DB search returned an unexpected response format."
        logger.debug(message)
        return None, message

    results = []
    if isinstance(payload, dict):
        results = payload.get("results") or []
    elif isinstance(payload, list):
        results = payload

    if not results:
        message = "Movie-DB search returned no matches."
        logger.debug(message)
        return None, message

    candidate = results[0]
    release_date = candidate.get("release_date") or candidate.get("first_air_date")
    release_year = _parse_release_year(release_date) or media_item.release_year

    metadata = _to_serializable(
        {
            "tmdb_id": str(candidate.get("id") or media_item.tmdb_id or ""),
            "title": candidate.get("title")
            or candidate.get("name")
            or media_item.title,
            "synopsis": candidate.get("overview") or media_item.synopsis,
            "release_year": release_year,
            "poster": build_image_url(candidate.get("poster_path")),
            "backdrop": build_image_url(candidate.get("backdrop_path")),
            "runtime_minutes": candidate.get("runtime"),
            "genres": [],
            "cast": [],
            "crew": [],
            "source": "movie-db",
            "raw": candidate,
        }
    )

    return metadata, None


def resolve_available_metadata_source() -> Tuple[Optional[str], Optional[str]]:
    tmdb_key = get_tmdb_api_key()
    tmdb_error: Optional[str] = None
    if tmdb_key:
        tmdb_valid, tmdb_message = validate_tmdb_api_key(tmdb_key)
        if tmdb_valid:
            return "tmdb", None
        tmdb_error = tmdb_message or "TMDB API key is invalid."
    else:
        tmdb_error = "TMDB API key not configured."

    movie_db_available, movie_db_message = check_movie_db_health()
    if movie_db_available:
        return "movie-db", None

    combined = "All metadata sources are unavailable."
    details: list[str] = []
    if tmdb_error:
        details.append(f"TMDB: {tmdb_error}")
    if movie_db_message:
        details.append(f"Movie-DB: {movie_db_message}")
    if details:
        combined = f"{combined} {' '.join(details)}"
    return None, combined


def fetch_metadata_with_fallback(media_item: MediaItem) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    metadata = None
    tmdb_key = get_tmdb_api_key()
    tmdb_error: Optional[str] = None

    if tmdb_key:
        tmdb_valid, tmdb_message = validate_tmdb_api_key(tmdb_key)
        if tmdb_valid:
            metadata = fetch_tmdb_metadata(media_item)
            if metadata:
                return metadata, None
            tmdb_error = "TMDB returned no metadata for this item."
        else:
            tmdb_error = tmdb_message or "TMDB API key is invalid."
    else:
        tmdb_error = "TMDB API key not configured."

    fallback_metadata, fallback_error = fetch_movie_db_metadata(media_item)
    if fallback_metadata:
        return fallback_metadata, None

    details = []
    if tmdb_error:
        details.append(tmdb_error)
    if fallback_error:
        details.append(fallback_error)
    message = "All metadata sources are unavailable."
    if details:
        message = f"{message} {' '.join(details)}"
    return None, message


def apply_metadata(media_item: MediaItem, metadata: Dict[str, Any]) -> MediaItem:
    changed = False
    update_fields: list[str] = []
    if metadata.get("tmdb_id") and metadata.get("tmdb_id") != media_item.tmdb_id:
        media_item.tmdb_id = metadata["tmdb_id"]
        update_fields.append("tmdb_id")
        changed = True
    if metadata.get("imdb_id") and metadata.get("imdb_id") != media_item.imdb_id:
        media_item.imdb_id = metadata["imdb_id"]
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
        except (TypeError, ValueError):  # noqa: PERF203
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
        media_item.save(update_fields=list(dict.fromkeys(update_fields)))

    # Update artwork assets so frontend can access gallery
    if poster:
        ArtworkAsset.objects.update_or_create(
            media_item=media_item,
            asset_type=ArtworkAsset.TYPE_POSTER,
            source=metadata.get("source", "unknown"),
            defaults={"external_url": poster},
        )
    if backdrop:
        ArtworkAsset.objects.update_or_create(
            media_item=media_item,
            asset_type=ArtworkAsset.TYPE_BACKDROP,
            source=metadata.get("source", "unknown"),
            defaults={"external_url": backdrop},
        )

    return media_item


def sync_metadata(media_item: MediaItem) -> Optional[MediaItem]:
    metadata, error = fetch_metadata_with_fallback(media_item)
    if not metadata:
        if error:
            logger.debug("Metadata sync skipped for %s: %s", media_item, error)
        return None
    return apply_metadata(media_item, metadata)
