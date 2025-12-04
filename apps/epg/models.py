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
    api_key = models.CharField(max_length=255, blank=True, null=True)  # For Schedules Direct
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
        help_text="Custom properties for dummy EPG configuration (regex patterns, timezone, duration, etc.)"
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

        # Use a temporary extension for initial download
        # The actual extension will be determined after content inspection
        file_ext = ".tmp"

        # If file_path is already set and contains an extension, use that
        # This handles cases where we've already detected the proper type
        if self.file_path and os.path.exists(self.file_path):
            _, existing_ext = os.path.splitext(self.file_path)
            if existing_ext:
                file_ext = existing_ext
            else:
                # Try to detect the MIME type and map to extension
                mime_type, _ = mimetypes.guess_type(self.file_path)
                if mime_type:
                    if mime_type == 'application/gzip' or mime_type == 'application/x-gzip':
                        file_ext = '.gz'
                    elif mime_type == 'application/zip':
                        file_ext = '.zip'
                    elif mime_type == 'application/xml' or mime_type == 'text/xml':
                        file_ext = '.xml'
                # For files without mime type detection, try peeking at content
                else:
                    try:
                        with open(self.file_path, 'rb') as f:
                            header = f.read(4)
                            # Check for gzip magic number (1f 8b)
                            if header[:2] == b'\x1f\x8b':
                                file_ext = '.gz'
                            # Check for zip magic number (PK..)
                            elif header[:2] == b'PK':
                                file_ext = '.zip'
                            # Check for XML
                            elif header[:5] == b'<?xml' or header[:5] == b'<tv>':
                                file_ext = '.xml'
                    except Exception as e:
                        # If we can't read the file, just keep the default extension
                        pass

        filename = f"{self.id}{file_ext}"

        # Build full path in MEDIA_ROOT/cached_epg
        cache_dir = os.path.join(settings.MEDIA_ROOT, "cached_epg")

        # Create directory if it doesn't exist
        os.makedirs(cache_dir, exist_ok=True)

        cache = os.path.join(cache_dir, filename)

        return cache

    def save(self, *args, **kwargs):
        # Prevent auto_now behavior by handling updated_at manually
        if 'update_fields' in kwargs and 'updated_at' not in kwargs['update_fields']:
            # Don't modify updated_at for regular updates
            kwargs.setdefault('update_fields', [])
            if 'updated_at' in kwargs['update_fields']:
                kwargs['update_fields'].remove('updated_at')
        super().save(*args, **kwargs)

class EPGData(models.Model):
    # Removed the Channel foreign key. We now just store the original tvg_id
    # and a name (which might simply be the tvg_id if no real channel exists).
    tvg_id = models.CharField(max_length=255, null=True, blank=True, db_index=True)
    name = models.CharField(max_length=255)
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
    # Each programme is associated with an EPGData record.
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
