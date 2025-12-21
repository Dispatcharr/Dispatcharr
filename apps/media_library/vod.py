import mimetypes
import os
from typing import Optional

from apps.media_library.models import Library, MediaFile, MediaItem, MediaItemVODLink
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


def _account_name(library: Library) -> str:
    return f"{LIBRARY_ACCOUNT_PREFIX} {library.id}: {library.name}"


def _local_tmdb_id(media_item: MediaItem) -> str:
    return f"{LOCAL_TMDB_PREFIX}:{media_item.id}"


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
    return (
        media_item.files.filter(is_primary=True).first()
        or media_item.files.first()
    )


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
    if not media_item.poster_url:
        return None
    logo, _ = VODLogo.objects.get_or_create(
        url=media_item.poster_url, defaults={"name": media_item.title}
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

    movie = link.vod_movie
    if not movie:
        movie = Movie.objects.filter(tmdb_id=_local_tmdb_id(media_item)).first()
    if not movie:
        movie = Movie.objects.create(
            name=media_item.title,
            description=media_item.synopsis or "",
            year=media_item.release_year,
            rating=media_item.rating or "",
            genre=_genre_string(media_item),
            duration_secs=_runtime_secs(media_item),
            tmdb_id=_local_tmdb_id(media_item),
            custom_properties=custom_properties,
            logo=logo,
        )
    else:
        movie.name = media_item.title
        movie.description = media_item.synopsis or ""
        movie.year = media_item.release_year
        movie.rating = media_item.rating or ""
        movie.genre = _genre_string(media_item)
        movie.duration_secs = _runtime_secs(media_item)
        movie.custom_properties = _merge_custom_properties(movie.custom_properties, custom_properties)
        if logo:
            movie.logo = logo
        movie.save()

    link.vod_movie = movie
    link.vod_series = None
    link.vod_episode = None
    link.save(update_fields=["vod_movie", "vod_series", "vod_episode", "updated_at"])

    file = _get_primary_file(media_item)
    if not file:
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


def _sync_series(media_item: MediaItem, account: M3UAccount, link: MediaItemVODLink) -> None:
    logo = _ensure_logo(media_item)
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

    series = link.vod_series
    if not series:
        series = Series.objects.filter(tmdb_id=_local_tmdb_id(media_item)).first()
    if not series:
        series = Series.objects.create(
            name=media_item.title,
            description=media_item.synopsis or "",
            year=media_item.release_year,
            rating=media_item.rating or "",
            genre=_genre_string(media_item),
            tmdb_id=_local_tmdb_id(media_item),
            custom_properties=custom_properties,
            logo=logo,
        )
    else:
        series.name = media_item.title
        series.description = media_item.synopsis or ""
        series.year = media_item.release_year
        series.rating = media_item.rating or ""
        series.genre = _genre_string(media_item)
        series.custom_properties = _merge_custom_properties(series.custom_properties, custom_properties)
        if logo:
            series.logo = logo
        series.save()

    link.vod_series = series
    link.vod_movie = None
    link.vod_episode = None
    link.save(update_fields=["vod_series", "vod_movie", "vod_episode", "updated_at"])

    category = _ensure_uncategorized("series")
    M3USeriesRelation.objects.update_or_create(
        m3u_account=account,
        series=series,
        defaults={
            "category": category,
            "external_series_id": str(media_item.id),
            "custom_properties": _merge_custom_properties(
                {},
                {
                    "source": "media-library",
                    "library_id": media_item.library_id,
                    "media_item_id": media_item.id,
                },
            ),
        },
    )


def _sync_episode(media_item: MediaItem, account: M3UAccount, link: MediaItemVODLink) -> None:
    if not media_item.parent_id:
        return
    parent = media_item.parent
    if not parent:
        return

    parent_link, _ = MediaItemVODLink.objects.get_or_create(media_item=parent)
    if not parent_link.vod_series:
        _sync_series(parent, account, parent_link)
        parent_link.refresh_from_db(fields=["vod_series"])

    if not parent_link.vod_series:
        return

    logo = _ensure_logo(media_item) or _ensure_logo(parent)
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

    episode = link.vod_episode
    if not episode:
        episode = Episode.objects.filter(tmdb_id=_local_tmdb_id(media_item)).first()
    if not episode:
        episode = Episode.objects.create(
            name=media_item.title,
            description=media_item.synopsis or "",
            season_number=media_item.season_number,
            episode_number=media_item.episode_number,
            series=parent_link.vod_series,
            tmdb_id=_local_tmdb_id(media_item),
            custom_properties=custom_properties,
            duration_secs=_runtime_secs(media_item),
        )
    else:
        episode.name = media_item.title
        episode.description = media_item.synopsis or ""
        episode.season_number = media_item.season_number
        episode.episode_number = media_item.episode_number
        episode.duration_secs = _runtime_secs(media_item)
        episode.custom_properties = _merge_custom_properties(episode.custom_properties, custom_properties)
        episode.save()

    link.vod_episode = episode
    link.vod_movie = None
    link.vod_series = None
    link.save(update_fields=["vod_episode", "vod_movie", "vod_series", "updated_at"])

    file = _get_primary_file(media_item)
    if not file:
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
