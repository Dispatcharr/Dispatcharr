import json
from rest_framework import serializers
from .models import (
    Stream,
    Channel,
    ChannelGroup,
    ChannelStream,
    ChannelGroupM3UAccount,
    Logo,
    ChannelProfile,
    ChannelProfileMembership,
    Recording,
)
from apps.epg.serializers import EPGDataSerializer
from core.models import StreamProfile
from apps.epg.models import EPGData
from django.urls import reverse
from rest_framework import serializers
from django.utils import timezone
from core.utils import validate_flexible_url


class LogoSerializer(serializers.ModelSerializer):
    cache_url = serializers.SerializerMethodField()
    channel_count = serializers.SerializerMethodField()
    is_used = serializers.SerializerMethodField()
    channel_names = serializers.SerializerMethodField()

    class Meta:
        model = Logo
        fields = ["id", "name", "url", "cache_url", "channel_count", "is_used", "channel_names"]

    def validate_url(self, value):
        """Validate that the URL is unique for creation or update"""
        if self.instance and self.instance.url == value:
            return value

        if Logo.objects.filter(url=value).exists():
            raise serializers.ValidationError("A logo with this URL already exists.")

        return value

    def create(self, validated_data):
        """Handle logo creation with proper URL validation"""
        return Logo.objects.create(**validated_data)

    def update(self, instance, validated_data):
        """Handle logo updates"""
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        return instance

    def get_cache_url(self, obj):
        # return f"/api/channels/logos/{obj.id}/cache/"
        request = self.context.get("request")
        if request:
            return request.build_absolute_uri(
                reverse("api:channels:logo-cache", args=[obj.id])
            )
        return reverse("api:channels:logo-cache", args=[obj.id])

    def get_channel_count(self, obj):
        """Get the number of channels, movies, and series using this logo"""
        channel_count = obj.channels.count()

        # Safely get movie count
        try:
            movie_count = obj.movie.count() if hasattr(obj, 'movie') else 0
        except AttributeError:
            movie_count = 0

        # Safely get series count
        try:
            series_count = obj.series.count() if hasattr(obj, 'series') else 0
        except AttributeError:
            series_count = 0

        return channel_count + movie_count + series_count

    def get_is_used(self, obj):
        """Check if this logo is used by any channels, movies, or series"""
        # Check if used by channels
        if obj.channels.exists():
            return True

        # Check if used by movies (handle case where VOD app might not be available)
        try:
            if hasattr(obj, 'movie') and obj.movie.exists():
                return True
        except AttributeError:
            pass

        # Check if used by series (handle case where VOD app might not be available)
        try:
            if hasattr(obj, 'series') and obj.series.exists():
                return True
        except AttributeError:
            pass

        return False

    def get_channel_names(self, obj):
        """Get the names of channels, movies, and series using this logo (limited to first 5)"""
        names = []

        # Get channel names
        channels = obj.channels.all()[:5]
        for channel in channels:
            names.append(f"Channel: {channel.name}")

        # Get movie names (only if we haven't reached limit)
        if len(names) < 5:
            try:
                if hasattr(obj, 'movie'):
                    remaining_slots = 5 - len(names)
                    movies = obj.movie.all()[:remaining_slots]
                    for movie in movies:
                        names.append(f"Movie: {movie.name}")
            except AttributeError:
                pass

        # Get series names (only if we haven't reached limit)
        if len(names) < 5:
            try:
                if hasattr(obj, 'series'):
                    remaining_slots = 5 - len(names)
                    series = obj.series.all()[:remaining_slots]
                    for series_item in series:
                        names.append(f"Series: {series_item.name}")
            except AttributeError:
                pass

        # Calculate total count for "more" message
        total_count = self.get_channel_count(obj)
        if total_count > 5:
            names.append(f"...and {total_count - 5} more")

        return names


#
# Stream
#
class StreamSerializer(serializers.ModelSerializer):
    url = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        validators=[validate_flexible_url]
    )
    stream_profile_id = serializers.PrimaryKeyRelatedField(
        queryset=StreamProfile.objects.all(),
        source="stream_profile",
        allow_null=True,
        required=False,
    )
    read_only_fields = ["is_custom", "m3u_account", "stream_hash"]

    class Meta:
        model = Stream
        fields = [
            "id",
            "name",
            "url",
            "m3u_account",  # Uncomment if using M3U fields
            "logo_url",
            "tvg_id",
            "local_file",
            "current_viewers",
            "updated_at",
            "last_seen",
            "stream_profile_id",
            "is_custom",
            "channel_group",
            "stream_hash",
            "stream_stats",
            "stream_stats_updated_at",
        ]

    def get_fields(self):
        fields = super().get_fields()

        # Unable to edit specific properties if this stream was created from an M3U account
        if (
            self.instance
            and getattr(self.instance, "m3u_account", None)
            and not self.instance.is_custom
        ):
            fields["id"].read_only = True
            fields["name"].read_only = True
            fields["url"].read_only = True
            fields["m3u_account"].read_only = True
            fields["tvg_id"].read_only = True
            fields["channel_group"].read_only = True

        return fields


class ChannelGroupM3UAccountSerializer(serializers.ModelSerializer):
    m3u_accounts = serializers.IntegerField(source="m3u_accounts.id", read_only=True)
    enabled = serializers.BooleanField()
    auto_channel_sync = serializers.BooleanField(default=False)
    auto_sync_channel_start = serializers.FloatField(allow_null=True, required=False)
    custom_properties = serializers.JSONField(required=False)

    class Meta:
        model = ChannelGroupM3UAccount
        fields = ["m3u_accounts", "channel_group", "enabled", "auto_channel_sync", "auto_sync_channel_start", "custom_properties"]

    def to_representation(self, instance):
        data = super().to_representation(instance)

        custom_props = instance.custom_properties or {}

        return data

    def to_internal_value(self, data):
        # Accept both dict and JSON string for custom_properties (for backward compatibility)
        val = data.get("custom_properties")
        if isinstance(val, str):
            try:
                data["custom_properties"] = json.loads(val)
            except Exception:
                pass

        return super().to_internal_value(data)

#
# Channel Group
#
class ChannelGroupSerializer(serializers.ModelSerializer):
    channel_count = serializers.IntegerField(read_only=True)
    m3u_account_count = serializers.IntegerField(read_only=True)
    m3u_accounts = ChannelGroupM3UAccountSerializer(
        many=True,
        read_only=True
    )

    class Meta:
        model = ChannelGroup
        fields = ["id", "name", "channel_count", "m3u_account_count", "m3u_accounts"]


class ChannelProfileSerializer(serializers.ModelSerializer):
    channels = serializers.SerializerMethodField()

    class Meta:
        model = ChannelProfile
        fields = ["id", "name", "channels"]

    def get_channels(self, obj):
        memberships = ChannelProfileMembership.objects.filter(
            channel_profile=obj, enabled=True
        )
        return [membership.channel.id for membership in memberships]


class ChannelProfileMembershipSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChannelProfileMembership
        fields = ["channel", "enabled"]


class ChanneProfilelMembershipUpdateSerializer(serializers.Serializer):
    channel_id = serializers.IntegerField()  # Ensure channel_id is an integer
    enabled = serializers.BooleanField()


class BulkChannelProfileMembershipSerializer(serializers.Serializer):
    channels = serializers.ListField(
        child=ChanneProfilelMembershipUpdateSerializer(),  # Use the nested serializer
        allow_empty=False,
    )

    def validate_channels(self, value):
        if not value:
            raise serializers.ValidationError("At least one channel must be provided.")
        return value


#
# Channel
#
class ChannelSerializer(serializers.ModelSerializer):
    # Show nested group data, or ID
    # Ensure channel_number is explicitly typed as FloatField and properly validated
    channel_number = serializers.FloatField(
        allow_null=True,
        required=False,
        error_messages={"invalid": "Channel number must be a valid decimal number."},
    )
    channel_group_id = serializers.PrimaryKeyRelatedField(
        queryset=ChannelGroup.objects.all(), source="channel_group", required=False
    )
    epg_data_id = serializers.PrimaryKeyRelatedField(
        queryset=EPGData.objects.all(),
        source="epg_data",
        required=False,
        allow_null=True,
    )

    stream_profile_id = serializers.PrimaryKeyRelatedField(
        queryset=StreamProfile.objects.all(),
        source="stream_profile",
        allow_null=True,
        required=False,
    )

    streams = serializers.PrimaryKeyRelatedField(
        queryset=Stream.objects.all(), many=True, required=False
    )

    logo_id = serializers.PrimaryKeyRelatedField(
        queryset=Logo.objects.all(),
        source="logo",
        allow_null=True,
        required=False,
    )

    auto_created_by_name = serializers.SerializerMethodField()

    class Meta:
        model = Channel
        fields = [
            "id",
            "channel_number",
            "name",
            "channel_group_id",
            "tvg_id",
            "tvc_guide_stationid",
            "epg_data_id",
            "streams",
            "stream_profile_id",
            "uuid",
            "logo_id",
            "user_level",
            "auto_created",
            "auto_created_by",
            "auto_created_by_name",
        ]

    def to_representation(self, instance):
        include_streams = self.context.get("include_streams", False)

        if include_streams:
            self.fields["streams"] = serializers.SerializerMethodField()

        return super().to_representation(instance)

    def get_logo(self, obj):
        return LogoSerializer(obj.logo).data

    def get_streams(self, obj):
        """Retrieve ordered stream IDs for GET requests."""
        return StreamSerializer(
            obj.streams.all().order_by("channelstream__order"), many=True
        ).data

    def create(self, validated_data):
        streams = validated_data.pop("streams", [])
        channel_number = validated_data.pop(
            "channel_number", Channel.get_next_available_channel_number()
        )
        validated_data["channel_number"] = channel_number
        channel = Channel.objects.create(**validated_data)

        # Add streams in the specified order
        for index, stream in enumerate(streams):
            ChannelStream.objects.create(
                channel=channel, stream_id=stream.id, order=index
            )

        return channel

    def update(self, instance, validated_data):
        streams = validated_data.pop("streams", None)

        # Update standard fields
        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        instance.save()

        if streams is not None:
            # Normalize stream IDs
            normalized_ids = [
                stream.id if hasattr(stream, "id") else stream for stream in streams
            ]
            print(normalized_ids)

            # Get current mapping of stream_id -> ChannelStream
            current_links = {
                cs.stream_id: cs for cs in instance.channelstream_set.all()
            }

            # Track existing stream IDs
            existing_ids = set(current_links.keys())
            new_ids = set(normalized_ids)

            # Delete any links not in the new list
            to_remove = existing_ids - new_ids
            if to_remove:
                instance.channelstream_set.filter(stream_id__in=to_remove).delete()

            # Update or create with new order
            for order, stream_id in enumerate(normalized_ids):
                if stream_id in current_links:
                    cs = current_links[stream_id]
                    if cs.order != order:
                        cs.order = order
                        cs.save(update_fields=["order"])
                else:
                    ChannelStream.objects.create(
                        channel=instance, stream_id=stream_id, order=order
                    )

        return instance

    def validate_channel_number(self, value):
        """Ensure channel_number is properly processed as a float"""
        if value is None:
            return value

        try:
            # Ensure it's processed as a float
            return float(value)
        except (ValueError, TypeError):
            raise serializers.ValidationError(
                "Channel number must be a valid decimal number."
            )

    def validate_stream_profile(self, value):
        """Handle special case where empty/0 values mean 'use default' (null)"""
        if value == "0" or value == 0 or value == "" or value is None:
            return None
        return value  # PrimaryKeyRelatedField will handle the conversion to object

    def get_auto_created_by_name(self, obj):
        """Get the name of the M3U account that auto-created this channel."""
        if obj.auto_created_by:
            return obj.auto_created_by.name
        return None


class RecordingSerializer(serializers.ModelSerializer):
    class Meta:
        model = Recording
        fields = "__all__"
        read_only_fields = ["task_id"]

    def validate(self, data):
        from core.models import CoreSettings
        start_time = data.get("start_time")
        end_time = data.get("end_time")

        # If this is an EPG-based recording (program provided), apply global pre/post offsets
        try:
            cp = data.get("custom_properties") or {}
            is_epg_based = isinstance(cp, dict) and isinstance(cp.get("program"), (dict,))
        except Exception:
            is_epg_based = False

        if is_epg_based and start_time and end_time:
            try:
                pre_min = int(CoreSettings.get_dvr_pre_offset_minutes())
            except Exception:
                pre_min = 0
            try:
                post_min = int(CoreSettings.get_dvr_post_offset_minutes())
            except Exception:
                post_min = 0
            from datetime import timedelta
            try:
                if pre_min and pre_min > 0:
                    start_time = start_time - timedelta(minutes=pre_min)
            except Exception:
                pass
            try:
                if post_min and post_min > 0:
                    end_time = end_time + timedelta(minutes=post_min)
            except Exception:
                pass
            # write back adjusted times so scheduling uses them
            data["start_time"] = start_time
            data["end_time"] = end_time

        now = timezone.now()  # timezone-aware current time

        if end_time < now:
            raise serializers.ValidationError("End time must be in the future.")

        if start_time < now:
            # Optional: Adjust start_time if it's in the past but end_time is in the future
            data["start_time"] = now  # or: timezone.now() + timedelta(seconds=1)
        if end_time <= data["start_time"]:
            raise serializers.ValidationError("End time must be after start time.")

        return data
