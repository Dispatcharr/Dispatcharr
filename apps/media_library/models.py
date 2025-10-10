import hashlib
import os
import uuid
from dataclasses import dataclass

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone
from django.utils.text import slugify


MEDIA_EXTENSIONS = {
    ".mkv",
    ".mp4",
    ".mov",
    ".avi",
    ".m4v",
    ".ts",
    ".flv",
    ".wmv",
    ".mpg",
    ".mpeg",
}


class Library(models.Model):
    """Represents a logical grouping of media content (movies, shows, etc.)."""

    LIBRARY_TYPE_MOVIES = "movies"
    LIBRARY_TYPE_SHOWS = "shows"
    LIBRARY_TYPE_MIXED = "mixed"
    LIBRARY_TYPE_OTHER = "other"

    LIBRARY_TYPE_CHOICES = [
        (LIBRARY_TYPE_MOVIES, "Movies"),
        (LIBRARY_TYPE_SHOWS, "TV Shows"),
        (LIBRARY_TYPE_MIXED, "Mixed"),
        (LIBRARY_TYPE_OTHER, "Other"),
    ]

    name = models.CharField(max_length=255, unique=True)
    slug = models.SlugField(max_length=255, unique=True, editable=False)
    description = models.TextField(blank=True)
    library_type = models.CharField(
        max_length=16,
        choices=LIBRARY_TYPE_CHOICES,
        default=LIBRARY_TYPE_MIXED,
    )
    auto_scan_enabled = models.BooleanField(default=True)
    scan_interval_minutes = models.PositiveIntegerField(
        default=24 * 60,
        help_text="How often to auto-scan library paths when auto-scan is enabled.",
    )
    metadata_language = models.CharField(
        max_length=8,
        default="en",
        help_text="Primary language for metadata lookups (ISO-639-1).",
    )
    metadata_country = models.CharField(
        max_length=8,
        default="US",
        help_text="Primary country/region for metadata lookups (ISO-3166-1 alpha-2).",
    )
    use_as_vod_source = models.BooleanField(
        default=False,
        help_text="When enabled, media matched in this library syncs into the VOD catalog.",
    )
    metadata_options = models.JSONField(
        blank=True,
        null=True,
        help_text="Structured configuration for metadata providers and overrides.",
    )
    last_scan_at = models.DateTimeField(blank=True, null=True)
    last_successful_scan_at = models.DateTimeField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            base_slug = slugify(self.name)
            slug_candidate = base_slug
            counter = 1
            while Library.objects.filter(slug=slug_candidate).exclude(pk=self.pk).exists():
                counter += 1
                slug_candidate = f"{base_slug}-{counter}"
            self.slug = slug_candidate
        super().save(*args, **kwargs)


class LibraryLocation(models.Model):
    """Physical path backing a library."""

    library = models.ForeignKey(
        Library,
        on_delete=models.CASCADE,
        related_name="locations",
    )
    path = models.CharField(max_length=4096)
    include_subdirectories = models.BooleanField(default=True)
    is_primary = models.BooleanField(
        default=False,
        help_text="Primary location is used for generating relative paths when multiple roots share structure.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("library", "path")]
        ordering = ["library__name", "path"]

    def __str__(self):
        return f"{self.library.name}: {self.path}"


class LibraryScan(models.Model):
    """Tracks an individual scan execution."""

    STATUS_PENDING = "pending"
    STATUS_RUNNING = "running"
    STATUS_COMPLETED = "completed"
    STATUS_FAILED = "failed"
    STATUS_CANCELLED = "cancelled"

    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_RUNNING, "Running"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_FAILED, "Failed"),
        (STATUS_CANCELLED, "Cancelled"),
    ]

    STAGE_STATUS_PENDING = "pending"
    STAGE_STATUS_RUNNING = "running"
    STAGE_STATUS_COMPLETED = "completed"
    STAGE_STATUS_SKIPPED = "skipped"

    STAGE_STATUS_CHOICES = [
        (STAGE_STATUS_PENDING, "Pending"),
        (STAGE_STATUS_RUNNING, "Running"),
        (STAGE_STATUS_COMPLETED, "Completed"),
        (STAGE_STATUS_SKIPPED, "Skipped"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    library = models.ForeignKey(
        Library,
        on_delete=models.CASCADE,
        related_name="scans",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="library_scans",
    )
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_PENDING)
    started_at = models.DateTimeField(blank=True, null=True)
    finished_at = models.DateTimeField(blank=True, null=True)
    total_files = models.PositiveIntegerField(default=0)
    processed_files = models.PositiveIntegerField(default=0)
    new_files = models.PositiveIntegerField(default=0)
    updated_files = models.PositiveIntegerField(default=0)
    removed_files = models.PositiveIntegerField(default=0)
    matched_items = models.PositiveIntegerField(default=0)
    unmatched_files = models.PositiveIntegerField(default=0)
    task_id = models.CharField(max_length=255, blank=True, null=True)
    summary = models.TextField(blank=True)
    log = models.TextField(blank=True)
    extra = models.JSONField(blank=True, null=True)

    discovery_status = models.CharField(
        max_length=16,
        choices=STAGE_STATUS_CHOICES,
        default=STAGE_STATUS_PENDING,
    )
    discovery_total = models.PositiveIntegerField(default=0)
    discovery_processed = models.PositiveIntegerField(default=0)

    metadata_status = models.CharField(
        max_length=16,
        choices=STAGE_STATUS_CHOICES,
        default=STAGE_STATUS_PENDING,
    )
    metadata_total = models.PositiveIntegerField(default=0)
    metadata_processed = models.PositiveIntegerField(default=0)

    artwork_status = models.CharField(
        max_length=16,
        choices=STAGE_STATUS_CHOICES,
        default=STAGE_STATUS_PENDING,
    )
    artwork_total = models.PositiveIntegerField(default=0)
    artwork_processed = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def mark_running(self, task_id: str | None = None):
        self.status = self.STATUS_RUNNING
        self.started_at = timezone.now()
        self.processed_files = 0
        if task_id:
            self.task_id = task_id
        self.save(
            update_fields=[
                "status",
                "started_at",
                "task_id",
                "processed_files",
                "updated_at",
            ]
        )

    def mark_completed(self, summary: str = ""):
        self.status = self.STATUS_COMPLETED
        self.finished_at = timezone.now()
        self.summary = summary
        self.processed_files = self.total_files
        self.save(
            update_fields=[
                "status",
                "finished_at",
                "summary",
                "processed_files",
                "updated_at",
            ]
        )

    def mark_failed(self, summary: str = ""):
        self.status = self.STATUS_FAILED
        self.finished_at = timezone.now()
        self.summary = summary
        self.save(update_fields=["status", "finished_at", "summary", "updated_at"])

    def record_progress(
        self,
        *,
        processed: int | None = None,
        matched: int | None = None,
        unmatched: int | None = None,
        total: int | None = None,
        summary: str | None = None,
    ) -> None:
        updates: dict[str, object] = {}

        if processed is not None:
            self.processed_files = processed
            updates["processed_files"] = processed
        if matched is not None:
            self.matched_items = matched
            updates["matched_items"] = matched
        if unmatched is not None:
            self.unmatched_files = unmatched
            updates["unmatched_files"] = unmatched
        if total is not None:
            total_value = max(0, int(total))
            self.total_files = total_value
            updates["total_files"] = total_value
        if summary is not None:
            self.summary = summary
            updates["summary"] = summary

        if not updates:
            return

        now = timezone.now()
        updates["updated_at"] = now
        self.__class__.objects.filter(pk=self.pk).update(**updates)
        self.updated_at = now

    _stage_field_map = {
        "discovery": ("discovery_status", "discovery_total", "discovery_processed"),
        "metadata": ("metadata_status", "metadata_total", "metadata_processed"),
        "artwork": ("artwork_status", "artwork_total", "artwork_processed"),
    }

    def stage_snapshot(self, *, normalize: bool = False) -> dict[str, dict[str, int | str]]:
        """
        Return the current stage progress for the scan.

        When `normalize` is True, metadata and artwork counts are scaled so that
        their totals align with the overall `total_files` count. This keeps the
        progress bars consistent in the UI without affecting the stored values
        that drive the underlying workflow.
        """
        snapshot: dict[str, dict[str, int | str]] = {}
        total_files = max(0, int(self.total_files or 0))

        for stage, (status_field, total_field, processed_field) in self._stage_field_map.items():
            status = getattr(self, status_field)
            total_value = max(0, int(getattr(self, total_field) or 0))
            processed_value = max(0, int(getattr(self, processed_field) or 0))

            if (
                normalize
                and stage != "discovery"
                and status != self.STAGE_STATUS_SKIPPED
                and total_files > 0
            ):
                normalized_total = total_files
                if total_value > 0:
                    if processed_value >= total_value:
                        normalized_processed = normalized_total
                    else:
                        ratio = processed_value / total_value
                        normalized_processed = int(ratio * normalized_total)
                        if processed_value > 0 and normalized_processed == 0:
                            normalized_processed = 1
                        normalized_processed = min(normalized_total, normalized_processed)
                else:
                    normalized_processed = 0

                total_value = normalized_total
                processed_value = normalized_processed

            snapshot[stage] = {
                "status": status,
                "processed": processed_value,
                "total": total_value,
            }

        return snapshot

    def record_stage_progress(
        self,
        stage: str,
        *,
        status: str | None = None,
        total: int | None = None,
        processed: int | None = None,
    ) -> None:
        if stage not in self._stage_field_map:
            raise ValueError(f"Unknown stage '{stage}'")

        status_field, total_field, processed_field = self._stage_field_map[stage]
        updates: dict[str, object] = {}

        if status is not None:
            if status not in dict(self.STAGE_STATUS_CHOICES):
                raise ValueError(f"Invalid stage status '{status}' for stage '{stage}'")
            setattr(self, status_field, status)
            updates[status_field] = status
        if total is not None:
            total_value = max(0, int(total))
            setattr(self, total_field, total_value)
            updates[total_field] = total_value
        if processed is not None:
            processed_value = max(0, int(processed))
            setattr(self, processed_field, processed_value)
            updates[processed_field] = processed_value

        if not updates:
            return

        now = timezone.now()
        updates["updated_at"] = now
        self.__class__.objects.filter(pk=self.pk).update(**updates)
        self.updated_at = now



class MediaItem(models.Model):
    """Represents a logical piece of media (movie, series, season, episode)."""

    TYPE_COLLECTION = "collection"
    TYPE_SHOW = "show"
    TYPE_SEASON = "season"
    TYPE_EPISODE = "episode"
    TYPE_MOVIE = "movie"
    TYPE_OTHER = "other"

    ITEM_TYPE_CHOICES = [
        (TYPE_COLLECTION, "Collection"),
        (TYPE_SHOW, "Series"),
        (TYPE_SEASON, "Season"),
        (TYPE_EPISODE, "Episode"),
        (TYPE_MOVIE, "Movie"),
        (TYPE_OTHER, "Other"),
    ]

    STATUS_PENDING = "pending"
    STATUS_MATCHED = "matched"
    STATUS_FAILED = "failed"

    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_MATCHED, "Matched"),
        (STATUS_FAILED, "Failed"),
    ]

    library = models.ForeignKey(
        Library,
        on_delete=models.CASCADE,
        related_name="items",
    )
    parent = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        related_name="children",
        null=True,
        blank=True,
    )
    item_type = models.CharField(max_length=16, choices=ITEM_TYPE_CHOICES, default=TYPE_OTHER)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_PENDING)

    title = models.CharField(max_length=512)
    sort_title = models.CharField(max_length=512, blank=True)
    normalized_title = models.CharField(max_length=512, blank=True, db_index=True)
    release_year = models.IntegerField(blank=True, null=True)
    season_number = models.IntegerField(blank=True, null=True)
    episode_number = models.IntegerField(blank=True, null=True)
    runtime_ms = models.BigIntegerField(blank=True, null=True)
    synopsis = models.TextField(blank=True)
    tagline = models.CharField(max_length=512, blank=True)
    rating = models.CharField(max_length=32, blank=True)
    genres = models.JSONField(blank=True, null=True)
    studios = models.JSONField(blank=True, null=True)
    cast = models.JSONField(blank=True, null=True)
    crew = models.JSONField(blank=True, null=True)
    tags = models.JSONField(blank=True, null=True)
    poster_url = models.URLField(blank=True)
    backdrop_url = models.URLField(blank=True)

    tmdb_id = models.CharField(max_length=64, blank=True, null=True, db_index=True)
    imdb_id = models.CharField(max_length=64, blank=True, null=True, db_index=True)
    tvdb_id = models.CharField(max_length=64, blank=True, null=True, db_index=True)

    vod_movie = models.ForeignKey(
        "vod.Movie",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="library_items",
    )
    vod_series = models.ForeignKey(
        "vod.Series",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="library_items",
    )
    vod_episode = models.ForeignKey(
        "vod.Episode",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="library_items",
    )

    metadata = models.JSONField(blank=True, null=True)
    metadata_last_synced_at = models.DateTimeField(blank=True, null=True)
    metadata_source = models.CharField(max_length=64, blank=True)

    first_imported_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["library", "item_type", "normalized_title"]),
            models.Index(fields=["library", "item_type", "release_year"]),
        ]
        ordering = ["library__name", "item_type", "sort_title", "title"]

    def __str__(self):
        return self.title

    def ensure_sort_title(self):
        if not self.sort_title:
            self.sort_title = self.title
        if not self.normalized_title:
            self.normalized_title = normalize_title(self.title)

    def save(self, *args, **kwargs):
        self.ensure_sort_title()
        super().save(*args, **kwargs)

    @property
    def is_movie(self) -> bool:
        return self.item_type == self.TYPE_MOVIE

    @property
    def is_episode(self) -> bool:
        return self.item_type == self.TYPE_EPISODE


class ArtworkAsset(models.Model):
    """Represents an artwork asset linked to a media item."""

    TYPE_POSTER = "poster"
    TYPE_BACKDROP = "backdrop"
    TYPE_BANNER = "banner"
    TYPE_THUMB = "thumb"

    ASSET_TYPE_CHOICES = [
        (TYPE_POSTER, "Poster"),
        (TYPE_BACKDROP, "Backdrop"),
        (TYPE_BANNER, "Banner"),
        (TYPE_THUMB, "Thumbnail"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    media_item = models.ForeignKey(
        MediaItem,
        on_delete=models.CASCADE,
        related_name="artwork",
    )
    asset_type = models.CharField(max_length=16, choices=ASSET_TYPE_CHOICES)
    external_url = models.URLField(blank=True)
    local_path = models.CharField(max_length=4096, blank=True)
    width = models.IntegerField(blank=True, null=True)
    height = models.IntegerField(blank=True, null=True)
    language = models.CharField(max_length=16, blank=True)
    source = models.CharField(max_length=64, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("media_item", "asset_type", "language", "source")]
        ordering = ["media_item", "asset_type"]

    def __str__(self):
        return f"{self.media_item.title} - {self.asset_type}"


class MediaFile(models.Model):
    """Physical file on disk that is associated with a media item."""

    TRANSCODE_STATUS_NOT_REQUIRED = "not_required"
    TRANSCODE_STATUS_PENDING = "pending"
    TRANSCODE_STATUS_PROCESSING = "processing"
    TRANSCODE_STATUS_READY = "ready"
    TRANSCODE_STATUS_FAILED = "failed"

    TRANSCODE_STATUS_CHOICES = [
        (TRANSCODE_STATUS_NOT_REQUIRED, "Not Required"),
        (TRANSCODE_STATUS_PENDING, "Pending"),
        (TRANSCODE_STATUS_PROCESSING, "Processing"),
        (TRANSCODE_STATUS_READY, "Ready"),
        (TRANSCODE_STATUS_FAILED, "Failed"),
    ]

    BROWSER_SAFE_CONTAINERS = {"mp4", "m4v"}
    BROWSER_SAFE_VIDEO_CODECS = {"h264", "avc1"}
    BROWSER_SAFE_AUDIO_CODECS = {"aac", "mp3", "mp4a", "libmp3lame"}

    library = models.ForeignKey(
        Library,
        on_delete=models.CASCADE,
        related_name="files",
    )
    media_item = models.ForeignKey(
        MediaItem,
        on_delete=models.SET_NULL,
        related_name="files",
        blank=True,
        null=True,
    )
    location = models.ForeignKey(
        LibraryLocation,
        on_delete=models.SET_NULL,
        related_name="files",
        blank=True,
        null=True,
    )
    absolute_path = models.CharField(max_length=4096)
    relative_path = models.CharField(max_length=4096, blank=True)
    file_name = models.CharField(max_length=1024)
    size_bytes = models.BigIntegerField(default=0)
    duration_ms = models.BigIntegerField(blank=True, null=True)
    video_codec = models.CharField(max_length=128, blank=True)
    audio_codec = models.CharField(max_length=128, blank=True)
    audio_channels = models.FloatField(blank=True, null=True)
    width = models.IntegerField(blank=True, null=True)
    height = models.IntegerField(blank=True, null=True)
    frame_rate = models.FloatField(blank=True, null=True)
    bit_rate = models.BigIntegerField(blank=True, null=True)
    container = models.CharField(max_length=64, blank=True)
    has_subtitles = models.BooleanField(default=False)
    subtitle_languages = models.JSONField(blank=True, null=True)
    extra_streams = models.JSONField(blank=True, null=True)
    checksum = models.CharField(max_length=64, blank=True, db_index=True)
    fingerprint = models.CharField(max_length=64, blank=True, db_index=True)
    last_modified_at = models.DateTimeField(blank=True, null=True)
    requires_transcode = models.BooleanField(default=False)
    transcode_status = models.CharField(
        max_length=20,
        choices=TRANSCODE_STATUS_CHOICES,
        default=TRANSCODE_STATUS_NOT_REQUIRED,
    )
    transcoded_path = models.CharField(max_length=4096, blank=True)
    transcoded_mime_type = models.CharField(max_length=128, blank=True)
    transcode_error = models.TextField(blank=True)
    transcoded_at = models.DateTimeField(blank=True, null=True)
    last_seen_at = models.DateTimeField(blank=True, null=True)
    missing_since = models.DateTimeField(blank=True, null=True)
    notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("library", "absolute_path")]
        indexes = [
            models.Index(fields=["library", "relative_path"]),
            models.Index(fields=["media_item", "last_seen_at"]),
        ]
        ordering = ["library", "relative_path"]

    def __str__(self):
        return self.absolute_path

    @property
    def extension(self):
        return os.path.splitext(self.file_name)[1].lower()

    def _normalized_container(self) -> str:
        container = (self.container or "").split(",")[0].strip().lower()
        if container:
            return container
        ext = self.extension
        return ext[1:] if ext.startswith(".") else ext

    @staticmethod
    def _normalized_codec(codec_value: str) -> str:
        return (codec_value or "").split(".")[0].strip().lower()

    def is_browser_playable(self) -> bool:
        container = self._normalized_container()
        if container not in self.BROWSER_SAFE_CONTAINERS:
            return False

        video_codec = self._normalized_codec(self.video_codec)
        if video_codec and video_codec not in self.BROWSER_SAFE_VIDEO_CODECS:
            return False

        audio_codec = self._normalized_codec(self.audio_codec)
        if audio_codec and audio_codec not in self.BROWSER_SAFE_AUDIO_CODECS:
            return False

        return True

    @property
    def effective_duration_ms(self) -> int | None:
        """
        Return the best-known duration (ms). Falls back to probe metadata and
        associated media item runtime when the direct field is missing.
        """
        if self.duration_ms:
            try:
                return int(self.duration_ms)
            except (TypeError, ValueError):
                pass

        extra = self.extra_streams or {}
        format_info = extra.get("format") or {}

        candidates: list[tuple[object, float]] = []
        if "duration_ms" in format_info:
            candidates.append((format_info.get("duration_ms"), 1.0))
        if "duration" in format_info:
            # ffprobe reports seconds in this field.
            candidates.append((format_info.get("duration"), 1000.0))

        for value, multiplier in candidates:
            if value in (None, "", 0):
                continue
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                continue
            if numeric <= 0:
                continue
            return int(numeric * multiplier)

        if self.media_item_id:
            runtime_ms = self.media_item.runtime_ms
            if runtime_ms:
                try:
                    return int(runtime_ms)
                except (TypeError, ValueError):
                    return None

        return None

    def calculate_checksum(self, chunk_size: int = 1024 * 1024) -> str:
        """Calculate a SHA1 checksum for the file."""
        sha1 = hashlib.sha1()
        try:
            with open(self.absolute_path, "rb") as handle:
                while True:
                    data = handle.read(chunk_size)
                    if not data:
                        break
                    sha1.update(data)
        except FileNotFoundError:
            return ""
        return sha1.hexdigest()


class WatchProgress(models.Model):
    """Tracks where a user left off while watching a media item."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="media_progress",
    )
    media_item = models.ForeignKey(
        MediaItem,
        on_delete=models.CASCADE,
        related_name="watch_progress",
    )
    position_ms = models.BigIntegerField(default=0, validators=[MinValueValidator(0)])
    duration_ms = models.BigIntegerField(default=0, validators=[MinValueValidator(0)])
    completed = models.BooleanField(default=False)
    last_watched_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("user", "media_item")]
        ordering = ["-last_watched_at"]

    def __str__(self):
        return f"{self.user} - {self.media_item}"

    def update_progress(self, position_ms: int, duration_ms: int | None = None, completion_threshold: float = 0.96):
        if duration_ms is not None:
            self.duration_ms = max(self.duration_ms, duration_ms)
        self.position_ms = max(position_ms, 0)
        if self.duration_ms > 0:
            ratio = self.position_ms / self.duration_ms
            if ratio >= completion_threshold:
                self.completed = True
                self.position_ms = self.duration_ms
        self.save(update_fields=["position_ms", "duration_ms", "completed", "last_watched_at"])


def normalize_title(text: str | None) -> str:
    if not text:
        return ""
    return "".join(ch for ch in text.lower() if ch.isalnum() or ch.isspace()).strip()


@dataclass
class ClassificationResult:
    """Represents the outcome of parsing a media file name."""

    detected_type: str
    title: str
    year: int | None = None
    season: int | None = None
    episode: int | None = None
    episode_title: str | None = None
    data: dict | None = None
