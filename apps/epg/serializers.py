import re

from core.utils import validate_flexible_url
from rest_framework import serializers
from .models import EPGSource, EPGData, ProgramData
from apps.channels.models import Channel

# Matches patterns like "S12 E6", "S3E21", "S8 E8 P2/2"
_ONSCREEN_RE = re.compile(r'S(\d+)\s*E(\d+)', re.IGNORECASE)

class EPGSourceSerializer(serializers.ModelSerializer):
    epg_data_count = serializers.SerializerMethodField()
    has_channels = serializers.BooleanField(read_only=True, default=False)
    read_only_fields = ['created_at', 'updated_at']
    url = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        validators=[validate_flexible_url]
    )
    cron_expression = serializers.CharField(required=False, allow_blank=True, default='')

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
            'cron_expression',
            'priority',
            'status',
            'last_message',
            'created_at',
            'updated_at',
            'custom_properties',
            'epg_data_count',
            'has_channels',
        ]

    def get_epg_data_count(self, obj):
        """Return the count of EPG data entries instead of all IDs to prevent large payloads"""
        return obj.epgs.count()

    def to_representation(self, instance):
        data = super().to_representation(instance)
        # Derive cron_expression from the linked PeriodicTask's crontab (single source of truth)
        # But first check if we have a transient _cron_expression (from create/update before signal runs)
        cron_expr = ''
        if hasattr(instance, '_cron_expression'):
            cron_expr = instance._cron_expression
        elif instance.refresh_task_id and instance.refresh_task and instance.refresh_task.crontab:
            ct = instance.refresh_task.crontab
            cron_expr = f'{ct.minute} {ct.hour} {ct.day_of_month} {ct.month_of_year} {ct.day_of_week}'
        data['cron_expression'] = cron_expr
        return data

    def update(self, instance, validated_data):
        # Pop cron_expression before it reaches model fields
        # If not present (partial update), preserve the existing cron from the PeriodicTask
        if 'cron_expression' in validated_data:
            cron_expr = validated_data.pop('cron_expression')
        else:
            cron_expr = ''
            if instance.refresh_task_id and instance.refresh_task and instance.refresh_task.crontab:
                ct = instance.refresh_task.crontab
                cron_expr = f'{ct.minute} {ct.hour} {ct.day_of_month} {ct.month_of_year} {ct.day_of_week}'
        instance._cron_expression = cron_expr
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        return instance

    def create(self, validated_data):
        cron_expr = validated_data.pop('cron_expression', '')
        instance = EPGSource(**validated_data)
        instance._cron_expression = cron_expr
        instance.save()
        return instance

class ProgramDataSerializer(serializers.ModelSerializer):
    season = serializers.SerializerMethodField()
    episode = serializers.SerializerMethodField()

    class Meta:
        model = ProgramData
        fields = ['id', 'start_time', 'end_time', 'title', 'sub_title', 'description', 'tvg_id', 'season', 'episode']

    def _parse_onscreen(self, obj):
        """Parse season/episode from onscreen_episode string (e.g. 'S12 E6')."""
        onscreen = (obj.custom_properties or {}).get('onscreen_episode', '')
        match = _ONSCREEN_RE.search(onscreen)
        if match:
            return int(match.group(1)), int(match.group(2))
        return None, None

    def get_season(self, obj):
        if obj.custom_properties:
            season = obj.custom_properties.get('season')
            if season is not None:
                return season
            season, _ = self._parse_onscreen(obj)
            return season
        return None

    def get_episode(self, obj):
        if obj.custom_properties:
            episode = obj.custom_properties.get('episode')
            if episode is not None:
                return episode
            _, episode = self._parse_onscreen(obj)
            return episode
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
            'icon_url',
            'epg_source',
        ]
