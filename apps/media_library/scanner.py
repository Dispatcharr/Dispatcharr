import os
from datetime import timezone as dt_timezone
from dataclasses import dataclass, field
from typing import Callable, Iterable, Optional

from django.db.models import Q
from django.utils import timezone

from apps.media_library.classification import classify_media_entry
from apps.media_library.metadata import parse_nfo_episode_entries
from apps.media_library.file_utils import sync_media_file_links
from apps.media_library.models import Library, MediaFile, MediaFileLink, MediaItem
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


def _needs_metadata_refresh(item_state: dict | None) -> bool:
    if not item_state:
        return True
    if not item_state.get("metadata_last_synced_at"):
        return True
    if item_state.get("item_type") in {MediaItem.TYPE_MOVIE, MediaItem.TYPE_SHOW}:
        poster = (item_state.get("poster_url") or "").strip()
        backdrop = (item_state.get("backdrop_url") or "").strip()
        if not poster or not backdrop:
            return True
    return False


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


def _find_episode_nfo_path(file_path: str) -> str | None:
    directory = os.path.dirname(file_path)
    base_name = os.path.splitext(os.path.basename(file_path))[0]
    for candidate_name in (f"{base_name}.nfo", "episode.nfo"):
        candidate = os.path.join(directory, candidate_name)
        if os.path.isfile(candidate):
            return candidate
    return None


def scan_library_files(
    library: Library,
    *,
    full: bool = False,
    progress_callback: Optional[Callable[[int, int], None]] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
    metadata_callback: Optional[Callable[[int], None]] = None,
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
    item_metadata_state = {
        row["id"]: row
        for row in MediaItem.objects.filter(library=library).values(
            "id",
            "item_type",
            "metadata_last_synced_at",
            "poster_url",
            "backdrop_url",
        )
    }

    movie_cache: dict[tuple[str, int | None], MediaItem] = {}
    show_cache: dict[str, MediaItem] = {}
    episode_cache: dict[tuple[int, int | None, int | None, str], MediaItem] = {}

    file_updates: list[MediaFile] = []
    file_creates: list[MediaFile] = []
    seen_paths: set[str] = set()

    def enqueue_metadata_item(item_id: int | None):
        if not item_id:
            return
        is_new = item_id not in result.metadata_item_ids
        result.metadata_item_ids.add(item_id)
        if is_new and metadata_callback:
            metadata_callback(item_id)

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
                    episode_items: list[MediaItem] = []
                    primary_episode: MediaItem | None = None

                    if library.library_type == Library.LIBRARY_TYPE_SHOWS:
                        show_item = get_or_create_show(
                            item_title, classification.year
                        )
                        enqueue_metadata_item(show_item.id)
                        episode_title = classification.episode_title or os.path.splitext(file_name)[0]
                        season_number = classification.season
                        episode_numbers = []
                        if classification.episode is not None:
                            episode_numbers.append(classification.episode)
                        if classification.episode_list:
                            episode_numbers.extend(
                                [num for num in classification.episode_list if num is not None]
                            )
                        seen_numbers = set()
                        deduped_numbers = []
                        for num in episode_numbers:
                            if num in seen_numbers:
                                continue
                            seen_numbers.add(num)
                            deduped_numbers.append(num)
                        episode_numbers = deduped_numbers
                        episode_title_map: dict[int, str] = {}
                        if len(episode_numbers) <= 1:
                            nfo_path = _find_episode_nfo_path(full_path)
                            if nfo_path:
                                nfo_entries, _error = parse_nfo_episode_entries(nfo_path)
                                nfo_entries = [
                                    entry
                                    for entry in nfo_entries
                                    if entry.get("episode") is not None
                                ]
                                if len(nfo_entries) > 1:
                                    episode_numbers = []
                                    for entry in nfo_entries:
                                        episode_number = entry.get("episode")
                                        if episode_number in episode_numbers:
                                            continue
                                        episode_numbers.append(episode_number)
                                        if entry.get("title"):
                                            episode_title_map[episode_number] = entry["title"]
                                    if season_number is None:
                                        seasons = {
                                            entry.get("season")
                                            for entry in nfo_entries
                                            if entry.get("season") is not None
                                        }
                                        if len(seasons) == 1:
                                            season_number = seasons.pop()
                        if not episode_numbers:
                            episode_numbers = [classification.episode]

                        episode_items = [
                            get_or_create_episode(
                                show_item,
                                episode_title_map.get(episode_number, episode_title),
                                season_number,
                                episode_number,
                            )
                            for episode_number in episode_numbers
                        ]
                        primary_episode = episode_items[0]
                        media_item = primary_episode
                        for episode in episode_items:
                            enqueue_metadata_item(episode.id)
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

                    if library.library_type != Library.LIBRARY_TYPE_SHOWS:
                        enqueue_metadata_item(media_item.id)

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
                        if library.library_type == Library.LIBRARY_TYPE_SHOWS:
                            sync_media_file_links(
                                MediaFile(id=existing["id"]),
                                episode_items,
                                primary_item=primary_episode,
                                prune=len(episode_items) > 1,
                            )
                        result.updated_files += 1
                    else:
                        is_primary = False
                        if media_item.id not in primary_item_ids:
                            is_primary = True
                            primary_item_ids.add(media_item.id)
                        if library.library_type == Library.LIBRARY_TYPE_SHOWS and len(episode_items) > 1:
                            media_file = MediaFile.objects.create(
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
                            sync_media_file_links(
                                media_file,
                                episode_items,
                                primary_item=primary_episode,
                                prune=len(episode_items) > 1,
                            )
                            result.new_files += 1
                        else:
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
                    if not full and _needs_metadata_refresh(
                        item_metadata_state.get(existing["media_item_id"])
                    ):
                        enqueue_metadata_item(existing["media_item_id"])

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
    stale_file_ids = list(stale_files.values_list("id", flat=True))
    stale_item_ids = set(stale_files.values_list("media_item_id", flat=True))
    stale_linked_item_ids = set()
    if stale_file_ids:
        stale_linked_item_ids = set(
            MediaFileLink.objects.filter(media_file_id__in=stale_file_ids).values_list(
                "media_item_id", flat=True
            )
        )
    stale_files.delete()

    candidate_item_ids = stale_item_ids | stale_linked_item_ids
    if candidate_item_ids:
        parent_show_ids = set(
            MediaItem.objects.filter(
                library=library,
                id__in=candidate_item_ids,
                parent_id__isnull=False,
            ).values_list("parent_id", flat=True)
        )
        candidate_item_ids.update(parent_show_ids)

        MediaItem.objects.filter(
            library=library,
            id__in=candidate_item_ids,
        ).filter(
            files__isnull=True,
            file_links__isnull=True,
            children__isnull=True,
        ).delete()

    if progress_callback:
        progress_callback(result.processed_files, result.total_files)

    return result
