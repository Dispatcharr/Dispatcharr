from apps.epg.sd_utils import (
    sd_clear_cached_token,
    sd_credential_fingerprint,
)
from apps.epg.utils import sd_poster_proxy_path
from core.utils import validate_flexible_url, build_absolute_uri_with_port
from rest_framework import serializers
from .models import EPGSource, EPGData, ProgramData
from apps.channels.models import Channel, Stream

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
            'username',
            'password',
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
        extra_kwargs = {'password': {'write_only': True}}

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
        prior_fp = sd_credential_fingerprint(instance.username, instance.password)
        for attr, value in validated_data.items():
            if attr == 'password' and not value:
                continue
            setattr(instance, attr, value)
        instance.save()
        # Drop any Redis SD session tied to the previous username/password so
        # poster traffic cannot keep using another account's token.
        if prior_fp != sd_credential_fingerprint(instance.username, instance.password):
            sd_clear_cached_token(instance.id)
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

        # Content advisory (SD)
        data['content_advisory'] = cp.get('content_advisory') or []

        # Full content ratings array (SD — all regional ratings)
        data['content_ratings'] = cp.get('content_ratings') or []

        # Sports event details (SD)
        data['event_details'] = cp.get('event_details')

        # Runtime (duration without commercials)
        length = cp.get('length') or {}
        data['runtime'] = length.get('value') if length else None
        data['runtime_units'] = length.get('units') if length else None

        # External IDs
        data['imdb_id'] = cp.get('imdb.com_id')
        data['tmdb_id'] = cp.get('themoviedb.org_id')
        data['tvdb_id'] = cp.get('thetvdb.com_id')

        # Images
        data['icon'] = cp.get('icon')
        data['images'] = cp.get('images') or []

        # SD poster: expose as absolute proxy URL so frontend/img tags never need SD auth.
        # ``?v=`` tracks the sd_icon URI so nginx/browser caches bust when artwork changes.
        sd_icon = cp.get('sd_icon')
        if sd_icon:
            poster_path = sd_poster_proxy_path(obj.id, sd_icon)
            request = self.context.get('request')
            if request:
                data['poster_url'] = build_absolute_uri_with_port(request, poster_path)
            else:
                data['poster_url'] = poster_path
        else:
            data['poster_url'] = None

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

    def _accessible_channels(self, obj):
        """Return prefetched channels filtered to those the requesting user can access."""
        channels = list(obj.epg.channels.all()) if obj.epg else []
        user = self.context.get('user')
        if user is None or user.user_level >= 10:
            return channels
        custom_props = user.custom_properties or {}
        hide_adult = custom_props.get('hide_adult_content', False)
        return [
            ch for ch in channels
            if ch.user_level <= user.user_level and (not hide_adult or not ch.is_adult)
        ]

    def get_channels(self, obj):
        fields = self.context.get('fields')
        if fields is not None and 'channels' not in fields:
            return []
        return ProgramSearchChannelSerializer(self._accessible_channels(obj), many=True).data

    def get_streams(self, obj):
        fields = self.context.get('fields')
        if fields is not None and 'streams' not in fields:
            return []
        stream_ids = set()
        streams = []
        for ch in self._accessible_channels(obj):
            for s in ch.streams.all():
                if s.id not in stream_ids:
                    stream_ids.add(s.id)
                    streams.append(s)
        return ProgramSearchStreamSerializer(streams, many=True).data
