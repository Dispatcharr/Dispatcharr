import json
from datetime import datetime

from rest_framework import serializers
from .models import (
    Stream,
    Channel,
    ChannelGroup,
    ChannelOverride,
    ChannelStream,
    ChannelGroupM3UAccount,
    Logo,
    ChannelProfile,
    ChannelProfileMembership,
    Recording,
    RecurringRecordingRule,
)
from apps.epg.serializers import EPGDataSerializer
from core.models import StreamProfile
from apps.epg.models import EPGData
from django.db import connection, transaction
from django.urls import reverse
from rest_framework import serializers
from django.utils import timezone
from core.utils import validate_flexible_url, build_absolute_uri_with_port


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
        # Cache-busting: append a short hash of the logo's source URL so the browser
        # fetches fresh when the logo changes (e.g., M3U logo replaced by SD logo).
        # The backend ignores the 'v' parameter — it's purely for browser cache invalidation.
        # See SD integration PR notes for context on why this was added.
        import hashlib
        url_hash = hashlib.md5((obj.url or '').encode()).hexdigest()[:8]
        base_path = reverse("api:channels:logo-cache", args=[obj.id])
        cache_url = f"{base_path}?v={url_hash}"
        request = self.context.get("request")
        if request:
            return build_absolute_uri_with_port(request, cache_url)
        return cache_url

    def get_channel_count(self, obj):
        """Get the number of channels using this logo"""
        # `channel_count` is provided as an annotation in LogoViewSet.get_queryset().
        # Fall back to a query only when serializing a single un-annotated Logo
        # (e.g. nested inside ChannelSerializer.get_logo()).
        annotated = getattr(obj, "channel_count", None)
        if annotated is not None:
            return annotated
        return obj.channels.count()

    def get_is_used(self, obj):
        """Check if this logo is used by any channels"""
        return self.get_channel_count(obj) > 0

    def get_channel_names(self, obj):
        """Get the names of channels using this logo (limited to first 5)"""
        names = []

        # When LogoViewSet.get_queryset() prefetches `channels`, iterating
        # obj.channels.all() reuses the cached set; slicing happens in Python.
        channels = list(obj.channels.all()[:5])
        for channel in channels:
            names.append(f"Channel: {channel.name}")

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
    read_only_fields = ["is_custom", "m3u_account", "stream_hash", "stream_id", "stream_chno"]

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
            "is_stale",
            "is_adult",
            "stream_profile_id",
            "is_custom",
            "channel_group",
            "stream_hash",
            "stream_stats",
            "stream_stats_updated_at",
            "stream_id",
            "stream_chno",
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
    auto_sync_channel_start = serializers.FloatField(
        allow_null=True, required=False, min_value=1
    )
    auto_sync_channel_end = serializers.FloatField(
        allow_null=True, required=False, min_value=1
    )
    custom_properties = serializers.JSONField(required=False)
    # Provider stream count for this group+account. Lets users size an
    # optional end-range without first running a blind sync.
    stream_count = serializers.SerializerMethodField()

    class Meta:
        model = ChannelGroupM3UAccount
        fields = [
            "m3u_accounts",
            "channel_group",
            "enabled",
            "auto_channel_sync",
            "auto_sync_channel_start",
            "auto_sync_channel_end",
            "custom_properties",
            "is_stale",
            "last_seen",
            "stream_count",
        ]

    def get_stream_count(self, obj):
        """
        Return the number of streams for this (m3u_account, channel_group)
        pair. A parent serializer (e.g. M3UAccountSerializer) may seed
        ``context["stream_counts"]`` with a pre-aggregated dict keyed by
        ``(m3u_account_id, channel_group_id)`` to avoid one COUNT per row;
        when present, it is used as the source of truth. The per-row
        COUNT fallback is correct for stand-alone serialization (rare,
        low-volume) and exists so direct ChannelGroupM3UAccount queries
        do not require callers to know the seeding pattern.
        """
        counts = self.context.get("stream_counts")
        if counts is not None:
            return counts.get((obj.m3u_account_id, obj.channel_group_id), 0)
        from apps.channels.models import Stream

        return Stream.objects.filter(
            m3u_account_id=obj.m3u_account_id,
            channel_group_id=obj.channel_group_id,
        ).count()

    def to_representation(self, instance):
        data = super().to_representation(instance)

        custom_props = instance.custom_properties or {}

        return data

    def validate(self, attrs):
        # Partial PATCHes only carry submitted fields; fill missing
        # start/end from the instance so the validator catches a PATCH
        # that lowers end past the existing start.
        start = attrs.get("auto_sync_channel_start")
        end = attrs.get("auto_sync_channel_end")
        if start is None and self.instance is not None:
            start = self.instance.auto_sync_channel_start
        if end is None and self.instance is not None:
            end = self.instance.auto_sync_channel_end
        if start is not None and end is not None and end < start:
            raise serializers.ValidationError(
                {
                    "auto_sync_channel_end": (
                        "End must be greater than or equal to start."
                    )
                }
            )
        return super().validate(attrs)

#
# Channel Group
#
class ChannelGroupSerializer(serializers.ModelSerializer):
    channel_count = serializers.SerializerMethodField()
    m3u_account_count = serializers.SerializerMethodField()
    m3u_accounts = ChannelGroupM3UAccountSerializer(
        many=True,
        read_only=True
    )

    class Meta:
        model = ChannelGroup
        fields = ["id", "name", "channel_count", "m3u_account_count", "m3u_accounts"]

    def get_channel_count(self, obj):
        # Use the queryset annotation when available (list path); fall back
        # to a live query for retrieve/create/update where it isn't set.
        v = getattr(obj, 'channel_count', None)
        return v if v is not None else obj.channels.count()

    def get_m3u_account_count(self, obj):
        v = getattr(obj, 'm3u_account_count', None)
        return v if v is not None else obj.m3u_accounts.count()


class ChannelProfileSerializer(serializers.ModelSerializer):
    channels = serializers.SerializerMethodField()

    class Meta:
        model = ChannelProfile
        fields = ["id", "name", "channels"]

    def get_channels(self, obj):
        # Use prefetched attr when available, fall back to a direct query.
        memberships = getattr(obj, 'enabled_memberships', None)
        if memberships is not None:
            return [m.channel_id for m in memberships]
        return list(
            ChannelProfileMembership.objects.filter(
                channel_profile=obj, enabled=True
            ).values_list('channel_id', flat=True)
        )


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
# Channel override
#
# Nullable per-field overrides resolved over the parent Channel in read
# paths. Embedded in ChannelSerializer so clients can upsert/clear in the
# same PATCH that targets direct channel fields.
class ChannelOverrideSerializer(serializers.ModelSerializer):
    # HDHR clients reject negative GuideNumber and zero is not a real
    # provider value, so reject both at the API boundary.
    channel_number = serializers.FloatField(
        allow_null=True, required=False, min_value=0.0001
    )
    channel_group_id = serializers.PrimaryKeyRelatedField(
        queryset=ChannelGroup.objects.all(),
        source="channel_group",
        allow_null=True,
        required=False,
    )
    logo_id = serializers.PrimaryKeyRelatedField(
        queryset=Logo.objects.all(),
        source="logo",
        allow_null=True,
        required=False,
    )
    epg_data_id = serializers.PrimaryKeyRelatedField(
        queryset=EPGData.objects.all(),
        source="epg_data",
        allow_null=True,
        required=False,
    )
    stream_profile_id = serializers.PrimaryKeyRelatedField(
        queryset=StreamProfile.objects.all(),
        source="stream_profile",
        allow_null=True,
        required=False,
    )

    class Meta:
        model = ChannelOverride
        fields = [
            "name",
            "channel_number",
            "channel_group_id",
            "logo_id",
            "tvg_id",
            "tvc_guide_stationid",
            "epg_data_id",
            "stream_profile_id",
        ]
        extra_kwargs = {
            "name": {"allow_null": True, "required": False},
            "tvg_id": {"allow_null": True, "required": False},
            "tvc_guide_stationid": {"allow_null": True, "required": False},
        }


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
    override = ChannelOverrideSerializer(
        required=False,
        allow_null=True,
        help_text=(
            "Per-field overrides for an auto-created channel. "
            'Send {"override": {"name": "ESPN"}} to upsert the listed '
            'fields, {"override": {"name": null}} to clear specific fields '
            'while leaving others, or {"override": null} to delete the '
            "override row entirely. Omitting the key leaves any existing "
            "override unchanged. Only valid for auto_created=True channels. "
            "Duplicate channel_number values across channels are permitted; "
            "downstream client behavior on duplicates varies by client."
        ),
    )
    source_stream = serializers.SerializerMethodField()
    # Effective fields coalesce override over channel column. Consumers
    # display these; raw fields remain in the response so the edit form
    # can show them as "Provider: X" subtext.
    effective_name = serializers.SerializerMethodField()
    effective_channel_number = serializers.SerializerMethodField()
    effective_channel_group_id = serializers.SerializerMethodField()
    effective_logo_id = serializers.SerializerMethodField()
    effective_tvg_id = serializers.SerializerMethodField()
    effective_tvc_guide_stationid = serializers.SerializerMethodField()
    effective_epg_data_id = serializers.SerializerMethodField()
    effective_stream_profile_id = serializers.SerializerMethodField()

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
            "is_adult",
            "is_catchup",
            "hidden_from_output",
            "auto_created",
            "auto_created_by",
            "auto_created_by_name",
            "override",
            "source_stream",
            "effective_name",
            "effective_channel_number",
            "effective_channel_group_id",
            "effective_logo_id",
            "effective_tvg_id",
            "effective_tvc_guide_stationid",
            "effective_epg_data_id",
            "effective_stream_profile_id",
        ]

    def _effective_value(self, obj, field_name):
        override = getattr(obj, "_channel_override_cache", None)
        if override is None:
            try:
                override = obj.override
            except ChannelOverride.DoesNotExist:
                override = None
            obj._channel_override_cache = override
        if override is not None:
            value = getattr(override, field_name, None)
            if value is not None:
                return value
        return getattr(obj, field_name, None)

    def get_effective_name(self, obj):
        return self._effective_value(obj, "name")

    def get_effective_channel_number(self, obj):
        return self._effective_value(obj, "channel_number")

    def get_effective_channel_group_id(self, obj):
        return self._effective_value(obj, "channel_group_id")

    def get_effective_logo_id(self, obj):
        return self._effective_value(obj, "logo_id")

    def get_effective_tvg_id(self, obj):
        return self._effective_value(obj, "tvg_id")

    def get_effective_tvc_guide_stationid(self, obj):
        return self._effective_value(obj, "tvc_guide_stationid")

    def get_effective_epg_data_id(self, obj):
        return self._effective_value(obj, "epg_data_id")

    def get_effective_stream_profile_id(self, obj):
        return self._effective_value(obj, "stream_profile_id")

    def get_source_stream(self, obj):
        """
        Return the originating provider stream for an auto-created channel.

        Surfaces the provider stream's name and owning M3U account so the
        frontend can render "Auto-created from: <provider> / <stream name>"
        in the channel edit form. Returns None for manual channels.
        """
        if not self.context.get("include_source_stream", False):
            return None
        if not obj.auto_created:
            return None
        # Viewset prefetches `channelstream_set` ordered by `order`, so
        # `.all()[0]` reuses the cache and returns the lowest-order entry.
        prefetched_list = list(obj.channelstream_set.all())
        if not prefetched_list:
            return None
        cs = prefetched_list[0]
        if not cs.stream:
            return None
        stream = cs.stream
        return {
            "id": stream.id,
            "name": stream.name,
            "account_id": stream.m3u_account_id,
            "account_name": getattr(stream.m3u_account, "name", None),
        }

    def to_representation(self, instance):
        include_streams = self.context.get("include_streams", False)

        if include_streams:
            self.fields["streams"] = serializers.SerializerMethodField()
            return super().to_representation(instance)
        else:
            # Read from the prefetched channelstream_set (ordered by the
            # viewset's Prefetch); chaining .order_by() rebuilds the
            # queryset and fires one SELECT per row in list responses.
            representation = super().to_representation(instance)
            if "streams" in representation:
                representation["streams"] = [
                    cs.stream_id for cs in instance.channelstream_set.all()
                ]
            return representation

    def get_logo(self, obj):
        return LogoSerializer(obj.logo).data

    def get_streams(self, obj):
        """Retrieve ordered streams for GET requests using prefetched channelstream_set."""
        ordered_streams = [
            cs.stream
            for cs in obj.channelstream_set.all()
            if cs.stream_id is not None
        ]
        return StreamSerializer(ordered_streams, many=True).data

    def create(self, validated_data):
        streams = validated_data.pop("streams", [])
        override_data = validated_data.pop("override", None)
        channel_number = validated_data.pop(
            "channel_number", Channel.get_next_available_channel_number()
        )
        validated_data["channel_number"] = channel_number

        # Auto-assign Default Group if no channel_group is specified
        if "channel_group" not in validated_data or validated_data.get("channel_group") is None:
            from apps.channels.models import ChannelGroup
            default_group, _ = ChannelGroup.objects.get_or_create(name="Default Group")
            validated_data["channel_group"] = default_group

        # Atomic wrapper keeps the channel insert and its override row
        # in the same transaction so a failure on either rolls both back.
        with transaction.atomic():
            channel = Channel.objects.create(**validated_data)

            # Add streams in the specified order
            for index, stream in enumerate(streams):
                ChannelStream.objects.create(
                    channel=channel, stream_id=stream.id, order=index
                )

            if override_data:
                # Manual channels (auto_created=False) have no provider
                # value to override; reject the override payload here so a
                # programmatic client can't write a semantically meaningless
                # row that the frontend would then surface as "Overrides
                # active".
                if not channel.auto_created:
                    raise serializers.ValidationError(
                        {
                            "override": (
                                "Cannot set override on a manual channel; "
                                "overrides only apply to auto-created channels."
                            )
                        }
                    )
                obj = ChannelOverride.objects.create(channel=channel, **override_data)
                # Drop an all-null override row; an empty override would
                # falsely surface as active in the UI.
                if not obj.has_any_override():
                    obj.delete()

        return channel

    def update(self, instance, validated_data):
        """
        PATCH handler for Channel rows. The ``override`` key carries
        per-field user overrides for auto-created channels and follows
        these rules:

        * key absent from payload: no change to existing overrides
        * ``{"override": {"field": value}}``: upsert those fields
        * ``{"override": {"field": null}}``: clear those specific fields
        * ``{"override": null}``: delete the override row entirely

        Key presence is what distinguishes "no change" from "delete";
        an explicit null means delete. Override mutations are rejected
        on manual channels (auto_created=False) since there is no
        provider value to override.
        """
        streams = validated_data.pop("streams", None)
        has_override_key = "override" in self.initial_data
        override_data = validated_data.pop("override", None)

        # Block override mutations on manual channels (no provider
        # value to override). Clearing is a tolerated no-op.
        if (
            has_override_key
            and override_data is not None
            and override_data != {}
            and not instance.auto_created
        ):
            raise serializers.ValidationError(
                {
                    "override": (
                        "Cannot set override on a manual channel; "
                        "overrides only apply to auto-created channels."
                    )
                }
            )

        # Atomic so a failure on the override row rolls back the
        # channel update too.
        with transaction.atomic():
            # Skip save() when only override keys were submitted; a
            # no-op UPDATE would bump updated_at and bust caches.
            if validated_data:
                for attr, value in validated_data.items():
                    setattr(instance, attr, value)
                instance.save()

            if has_override_key:
                if override_data is None:
                    # Explicit null: remove the override row.
                    ChannelOverride.objects.filter(channel=instance).delete()
                elif override_data == {}:
                    # Empty dict has no field intent; no-op.
                    pass
                else:
                    obj, _ = ChannelOverride.objects.update_or_create(
                        channel=instance, defaults=override_data
                    )
                    # Drop an all-null override; would falsely surface
                    # as active in the UI.
                    if not obj.has_any_override():
                        obj.delete()
                # Queryset writes leave the reverse-OneToOne cache stale;
                # clear it so to_representation reads the new state.
                try:
                    instance._state.fields_cache.pop("override", None)
                except AttributeError:
                    pass
                if hasattr(instance, "_channel_override_cache"):
                    delattr(instance, "_channel_override_cache")

            if streams is not None:
                # Normalize stream IDs
                normalized_ids = [
                    stream.id if hasattr(stream, "id") else stream for stream in streams
                ]

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
                to_update = []
                for order, stream_id in enumerate(normalized_ids):
                    if stream_id in current_links:
                        cs = current_links[stream_id]
                        if cs.order != order:
                            cs.order = order
                            to_update.append(cs)
                    else:
                        ChannelStream.objects.create(
                            channel=instance, stream_id=stream_id, order=order
                        )

                if to_update:
                    ChannelStream.objects.bulk_update(to_update, ["order"])

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

        if start_time and timezone.is_naive(start_time):
            start_time = timezone.make_aware(start_time, timezone.get_current_timezone())
            data["start_time"] = start_time
        if end_time and timezone.is_naive(end_time):
            end_time = timezone.make_aware(end_time, timezone.get_current_timezone())
            data["end_time"] = end_time

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


class RecurringRecordingRuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = RecurringRecordingRule
        fields = "__all__"
        read_only_fields = ["created_at", "updated_at"]

    def validate_days_of_week(self, value):
        if not value:
            raise serializers.ValidationError("Select at least one day of the week")
        cleaned = []
        for entry in value:
            try:
                iv = int(entry)
            except (TypeError, ValueError):
                raise serializers.ValidationError("Days of week must be integers 0-6")
            if iv < 0 or iv > 6:
                raise serializers.ValidationError("Days of week must be between 0 (Monday) and 6 (Sunday)")
            cleaned.append(iv)
        return sorted(set(cleaned))

    def validate(self, attrs):
        start = attrs.get("start_time") or getattr(self.instance, "start_time", None)
        end = attrs.get("end_time") or getattr(self.instance, "end_time", None)
        start_date = attrs.get("start_date") if "start_date" in attrs else getattr(self.instance, "start_date", None)
        end_date = attrs.get("end_date") if "end_date" in attrs else getattr(self.instance, "end_date", None)
        if start_date is None:
            existing_start = getattr(self.instance, "start_date", None)
            if existing_start is None:
                raise serializers.ValidationError("Start date is required")
        if start_date and end_date and end_date < start_date:
            raise serializers.ValidationError("End date must be on or after start date")
        if end_date is None:
            existing_end = getattr(self.instance, "end_date", None)
            if existing_end is None:
                raise serializers.ValidationError("End date is required")
        if start and end and start_date and end_date:
            start_dt = datetime.combine(start_date, start)
            end_dt = datetime.combine(end_date, end)
            if end_dt <= start_dt:
                raise serializers.ValidationError("End datetime must be after start datetime")
        elif start and end and end == start:
            raise serializers.ValidationError("End time must be different from start time")
        # Normalize empty strings to None for dates
        if attrs.get("end_date") == "":
            attrs["end_date"] = None
        if attrs.get("start_date") == "":
            attrs["start_date"] = None
        return super().validate(attrs)

    def create(self, validated_data):
        return super().create(validated_data)
