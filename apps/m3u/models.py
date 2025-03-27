from django.db import models
from django.core.exceptions import ValidationError
from core.models import UserAgent
import re
from django.dispatch import receiver
from apps.channels.models import StreamProfile

CUSTOM_M3U_ACCOUNT_NAME="custom"

class M3UAccount(models.Model):
    """Represents an M3U Account for IPTV streams."""
    name = models.CharField(
        max_length=255,
        unique=True,
        help_text="Unique name for this M3U account"
    )
    server_url = models.URLField(
        blank=True,
        null=True,
        help_text="The base URL of the M3U server (optional if a file is uploaded)"
    )
    uploaded_file = models.FileField(
        upload_to='m3u_uploads/',
        blank=True,
        null=True
    )
    server_group = models.ForeignKey(
        'ServerGroup',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='m3u_accounts',
        help_text="The server group this M3U account belongs to"
    )
    max_streams = models.PositiveIntegerField(
        default=0,
        help_text="Maximum number of concurrent streams (0 for unlimited)"
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Set to false to deactivate this M3U account"
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        help_text="Time when this account was created"
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        help_text="Time when this account was last updated"
    )
    user_agent = models.ForeignKey(
        'core.UserAgent',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='m3u_accounts',
        help_text="The User-Agent associated with this M3U account."
    )
    locked = models.BooleanField(
        default=False,
        help_text="Protected - can't be deleted or modified"
    )
    stream_profile = models.ForeignKey(
        StreamProfile,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='m3u_accounts'
    )
    custom_properties = models.TextField(null=True, blank=True)

    def __str__(self):
        return self.name

    def clean(self):
        if self.max_streams < 0:
            raise ValidationError("Max streams cannot be negative.")

    def display_action(self):
        return "Exclude" if self.exclude else "Include"

    def deactivate_streams(self):
        """Deactivate all streams linked to this account."""
        for stream in self.streams.all():
            stream.is_active = False
            stream.save()

    def reactivate_streams(self):
        """Reactivate all streams linked to this account."""
        for stream in self.streams.all():
            stream.is_active = True
            stream.save()

    @classmethod
    def get_custom_account(cls):
        return cls.objects.get(name=CUSTOM_M3U_ACCOUNT_NAME, locked=True)

    # def get_channel_groups(self):
    #     return ChannelGroup.objects.filter(m3u_account__m3u_account=self)

    # def is_channel_group_enabled(self, channel_group):
    #     """Check if the specified ChannelGroup is enabled for this M3UAccount."""
    #     return self.channel_group.filter(channel_group=channel_group, enabled=True).exists()

    # def get_enabled_streams(self):
    #     """Return all streams linked to this account with enabled ChannelGroups."""
    #     return self.streams.filter(channel_group__in=ChannelGroup.objects.filter(m3u_account__enabled=True))

class M3UFilter(models.Model):
    """Defines filters for M3U accounts based on stream name or group title."""
    FILTER_TYPE_CHOICES = (
        ('group', 'Group Title'),
        ('name', 'Stream Name'),
    )
    m3u_account = models.ForeignKey(
        M3UAccount,
        on_delete=models.CASCADE,
        related_name='filters',
        help_text="The M3U account this filter is applied to."
    )
    filter_type = models.CharField(
        max_length=50,
        choices=FILTER_TYPE_CHOICES,
        default='group',
        help_text="Filter based on either group title or stream name."
    )
    regex_pattern = models.CharField(
        max_length=200,
        help_text="A regex pattern to match streams or groups."
    )
    exclude = models.BooleanField(
        default=True,
        help_text="If True, matching items are excluded; if False, only matches are included."
    )

    def applies_to(self, stream_name, group_name):
        target = group_name if self.filter_type == 'group' else stream_name
        return bool(re.search(self.regex_pattern, target, re.IGNORECASE))

    def clean(self):
        try:
            re.compile(self.regex_pattern)
        except re.error:
            raise ValidationError(f"Invalid regex pattern: {self.regex_pattern}")

    def __str__(self):
        filter_type_display = dict(self.FILTER_TYPE_CHOICES).get(self.filter_type, 'Unknown')
        exclude_status = "Exclude" if self.exclude else "Include"
        return f"[{self.m3u_account.name}] {filter_type_display}: {self.regex_pattern} ({exclude_status})"

    @staticmethod
    def filter_streams(streams, filters):
        included_streams = set()
        excluded_streams = set()

        for f in filters:
            for stream in streams:
                if f.applies_to(stream.name, stream.group_name):
                    if f.exclude:
                        excluded_streams.add(stream)
                    else:
                        included_streams.add(stream)

        # If no include filters exist, assume all non-excluded streams are valid
        if not any(not f.exclude for f in filters):
            return streams.exclude(id__in=[s.id for s in excluded_streams])

        return streams.filter(id__in=[s.id for s in included_streams])


class ServerGroup(models.Model):
    """Represents a logical grouping of servers or channels."""
    name = models.CharField(
        max_length=100,
        unique=True,
        help_text="Unique name for this server group."
    )

    def __str__(self):
        return self.name

from django.db import models

class M3UAccountProfile(models.Model):
    """Represents a profile associated with an M3U Account."""
    m3u_account = models.ForeignKey(
        'M3UAccount',
        on_delete=models.CASCADE,
        related_name='profiles',
        help_text="The M3U account this profile belongs to."
    )
    name = models.CharField(
        max_length=255,
        help_text="Name for the M3U account profile"
    )
    is_default = models.BooleanField(
        default=False,
        help_text="Set to false to deactivate this profile"
    )
    max_streams = models.PositiveIntegerField(
        default=0,
        help_text="Maximum number of concurrent streams (0 for unlimited)"
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Set to false to deactivate this profile"
    )
    search_pattern = models.CharField(
        max_length=255,
    )
    replace_pattern = models.CharField(
        max_length=255,
    )
    current_viewers = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['m3u_account', 'name'], name='unique_account_name')
        ]

    def __str__(self):
        return f"{self.name} ({self.m3u_account.name})"

@receiver(models.signals.post_save, sender=M3UAccount)
def create_profile_for_m3u_account(sender, instance, created, **kwargs):
    """Automatically create an M3UAccountProfile when M3UAccount is created."""
    if created:
        M3UAccountProfile.objects.create(
            m3u_account=instance,
            name=f'{instance.name} Default',
            max_streams=instance.max_streams,
            is_default=True,
            is_active=True,
            search_pattern="^(.*)$",
            replace_pattern="$1",
        )
    else:
        profile = M3UAccountProfile.objects.get(
            m3u_account=instance,
            is_default=True,
        )


        profile.max_streams = instance.max_streams
        profile.save()
