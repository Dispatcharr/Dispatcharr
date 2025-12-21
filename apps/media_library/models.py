from django.conf import settings
from django.db import models


class Library(models.Model):
    LIBRARY_TYPE_MOVIES = "movies"
    LIBRARY_TYPE_SHOWS = "shows"

    LIBRARY_TYPE_CHOICES = [
        (LIBRARY_TYPE_MOVIES, "Movies"),
        (LIBRARY_TYPE_SHOWS, "TV Shows"),
    ]

    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    library_type = models.CharField(max_length=20, choices=LIBRARY_TYPE_CHOICES)
    metadata_language = models.CharField(max_length=12, blank=True, default="")
    metadata_country = models.CharField(max_length=12, blank=True, default="")
    metadata_options = models.JSONField(default=dict, blank=True, null=True)
    scan_interval_minutes = models.PositiveIntegerField(default=1440)
    auto_scan_enabled = models.BooleanField(default=True)
    add_to_vod = models.BooleanField(default=False)
    vod_account = models.ForeignKey(
        "m3u.M3UAccount",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="media_libraries",
    )
    last_scan_at = models.DateTimeField(null=True, blank=True)
    last_successful_scan_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class LibraryLocation(models.Model):
    library = models.ForeignKey(
        Library, on_delete=models.CASCADE, related_name="locations"
    )
    path = models.CharField(max_length=1024)
    include_subdirectories = models.BooleanField(default=True)
    is_primary = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("library", "path")]
        indexes = [
            models.Index(fields=["library", "is_primary"]),
        ]

    def __str__(self):
        return f"{self.library.name}: {self.path}"


class MediaItem(models.Model):
    TYPE_MOVIE = "movie"
    TYPE_SHOW = "show"
    TYPE_EPISODE = "episode"
    TYPE_OTHER = "other"

    ITEM_TYPE_CHOICES = [
        (TYPE_MOVIE, "Movie"),
        (TYPE_SHOW, "Show"),
        (TYPE_EPISODE, "Episode"),
        (TYPE_OTHER, "Other"),
    ]

    library = models.ForeignKey(
        Library, on_delete=models.CASCADE, related_name="items"
    )
    parent = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="children",
    )
    item_type = models.CharField(max_length=16, choices=ITEM_TYPE_CHOICES)
    title = models.CharField(max_length=512)
    sort_title = models.CharField(max_length=512, blank=True, default="")
    normalized_title = models.CharField(max_length=512, blank=True, default="")
    synopsis = models.TextField(blank=True, default="")
    tagline = models.TextField(blank=True, default="")
    release_year = models.IntegerField(null=True, blank=True)
    rating = models.CharField(max_length=10, blank=True, default="")
    runtime_ms = models.PositiveBigIntegerField(null=True, blank=True)
    season_number = models.IntegerField(null=True, blank=True)
    episode_number = models.IntegerField(null=True, blank=True)
    genres = models.JSONField(default=list, blank=True, null=True)
    tags = models.JSONField(default=list, blank=True, null=True)
    studios = models.JSONField(default=list, blank=True, null=True)
    cast = models.JSONField(default=list, blank=True, null=True)
    crew = models.JSONField(default=list, blank=True, null=True)
    poster_url = models.TextField(blank=True, default="")
    backdrop_url = models.TextField(blank=True, default="")
    movie_db_id = models.CharField(max_length=64, blank=True, default="")
    imdb_id = models.CharField(max_length=32, blank=True, default="")
    metadata = models.JSONField(blank=True, null=True)
    metadata_source = models.CharField(max_length=32, blank=True, default="")
    metadata_last_synced_at = models.DateTimeField(null=True, blank=True)
    first_imported_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sort_title", "title"]
        indexes = [
            models.Index(fields=["library", "item_type"]),
            models.Index(fields=["library", "sort_title"]),
            models.Index(fields=["library", "updated_at"]),
            models.Index(fields=["parent", "season_number", "episode_number"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["parent", "season_number", "episode_number"],
                condition=models.Q(item_type="episode"),
                name="unique_episode_per_season",
            )
        ]

    def __str__(self):
        return self.title

    @property
    def is_movie(self):
        return self.item_type == self.TYPE_MOVIE

    @property
    def is_show(self):
        return self.item_type == self.TYPE_SHOW

    @property
    def is_episode(self):
        return self.item_type == self.TYPE_EPISODE


class MediaFile(models.Model):
    library = models.ForeignKey(
        Library, on_delete=models.CASCADE, related_name="files"
    )
    media_item = models.ForeignKey(
        MediaItem, on_delete=models.CASCADE, related_name="files"
    )
    path = models.CharField(max_length=1024)
    relative_path = models.CharField(max_length=1024, blank=True, default="")
    file_name = models.CharField(max_length=512)
    size_bytes = models.BigIntegerField(null=True, blank=True)
    modified_at = models.DateTimeField(null=True, blank=True)
    duration_ms = models.PositiveBigIntegerField(null=True, blank=True)
    is_primary = models.BooleanField(default=False)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("library", "path")]
        indexes = [
            models.Index(fields=["media_item"]),
            models.Index(fields=["library", "is_primary"]),
            models.Index(fields=["library", "last_seen_at"]),
        ]

    def __str__(self):
        return self.path


class MediaItemVODLink(models.Model):
    media_item = models.OneToOneField(
        MediaItem, on_delete=models.CASCADE, related_name="vod_link"
    )
    vod_movie = models.ForeignKey(
        "vod.Movie",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="media_library_links",
    )
    vod_series = models.ForeignKey(
        "vod.Series",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="media_library_links",
    )
    vod_episode = models.ForeignKey(
        "vod.Episode",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="media_library_links",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["media_item"]),
            models.Index(fields=["vod_movie"]),
            models.Index(fields=["vod_series"]),
            models.Index(fields=["vod_episode"]),
        ]

    def __str__(self):
        return f"{self.media_item.title} -> VOD"


class ArtworkAsset(models.Model):
    TYPE_POSTER = "poster"
    TYPE_BACKDROP = "backdrop"

    TYPE_CHOICES = [
        (TYPE_POSTER, "Poster"),
        (TYPE_BACKDROP, "Backdrop"),
    ]

    media_item = models.ForeignKey(
        MediaItem, on_delete=models.CASCADE, related_name="artwork_assets"
    )
    asset_type = models.CharField(max_length=16, choices=TYPE_CHOICES)
    source = models.CharField(max_length=32, blank=True, default="")
    external_url = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["media_item", "asset_type"]),
        ]

    def __str__(self):
        return f"{self.media_item.title}: {self.asset_type}"


class WatchProgress(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="media_progress",
    )
    media_item = models.ForeignKey(
        MediaItem, on_delete=models.CASCADE, related_name="progress_entries"
    )
    file = models.ForeignKey(
        MediaFile,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="progress_entries",
    )
    position_ms = models.PositiveBigIntegerField(default=0)
    duration_ms = models.PositiveBigIntegerField(null=True, blank=True)
    completed = models.BooleanField(default=False)
    last_watched_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("user", "media_item")]
        indexes = [
            models.Index(fields=["user", "media_item"]),
        ]

    def __str__(self):
        return f"{self.user} - {self.media_item}"


class LibraryScan(models.Model):
    SCAN_QUICK = "quick"
    SCAN_FULL = "full"

    SCAN_TYPE_CHOICES = [
        (SCAN_QUICK, "Quick"),
        (SCAN_FULL, "Full"),
    ]

    STATUS_PENDING = "pending"
    STATUS_QUEUED = "queued"
    STATUS_RUNNING = "running"
    STATUS_COMPLETED = "completed"
    STATUS_FAILED = "failed"
    STATUS_CANCELLED = "cancelled"

    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_QUEUED, "Queued"),
        (STATUS_RUNNING, "Running"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_FAILED, "Failed"),
        (STATUS_CANCELLED, "Cancelled"),
    ]

    library = models.ForeignKey(
        Library, on_delete=models.CASCADE, related_name="scans"
    )
    scan_type = models.CharField(max_length=16, choices=SCAN_TYPE_CHOICES)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES)
    summary = models.CharField(max_length=255, blank=True, default="")
    stages = models.JSONField(default=dict, blank=True, null=True)
    processed_files = models.PositiveIntegerField(default=0)
    total_files = models.PositiveIntegerField(default=0)
    new_files = models.PositiveIntegerField(default=0)
    updated_files = models.PositiveIntegerField(default=0)
    removed_files = models.PositiveIntegerField(default=0)
    unmatched_files = models.PositiveIntegerField(default=0)
    log = models.TextField(blank=True, default="")
    extra = models.JSONField(blank=True, null=True)
    task_id = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["library", "created_at"]),
            models.Index(fields=["library", "status"]),
        ]

    def __str__(self):
        return f"{self.library.name} ({self.scan_type})"
