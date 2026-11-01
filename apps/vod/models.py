from django.conf import settings
from django.db import models
from django.db.models import Q
from django.db.models.functions import Now
from django.utils import timezone
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from apps.m3u.models import M3UAccount
import uuid


class VODLogoQuerySet(models.QuerySet):
    def bulk_create(self, objs, *args, **kwargs):
        # bulk_create bypasses Model.save(); clamp names here so provider
        # movie/series titles longer than varchar(255) cannot abort VOD ingest.
        from core.utils import truncate_with_warning

        max_length = self.model._meta.get_field("name").max_length
        for obj in objs:
            obj.name = truncate_with_warning(
                obj.name, max_length=max_length, label="Logo name"
            )
        return super().bulk_create(objs, *args, **kwargs)


class VODLogo(models.Model):
    """Logo model specifically for VOD content (movies and series)"""
    name = models.CharField(max_length=255)
    url = models.TextField(unique=True)

    objects = VODLogoQuerySet.as_manager()

    def save(self, *args, **kwargs):
        from core.utils import truncate_with_warning

        self.name = truncate_with_warning(
            self.name,
            max_length=self._meta.get_field("name").max_length,
            label="Logo name",
        )
        super().save(*args, **kwargs)

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


class VODSourceMetadataMixin(models.Model):
    """Metadata belongs to an exact account/provider relation, not a title."""

    declared_metadata = models.JSONField(default=dict, blank=True)
    observed_metadata = models.JSONField(default=dict, blank=True)
    manual_metadata = models.JSONField(default=dict, blank=True)
    locked_fields = models.JSONField(default=list, blank=True)
    last_observed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        abstract = True

    def effective_metadata(self, category_defaults=None):
        from .metadata import effective_source_metadata

        return effective_source_metadata(self, category_defaults=category_defaults)


class VODLibraryMetadataMixin(models.Model):
    """Canonical library annotations, independent of exact provider sources."""

    library_blocked = models.BooleanField(
        default=False, db_default=False, db_index=True
    )

    display_name = models.CharField(
        max_length=255, blank=True, default="", db_default=""
    )
    clean_title = models.CharField(
        max_length=255, blank=True, default="", db_default=""
    )
    tmdb_lookup_excluded = models.BooleanField(
        default=False, db_default=False, db_index=True
    )
    tmdb_metadata = models.JSONField(default=dict, db_default={}, blank=True)
    tmdb_match_id = models.CharField(
        max_length=50, blank=True, default="", db_default="", db_index=True
    )
    tmdb_imdb_id = models.CharField(
        max_length=50, blank=True, default="", db_default=""
    )
    tmdb_poster_url = models.CharField(
        max_length=500, blank=True, default="", db_default=""
    )
    tmdb_backdrop_url = models.CharField(
        max_length=500, blank=True, default="", db_default=""
    )
    tmdb_status = models.CharField(
        max_length=16, blank=True, default="", db_default="", db_index=True
    )
    tmdb_enriched_at = models.DateTimeField(null=True, blank=True)
    library_added_at = models.DateTimeField(
        default=timezone.now, db_default=Now(), db_index=True
    )

    class Meta:
        abstract = True


class Series(VODLibraryMetadataMixin):
    """Series information for TV shows"""
    uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    year = models.IntegerField(blank=True, null=True)
    rating = models.CharField(max_length=10, blank=True, null=True)
    genre = models.CharField(max_length=255, blank=True, null=True)
    logo = models.ForeignKey(VODLogo, on_delete=models.SET_NULL, null=True, blank=True, related_name='series')

    # Content identity is independent of source languages and technical features.
    tmdb_id = models.CharField(max_length=50, blank=True, null=True, db_index=True, help_text="TMDB ID for metadata")
    imdb_id = models.CharField(max_length=50, blank=True, null=True, db_index=True, help_text="IMDB ID for metadata")

    # Additional metadata and properties
    custom_properties = models.JSONField(blank=True, null=True, help_text='Additional metadata and properties for the series')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Series'
        verbose_name_plural = 'Series'
        ordering = ['name']
        constraints = [
            models.UniqueConstraint(
                fields=['tmdb_id'],
                condition=models.Q(tmdb_id__isnull=False),
                name='unique_series_tmdb_id'
            ),
            models.UniqueConstraint(
                fields=['imdb_id'],
                condition=models.Q(imdb_id__isnull=False),
                name='unique_series_imdb_id'
            ),
            models.UniqueConstraint(
                fields=['name', 'year'],
                condition=models.Q(tmdb_id__isnull=True) & models.Q(imdb_id__isnull=True),
                name='unique_series_name_year_no_external_id'
            ),
        ]

    def __str__(self):
        year_str = f" ({self.year})" if self.year else ""
        return f"{self.name}{year_str}"


class Movie(VODLibraryMetadataMixin):
    """Movie content"""
    uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    year = models.IntegerField(blank=True, null=True)
    rating = models.CharField(max_length=10, blank=True, null=True)
    genre = models.CharField(max_length=255, blank=True, null=True)
    duration_secs = models.IntegerField(blank=True, null=True, help_text="Duration in seconds")
    logo = models.ForeignKey(VODLogo, on_delete=models.SET_NULL, null=True, blank=True, related_name='movie')

    # Content identity is independent of source languages and technical features.
    tmdb_id = models.CharField(max_length=50, blank=True, null=True, db_index=True, help_text="TMDB ID for metadata")
    imdb_id = models.CharField(max_length=50, blank=True, null=True, db_index=True, help_text="IMDB ID for metadata")

    is_adult = models.BooleanField(
        default=False,
        db_index=True,
        help_text="Whether this movie contains adult content",
    )

    # Additional metadata and properties
    custom_properties = models.JSONField(blank=True, null=True, help_text='Additional metadata and properties for the movie')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Movie'
        verbose_name_plural = 'Movies'
        ordering = ['name']
        constraints = [
            models.UniqueConstraint(
                fields=['tmdb_id'],
                condition=models.Q(tmdb_id__isnull=False),
                name='unique_movie_tmdb_id'
            ),
            models.UniqueConstraint(
                fields=['imdb_id'],
                condition=models.Q(imdb_id__isnull=False),
                name='unique_movie_imdb_id'
            ),
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

class M3USeriesRelation(VODSourceMetadataMixin):
    """Links M3U accounts to Series with provider-specific information"""
    m3u_account = models.ForeignKey(M3UAccount, on_delete=models.CASCADE, related_name='series_relations')
    series = models.ForeignKey(Series, on_delete=models.CASCADE, related_name='m3u_relations')
    category = models.ForeignKey(VODCategory, on_delete=models.SET_NULL, null=True, blank=True)

    # Provider-specific fields - renamed to avoid clash with series ForeignKey
    external_series_id = models.CharField(max_length=255, help_text="External series ID from M3U provider")
    tmdb_override_id = models.CharField(
        max_length=50, blank=True, default="", db_default="", db_index=True
    )
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


class M3UMovieRelation(VODSourceMetadataMixin):
    """Links M3U accounts to Movies with provider-specific information"""
    m3u_account = models.ForeignKey(M3UAccount, on_delete=models.CASCADE, related_name='movie_relations')
    movie = models.ForeignKey(Movie, on_delete=models.CASCADE, related_name='m3u_relations')
    category = models.ForeignKey(VODCategory, on_delete=models.SET_NULL, null=True, blank=True)

    # Streaming information (provider-specific)
    stream_id = models.CharField(max_length=255, help_text="External stream ID from M3U provider")
    container_extension = models.CharField(max_length=10, blank=True, null=True)
    tmdb_override_id = models.CharField(
        max_length=50, blank=True, default="", db_default="", db_index=True
    )

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

    def get_stream_url(self, profile=None):
        """Build the XC movie URL using the same credential resolution as playback.

        When *profile* is omitted, the account's first active profile is used
        (identity patterns keep base credentials). Returns None for non-XC
        accounts or when credential transform fails.
        """
        if self.m3u_account.account_type != "XC":
            return None

        from apps.m3u.credentials import (
            build_xc_playback_url,
            get_transformed_credentials,
        )

        server_url, username, password = get_transformed_credentials(
            self.m3u_account, profile
        )
        if not (server_url and username and password and self.stream_id):
            return None

        return build_xc_playback_url(
            server_url,
            username,
            password,
            content_path="movie",
            stream_id=str(self.stream_id),
            extension=self.container_extension or "mp4",
        )


class M3UEpisodeRelation(VODSourceMetadataMixin):
    """Links M3U accounts to Episodes with provider-specific information"""
    m3u_account = models.ForeignKey(M3UAccount, on_delete=models.CASCADE, related_name='episode_relations')
    episode = models.ForeignKey(Episode, on_delete=models.CASCADE, related_name='m3u_relations')
    series_relation = models.ForeignKey(
        'M3USeriesRelation',
        on_delete=models.CASCADE,
        related_name='episode_relations',
        null=True,
        blank=True,
        help_text="The series relation this episode relation belongs to. CASCADE ensures cleanup when the series relation is removed."
    )

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

    def get_stream_url(self, profile=None):
        """Build the XC series/episode URL using the same credential resolution as playback.

        When *profile* is omitted, the account's first active profile is used
        (identity patterns keep base credentials). Returns None for non-XC
        accounts or when credential transform fails.
        """
        if self.m3u_account.account_type != "XC":
            return None

        from apps.m3u.credentials import (
            build_xc_playback_url,
            get_transformed_credentials,
        )

        server_url, username, password = get_transformed_credentials(
            self.m3u_account, profile
        )
        if not (server_url and username and password and self.stream_id):
            return None

        return build_xc_playback_url(
            server_url,
            username,
            password,
            content_path="series",
            stream_id=str(self.stream_id),
            extension=self.container_extension or "mp4",
        )

class M3UVODCategoryRelation(models.Model):
    """Links M3U accounts to categories with provider-specific information"""
    m3u_account = models.ForeignKey(M3UAccount, on_delete=models.CASCADE, related_name='category_relations')
    category = models.ForeignKey(VODCategory, on_delete=models.CASCADE, related_name='m3u_relations')

    enabled = models.BooleanField(
        default=False, help_text="Set to false to deactivate this category for the M3U account"
    )
    ignored = models.BooleanField(default=False)

    custom_properties = models.JSONField(blank=True, null=True, help_text="Provider-specific data like quality, language, etc.")
    metadata_defaults = models.JSONField(default=dict, blank=True)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'M3U VOD Category Relation'
        verbose_name_plural = 'M3U VOD Category Relations'
        unique_together = [('m3u_account', 'category')]
        constraints = [models.CheckConstraint(
            condition=models.Q(ignored=False) | models.Q(enabled=False),
            name="vod_ignored_category_disabled",
        )]

    def __str__(self):
        return f"{self.m3u_account.name} - {self.category.name}"

    def save(self, *args, **kwargs):
        if self.ignored:
            self.enabled = False
            if kwargs.get("update_fields") is not None:
                kwargs["update_fields"] = set(kwargs["update_fields"]) | {"enabled"}
        super().save(*args, **kwargs)


class VODContentAlias(models.Model):
    """Stable public selections and retired IDs retain playback requirements.

    Targets are numeric canonical IDs rather than provider IDs. A missing
    target resolves to 404; an old identifier is never reused for a source.
    """

    content_type = models.CharField(
        max_length=7,
        choices=(("movie", "Movie"), ("series", "Series"), ("episode", "Episode")),
    )
    legacy_id = models.PositiveBigIntegerField()
    legacy_uuid = models.UUIDField()
    target_id = models.PositiveBigIntegerField()
    requirements = models.JSONField(default=dict, blank=True)
    selection_key = models.CharField(max_length=100, unique=True, null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("content_type", "legacy_id"), name="vod_alias_legacy_id"
            ),
            models.UniqueConstraint(
                fields=("content_type", "legacy_uuid"), name="vod_alias_legacy_uuid"
            ),
        ]
        indexes = [
            models.Index(fields=("content_type", "target_id"), name="vod_alias_target_idx"),
        ]


class VODMetadataState(models.Model):
    """Durable selection and progress for an explicit library enrichment job."""

    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    task_id = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=12, default="idle")
    selection = models.JSONField(default=list, blank=True)
    pending_enrichment = models.JSONField(default=list, db_default=[], blank=True)
    refreshing_accounts = models.JSONField(default=list, db_default=[], blank=True)
    job_heartbeat = models.DateTimeField(default=timezone.now, db_default=Now())
    progress = models.JSONField(default=dict, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    error = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)


class VODProfile(models.Model):
    """Client VOD output for the users assigned to it.

    Profiles only shape Xtream Codes catalogues, details and playback. The
    Library and administration keep showing every source.
    """

    class OutputMode(models.TextChoices):
        COMPACT = "compact", "Compact"
        VARIANTS = "variants", "Sources"

    class OutputGroups(models.TextChoices):
        PROVIDER = "provider", "Provider"
        MOVIE_SERIES = "movie_series", "Movie & Series"

    class MetadataSource(models.TextChoices):
        PROVIDER = "provider", "Provider"
        ENRICHED = "enriched", "Enriched"

    class CatalogStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        BUILDING = "building", "Building"
        READY = "ready", "Ready"
        FAILED = "failed", "Failed"

    name = models.CharField(max_length=255, unique=True)
    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    output_mode = models.CharField(
        max_length=10, choices=OutputMode.choices, default=OutputMode.COMPACT
    )
    name_template = models.CharField(
        max_length=500, default="{title} [{dub} · {resolution} · {features}]"
    )
    output_groups = models.CharField(
        max_length=12, choices=OutputGroups.choices, default=OutputGroups.PROVIDER
    )
    # "provider", "clean" for the cleaned Library titles, or a Library
    # metadata language.
    title_source = models.CharField(max_length=10, default="provider")
    metadata_source = models.CharField(
        max_length=10, choices=MetadataSource.choices, default=MetadataSource.PROVIDER
    )
    # Manual choices win over the ordered import rules; the rest is disabled.
    category_choices = models.JSONField(default=list, blank=True)
    content_filters = models.JSONField(default=dict, blank=True)
    # Titles this profile never offers, whatever the filters allow.
    excluded_titles = models.JSONField(default=list, blank=True)
    edition_rules = models.JSONField(default=list, blank=True)
    ranking = models.JSONField(default=list, blank=True)
    audio_language_order = models.JSONField(default=list, blank=True)
    subtitle_language_order = models.JSONField(default=list, blank=True)
    provider_order = models.JSONField(default=list, blank=True)
    catalog_status = models.CharField(
        max_length=10, choices=CatalogStatus.choices, default=CatalogStatus.PENDING
    )
    catalog_generation = models.CharField(max_length=32, blank=True)
    catalog_signature = models.CharField(max_length=64, blank=True)
    catalog_counts = models.JSONField(default=dict, blank=True)
    catalog_progress = models.JSONField(default=dict, blank=True)
    catalog_started_at = models.DateTimeField(null=True, blank=True)
    catalog_completed_at = models.DateTimeField(null=True, blank=True)
    catalog_error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-is_default", "name")
        constraints = [
            models.UniqueConstraint(
                fields=("is_default",),
                condition=Q(is_default=True),
                name="vod_single_default_profile",
            ),
            models.CheckConstraint(
                condition=Q(is_default=False) | Q(is_active=True),
                name="vod_default_profile_active",
            ),
        ]

    def __str__(self):
        return self.name


class VODProfileAssignment(models.Model):
    """At most one profile per user; users without one use the default."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="vod_profile_assignment",
    )
    profile = models.ForeignKey(
        VODProfile, on_delete=models.CASCADE, related_name="assignments"
    )

    def __str__(self):
        return f"{self.user} -> {self.profile}"


class VODProfileCategoryRule(models.Model):
    """Ordered import rule deciding which account categories a profile offers.

    Rules behave like M3U import rules and share their evaluation: the first
    enabled match decides, categories without a match stay disabled.
    """

    class Scope(models.TextChoices):
        MOVIE = "movie", "VOD Movies"
        SERIES = "series", "VOD Series"

    class Action(models.TextChoices):
        ENABLE = "enable", "Enabled"
        DISABLE = "disable", "Disabled"

    profile = models.ForeignKey(
        VODProfile, on_delete=models.CASCADE, related_name="category_rules"
    )
    scope = models.CharField(max_length=10, choices=Scope.choices)
    regex_pattern = models.CharField(max_length=500)
    action = models.CharField(
        max_length=10, choices=Action.choices, default=Action.DISABLE
    )
    case_sensitive = models.BooleanField(default=False)
    enabled = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)

    # The shared M3U rule engine also reads these group rule attributes.
    match_field = "group_name"
    match_mode = "any"
    requires_review = False

    @property
    def metadata_defaults(self):
        return {}

    class Meta:
        ordering = ("scope", "order", "id")

    def __str__(self):
        return f"{self.profile}: {self.regex_pattern}"



class VODProfileEntry(models.Model):
    """One prepared Xtream Codes entry of a profile catalogue generation.

    Titles, artwork and blocks stay live at output time; an entry fixes which
    source represents the title, its public ID and the ordered fallbacks.
    """

    profile = models.ForeignKey(
        VODProfile, on_delete=models.CASCADE, related_name="entries"
    )
    generation = models.CharField(max_length=32)
    content_type = models.CharField(
        max_length=6, choices=(("movie", "Movie"), ("series", "Series"))
    )
    content_id = models.PositiveIntegerField()
    relation_id = models.PositiveIntegerField()
    public_id = models.PositiveBigIntegerField()
    edition = models.CharField(max_length=120, blank=True)
    source_ids = models.JSONField(default=list)
    # Full lists show primary entries; a category request also gets the best
    # source within that category, as the live output always did.
    primary = models.BooleanField(default=True)

    class Meta:
        indexes = [
            models.Index(
                fields=("profile", "generation", "content_type", "relation_id"),
                name="vod_profile_entry_relation",
            ),
            models.Index(
                fields=("profile", "generation", "content_type", "content_id"),
                name="vod_profile_entry_content",
            ),
        ]
