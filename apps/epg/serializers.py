from rest_framework import serializers
from .models import EPGSource, EPGData, ProgramData
from apps.channels.models import Channel

class EPGSourceSerializer(serializers.ModelSerializer):
    epg_data_ids = serializers.SerializerMethodField()
    read_only_fields = ['created_at', 'updated_at']

    class Meta:
        model = EPGSource
        fields = [
            'id',
            'name',
            'source_type',
            'url',
            'api_key',
            'username',
            'is_active',
            'file_path',
            'refresh_interval',
            'status',
            'last_message',
            'created_at',
            'updated_at',
            'epg_data_ids'
        ]

    def get_epg_data_ids(self, obj):
        return list(obj.epgs.values_list('id', flat=True))

class ProgramDataSerializer(serializers.ModelSerializer):
    epg = serializers.SerializerMethodField()
    
    class Meta:
        model = ProgramData
        fields = ['id', 'epg', 'start_time', 'end_time', 'title', 'sub_title', 'description', 'tvg_id', 'custom_properties']
    
    def get_epg(self, obj):
        """Return EPG data in the format expected by the TV guide frontend"""
        if obj.epg:
            return {
                'tvg_id': obj.epg.tvg_id,
                'name': obj.epg.name
            }
        return None

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
            'epg_source',
            'logo_url',
        ]
