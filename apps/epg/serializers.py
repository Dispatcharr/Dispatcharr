from core.utils import validate_flexible_url
from rest_framework import serializers
from .models import EPGSource, EPGData, ProgramData
from apps.channels.models import Channel, Stream

class EPGSourceSerializer(serializers.ModelSerializer):
    epg_data_count = serializers.SerializerMethodField()
    read_only_fields = ['created_at', 'updated_at']
    url = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        validators=[validate_flexible_url]
    )

    class Meta:
        model = EPGSource
        fields = [
            'id',
            'name',
            'source_type',
            'url',
            'api_key',
            'is_active',
            'file_path',
            'refresh_interval',
            'priority',
            'status',
            'last_message',
            'created_at',
            'updated_at',
            'custom_properties',
            'epg_data_count'
        ]

    def get_epg_data_count(self, obj):
        """Return the count of EPG data entries instead of all IDs to prevent large payloads"""
        return obj.epgs.count()

class ProgramDataSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProgramData
        fields = ['id', 'start_time', 'end_time', 'title', 'sub_title', 'description', 'tvg_id']

class EPGDataSerializer(serializers.ModelSerializer):
    """
    Only returns the tvg_id and the 'name' field from EPGData.
    We assume 'name' is effectively the channel name.
    """
    read_only_fields = ['epg_source']

    class Meta:
        model = EPGData
        fields = [
            'id',
            'tvg_id',
            'name',
            'icon_url',
            'epg_source',
        ]


class ProgramSearchChannelSerializer(serializers.ModelSerializer):
    """Lightweight channel info for search results."""
    channel_group = serializers.CharField(source='channel_group.name', default=None)

    class Meta:
        model = Channel
        fields = ['id', 'name', 'channel_number', 'channel_group', 'tvg_id']


class ProgramSearchStreamSerializer(serializers.ModelSerializer):
    """Lightweight stream info for search results."""
    channel_group = serializers.CharField(source='channel_group.name', default=None)
    m3u_account = serializers.CharField(source='m3u_account.name', default=None)

    class Meta:
        model = Stream
        fields = ['id', 'name', 'channel_group', 'tvg_id', 'm3u_account']


class ProgramSearchResultSerializer(serializers.ModelSerializer):
    """Full program data with associated channels and streams for search results."""
    epg_source = serializers.CharField(source='epg.epg_source.name', default=None)
    epg_name = serializers.CharField(source='epg.name', default=None)
    epg_icon_url = serializers.URLField(source='epg.icon_url', default=None)
    channels = serializers.SerializerMethodField()
    streams = serializers.SerializerMethodField()

    class Meta:
        model = ProgramData
        fields = [
            'id', 'title', 'sub_title', 'description',
            'start_time', 'end_time', 'tvg_id', 'custom_properties',
            'epg_source', 'epg_name', 'epg_icon_url',
            'channels', 'streams',
        ]

    def get_channels(self, obj):
        channels = obj.epg.channels.all() if obj.epg else []
        return ProgramSearchChannelSerializer(channels, many=True).data

    def get_streams(self, obj):
        channels = obj.epg.channels.all() if obj.epg else []
        stream_ids = set()
        streams = []
        for ch in channels:
            for s in ch.streams.all():
                if s.id not in stream_ids:
                    stream_ids.add(s.id)
                    streams.append(s)
        return ProgramSearchStreamSerializer(streams, many=True).data
