from rest_framework import serializers
from core.utils import truncate_with_warning
from .image_proxy import vodlogo_cache_url
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from .models import (
    Series, VODCategory, Movie, Episode, VODLogo,
    M3USeriesRelation, M3UMovieRelation, M3UEpisodeRelation, M3UVODCategoryRelation
)
from apps.m3u.serializers import M3UAccountSerializer


class QualityInfoSerializer(serializers.Serializer):
    """Optional quality metadata derived from provider/custom properties."""
    quality = serializers.CharField(required=False, allow_blank=True)
    resolution = serializers.CharField(required=False, allow_blank=True)
    bitrate = serializers.CharField(required=False, allow_blank=True)


class VODProviderAccountSerializer(serializers.Serializer):
    """Slim M3U account payload embedded in provider-info responses."""
    id = serializers.IntegerField()
    name = serializers.CharField()
    account_type = serializers.CharField()


class VODLogoSerializer(serializers.ModelSerializer):
    name = serializers.CharField()
    cache_url = serializers.SerializerMethodField()
    movie_count = serializers.SerializerMethodField(
        help_text="Number of movies using this logo"
    )
    series_count = serializers.SerializerMethodField(
        help_text="Number of series using this logo"
    )
    is_used = serializers.SerializerMethodField(
        help_text="Whether this logo is used by any movie or series"
    )
    item_names = serializers.SerializerMethodField(
        help_text="List of movies and series using this logo (limited to 10)"
    )

    class Meta:
        model = VODLogo
        fields = ["id", "name", "url", "cache_url", "movie_count", "series_count", "is_used", "item_names"]

    def validate_name(self, value):
        return truncate_with_warning(
            value,
            max_length=VODLogo._meta.get_field("name").max_length,
            label="Logo name",
        )

    def validate_url(self, value):
        """Validate that the URL is unique for creation or update"""
        if self.instance and self.instance.url == value:
            return value

        if VODLogo.objects.filter(url=value).exists():
            raise serializers.ValidationError("A VOD logo with this URL already exists.")

        return value

    def create(self, validated_data):
        """Handle logo creation with proper URL validation"""
        return VODLogo.objects.create(**validated_data)

    def update(self, instance, validated_data):
        """Handle logo updates"""
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        return instance

    @extend_schema_field(OpenApiTypes.URI)
    def get_cache_url(self, obj):
        return vodlogo_cache_url(self.context.get("request"), obj)

    @extend_schema_field(OpenApiTypes.INT)
    def get_movie_count(self, obj):
        """Get the number of movies using this logo"""
        return obj.movie.count() if hasattr(obj, 'movie') else 0

    @extend_schema_field(OpenApiTypes.INT)
    def get_series_count(self, obj):
        """Get the number of series using this logo"""
        return obj.series.count() if hasattr(obj, 'series') else 0

    @extend_schema_field(OpenApiTypes.BOOL)
    def get_is_used(self, obj):
        """Check if this logo is used by any movies or series"""
        return (hasattr(obj, 'movie') and obj.movie.exists()) or (hasattr(obj, 'series') and obj.series.exists())

    @extend_schema_field(serializers.ListField(child=serializers.CharField()))
    def get_item_names(self, obj):
        """Get the list of movies and series using this logo"""
        names = []

        if hasattr(obj, 'movie'):
            for movie in obj.movie.all()[:10]:  # Limit to 10 items for performance
                names.append(f"Movie: {movie.name}")

        if hasattr(obj, 'series'):
            for series in obj.series.all()[:10]:  # Limit to 10 items for performance
                names.append(f"Series: {series.name}")

        return names


class M3UVODCategoryRelationSerializer(serializers.ModelSerializer):
    category = serializers.IntegerField(source="category.id")
    m3u_account = serializers.IntegerField(source="m3u_account.id")

    class Meta:
        model = M3UVODCategoryRelation
        fields = ["category", "m3u_account", "enabled"]


class VODCategorySerializer(serializers.ModelSerializer):
    category_type_display = serializers.CharField(source='get_category_type_display', read_only=True)
    m3u_accounts = M3UVODCategoryRelationSerializer(many=True, source="m3u_relations", read_only=True)

    class Meta:
        model = VODCategory
        fields = [
            "id",
            "name",
            "category_type",
            "category_type_display",
            "m3u_accounts",
        ]


class SeriesSerializer(serializers.ModelSerializer):
    logo = VODLogoSerializer(read_only=True)
    episode_count = serializers.SerializerMethodField(
        help_text="Number of episodes in the series"
    )
    custom_properties = serializers.JSONField(required=False, allow_null=True)

    class Meta:
        model = Series
        fields = '__all__'

    @extend_schema_field(OpenApiTypes.INT)
    def get_episode_count(self, obj):
        return obj.episodes.count()


class MovieSerializer(serializers.ModelSerializer):
    logo = VODLogoSerializer(read_only=True)
    custom_properties = serializers.JSONField(required=False, allow_null=True)

    class Meta:
        model = Movie
        fields = '__all__'


class EpisodeSerializer(serializers.ModelSerializer):
    series = SeriesSerializer(read_only=True)
    custom_properties = serializers.JSONField(required=False, allow_null=True)

    class Meta:
        model = Episode
        fields = '__all__'


class M3USeriesRelationSerializer(serializers.ModelSerializer):
    series = SeriesSerializer(read_only=True)
    category = VODCategorySerializer(read_only=True)
    m3u_account = M3UAccountSerializer(read_only=True)
    custom_properties = serializers.JSONField(required=False, allow_null=True)

    class Meta:
        model = M3USeriesRelation
        fields = '__all__'


class M3UMovieRelationSerializer(serializers.ModelSerializer):
    movie = MovieSerializer(read_only=True)
    category = VODCategorySerializer(read_only=True)
    m3u_account = M3UAccountSerializer(read_only=True)
    quality_info = serializers.SerializerMethodField()
    custom_properties = serializers.JSONField(required=False, allow_null=True)

    class Meta:
        model = M3UMovieRelation
        fields = '__all__'

    @extend_schema_field(QualityInfoSerializer(allow_null=True))
    def get_quality_info(self, obj):
        """Extract quality information from various sources"""
        quality_info = {}

        # 1. Check custom_properties first
        if obj.custom_properties:
            if obj.custom_properties.get('quality'):
                quality_info['quality'] = obj.custom_properties['quality']
                return quality_info
            elif obj.custom_properties.get('resolution'):
                quality_info['resolution'] = obj.custom_properties['resolution']
                return quality_info

        # 2. Try to get detailed info from the movie if available
        movie = obj.movie
        if hasattr(movie, 'video') and movie.video:
            video_data = movie.video
            if isinstance(video_data, dict) and 'width' in video_data and 'height' in video_data:
                width = video_data['width']
                height = video_data['height']
                quality_info['resolution'] = f"{width}x{height}"

                # Convert to common quality names (prioritize width for ultrawide/cinematic content)
                if width >= 3840:
                    quality_info['quality'] = '4K'
                elif width >= 1920:
                    quality_info['quality'] = '1080p'
                elif width >= 1280:
                    quality_info['quality'] = '720p'
                elif width >= 854:
                    quality_info['quality'] = '480p'
                else:
                    quality_info['quality'] = f"{width}x{height}"
                return quality_info

        # 3. Extract from movie name/title
        if movie and movie.name:
            name = movie.name
            if '4K' in name or '2160p' in name:
                quality_info['quality'] = '4K'
                return quality_info
            elif '1080p' in name or 'FHD' in name:
                quality_info['quality'] = '1080p'
                return quality_info
            elif '720p' in name or 'HD' in name:
                quality_info['quality'] = '720p'
                return quality_info
            elif '480p' in name:
                quality_info['quality'] = '480p'
                return quality_info

        # 4. Try bitrate as last resort
        if hasattr(movie, 'bitrate') and movie.bitrate and movie.bitrate > 0:
            bitrate = movie.bitrate
            if bitrate >= 6000:
                quality_info['quality'] = '4K'
            elif bitrate >= 3000:
                quality_info['quality'] = '1080p'
            elif bitrate >= 1500:
                quality_info['quality'] = '720p'
            else:
                quality_info['bitrate'] = f"{round(bitrate/1000)}Mbps"
            return quality_info

        # 5. Fallback - no quality info available
        return None


class M3UEpisodeRelationSerializer(serializers.ModelSerializer):
    episode = EpisodeSerializer(read_only=True)
    m3u_account = M3UAccountSerializer(read_only=True)
    quality_info = serializers.SerializerMethodField()
    custom_properties = serializers.JSONField(required=False, allow_null=True)

    class Meta:
        model = M3UEpisodeRelation
        fields = '__all__'

    @extend_schema_field(QualityInfoSerializer(allow_null=True))
    def get_quality_info(self, obj):
        """Extract quality information from various sources"""
        quality_info = {}

        # 1. Check custom_properties first
        if obj.custom_properties:
            if obj.custom_properties.get('quality'):
                quality_info['quality'] = obj.custom_properties['quality']
                return quality_info
            elif obj.custom_properties.get('resolution'):
                quality_info['resolution'] = obj.custom_properties['resolution']
                return quality_info

        # 2. Try to get detailed info from the episode if available
        episode = obj.episode
        if hasattr(episode, 'video') and episode.video:
            video_data = episode.video
            if isinstance(video_data, dict) and 'width' in video_data and 'height' in video_data:
                width = video_data['width']
                height = video_data['height']
                quality_info['resolution'] = f"{width}x{height}"

                # Convert to common quality names (prioritize width for ultrawide/cinematic content)
                if width >= 3840:
                    quality_info['quality'] = '4K'
                elif width >= 1920:
                    quality_info['quality'] = '1080p'
                elif width >= 1280:
                    quality_info['quality'] = '720p'
                elif width >= 854:
                    quality_info['quality'] = '480p'
                else:
                    quality_info['quality'] = f"{width}x{height}"
                return quality_info

        # 3. Extract from episode name/title
        if episode and episode.name:
            name = episode.name
            if '4K' in name or '2160p' in name:
                quality_info['quality'] = '4K'
                return quality_info
            elif '1080p' in name or 'FHD' in name:
                quality_info['quality'] = '1080p'
                return quality_info
            elif '720p' in name or 'HD' in name:
                quality_info['quality'] = '720p'
                return quality_info
            elif '480p' in name:
                quality_info['quality'] = '480p'
                return quality_info

        # 4. Try bitrate as last resort
        if hasattr(episode, 'bitrate') and episode.bitrate and episode.bitrate > 0:
            bitrate = episode.bitrate
            if bitrate >= 6000:
                quality_info['quality'] = '4K'
            elif bitrate >= 3000:
                quality_info['quality'] = '1080p'
            elif bitrate >= 1500:
                quality_info['quality'] = '720p'
            else:
                quality_info['bitrate'] = f"{round(bitrate/1000)}Mbps"
            return quality_info

        # 5. Fallback - no quality info available
        return None


class EnhancedSeriesSerializer(serializers.ModelSerializer):
    """Enhanced serializer for series with provider information"""
    logo = VODLogoSerializer(read_only=True)
    providers = M3USeriesRelationSerializer(source='m3u_relations', many=True, read_only=True)
    episode_count = serializers.SerializerMethodField(
        help_text="Number of episodes in the series"
    )
    custom_properties = serializers.JSONField(required=False, allow_null=True)

    class Meta:
        model = Series
        fields = '__all__'

    @extend_schema_field(OpenApiTypes.INT)
    def get_episode_count(self, obj):
        return obj.episodes.count()


class EpisodeWithProvidersSerializer(EpisodeSerializer):
    """Episode payload with nested provider relations (series episodes action)."""
    providers = M3UEpisodeRelationSerializer(
        source='m3u_relations', many=True, read_only=True
    )


class MovieProviderInfoSerializer(serializers.Serializer):
    """Response shape for GET /api/vod/movies/{id}/provider-info/."""
    id = serializers.IntegerField()
    uuid = serializers.UUIDField()
    stream_id = serializers.CharField()
    name = serializers.CharField()
    o_name = serializers.CharField(allow_blank=True)
    description = serializers.CharField(allow_blank=True, allow_null=True)
    plot = serializers.CharField(allow_blank=True, allow_null=True)
    year = serializers.IntegerField(allow_null=True)
    release_date = serializers.CharField(allow_blank=True)
    genre = serializers.CharField(allow_blank=True)
    director = serializers.CharField(allow_blank=True)
    actors = serializers.CharField(allow_blank=True)
    country = serializers.CharField(allow_blank=True)
    rating = serializers.CharField(allow_blank=True, allow_null=True)
    tmdb_id = serializers.CharField(allow_blank=True, allow_null=True)
    imdb_id = serializers.CharField(allow_blank=True, allow_null=True)
    youtube_trailer = serializers.CharField(allow_blank=True)
    duration_secs = serializers.IntegerField(allow_null=True)
    age = serializers.CharField(allow_blank=True)
    backdrop_path = serializers.JSONField()
    cover = serializers.CharField(allow_blank=True)
    cover_big = serializers.CharField(allow_blank=True)
    movie_image = serializers.CharField(allow_blank=True)
    bitrate = serializers.IntegerField()
    video = serializers.JSONField()
    audio = serializers.JSONField()
    container_extension = serializers.CharField()
    direct_source = serializers.CharField(allow_blank=True)
    category_id = serializers.CharField(allow_blank=True)
    added = serializers.CharField(allow_blank=True)
    m3u_account = VODProviderAccountSerializer()


class SeriesProviderInfoCoverSerializer(serializers.Serializer):
    # Proxy path may set id to null when cover is relation artwork without a VODLogo.
    id = serializers.IntegerField(allow_null=True)
    url = serializers.CharField()
    cache_url = serializers.CharField(required=False, allow_blank=True)
    name = serializers.CharField()


class SeriesProviderInfoEpisodeSeriesSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()


class SeriesProviderInfoEpisodeSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    uuid = serializers.UUIDField()
    name = serializers.CharField()
    title = serializers.CharField()
    episode_number = serializers.IntegerField(allow_null=True)
    season_number = serializers.IntegerField(allow_null=True)
    description = serializers.CharField(allow_blank=True, allow_null=True)
    air_date = serializers.DateField(allow_null=True)
    plot = serializers.CharField(allow_blank=True, allow_null=True)
    duration_secs = serializers.IntegerField(allow_null=True)
    rating = serializers.CharField(allow_blank=True, allow_null=True)
    tmdb_id = serializers.CharField(allow_blank=True, allow_null=True)
    imdb_id = serializers.CharField(allow_blank=True, allow_null=True)
    movie_image = serializers.CharField(allow_blank=True)
    container_extension = serializers.CharField()
    type = serializers.CharField()
    series = SeriesProviderInfoEpisodeSeriesSerializer()


class SeriesProviderInfoSerializer(serializers.Serializer):
    """Response shape for GET /api/vod/series/{id}/provider-info/."""
    id = serializers.IntegerField()
    series_id = serializers.CharField()
    name = serializers.CharField()
    description = serializers.CharField(allow_blank=True, allow_null=True)
    year = serializers.IntegerField(allow_null=True)
    genre = serializers.CharField(allow_blank=True, allow_null=True)
    rating = serializers.CharField(allow_blank=True, allow_null=True)
    tmdb_id = serializers.CharField(allow_blank=True, allow_null=True)
    imdb_id = serializers.CharField(allow_blank=True, allow_null=True)
    category_id = serializers.IntegerField(allow_null=True)
    category_name = serializers.CharField(allow_null=True)
    cover = SeriesProviderInfoCoverSerializer(allow_null=True)
    backdrop_path = serializers.JSONField(required=False)
    last_refreshed = serializers.DateTimeField()
    custom_properties = serializers.JSONField(allow_null=True)
    m3u_account = VODProviderAccountSerializer()
    episodes_fetched = serializers.BooleanField()
    detailed_fetched = serializers.BooleanField()
    # Keys are season numbers as strings; values are episode lists.
    episodes = serializers.DictField(
        child=SeriesProviderInfoEpisodeSerializer(many=True),
        required=False,
    )


class UnifiedContentLogoSerializer(serializers.Serializer):
    """Logo shape returned by the unified content SQL list endpoint."""
    id = serializers.IntegerField()
    name = serializers.CharField(allow_null=True)
    url = serializers.CharField(allow_null=True)
    cache_url = serializers.CharField()
    movie_count = serializers.IntegerField()
    series_count = serializers.IntegerField()
    is_used = serializers.BooleanField()


class UnifiedContentItemSerializer(serializers.Serializer):
    """Single row from GET /api/vod/all/."""
    id = serializers.IntegerField()
    uuid = serializers.CharField()
    name = serializers.CharField()
    description = serializers.CharField(allow_blank=True)
    year = serializers.IntegerField(allow_null=True)
    # Unified list coerces rating to float; standard Movie/Series keep string.
    rating = serializers.FloatField()
    genre = serializers.CharField(allow_blank=True)
    duration = serializers.IntegerField(allow_null=True)
    created_at = serializers.DateTimeField(allow_null=True)
    updated_at = serializers.DateTimeField(allow_null=True)
    custom_properties = serializers.JSONField()
    logo = UnifiedContentLogoSerializer(allow_null=True)
    content_type = serializers.ChoiceField(choices=["movie", "series"])


class UnifiedContentListSerializer(serializers.Serializer):
    """Paginated payload from GET /api/vod/all/ (standard next/previous page URIs)."""
    count = serializers.IntegerField()
    next = serializers.CharField(allow_null=True)
    previous = serializers.CharField(allow_null=True)
    results = UnifiedContentItemSerializer(many=True)


class VODLogoBulkDeleteRequestSerializer(serializers.Serializer):
    logo_ids = serializers.ListField(
        child=serializers.IntegerField(),
        help_text="IDs of VOD logos to delete",
    )


class VODLogoBulkDeleteResponseSerializer(serializers.Serializer):
    deleted_count = serializers.IntegerField()
    message = serializers.CharField()


class VODLogoCleanupResponseSerializer(serializers.Serializer):
    deleted_count = serializers.IntegerField()
    deleted_logos = serializers.ListField(child=serializers.CharField())
    message = serializers.CharField()
