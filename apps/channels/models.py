from django.db import models
from django.core.exceptions import ValidationError
from core.models import StreamProfile
from django.conf import settings
from core.models import StreamProfile, CoreSettings
from core.utils import redis_client, execute_redis_command
import logging
import uuid
from datetime import datetime
import hashlib
import json

logger = logging.getLogger(__name__)

# If you have an M3UAccount model in apps.m3u, you can still import it:
from apps.m3u.models import M3UAccount

# Add fallback functions if Redis isn't available
def get_total_viewers(channel_id):
    """Get viewer count from Redis or return 0 if Redis isn't available"""
    if redis_client is None:
        return 0

    try:
        return int(redis_client.get(f"channel:{channel_id}:viewers") or 0)
    except Exception:
        return 0

class ChannelGroup(models.Model):
    name = models.CharField(max_length=100, unique=True)

    def related_channels(self):
        # local import if needed to avoid cyc. Usually fine in a single file though
        return Channel.objects.filter(channel_group=self)

    def __str__(self):
        return self.name

    @classmethod
    def bulk_create_and_fetch(cls, objects):
        # Perform the bulk create operation
        cls.objects.bulk_create(objects)

        # Use a unique field to fetch the created objects (assuming 'name' is unique)
        created_objects = cls.objects.filter(name__in=[obj.name for obj in objects])

        return created_objects

class Stream(models.Model):
    """
    Represents a single stream (e.g. from an M3U source or custom URL).
    """
    name = models.CharField(max_length=255, default="Default Stream")
    url = models.URLField(max_length=2000, blank=True, null=True)
    m3u_account = models.ForeignKey(
        M3UAccount,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="streams",
    )
    logo_url = models.TextField(blank=True, null=True)
    tvg_id = models.CharField(max_length=255, blank=True, null=True)
    local_file = models.FileField(upload_to='uploads/', blank=True, null=True)
    current_viewers = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)
    channel_group = models.ForeignKey(
        ChannelGroup,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='streams'
    )
    stream_profile = models.ForeignKey(
        StreamProfile,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='streams'
    )
    is_custom = models.BooleanField(
        default=False,
        help_text="Whether this is a user-created stream or from an M3U account"
    )
    stream_hash = models.CharField(
        max_length=255,
        null=True,
        unique=True,
        help_text="Unique hash for this stream from the M3U account",
        db_index=True,
    )
    last_seen = models.DateTimeField(db_index=True, default=datetime.now)

    class Meta:
        # If you use m3u_account, you might do unique_together = ('name','url','m3u_account')
        verbose_name = "Stream"
        verbose_name_plural = "Streams"
        ordering = ['-updated_at']

    def __str__(self):
        return self.name or self.url or f"Stream ID {self.id}"

    @classmethod
    def generate_hash_key(cls, name, url, tvg_id, keys=None):
        if keys is None:
            keys = CoreSettings.get_m3u_hash_key().split(",")

        stream_parts = {
            "name": name, "url": url, "tvg_id": tvg_id
        }

        hash_parts = {key: stream_parts[key] for key in keys if key in stream_parts}

        # Serialize and hash the dictionary
        serialized_obj = json.dumps(hash_parts, sort_keys=True)  # sort_keys ensures consistent ordering
        hash_object = hashlib.sha256(serialized_obj.encode())
        return hash_object.hexdigest()

    @classmethod
    def update_or_create_by_hash(cls, hash_value, **fields_to_update):
        try:
            # Try to find the Stream object with the given hash
            stream = cls.objects.get(stream_hash=hash_value)
            # If it exists, update the fields
            for field, value in fields_to_update.items():
                setattr(stream, field, value)
            stream.save()  # Save the updated object
            return stream, False  # False means it was updated, not created
        except cls.DoesNotExist:
            # If it doesn't exist, create a new object with the given hash
            fields_to_update['stream_hash'] = hash_value  # Make sure the hash field is set
            stream = cls.objects.create(**fields_to_update)
            return stream, True  # True means it was created

class ChannelManager(models.Manager):
    def active(self):
        return self.all()


class Channel(models.Model):
    channel_number = models.IntegerField()
    name = models.CharField(max_length=255)
    logo_url = models.URLField(max_length=2000, blank=True, null=True)
    logo_file = models.ImageField(
        upload_to='logos/',  # Will store in MEDIA_ROOT/logos
        blank=True,
        null=True
    )

    # M2M to Stream now in the same file
    streams = models.ManyToManyField(
        Stream,
        blank=True,
        through='ChannelStream',
        related_name='channels'
    )

    channel_group = models.ForeignKey(
        'ChannelGroup',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='channels',
        help_text="Channel group this channel belongs to."
    )
    tvg_id = models.CharField(max_length=255, blank=True, null=True)
    tvg_name = models.CharField(max_length=255, blank=True, null=True)

    stream_profile = models.ForeignKey(
        StreamProfile,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='channels'
    )

    uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True, db_index=True)

    def clean(self):
        # Enforce unique channel_number within a given group
        existing = Channel.objects.filter(
            channel_number=self.channel_number,
            channel_group=self.channel_group
        ).exclude(id=self.id)
        if existing.exists():
            raise ValidationError(
                f"Channel number {self.channel_number} already exists in group {self.channel_group}."
            )

    def __str__(self):
        return f"{self.channel_number} - {self.name}"

    def get_stream_profile(self):
        stream_profile = self.stream_profile
        if not stream_profile:
            stream_profile = StreamProfile.objects.get(id=CoreSettings.get_default_stream_profile_id())

        return stream_profile

    def get_stream(self):
        """
        Finds an available stream for the requested channel and returns the selected stream and profile.
        """

        # 2. Check if a stream is already active for this channel
        stream_id = redis_client.get(f"channel_stream:{self.id}")
        if stream_id:
            stream_id = int(stream_id)
            profile_id = redis_client.get(f"stream_profile:{stream_id}")
            if profile_id:
                profile_id = int(profile_id)
                return stream_id, profile_id

        # 3. Iterate through channel streams and their profiles
        for stream in self.streams.all().order_by('channelstream__order'):
            # Retrieve the M3U account associated with the stream.
            m3u_account = stream.m3u_account
            m3u_profiles = m3u_account.profiles.all()
            default_profile = next((obj for obj in m3u_profiles if obj.is_default), None)
            profiles = [default_profile] + [obj for obj in m3u_profiles if not obj.is_default]

            logger.info('profiles')

            for profile in profiles:
                logger.info(profile)
                # Skip inactive profiles
                if profile.is_active == False:
                    continue

                profile_connections_key = f"profile_connections:{profile.id}"
                current_connections = int(redis_client.get(profile_connections_key) or 0)

                # Check if profile has available slots (or unlimited connections)
                if profile.max_streams == 0 or current_connections < profile.max_streams:
                    # Start a new stream
                    redis_client.set(f"channel_stream:{self.id}", stream.id)
                    redis_client.set(f"stream_profile:{stream.id}", profile.id)  # Store only the matched profile

                    # Increment connection count for profiles with limits
                    if profile.max_streams > 0:
                        redis_client.incr(profile_connections_key)

                    return stream.id, profile.id  # Return newly assigned stream and matched profile

        # 4. No available streams
        return None, None

    def release_stream(self):
        """
        Called when a stream is finished to release the lock.
        """
        stream_id = redis_client.get(f"channel_stream:{self.id}")
        if not stream_id:
            logger.debug("Invalid stream ID pulled from channel index")
            return

        redis_client.delete(f"channel_stream:{self.id}")  # Remove active stream

        stream_id = int(stream_id)
        logger.debug(f"Found stream ID {stream_id} associated with channel stream {self.id}")

        # Get the matched profile for cleanup
        profile_id = redis_client.get(f"stream_profile:{stream_id}")
        if not profile_id:
            logger.debug("Invalid profile ID pulled from stream index")
            return

        redis_client.delete(f"stream_profile:{stream_id}")  # Remove profile association

        profile_id = int(profile_id)
        logger.debug(f"Found profile ID {profile_id} associated with stream {stream_id}")

        profile_connections_key = f"profile_connections:{profile_id}"

        # Only decrement if the profile had a max_connections limit
        current_count = int(redis_client.get(profile_connections_key) or 0)
        if current_count > 0:
            redis_client.decr(profile_connections_key)

class ChannelStream(models.Model):
    channel = models.ForeignKey(Channel, on_delete=models.CASCADE)
    stream = models.ForeignKey(Stream, on_delete=models.CASCADE)
    order = models.PositiveIntegerField(default=0)  # Ordering field

    class Meta:
        ordering = ['order']  # Ensure streams are retrieved in order

class ChannelGroupM3UAccount(models.Model):
    channel_group = models.ForeignKey(
        ChannelGroup,
        on_delete=models.CASCADE,
        related_name='m3u_account'
    )
    m3u_account = models.ForeignKey(
        M3UAccount,
        on_delete=models.CASCADE,
        related_name='channel_group'
    )
    enabled = models.BooleanField(default=True)

    class Meta:
        unique_together = ('channel_group', 'm3u_account')

    def __str__(self):
        return f"{self.channel_group.name} - {self.m3u_account.name} (Enabled: {self.enabled})"
