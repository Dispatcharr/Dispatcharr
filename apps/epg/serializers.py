from core.utils import validate_flexible_url
from rest_framework import serializers
from .models import EPGSource, EPGData, ProgramData
from apps.channels.models import Channel

class EPGSourceSerializer(serializers.ModelSerializer):
    epg_data_count = serializers.SerializerMethodField()
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
            'epg_data_count'
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
        cron_expr = validated_data.pop('cron_expression', '')
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
