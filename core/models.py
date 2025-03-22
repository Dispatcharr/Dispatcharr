# core/models.py
from django.db import models
from django.utils.text import slugify

class UserAgent(models.Model):
    name = models.CharField(
        max_length=512,
        unique=True,
        help_text="The User-Agent name."
    )
    user_agent = models.CharField(
        max_length=512,
        unique=True,
        help_text="The complete User-Agent string sent by the client."
    )
    description = models.CharField(
        max_length=255,
        blank=True,
        help_text="An optional description of the client or device type."
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Whether this user agent is currently allowed/recognized."
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

PROXY_PROFILE_NAME = 'Proxy'
REDIRECT_PROFILE_NAME = 'Redirect'

class StreamProfile(models.Model):
    name = models.CharField(max_length=255, help_text="Name of the stream profile")
    command = models.CharField(
        max_length=255,
        help_text="Command to execute (e.g., 'yt.sh', 'streamlink', or 'vlc')",
        blank=True
    )
    parameters = models.TextField(
        help_text="Command-line parameters. Use {userAgent} and {streamUrl} as placeholders.",
        blank=True
    )
    locked = models.BooleanField(
        default=False,
        help_text="Protected - can't be deleted or modified"
    )
    is_active = models.BooleanField(default=True, help_text="Whether this profile is active")
    user_agent = models.ForeignKey(
        "UserAgent",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="Optional user agent to use. If not set, you can fall back to a default."
    )

    def __str__(self):
        return self.name

    def delete(self):
        if self.locked():
            raise ValueError("This profile is locked and cannot be deleted.")

        self.delete()

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
                        raise ValidationError(f"Cannot modify {field_name} on a protected profile.")

        super().save(*args, **kwargs)

    @classmethod
    def update(cls, pk, **kwargs):
        instance = cls.objects.get(pk=pk)

        if instance.locked:
            allowed_fields = {"user_agent_id"}  # Only allow updating this field

            for field_name, new_value in kwargs.items():
                if field_name not in allowed_fields:
                    raise ValidationError(f"Cannot modify {field_name} on a protected profile.")

                # Ensure user_agent ForeignKey updates correctly
                if field_name == "user_agent" and isinstance(new_value, cls._meta.get_field("user_agent").related_model):
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
            self._replace_in_part(part, replacements) for part in self.parameters.split()
        ]

        return cmd

    def _replace_in_part(self, part, replacements):
        # Iterate through the replacements and replace each part of the string
        for key, value in replacements.items():
            part = part.replace(key, value)
        return part


DEFAULT_USER_AGENT_KEY= slugify("Default User-Agent")
DEFAULT_STREAM_PROFILE_KEY = slugify("Default Stream Profile")
STREAM_HASH_KEY = slugify("M3U Hash Key")
PREFERRED_REGION_KEY = slugify("Preferred Region")

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

    def get_preferred_region(cls):
        """Retrieve the preferred region setting (or return None if not found)."""
        try:
            return cls.objects.get(key=PREFERRED_REGION_KEY).value
        except cls.DoesNotExist:
            return None
