import os
from datetime import timezone as dt_timezone
from dataclasses import dataclass, field
from typing import Callable, Iterable, Optional

from django.db.models import Q
from django.utils import timezone

from apps.media_library.classification import classify_media_entry
from apps.media_library.models import Library, MediaFile, MediaItem
from apps.media_library.utils import normalize_title

VIDEO_EXTENSIONS = {
    ".mkv",
    ".mp4",
    ".m4v",
    ".avi",
    ".mov",
    ".wmv",
    ".mpg",
    ".mpeg",
    ".ts",
    ".m2ts",
    ".webm",
}

PROGRESS_UPDATE_INTERVAL = 50
BULK_UPDATE_SIZE = 200
BULK_CREATE_SIZE = 200


class ScanCancelled(Exception):
    pass


@dataclass
class ScanResult:
    processed_files: int = 0
    total_files: int = 0
    new_files: int = 0
    updated_files: int = 0
    removed_files: int = 0
    unmatched_files: int = 0
    unmatched_paths: list[str] = field(default_factory=list)
    metadata_item_ids: set[int] = field(default_factory=set)
    errors: list[dict[str, str]] = field(default_factory=list)


def _is_media_file(file_name: str) -> bool:
    _, ext = os.path.splitext(file_name)
    return ext.lower() in VIDEO_EXTENSIONS


def _iter_location_files(base_path: str, include_subdirectories: bool) -> Iterable[str]:
    if include_subdirectories:
        for root, _dirs, files in os.walk(base_path):
            for file_name in files:
                yield os.path.join(root, file_name)
    else:
        for entry in os.scandir(base_path):
            if entry.is_file():
                yield entry.path


def _resolve_relative_path(full_path: str, base_path: str) -> str:
    relative = os.path.relpath(full_path, base_path)
    if relative == ".":
        return ""
    parent = os.path.dirname(relative)
    return "" if parent == "." else parent


def scan_library_files(
    library: Library,
    *,
    full: bool = False,
    progress_callback: Optional[Callable[[int, int], None]] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
) -> ScanResult:
    result = ScanResult()
    scan_start = timezone.now()

    existing_files = {
        row["path"]: row
        for row in MediaFile.objects.filter(library=library).values(
            "id",
            "path",
            "size_bytes",
            "modified_at",
            "media_item_id",
            "relative_path",
            "file_name",
            "duration_ms",
            "is_primary",
        )
    }

    primary_item_ids = set(
        MediaFile.objects.filter(library=library, is_primary=True).values_list(
            "media_item_id", flat=True
        )
    )

    movie_cache: dict[tuple[str, int | None], MediaItem] = {}
    show_cache: dict[str, MediaItem] = {}
    episode_cache: dict[tuple[int, int | None, int | None, str], MediaItem] = {}

    file_updates: list[MediaFile] = []
    file_creates: list[MediaFile] = []
    seen_paths: set[str] = set()

    def flush_updates():
        nonlocal file_updates, file_creates
        if file_updates:
            MediaFile.objects.bulk_update(
                file_updates,
                [
                    "media_item",
                    "relative_path",
                    "file_name",
                    "size_bytes",
                    "modified_at",
                    "duration_ms",
                    "is_primary",
                    "last_seen_at",
                ],
            )
            file_updates = []
        if file_creates:
            MediaFile.objects.bulk_create(file_creates)
            file_creates = []

    def get_or_create_movie(title: str, release_year: int | None) -> MediaItem:
        normalized = normalize_title(title)
        key = (normalized, release_year)
        if key in movie_cache:
            return movie_cache[key]
        query = MediaItem.objects.filter(
            library=library,
            item_type=MediaItem.TYPE_MOVIE,
            normalized_title=normalized,
        )
        if release_year:
            query = query.filter(release_year=release_year)
        item = query.first()
        if not item:
            item = MediaItem.objects.create(
                library=library,
                item_type=MediaItem.TYPE_MOVIE,
                title=title,
                sort_title=title,
                normalized_title=normalized,
                release_year=release_year,
            )
        movie_cache[key] = item
        return item

    def get_or_create_show(title: str, release_year: int | None) -> MediaItem:
        normalized = normalize_title(title)
        if normalized in show_cache:
            return show_cache[normalized]
        query = MediaItem.objects.filter(
            library=library,
            item_type=MediaItem.TYPE_SHOW,
            normalized_title=normalized,
        )
        if release_year:
            query = query.filter(release_year=release_year)
        item = query.first()
        if not item:
            item = MediaItem.objects.create(
                library=library,
                item_type=MediaItem.TYPE_SHOW,
                title=title,
                sort_title=title,
                normalized_title=normalized,
                release_year=release_year,
            )
        show_cache[normalized] = item
        return item

    def get_or_create_episode(
        parent: MediaItem,
        title: str,
        season_number: int | None,
        episode_number: int | None,
    ) -> MediaItem:
        cache_key = (parent.id, season_number, episode_number, title)
        if cache_key in episode_cache:
            return episode_cache[cache_key]
        normalized_title = normalize_title(title)
        query = MediaItem.objects.filter(
            library=library,
            parent=parent,
            item_type=MediaItem.TYPE_EPISODE,
        )
        if season_number is not None:
            query = query.filter(season_number=season_number)
        if episode_number is not None:
            query = query.filter(episode_number=episode_number)
        if season_number is None or episode_number is None:
            query = query.filter(
                Q(normalized_title=normalized_title) | Q(title=title)
            )
        item = query.first()
        if not item:
            item = MediaItem.objects.create(
                library=library,
                parent=parent,
                item_type=MediaItem.TYPE_EPISODE,
                title=title,
                sort_title=title,
                normalized_title=normalized_title,
                season_number=season_number,
                episode_number=episode_number,
            )
        episode_cache[cache_key] = item
        return item

    processed_since_update = 0

    for location in library.locations.all():
        base_path = os.path.expanduser(location.path)
        if not os.path.isdir(base_path):
            result.errors.append({"path": base_path, "error": "Path not found"})
            continue

        try:
            file_iter = _iter_location_files(base_path, location.include_subdirectories)
            for full_path in file_iter:
                if cancel_check and cancel_check():
                    raise ScanCancelled()

                file_name = os.path.basename(full_path)
                if not _is_media_file(file_name):
                    continue
                if full_path in seen_paths:
                    continue
                seen_paths.add(full_path)

                result.total_files += 1
                result.processed_files += 1
                processed_since_update += 1

                try:
                    stat = os.stat(full_path)
                except OSError as exc:
                    result.errors.append({"path": full_path, "error": str(exc)})
                    continue
                modified_at = timezone.datetime.fromtimestamp(
                    stat.st_mtime, tz=dt_timezone.utc
                )
                size_bytes = stat.st_size
                relative_path = _resolve_relative_path(full_path, base_path)

                existing = existing_files.get(full_path)
                changed = full or not existing
                if existing and not changed:
                    if existing["size_bytes"] != size_bytes:
                        changed = True
                    elif existing["modified_at"] != modified_at:
                        changed = True

                if changed:
                    classification = classify_media_entry(
                        library, relative_path=relative_path, file_name=file_name
                    )
                    item_type = classification.detected_type
                    item_title = classification.title
                    media_item: MediaItem

                    if library.library_type == Library.LIBRARY_TYPE_SHOWS:
                        show_item = get_or_create_show(
                            item_title, classification.year
                        )
                        result.metadata_item_ids.add(show_item.id)
                        episode_title = classification.episode_title or os.path.splitext(file_name)[0]
                        media_item = get_or_create_episode(
                            show_item,
                            episode_title,
                            classification.season,
                            classification.episode,
                        )
                        if media_item.normalized_title != normalize_title(media_item.title):
                            media_item.normalized_title = normalize_title(media_item.title)
                            media_item.save(update_fields=["normalized_title", "updated_at"])
                    else:
                        if item_type == MediaItem.TYPE_OTHER:
                            result.unmatched_files += 1
                            result.unmatched_paths.append(full_path)
                        media_item = get_or_create_movie(
                            item_title, classification.year
                        )

                    result.metadata_item_ids.add(media_item.id)

                    if existing:
                        file_updates.append(
                            MediaFile(
                                id=existing["id"],
                                library_id=library.id,
                                media_item_id=media_item.id,
                                path=full_path,
                                relative_path=relative_path,
                                file_name=file_name,
                                size_bytes=size_bytes,
                                modified_at=modified_at,
                                duration_ms=existing.get("duration_ms"),
                                is_primary=existing.get("is_primary", False),
                                last_seen_at=scan_start,
                            )
                        )
                        result.updated_files += 1
                    else:
                        is_primary = False
                        if media_item.id not in primary_item_ids:
                            is_primary = True
                            primary_item_ids.add(media_item.id)
                        file_creates.append(
                            MediaFile(
                                library=library,
                                media_item=media_item,
                                path=full_path,
                                relative_path=relative_path,
                                file_name=file_name,
                                size_bytes=size_bytes,
                                modified_at=modified_at,
                                is_primary=is_primary,
                                last_seen_at=scan_start,
                            )
                        )
                        result.new_files += 1
                else:
                    file_updates.append(
                        MediaFile(
                            id=existing["id"],
                            library_id=library.id,
                            media_item_id=existing["media_item_id"],
                            path=full_path,
                            relative_path=existing.get("relative_path") or relative_path,
                            file_name=existing.get("file_name") or file_name,
                            size_bytes=size_bytes,
                            modified_at=modified_at,
                            duration_ms=existing.get("duration_ms"),
                            is_primary=existing.get("is_primary", False),
                            last_seen_at=scan_start,
                        )
                    )

                if processed_since_update >= PROGRESS_UPDATE_INTERVAL:
                    flush_updates()
                    if progress_callback:
                        progress_callback(result.processed_files, result.total_files)
                    processed_since_update = 0

                if len(file_updates) >= BULK_UPDATE_SIZE or len(file_creates) >= BULK_CREATE_SIZE:
                    flush_updates()

        except PermissionError as exc:
            result.errors.append({"path": base_path, "error": str(exc)})
        except OSError as exc:
            result.errors.append({"path": base_path, "error": str(exc)})

    flush_updates()

    stale_files = MediaFile.objects.filter(
        library=library, last_seen_at__lt=scan_start
    )
    result.removed_files = stale_files.count()
    stale_item_ids = set(stale_files.values_list("media_item_id", flat=True))
    stale_files.delete()

    if stale_item_ids:
        MediaItem.objects.filter(
            library=library,
            id__in=stale_item_ids,
        ).filter(
            files__isnull=True,
            children__isnull=True,
        ).delete()

    if progress_callback:
        progress_callback(result.processed_files, result.total_files)

    return result
