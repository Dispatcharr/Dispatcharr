import re

from core.utils import validate_flexible_url
from rest_framework import serializers
from .models import EPGSource, EPGData, ProgramData
from .utils import extract_season_episode
from apps.channels.models import Channel

# Live-event inference patterns
_PPV_RE = re.compile(r'\bPPV\d*\b', re.IGNORECASE)
_VS_RE = re.compile(r'\bvs\.?\b|\bversus\b', re.IGNORECASE)
_LIVE_TIME_RE = re.compile(r'\d{1,2}:\d{2}\s*(?:AM|PM)', re.IGNORECASE)
_SCHEDULED_EVENT_RE = re.compile(r'@\s+\w{3,}\s+\d{1,2}\s+\d{1,2}:\d{2}\s*(?:AM|PM)', re.IGNORECASE)


def infer_is_live(title, epg_name=None, dd_progid=None):
    """Infer LIVE status from title/channel patterns when provider omits <live> flag."""
    text = title or ''
    # Rule 1: PPV in title or EPG name
    if _PPV_RE.search(text) or (epg_name and _PPV_RE.search(epg_name)):
        return True
    has_vs = bool(_VS_RE.search(text))
    has_time = bool(_LIVE_TIME_RE.search(text))
    # Rule 2: "vs" + embedded time
    if has_vs and has_time:
        return True
    # Rule 3: dd_progid=SP + matchup or time
    if dd_progid and str(dd_progid)[:2].upper() == 'SP' and (has_vs or has_time):
        return True
    # Rule 4: "@ Month Day Time" scheduling notation (e.g. "@ Mar 08 10:00 AM ET")
    if _SCHEDULED_EVENT_RE.search(text):
        return True
    return False


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
    """Querysets must use select_related('epg') to avoid N+1 on is_live inference."""

    class Meta:
        model = ProgramData
        fields = ['id', 'start_time', 'end_time', 'title', 'sub_title', 'description', 'tvg_id']

    def to_representation(self, obj):
        data = super().to_representation(obj)
        cp = obj.custom_properties or {}
        season, episode = extract_season_episode(cp, description=obj.description)
        data['season'] = season
        data['episode'] = episode
        data['is_new'] = bool(cp.get('new'))
        data['is_live'] = bool(cp.get('live')) or infer_is_live(
            obj.title, epg_name=obj.epg.name if obj.epg_id else None,
            dd_progid=cp.get('dd_progid'))
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
