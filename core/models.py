# core/models.py
from django.conf import settings
from django.db import models
from django.utils.text import slugify
from django.core.exceptions import ValidationError


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
            for part in self.parameters.split()
        ]

        return cmd

    def _replace_in_part(self, part, replacements):
        # Iterate through the replacements and replace each part of the string
        for key, value in replacements.items():
            part = part.replace(key, value)
        return part


DEFAULT_USER_AGENT_KEY = slugify("Default User-Agent")
DEFAULT_STREAM_PROFILE_KEY = slugify("Default Stream Profile")
STREAM_HASH_KEY = slugify("M3U Hash Key")
PREFERRED_REGION_KEY = slugify("Preferred Region")
AUTO_IMPORT_MAPPED_FILES = slugify("Auto-Import Mapped Files")
NETWORK_ACCESS = slugify("Network Access")
PROXY_SETTINGS_KEY = slugify("Proxy Settings")
DVR_TV_TEMPLATE_KEY = slugify("DVR TV Template")
DVR_MOVIE_TEMPLATE_KEY = slugify("DVR Movie Template")
DVR_SERIES_RULES_KEY = slugify("DVR Series Rules")
DVR_TV_FALLBACK_DIR_KEY = slugify("DVR TV Fallback Dir")
DVR_TV_FALLBACK_TEMPLATE_KEY = slugify("DVR TV Fallback Template")
DVR_MOVIE_FALLBACK_TEMPLATE_KEY = slugify("DVR Movie Fallback Template")
DVR_COMSKIP_ENABLED_KEY = slugify("DVR Comskip Enabled")
DVR_COMSKIP_CUSTOM_PATH_KEY = slugify("DVR Comskip Custom Path")
DVR_PRE_OFFSET_MINUTES_KEY = slugify("DVR Pre-Offset Minutes")
DVR_POST_OFFSET_MINUTES_KEY = slugify("DVR Post-Offset Minutes")
SYSTEM_TIME_ZONE_KEY = slugify("System Time Zone")


class CoreSettings(models.Model):
    key = models.CharField(
        max_length=255,
        unique=True,
    )
    name = models.CharField(
        max_length=255,
    )
    value = models.CharField(
        max_length=255,
    )

    def __str__(self):
        return "Core Settings"

    @classmethod
    def get_default_user_agent_id(cls):
        """Retrieve a system profile by name (or return None if not found)."""
        return cls.objects.get(key=DEFAULT_USER_AGENT_KEY).value

    @classmethod
    def get_default_stream_profile_id(cls):
        return cls.objects.get(key=DEFAULT_STREAM_PROFILE_KEY).value

    @classmethod
    def get_m3u_hash_key(cls):
        return cls.objects.get(key=STREAM_HASH_KEY).value

    @classmethod
    def get_preferred_region(cls):
        """Retrieve the preferred region setting (or return None if not found)."""
        try:
            return cls.objects.get(key=PREFERRED_REGION_KEY).value
        except cls.DoesNotExist:
            return None

    @classmethod
    def get_auto_import_mapped_files(cls):
        """Retrieve the preferred region setting (or return None if not found)."""
        try:
            return cls.objects.get(key=AUTO_IMPORT_MAPPED_FILES).value
        except cls.DoesNotExist:
            return None

    @classmethod
    def get_proxy_settings(cls):
        """Retrieve proxy settings as dict (or return defaults if not found)."""
        try:
            import json
            settings_json = cls.objects.get(key=PROXY_SETTINGS_KEY).value
            return json.loads(settings_json)
        except (cls.DoesNotExist, json.JSONDecodeError):
            # Return defaults if not found or invalid JSON
            return {
                "buffering_timeout": 15,
                "buffering_speed": 1.0,
                "redis_chunk_ttl": 60,
                "channel_shutdown_delay": 0,
                "channel_init_grace_period": 5,
            }

    @classmethod
    def get_dvr_tv_template(cls):
        try:
            return cls.objects.get(key=DVR_TV_TEMPLATE_KEY).value
        except cls.DoesNotExist:
            # Default: relative to recordings root (/data/recordings)
            return "TV_Shows/{show}/S{season:02d}E{episode:02d}.mkv"

    @classmethod
    def get_dvr_movie_template(cls):
        try:
            return cls.objects.get(key=DVR_MOVIE_TEMPLATE_KEY).value
        except cls.DoesNotExist:
            return "Movies/{title} ({year}).mkv"

    @classmethod
    def get_dvr_tv_fallback_dir(cls):
        """Folder name to use when a TV episode has no season/episode information.
        Defaults to 'TV_Show' to match existing behavior but can be overridden in settings.
        """
        try:
            return cls.objects.get(key=DVR_TV_FALLBACK_DIR_KEY).value or "TV_Shows"
        except cls.DoesNotExist:
            return "TV_Shows"

    @classmethod
    def get_dvr_tv_fallback_template(cls):
        """Full path template used when season/episode are missing for a TV airing."""
        try:
            return cls.objects.get(key=DVR_TV_FALLBACK_TEMPLATE_KEY).value
        except cls.DoesNotExist:
            # default requested by user
            return "TV_Shows/{show}/{start}.mkv"

    @classmethod
    def get_dvr_movie_fallback_template(cls):
        """Full path template used when movie metadata is incomplete."""
        try:
            return cls.objects.get(key=DVR_MOVIE_FALLBACK_TEMPLATE_KEY).value
        except cls.DoesNotExist:
            return "Movies/{start}.mkv"

    @classmethod
    def get_dvr_comskip_enabled(cls):
        """Return boolean-like string value ('true'/'false') for comskip enablement."""
        try:
            val = cls.objects.get(key=DVR_COMSKIP_ENABLED_KEY).value
            return str(val).lower() in ("1", "true", "yes", "on")
        except cls.DoesNotExist:
            return False

    @classmethod
    def get_dvr_comskip_custom_path(cls):
        """Return configured comskip.ini path or empty string if unset."""
        try:
            return cls.objects.get(key=DVR_COMSKIP_CUSTOM_PATH_KEY).value
        except cls.DoesNotExist:
            return ""

    @classmethod
    def set_dvr_comskip_custom_path(cls, path: str | None):
        """Persist the comskip.ini path setting, normalizing nulls to empty string."""
        value = (path or "").strip()
        obj, _ = cls.objects.get_or_create(
            key=DVR_COMSKIP_CUSTOM_PATH_KEY,
            defaults={"name": "DVR Comskip Custom Path", "value": value},
        )
        if obj.value != value:
            obj.value = value
            obj.save(update_fields=["value"])
        return value

    @classmethod
    def get_dvr_pre_offset_minutes(cls):
        """Minutes to start recording before scheduled start (default 0)."""
        try:
            val = cls.objects.get(key=DVR_PRE_OFFSET_MINUTES_KEY).value
            return int(val)
        except cls.DoesNotExist:
            return 0
        except Exception:
            try:
                return int(float(val))
            except Exception:
                return 0

    @classmethod
    def get_dvr_post_offset_minutes(cls):
        """Minutes to stop recording after scheduled end (default 0)."""
        try:
            val = cls.objects.get(key=DVR_POST_OFFSET_MINUTES_KEY).value
            return int(val)
        except cls.DoesNotExist:
            return 0
        except Exception:
            try:
                return int(float(val))
            except Exception:
                return 0

    @classmethod
    def get_system_time_zone(cls):
        """Return configured system time zone or fall back to Django settings."""
        try:
            value = cls.objects.get(key=SYSTEM_TIME_ZONE_KEY).value
            if value:
                return value
        except cls.DoesNotExist:
            pass
        return getattr(settings, "TIME_ZONE", "UTC") or "UTC"

    @classmethod
    def set_system_time_zone(cls, tz_name: str | None):
        """Persist the desired system time zone identifier."""
        value = (tz_name or "").strip() or getattr(settings, "TIME_ZONE", "UTC") or "UTC"
        obj, _ = cls.objects.get_or_create(
            key=SYSTEM_TIME_ZONE_KEY,
            defaults={"name": "System Time Zone", "value": value},
        )
        if obj.value != value:
            obj.value = value
            obj.save(update_fields=["value"])
        return value

    @classmethod
    def get_dvr_series_rules(cls):
        """Return list of series recording rules. Each: {tvg_id, title, mode: 'all'|'new'}"""
        import json
        try:
            raw = cls.objects.get(key=DVR_SERIES_RULES_KEY).value
            rules = json.loads(raw) if raw else []
            if isinstance(rules, list):
                return rules
            return []
        except cls.DoesNotExist:
            # Initialize empty if missing
            cls.objects.create(key=DVR_SERIES_RULES_KEY, name="DVR Series Rules", value="[]")
            return []

    @classmethod
    def set_dvr_series_rules(cls, rules):
        import json
        try:
            obj, _ = cls.objects.get_or_create(key=DVR_SERIES_RULES_KEY, defaults={"name": "DVR Series Rules", "value": "[]"})
            obj.value = json.dumps(rules)
            obj.save(update_fields=["value"])
            return rules
        except Exception:
            return rules
