import logging
import os
import re
import xml.etree.ElementTree as ET
from typing import Any, Dict, Optional, Tuple

import requests
from dateutil import parser as date_parser
from django.core.cache import cache
from django.utils import timezone

from core.models import CoreSettings
from apps.media_library.models import ArtworkAsset, MediaItem
from apps.media_library.utils import normalize_title

logger = logging.getLogger(__name__)

IMAGE_BASE_URL = "https://image.tmdb.org/t/p/original"
TMDB_API_BASE_URL = "https://api.themoviedb.org/3"
MOVIEDB_SEARCH_URL = "https://movie-db.org/api.php"
MOVIEDB_EPISODE_URL = "https://movie-db.org/episode.php"
MOVIEDB_CREDITS_URL = "https://movie-db.org/credits.php"
METADATA_CACHE_TIMEOUT = 60 * 60 * 6
MOVIEDB_HEALTH_CACHE_KEY = "movie-db:health"
MOVIEDB_HEALTH_SUCCESS_TTL = 60 * 15
MOVIEDB_HEALTH_FAILURE_TTL = 60 * 2

# Shared HTTP session + in-memory caches to reduce duplicate lookups.
_REQUESTS_SESSION = requests.Session()
_REQUESTS_SESSION.mount(
    "https://",
    requests.adapters.HTTPAdapter(pool_connections=20, pool_maxsize=40, max_retries=3),
)

_MOVIEDB_SEARCH_CACHE: dict[tuple[str, ...], tuple[dict | None, str | None]] = {}
_MOVIEDB_CREDITS_CACHE: dict[tuple[str, str], tuple[dict | None, str | None]] = {}
_TMDB_SEARCH_CACHE: dict[tuple[str, ...], tuple[dict | None, str | None]] = {}
_TMDB_DETAIL_CACHE: dict[tuple[str, str], tuple[dict | None, str | None]] = {}

# TMDB/Movie-DB genre IDs mapped to display values.
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

_YOUTUBE_ID_RE = re.compile(
    r"(?:video_id=|v=|youtu\.be/|youtube\.com/embed/)([A-Za-z0-9_-]{6,})"
)


def _get_library_metadata_prefs(media_item: MediaItem) -> dict[str, Any]:
    # Merge library language/region fields with optional metadata overrides.
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


def _metadata_cache_key(
    media_item: MediaItem,
    prefs: dict[str, Any] | None = None,
    *,
    provider: str = "movie-db",
) -> str:
    # Include provider + identifiers to avoid collisions across sources.
    normalized = normalize_title(media_item.title) or media_item.normalized_title or ""
    key_parts = [
        provider,
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
    # Force JSON-safe values so metadata payloads can be persisted.
    if isinstance(obj, dict):
        return {key: _to_serializable(value) for key, value in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_to_serializable(item) for item in obj]
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    return str(obj)


def _get_tmdb_api_key() -> Optional[str]:
    # Prefer stored setting, but allow env var for deployments.
    key = CoreSettings.get_tmdb_api_key() or os.environ.get("TMDB_API_KEY")
    if not key:
        return None
    key = str(key).strip()
    return key or None


def _is_http_url(value: str | None) -> bool:
    if not value:
        return False
    return value.startswith("http://") or value.startswith("https://")


def _safe_xml_text(node: ET.Element | None) -> Optional[str]:
    if node is None:
        return None
    text = node.text or ""
    text = text.strip()
    return text or None


def _parse_xml_int(text: str | None) -> Optional[int]:
    if not text:
        return None
    try:
        return int(float(text))
    except (TypeError, ValueError):
        return None


def _parse_xml_float(text: str | None) -> Optional[float]:
    if not text:
        return None
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def _normalize_numeric_rating(text: str | None) -> Optional[str]:
    # MediaItem.rating expects numeric strings; skip non-numeric ratings.
    if not text:
        return None
    value = str(text).strip()
    if not value:
        return None
    try:
        float(value)
    except (TypeError, ValueError):
        return None
    return value


def check_movie_db_health(*, use_cache: bool = True) -> Tuple[bool, str | None]:
    # Lightweight probe to decide whether Movie-DB is usable.
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


def _nfo_rating(root: ET.Element) -> Optional[str]:
    rating = _normalize_numeric_rating(_safe_xml_text(root.find("rating")))
    if rating:
        return rating
    ratings = root.find("ratings")
    if ratings is None:
        return None
    entries = ratings.findall("rating")
    if not entries:
        return None
    default_entry = next(
        (
            entry
            for entry in entries
            if str(entry.get("default", "")).lower() in {"true", "1", "yes"}
        ),
        None,
    )
    entry = default_entry or entries[0]
    value = _normalize_numeric_rating(
        _safe_xml_text(entry.find("value")) or _safe_xml_text(entry)
    )
    return value


def _nfo_list(root: ET.Element, tag: str) -> list[str]:
    values: list[str] = []
    for node in root.findall(tag):
        value = _safe_xml_text(node)
        if value:
            values.append(value)
    return values


def _nfo_cast(root: ET.Element) -> list[dict[str, Any]]:
    cast: list[dict[str, Any]] = []
    for actor in root.findall("actor"):
        name = _safe_xml_text(actor.find("name")) or _safe_xml_text(actor)
        if not name:
            continue
        cast.append(
            {
                "name": name,
                "character": _safe_xml_text(actor.find("role")),
                "profile_url": _safe_xml_text(actor.find("thumb")),
            }
        )
    return cast


def _nfo_crew(root: ET.Element) -> list[dict[str, Any]]:
    crew: list[dict[str, Any]] = []
    for director in root.findall("director"):
        name = _safe_xml_text(director)
        if name:
            crew.append({"name": name, "job": "Director", "department": "Directing"})
    for writer in root.findall("credits"):
        name = _safe_xml_text(writer)
        if name:
            crew.append({"name": name, "job": "Writer", "department": "Writing"})
    return crew


def _nfo_art(root: ET.Element) -> tuple[Optional[str], Optional[str]]:
    poster_url = None
    backdrop_url = None

    for thumb in root.findall("thumb"):
        url = _safe_xml_text(thumb)
        if not url:
            continue
        aspect = (thumb.get("aspect") or thumb.get("type") or "").lower()
        if not poster_url and aspect in {"poster", "thumb"}:
            poster_url = url
        if not backdrop_url and aspect in {"fanart", "backdrop", "landscape"}:
            backdrop_url = url

    fanart = root.find("fanart")
    if fanart is not None:
        for thumb in fanart.findall("thumb"):
            url = _safe_xml_text(thumb)
            if url:
                backdrop_url = backdrop_url or url
                break

    art = root.find("art")
    if art is not None:
        if not poster_url:
            poster_url = _safe_xml_text(art.find("poster"))
        if not backdrop_url:
            backdrop_url = _safe_xml_text(art.find("fanart")) or _safe_xml_text(
                art.find("backdrop")
            )

    if poster_url and not _is_http_url(poster_url):
        poster_url = None
    if backdrop_url and not _is_http_url(backdrop_url):
        backdrop_url = None

    return poster_url, backdrop_url


def _nfo_unique_ids(root: ET.Element) -> tuple[Optional[str], Optional[str]]:
    imdb_id = None
    tmdb_id = None
    for node in root.findall("uniqueid"):
        value = _safe_xml_text(node)
        if not value:
            continue
        id_type = str(node.get("type", "")).lower()
        if id_type == "imdb":
            imdb_id = value
        elif id_type in {"tmdb", "themoviedb"}:
            tmdb_id = value
    if not tmdb_id:
        raw_id = _safe_xml_text(root.find("id"))
        if raw_id and raw_id.isdigit():
            tmdb_id = raw_id
    return imdb_id, tmdb_id


def _nfo_runtime_minutes(root: ET.Element) -> Optional[int]:
    runtime = _parse_xml_float(_safe_xml_text(root.find("runtime")))
    if runtime:
        return int(round(runtime))
    duration = (
        _safe_xml_text(root.find("./fileinfo/streamdetails/video/durationinseconds"))
        or _safe_xml_text(root.find("./fileinfo/streamdetails/video/duration"))
    )
    seconds = _parse_xml_float(duration)
    if seconds:
        return int(round(seconds / 60))
    return None


def _extract_youtube_id(value: str | None) -> Optional[str]:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    match = _YOUTUBE_ID_RE.search(text)
    if match:
        return match.group(1)
    if "://" not in text:
        return text
    return None


def _nfo_trailer(root: ET.Element) -> Optional[str]:
    trailer = _safe_xml_text(root.find("trailer"))
    if not trailer:
        return None
    return _extract_youtube_id(trailer) or trailer


def _find_library_base_path(file_path: str, library) -> Optional[str]:
    # Identify which library location contains the file path.
    if not file_path:
        return None
    normalized_file_path = os.path.normcase(
        os.path.abspath(os.path.expanduser(file_path))
    )
    for location in library.locations.all():
        base_path = os.path.normcase(
            os.path.abspath(os.path.expanduser(location.path))
        )
        try:
            if os.path.commonpath([base_path, normalized_file_path]) == base_path:
                return base_path
        except ValueError:
            continue
    return None


def _find_nfo_in_directory(
    directory: str,
    *,
    preferred_names: list[str],
    allow_single_fallback: bool = True,
) -> Optional[str]:
    # Prefer named NFOs; optionally fallback to the only NFO when unambiguous.
    try:
        entries = [
            entry
            for entry in os.listdir(directory)
            if entry.lower().endswith(".nfo")
        ]
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


def _iter_parent_dirs(start_dir: str, *, stop_dir: Optional[str] = None):
    if not start_dir:
        return
    current = os.path.abspath(os.path.expanduser(start_dir))
    stop = os.path.abspath(os.path.expanduser(stop_dir)) if stop_dir else None
    stop_norm = os.path.normcase(stop) if stop else None

    while True:
        yield current
        if stop_norm and os.path.normcase(current) == stop_norm:
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


def _find_local_artwork_files(
    directory: str | None,
) -> tuple[Optional[str], Optional[str]]:
    # Prefer poster.jpg and fanart.jpg when present alongside NFO.
    if not directory:
        return None, None
    try:
        entries = [entry for entry in os.listdir(directory) if entry]
    except OSError:
        return None, None

    entries_by_lower = {entry.lower(): entry for entry in entries}
    poster_name = entries_by_lower.get("poster.jpg")
    fanart_name = entries_by_lower.get("fanart.jpg")

    poster_path = os.path.join(directory, poster_name) if poster_name else None
    fanart_path = os.path.join(directory, fanart_name) if fanart_name else None
    logger.debug(
        "Local artwork files directory=%s poster=%s fanart=%s",
        directory,
        poster_path,
        fanart_path,
    )
    return poster_path, fanart_path


def _local_artwork_url(media_item: MediaItem, asset_type: str) -> Optional[str]:
    if not media_item.id:
        return None
    return f"/api/media-library/items/{media_item.id}/artwork/{asset_type}/"


def find_local_artwork_path(media_item: MediaItem, asset_type: str) -> Optional[str]:
    # Resolve the local artwork path for API responses.
    logger.debug(
        "Artwork lookup start item_id=%s asset_type=%s",
        media_item.id,
        asset_type,
    )
    if asset_type not in {"poster", "backdrop"}:
        logger.debug("Artwork lookup skipped: unsupported asset_type=%s", asset_type)
        return None

    nfo_path = _find_local_nfo_path(media_item)
    directory = os.path.dirname(nfo_path) if nfo_path else None
    if not directory:
        file = media_item.files.filter(is_primary=True).first() or media_item.files.first()
        if file and file.path:
            directory = os.path.dirname(file.path)
            logger.debug(
                "Artwork lookup using media file directory=%s file_path=%s",
                directory,
                file.path,
            )
        else:
            logger.debug("Artwork lookup failed: no media file path available")
    if not directory:
        return None

    poster_path, fanart_path = _find_local_artwork_files(directory)
    target_path = poster_path if asset_type == "poster" else fanart_path
    if not target_path:
        logger.debug(
            "Artwork lookup missing target asset_type=%s directory=%s",
            asset_type,
            directory,
        )
        return None

    base_path = _find_library_base_path(target_path, media_item.library)
    if not base_path:
        logger.debug(
            "Artwork lookup failed: path not under library base path=%s library_id=%s",
            target_path,
            media_item.library_id,
        )
        return None
    logger.debug(
        "Artwork lookup success item_id=%s asset_type=%s path=%s base_path=%s",
        media_item.id,
        asset_type,
        target_path,
        base_path,
    )
    return target_path


def _find_local_nfo_path(media_item: MediaItem) -> Optional[str]:
    # Locate the most likely NFO for movies, shows, or episodes.
    files = list(media_item.files.all())
    if not files and media_item.item_type == MediaItem.TYPE_SHOW:
        episodes = list(
            MediaItem.objects.filter(parent=media_item, item_type=MediaItem.TYPE_EPISODE)
            .exclude(files__isnull=True)
            .prefetch_related("files")[:5]
        )
        files = []
        for episode in episodes:
            files.extend(list(episode.files.all()))

    for media_file in files:
        file_path = media_file.path
        if not file_path:
            continue
        directory = os.path.dirname(file_path)
        base_name = os.path.splitext(os.path.basename(file_path))[0]

        if media_item.item_type in {MediaItem.TYPE_MOVIE, MediaItem.TYPE_EPISODE}:
            preferred = [f"{base_name}.nfo"]
            if media_item.item_type == MediaItem.TYPE_MOVIE:
                preferred.append("movie.nfo")
            if media_item.item_type == MediaItem.TYPE_EPISODE:
                preferred.append("episode.nfo")
            candidate = _find_nfo_in_directory(
                directory,
                preferred_names=preferred,
                allow_single_fallback=media_item.item_type == MediaItem.TYPE_MOVIE,
            )
            if candidate:
                return candidate
            continue

        if media_item.item_type == MediaItem.TYPE_SHOW:
            base_path = _find_library_base_path(file_path, media_item.library)
            for root_dir in _iter_parent_dirs(directory, stop_dir=base_path):
                candidate = _find_nfo_in_directory(
                    root_dir,
                    preferred_names=["tvshow.nfo"],
                    allow_single_fallback=False,
                )
                if candidate:
                    return candidate
    return None


def fetch_local_nfo_metadata(
    media_item: MediaItem,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    # Parse NFO XML and map to MediaItem metadata fields.
    nfo_path = _find_local_nfo_path(media_item)
    if not nfo_path:
        return None, "No NFO file found."

    try:
        tree = ET.parse(nfo_path)
    except (ET.ParseError, OSError) as exc:
        return None, f"Failed to parse NFO: {exc}"

    root = tree.getroot()
    if root is None:
        return None, "NFO did not contain metadata."

    imdb_id, tmdb_id = _nfo_unique_ids(root)
    title = _safe_xml_text(root.find("title")) or _safe_xml_text(
        root.find("originaltitle")
    )
    sort_title = _safe_xml_text(root.find("sorttitle"))
    synopsis = _safe_xml_text(root.find("plot")) or _safe_xml_text(root.find("outline"))
    tagline = _safe_xml_text(root.find("tagline"))
    youtube_trailer = _nfo_trailer(root)
    premiered = _safe_xml_text(root.find("premiered")) or _safe_xml_text(root.find("aired"))
    release_year = _parse_xml_int(_safe_xml_text(root.find("year"))) or _parse_release_year(premiered)
    runtime_minutes = _nfo_runtime_minutes(root)
    genres = _nfo_list(root, "genre")
    tags = _nfo_list(root, "tag")
    studios = _nfo_list(root, "studio")
    rating = _nfo_rating(root)
    poster_url, backdrop_url = _nfo_art(root)
    local_poster_path, local_backdrop_path = _find_local_artwork_files(
        os.path.dirname(nfo_path)
    )
    if local_poster_path:
        poster_url = _local_artwork_url(media_item, "poster") or poster_url
    if local_backdrop_path:
        backdrop_url = _local_artwork_url(media_item, "backdrop") or backdrop_url
    cast = _nfo_cast(root)
    crew = _nfo_crew(root)

    if not any(
        [
            title,
            synopsis,
            tagline,
            release_year,
            runtime_minutes,
            genres,
            tags,
            studios,
            rating,
            poster_url,
            backdrop_url,
            youtube_trailer,
            imdb_id,
            tmdb_id,
            cast,
            crew,
        ]
    ):
        return None, "NFO did not contain usable metadata."

    payload = _to_serializable(
        {
            "source": "nfo",
            "title": title,
            "sort_title": sort_title,
            "synopsis": synopsis,
            "tagline": tagline,
            "youtube_trailer": youtube_trailer,
            "release_year": release_year,
            "runtime_minutes": runtime_minutes,
            "genres": genres,
            "tags": tags,
            "studios": studios,
            "rating": rating,
            "poster": poster_url,
            "backdrop": backdrop_url,
            "imdb_id": imdb_id,
            "tmdb_id": tmdb_id,
            "raw": {
                "path": nfo_path,
                "title": title,
                "sort_title": sort_title,
                "synopsis": synopsis,
                "tagline": tagline,
                "youtube_trailer": youtube_trailer,
                "release_year": release_year,
                "runtime_minutes": runtime_minutes,
                "genres": genres,
                "tags": tags,
                "studios": studios,
                "rating": rating,
                "poster": poster_url,
                "backdrop": backdrop_url,
                "imdb_id": imdb_id,
                "tmdb_id": tmdb_id,
            },
        }
    )

    return payload, None


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
    # Normalize cast/crew into the shared MediaItem schema.
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


def _tmdb_title(payload: dict) -> str:
    return payload.get("title") or payload.get("name") or ""


def _tmdb_candidate_year(payload: dict) -> Optional[int]:
    return _parse_release_year(
        payload.get("release_date") or payload.get("first_air_date")
    )


def _tmdb_trailer_key(payload: dict | None) -> Optional[str]:
    if not isinstance(payload, dict):
        return None
    videos = payload.get("videos")
    if not isinstance(videos, dict):
        return None
    results = videos.get("results") or []
    if not isinstance(results, list):
        return None
    candidates = [
        entry
        for entry in results
        if isinstance(entry, dict)
        and entry.get("site") == "YouTube"
        and entry.get("key")
    ]
    if not candidates:
        return None

    def score(entry: dict) -> tuple[int, int]:
        score_value = 0
        if entry.get("type") == "Trailer":
            score_value += 3
        elif entry.get("type") == "Teaser":
            score_value += 1
        if entry.get("official"):
            score_value += 2
        return score_value, 0

    best = max(candidates, key=score)
    return best.get("key")


def _select_tmdb_candidate(
    results: list[dict],
    title: str,
    *,
    year: Optional[int] = None,
    prefs: dict[str, Any] | None = None,
) -> Optional[dict]:
    # Score candidates by title, year, region, and artwork availability.
    if not results:
        return None
    normalized_query = normalize_title(title)
    region = (prefs or {}).get("region")
    best_score = None
    best_result = None
    for idx, result in enumerate(results):
        if not isinstance(result, dict):
            continue
        normalized_title = normalize_title(_tmdb_title(result))
        score = 0
        if normalized_query and normalized_title == normalized_query:
            score += 6
        elif normalized_query and (
            normalized_query in normalized_title or normalized_title in normalized_query
        ):
            score += 3
        if year:
            candidate_year = _tmdb_candidate_year(result)
            if candidate_year and candidate_year == year:
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
        score = (score, -idx)
        if best_score is None or score > best_score:
            best_score = score
            best_result = result
    return best_result or (results[0] if results else None)


def _tmdb_request(
    path: str,
    *,
    params: dict[str, Any],
    timeout: int = 6,
) -> tuple[Optional[dict], Optional[str]]:
    # TMDB API request wrapper with consistent error handling.
    try:
        response = _REQUESTS_SESSION.get(
            f"{TMDB_API_BASE_URL}{path}",
            params=params,
            timeout=timeout,
        )
    except requests.RequestException as exc:
        return None, f"TMDB request failed: {exc}"
    if response.status_code != 200:
        return None, f"TMDB returned status {response.status_code}."
    try:
        payload = response.json()
    except ValueError:
        return None, "TMDB returned an unexpected response format."
    if not isinstance(payload, dict):
        return None, "TMDB returned an unexpected payload."
    return payload, None


def _tmdb_search(
    media_type: str,
    title: str,
    *,
    year: Optional[int] = None,
    prefs: dict[str, Any] | None = None,
) -> tuple[Optional[dict], Optional[str]]:
    api_key = _get_tmdb_api_key()
    if not api_key:
        return None, "TMDB API key is missing."
    language = (prefs or {}).get("language") or ""
    region = (prefs or {}).get("region") or ""
    normalized_key = (
        media_type,
        (title or "").strip().lower(),
        str(year or ""),
        str(language),
        str(region),
    )
    if normalized_key in _TMDB_SEARCH_CACHE:
        return _TMDB_SEARCH_CACHE[normalized_key]

    params = {"api_key": api_key, "query": title}
    if language:
        params["language"] = language
    if region:
        params["region"] = region
    if media_type == "movie" and year:
        params["year"] = year
    if media_type == "tv" and year:
        params["first_air_date_year"] = year

    payload, error = _tmdb_request(
        f"/search/{media_type}",
        params=params,
    )
    if error:
        _TMDB_SEARCH_CACHE[normalized_key] = (None, error)
        return None, error

    results = payload.get("results") or []
    if not results:
        message = "TMDB search returned no matches."
        _TMDB_SEARCH_CACHE[normalized_key] = (None, message)
        return None, message

    candidate = _select_tmdb_candidate(results, title, year=year, prefs=prefs)
    _TMDB_SEARCH_CACHE[normalized_key] = (candidate, None)
    return candidate, None


def _tmdb_fetch_details(
    media_type: str,
    content_id: str,
    *,
    prefs: dict[str, Any] | None = None,
) -> tuple[Optional[dict], Optional[str]]:
    api_key = _get_tmdb_api_key()
    if not api_key:
        return None, "TMDB API key is missing."
    normalized_key = (media_type, str(content_id))
    if normalized_key in _TMDB_DETAIL_CACHE:
        return _TMDB_DETAIL_CACHE[normalized_key]

    params = {"api_key": api_key, "append_to_response": "credits,videos"}
    if prefs and prefs.get("language"):
        params["language"] = prefs["language"]

    payload, error = _tmdb_request(
        f"/{media_type}/{content_id}",
        params=params,
    )
    if error:
        _TMDB_DETAIL_CACHE[normalized_key] = (None, error)
        return None, error

    _TMDB_DETAIL_CACHE[normalized_key] = (payload, None)
    return payload, None


def _tmdb_fetch_episode_details(
    tv_id: str,
    season: int,
    episode: int,
    *,
    prefs: dict[str, Any] | None = None,
) -> tuple[Optional[dict], Optional[str]]:
    api_key = _get_tmdb_api_key()
    if not api_key:
        return None, "TMDB API key is missing."
    params = {"api_key": api_key}
    if prefs and prefs.get("language"):
        params["language"] = prefs["language"]
    payload, error = _tmdb_request(
        f"/tv/{tv_id}/season/{season}/episode/{episode}",
        params=params,
    )
    return payload, error


def fetch_tmdb_metadata(
    media_item: MediaItem,
    *,
    use_cache: bool = True,
) -> tuple[Optional[Dict[str, Any]], Optional[str]]:
    # TMDB metadata lookup for movies, shows, and episodes.
    if media_item.item_type not in {
        MediaItem.TYPE_MOVIE,
        MediaItem.TYPE_SHOW,
        MediaItem.TYPE_EPISODE,
    }:
        return None, "TMDB does not support this media type."

    prefs = _get_library_metadata_prefs(media_item)
    cache_key = _metadata_cache_key(media_item, prefs, provider="tmdb")
    if use_cache:
        cached = cache.get(cache_key)
        if cached:
            return cached, None

    if media_item.item_type == MediaItem.TYPE_MOVIE:
        direct_id = None
        if media_item.movie_db_id and media_item.metadata_source in {"tmdb", "nfo"}:
            direct_id = str(media_item.movie_db_id)

        if direct_id:
            details, message = _tmdb_fetch_details(
                "movie",
                direct_id,
                prefs=prefs,
            )
        else:
            candidate, message = _tmdb_search(
                "movie",
                media_item.title,
                year=media_item.release_year,
                prefs=prefs,
            )
            if not candidate:
                return None, message
            details, message = _tmdb_fetch_details(
                "movie",
                str(candidate.get("id")),
                prefs=prefs,
            )
        if not details:
            return None, message

        credits_payload = details.get("credits") if isinstance(details, dict) else None
        cast, crew = _normalize_credits(credits_payload)
        genres = [entry.get("name") for entry in details.get("genres", []) if entry.get("name")]
        runtime = details.get("runtime")
        trailer_key = _tmdb_trailer_key(details)
        release_year = _parse_release_year(details.get("release_date")) or media_item.release_year
        metadata = _to_serializable(
            {
                "tmdb_id": str(details.get("id") or ""),
                "imdb_id": details.get("imdb_id"),
                "title": details.get("title") or media_item.title,
                "synopsis": details.get("overview") or media_item.synopsis,
                "tagline": details.get("tagline") or media_item.tagline,
                "release_year": release_year,
                "poster": build_image_url(details.get("poster_path")),
                "backdrop": build_image_url(details.get("backdrop_path")),
                "runtime_minutes": runtime,
                "youtube_trailer": trailer_key,
                "genres": genres,
                "studios": [
                    entry.get("name")
                    for entry in details.get("production_companies", [])
                    if entry.get("name")
                ],
                "rating": str(details.get("vote_average"))
                if details.get("vote_average") is not None
                else None,
                "cast": cast,
                "crew": crew,
                "source": "tmdb",
                "raw": details,
            }
        )
        if use_cache:
            cache.set(cache_key, metadata, METADATA_CACHE_TIMEOUT)
        return metadata, None

    if media_item.item_type == MediaItem.TYPE_SHOW:
        direct_id = None
        if media_item.movie_db_id and media_item.metadata_source in {"tmdb", "nfo"}:
            direct_id = str(media_item.movie_db_id)

        if direct_id:
            details, message = _tmdb_fetch_details(
                "tv",
                direct_id,
                prefs=prefs,
            )
        else:
            candidate, message = _tmdb_search(
                "tv",
                media_item.title,
                year=media_item.release_year,
                prefs=prefs,
            )
            if not candidate:
                return None, message
            details, message = _tmdb_fetch_details(
                "tv",
                str(candidate.get("id")),
                prefs=prefs,
            )
        if not details:
            return None, message

        credits_payload = details.get("credits") if isinstance(details, dict) else None
        cast, crew = _normalize_credits(credits_payload)
        genres = [entry.get("name") for entry in details.get("genres", []) if entry.get("name")]
        runtime_list = details.get("episode_run_time") or []
        runtime = runtime_list[0] if runtime_list else None
        trailer_key = _tmdb_trailer_key(details)
        release_year = _parse_release_year(details.get("first_air_date")) or media_item.release_year
        metadata = _to_serializable(
            {
                "tmdb_id": str(details.get("id") or ""),
                "title": details.get("name") or media_item.title,
                "synopsis": details.get("overview") or media_item.synopsis,
                "tagline": details.get("tagline") or media_item.tagline,
                "release_year": release_year,
                "poster": build_image_url(details.get("poster_path")),
                "backdrop": build_image_url(details.get("backdrop_path")),
                "runtime_minutes": runtime,
                "youtube_trailer": trailer_key,
                "genres": genres,
                "studios": [
                    entry.get("name")
                    for entry in details.get("production_companies", [])
                    if entry.get("name")
                ],
                "rating": str(details.get("vote_average"))
                if details.get("vote_average") is not None
                else None,
                "cast": cast,
                "crew": crew,
                "source": "tmdb",
                "raw": details,
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

    tv_id = None
    if parent_series.metadata_source in {"tmdb", "nfo"} and parent_series.movie_db_id:
        tv_id = parent_series.movie_db_id
    if not tv_id and isinstance(parent_series.metadata, dict):
        tv_id = parent_series.metadata.get("id") or parent_series.metadata.get("tmdb_id")

    if not tv_id:
        series_candidate, message = _tmdb_search(
            "tv",
            parent_series.title,
            year=parent_series.release_year or media_item.release_year,
            prefs=prefs,
        )
        if not series_candidate:
            return None, message
        tv_id = series_candidate.get("id")

    if not tv_id:
        return None, "TMDB did not return a tvId for this series."

    if media_item.season_number is None or media_item.episode_number is None:
        return None, "Episode numbers are required for TMDB lookup."

    try:
        season_number = int(media_item.season_number)
        episode_number = int(media_item.episode_number)
    except (TypeError, ValueError):
        return None, "Episode numbers are required for TMDB lookup."

    details, message = _tmdb_fetch_episode_details(
        str(tv_id),
        season_number,
        episode_number,
        prefs=prefs,
    )
    if not details:
        return None, message

    release_year = _parse_release_year(details.get("air_date")) or media_item.release_year
    cast = []
    for star in details.get("guest_stars", [])[:12]:
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
    crew = []
    for member in details.get("crew", [])[:15]:
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
            "tmdb_id": str(details.get("id") or ""),
            "title": details.get("name") or media_item.title,
            "synopsis": details.get("overview") or media_item.synopsis,
            "release_year": release_year,
            "poster": build_image_url(details.get("still_path")),
            "backdrop": build_image_url(details.get("still_path")),
            "runtime_minutes": details.get("runtime"),
            "genres": [],
            "cast": cast,
            "crew": crew,
            "source": "tmdb",
            "raw": details,
        }
    )

    if use_cache:
        cache.set(cache_key, metadata, METADATA_CACHE_TIMEOUT)
    return metadata, None


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
    # Movie-DB fallback metadata lookup when TMDB is unavailable.
    if media_item.item_type not in {
        MediaItem.TYPE_MOVIE,
        MediaItem.TYPE_SHOW,
        MediaItem.TYPE_EPISODE,
    }:
        return None, "Movie-DB does not support this media type."

    prefs = _get_library_metadata_prefs(media_item)
    cache_key = _metadata_cache_key(media_item, prefs, provider="movie-db")
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

    tv_id = None
    if parent_series.metadata_source not in {"tmdb", "nfo"}:
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


def _is_empty_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) == 0
    if isinstance(value, (int, float)) and value == 0:
        return True
    return False


def apply_metadata(
    media_item: MediaItem,
    metadata: Dict[str, Any],
    *,
    fill_missing_only: bool = False,
    update_source: bool = True,
) -> MediaItem:
    # Optionally fill only missing fields, preserving existing metadata.
    changed = False
    update_fields: list[str] = []

    def can_update(current_value: Any) -> bool:
        if not fill_missing_only:
            return True
        return _is_empty_value(current_value)

    movie_db_id = metadata.get("movie_db_id") or metadata.get("tmdb_id")
    if movie_db_id and movie_db_id != media_item.movie_db_id and can_update(media_item.movie_db_id):
        media_item.movie_db_id = movie_db_id
        update_fields.append("movie_db_id")
        changed = True

    imdb_id = metadata.get("imdb_id")
    if imdb_id and imdb_id != media_item.imdb_id and can_update(media_item.imdb_id):
        media_item.imdb_id = imdb_id
        update_fields.append("imdb_id")
        changed = True

    title = metadata.get("title")
    if title and title != media_item.title and can_update(media_item.title):
        media_item.title = title
        update_fields.append("title")
        changed = True

    sort_title = metadata.get("sort_title")
    if sort_title and sort_title != media_item.sort_title and can_update(media_item.sort_title):
        media_item.sort_title = sort_title
        update_fields.append("sort_title")
        changed = True

    synopsis = metadata.get("synopsis")
    if synopsis and synopsis != media_item.synopsis and can_update(media_item.synopsis):
        media_item.synopsis = synopsis
        update_fields.append("synopsis")
        changed = True

    tagline = metadata.get("tagline")
    if tagline and tagline != media_item.tagline and can_update(media_item.tagline):
        media_item.tagline = tagline
        update_fields.append("tagline")
        changed = True

    youtube_trailer = metadata.get("youtube_trailer") or metadata.get("trailer")
    if (
        youtube_trailer
        and youtube_trailer != media_item.youtube_trailer
        and can_update(media_item.youtube_trailer)
    ):
        media_item.youtube_trailer = youtube_trailer
        update_fields.append("youtube_trailer")
        changed = True

    rating = metadata.get("rating")
    if rating and rating != media_item.rating and can_update(media_item.rating):
        media_item.rating = rating
        update_fields.append("rating")
        changed = True

    release_year = metadata.get("release_year")
    if release_year and release_year != media_item.release_year and can_update(media_item.release_year):
        try:
            media_item.release_year = int(release_year)
        except (TypeError, ValueError):
            media_item.release_year = media_item.release_year
        else:
            changed = True
            update_fields.append("release_year")

    runtime_minutes = metadata.get("runtime_minutes")
    if runtime_minutes and can_update(media_item.runtime_ms):
        new_runtime_ms = int(float(runtime_minutes) * 60 * 1000)
        if media_item.runtime_ms != new_runtime_ms:
            media_item.runtime_ms = new_runtime_ms
            update_fields.append("runtime_ms")
            changed = True

    genres = metadata.get("genres")
    if genres and genres != media_item.genres and can_update(media_item.genres):
        media_item.genres = genres
        update_fields.append("genres")
        changed = True

    tags = metadata.get("tags")
    if tags and tags != media_item.tags and can_update(media_item.tags):
        media_item.tags = tags
        update_fields.append("tags")
        changed = True

    studios = metadata.get("studios")
    if studios and studios != media_item.studios and can_update(media_item.studios):
        media_item.studios = studios
        update_fields.append("studios")
        changed = True

    cast = metadata.get("cast")
    if cast and cast != media_item.cast and can_update(media_item.cast):
        media_item.cast = cast
        update_fields.append("cast")
        changed = True

    crew = metadata.get("crew")
    if crew and crew != media_item.crew and can_update(media_item.crew):
        media_item.crew = crew
        update_fields.append("crew")
        changed = True

    poster = metadata.get("poster")
    if poster and poster != media_item.poster_url and can_update(media_item.poster_url):
        media_item.poster_url = poster
        update_fields.append("poster_url")
        changed = True

    backdrop = metadata.get("backdrop")
    if backdrop and backdrop != media_item.backdrop_url and can_update(media_item.backdrop_url):
        media_item.backdrop_url = backdrop
        update_fields.append("backdrop_url")
        changed = True

    raw_payload = metadata.get("raw")
    if raw_payload and raw_payload != media_item.metadata and can_update(media_item.metadata):
        media_item.metadata = raw_payload
        update_fields.append("metadata")
        changed = True

    new_source = metadata.get("source", media_item.metadata_source or "unknown")
    if (
        update_source
        and new_source
        and new_source != media_item.metadata_source
        and can_update(media_item.metadata_source)
    ):
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


def _needs_remote_metadata(media_item: MediaItem) -> bool:
    # Determine if enough metadata is missing to justify remote lookups.
    required_fields = [
        media_item.synopsis,
        media_item.release_year,
        media_item.runtime_ms,
        media_item.genres,
        media_item.poster_url,
        media_item.backdrop_url,
        media_item.cast,
        media_item.crew,
        media_item.rating,
    ]
    if media_item.item_type in {MediaItem.TYPE_MOVIE, MediaItem.TYPE_SHOW}:
        required_fields.append(media_item.youtube_trailer)
    return any(_is_empty_value(value) for value in required_fields)


def sync_metadata(media_item: MediaItem, *, force: bool = False) -> Optional[MediaItem]:
    # Orchestrate metadata sources: NFO -> TMDB -> Movie-DB.
    prefer_local = CoreSettings.get_prefer_local_metadata()
    has_local_metadata = False

    if prefer_local:
        local_metadata, local_error = fetch_local_nfo_metadata(media_item)
        if local_metadata:
            apply_metadata(media_item, local_metadata)
            has_local_metadata = True
        elif local_error:
            logger.debug("Local metadata skipped for %s: %s", media_item, local_error)

        if has_local_metadata and not _needs_remote_metadata(media_item):
            return media_item

    tmdb_metadata = None
    tmdb_error = None
    if _get_tmdb_api_key():
        tmdb_metadata, tmdb_error = fetch_tmdb_metadata(
            media_item, use_cache=not force
        )
        if tmdb_metadata:
            return apply_metadata(
                media_item,
                tmdb_metadata,
                fill_missing_only=prefer_local and has_local_metadata,
                update_source=not (prefer_local and has_local_metadata),
            )
        if tmdb_error:
            logger.debug("TMDB metadata skipped for %s: %s", media_item, tmdb_error)

    movie_db_ok, movie_db_message = check_movie_db_health()
    if not movie_db_ok:
        if movie_db_message:
            logger.debug("Movie-DB metadata skipped for %s: %s", media_item, movie_db_message)
        return media_item if has_local_metadata else None

    metadata, error = fetch_movie_db_metadata(media_item, use_cache=not force)
    if not metadata:
        if error:
            logger.debug("Movie-DB metadata skipped for %s: %s", media_item, error)
        return media_item if has_local_metadata else None
    return apply_metadata(
        media_item,
        metadata,
        fill_missing_only=prefer_local and has_local_metadata,
        update_source=not (prefer_local and has_local_metadata),
    )
