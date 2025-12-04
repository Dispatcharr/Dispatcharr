from django.db import models
from django.db.models import Q
from django.utils import timezone
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from apps.m3u.models import M3UAccount
import uuid


class VODLogo(models.Model):
    """Logo model specifically for VOD content (movies and series)"""
    name = models.CharField(max_length=255)
    url = models.TextField(unique=True)

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = 'VOD Logo'
        verbose_name_plural = 'VOD Logos'


class VODCategory(models.Model):
    """Categories for organizing VODs (e.g., Action, Comedy, Drama)"""

    CATEGORY_TYPE_CHOICES = [
        ('movie', 'Movie'),
        ('series', 'Series'),
    ]

    name = models.CharField(max_length=255)
    category_type = models.CharField(
        max_length=10,
        choices=CATEGORY_TYPE_CHOICES,
        default='movie',
        help_text="Type of content this category contains"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'VOD Category'
        verbose_name_plural = 'VOD Categories'
        ordering = ['name']
        unique_together = [('name', 'category_type')]

    @classmethod
    def bulk_create_and_fetch(cls, objects, ignore_conflicts=False):
        # Perform the bulk create operation
        cls.objects.bulk_create(objects, ignore_conflicts=ignore_conflicts)

        # Use the unique fields to fetch the created objects
        # Since we have unique_together on ('name', 'category_type'), we need both fields
        filter_conditions = []
        for obj in objects:
            filter_conditions.append(
                Q(name=obj.name, category_type=obj.category_type)
            )

        if filter_conditions:
            # Combine all conditions with OR
            combined_condition = filter_conditions[0]
            for condition in filter_conditions[1:]:
                combined_condition |= condition

            created_objects = cls.objects.filter(combined_condition)
        else:
            created_objects = cls.objects.none()

        return created_objects

    def __str__(self):
        return f"{self.name} ({self.get_category_type_display()})"


class Series(models.Model):
    """Series information for TV shows"""
    uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    year = models.IntegerField(blank=True, null=True)
    rating = models.CharField(max_length=10, blank=True, null=True)
    genre = models.CharField(max_length=255, blank=True, null=True)
    logo = models.ForeignKey(VODLogo, on_delete=models.SET_NULL, null=True, blank=True, related_name='series')

    # Metadata IDs for deduplication - these should be globally unique when present
    tmdb_id = models.CharField(max_length=50, blank=True, null=True, unique=True, help_text="TMDB ID for metadata")
    imdb_id = models.CharField(max_length=50, blank=True, null=True, unique=True, help_text="IMDB ID for metadata")

    # Additional metadata and properties
    custom_properties = models.JSONField(blank=True, null=True, help_text='Additional metadata and properties for the series')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Series'
        verbose_name_plural = 'Series'
        ordering = ['name']
        # Only enforce name+year uniqueness when no external IDs are present
        constraints = [
            models.UniqueConstraint(
                fields=['name', 'year'],
                condition=models.Q(tmdb_id__isnull=True) & models.Q(imdb_id__isnull=True),
                name='unique_series_name_year_no_external_id'
            ),
        ]

    def __str__(self):
        year_str = f" ({self.year})" if self.year else ""
        return f"{self.name}{year_str}"


class Movie(models.Model):
    """Movie content"""
    uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    year = models.IntegerField(blank=True, null=True)
    rating = models.CharField(max_length=10, blank=True, null=True)
    genre = models.CharField(max_length=255, blank=True, null=True)
    duration_secs = models.IntegerField(blank=True, null=True, help_text="Duration in seconds")
    logo = models.ForeignKey(VODLogo, on_delete=models.SET_NULL, null=True, blank=True, related_name='movie')

    # Metadata IDs for deduplication - these should be globally unique when present
    tmdb_id = models.CharField(max_length=50, blank=True, null=True, unique=True, help_text="TMDB ID for metadata")
    imdb_id = models.CharField(max_length=50, blank=True, null=True, unique=True, help_text="IMDB ID for metadata")

    # Additional metadata and properties
    custom_properties = models.JSONField(blank=True, null=True, help_text='Additional metadata and properties for the movie')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Movie'
        verbose_name_plural = 'Movies'
        ordering = ['name']
        # Only enforce name+year uniqueness when no external IDs are present
        constraints = [
            models.UniqueConstraint(
                fields=['name', 'year'],
                condition=models.Q(tmdb_id__isnull=True) & models.Q(imdb_id__isnull=True),
                name='unique_movie_name_year_no_external_id'
            ),
        ]

    def __str__(self):
        year_str = f" ({self.year})" if self.year else ""
        return f"{self.name}{year_str}"


class Episode(models.Model):
    """Episode content for TV series"""
    uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    air_date = models.DateField(blank=True, null=True)
    rating = models.CharField(max_length=10, blank=True, null=True)
    duration_secs = models.IntegerField(blank=True, null=True, help_text="Duration in seconds")

    # Episode specific fields
    series = models.ForeignKey(Series, on_delete=models.CASCADE, related_name='episodes')
    season_number = models.IntegerField(blank=True, null=True)
    episode_number = models.IntegerField(blank=True, null=True)

    # Metadata IDs
    tmdb_id = models.CharField(max_length=50, blank=True, null=True, help_text="TMDB ID for metadata", db_index=True)
    imdb_id = models.CharField(max_length=50, blank=True, null=True, help_text="IMDB ID for metadata", db_index=True)

    # Custom properties for episode
    custom_properties = models.JSONField(blank=True, null=True, help_text="Custom properties for this episode")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Episode'
        verbose_name_plural = 'Episodes'
        ordering = ['series__name', 'season_number', 'episode_number']
        unique_together = [
            ('series', 'season_number', 'episode_number'),
        ]

    def __str__(self):
        season_ep = f"S{self.season_number or 0:02d}E{self.episode_number or 0:02d}"
        return f"{self.series.name} - {season_ep} - {self.name}"


# New relation models to link M3U accounts with VOD content

class M3USeriesRelation(models.Model):
    """Links M3U accounts to Series with provider-specific information"""
    m3u_account = models.ForeignKey(M3UAccount, on_delete=models.CASCADE, related_name='series_relations')
    series = models.ForeignKey(Series, on_delete=models.CASCADE, related_name='m3u_relations')
    category = models.ForeignKey(VODCategory, on_delete=models.SET_NULL, null=True, blank=True)

    # Provider-specific fields - renamed to avoid clash with series ForeignKey
    external_series_id = models.CharField(max_length=255, help_text="External series ID from M3U provider")
    custom_properties = models.JSONField(blank=True, null=True, help_text="Provider-specific data")

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_episode_refresh = models.DateTimeField(blank=True, null=True, help_text="Last time episodes were refreshed")
    last_seen = models.DateTimeField(default=timezone.now, help_text="Last time this relation was seen during VOD scan")

    class Meta:
        verbose_name = 'M3U Series Relation'
        verbose_name_plural = 'M3U Series Relations'
        unique_together = [('m3u_account', 'external_series_id')]

    def __str__(self):
        return f"{self.m3u_account.name} - {self.series.name}"


class M3UMovieRelation(models.Model):
    """Links M3U accounts to Movies with provider-specific information"""
    m3u_account = models.ForeignKey(M3UAccount, on_delete=models.CASCADE, related_name='movie_relations')
    movie = models.ForeignKey(Movie, on_delete=models.CASCADE, related_name='m3u_relations')
    category = models.ForeignKey(VODCategory, on_delete=models.SET_NULL, null=True, blank=True)

    # Streaming information (provider-specific)
    stream_id = models.CharField(max_length=255, help_text="External stream ID from M3U provider")
    container_extension = models.CharField(max_length=10, blank=True, null=True)

    # Provider-specific data
    custom_properties = models.JSONField(blank=True, null=True, help_text="Provider-specific data like quality, language, etc.")

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_advanced_refresh = models.DateTimeField(blank=True, null=True, help_text="Last time advanced data was fetched from provider")
    last_seen = models.DateTimeField(default=timezone.now, help_text="Last time this relation was seen during VOD scan")

    class Meta:
        verbose_name = 'M3U Movie Relation'
        verbose_name_plural = 'M3U Movie Relations'
        unique_together = [('m3u_account', 'stream_id')]

    def __str__(self):
        return f"{self.m3u_account.name} - {self.movie.name}"

    def get_stream_url(self):
        """Get the full stream URL for this movie from this provider"""
        # Build URL dynamically for XtreamCodes accounts
        if self.m3u_account.account_type == 'XC':
            server_url = self.m3u_account.server_url.rstrip('/')
            username = self.m3u_account.username
            password = self.m3u_account.password
            return f"{server_url}/movie/{username}/{password}/{self.stream_id}.{self.container_extension or 'mp4'}"
        else:
            # For other account types, we would need another way to build URLs
            return None


class M3UEpisodeRelation(models.Model):
    """Links M3U accounts to Episodes with provider-specific information"""
    m3u_account = models.ForeignKey(M3UAccount, on_delete=models.CASCADE, related_name='episode_relations')
    episode = models.ForeignKey(Episode, on_delete=models.CASCADE, related_name='m3u_relations')

    # Streaming information (provider-specific)
    stream_id = models.CharField(max_length=255, help_text="External stream ID from M3U provider")
    container_extension = models.CharField(max_length=10, blank=True, null=True)

    # Provider-specific data
    custom_properties = models.JSONField(blank=True, null=True, help_text="Provider-specific data like quality, language, etc.")

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_seen = models.DateTimeField(default=timezone.now, help_text="Last time this relation was seen during VOD scan")

    class Meta:
        verbose_name = 'M3U Episode Relation'
        verbose_name_plural = 'M3U Episode Relations'
        unique_together = [('m3u_account', 'stream_id')]

    def __str__(self):
        return f"{self.m3u_account.name} - {self.episode}"

    def get_stream_url(self):
        """Get the full stream URL for this episode from this provider"""
        from core.xtream_codes import Client as XtreamCodesClient

        if self.m3u_account.account_type == 'XC':
            # For XtreamCodes accounts, build the URL dynamically
            server_url = self.m3u_account.server_url.rstrip('/')
            username = self.m3u_account.username
            password = self.m3u_account.password
            return f"{server_url}/series/{username}/{password}/{self.stream_id}.{self.container_extension or 'mp4'}"
        else:
            # We might support non XC accounts in the future
            # For now, return None
            return None

class M3UVODCategoryRelation(models.Model):
    """Links M3U accounts to categories with provider-specific information"""
    m3u_account = models.ForeignKey(M3UAccount, on_delete=models.CASCADE, related_name='category_relations')
    category = models.ForeignKey(VODCategory, on_delete=models.CASCADE, related_name='m3u_relations')

    enabled = models.BooleanField(
        default=False, help_text="Set to false to deactivate this category for the M3U account"
    )

    custom_properties = models.JSONField(blank=True, null=True, help_text="Provider-specific data like quality, language, etc.")

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'M3U VOD Category Relation'
        verbose_name_plural = 'M3U VOD Category Relations'
        unique_together = [('m3u_account', 'category')]

    def __str__(self):
        return f"{self.m3u_account.name} - {self.category.name}"
