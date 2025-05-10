from rest_framework import serializers
from .models import Stream, Channel, ChannelGroup, ChannelStream, ChannelGroupM3UAccount, Logo, ChannelProfile, ChannelProfileMembership, Recording
from apps.epg.serializers import EPGDataSerializer
from core.models import StreamProfile
from apps.epg.models import EPGData
from django.urls import reverse
from rest_framework import serializers
from django.utils import timezone

class LogoSerializer(serializers.ModelSerializer):
    cache_url = serializers.SerializerMethodField()

    class Meta:
        model = Logo
        fields = ['id', 'name', 'url', 'cache_url']

    def get_cache_url(self, obj):
        # return f"/api/channels/logos/{obj.id}/cache/"
        request = self.context.get('request')
        if request:
            return request.build_absolute_uri(reverse('api:channels:logo-cache', args=[obj.id]))
        return reverse('api:channels:logo-cache', args=[obj.id])

#
# Stream
#
class StreamSerializer(serializers.ModelSerializer):
    stream_profile_id = serializers.PrimaryKeyRelatedField(
        queryset=StreamProfile.objects.all(),
        source='stream_profile',
        allow_null=True,
        required=False
    )
    read_only_fields = ['is_custom', 'm3u_account', 'stream_hash']

    class Meta:
        model = Stream
        fields = [
            'id',
            'name',
            'url',
            'm3u_account',  # Uncomment if using M3U fields
            'logo_url',
            'tvg_id',
            'local_file',
            'current_viewers',
            'updated_at',
            'last_seen',
            'stream_profile_id',
            'is_custom',
            'channel_group',
            'stream_hash',
        ]

    def get_fields(self):
        fields = super().get_fields()

        # Unable to edit specific properties if this stream was created from an M3U account
        if self.instance and getattr(self.instance, 'm3u_account', None) and not self.instance.is_custom:
            fields['id'].read_only = True
            fields['name'].read_only = True
            fields['url'].read_only = True
            fields['m3u_account'].read_only = True
            fields['tvg_id'].read_only = True
            fields['channel_group'].read_only = True


        return fields


#
# Channel Group
#
class ChannelGroupSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChannelGroup
        fields = ['id', 'name']

class ChannelProfileSerializer(serializers.ModelSerializer):
    channels = serializers.SerializerMethodField()

    class Meta:
        model = ChannelProfile
        fields = ['id', 'name', 'channels']

    def get_channels(self, obj):
        memberships = ChannelProfileMembership.objects.filter(channel_profile=obj, enabled=True)
        return [
            membership.channel.id
            for membership in memberships
        ]

class ChannelProfileMembershipSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChannelProfileMembership
        fields = ['channel', 'enabled']

class ChanneProfilelMembershipUpdateSerializer(serializers.Serializer):
    channel_id = serializers.IntegerField()  # Ensure channel_id is an integer
    enabled = serializers.BooleanField()

class BulkChannelProfileMembershipSerializer(serializers.Serializer):
    channels = serializers.ListField(
        child=ChanneProfilelMembershipUpdateSerializer(),  # Use the nested serializer
        allow_empty=False
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
    channel_number = serializers.FloatField(allow_null=True, required=False)
    channel_group_id = serializers.PrimaryKeyRelatedField(
        queryset=ChannelGroup.objects.all(),
        source="channel_group",
        required=False
    )
    epg_data_id = serializers.PrimaryKeyRelatedField(
        queryset=EPGData.objects.all(),
        source="epg_data",
        required=False,
        allow_null=True,
    )

    stream_profile_id = serializers.PrimaryKeyRelatedField(
        queryset=StreamProfile.objects.all(),
        source='stream_profile',
        allow_null=True,
        required=False
    )

    streams = serializers.PrimaryKeyRelatedField(queryset=Stream.objects.all(), many=True, required=False)

    logo_id = serializers.PrimaryKeyRelatedField(
        queryset=Logo.objects.all(),
        source='logo',
        allow_null=True,
        required=False,
    )

    class Meta:
        model = Channel
        fields = [
            'id',
            'channel_number',
            'name',
            'channel_group_id',
            'tvg_id',
            'tvc_guide_stationid',
            'epg_data_id',
            'streams',
            'stream_profile_id',
            'uuid',
            'logo_id',
        ]

    def to_representation(self, instance):
        include_streams = self.context.get('include_streams', False)

        if include_streams:
            self.fields['streams'] = serializers.SerializerMethodField()

        return super().to_representation(instance)

    def get_logo(self, obj):
        return LogoSerializer(obj.logo).data

    def get_streams(self, obj):
        """Retrieve ordered stream IDs for GET requests."""
        return StreamSerializer(obj.streams.all().order_by('channelstream__order'), many=True).data

    def create(self, validated_data):
        streams = validated_data.pop('streams', [])
        channel_number = validated_data.pop('channel_number', Channel.get_next_available_channel_number())
        validated_data["channel_number"] = channel_number
        channel = Channel.objects.create(**validated_data)

        # Add streams in the specified order
        for index, stream in enumerate(streams):
            ChannelStream.objects.create(channel=channel, stream_id=stream.id, order=index)

        return channel

    def update(self, instance, validated_data):
        streams = validated_data.pop('streams', None)

        # Update standard fields
        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        instance.save()

        if streams is not None:
            # Normalize stream IDs
            normalized_ids = [
                stream.id if hasattr(stream, "id") else stream
                for stream in streams
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
                        channel=instance,
                        stream_id=stream_id,
                        order=order
                    )

        return instance


    def validate_stream_profile(self, value):
        """Handle special case where empty/0 values mean 'use default' (null)"""
        if value == '0' or value == 0 or value == '' or value is None:
            return None
        return value  # PrimaryKeyRelatedField will handle the conversion to object

class ChannelGroupM3UAccountSerializer(serializers.ModelSerializer):
    enabled = serializers.BooleanField()

    class Meta:
        model = ChannelGroupM3UAccount
        fields = ['id', 'channel_group', 'enabled']

    # Optionally, if you only need the id of the ChannelGroup, you can customize it like this:
    # channel_group = serializers.PrimaryKeyRelatedField(queryset=ChannelGroup.objects.all())


class RecordingSerializer(serializers.ModelSerializer):
    class Meta:
        model = Recording
        fields = '__all__'
        read_only_fields = ['task_id']

    def validate(self, data):
        start_time = data.get('start_time')
        end_time = data.get('end_time')

        now = timezone.now()  # timezone-aware current time

        if end_time < now:
            raise serializers.ValidationError("End time must be in the future.")

        if start_time < now:
            # Optional: Adjust start_time if it's in the past but end_time is in the future
            data['start_time'] = now  # or: timezone.now() + timedelta(seconds=1)
        if end_time <= data['start_time']:
            raise serializers.ValidationError("End time must be after start time.")

        return data
