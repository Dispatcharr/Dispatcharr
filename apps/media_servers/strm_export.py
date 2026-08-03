from __future__ import annotations

import json
import re
import os
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Iterable, Optional

from django.db.models import Prefetch
from django.urls import reverse

from apps.media_servers.path_security import is_beneath, resolve_export_path

from apps.vod.models import (
    Episode,
    M3UEpisodeRelation,
    M3UMovieRelation,
    M3USeriesRelation,
    Movie,
    Series,
)

INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1F]')
MAX_FILENAME_LEN = 240


def _sanitize_filename(value: Any, fallback: str = "item") -> str:
    text = str(value or "").strip()
    text = INVALID_FILENAME_CHARS.sub("_", text)
    text = " ".join(text.split())
    text = text.rstrip(".")
    if not text:
        text = fallback
    if len(text) > MAX_FILENAME_LEN:
        text = text[:MAX_FILENAME_LEN].rstrip()
    if not text:
        text = fallback
    return text


def _safe_int(value: Any) -> Optional[int]:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _best_relation(relations: Iterable[Any]):
    candidates = []
    for relation in relations or []:
        account = getattr(relation, "m3u_account", None)
        if not account or not bool(getattr(account, "is_active", False)):
            continue
        candidates.append(relation)
    if not candidates:
        return None
    return sorted(
        candidates,
        key=lambda rel: (-(getattr(rel.m3u_account, "priority", 0) or 0), rel.id),
    )[0]


def _relation_list(relations: Any) -> list[Any]:
    if relations is None:
        return []
    if hasattr(relations, "all"):
        return list(relations.all())
    if isinstance(relations, (list, tuple, set)):
        return list(relations)
    return []


def _read_dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _first_non_empty(*values: Any) -> Any:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        if isinstance(value, (list, tuple, dict)) and not value:
            continue
        return value
    return None


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _as_text_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        output = []
        for item in value:
            output.extend(_as_text_list(item))
        return [item for item in output if item]
    if isinstance(value, dict):
        parts = []
        for key in ("name", "title", "value"):
            text = _stringify(value.get(key))
            if text:
                parts.append(text)
                break
        return parts
    raw = _stringify(value)
    if not raw:
        return []
    if "," in raw:
        return [part.strip() for part in raw.split(",") if part.strip()]
    return [raw]


def _duration_minutes(seconds_value: Any) -> Optional[int]:
    seconds = _safe_int(seconds_value)
    if seconds is None or seconds <= 0:
        return None
    return max(1, int(round(seconds / 60.0)))


def _add_text(parent: ET.Element, tag: str, value: Any) -> None:
    text = _stringify(value)
    if text:
        ET.SubElement(parent, tag).text = text


def _add_genres(parent: ET.Element, raw_genre: Any) -> None:
    for genre in _as_text_list(raw_genre):
        _add_text(parent, "genre", genre)


def _add_actors(parent: ET.Element, actors_value: Any) -> None:
    actors = _as_text_list(actors_value)
    for actor_name in actors:
        actor_node = ET.SubElement(parent, "actor")
        _add_text(actor_node, "name", actor_name)


def _add_unique_ids(parent: ET.Element, imdb_id: Any, tmdb_id: Any) -> None:
    imdb_text = _stringify(imdb_id)
    tmdb_text = _stringify(tmdb_id)
    if imdb_text:
        node = ET.SubElement(parent, "uniqueid", {"type": "imdb", "default": "true"})
        node.text = imdb_text
        _add_text(parent, "imdbid", imdb_text)
    if tmdb_text:
        node = ET.SubElement(parent, "uniqueid", {"type": "tmdb", "default": "false"})
        node.text = tmdb_text
        _add_text(parent, "tmdbid", tmdb_text)


def _to_xml_text(root: ET.Element) -> str:
    try:
        ET.indent(root, space="  ")  # Python 3.9+
    except Exception:
        pass
    xml_bytes = ET.tostring(root, encoding="utf-8")
    return "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n" + xml_bytes.decode("utf-8")


def _build_movie_nfo(
    movie: Movie,
    relation: Optional[M3UMovieRelation],
    *,
    base_url: str,
) -> str:
    movie_props = _read_dict(movie.custom_properties)
    relation_props = _read_dict(getattr(relation, "custom_properties", None))
    detailed = _read_dict(relation_props.get("detailed_info"))
    movie_data = _read_dict(relation_props.get("movie_data"))

    title = _first_non_empty(detailed.get("name"), movie.name)
    plot = _first_non_empty(detailed.get("plot"), detailed.get("description"), movie.description)
    year = _first_non_empty(movie.year, detailed.get("year"))
    release_date = _first_non_empty(
        movie_props.get("release_date"),
        detailed.get("release_date"),
        detailed.get("releasedate"),
    )
    rating = _first_non_empty(movie.rating, detailed.get("rating"))
    genre = _first_non_empty(movie.genre, detailed.get("genre"))
    director = _first_non_empty(movie_props.get("director"), detailed.get("director"))
    writer = _first_non_empty(
        movie_props.get("writer"),
        movie_props.get("credits"),
        detailed.get("writer"),
        detailed.get("credits"),
    )
    actors = _first_non_empty(
        movie_props.get("actors"),
        movie_props.get("cast"),
        detailed.get("actors"),
        detailed.get("cast"),
    )
    country = _first_non_empty(movie_props.get("country"), detailed.get("country"))
    trailer = _first_non_empty(
        movie_props.get("youtube_trailer"),
        detailed.get("youtube_trailer"),
        detailed.get("trailer"),
    )
    studio = _first_non_empty(movie_props.get("studio"), detailed.get("studio"))
    mpaa = _first_non_empty(movie_props.get("age"), detailed.get("age"))
    tagline = _first_non_empty(movie_props.get("tagline"), detailed.get("tagline"))
    set_name = _first_non_empty(movie_props.get("set"), detailed.get("set"))
    runtime = _duration_minutes(_first_non_empty(movie.duration_secs, detailed.get("duration_secs")))
    poster = _first_non_empty(
        _vod_logo_cache_url(base_url, getattr(movie, "logo_id", None)),
        detailed.get("cover_big"),
        detailed.get("movie_image"),
        getattr(movie.logo, "url", None),
    )
    backdrop = _first_non_empty(movie_props.get("backdrop_path"), detailed.get("backdrop_path"))

    root = ET.Element("movie")
    _add_text(root, "title", title)
    _add_text(root, "originaltitle", title)
    _add_text(root, "plot", plot)
    _add_text(root, "outline", plot)
    _add_text(root, "tagline", tagline)
    _add_text(root, "year", year)
    _add_text(root, "premiered", release_date)
    _add_text(root, "releasedate", release_date)
    _add_text(root, "rating", rating)
    _add_genres(root, genre)
    _add_text(root, "director", director)
    _add_text(root, "credits", writer)
    _add_text(root, "country", country)
    _add_text(root, "studio", studio)
    _add_text(root, "trailer", trailer)
    _add_text(root, "mpaa", mpaa)
    _add_text(root, "set", set_name)
    _add_text(root, "runtime", runtime)
    _add_text(root, "thumb", poster)
    _add_actors(root, actors)
    backdrop_values = _as_text_list(backdrop)
    if backdrop_values:
        fanart = ET.SubElement(root, "fanart")
        _add_text(fanart, "thumb", backdrop_values[0])
    _add_unique_ids(root, movie.imdb_id, movie.tmdb_id)
    return _to_xml_text(root)


def _build_tvshow_nfo(
    series: Series,
    relation: Optional[M3USeriesRelation],
    *,
    base_url: str,
) -> str:
    series_props = _read_dict(series.custom_properties)
    relation_props = _read_dict(getattr(relation, "custom_properties", None))
    detailed = _read_dict(relation_props.get("detailed_info"))

    title = _first_non_empty(detailed.get("name"), series.name)
    plot = _first_non_empty(detailed.get("plot"), detailed.get("description"), series.description)
    year = _first_non_empty(series.year, detailed.get("year"))
    release_date = _first_non_empty(
        series_props.get("release_date"),
        detailed.get("release_date"),
        detailed.get("releasedate"),
    )
    rating = _first_non_empty(series.rating, detailed.get("rating"))
    genre = _first_non_empty(series.genre, detailed.get("genre"))
    director = _first_non_empty(series_props.get("director"), detailed.get("director"))
    writer = _first_non_empty(
        series_props.get("writer"),
        series_props.get("credits"),
        detailed.get("writer"),
        detailed.get("credits"),
    )
    cast = _first_non_empty(series_props.get("cast"), detailed.get("cast"))
    trailer = _first_non_empty(
        series_props.get("youtube_trailer"),
        detailed.get("youtube_trailer"),
        detailed.get("trailer"),
    )
    status = _first_non_empty(series_props.get("status"), detailed.get("status"))
    studio = _first_non_empty(series_props.get("studio"), detailed.get("studio"))
    country = _first_non_empty(series_props.get("country"), detailed.get("country"))
    episode_runtime = _first_non_empty(
        series_props.get("episode_run_time"),
        detailed.get("episode_run_time"),
    )
    poster = _first_non_empty(
        _vod_logo_cache_url(base_url, getattr(series, "logo_id", None)),
        detailed.get("cover_big"),
        detailed.get("movie_image"),
        getattr(series.logo, "url", None),
    )
    backdrop = _first_non_empty(series_props.get("backdrop_path"), detailed.get("backdrop_path"))

    root = ET.Element("tvshow")
    _add_text(root, "title", title)
    _add_text(root, "showtitle", title)
    _add_text(root, "plot", plot)
    _add_text(root, "outline", plot)
    _add_text(root, "year", year)
    _add_text(root, "premiered", release_date)
    _add_text(root, "rating", rating)
    _add_genres(root, genre)
    _add_text(root, "director", director)
    _add_text(root, "credits", writer)
    _add_text(root, "trailer", trailer)
    _add_text(root, "studio", studio)
    _add_text(root, "country", country)
    _add_text(root, "status", status)
    _add_text(root, "runtime", episode_runtime)
    _add_text(root, "thumb", poster)
    _add_actors(root, cast)
    backdrop_values = _as_text_list(backdrop)
    if backdrop_values:
        fanart = ET.SubElement(root, "fanart")
        _add_text(fanart, "thumb", backdrop_values[0])
    _add_unique_ids(root, series.imdb_id, series.tmdb_id)
    return _to_xml_text(root)


def _build_episode_nfo(
    series: Series,
    episode: Episode,
    relation: Optional[M3UEpisodeRelation],
    *,
    base_url: str,
) -> str:
    episode_props = _read_dict(episode.custom_properties)
    relation_props = _read_dict(getattr(relation, "custom_properties", None))
    detailed = _read_dict(relation_props.get("detailed_info"))

    title = _first_non_empty(detailed.get("title"), detailed.get("name"), episode.name)
    plot = _first_non_empty(detailed.get("plot"), detailed.get("description"), episode.description)
    rating = _first_non_empty(episode.rating, detailed.get("rating"))
    runtime = _duration_minutes(_first_non_empty(episode.duration_secs, detailed.get("duration_secs")))
    air_date = _first_non_empty(
        episode.air_date.isoformat() if episode.air_date else None,
        detailed.get("release_date"),
        detailed.get("aired"),
    )
    director = _first_non_empty(episode_props.get("director"), detailed.get("director"))
    writer = _first_non_empty(
        episode_props.get("writer"),
        episode_props.get("credits"),
        detailed.get("writer"),
        detailed.get("credits"),
    )
    cast = _first_non_empty(episode_props.get("cast"), episode_props.get("actors"), detailed.get("cast"))
    genre = _first_non_empty(episode_props.get("genre"), detailed.get("genre"), series.genre)
    poster_logo_id = _first_non_empty(
        episode_props.get("poster_logo_id"),
        relation_props.get("poster_logo_id"),
        detailed.get("poster_logo_id"),
        getattr(series, "logo_id", None),
    )
    poster = _first_non_empty(
        _vod_logo_cache_url(base_url, poster_logo_id),
        episode_props.get("movie_image"),
        detailed.get("movie_image"),
        detailed.get("thumb"),
    )

    season_num = _safe_int(episode.season_number) or 0
    episode_num = _safe_int(episode.episode_number) or 0

    root = ET.Element("episodedetails")
    _add_text(root, "title", title)
    _add_text(root, "showtitle", series.name)
    _add_text(root, "plot", plot)
    _add_text(root, "season", season_num)
    _add_text(root, "episode", episode_num)
    _add_text(root, "aired", air_date)
    _add_text(root, "premiered", air_date)
    _add_text(root, "rating", rating)
    _add_genres(root, genre)
    _add_text(root, "runtime", runtime)
    _add_text(root, "director", director)
    _add_text(root, "credits", writer)
    _add_text(root, "thumb", poster)
    _add_actors(root, cast)
    _add_unique_ids(root, episode.imdb_id, episode.tmdb_id)
    return _to_xml_text(root)


def _stream_url(target, content_type: str, content_uuid) -> str:
    path = reverse(
        "proxy:vod_proxy:media_library_vod_stream",
        kwargs={
            "target_public_id": target.public_id,
            "content_type": content_type,
            "content_id": content_uuid,
        },
    )
    return f"{target.playback_base_url.rstrip('/')}{path}"


def _vod_logo_cache_url(base_url: str, logo_id: Any) -> Optional[str]:
    normalized_id = _safe_int(logo_id)
    if normalized_id is None:
        return None
    path = reverse("api:vod:vodlogo-cache", args=[normalized_id])
    return f"{base_url.rstrip('/')}{path}"


def _safe_output_path(root: Path, relative: Path) -> Path:
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("Unsafe export path")
    destination = root
    for part in relative.parts:
        destination = destination / part
        if destination.is_symlink():
            raise ValueError("Symlinks are not allowed in managed export paths")
    if not is_beneath(destination.resolve(strict=False), (root,)):
        raise ValueError("Export path escapes the configured target")
    return destination


def _write_text(path: Path, contents: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(contents.rstrip() + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _movie_display_name(movie: Movie) -> str:
    base_name = _sanitize_filename(movie.name, fallback=f"Movie-{movie.id}")
    year = _safe_int(movie.year)
    if year:
        return _sanitize_filename(f"{base_name} ({year})", fallback=base_name)
    return base_name


def _episode_base_name(series_name: str, season_num: int, episode_num: int) -> str:
    return _sanitize_filename(
        f"{series_name} - S{season_num:02d}E{episode_num:02d}",
        fallback=f"Episode-S{season_num:02d}E{episode_num:02d}",
    )


def _load_manifest(root: Path) -> set[str]:
    path = root / ".dispatcharr-media-library.json"
    if not path.is_file():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    output = set()
    for value in data.get("files", []):
        relative = Path(str(value))
        if (
            not relative.is_absolute()
            and ".." not in relative.parts
            and relative.parts
            and relative.parts[0] in {"Movies", "TV Shows"}
            and relative.suffix in {".strm", ".nfo"}
        ):
            output.add(relative.as_posix())
    return output


def _write_manifest(root: Path, files: set[str], *, state: str) -> None:
    manifest = root / ".dispatcharr-media-library.json"
    _write_text(
        manifest,
        json.dumps(
            {"version": 1, "state": state, "files": sorted(files)},
            ensure_ascii=False,
            indent=2,
        ),
    )


def _remove_empty_managed_directories(root: Path) -> None:
    for top_name in ("Movies", "TV Shows"):
        top = _safe_output_path(root, Path(top_name))
        if not top.exists() or top.is_symlink():
            continue
        directories = sorted(
            (path for path in top.rglob("*") if path.is_dir() and not path.is_symlink()),
            key=lambda path: len(path.parts),
            reverse=True,
        )
        for directory in directories:
            try:
                directory.rmdir()
            except OSError:
                pass


def remove_managed_export_files(target) -> dict:
    """Remove only files owned by this target's completed export manifest."""
    root = resolve_export_path(
        target.output_root,
        must_exist=True,
        require_directory=True,
    )
    managed = _load_manifest(root)
    deleted = 0
    missing = 0
    for relative in sorted(managed):
        destination = _safe_output_path(root, Path(relative))
        if destination.is_symlink():
            raise ValueError("Refusing to remove a symlink from an export target")
        try:
            destination.unlink()
            deleted += 1
        except FileNotFoundError:
            missing += 1
    _remove_empty_managed_directories(root)
    manifest = _safe_output_path(root, Path(".dispatcharr-media-library.json"))
    if manifest.is_symlink():
        raise ValueError("Refusing to remove a symlinked export manifest")
    try:
        manifest.unlink()
    except FileNotFoundError:
        pass
    return {
        "output_root": str(root),
        "managed_files_deleted": deleted,
        "managed_files_missing": missing,
    }


def build_strm_nfo_snapshot(target, *, cancel_check=None) -> dict:
    """Build a recoverable, manifest-owned STRM/NFO snapshot for one target."""
    root = resolve_export_path(
        target.output_root,
        must_exist=False,
        require_directory=True,
    )
    root.mkdir(parents=True, exist_ok=True)
    root = resolve_export_path(str(root), must_exist=True, require_directory=True)

    movie_relations_qs = M3UMovieRelation.objects.select_related("m3u_account").filter(
        m3u_account__is_active=True
    )
    movies_qs = (
        Movie.objects.filter(m3u_relations__m3u_account__is_active=True)
        .distinct()
        .select_related("logo")
        .prefetch_related(Prefetch("m3u_relations", queryset=movie_relations_qs))
        .order_by("name", "year", "id")
    )
    series_relations_qs = M3USeriesRelation.objects.select_related("m3u_account").filter(
        m3u_account__is_active=True
    )
    episode_relations_qs = M3UEpisodeRelation.objects.select_related("m3u_account").filter(
        m3u_account__is_active=True
    )
    episodes_qs = Episode.objects.prefetch_related(
        Prefetch("m3u_relations", queryset=episode_relations_qs)
    ).order_by("season_number", "episode_number", "id")
    series_qs = (
        Series.objects.filter(episodes__m3u_relations__m3u_account__is_active=True)
        .distinct()
        .select_related("logo")
        .prefetch_related(
            Prefetch("m3u_relations", queryset=series_relations_qs),
            Prefetch("episodes", queryset=episodes_qs),
        )
        .order_by("name", "year", "id")
    )

    desired: dict[str, str] = {}
    used_show_roots: set[str] = set()
    movies_written = series_written = episodes_written = 0
    nfo_written = strm_written = 0

    for movie in movies_qs:
        if cancel_check:
            cancel_check()
        relation = _best_relation(_relation_list(movie.m3u_relations))
        if not relation:
            continue
        movie_name = _movie_display_name(movie)
        base = Path("Movies") / movie_name / movie_name
        if base.with_suffix(".strm").as_posix() in desired:
            movie_name = _sanitize_filename(
                f"{movie_name} [{str(movie.uuid)[:8]}]"
            )
            base = Path("Movies") / movie_name / movie_name
        desired[base.with_suffix(".strm").as_posix()] = _stream_url(
            target, "movie", movie.uuid
        )
        strm_written += 1
        if target.include_nfo:
            desired[base.with_suffix(".nfo").as_posix()] = _build_movie_nfo(
                movie, relation, base_url=target.playback_base_url
            )
            nfo_written += 1
        movies_written += 1

    for series in series_qs:
        if cancel_check:
            cancel_check()
        series_relation = _best_relation(_relation_list(series.m3u_relations))
        series_name = _sanitize_filename(series.name, fallback=f"Series-{series.id}")
        show_root = Path("TV Shows") / series_name
        if show_root.as_posix() in used_show_roots:
            series_name = _sanitize_filename(
                f"{series_name} [{str(series.uuid)[:8]}]"
            )
            show_root = Path("TV Shows") / series_name
        used_show_roots.add(show_root.as_posix())
        series_has_episode = False
        for episode in _relation_list(series.episodes):
            if cancel_check:
                cancel_check()
            episode_relation = _best_relation(_relation_list(episode.m3u_relations))
            if not episode_relation:
                continue
            season_num = _safe_int(episode.season_number) or 0
            episode_num = _safe_int(episode.episode_number) or 0
            episode_base = _episode_base_name(series_name, season_num, episode_num)
            base = show_root / f"Season {season_num:02d}" / episode_base
            if base.with_suffix(".strm").as_posix() in desired:
                episode_base = _sanitize_filename(
                    f"{episode_base} [{str(episode.uuid)[:8]}]"
                )
                base = show_root / f"Season {season_num:02d}" / episode_base
            desired[base.with_suffix(".strm").as_posix()] = _stream_url(
                target, "episode", episode.uuid
            )
            strm_written += 1
            series_has_episode = True
            episodes_written += 1
            if target.include_nfo:
                desired[base.with_suffix(".nfo").as_posix()] = _build_episode_nfo(
                    series, episode, episode_relation,
                    base_url=target.playback_base_url,
                )
                nfo_written += 1
        if series_has_episode:
            series_written += 1
            if target.include_nfo:
                desired[(show_root / "tvshow.nfo").as_posix()] = _build_tvshow_nfo(
                    series, series_relation, base_url=target.playback_base_url
                )
                nfo_written += 1

    previous = _load_manifest(root)
    desired_files = set(desired)
    _write_manifest(root, previous | desired_files, state="building")
    for relative, contents in desired.items():
        if cancel_check:
            cancel_check()
        _write_text(_safe_output_path(root, Path(relative)), contents)

    for relative in sorted(previous - desired_files):
        if cancel_check:
            cancel_check()
        stale = _safe_output_path(root, Path(relative))
        if stale.is_symlink():
            raise ValueError("Refusing to remove a symlink from an export target")
        try:
            stale.unlink()
        except FileNotFoundError:
            pass

    _remove_empty_managed_directories(root)
    _write_manifest(root, desired_files, state="complete")
    return {
        "output_root": str(root),
        "base_url": target.playback_base_url.rstrip("/"),
        "include_nfo": bool(target.include_nfo),
        "movies_written": movies_written,
        "series_written": series_written,
        "episodes_written": episodes_written,
        "strm_files_written": strm_written,
        "nfo_files_written": nfo_written,
        "total_files_written": strm_written + nfo_written,
        "stale_files_removed": len(previous - desired_files),
    }
