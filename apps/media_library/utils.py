import fnmatch
import json
import logging
import os
import subprocess
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone as dt_timezone
from importlib import resources as importlib_resources
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from guessit import guessit

try:
    from guessit.rules.properties import website as guessit_website
except Exception:  # noqa: BLE001
    guessit_website = None
else:
    # Python 3.13's importlib.resources.files no longer returns a context manager;
    # wrap it so guessit can still use `with files(...)`.
    def _compatible_files(package: str):  # type: ignore[override]
        return importlib_resources.as_file(importlib_resources.files(package))

    if guessit_website:
        guessit_website.files = _compatible_files
from pymediainfo import MediaInfo

from apps.media_library.models import (
    ClassificationResult,
    Library,
    LibraryLocation,
    LibraryScan,
    MediaFile,
    MediaItem,
    MEDIA_EXTENSIONS,
    normalize_title,
)
from apps.media_library.transcode import purge_transcoded_artifact

logger = logging.getLogger(__name__)


def _json_safe(value):
    """Ensure value can be serialized via json.dumps."""
    if isinstance(value, dict):
        return {key: _json_safe(val) for key, val in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _first_numeric(value):
    """Extract the first integer-like value from guessit responses."""
    if value is None:
        return None
    if isinstance(value, (list, tuple, set)):
        for item in value:
            normalized = _first_numeric(item)
            if normalized is not None:
                return normalized
        return None
    if isinstance(value, dict):
        # Some guessit versions wrap values (e.g. {"season": 1})
        for key in ("season", "episode", "number"):
            if key in value:
                normalized = _first_numeric(value[key])
                if normalized is not None:
                    return normalized
        return None
    if isinstance(value, (int, float)):
        return int(value)
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


@dataclass
class DiscoveredFile:
    file_id: int
    requires_probe: bool


class LibraryScanner:
    """Performs discovery of files for a library scan."""

    def __init__(
        self,
        library: Library,
        scan: LibraryScan,
        force_full: bool = False,
        rescan_item_id: Optional[int] = None,
    ) -> None:
        self.library = library
        self.scan = scan
        self.force_full = force_full or rescan_item_id is not None
        self.rescan_item_id = rescan_item_id
        self.now = timezone.now()
        self.log_messages: list[str] = []
        self.stats: Dict[str, int] = defaultdict(int)
        self._seen_paths: set[str] = set()
        self.target_item = None
        options = library.metadata_options or {}
        ignore_patterns_default = getattr(settings, "MEDIA_LIBRARY_IGNORE_PATTERNS", [])
        library_ignore = options.get("ignore_patterns") if isinstance(options, dict) else None
        combined_patterns = []
        if isinstance(ignore_patterns_default, (list, tuple, set)):
            combined_patterns.extend(
                [pat for pat in ignore_patterns_default if isinstance(pat, str) and pat]
            )
        if isinstance(library_ignore, (list, tuple, set)):
            combined_patterns.extend([pat for pat in library_ignore if isinstance(pat, str) and pat])
        self.ignore_patterns = [pattern.strip() for pattern in combined_patterns if pattern.strip()]
        self.skip_hidden = bool(options.get("skip_hidden", True))
        if rescan_item_id:
            self.target_item = (
                MediaItem.objects.filter(pk=rescan_item_id, library=library).first()
            )
            if not self.target_item:
                self._log(
                    f"Target media item {rescan_item_id} not found in library {library.id}."
                )

    def discover_files(self) -> List[DiscoveredFile]:
        """Walk library locations, ensure MediaFile records exist, and return the IDs."""
        return list(self.discover_files_iter())

    def discover_files_iter(self) -> Iterator[DiscoveredFile]:
        """Yield discovered files one-at-a-time for incremental processing."""
        discovered_count = 0
        try:
            if not self.library.locations.exists():
                self._log(f"Library '{self.library.name}' has no configured locations.")
                return

            for location in self.library.locations.all():
                path = Path(location.path).expanduser()
                if not path.exists():
                    self._log(
                        f"Path '{path}' does not exist for library '{self.library.name}'."
                    )
                    continue
                if not path.is_dir():
                    self._log(f"Path '{path}' is not a directory; skipping.")
                    continue

                iterator = path.rglob("*") if location.include_subdirectories else path.iterdir()
                for file_path in iterator:
                    if not file_path.is_file():
                        continue
                    if file_path.suffix.lower() not in MEDIA_EXTENSIONS:
                        continue
                    if self._should_ignore_path(file_path):
                        continue

                    absolute_path = str(file_path)
                    self._seen_paths.add(absolute_path)
                    try:
                        record_data = self._ensure_file_record(location, file_path)
                    except Exception as exc:  # noqa: BLE001
                        logger.exception("Failed to process file %s", absolute_path)
                        self._log(f"Failed to process '{absolute_path}': {exc}")
                        continue

                    if not record_data:
                        continue

                    file_record, requires_probe = record_data
                    if (
                        self.target_item
                        and file_record.media_item_id not in {None, self.target_item.id}
                    ):
                        continue

                    discovered_count += 1
                    self.stats["total"] = discovered_count
                    yield DiscoveredFile(file_id=file_record.id, requires_probe=requires_probe)
        finally:
            self.stats["total"] = discovered_count
            self.scan.total_files = discovered_count
            self.scan.new_files = self.stats.get("new", 0)
            self.scan.updated_files = self.stats.get("updated", 0)
            self.scan.save(
                update_fields=[
                    "total_files",
                    "new_files",
                    "updated_files",
                    "updated_at",
                ]
            )

    def mark_missing_files(self) -> int:
        missing_qs = (
            MediaFile.objects.filter(library=self.library)
            .exclude(absolute_path__in=self._seen_paths)
            .exclude(absolute_path="")
        )
        missing_files = list(
            missing_qs.only("id", "transcoded_path", "requires_transcode", "transcode_status")
        )
        count = missing_qs.update(missing_since=self.now)
        if count:
            self.stats["removed"] += count
            self._log(f"Marked {count} files as missing.")
            self.scan.removed_files = self.stats["removed"]
            self.scan.save(update_fields=["removed_files", "updated_at"])
            for file_record in missing_files:
                try:
                    purge_transcoded_artifact(file_record)
                except Exception:  # noqa: BLE001
                    logger.debug("Unable to purge transcode for missing file %s", file_record.id)
        return count

    def finalize(self, matched: int, unmatched: int, summary: str | None = None) -> None:
        self.stats["matched"] += matched
        self.stats["unmatched"] += unmatched
        self.scan.matched_items = self.stats["matched"]
        self.scan.unmatched_files = self.stats["unmatched"]
        if summary:
            self.scan.summary = summary
        self.scan.log = "\n".join(self.log_messages)
        self.scan.save(
            update_fields=[
                "matched_items",
                "unmatched_files",
                "summary",
                "log",
                "updated_at",
            ]
        )

    def _ensure_file_record(
        self, location: LibraryLocation, file_path: Path
    ) -> Optional[tuple[MediaFile, bool]]:
        relative_path = os.path.relpath(file_path, location.path)
        stat = file_path.stat()
        last_modified = datetime.fromtimestamp(stat.st_mtime, tz=dt_timezone.utc)

        with transaction.atomic():
            file_record, created = MediaFile.objects.select_for_update().get_or_create(
                library=self.library,
                absolute_path=str(file_path),
                defaults={
                    "location": location,
                    "relative_path": relative_path,
                    "file_name": file_path.name,
                    "size_bytes": stat.st_size,
                    "last_modified_at": last_modified,
                    "last_seen_at": self.now,
                },
            )

            requires_probe = False
            checksum_reset = False
            if created:
                self.stats["new"] += 1
                requires_probe = True
                checksum_reset = True
            else:
                should_update = (
                    self.force_full
                    or file_record.last_modified_at is None
                    or last_modified > file_record.last_modified_at
                )
                if should_update:
                    file_record.size_bytes = stat.st_size
                    file_record.last_modified_at = last_modified
                    self.stats["updated"] += 1
                    requires_probe = True
                    checksum_reset = True

            file_record.last_seen_at = self.now
            file_record.location = location
            file_record.relative_path = relative_path
            file_record.file_name = file_path.name
            file_record.missing_since = None
            update_fields = [
                "location",
                "relative_path",
                "file_name",
                "size_bytes",
                "last_modified_at",
                "last_seen_at",
                "missing_since",
                "updated_at",
            ]

            if checksum_reset and file_record.checksum:
                file_record.checksum = ""
                update_fields.append("checksum")

            file_record.save(update_fields=update_fields)

        # Always probe on forced scans or if checksum missing
        if self.force_full or not file_record.checksum:
            requires_probe = True
        return file_record, requires_probe

    def _log(self, message: str) -> None:
        logger.debug("[Library %s] %s", self.library.id, message)
        self.log_messages.append(message)

    def _should_ignore_path(self, file_path: Path) -> bool:
        """
        Skip files that match ignore patterns or hidden folders when configured.
        """
        if self.skip_hidden:
            parts = file_path.parts
            if any(segment.startswith(".") for segment in parts):
                return True

        if not self.ignore_patterns:
            return False

        candidate = str(file_path)
        for pattern in self.ignore_patterns:
            if fnmatch.fnmatch(candidate, pattern):
                return True
        return False


def resolve_media_item(
    library: Library,
    classification: ClassificationResult,
    target_item: Optional[MediaItem] = None,
) -> Optional[MediaItem]:
    def _first_text(value):
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        if isinstance(value, (list, tuple, set)):
            for entry in value:
                text = _first_text(entry)
                if text:
                    return text
            return ""
        if isinstance(value, dict):
            for key in ("title", "name", "value"):
                if key in value:
                    text = _first_text(value[key])
                    if text:
                        return text
            return ""
        return str(value)

    if target_item:
        return target_item

    title_raw = classification.title
    title = _first_text(title_raw) or "Unknown"
    normalized = normalize_title(title)

    if classification.detected_type == MediaItem.TYPE_MOVIE:
        queryset = MediaItem.objects.filter(
            library=library,
            item_type=MediaItem.TYPE_MOVIE,
            normalized_title=normalized,
        )
        match = None
        if classification.year:
            match = queryset.filter(release_year=classification.year).first()
        if not match:
            match = queryset.first()
        if match:
            if classification.year and match.release_year != classification.year:
                match.release_year = classification.year
                match.save(update_fields=["release_year", "updated_at"])
            return match
        metadata_payload = _json_safe(classification.data or {})
        return MediaItem.objects.create(
            library=library,
            item_type=MediaItem.TYPE_MOVIE,
            status=MediaItem.STATUS_PENDING,
            title=title,
            sort_title=title,
            normalized_title=normalized,
            release_year=classification.year,
            metadata=metadata_payload,
        )

    if classification.detected_type == MediaItem.TYPE_SHOW:
        metadata_payload = _json_safe(classification.data or {})
        match = MediaItem.objects.filter(
            library=library,
            item_type=MediaItem.TYPE_SHOW,
            normalized_title=normalized,
        ).first()
        if match:
            return match
        return MediaItem.objects.create(
            library=library,
            item_type=MediaItem.TYPE_SHOW,
            status=MediaItem.STATUS_PENDING,
            title=title,
            sort_title=title,
            normalized_title=normalized,
            metadata=metadata_payload,
        )

    if classification.detected_type == MediaItem.TYPE_EPISODE:
        series_title_raw = ""
        if classification.data:
            series_title_raw = classification.data.get("series_title") or classification.data.get("series")
        series_title = _first_text(series_title_raw) or title
        if not series_title:
            series_title = title
        series_normalized = normalize_title(series_title)

        series_item = (
            MediaItem.objects.filter(
                library=library,
                item_type=MediaItem.TYPE_SHOW,
                normalized_title=series_normalized,
            ).first()
        )
        if not series_item:
            series_metadata = _json_safe(classification.data or {})
            series_item = MediaItem.objects.create(
                library=library,
                item_type=MediaItem.TYPE_SHOW,
                status=MediaItem.STATUS_PENDING,
                title=series_title,
                sort_title=series_title,
                normalized_title=series_normalized,
                metadata=series_metadata,
            )

        episode_item = (
            MediaItem.objects.filter(
                library=library,
                item_type=MediaItem.TYPE_EPISODE,
                parent=series_item,
                season_number=classification.season,
                episode_number=classification.episode,
            ).first()
        )
        if episode_item:
            if episode_item.is_missing:
                episode_item.is_missing = False
                episode_item.save(update_fields=["is_missing", "updated_at"])
            if classification.episode_title and not episode_item.title:
                episode_item.title = classification.episode_title
                episode_item.save(update_fields=["title", "updated_at"])
            return episode_item

        title_to_use = (
            classification.episode_title
            or (
                f"S{classification.season:02d}E{classification.episode:02d}"
                if classification.season and classification.episode
                else title
            )
        )

        metadata_payload = _json_safe(classification.data or {})
        return MediaItem.objects.create(
            library=library,
            parent=series_item,
            item_type=MediaItem.TYPE_EPISODE,
            status=MediaItem.STATUS_PENDING,
            title=title_to_use,
            sort_title=title_to_use,
            normalized_title=normalize_title(title_to_use),
            release_year=classification.year,
            season_number=classification.season,
            episode_number=classification.episode,
            metadata=metadata_payload,
        )

    metadata_payload = _json_safe(classification.data or {})
    match = MediaItem.objects.filter(
        library=library,
        item_type=MediaItem.TYPE_OTHER,
        normalized_title=normalized,
    ).first()
    if match:
        return match
    return MediaItem.objects.create(
        library=library,
        item_type=MediaItem.TYPE_OTHER,
        status=MediaItem.STATUS_PENDING,
        title=title,
        sort_title=title,
        normalized_title=normalized,
        metadata=metadata_payload,
    )


def probe_media_file(path: str) -> dict:
    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration,bit_rate,format_name",
        "-show_streams",
        "-of",
        "json",
        path,
    ]

    try:
        process = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
            text=True,
        )
    except FileNotFoundError:
        logger.debug("ffprobe not available; falling back to pymediainfo for %s", path)
        return _probe_with_mediainfo(path)
    except subprocess.CalledProcessError as exc:  # noqa: BLE001
        logger.warning("ffprobe failed for %s: %s", path, exc.stderr)
        fallback = _probe_with_mediainfo(path)
        if fallback:
            return fallback
        return {}

    try:
        return json.loads(process.stdout)
    except json.JSONDecodeError:
        logger.warning("Failed to parse ffprobe output for %s", path)
        return {}


def _probe_with_mediainfo(path: str) -> dict:
    try:
        media_info = MediaInfo.parse(path)
    except Exception:  # noqa: BLE001
        return {}

    format_info: dict = {}
    streams: list[dict] = []
    for track in media_info.tracks:
        if track.track_type == "General":
            format_info = {
                "duration": track.duration / 1000 if track.duration else None,
                "bit_rate": track.overall_bit_rate,
                "format_name": track.format,
            }
        elif track.track_type == "Video":
            streams.append(
                {
                    "codec_type": "video",
                    "codec_name": track.format,
                    "width": track.width,
                    "height": track.height,
                    "avg_frame_rate": track.frame_rate,
                }
            )
        elif track.track_type == "Audio":
            streams.append(
                {
                    "codec_type": "audio",
                    "codec_name": track.format,
                    "channels": track.channel_s,
                }
            )
        elif track.track_type == "Text":
            streams.append(
                {
                    "codec_type": "subtitle",
                    "codec_name": track.format,
                    "tags": {"language": track.language},
                }
            )

    return {"format": format_info, "streams": streams}


def apply_probe_metadata(file_record: MediaFile, probe_data: dict) -> None:
    if not probe_data:
        return
    format_info = probe_data.get("format", {})
    streams = probe_data.get("streams", [])

    duration_ms: int | None = None

    duration = format_info.get("duration")
    if duration not in (None, "", 0):
        try:
            duration_ms = int(float(duration) * 1000)
            file_record.duration_ms = duration_ms
        except (TypeError, ValueError):  # noqa: PERF203
            logger.debug("Unable to parse duration '%s' for %s", duration, file_record)

    if duration_ms is None:
        raw_duration_ms = format_info.get("duration_ms")
        if raw_duration_ms not in (None, "", 0):
            try:
                duration_ms = int(float(raw_duration_ms))
                file_record.duration_ms = duration_ms
            except (TypeError, ValueError):  # noqa: PERF203
                logger.debug(
                    "Unable to parse duration_ms '%s' for %s", raw_duration_ms, file_record
                )

    bit_rate = format_info.get("bit_rate")
    try:
        if bit_rate:
            file_record.bit_rate = int(bit_rate)
    except (TypeError, ValueError):  # noqa: PERF203
        pass

    if format_info.get("format_name"):
        file_record.container = format_info["format_name"].split(",")[0]

    video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)
    subtitle_streams = [s for s in streams if s.get("codec_type") == "subtitle"]

    if video_stream:
        file_record.video_codec = video_stream.get("codec_name", "")
        file_record.width = video_stream.get("width")
        file_record.height = video_stream.get("height")
        file_record.frame_rate = _safe_frame_rate(video_stream)

    if audio_stream:
        file_record.audio_codec = audio_stream.get("codec_name", "")
        channels = audio_stream.get("channels")
        if channels is not None:
            try:
                file_record.audio_channels = float(channels)
            except (TypeError, ValueError):  # noqa: PERF203
                file_record.audio_channels = None

    file_record.has_subtitles = bool(subtitle_streams)
    if subtitle_streams:
        file_record.subtitle_languages = [
            stream.get("tags", {}).get("language") for stream in subtitle_streams
        ]

    file_record.extra_streams = {
        "format": format_info,
        "streams": streams,
    }
    needs_transcode = not file_record.is_browser_playable()
    file_record.requires_transcode = needs_transcode

    update_fields = [
        "duration_ms",
        "bit_rate",
        "container",
        "video_codec",
        "width",
        "height",
        "frame_rate",
        "audio_codec",
        "audio_channels",
        "has_subtitles",
        "subtitle_languages",
        "extra_streams",
        "requires_transcode",
        "updated_at",
    ]

    if not needs_transcode:
        file_record.transcode_status = MediaFile.TRANSCODE_STATUS_NOT_REQUIRED
        file_record.transcoded_path = ""
        file_record.transcoded_mime_type = ""
        file_record.transcode_error = ""
        file_record.transcoded_at = None
        update_fields.extend(
            [
                "transcode_status",
                "transcoded_path",
                "transcoded_mime_type",
                "transcode_error",
                "transcoded_at",
            ]
        )
    else:
        if file_record.transcode_status in (
            MediaFile.TRANSCODE_STATUS_NOT_REQUIRED,
            "",
        ):
            file_record.transcode_status = MediaFile.TRANSCODE_STATUS_PENDING
            update_fields.append("transcode_status")

        if (
            file_record.transcode_status == MediaFile.TRANSCODE_STATUS_READY
            and file_record.transcoded_path
            and not os.path.exists(file_record.transcoded_path)
        ):
            file_record.transcode_status = MediaFile.TRANSCODE_STATUS_PENDING
            file_record.transcoded_path = ""
            file_record.transcoded_mime_type = ""
            file_record.transcoded_at = None
            update_fields.extend(
                [
                    "transcode_status",
                    "transcoded_path",
                    "transcoded_mime_type",
                    "transcoded_at",
                ]
            )

    file_record.save(update_fields=update_fields)

    if file_record.media_item_id:
        candidate_duration_ms = duration_ms or file_record.duration_ms
        try:
            media_item = file_record.media_item
        except MediaFile.media_item.RelatedObjectDoesNotExist:  # type: ignore[attr-defined]
            media_item = None

        if not candidate_duration_ms:
            extra = file_record.extra_streams or {}
            format_info = extra.get("format") or {}
            fallback_candidates: list[tuple[object, float]] = []
            if "duration_ms" in format_info:
                fallback_candidates.append((format_info.get("duration_ms"), 1.0))
            if "duration" in format_info:
                fallback_candidates.append((format_info.get("duration"), 1000.0))

            for value, multiplier in fallback_candidates:
                if value in (None, "", 0):
                    continue
                try:
                    numeric = float(value)
                except (TypeError, ValueError):  # noqa: PERF203
                    continue
                if numeric <= 0:
                    continue
                candidate_duration_ms = int(numeric * multiplier)
                break

        if candidate_duration_ms and media_item and (
            not media_item.runtime_ms or media_item.runtime_ms < candidate_duration_ms
        ):
            media_item.runtime_ms = int(candidate_duration_ms)
            media_item.save(update_fields=["runtime_ms", "updated_at"])


def _safe_frame_rate(stream: dict) -> Optional[float]:
    value = stream.get("avg_frame_rate") or stream.get("r_frame_rate")
    if not value or value == "0/0":
        return None
    try:
        if "/" in value:
            numerator, denominator = value.split("/", 1)
            numerator = float(numerator)
            denominator = float(denominator)
            if denominator == 0:
                return None
            return round(numerator / denominator, 3)
        return float(value)
    except (ValueError, ZeroDivisionError):  # noqa: PERF203
        return None
