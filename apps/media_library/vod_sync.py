"""
Helpers for synchronizing local media library items with the VOD catalog.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.media_library.models import Library, MediaFile, MediaItem
from apps.vod.models import Episode, Movie, Series


def _select_primary_file(media_item: MediaItem) -> MediaFile | None:
    """Pick the best representative file for metadata (prefer longest duration)."""
    return (
        media_item.files.order_by("-duration_ms", "-size_bytes", "id").first()
        if media_item.pk
        else None
    )


def _duration_seconds(media_item: MediaItem) -> int | None:
    if media_item.runtime_ms:
        return int(media_item.runtime_ms / 1000)
    file_record = _select_primary_file(media_item)
    if file_record and file_record.duration_ms:
        return int(file_record.duration_ms / 1000)
    return None


def _collect_quality_info(media_item: MediaItem) -> dict[str, Any] | None:
    file_record = _select_primary_file(media_item)
    if not file_record:
        return None
    payload: dict[str, Any] = {}
    if file_record.bitrate:
        payload["bitrate"] = file_record.bitrate
    video_payload: dict[str, Any] = {}
    if file_record.width and file_record.height:
        video_payload["width"] = file_record.width
        video_payload["height"] = file_record.height
    if file_record.video_codec:
        video_payload["codec"] = file_record.video_codec
    if file_record.frame_rate:
        video_payload["frame_rate"] = file_record.frame_rate
    if video_payload:
        payload["video"] = video_payload

    audio_payload: dict[str, Any] = {}
    if file_record.audio_codec:
        audio_payload["codec"] = file_record.audio_codec
    if file_record.audio_channels:
        audio_payload["channels"] = file_record.audio_channels
    if audio_payload:
        payload["audio"] = audio_payload

    if file_record.container:
        payload["container"] = file_record.container

    if not payload:
        return None
    return payload


def _merge_custom_properties(existing: dict[str, Any] | None, updates: dict[str, Any]) -> dict[str, Any]:
    data = dict(existing or {})
    data.update({key: value for key, value in updates.items() if value is not None})
    return data


def _update_movie_from_media_item(movie: Movie, media_item: MediaItem) -> Movie:
    fields_to_update: list[str] = []

    def set_field(field: str, value: Any):
        nonlocal fields_to_update
        if getattr(movie, field) != value and value is not None:
            setattr(movie, field, value)
            fields_to_update.append(field)

    set_field("name", media_item.title or movie.name)
    set_field("description", media_item.synopsis or movie.description)
    set_field("year", media_item.release_year or movie.year)
    set_field("rating", media_item.rating or movie.rating)
    genres = ", ".join(media_item.genres) if isinstance(media_item.genres, Iterable) else None
    set_field("genre", genres or movie.genre)
    duration = _duration_seconds(media_item)
    set_field("duration_secs", duration or movie.duration_secs)

    if media_item.tmdb_id and movie.tmdb_id != media_item.tmdb_id:
        movie.tmdb_id = media_item.tmdb_id
        fields_to_update.append("tmdb_id")
    if media_item.imdb_id and movie.imdb_id != media_item.imdb_id:
        movie.imdb_id = media_item.imdb_id
        fields_to_update.append("imdb_id")

    quality_info = _collect_quality_info(media_item) or {}
    custom_updates = {
        "source": "library",
        "library_id": media_item.library_id,
        "library_item_id": media_item.id,
        "poster_url": media_item.poster_url,
        "backdrop_url": media_item.backdrop_url,
        "quality": quality_info,
    }
    merged_custom = _merge_custom_properties(movie.custom_properties, custom_updates)
    if merged_custom != movie.custom_properties:
        movie.custom_properties = merged_custom
        fields_to_update.append("custom_properties")

    if fields_to_update:
        movie.save(update_fields=fields_to_update + ["updated_at"])
    return movie


def _update_series_from_media_item(series: Series, media_item: MediaItem) -> Series:
    fields_to_update: list[str] = []

    def set_field(field: str, value: Any):
        nonlocal fields_to_update
        if getattr(series, field) != value and value is not None:
            setattr(series, field, value)
            fields_to_update.append(field)

    set_field("name", media_item.title or series.name)
    set_field("description", media_item.synopsis or series.description)
    set_field("year", media_item.release_year or series.year)
    set_field("rating", media_item.rating or series.rating)
    genres = ", ".join(media_item.genres) if isinstance(media_item.genres, Iterable) else None
    set_field("genre", genres or series.genre)

    if media_item.tmdb_id and series.tmdb_id != media_item.tmdb_id:
        series.tmdb_id = media_item.tmdb_id
        fields_to_update.append("tmdb_id")
    if media_item.imdb_id and series.imdb_id != media_item.imdb_id:
        series.imdb_id = media_item.imdb_id
        fields_to_update.append("imdb_id")

    custom_updates = {
        "source": "library",
        "library_id": media_item.library_id,
        "library_item_id": media_item.id,
        "poster_url": media_item.poster_url,
        "backdrop_url": media_item.backdrop_url,
    }
    merged_custom = _merge_custom_properties(series.custom_properties, custom_updates)
    if merged_custom != series.custom_properties:
        series.custom_properties = merged_custom
        fields_to_update.append("custom_properties")

    if fields_to_update:
        series.save(update_fields=fields_to_update + ["updated_at"])
    return series


def _update_episode_from_media_item(episode: Episode, media_item: MediaItem, series: Series) -> Episode:
    fields_to_update: list[str] = []

    def set_field(field: str, value: Any):
        nonlocal fields_to_update
        if getattr(episode, field) != value and value is not None:
            setattr(episode, field, value)
            fields_to_update.append(field)

    set_field("name", media_item.title or episode.name)
    set_field("description", media_item.synopsis or episode.description)
    set_field("season_number", media_item.season_number or episode.season_number)
    set_field("episode_number", media_item.episode_number or episode.episode_number)
    duration = _duration_seconds(media_item)
    set_field("duration_secs", duration or episode.duration_secs)

    if media_item.tmdb_id and episode.tmdb_id != media_item.tmdb_id:
        episode.tmdb_id = media_item.tmdb_id
        fields_to_update.append("tmdb_id")
    if media_item.imdb_id and episode.imdb_id != media_item.imdb_id:
        episode.imdb_id = media_item.imdb_id
        fields_to_update.append("imdb_id")

    quality_info = _collect_quality_info(media_item)
    custom_updates = {
        "source": "library",
        "library_id": media_item.library_id,
        "library_item_id": media_item.id,
        "quality": quality_info,
    }
    merged_custom = _merge_custom_properties(episode.custom_properties, custom_updates)
    if merged_custom != episode.custom_properties:
        episode.custom_properties = merged_custom
        fields_to_update.append("custom_properties")

    if episode.series_id != series.id:
        episode.series = series
        fields_to_update.append("series")

    if fields_to_update:
        episode.save(update_fields=fields_to_update + ["updated_at"])
    return episode


@transaction.atomic
def sync_media_item_to_vod(media_item: MediaItem) -> None:
    """
    Ensure the provided media item is represented in the VOD catalog if its library
    is configured as a VOD source. When disabled, remove any previously linked VOD entries.
    """
    if not media_item.pk:
        return

    library: Library = media_item.library
    if not library.use_as_vod_source:
        remove_media_item_from_vod(media_item)
        return

    now = timezone.now()

    if media_item.item_type == MediaItem.TYPE_MOVIE:
        movie = None
        if media_item.vod_movie_id:
            movie = Movie.objects.filter(pk=media_item.vod_movie_id).first()
        if not movie and media_item.tmdb_id:
            movie = Movie.objects.filter(tmdb_id=media_item.tmdb_id).first()
        if not movie and media_item.imdb_id:
            movie = Movie.objects.filter(imdb_id=media_item.imdb_id).first()
        if not movie:
            movie = Movie.objects.create(
                name=media_item.title or "Untitled Movie",
                description=media_item.synopsis or "",
                year=media_item.release_year,
                rating=media_item.rating or "",
                genre=", ".join(media_item.genres) if isinstance(media_item.genres, Iterable) else "",
                duration_secs=_duration_seconds(media_item),
                tmdb_id=media_item.tmdb_id,
                imdb_id=media_item.imdb_id,
                custom_properties={
                    "source": "library",
                    "library_id": media_item.library_id,
                    "library_item_id": media_item.id,
                },
            )
        movie = _update_movie_from_media_item(movie, media_item)
        if media_item.vod_movie_id != movie.id:
            media_item.vod_movie = movie
            media_item.save(update_fields=["vod_movie", "updated_at"])
        movie.custom_properties["synced_at"] = now.isoformat()
        movie.save(update_fields=["custom_properties", "updated_at"])

    elif media_item.item_type == MediaItem.TYPE_SHOW:
        series = None
        if media_item.vod_series_id:
            series = Series.objects.filter(pk=media_item.vod_series_id).first()
        if not series and media_item.tmdb_id:
            series = Series.objects.filter(tmdb_id=media_item.tmdb_id).first()
        if not series and media_item.imdb_id:
            series = Series.objects.filter(imdb_id=media_item.imdb_id).first()
        if not series:
            series = Series.objects.create(
                name=media_item.title or "Untitled Series",
                description=media_item.synopsis or "",
                year=media_item.release_year,
                rating=media_item.rating or "",
                genre=", ".join(media_item.genres) if isinstance(media_item.genres, Iterable) else "",
                tmdb_id=media_item.tmdb_id,
                imdb_id=media_item.imdb_id,
                custom_properties={
                    "source": "library",
                    "library_id": media_item.library_id,
                    "library_item_id": media_item.id,
                },
            )
        series = _update_series_from_media_item(series, media_item)
        if media_item.vod_series_id != series.id:
            media_item.vod_series = series
            media_item.save(update_fields=["vod_series", "updated_at"])
        series.custom_properties["synced_at"] = now.isoformat()
        series.save(update_fields=["custom_properties", "updated_at"])

    elif media_item.item_type == MediaItem.TYPE_EPISODE:
        parent = media_item.parent
        if parent:
            sync_media_item_to_vod(parent)
            series = parent.vod_series
        else:
            series = None
        if not series:
            # Ensure there is a series placeholder to attach this episode.
            series = Series.objects.create(
                name=media_item.title or "Series",
                description="Library-sourced series",
                custom_properties={
                    "source": "library",
                    "library_id": media_item.library_id,
                },
            )

        episode = None
        if media_item.vod_episode_id:
            episode = Episode.objects.filter(pk=media_item.vod_episode_id).first()
        if not episode and media_item.tmdb_id:
            episode = Episode.objects.filter(tmdb_id=media_item.tmdb_id).first()
        if not episode and media_item.imdb_id:
            episode = Episode.objects.filter(imdb_id=media_item.imdb_id).first()
        if not episode:
            episode = Episode.objects.create(
                series=series,
                name=media_item.title or "Episode",
                description=media_item.synopsis or "",
                season_number=media_item.season_number,
                episode_number=media_item.episode_number,
                duration_secs=_duration_seconds(media_item),
                tmdb_id=media_item.tmdb_id,
                imdb_id=media_item.imdb_id,
                custom_properties={
                    "source": "library",
                    "library_id": media_item.library_id,
                    "library_item_id": media_item.id,
                },
            )
        episode = _update_episode_from_media_item(episode, media_item, series)
        if media_item.vod_episode_id != episode.id:
            media_item.vod_episode = episode
            media_item.save(update_fields=["vod_episode", "updated_at"])
        episode.custom_properties["synced_at"] = now.isoformat()
        episode.save(update_fields=["custom_properties", "updated_at"])


@transaction.atomic
def remove_media_item_from_vod(media_item: MediaItem) -> None:
    """Detach a media item from the VOD catalog and prune orphaned entries."""
    if media_item.vod_movie_id:
        movie = Movie.objects.filter(pk=media_item.vod_movie_id).first()
        media_item.vod_movie = None
        media_item.save(update_fields=["vod_movie", "updated_at"])
        if movie and not movie.m3u_relations.exists() and not movie.library_items.exists():
            movie.delete()

    if media_item.vod_episode_id:
        episode = Episode.objects.filter(pk=media_item.vod_episode_id).first()
        series = episode.series if episode else None
        media_item.vod_episode = None
        media_item.save(update_fields=["vod_episode", "updated_at"])
        if episode and not episode.m3u_relations.exists() and not episode.library_items.exists():
            episode.delete()

        if series and not series.m3u_relations.exists() and not series.library_items.exists():
            # Only remove episode-less series that were sourced from library content.
            if (series.custom_properties or {}).get("source") == "library":
                series.delete()

    if media_item.vod_series_id and media_item.item_type == MediaItem.TYPE_SHOW:
        series = Series.objects.filter(pk=media_item.vod_series_id).first()
        media_item.vod_series = None
        media_item.save(update_fields=["vod_series", "updated_at"])
        if series and not series.m3u_relations.exists() and not series.library_items.exists():
            if (series.custom_properties or {}).get("source") == "library":
                series.delete()


def sync_library_to_vod(library: Library) -> None:
    """Synchronize all media items in a library with the VOD catalog."""
    for media_item in library.items.select_related("parent").all():
        sync_media_item_to_vod(media_item)


def unsync_library_from_vod(library: Library) -> None:
    """Remove all VOD links for items in a library."""
    for media_item in library.items.all():
        remove_media_item_from_vod(media_item)
