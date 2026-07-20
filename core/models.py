# core/models.py

import logging
import time
from shlex import split as shlex_split

from django.conf import settings
from django.db import models
from django.utils.text import slugify
from django.core.exceptions import ValidationError
from django_redis.exceptions import ConnectionInterrupted
from redis.exceptions import AuthenticationError as RedisAuthenticationError
from redis.exceptions import AuthorizationError as RedisAuthorizationError
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

logger = logging.getLogger(__name__)


class UserAgent(models.Model):
    name = models.CharField(
        max_length=512, unique=True, help_text="The User-Agent name."
    )
    user_agent = models.CharField(
        max_length=512,
        unique=True,
        help_text="The complete User-Agent string sent by the client.",
    )
    description = models.CharField(
        max_length=255,
        blank=True,
        help_text="An optional description of the client or device type.",
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Whether this user agent is currently allowed/recognized.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name


PROXY_PROFILE_NAME = "Proxy"
REDIRECT_PROFILE_NAME = "Redirect"


class StreamProfile(models.Model):
    name = models.CharField(max_length=255, help_text="Name of the stream profile")
    command = models.CharField(
        max_length=255,
        help_text="Command to execute (e.g., 'yt.sh', 'streamlink', or 'vlc')",
        blank=True,
    )
    parameters = models.TextField(
        help_text="Command-line parameters. Use {userAgent} and {streamUrl} as placeholders.",
        blank=True,
    )
    locked = models.BooleanField(
        default=False, help_text="Protected - can't be deleted or modified"
    )
    is_active = models.BooleanField(
        default=True, help_text="Whether this profile is active"
    )
    user_agent = models.ForeignKey(
        "UserAgent",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="Optional user agent to use. If not set, you can fall back to a default.",
    )

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if self.pk:  # Only check existing records
            orig = StreamProfile.objects.get(pk=self.pk)
            if orig.locked:
                allowed_fields = {"user_agent_id"}  # Only allow this field to change
                for field in self._meta.fields:
                    field_name = field.name

                    # Convert user_agent to user_agent_id for comparison
                    orig_value = getattr(orig, field_name)
                    new_value = getattr(self, field_name)

                    # Ensure that ForeignKey fields compare their ID values
                    if isinstance(orig_value, models.Model):
                        orig_value = orig_value.pk
                    if isinstance(new_value, models.Model):
                        new_value = new_value.pk

                    if field_name not in allowed_fields and orig_value != new_value:
                        raise ValidationError(
                            f"Cannot modify {field_name} on a protected profile."
                        )

        super().save(*args, **kwargs)

    @classmethod
    def update(cls, pk, **kwargs):
        instance = cls.objects.get(pk=pk)

        if instance.locked:
            allowed_fields = {"user_agent_id"}  # Only allow updating this field

            for field_name, new_value in kwargs.items():
                if field_name not in allowed_fields:
                    raise ValidationError(
                        f"Cannot modify {field_name} on a protected profile."
                    )

                # Ensure user_agent ForeignKey updates correctly
                if field_name == "user_agent" and isinstance(
                    new_value, cls._meta.get_field("user_agent").related_model
                ):
                    new_value = new_value.pk  # Convert object to ID if needed

                setattr(instance, field_name, new_value)

        instance.save()
        return instance

    def is_proxy(self):
        if self.locked and self.name == PROXY_PROFILE_NAME:
            return True
        return False

    def is_redirect(self):
        if self.locked and self.name == REDIRECT_PROFILE_NAME:
            return True
        return False

    def build_command(self, stream_url, user_agent):

        if self.is_proxy():
            return []

        replacements = {
            "{streamUrl}": stream_url,
            "{userAgent}": user_agent,
        }

        # Split the command and iterate through each part to apply replacements
        cmd = [self.command] + [
            self._replace_in_part(part, replacements)
            for part in shlex_split(self.parameters) # use shlex to handle quoted strings
        ]

        return cmd

    def _replace_in_part(self, part, replacements):
        # Iterate through the replacements and replace each part of the string
        for key, value in replacements.items():
            part = part.replace(key, value)
        return part


class OutputProfile(models.Model):
    """
    Defines a pre-delivery transcode step applied to a channel's TS stream.

    The command and parameters must accept raw MPEG-TS via pipe:0 (stdin) and
    write the transcoded output to pipe:1 (stdout). One transcode process runs
    per active (channel, OutputProfile) pair regardless of how many clients
    request it; all clients share the same Redis-backed output buffer.

    Example parameters for a 720p transcode:
        -i pipe:0 -c:v libx264 -b:v 2000k -vf scale=-2:720 -c:a copy -f mpegts pipe:1
    """

    name = models.CharField(max_length=255, unique=True, help_text="Display name for this output profile")
    command = models.CharField(
        max_length=255,
        help_text="Executable to run (e.g. 'ffmpeg')",
    )
    parameters = models.TextField(
        help_text="Command-line parameters. Must read from pipe:0 (stdin) and write to pipe:1 (stdout).",
    )
    locked = models.BooleanField(
        default=False, help_text="Protected - can't be deleted or modified"
    )
    is_active = models.BooleanField(
        default=True, help_text="Whether this profile is available for use"
    )

    def __str__(self):
        return self.name

    def build_command(self):
        """Return the full command as a list suitable for subprocess.Popen."""
        from shlex import split as shlex_split
        return [self.command] + shlex_split(self.parameters)


# Setting group keys
STREAM_SETTINGS_KEY = "stream_settings"
DVR_SETTINGS_KEY = "dvr_settings"
BACKUP_SETTINGS_KEY = "backup_settings"
PROXY_SETTINGS_KEY = "proxy_settings"
NETWORK_ACCESS_KEY = "network_access"
SYSTEM_SETTINGS_KEY = "system_settings"
EPG_SETTINGS_KEY = "epg_settings"
USER_LIMITS_SETTINGS_KEY = "user_limit_settings"

# Redis cache for CoreSettings JSON groups. Primary invalidation is post_save /
# post_delete; TTL is a safety net if a writer bypasses signals.
# A version key is bumped on invalidate so a concurrent miss cannot re-poison
# Redis with a stale DB snapshot after delete.
_GROUP_CACHE_PREFIX = "coresettings:group:"
_GROUP_CACHE_VER_PREFIX = "coresettings:groupver:"
_GROUP_CACHE_TTL_SECONDS = 300

# Connectivity / timeout only. ResponseError (WRONGTYPE) and similar must still
# propagate. Note: redis-py's AuthenticationError / AuthorizationError subclass
# ConnectionError, so helpers re-raise those after the catch.
_GROUP_CACHE_BACKEND_ERRORS = (
    RedisConnectionError,
    RedisTimeoutError,
    ConnectionInterrupted,
    OSError,
    TimeoutError,
)
_GROUP_CACHE_RERAISE_ERRORS = (RedisAuthenticationError, RedisAuthorizationError)

# Distinct from a normal cache miss (None) so version-guard compares never
# collapse to None == None after a backend failure.
_CACHE_BACKEND_ERROR = object()

_GROUP_CACHE_ERROR_LOG_INTERVAL_SECONDS = 60
_last_group_cache_error_log_at = 0.0


def _log_group_cache_backend_error(operation, key, exc):
    """Warn when settings cache degrades to Postgres (throttled)."""
    global _last_group_cache_error_log_at

    now = time.time()
    if now - _last_group_cache_error_log_at < _GROUP_CACHE_ERROR_LOG_INTERVAL_SECONDS:
        return
    _last_group_cache_error_log_at = now
    logger.warning(
        "CoreSettings group cache %s failed for %s (%s: %s); falling back to Postgres",
        operation,
        key,
        type(exc).__name__,
        exc,
    )


class CoreSettings(models.Model):
    key = models.CharField(
        max_length=255,
        unique=True,
    )
    name = models.CharField(
        max_length=255,
    )
    value = models.JSONField(
        default=dict,
        blank=True,
    )

    def __str__(self):
        return "Core Settings"

    @classmethod
    def group_cache_key(cls, key):
        return f"{_GROUP_CACHE_PREFIX}{key}"

    @classmethod
    def group_cache_ver_key(cls, key):
        return f"{_GROUP_CACHE_VER_PREFIX}{key}"

    @classmethod
    def _cache_get(cls, key, default=None):
        """Read from Django cache.

        Returns ``_CACHE_BACKEND_ERROR`` if Redis is unreachable so callers can
        distinguish that from a normal miss. AIO starts Redis via uWSGI after
        ``migrate``, so settings reads during data migrations must not
        hard-require Redis. Local connection refused fails immediately (no
        connect-timeout wait).
        """
        try:
            from django.core.cache import cache

            return cache.get(key, default)
        except _GROUP_CACHE_RERAISE_ERRORS:
            raise
        except _GROUP_CACHE_BACKEND_ERRORS as exc:
            _log_group_cache_backend_error("get", key, exc)
            return _CACHE_BACKEND_ERROR

    @classmethod
    def _cache_set(cls, key, value, timeout=None):
        """Write to Django cache; no-op if Redis is unreachable."""
        try:
            from django.core.cache import cache

            cache.set(key, value, timeout=timeout)
            return True
        except _GROUP_CACHE_RERAISE_ERRORS:
            raise
        except _GROUP_CACHE_BACKEND_ERRORS as exc:
            _log_group_cache_backend_error("set", key, exc)
            return False

    @classmethod
    def _cache_delete(cls, key):
        """Delete from Django cache; no-op if Redis is unreachable."""
        try:
            from django.core.cache import cache

            cache.delete(key)
            return True
        except _GROUP_CACHE_RERAISE_ERRORS:
            raise
        except _GROUP_CACHE_BACKEND_ERRORS as exc:
            _log_group_cache_backend_error("delete", key, exc)
            return False

    @classmethod
    def invalidate_group_cache(cls, key):
        """Drop the cached JSON for a settings group (all workers share Redis)."""
        cls._cache_delete(cls.group_cache_key(key))
        # Monotonic bump so in-flight _get_group fills skip cache.set.
        # timeout=None: never expire (version must outlive group entries).
        cls._cache_set(cls.group_cache_ver_key(key), time.time_ns(), timeout=None)
        if key == PROXY_SETTINGS_KEY:
            # Proxy workers also keep a short process-local copy.
            try:
                from apps.proxy.config import BaseConfig

                BaseConfig.clear_proxy_settings_cache()
            except Exception:
                pass

    @classmethod
    def _load_group_value(cls, key, defaults):
        """Read a settings group from Postgres (no cache)."""
        try:
            value = cls.objects.get(key=key).value or defaults
            if not isinstance(value, dict):
                value = defaults
        except cls.DoesNotExist:
            value = defaults
        return value

    # Helper methods to get/set grouped settings
    @classmethod
    def _get_group(cls, key, defaults=None):
        """Get a settings group, returning defaults if not found.

        Results are cached in Redis so hot paths (proxy, XC, catchup) do not
        hit Postgres on every client request. If Redis is down (for example
        during AIO first-boot migrate), reads fall through to Postgres and
        skip cache fill so a flapping backend cannot re-poison Redis after
        invalidate. Mutations go through ``save`` / ``_update_group``, which
        invalidate via CoreSettings post_save / post_delete signals.
        """
        import copy

        defaults = defaults or {}
        cache_key = cls.group_cache_key(key)
        ver_key = cls.group_cache_ver_key(key)
        cached = cls._cache_get(cache_key)
        if isinstance(cached, dict):
            return copy.deepcopy(cached)

        # Backend errors are not normal misses: read DB and skip fill so a
        # flapping backend cannot collapse the version guard to None == None.
        if cached is _CACHE_BACKEND_ERROR:
            return copy.deepcopy(cls._load_group_value(key, defaults))

        ver_before = cls._cache_get(ver_key)
        if ver_before is _CACHE_BACKEND_ERROR:
            return copy.deepcopy(cls._load_group_value(key, defaults))

        value = copy.deepcopy(cls._load_group_value(key, defaults))

        # Skip fill if an invalidate landed during the DB read (avoids
        # re-caching a stale snapshot for the full TTL).
        ver_after = cls._cache_get(ver_key)
        if ver_after is _CACHE_BACKEND_ERROR or ver_after != ver_before:
            return value

        cls._cache_set(cache_key, value, timeout=_GROUP_CACHE_TTL_SECONDS)
        return copy.deepcopy(value)

    @classmethod
    def _update_group(cls, key, name, updates):
        """Update specific fields in a settings group."""
        obj, created = cls.objects.get_or_create(
            key=key,
            defaults={"name": name, "value": {}}
        )
        current = obj.value if isinstance(obj.value, dict) else {}
        current.update(updates)
        obj.value = current
        obj.save()
        return current

    # Stream Settings
    @classmethod
    def get_stream_settings(cls):
        """Get all stream-related settings."""
        return cls._get_group(STREAM_SETTINGS_KEY, {
            "default_user_agent": None,
            "default_stream_profile": None,
            "m3u_hash_key": "",
            "default_output_format": "mpegts",
            "hdhr_output_profile_id": None,
        })

    @classmethod
    def get_default_user_agent_id(cls):
        return cls.get_stream_settings().get("default_user_agent")

    @classmethod
    def get_default_stream_profile_id(cls):
        return cls.get_stream_settings().get("default_stream_profile")

    @classmethod
    def get_default_output_format(cls):
        return cls.get_stream_settings().get("default_output_format", "mpegts")

    @classmethod
    def get_m3u_hash_key(cls):
        return cls.get_stream_settings().get("m3u_hash_key", "")

    @classmethod
    def get_preferred_region(cls):
        return cls.get_system_settings().get("preferred_region")

    @classmethod
    def get_auto_import_mapped_files(cls):
        return cls.get_system_settings().get("auto_import_mapped_files")

    # EPG Settings
    @classmethod
    def get_epg_settings(cls):
        """Get all EPG-related settings."""
        return cls._get_group(EPG_SETTINGS_KEY, {
            "epg_match_mode": "default",
            "epg_match_ignore_prefixes": [],
            "epg_match_ignore_suffixes": [],
            "epg_match_ignore_custom": [],
        })

    @classmethod
    def _safe_string_list(cls, value):
        """Return a list of strings, filtering out non-list or non-string values."""
        if not isinstance(value, list):
            return []
        return [v for v in value if isinstance(v, str)]

    @classmethod
    def get_epg_match_ignore_prefixes(cls):
        return cls._safe_string_list(cls.get_epg_settings().get("epg_match_ignore_prefixes", []))

    @classmethod
    def get_epg_match_ignore_suffixes(cls):
        return cls._safe_string_list(cls.get_epg_settings().get("epg_match_ignore_suffixes", []))

    @classmethod
    def get_epg_match_ignore_custom(cls):
        return cls._safe_string_list(cls.get_epg_settings().get("epg_match_ignore_custom", []))

    # DVR Settings
    @classmethod
    def get_dvr_settings(cls):
        """Get all DVR-related settings."""
        return cls._get_group(DVR_SETTINGS_KEY, {
            "tv_template": "TV_Shows/{show}/S{season:02d}E{episode:02d}.mkv",
            "movie_template": "Movies/{title} ({year}).mkv",
            "tv_fallback_dir": "TV_Shows",
            "tv_fallback_template": "TV_Shows/{show}/{start}.mkv",
            "movie_fallback_template": "Movies/{start}.mkv",
            "comskip_enabled": False,
            "comskip_custom_path": "",
            "comskip_mode": "cut",
            "comskip_hw_accel": "none",
            "pre_offset_minutes": 0,
            "post_offset_minutes": 0,
            "series_rules": [],
        })

    @classmethod
    def get_dvr_tv_template(cls):
        return cls.get_dvr_settings().get("tv_template", "TV_Shows/{show}/S{season:02d}E{episode:02d}.mkv")

    @classmethod
    def get_dvr_movie_template(cls):
        return cls.get_dvr_settings().get("movie_template", "Movies/{title} ({year}).mkv")

    @classmethod
    def get_dvr_tv_fallback_dir(cls):
        return cls.get_dvr_settings().get("tv_fallback_dir", "TV_Shows")

    @classmethod
    def get_dvr_tv_fallback_template(cls):
        return cls.get_dvr_settings().get("tv_fallback_template", "TV_Shows/{show}/{start}.mkv")

    @classmethod
    def get_dvr_movie_fallback_template(cls):
        return cls.get_dvr_settings().get("movie_fallback_template", "Movies/{start}.mkv")

    @classmethod
    def get_dvr_comskip_enabled(cls):
        return bool(cls.get_dvr_settings().get("comskip_enabled", False))

    @classmethod
    def get_dvr_comskip_mode(cls):
        mode = cls.get_dvr_settings().get("comskip_mode", "cut")
        return mode if mode in ("cut", "mark") else "cut"

    @classmethod
    def get_dvr_comskip_hw_accel(cls):
        hw = cls.get_dvr_settings().get("comskip_hw_accel", "none")
        return hw if hw in ("none", "cuvid", "qsv") else "none"

    @classmethod
    def get_dvr_comskip_custom_path(cls):
        return cls.get_dvr_settings().get("comskip_custom_path", "")

    @classmethod
    def set_dvr_comskip_custom_path(cls, path: str | None):
        value = (path or "").strip()
        cls._update_group(DVR_SETTINGS_KEY, "DVR Settings", {"comskip_custom_path": value})
        return value

    @classmethod
    def get_dvr_pre_offset_minutes(cls):
        return int(cls.get_dvr_settings().get("pre_offset_minutes", 0) or 0)

    @classmethod
    def get_dvr_post_offset_minutes(cls):
        return int(cls.get_dvr_settings().get("post_offset_minutes", 0) or 0)

    @classmethod
    def get_dvr_series_rules(cls):
        rules = cls.get_dvr_settings().get("series_rules", [])
        if not isinstance(rules, list):
            return []
        return [r for r in rules if isinstance(r, dict)]

    @classmethod
    def set_dvr_series_rules(cls, rules):
        clean = [r for r in rules if isinstance(r, dict)] if isinstance(rules, list) else []
        cls._update_group(DVR_SETTINGS_KEY, "DVR Settings", {"series_rules": clean})
        return clean

    # Proxy Settings
    @classmethod
    def get_proxy_settings(cls):
        """Get proxy settings."""
        return cls._get_group(PROXY_SETTINGS_KEY, {
            "buffering_timeout": 15,
            "buffering_speed": 1.0,
            "redis_chunk_ttl": 60,
            "channel_shutdown_delay": 0,
            "channel_init_grace_period": 60,
            "channel_client_wait_period": 5,
            "new_client_behind_seconds": 5,
        })

    @classmethod
    def get_network_access_settings(cls):
        """CIDR allowlists per endpoint type (UI, STREAMS, XC_API, M3U_EPG, ...)."""
        return cls._get_group(NETWORK_ACCESS_KEY, {})

    # System Settings
    @classmethod
    def get_system_settings(cls):
        """Get all system-related settings."""
        return cls._get_group(SYSTEM_SETTINGS_KEY, {
            "time_zone": getattr(settings, "TIME_ZONE", "UTC") or "UTC",
            "max_system_events": 100,
            "preferred_region": None,
            "auto_import_mapped_files": True,
            "enable_ip_lookup": True,
            "catchup_enabled": True,
        })

    @classmethod
    def get_catchup_enabled(cls):
        """Whether catch-up / timeshift is enabled system-wide (default True)."""
        # Stored as a JSON boolean by System Settings; default on when unset.
        return cls.get_system_settings().get("catchup_enabled", True) is not False

    @classmethod
    def get_system_time_zone(cls):
        return cls.get_system_settings().get("time_zone") or getattr(settings, "TIME_ZONE", "UTC") or "UTC"

    @classmethod
    def set_system_time_zone(cls, tz_name: str | None):
        value = (tz_name or "").strip() or getattr(settings, "TIME_ZONE", "UTC") or "UTC"
        cls._update_group(SYSTEM_SETTINGS_KEY, "System Settings", {"time_zone": value})
        return value

    @classmethod
    def get_hdhr_output_profile_id(cls):
        raw = cls.get_stream_settings().get("hdhr_output_profile_id")
        try:
            return int(raw) if raw is not None else None
        except (ValueError, TypeError):
            return None

    @classmethod
    def get_user_limits_settings(cls):
        return cls._get_group(USER_LIMITS_SETTINGS_KEY, {
            "terminate_on_limit_exceeded": True,
            "prioritize_single_client_channels": True,
            "ignore_same_channel_connections": False,
            "terminate_oldest": True,
        })


class SystemEvent(models.Model):
    """
    Tracks system events like channel start/stop, buffering, failover, client connections.
    Maintains a rolling history based on max_system_events setting.
    """
    EVENT_TYPES = [
        ('channel_start', 'Channel Started'),
        ('channel_stop', 'Channel Stopped'),
        ('channel_buffering', 'Channel Buffering'),
        ('channel_failover', 'Channel Failover'),
        ('channel_reconnect', 'Channel Reconnected'),
        ('channel_error', 'Channel Error'),
        ('client_connect', 'Client Connected'),
        ('client_disconnect', 'Client Disconnected'),
        ('recording_start', 'Recording Started'),
        ('recording_end', 'Recording Ended'),
        ('stream_switch', 'Stream Switched'),
        ('m3u_refresh', 'M3U Refreshed'),
        ('m3u_download', 'M3U Downloaded'),
        ('epg_refresh', 'EPG Refreshed'),
        ('epg_download', 'EPG Downloaded'),
        ('login_success', 'Login Successful'),
        ('login_failed', 'Login Failed'),
        ('logout', 'User Logged Out'),
        ('m3u_blocked', 'M3U Download Blocked'),
        ('epg_blocked', 'EPG Download Blocked'),
        ('vod_start', 'VOD Started'),
        ('vod_stop', 'VOD Stopped'),
    ]

    event_type = models.CharField(max_length=50, choices=EVENT_TYPES, db_index=True)
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    channel_id = models.UUIDField(null=True, blank=True, db_index=True)
    channel_name = models.CharField(max_length=255, null=True, blank=True)
    details = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['-timestamp']),
            models.Index(fields=['event_type', '-timestamp']),
        ]

    def __str__(self):
        return f"{self.event_type} - {self.channel_name or 'N/A'} @ {self.timestamp}"


class SystemNotification(models.Model):
    """
    Stores system notifications that users can view and dismiss.
    Used for version updates, recommended settings, announcements, etc.
    """
    class NotificationType(models.TextChoices):
        VERSION_UPDATE = 'version_update', 'Version Update Available'
        SETTING_RECOMMENDATION = 'setting_recommendation', 'Recommended Setting Change'
        ANNOUNCEMENT = 'announcement', 'System Announcement'
        WARNING = 'warning', 'Warning'
        INFO = 'info', 'Information'

    class Priority(models.TextChoices):
        LOW = 'low', 'Low'
        NORMAL = 'normal', 'Normal'
        HIGH = 'high', 'High'
        CRITICAL = 'critical', 'Critical'

    class Source(models.TextChoices):
        SYSTEM = 'system', 'System Generated'
        DEVELOPER = 'developer', 'Developer Notification'

    # Unique identifier for the notification (e.g., 'version-0.19.0', 'setting-proxy-buffer')
    # This allows deduplication and targeted dismissals
    notification_key = models.CharField(max_length=255, unique=True, db_index=True)

    notification_type = models.CharField(
        max_length=50,
        choices=NotificationType.choices,
        default=NotificationType.INFO,
        db_index=True
    )
    priority = models.CharField(
        max_length=20,
        choices=Priority.choices,
        default=Priority.NORMAL
    )

    # Source of the notification (system-generated vs developer-defined)
    source = models.CharField(
        max_length=20,
        choices=Source.choices,
        default=Source.SYSTEM,
        db_index=True
    )

    title = models.CharField(max_length=255)
    message = models.TextField()

    # Optional action data (e.g., setting key/value for recommendations, release URL for versions)
    action_data = models.JSONField(default=dict, blank=True)

    # Whether this notification is currently active
    is_active = models.BooleanField(default=True, db_index=True)

    # Admin-only notifications require admin privileges to view
    admin_only = models.BooleanField(default=False)

    # Auto-expire after this date (null = never expires)
    expires_at = models.DateTimeField(null=True, blank=True, db_index=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-priority', '-created_at']
        indexes = [
            models.Index(fields=['is_active', '-created_at']),
            models.Index(fields=['notification_type', 'is_active']),
            models.Index(fields=['source', 'is_active']),
        ]

    def __str__(self):
        return f"[{self.notification_type}] {self.title}"

    @classmethod
    def create_version_notification(cls, version, release_url=None, release_notes=None):
        """Create or update a version update notification. Returns (notification, created) tuple."""
        key = f"version-{version}"
        notification, created = cls.objects.update_or_create(
            notification_key=key,
            defaults={
                'notification_type': cls.NotificationType.VERSION_UPDATE,
                'priority': cls.Priority.HIGH,
                'title': f'Version {version} Available',
                'message': f'A new version of Dispatcharr ({version}) is available.',
                'action_data': {
                    'version': version,
                    'release_url': release_url,
                    'release_notes': release_notes,
                },
                'is_active': True,
                'admin_only': True,
            }
        )
        return notification, created

    @classmethod
    def create_setting_recommendation(cls, setting_key, recommended_value, reason, current_value=None):
        """Create a setting recommendation notification. Returns (notification, created) tuple."""
        key = f"setting-{setting_key}"
        notification, created = cls.objects.update_or_create(
            notification_key=key,
            defaults={
                'notification_type': cls.NotificationType.SETTING_RECOMMENDATION,
                'priority': cls.Priority.NORMAL,
                'title': f'Recommended Setting: {setting_key}',
                'message': reason,
                'action_data': {
                    'setting_key': setting_key,
                    'recommended_value': recommended_value,
                    'current_value': current_value,
                },
                'is_active': True,
                'admin_only': True,
            }
        )
        return notification, created


class NotificationDismissal(models.Model):
    """
    Tracks which users have dismissed which notifications.
    Allows users to dismiss notifications once without seeing them again.
    """
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='dismissed_notifications'
    )
    notification = models.ForeignKey(
        SystemNotification,
        on_delete=models.CASCADE,
        related_name='dismissals'
    )
    dismissed_at = models.DateTimeField(auto_now_add=True)

    # Optional: track if user accepted/applied the recommendation
    action_taken = models.CharField(max_length=50, blank=True, null=True)

    class Meta:
        unique_together = ['user', 'notification']
        indexes = [
            models.Index(fields=['user', 'notification']),
        ]

    def __str__(self):
        return f"{self.user.username} dismissed {self.notification.notification_key}"
