from core.utils import validate_flexible_url
from rest_framework import serializers
from .models import EPGSource, EPGData, ProgramData
from apps.channels.models import Channel

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
            'username',
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

    class Meta:
        model = ProgramData
        fields = ['id', 'start_time', 'end_time', 'title', 'sub_title', 'description', 'tvg_id']

    def to_representation(self, obj):
        data = super().to_representation(obj)
        cp = obj.custom_properties or {}
        data['season'] = cp.get('season')
        data['episode'] = cp.get('episode')
        data['is_new'] = bool(cp.get('new'))
        data['is_live'] = bool(cp.get('live'))
        data['is_premiere'] = bool(cp.get('premiere'))
        premiere_text = cp.get('premiere_text', '')
        data['is_finale'] = bool(premiere_text and 'finale' in premiere_text.lower())
        return data

class ProgramDetailSerializer(ProgramDataSerializer):
    """Rich serializer for program detail view — extends slim serializer with full custom_properties."""

    def to_representation(self, obj):
        data = super().to_representation(obj)
        cp = obj.custom_properties or {}

        # Categories
        data['categories'] = cp.get('categories') or []

        # Content rating
        data['rating'] = cp.get('rating')
        data['rating_system'] = cp.get('rating_system')

        # Star ratings
        data['star_ratings'] = cp.get('star_ratings') or []

        # Credits — flatten from XMLTV structure
        credits = cp.get('credits') or {}
        data['credits'] = {
            'actors': credits.get('actor') or [],
            'directors': credits.get('director') or [],
            'writers': credits.get('writer') or [],
            'producers': credits.get('producer') or [],
            'presenters': credits.get('presenter') or [],
        }

        # Video/audio quality
        video = cp.get('video') or {}
        data['video_quality'] = video.get('quality')
        data['aspect_ratio'] = video.get('aspect')

        audio = cp.get('audio') or {}
        data['stereo'] = audio.get('stereo')

        # Previously shown (rerun)
        data['is_previously_shown'] = bool(cp.get('previously_shown'))

        # Geographic/language
        data['country'] = cp.get('country')
        data['language'] = cp.get('language')

        # Dates
        data['production_date'] = cp.get('date')
        previously_shown = cp.get('previously_shown_details') or {}
        data['original_air_date'] = previously_shown.get('start')

        # External IDs
        data['imdb_id'] = cp.get('imdb.com_id')
        data['tmdb_id'] = cp.get('themoviedb.org_id')
        data['tvdb_id'] = cp.get('thetvdb.com_id')

        # Images
        data['icon'] = cp.get('icon')
        data['images'] = cp.get('images') or []

        return data


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
