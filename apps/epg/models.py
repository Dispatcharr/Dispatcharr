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
                    elif mime_type == 'application/x-xz':
                        file_ext = '.xz'
                    elif mime_type == 'application/xml' or mime_type == 'text/xml':
                        file_ext = '.xml'
                else:
                    try:
                        with open(self.file_path, 'rb') as f:
                            header = f.read(6)
                            if header.startswith(b'\x1f\x8b'):
                                file_ext = '.gz'
                            elif header.startswith(b'PK'):
                                file_ext = '.zip'
                            elif header.startswith(b'\xfd7zXZ\x00'):
                                file_ext = '.xz'
                            elif header.startswith(b'<?xml') or header.startswith(b'<tv>'):
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

    @property
    def programme_index(self):
        """Byte-offset index for this source, read on demand from the separate
        EPGSourceIndex table so the multi-MB blob is never pulled into EPGSource
        queries or select_related JOINs. Returns the stored dict or None."""
        return (
            EPGSourceIndex.objects.filter(source_id=self.pk)
            .values_list('data', flat=True)
            .first()
        )

    def _get_linked_m3u_proxy_override(self, custom_props: dict) -> str | None:
        """
        Return a normalized proxy override from an associated M3UAccount if one
        exists (matched via custom_properties['m3u_account_id'], matching name,
        or matching Xtream Codes server_url origin for /xmltv.php URLs).
        """
        from urllib.parse import urlparse
        from apps.m3u.models import M3UAccount
        from apps.m3u.utils import normalize_proxy_url

        try:
            account = None
            m3u_account_id = custom_props.get("m3u_account_id")
            if m3u_account_id:
                account = (
                    M3UAccount.objects.filter(id=int(m3u_account_id))
                    .only("custom_properties")
                    .first()
                )
            if account is None and self.name:
                account = (
                    M3UAccount.objects.filter(name=self.name)
                    .only("custom_properties")
                    .first()
                )
            if (
                account is None
                and self.source_type == "xmltv"
                and self.url
                and "/xmltv.php" in self.url
            ):
                parsed = urlparse(self.url)
                if parsed.scheme and parsed.netloc:
                    origin = f"{parsed.scheme}://{parsed.netloc}"
                    account = (
                        M3UAccount.objects.filter(
                            server_url__startswith=origin
                        )
                        .only("custom_properties")
                        .first()
                    )
            if account and isinstance(account.custom_properties, dict):
                acct_proxy = normalize_proxy_url(
                    account.custom_properties.get("proxy")
                )
                if acct_proxy:
                    return acct_proxy
        except Exception:
            pass
        return None

    def get_effective_proxy(self) -> str | None:
        """
        Resolve the effective proxy URL for this EPG source:
        1. Explicit per-source override in ``custom_properties['proxy']``
        2. Proxy override on an associated M3UAccount
        3. Global ``default_proxy`` in ``CoreSettings`` (stream_settings)
        4. ``None`` (no proxy)
        """
        from apps.m3u.utils import normalize_proxy_url
        from core.models import CoreSettings

        custom_props = (
            self.custom_properties
            if isinstance(self.custom_properties, dict)
            else {}
        )
        source_proxy = normalize_proxy_url(custom_props.get("proxy"))
        if source_proxy:
            return source_proxy

        linked_m3u_proxy = self._get_linked_m3u_proxy_override(custom_props)
        if linked_m3u_proxy:
            return linked_m3u_proxy

        global_proxy = CoreSettings.get_default_proxy()
        return global_proxy or None

    def get_proxies(self) -> dict[str, str] | None:
        """Return a requests-compatible ``proxies`` mapping for this EPG source, or ``None``."""
        from apps.m3u.utils import build_requests_proxies

        return build_requests_proxies(self.get_effective_proxy())


class EPGSourceIndex(models.Model):
    """Byte-offset programme index for an EPGSource, stored in its own table.

    Kept out of EPGSource so the multi-MB JSON blob is only loaded when read
    explicitly, never when querying or joining EPGSource rows.
    """
    source = models.OneToOneField(
        EPGSource,
        on_delete=models.CASCADE,
        related_name='index_record',
        primary_key=True,
    )
    data = models.JSONField(null=True, blank=True, default=None)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Programme index for source {self.source_id}"


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
    program_id = models.CharField(max_length=64, null=True, blank=True, help_text='Schedules Direct programID (e.g. EP123456789). Null for XMLTV sources.')
    custom_properties = models.JSONField(default=dict, blank=True, null=True)

    class Meta:
        indexes = [
            models.Index(fields=['epg', 'id'], name='epg_prog_epg_id_idx'),
            models.Index(
                fields=['epg', 'start_time', 'end_time'],
                name='epg_prog_epg_start_end_idx',
            ),
            models.Index(fields=['epg', 'end_time'], name='epg_prog_epg_end_idx'),
        ]

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

    def __str__(self):
        return f"SDProgramMD5: {self.program_id} ({self.epg_source.name})"
