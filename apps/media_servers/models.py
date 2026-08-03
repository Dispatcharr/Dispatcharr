from __future__ import annotations

import uuid
from urllib.parse import urlsplit

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django_celery_beat.models import PeriodicTask

from .path_security import (
    resolve_export_path,
    resolve_import_path,
    validate_no_import_export_overlap,
)


ACTIVE_RUN_STATUSES = ("pending", "queued", "running")


class MediaLibrarySource(models.Model):
    class ProviderTypes(models.TextChoices):
        PLEX = "plex", "Plex"
        EMBY = "emby", "Emby"
        JELLYFIN = "jellyfin", "Jellyfin"
        LOCAL = "local", "Local"

    class SyncStatus(models.TextChoices):
        IDLE = "idle", "Idle"
        RUNNING = "running", "Running"
        SUCCESS = "success", "Success"
        ERROR = "error", "Error"

    name = models.CharField(max_length=255, unique=True)
    provider_type = models.CharField(max_length=32, choices=ProviderTypes.choices)
    base_url = models.URLField(max_length=1000, blank=True, default="")
    api_token = models.CharField(max_length=1024, blank=True, default="")
    username = models.CharField(max_length=255, blank=True, default="")
    password = models.CharField(max_length=255, blank=True, default="")
    verify_ssl = models.BooleanField(default=True)
    enabled = models.BooleanField(default=True)
    add_to_vod = models.BooleanField(default=True)
    sync_interval = models.PositiveIntegerField(
        default=0,
        help_text="Automatic synchronization interval in hours; zero disables it.",
    )
    include_libraries = models.JSONField(default=list, blank=True)
    library_content_types = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "Optional per-library media type overrides keyed by provider library ID."
        ),
    )
    provider_config = models.JSONField(default=dict, blank=True)
    sync_task = models.ForeignKey(
        PeriodicTask,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="media_library_sources",
    )
    vod_account = models.ForeignKey(
        "m3u.M3UAccount",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="media_library_sources",
    )
    last_synced_at = models.DateTimeField(null=True, blank=True)
    last_sync_status = models.CharField(
        max_length=16,
        choices=SyncStatus.choices,
        default=SyncStatus.IDLE,
    )
    last_sync_message = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        indexes = [
            models.Index(
                fields=["provider_type", "enabled"],
                name="media_serve_provide_82a7a8_idx",
            )
        ]

    def __str__(self):
        return f"{self.name} ({self.get_provider_type_display()})"

    def clean(self):
        if self.base_url:
            parsed = urlsplit(self.base_url)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                raise ValidationError(
                    {"base_url": "The provider URL must use HTTP or HTTPS."}
                )
            if parsed.username or parsed.password:
                raise ValidationError(
                    {"base_url": "Credentials may not be embedded in provider URLs."}
                )
            if parsed.query or parsed.fragment:
                raise ValidationError(
                    {
                        "base_url": (
                            "Provider base URLs may not contain query parameters "
                            "or fragments."
                        )
                    }
                )

    def save(self, *args, **kwargs):
        if self.base_url:
            self.base_url = self.base_url.rstrip("/")
        self.full_clean()
        super().save(*args, **kwargs)

    @property
    def selected_library_ids(self) -> set[str]:
        values = self.include_libraries if isinstance(self.include_libraries, list) else []
        return {str(value).strip() for value in values if str(value).strip()}

    @property
    def configured_library_content_types(self) -> dict[str, str]:
        values = (
            self.library_content_types
            if isinstance(self.library_content_types, dict)
            else {}
        )
        valid_types = set(MediaLibraryLocation.ContentTypes.values)
        return {
            str(library_id).strip(): str(content_type).strip().lower()
            for library_id, content_type in values.items()
            if str(library_id).strip()
            and str(content_type).strip().lower() in valid_types
        }

    def content_type_for_library(self, library_id, detected_type="mixed") -> str:
        detected = str(detected_type or "mixed").strip().lower()
        if detected not in set(MediaLibraryLocation.ContentTypes.values):
            detected = MediaLibraryLocation.ContentTypes.MIXED
        return self.configured_library_content_types.get(str(library_id), detected)


class MediaLibraryLocation(models.Model):
    class ContentTypes(models.TextChoices):
        MOVIE = "movie", "Movies"
        SERIES = "series", "Series"
        MIXED = "mixed", "Movies and series"

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    source = models.ForeignKey(
        MediaLibrarySource,
        on_delete=models.CASCADE,
        related_name="locations",
    )
    name = models.CharField(max_length=255, blank=True, default="")
    path = models.TextField()
    content_type = models.CharField(
        max_length=16,
        choices=ContentTypes.choices,
        default=ContentTypes.MIXED,
    )
    include_subdirectories = models.BooleanField(default=True)
    enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(fields=["source", "path"], name="unique_media_location_path")
        ]

    def clean(self):
        resolved = resolve_import_path(
            self.path,
            must_exist=False,
            require_directory=True,
        )
        export_paths = MediaLibraryExportTarget.objects.values_list(
            "output_root",
            flat=True,
        )
        validate_no_import_export_overlap(resolved, (), export_paths)
        self.path = str(resolved)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class MediaLibraryImportRun(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        QUEUED = "queued", "Queued"
        RUNNING = "running", "Running"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"

    integration = models.ForeignKey(
        MediaLibrarySource,
        on_delete=models.CASCADE,
        related_name="import_runs",
    )
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.QUEUED)
    summary = models.CharField(max_length=255, blank=True, default="")
    stages = models.JSONField(default=dict, blank=True)
    scope_results = models.JSONField(default=dict, blank=True)
    processed_items = models.PositiveIntegerField(default=0)
    total_items = models.PositiveIntegerField(default=0)
    created_items = models.PositiveIntegerField(default=0)
    updated_items = models.PositiveIntegerField(default=0)
    removed_items = models.PositiveIntegerField(default=0)
    skipped_items = models.PositiveIntegerField(default=0)
    ambiguous_items = models.PositiveIntegerField(default=0)
    error_count = models.PositiveIntegerField(default=0)
    message = models.TextField(blank=True, default="")
    extra = models.JSONField(default=dict, blank=True)
    task_id = models.CharField(max_length=255, blank=True, default="")
    cancellation_requested_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["integration", "created_at"],
                name="media_serve_integra_250357_idx",
            ),
            models.Index(
                fields=["integration", "status"],
                name="media_serve_integra_7ecae3_idx",
            ),
            models.Index(
                fields=["status", "created_at"],
                name="media_serve_status_d6f390_idx",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["integration"],
                condition=Q(status__in=ACTIVE_RUN_STATUSES),
                name="one_active_media_import_per_source",
            )
        ]

    @property
    def source(self):
        return self.integration

    @property
    def source_id(self):
        return self.integration_id


class MediaLibraryExportTarget(models.Model):
    class TargetTypes(models.TextChoices):
        JELLYFIN = "jellyfin", "Jellyfin"
        EMBY = "emby", "Emby"

    class ExportStatus(models.TextChoices):
        IDLE = "idle", "Idle"
        RUNNING = "running", "Running"
        SUCCESS = "success", "Success"
        ERROR = "error", "Error"

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    name = models.CharField(max_length=255, unique=True)
    target_type = models.CharField(
        max_length=16,
        choices=TargetTypes.choices,
        default=TargetTypes.JELLYFIN,
    )
    enabled = models.BooleanField(default=True)
    output_root = models.TextField(unique=True)
    playback_base_url = models.URLField(max_length=1000)
    playback_cidrs = models.TextField(
        help_text="Comma-separated CIDRs allowed to use this target's STRM URLs."
    )
    playback_stream_limit = models.PositiveIntegerField(
        default=0,
        help_text="Maximum concurrent streams for this target; zero is unlimited.",
    )
    include_nfo = models.BooleanField(default=True)
    auto_export_on_vod_change = models.BooleanField(default=True)
    last_exported_at = models.DateTimeField(null=True, blank=True)
    last_export_status = models.CharField(
        max_length=16,
        choices=ExportStatus.choices,
        default=ExportStatus.IDLE,
    )
    last_export_message = models.TextField(blank=True, default="")
    last_export_summary = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        indexes = [
            models.Index(
                fields=["enabled", "auto_export_on_vod_change"],
                name="media_serve_enabled_28e257_idx",
            )
        ]

    def clean(self):
        resolved_output = resolve_export_path(
            self.output_root,
            must_exist=False,
            require_directory=True,
        )
        local_paths = MediaLibraryLocation.objects.filter(
            enabled=True
        ).values_list("path", flat=True)
        other_outputs = MediaLibraryExportTarget.objects.exclude(
            pk=self.pk
        ).values_list("output_root", flat=True)
        validate_no_import_export_overlap(
            resolved_output,
            local_paths,
            other_outputs,
        )
        self.output_root = str(resolved_output)
        self.playback_base_url = self.playback_base_url.rstrip("/")
        parsed = urlsplit(self.playback_base_url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValidationError(
                {
                    "playback_base_url": (
                        "Use an HTTP(S) base URL without credentials, query "
                        "parameters, or fragments."
                    )
                }
            )
        if not self.playback_cidrs.strip():
            raise ValidationError({"playback_cidrs": "At least one explicit CIDR is required."})
        import ipaddress

        invalid = []
        for raw in self.playback_cidrs.split(","):
            try:
                ipaddress.ip_network(raw.strip(), strict=False)
            except ValueError:
                invalid.append(raw.strip())
        if invalid:
            raise ValidationError({"playback_cidrs": f"Invalid CIDRs: {', '.join(invalid)}"})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class MediaLibraryExportRun(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        QUEUED = "queued", "Queued"
        RUNNING = "running", "Running"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"

    target = models.ForeignKey(
        MediaLibraryExportTarget,
        on_delete=models.CASCADE,
        related_name="export_runs",
    )
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.QUEUED)
    reason = models.CharField(max_length=255, blank=True, default="")
    task_id = models.CharField(max_length=255, blank=True, default="")
    summary = models.JSONField(default=dict, blank=True)
    message = models.TextField(blank=True, default="")
    cancellation_requested_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["target", "created_at"],
                name="media_serve_target__ee4da9_idx",
            ),
            models.Index(
                fields=["target", "status"],
                name="media_serve_target__9f3e27_idx",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["target"],
                condition=Q(status__in=ACTIVE_RUN_STATUSES),
                name="one_active_media_export_per_target",
            )
        ]


# Compatibility names used by the carefully adapted reference provider/import
# implementation. Public API and new code use the MediaLibrary names above.
MediaServerIntegration = MediaLibrarySource
MediaServerSyncRun = MediaLibraryImportRun
