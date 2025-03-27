from rest_framework import serializers
from .models import EPGSource, EPGData, ProgramData
from apps.channels.models import Channel

class EPGSourceSerializer(serializers.ModelSerializer):
    epg_data_ids = serializers.SerializerMethodField()

    class Meta:
        model = EPGSource
        fields = ['id', 'name', 'source_type', 'url', 'api_key', 'is_active', 'epg_data_ids']

    def get_epg_data_ids(self, obj):
        return  list(obj.epgs.values_list('id', flat=True))

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
            'epg_source',
        ]
