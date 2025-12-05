from rest_framework import serializers
from django.urls import reverse
from .models import (
    Series, VODCategory, Movie, Episode, VODLogo,
    M3USeriesRelation, M3UMovieRelation, M3UEpisodeRelation, M3UVODCategoryRelation
)
from apps.m3u.serializers import M3UAccountSerializer


class VODLogoSerializer(serializers.ModelSerializer):
    cache_url = serializers.SerializerMethodField()
    movie_count = serializers.SerializerMethodField()
    series_count = serializers.SerializerMethodField()
    is_used = serializers.SerializerMethodField()
    item_names = serializers.SerializerMethodField()

    class Meta:
        model = VODLogo
        fields = ["id", "name", "url", "cache_url", "movie_count", "series_count", "is_used", "item_names"]

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

    def get_cache_url(self, obj):
        request = self.context.get("request")
        if request:
            return request.build_absolute_uri(
                reverse("api:vod:vodlogo-cache", args=[obj.id])
            )
        return reverse("api:vod:vodlogo-cache", args=[obj.id])

    def get_movie_count(self, obj):
        """Get the number of movies using this logo"""
        return obj.movie.count() if hasattr(obj, 'movie') else 0

    def get_series_count(self, obj):
        """Get the number of series using this logo"""
        return obj.series.count() if hasattr(obj, 'series') else 0

    def get_is_used(self, obj):
        """Check if this logo is used by any movies or series"""
        return (hasattr(obj, 'movie') and obj.movie.exists()) or (hasattr(obj, 'series') and obj.series.exists())

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
    episode_count = serializers.SerializerMethodField()

    class Meta:
        model = Series
        fields = '__all__'

    def get_episode_count(self, obj):
        return obj.episodes.count()


class MovieSerializer(serializers.ModelSerializer):
    logo = VODLogoSerializer(read_only=True)

    class Meta:
        model = Movie
        fields = '__all__'


class EpisodeSerializer(serializers.ModelSerializer):
    series = SeriesSerializer(read_only=True)

    class Meta:
        model = Episode
        fields = '__all__'


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
    logo = VODLogoSerializer(read_only=True)
    providers = M3USeriesRelationSerializer(source='m3u_relations', many=True, read_only=True)
    episode_count = serializers.SerializerMethodField()

    class Meta:
        model = Series
        fields = '__all__'

    def get_episode_count(self, obj):
        return obj.episodes.count()
