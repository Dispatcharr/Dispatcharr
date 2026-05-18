from django.db import models
from django.utils import timezone
from django_celery_beat.models import PeriodicTask
from django.conf import settings
import os

class EPGSource(models.Model):
    SOURCE_TYPE_CHOICES = [
        ('xmltv', 'XMLTV URL'),
        ('schedules_direct', 'Schedules Direct API'),
        ('dummy', 'Custom Dummy EPG'),
    ]

    STATUS_IDLE = 'idle'
    STATUS_FETCHING = 'fetching'
    STATUS_PARSING = 'parsing'
    STATUS_ERROR = 'error'
    STATUS_SUCCESS = 'success'
    STATUS_DISABLED = 'disabled'

    STATUS_CHOICES = [
        (STATUS_IDLE, 'Idle'),
        (STATUS_FETCHING, 'Fetching'),
        (STATUS_PARSING, 'Parsing'),
        (STATUS_ERROR, 'Error'),
        (STATUS_SUCCESS, 'Success'),
        (STATUS_DISABLED, 'Disabled'),
    ]

    name = models.CharField(max_length=255, unique=True)
    source_type = models.CharField(max_length=20, choices=SOURCE_TYPE_CHOICES)
    url = models.URLField(max_length=1000, blank=True, null=True)  # For XMLTV
    username = models.CharField(max_length=255, blank=True, null=True,
                               help_text='Username for credential-based EPG sources (e.g. Schedules Direct)')
    password = models.CharField(max_length=255, blank=True, null=True,
                               help_text='Password for credential-based EPG sources (e.g. Schedules Direct)')
    is_active = models.BooleanField(default=True)
    file_path = models.CharField(max_length=1024, blank=True, null=True)
    extracted_file_path = models.CharField(max_length=1024, blank=True, null=True,
                                         help_text="Path to extracted XML file after decompression")
    refresh_interval = models.IntegerField(default=0)
    refresh_task = models.ForeignKey(
        PeriodicTask, on_delete=models.SET_NULL, null=True, blank=True
    )
    custom_properties = models.JSONField(
        default=dict,
        blank=True,
        null=True,
        help_text="Custom properties for source-specific configuration"
    )
    priority = models.PositiveIntegerField(
        default=0,
        help_text="Priority for EPG matching (higher numbers = higher priority). Used when multiple EPG sources have matching entries for a channel."
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_IDLE
    )
    last_message = models.TextField(
        null=True,
        blank=True,
        help_text="Last status message, including success results or error information"
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        help_text="Time when this source was created"
    )
    updated_at = models.DateTimeField(
        null=True, blank=True,
        help_text="Time when this source was last successfully refreshed"
    )

    def __str__(self):
        return self.name

    def get_cache_file(self):
        import mimetypes

        file_ext = ".tmp"

        if self.file_path and os.path.exists(self.file_path):
            _, existing_ext = os.path.splitext(self.file_path)
            if existing_ext:
                file_ext = existing_ext
            else:
                mime_type, _ = mimetypes.guess_type(self.file_path)
                if mime_type:
                    if mime_type == 'application/gzip' or mime_type == 'application/x-gzip':
                        file_ext = '.gz'
                    elif mime_type == 'application/zip':
                        file_ext = '.zip'
                    elif mime_type == 'application/xml' or mime_type == 'text/xml':
                        file_ext = '.xml'
                else:
                    try:
                        with open(self.file_path, 'rb') as f:
                            header = f.read(4)
                            if header[:2] == b'\x1f\x8b':
                                file_ext = '.gz'
                            elif header[:2] == b'PK':
                                file_ext = '.zip'
                            elif header[:5] == b'<?xml' or header[:5] == b'<tv>':
                                file_ext = '.xml'
                    except Exception:
                        pass

        filename = f"{self.id}{file_ext}"
        cache_dir = os.path.join(settings.MEDIA_ROOT, "cached_epg")
        os.makedirs(cache_dir, exist_ok=True)
        cache = os.path.join(cache_dir, filename)
        return cache

    def save(self, *args, **kwargs):
        if 'update_fields' in kwargs and 'updated_at' not in kwargs['update_fields']:
            kwargs.setdefault('update_fields', [])
            if 'updated_at' in kwargs['update_fields']:
                kwargs['update_fields'].remove('updated_at')
        super().save(*args, **kwargs)

class EPGData(models.Model):
    tvg_id = models.CharField(max_length=255, null=True, blank=True, db_index=True)
    name = models.CharField(max_length=512)
    icon_url = models.URLField(max_length=500, null=True, blank=True)
    epg_source = models.ForeignKey(
        EPGSource,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="epgs",
    )

    class Meta:
        unique_together = ('tvg_id', 'epg_source')

    def __str__(self):
        return f"EPG Data for {self.name}"

class ProgramData(models.Model):
    epg = models.ForeignKey(EPGData, on_delete=models.CASCADE, related_name="programs")
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    title = models.CharField(max_length=255)
    sub_title = models.TextField(blank=True, null=True)
    description = models.TextField(blank=True, null=True)
    tvg_id = models.CharField(max_length=255, null=True, blank=True)
    custom_properties = models.JSONField(default=dict, blank=True, null=True)

    def __str__(self):
        return f"{self.title} ({self.start_time} - {self.end_time})"

class SDScheduleMD5(models.Model):
    """
    Caches per-station per-date MD5 hashes from Schedules Direct.
    Used to detect schedule changes and avoid unnecessary re-downloads,
    minimizing API calls against SD's rate-limited endpoints.
    """
    epg_source = models.ForeignKey(
        EPGSource,
        on_delete=models.CASCADE,
        related_name="sd_schedule_md5s",
    )
    station_id = models.CharField(
        max_length=20,
        help_text="Schedules Direct stationID"
    )
    date = models.DateField(
        help_text="Schedule date (UTC)"
    )
    md5 = models.CharField(
        max_length=22,
        help_text="MD5 hash of the schedule for this station/date from Schedules Direct"
    )
    last_modified = models.DateTimeField(
        help_text="Last modified timestamp from Schedules Direct"
    )

    class Meta:
        unique_together = ('epg_source', 'station_id', 'date')
        indexes = [
            models.Index(fields=['epg_source', 'station_id']),
        ]

    def __str__(self):
        return f"SDScheduleMD5: {self.station_id} / {self.date} ({self.epg_source.name})"


class SDProgramMD5(models.Model):
    """
    Caches per-program MD5 hashes from Schedules Direct.
    Keyed by epg_source + program_id (SD's programID e.g. EP123456789).
    Used for program-level delta detection to avoid re-downloading unchanged
    program metadata, minimizing API calls against SD's rate-limited endpoints.
    """
    epg_source = models.ForeignKey(
        EPGSource,
        on_delete=models.CASCADE,
        related_name="sd_program_md5s",
    )
    program_id = models.CharField(
        max_length=64,
        help_text="Schedules Direct programID (e.g. EP123456789)"
    )
    md5 = models.CharField(
        max_length=22,
        help_text="MD5 hash of the program metadata from Schedules Direct"
    )

    class Meta:
        unique_together = ('epg_source', 'program_id')
        indexes = [
            models.Index(fields=['epg_source', 'program_id']),
        ]

    def __str__(self):
        return f"SDProgramMD5: {self.program_id} ({self.epg_source.name})"
