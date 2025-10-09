from django.urls import reverse
from rest_framework import serializers
from .models import (
    Series, VODCategory, Movie, Episode,
    M3USeriesRelation, M3UMovieRelation, M3UEpisodeRelation, M3UVODCategoryRelation
)
from apps.channels.serializers import LogoSerializer
from apps.m3u.serializers import M3UAccountSerializer


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

def _build_logo_cache_url(request, logo_id):
    if not logo_id:
        return None
    cache_path = reverse("api:channels:logo-cache", args=[logo_id])
    if request:
        return request.build_absolute_uri(cache_path)
    return cache_path


class SeriesSerializer(serializers.ModelSerializer):
    logo = LogoSerializer(read_only=True)
    episode_count = serializers.SerializerMethodField()
    library_sources = serializers.SerializerMethodField()
    series_image = serializers.SerializerMethodField()
    backdrop_path = serializers.SerializerMethodField()

    class Meta:
        model = Series
        fields = '__all__'

    def get_episode_count(self, obj):
        return obj.episodes.count()

    def get_library_sources(self, obj):
        sources = []
        for item in obj.library_items.select_related("library").filter(library__use_as_vod_source=True):
            library = item.library
            sources.append(
                {
                    "library_id": library.id,
                    "library_name": library.name,
                    "media_item_id": item.id,
                }
        )
        return sources

    def get_series_image(self, obj):
        request = self.context.get("request")
        if obj.logo_id:
            cache_url = _build_logo_cache_url(request, obj.logo_id)
            return cache_url or (obj.logo.url if obj.logo else None)

        custom = obj.custom_properties or {}
        return custom.get("poster_url") or custom.get("cover")

    def get_backdrop_path(self, obj):
        custom = obj.custom_properties or {}
        if "backdrop_path" in custom and isinstance(custom["backdrop_path"], list):
            return custom["backdrop_path"]
        backdrop_url = custom.get("backdrop_url")
        if backdrop_url:
            return [backdrop_url]
        return []


class MovieSerializer(serializers.ModelSerializer):
    logo = LogoSerializer(read_only=True)
    library_sources = serializers.SerializerMethodField()
    movie_image = serializers.SerializerMethodField()
    backdrop_path = serializers.SerializerMethodField()

    class Meta:
        model = Movie
        fields = '__all__'

    def get_library_sources(self, obj):
        sources = []
        for item in obj.library_items.select_related("library").filter(library__use_as_vod_source=True):
            library = item.library
            sources.append(
                {
                    "library_id": library.id,
                    "library_name": library.name,
                    "media_item_id": item.id,
                }
        )
        return sources

    def get_movie_image(self, obj):
        request = self.context.get("request")
        if obj.logo_id:
            cache_url = _build_logo_cache_url(request, obj.logo_id)
            return cache_url or (obj.logo.url if obj.logo else None)

        custom = obj.custom_properties or {}
        return custom.get("poster_url") or custom.get("cover")

    def get_backdrop_path(self, obj):
        custom = obj.custom_properties or {}
        if "backdrop_path" in custom and isinstance(custom["backdrop_path"], list):
            return custom["backdrop_path"]
        backdrop_url = custom.get("backdrop_url")
        if backdrop_url:
            return [backdrop_url]
        return []


class EpisodeSerializer(serializers.ModelSerializer):
    series = SeriesSerializer(read_only=True)
    library_sources = serializers.SerializerMethodField()
    movie_image = serializers.SerializerMethodField()
    backdrop_path = serializers.SerializerMethodField()

    class Meta:
        model = Episode
        fields = '__all__'

    def get_library_sources(self, obj):
        sources = []
        for item in obj.library_items.select_related("library").filter(library__use_as_vod_source=True):
            library = item.library
            sources.append(
                {
                    "library_id": library.id,
                    "library_name": library.name,
                    "media_item_id": item.id,
                }
        )
        return sources

    def get_movie_image(self, obj):
        custom = obj.custom_properties or {}
        if custom.get("poster_url"):
            return custom["poster_url"]
        if obj.series_id and obj.series and obj.series.logo_id:
            request = self.context.get("request")
            return _build_logo_cache_url(request, obj.series.logo_id) or (
                obj.series.logo.url if obj.series.logo else None
            )
        return None

    def get_backdrop_path(self, obj):
        custom = obj.custom_properties or {}
        if isinstance(custom.get("backdrop_path"), list):
            return custom["backdrop_path"]
        backdrop_url = custom.get("backdrop_url")
        if backdrop_url:
            return [backdrop_url]
        if obj.series_id and obj.series:
            series_custom = obj.series.custom_properties or {}
            if isinstance(series_custom.get("backdrop_path"), list):
                return series_custom["backdrop_path"]
            if series_custom.get("backdrop_url"):
                return [series_custom["backdrop_url"]]
        return []


class M3USeriesRelationSerializer(serializers.ModelSerializer):
    series = SeriesSerializer(read_only=True)
    category = VODCategorySerializer(read_only=True)
    m3u_account = M3UAccountSerializer(read_only=True)

    class Meta:
        model = M3USeriesRelation
        fields = '__all__'


class M3UMovieRelationSerializer(serializers.ModelSerializer):
    movie = MovieSerializer(read_only=True)
    category = VODCategorySerializer(read_only=True)
    m3u_account = M3UAccountSerializer(read_only=True)
    quality_info = serializers.SerializerMethodField()

    class Meta:
        model = M3UMovieRelation
        fields = '__all__'

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

    class Meta:
        model = M3UEpisodeRelation
        fields = '__all__'

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
    logo = LogoSerializer(read_only=True)
    providers = M3USeriesRelationSerializer(source='m3u_relations', many=True, read_only=True)
    episode_count = serializers.SerializerMethodField()

    class Meta:
        model = Series
        fields = '__all__'

    def get_episode_count(self, obj):
        return obj.episodes.count()
