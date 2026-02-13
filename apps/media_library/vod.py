import mimetypes
import os
from typing import Optional

from django.utils import timezone

from apps.media_library.models import Library, MediaFile, MediaItem, MediaItemVODLink
from apps.media_library.file_utils import primary_media_file_for_item
from apps.m3u.models import M3UAccount
from apps.vod.models import (
    Episode,
    M3UEpisodeRelation,
    M3UMovieRelation,
    M3USeriesRelation,
    Movie,
    Series,
    VODCategory,
    VODLogo,
)

LIBRARY_ACCOUNT_PREFIX = "Media Library"
LOCAL_TMDB_PREFIX = "ml"
UNCATEGORIZED_NAME = "Uncategorized"
MEDIA_LIBRARY_BASE_URL_ENV = "DISPATCHARR_PUBLIC_API_BASE"
MEDIA_LIBRARY_BASE_URL_FALLBACK_ENV = "DISPATCHARR_MEDIA_LIBRARY_BASE_URL"
MEDIA_LIBRARY_DEV_FALLBACK = "http://localhost:5656"


def _is_dev_runtime() -> bool:
    return (
        os.environ.get("DISPATCHARR_ENV", "").lower() == "dev"
        or os.environ.get("DISPATCHARR_DEBUG", "").lower() == "true"
        or os.environ.get("REDIS_HOST", "redis") in ("localhost", "127.0.0.1")
    )


def _account_name(library: Library) -> str:
    return f"{LIBRARY_ACCOUNT_PREFIX} {library.id}: {library.name}"


def _local_tmdb_id(media_item: MediaItem) -> str:
    return f"{LOCAL_TMDB_PREFIX}:{media_item.id}"


def _media_library_base_url() -> str:
    base = os.environ.get(MEDIA_LIBRARY_BASE_URL_ENV) or os.environ.get(
        MEDIA_LIBRARY_BASE_URL_FALLBACK_ENV
    )
    if not base and _is_dev_runtime():
        base = MEDIA_LIBRARY_DEV_FALLBACK
    if not base:
        return ""
    return base.rstrip("/")


def _media_library_poster_url(media_item: MediaItem) -> Optional[str]:
    poster_url = (media_item.poster_url or "").strip()
    if not poster_url:
        return None
    if poster_url.startswith("/"):
        base = _media_library_base_url()
        if base:
            return f"{base}{poster_url}"
    return poster_url


def _normalize_external_id(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def _media_item_external_ids(media_item: MediaItem) -> tuple[Optional[str], Optional[str]]:
    imdb_id = _normalize_external_id(media_item.imdb_id)

    tmdb_id = None
    metadata = media_item.metadata if isinstance(media_item.metadata, dict) else {}
    tmdb_id = _normalize_external_id(metadata.get("tmdb_id"))
    if not tmdb_id and media_item.metadata_source in {"tmdb", "nfo"}:
        tmdb_id = _normalize_external_id(media_item.movie_db_id)

    return imdb_id, tmdb_id


def _first_if_unique(queryset):
    matches = list(queryset[:2])
    if len(matches) == 1:
        return matches[0]
    return None


def _find_existing_movie(media_item: MediaItem) -> Optional[Movie]:
    imdb_id, tmdb_id = _media_item_external_ids(media_item)

    if tmdb_id:
        movie = Movie.objects.filter(tmdb_id=tmdb_id).first()
        if movie:
            return movie

    if imdb_id:
        movie = Movie.objects.filter(imdb_id=imdb_id).first()
        if movie:
            return movie

    if media_item.title and media_item.release_year:
        return _first_if_unique(
            Movie.objects.filter(
                name__iexact=media_item.title,
                year=media_item.release_year,
            )
        )

    return None


def _find_existing_series(media_item: MediaItem) -> Optional[Series]:
    imdb_id, tmdb_id = _media_item_external_ids(media_item)

    if tmdb_id:
        series = Series.objects.filter(tmdb_id=tmdb_id).first()
        if series:
            return series

    if imdb_id:
        series = Series.objects.filter(imdb_id=imdb_id).first()
        if series:
            return series

    if media_item.title and media_item.release_year:
        return _first_if_unique(
            Series.objects.filter(
                name__iexact=media_item.title,
                year=media_item.release_year,
            )
        )

    return None


def _find_existing_episode(series: Series, media_item: MediaItem) -> Optional[Episode]:
    if not series:
        return None
    if media_item.season_number is None or media_item.episode_number is None:
        return None
    return Episode.objects.filter(
        series=series,
        season_number=media_item.season_number,
        episode_number=media_item.episode_number,
    ).first()


def _set_if_blank(obj, field: str, value) -> bool:
    if value in (None, "", [], {}):
        return False
    existing = getattr(obj, field)
    if existing in (None, "", [], {}):
        setattr(obj, field, value)
        return True
    return False


def _cleanup_old_movie_link(account: M3UAccount, previous_id: Optional[int], new_id: int) -> None:
    if not previous_id or previous_id == new_id:
        return
    M3UMovieRelation.objects.filter(m3u_account=account, movie_id=previous_id).delete()
    Movie.objects.filter(
        id=previous_id,
        m3u_relations__isnull=True,
        media_library_links__isnull=True,
    ).delete()


def _cleanup_old_series_link(account: M3UAccount, previous_id: Optional[int], new_id: int) -> None:
    if not previous_id or previous_id == new_id:
        return
    M3USeriesRelation.objects.filter(m3u_account=account, series_id=previous_id).delete()
    Series.objects.filter(
        id=previous_id,
        m3u_relations__isnull=True,
        episodes__isnull=True,
        media_library_links__isnull=True,
    ).delete()


def _cleanup_old_episode_link(account: M3UAccount, previous_id: Optional[int], new_id: int) -> None:
    if not previous_id or previous_id == new_id:
        return
    M3UEpisodeRelation.objects.filter(m3u_account=account, episode_id=previous_id).delete()
    Episode.objects.filter(
        id=previous_id,
        m3u_relations__isnull=True,
        media_library_links__isnull=True,
    ).delete()


def _ensure_uncategorized(category_type: str) -> VODCategory:
    category, _ = VODCategory.objects.get_or_create(
        name=UNCATEGORIZED_NAME, category_type=category_type
    )
    return category


def _merge_custom_properties(existing: Optional[dict], updates: dict) -> dict:
    merged = dict(existing or {})
    for key, value in updates.items():
        if value in (None, "", [], {}):
            continue
        merged[key] = value
    return merged


def _get_primary_file(media_item: MediaItem) -> Optional[MediaFile]:
    return primary_media_file_for_item(media_item)


def ensure_library_vod_account(library: Library) -> M3UAccount:
    desired_name = _account_name(library)
    if library.vod_account_id:
        account = library.vod_account
        if account and account.name != desired_name:
            account.name = desired_name
            account.save(update_fields=["name"])
        return account

    account = (
        M3UAccount.objects.filter(custom_properties__media_library_id=library.id).first()
    )
    if account:
        if account.name != desired_name:
            account.name = desired_name
            account.save(update_fields=["name"])
        library.vod_account = account
        library.save(update_fields=["vod_account"])
        return account

    account = M3UAccount.objects.create(
        name=desired_name,
        account_type=M3UAccount.Types.STADNARD,
        is_active=library.add_to_vod,
        locked=True,
        priority=0,
        custom_properties={
            "media_library_id": library.id,
            "source": "media-library",
        },
    )
    library.vod_account = account
    library.save(update_fields=["vod_account"])
    return account


def sync_library_vod_account_state(library: Library) -> M3UAccount:
    account = ensure_library_vod_account(library)
    if account.is_active != library.add_to_vod:
        account.is_active = library.add_to_vod
        account.save(update_fields=["is_active"])
    return account


def _ensure_logo(media_item: MediaItem) -> Optional[VODLogo]:
    poster_url = _media_library_poster_url(media_item)
    if not poster_url:
        return None

    if poster_url != media_item.poster_url:
        existing = VODLogo.objects.filter(url=poster_url).first()
        if existing:
            return existing
        legacy = VODLogo.objects.filter(url=media_item.poster_url).first()
        if legacy:
            legacy.url = poster_url
            legacy.name = media_item.title
            legacy.save(update_fields=["url", "name"])
            return legacy

    logo, _ = VODLogo.objects.get_or_create(
        url=poster_url, defaults={"name": media_item.title}
    )
    return logo


def _runtime_secs(media_item: MediaItem) -> Optional[int]:
    if media_item.runtime_ms:
        return int(media_item.runtime_ms / 1000)
    return None


def _genre_string(media_item: MediaItem) -> str:
    if isinstance(media_item.genres, list) and media_item.genres:
        return ", ".join([str(entry) for entry in media_item.genres if entry])
    return ""


def _file_container_extension(file: Optional[MediaFile]) -> Optional[str]:
    if not file or not file.file_name:
        return None
    _base, ext = os.path.splitext(file.file_name)
    return ext[1:].lower() if ext else None


def _relation_payload(media_item: MediaItem, file: Optional[MediaFile]) -> dict:
    return _merge_custom_properties(
        {},
        {
            "source": "media-library",
            "library_id": media_item.library_id,
            "media_item_id": media_item.id,
            "file_id": file.id if file else None,
            "file_path": file.path if file else None,
            "file_name": file.file_name if file else None,
            "file_size_bytes": file.size_bytes if file else None,
            "file_mime": mimetypes.guess_type(file.path)[0] if file else None,
        },
    )


def _update_series_relation_flags(relation: M3USeriesRelation, media_item: MediaItem) -> None:
    custom_properties = _merge_custom_properties(
        relation.custom_properties,
        {
            "source": "media-library",
            "library_id": media_item.library_id,
            "media_item_id": media_item.id,
            "episodes_fetched": True,
            "detailed_fetched": True,
        },
    )
    update_fields = ["last_episode_refresh", "updated_at"]
    relation.last_episode_refresh = timezone.now()
    if custom_properties != (relation.custom_properties or {}):
        relation.custom_properties = custom_properties
        update_fields.append("custom_properties")
    relation.save(update_fields=update_fields)


def sync_vod_for_media_item(media_item: MediaItem) -> None:
    library = media_item.library
    account = sync_library_vod_account_state(library)
    link, _ = MediaItemVODLink.objects.get_or_create(media_item=media_item)

    if media_item.item_type == MediaItem.TYPE_MOVIE:
        _sync_movie(media_item, account, link)
    elif media_item.item_type == MediaItem.TYPE_SHOW:
        _sync_series(media_item, account, link)
    elif media_item.item_type == MediaItem.TYPE_EPISODE:
        _sync_episode(media_item, account, link)


def _sync_movie(media_item: MediaItem, account: M3UAccount, link: MediaItemVODLink) -> None:
    logo = _ensure_logo(media_item)
    imdb_id, tmdb_id = _media_item_external_ids(media_item)
    custom_properties = _merge_custom_properties(
        {},
        {
            "source": "media-library",
            "movie_db_id": media_item.movie_db_id,
            "imdb_id": media_item.imdb_id,
            "poster_url": media_item.poster_url,
            "backdrop_url": media_item.backdrop_url,
            "tags": media_item.tags,
            "studios": media_item.studios,
        },
    )

    previous_movie_id = link.vod_movie_id
    movie = _find_existing_movie(media_item) or link.vod_movie
    if not movie:
        tmdb_value = tmdb_id or (None if imdb_id else _local_tmdb_id(media_item))
        movie = Movie.objects.create(
            name=media_item.title,
            description=media_item.synopsis or "",
            year=media_item.release_year,
            rating=media_item.rating or "",
            genre=_genre_string(media_item),
            duration_secs=_runtime_secs(media_item),
            tmdb_id=tmdb_value,
            imdb_id=imdb_id,
            custom_properties=custom_properties,
            logo=logo,
        )
    else:
        updated = False
        updated |= _set_if_blank(movie, "name", media_item.title)
        updated |= _set_if_blank(movie, "description", media_item.synopsis or "")
        updated |= _set_if_blank(movie, "year", media_item.release_year)
        updated |= _set_if_blank(movie, "rating", media_item.rating or "")
        updated |= _set_if_blank(movie, "genre", _genre_string(media_item))
        updated |= _set_if_blank(movie, "tmdb_id", tmdb_id)
        updated |= _set_if_blank(movie, "imdb_id", imdb_id)

        duration_secs = _runtime_secs(media_item)
        if movie.duration_secs in (None, 0) and duration_secs:
            movie.duration_secs = duration_secs
            updated = True

        merged_props = _merge_custom_properties(movie.custom_properties, custom_properties)
        if merged_props != (movie.custom_properties or {}):
            movie.custom_properties = merged_props
            updated = True

        if not movie.logo and logo:
            movie.logo = logo
            updated = True

        if updated:
            movie.save()

    link.vod_movie = movie
    link.vod_series = None
    link.vod_episode = None
    link.save(update_fields=["vod_movie", "vod_series", "vod_episode", "updated_at"])

    file = _get_primary_file(media_item)
    if not file:
        _cleanup_old_movie_link(account, previous_movie_id, movie.id)
        return

    category = _ensure_uncategorized("movie")
    M3UMovieRelation.objects.update_or_create(
        m3u_account=account,
        movie=movie,
        defaults={
            "category": category,
            "stream_id": str(media_item.id),
            "container_extension": _file_container_extension(file),
            "custom_properties": _relation_payload(media_item, file),
        },
    )
    _cleanup_old_movie_link(account, previous_movie_id, movie.id)


def _sync_series(media_item: MediaItem, account: M3UAccount, link: MediaItemVODLink) -> None:
    logo = _ensure_logo(media_item)
    imdb_id, tmdb_id = _media_item_external_ids(media_item)
    custom_properties = _merge_custom_properties(
        {},
        {
            "source": "media-library",
            "movie_db_id": media_item.movie_db_id,
            "imdb_id": media_item.imdb_id,
            "poster_url": media_item.poster_url,
            "backdrop_url": media_item.backdrop_url,
            "tags": media_item.tags,
            "studios": media_item.studios,
        },
    )

    previous_series_id = link.vod_series_id
    series = _find_existing_series(media_item) or link.vod_series
    if not series:
        tmdb_value = tmdb_id or (None if imdb_id else _local_tmdb_id(media_item))
        series = Series.objects.create(
            name=media_item.title,
            description=media_item.synopsis or "",
            year=media_item.release_year,
            rating=media_item.rating or "",
            genre=_genre_string(media_item),
            tmdb_id=tmdb_value,
            imdb_id=imdb_id,
            custom_properties=custom_properties,
            logo=logo,
        )
    else:
        updated = False
        updated |= _set_if_blank(series, "name", media_item.title)
        updated |= _set_if_blank(series, "description", media_item.synopsis or "")
        updated |= _set_if_blank(series, "year", media_item.release_year)
        updated |= _set_if_blank(series, "rating", media_item.rating or "")
        updated |= _set_if_blank(series, "genre", _genre_string(media_item))
        updated |= _set_if_blank(series, "tmdb_id", tmdb_id)
        updated |= _set_if_blank(series, "imdb_id", imdb_id)

        merged_props = _merge_custom_properties(series.custom_properties, custom_properties)
        if merged_props != (series.custom_properties or {}):
            series.custom_properties = merged_props
            updated = True

        if not series.logo and logo:
            series.logo = logo
            updated = True

        if updated:
            series.save()

    link.vod_series = series
    link.vod_movie = None
    link.vod_episode = None
    link.save(update_fields=["vod_series", "vod_movie", "vod_episode", "updated_at"])

    category = _ensure_uncategorized("series")
    relation, _ = M3USeriesRelation.objects.update_or_create(
        m3u_account=account,
        series=series,
        defaults={
            "category": category,
            "external_series_id": str(media_item.id),
        },
    )
    _update_series_relation_flags(relation, media_item)
    _cleanup_old_series_link(account, previous_series_id, series.id)


def _sync_episode(media_item: MediaItem, account: M3UAccount, link: MediaItemVODLink) -> None:
    if not media_item.parent_id:
        return
    parent = media_item.parent
    if not parent:
        return

    parent_link, _ = MediaItemVODLink.objects.get_or_create(media_item=parent)
    matched_series = _find_existing_series(parent)
    should_sync_series = (
        not parent_link.vod_series
        or (matched_series and parent_link.vod_series_id != matched_series.id)
    )
    if should_sync_series:
        _sync_series(parent, account, parent_link)
        parent_link.refresh_from_db(fields=["vod_series"])

    if not parent_link.vod_series:
        return

    category = _ensure_uncategorized("series")
    relation, _ = M3USeriesRelation.objects.update_or_create(
        m3u_account=account,
        series=parent_link.vod_series,
        defaults={
            "category": category,
            "external_series_id": str(parent.id),
        },
    )
    _update_series_relation_flags(relation, parent)

    imdb_id, tmdb_id = _media_item_external_ids(media_item)
    custom_properties = _merge_custom_properties(
        {},
        {
            "source": "media-library",
            "movie_db_id": media_item.movie_db_id,
            "imdb_id": media_item.imdb_id,
            "poster_url": media_item.poster_url,
            "backdrop_url": media_item.backdrop_url,
            "tags": media_item.tags,
            "studios": media_item.studios,
        },
    )

    previous_episode_id = link.vod_episode_id
    episode = _find_existing_episode(parent_link.vod_series, media_item) or link.vod_episode
    if not episode:
        episode = Episode.objects.create(
            name=media_item.title,
            description=media_item.synopsis or "",
            season_number=media_item.season_number,
            episode_number=media_item.episode_number,
            series=parent_link.vod_series,
            tmdb_id=tmdb_id,
            imdb_id=imdb_id,
            custom_properties=custom_properties,
            duration_secs=_runtime_secs(media_item),
        )
    else:
        updated = False
        updated |= _set_if_blank(episode, "name", media_item.title)
        updated |= _set_if_blank(episode, "description", media_item.synopsis or "")
        updated |= _set_if_blank(episode, "season_number", media_item.season_number)
        updated |= _set_if_blank(episode, "episode_number", media_item.episode_number)
        updated |= _set_if_blank(episode, "tmdb_id", tmdb_id)
        updated |= _set_if_blank(episode, "imdb_id", imdb_id)

        duration_secs = _runtime_secs(media_item)
        if episode.duration_secs in (None, 0) and duration_secs:
            episode.duration_secs = duration_secs
            updated = True

        merged_props = _merge_custom_properties(episode.custom_properties, custom_properties)
        if merged_props != (episode.custom_properties or {}):
            episode.custom_properties = merged_props
            updated = True

        if updated:
            episode.save()

    link.vod_episode = episode
    link.vod_movie = None
    link.vod_series = None
    link.save(update_fields=["vod_episode", "vod_movie", "vod_series", "updated_at"])

    file = _get_primary_file(media_item)
    if not file:
        _cleanup_old_episode_link(account, previous_episode_id, episode.id)
        return

    M3UEpisodeRelation.objects.update_or_create(
        m3u_account=account,
        episode=episode,
        defaults={
            "stream_id": str(media_item.id),
            "container_extension": _file_container_extension(file),
            "custom_properties": _relation_payload(media_item, file),
        },
    )
    _cleanup_old_episode_link(account, previous_episode_id, episode.id)


def cleanup_library_vod(library: Library) -> None:
    if not library:
        return

    link_qs = MediaItemVODLink.objects.filter(media_item__library=library)
    movie_ids = set(link_qs.exclude(vod_movie__isnull=True).values_list("vod_movie_id", flat=True))
    series_ids = set(link_qs.exclude(vod_series__isnull=True).values_list("vod_series_id", flat=True))
    episode_ids = set(link_qs.exclude(vod_episode__isnull=True).values_list("vod_episode_id", flat=True))

    account = library.vod_account
    if account:
        account.delete()

    if episode_ids:
        Episode.objects.filter(id__in=episode_ids, m3u_relations__isnull=True).delete()

    if series_ids:
        Series.objects.filter(id__in=series_ids, m3u_relations__isnull=True, episodes__isnull=True).delete()

    if movie_ids:
        Movie.objects.filter(id__in=movie_ids, m3u_relations__isnull=True).delete()


def cleanup_media_item_vod(media_item: MediaItem) -> None:
    if not media_item:
        return
    link = getattr(media_item, "vod_link", None)
    if not link:
        return

    account_id = None
    try:
        account_id = media_item.library.vod_account_id
    except Exception:
        account_id = None

    movie_id = link.vod_movie_id
    series_id = link.vod_series_id
    episode_id = link.vod_episode_id

    if account_id:
        if movie_id:
            M3UMovieRelation.objects.filter(
                m3u_account_id=account_id, movie_id=movie_id
            ).delete()
        if series_id:
            M3USeriesRelation.objects.filter(
                m3u_account_id=account_id, series_id=series_id
            ).delete()
        if episode_id:
            M3UEpisodeRelation.objects.filter(
                m3u_account_id=account_id, episode_id=episode_id
            ).delete()

    link.delete()

    if episode_id:
        Episode.objects.filter(id=episode_id, m3u_relations__isnull=True).delete()
    if series_id:
        Series.objects.filter(id=series_id, m3u_relations__isnull=True, episodes__isnull=True).delete()
    if movie_id:
        Movie.objects.filter(id=movie_id, m3u_relations__isnull=True).delete()
