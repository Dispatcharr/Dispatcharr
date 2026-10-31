from rest_framework import serializers

from .metadata import (
    normalize_language_code,
    normalize_resolution,
    normalize_video_feature,
)
from .tmdb import MAX_METADATA_LANGUAGES


class StrictSerializer(serializers.Serializer):
    def to_internal_value(self, data):
        if isinstance(data, dict) and set(data) - set(self.fields):
            raise serializers.ValidationError(
                {"non_field_errors": ["Unsupported library field."]}
            )
        return super().to_internal_value(data)


class LibraryFilterSerializer(StrictSerializer):
    type = serializers.ChoiceField(choices=["all", "movie", "series"], default="all")
    view = serializers.ChoiceField(
        choices=["posters", "titles", "sources"], default="titles"
    )
    search = serializers.CharField(required=False, allow_blank=True, max_length=255)
    account = serializers.IntegerField(required=False, min_value=1)
    category = serializers.IntegerField(required=False, min_value=1)
    content_id = serializers.IntegerField(required=False, min_value=1)
    locked = serializers.ChoiceField(choices=["true", "false"], required=False)
    blocked = serializers.ChoiceField(choices=["true", "false"], required=False)
    metadata_status = serializers.ChoiceField(
        choices=[
            "matched",
            "not_found",
            "ambiguous",
            "failed",
            "missing_id",
            "missing_external_ids",
            "missing_metadata",
            "enriched",
        ],
        required=False,
    )
    audio_language = serializers.CharField(required=False, max_length=20)
    subtitle_language = serializers.CharField(required=False, max_length=20)
    resolution = serializers.CharField(required=False, max_length=20)
    video_feature = serializers.CharField(required=False, max_length=100)
    container_extension = serializers.RegexField(r"^[a-zA-Z0-9]{1,10}$", required=False)
    genre = serializers.CharField(
        required=False,
        max_length=2000,
        help_text="One or more comma-separated terms; a title matches if its genre contains any of them.",
    )
    anime_mode = serializers.ChoiceField(choices=["only", "exclude"], required=False)
    adult_mode = serializers.ChoiceField(choices=["only", "exclude"], required=False)
    added_after_days = serializers.IntegerField(
        min_value=1, max_value=36500, required=False
    )
    added_since = serializers.DateField(required=False)
    added_until = serializers.DateField(required=False)
    released_since = serializers.DateField(required=False)
    released_until = serializers.DateField(required=False)

    def validate(self, data):
        for start, end in (
            ("added_since", "added_until"),
            ("released_since", "released_until"),
        ):
            if data.get(start) and data.get(end) and data[start] > data[end]:
                raise serializers.ValidationError(
                    {end: "The end date must not precede the start date."}
                )
        for field, normalize in (
            ("audio_language", normalize_language_code),
            ("subtitle_language", normalize_language_code),
            ("resolution", normalize_resolution),
            ("video_feature", normalize_video_feature),
        ):
            if field in data:
                try:
                    data[field] = normalize(data[field])
                except ValueError as exc:
                    raise serializers.ValidationError({field: str(exc)}) from exc
        return data


class LibraryReferenceSerializer(StrictSerializer):
    content_type = serializers.ChoiceField(choices=["movie", "series"])
    id = serializers.IntegerField(min_value=1)


class LibrarySelectionSerializer(StrictSerializer):
    items = LibraryReferenceSerializer(many=True, required=False, max_length=10000)
    all_matching = serializers.BooleanField(default=False)
    filters = LibraryFilterSerializer(required=False)
    excluded = LibraryReferenceSerializer(many=True, required=False, max_length=10000)

    def validate(self, data):
        if bool(data.get("items")) == bool(data.get("all_matching")):
            raise serializers.ValidationError(
                "Select specific items or explicitly select all matching items."
            )
        if data.get("excluded") and not data.get("all_matching"):
            raise serializers.ValidationError("Exclusions require all matching items.")
        return data


class LibraryBulkSerializer(LibrarySelectionSerializer):
    operation = serializers.ChoiceField(
        choices=["cleanup", "enrich", "lock", "unlock", "reset", "block", "unblock"]
    )
    include_protected = serializers.BooleanField(
        default=False,
        help_text="Explicit one-time permission to process protected titles in this cleanup or enrichment job, without unlocking them.",
    )
    search_missing = serializers.BooleanField(required=False)
    title_rules = serializers.JSONField(required=False)
    removal_rules = serializers.JSONField(required=False)
    year_rules = serializers.JSONField(required=False)

    def validate(self, data):
        data = super().validate(data)
        if data["include_protected"] and data["operation"] not in {"cleanup", "enrich"}:
            raise serializers.ValidationError(
                "A one-time protection override is only available for cleanup or enrichment."
            )
        if data["operation"] not in {"cleanup", "enrich"} and any(
            key in data
            for key in ("search_missing", "title_rules", "removal_rules", "year_rules")
        ):
            raise serializers.ValidationError(
                "Run options require cleanup or enrichment."
            )
        return data


class LibraryCleanupPreviewSerializer(LibrarySelectionSerializer):
    scope = serializers.ChoiceField(
        choices=["selection", "catalog", "category"], default="selection"
    )
    search = serializers.CharField(required=False, allow_blank=True, max_length=255)
    missing_tmdb_only = serializers.BooleanField(default=False)
    page = serializers.IntegerField(min_value=1, default=1)
    page_size = serializers.IntegerField(min_value=1, max_value=50, default=25)
    title_rules = serializers.JSONField(required=False)
    removal_rules = serializers.JSONField(required=False)
    year_rules = serializers.JSONField(required=False)
    account = serializers.IntegerField(min_value=1, required=False)
    category = serializers.IntegerField(min_value=1, required=False)
    title_cleanup = serializers.JSONField(required=False)

    def validate(self, data):
        if data["scope"] != "category" and any(
            field in data for field in ("account", "category", "title_cleanup")
        ):
            raise serializers.ValidationError(
                "Account, category and title cleanup require a category preview."
            )
        if data["scope"] == "selection":
            return super().validate(data)
        if data["scope"] == "category":
            if not data.get("account") or not data.get("category"):
                raise serializers.ValidationError("Choose an account and category.")
            if any(
                data.get(field)
                for field in ("items", "all_matching", "filters", "excluded")
            ):
                raise serializers.ValidationError(
                    "Choose only one category for this preview."
                )
            if data.get("search") or data["missing_tmdb_only"]:
                raise serializers.ValidationError(
                    "Use the selected category without catalog search filters."
                )
            return data
        if any(
            data.get(field)
            for field in ("items", "all_matching", "filters", "excluded")
        ):
            raise serializers.ValidationError("Use search for a catalog preview.")
        if not data.get("search") and not data["missing_tmdb_only"]:
            raise serializers.ValidationError(
                "Enter a title or choose Without TMDB ID."
            )
        return data


class LibraryConnectionStatusSerializer(StrictSerializer):
    status = serializers.ChoiceField(
        choices=["not_configured", "unchecked", "connected", "error"]
    )
    checked_at = serializers.DateTimeField(allow_null=True)
    detail = serializers.CharField(allow_blank=True)


class LibraryConnectionTestSerializer(StrictSerializer):
    api_token = serializers.CharField(required=False, max_length=2048, write_only=True)


class LibrarySettingsSerializer(StrictSerializer):
    languages = serializers.ListField(
        child=serializers.CharField(max_length=5),
        min_length=1,
        required=False,
    )
    api_token = serializers.CharField(
        write_only=True, required=False, allow_blank=True, max_length=2048
    )
    clear_api_token = serializers.BooleanField(write_only=True, required=False)
    token_configured = serializers.BooleanField(read_only=True)
    token_source = serializers.CharField(read_only=True)
    auto_enrich = serializers.BooleanField(required=False)
    connection = LibraryConnectionStatusSerializer(read_only=True)
    match_missing = serializers.BooleanField(required=False)
    prefer_artwork = serializers.BooleanField(required=False)
    title_rules = serializers.JSONField(required=False)
    removal_rules = serializers.JSONField(required=False)
    year_rules = serializers.JSONField(required=False)


class LibrarySettingsUpdateSerializer(LibrarySettingsSerializer):
    languages = serializers.ListField(
        child=serializers.CharField(max_length=5),
        min_length=1,
        max_length=MAX_METADATA_LANGUAGES,
        required=False,
        help_text="Languages in Library display order; at most five in a new selection.",
    )


class LibraryTranslationSerializer(StrictSerializer):
    title = serializers.CharField(max_length=255, required=False, allow_blank=True)
    overview = serializers.CharField(max_length=20000, required=False, allow_blank=True)
    tagline = serializers.CharField(max_length=2000, required=False, allow_blank=True)


class LibraryExternalIDsSerializer(StrictSerializer):
    imdb_id = serializers.RegexField(r"^tt[0-9]+$", required=False, allow_blank=True)
    tvdb_id = serializers.RegexField(r"^[0-9]+$", required=False, allow_blank=True)
    wikidata_id = serializers.RegexField(r"^Q[0-9]+$", required=False, allow_blank=True)


class LibraryCanonicalMetadataSerializer(StrictSerializer):
    localized = serializers.DictField(
        child=LibraryTranslationSerializer(), required=False
    )
    release_date = serializers.DateField(required=False, allow_null=True)
    runtime_minutes = serializers.IntegerField(
        min_value=0, max_value=144000, required=False, allow_null=True
    )
    age_rating = serializers.CharField(max_length=50, required=False, allow_blank=True)
    country = serializers.CharField(max_length=2000, required=False, allow_blank=True)
    director = serializers.CharField(max_length=2000, required=False, allow_blank=True)
    actors = serializers.CharField(max_length=4000, required=False, allow_blank=True)
    crew = serializers.CharField(max_length=4000, required=False, allow_blank=True)
    youtube_trailer = serializers.CharField(
        max_length=2048, required=False, allow_blank=True
    )
    poster_url = serializers.URLField(max_length=500, required=False, allow_blank=True)
    backdrop_url = serializers.URLField(
        max_length=500, required=False, allow_blank=True
    )
    keywords = serializers.ListField(
        child=serializers.CharField(max_length=200), max_length=100, required=False
    )
    is_anime = serializers.BooleanField(required=False)
    adult = serializers.BooleanField(required=False)
    external_ids = LibraryExternalIDsSerializer(required=False)

    def validate_localized(self, value):
        import re

        if len(value) > 30 or any(
            not re.fullmatch(r"[a-z]{2}(?:-[A-Z]{2})?", key) for key in value
        ):
            raise serializers.ValidationError(
                "Use at most 30 language-region translations, such as de-DE."
            )
        return value


class LibraryContentPatchSerializer(LibraryReferenceSerializer):
    tmdb_id = serializers.RegexField(r"^[1-9][0-9]{0,14}$", required=False)
    metadata = LibraryCanonicalMetadataSerializer(required=False)
    clean_title = serializers.CharField(
        max_length=255, required=False, allow_blank=True
    )
    display_name = serializers.CharField(
        max_length=255, required=False, allow_blank=True
    )
    description = serializers.CharField(
        max_length=20000, required=False, allow_blank=True
    )
    year = serializers.IntegerField(
        min_value=1800, max_value=2200, required=False, allow_null=True
    )
    genre = serializers.CharField(max_length=255, required=False, allow_blank=True)
    rating = serializers.CharField(max_length=10, required=False, allow_blank=True)

    def validate_rating(self, value):
        if value == "":
            return value
        try:
            rating = float(value)
        except ValueError as exc:
            raise serializers.ValidationError("Use a rating between 0 and 10.") from exc
        if not 0 <= rating <= 10:
            raise serializers.ValidationError("Use a rating between 0 and 10.")
        return value


class LibraryLookupSerializer(StrictSerializer):
    content_type = serializers.ChoiceField(choices=["movie", "series"])
    query = serializers.CharField(max_length=255, required=False, allow_blank=True)
    year = serializers.IntegerField(
        min_value=1800, max_value=2200, required=False, allow_null=True
    )
    tmdb_id = serializers.RegexField(r"^[1-9][0-9]{0,14}$", required=False)

    def validate(self, data):
        if not data.get("tmdb_id") and not data.get("query"):
            raise serializers.ValidationError("Enter a title or a TMDB ID.")
        return data


class LibraryMatchSerializer(LibraryReferenceSerializer):
    tmdb_id = serializers.RegexField(r"^[1-9][0-9]{0,14}$")
    source = serializers.BooleanField(default=False)


class LibrarySourcePatchSerializer(LibrarySelectionSerializer):
    items = LibraryReferenceSerializer(
        many=True, required=False, min_length=1, max_length=1000
    )
    manual_metadata = serializers.JSONField(required=False)
    tmdb_id = serializers.RegexField(r"^[1-9][0-9]{0,14}$", required=False)
    target_id = serializers.IntegerField(min_value=1, required=False)
    create_from_provider = serializers.BooleanField(required=False, default=False)
    title_name = serializers.CharField(max_length=255, required=False)
    title_year = serializers.IntegerField(
        min_value=1800, max_value=2200, required=False, allow_null=True
    )

    def validate(self, data):
        data = super().validate(data)
        if (
            data.get("all_matching")
            and data.get("filters", {}).get("view") != "sources"
        ):
            raise serializers.ValidationError("Choose the filtered source view.")
        targets = sum(
            bool(data.get(field))
            for field in ("tmdb_id", "target_id", "create_from_provider")
        )
        if targets > 1:
            raise serializers.ValidationError("Choose only one canonical target.")
        if targets and (data.get("all_matching") or len(data["items"]) != 1):
            raise serializers.ValidationError("Move exactly one source at a time.")
        if not data["create_from_provider"] and any(
            field in data for field in ("title_name", "title_year")
        ):
            raise serializers.ValidationError(
                "A title name and year are only used when creating a title from a source."
            )
        if "title_year" in data and "title_name" not in data:
            raise serializers.ValidationError(
                {"title_name": "Enter the new title name."}
            )
        if not data.get("manual_metadata") and not targets:
            raise serializers.ValidationError(
                "Change source metadata or choose a canonical title."
            )
        if targets and len({row["content_type"] for row in data["items"]}) != 1:
            raise serializers.ValidationError(
                "Choose only movies or only series for a canonical assignment."
            )
        if data.get("all_matching"):
            return data
        data["items"] = [
            {"content_type": kind, "id": pk}
            for kind, pk in sorted(
                {(row["content_type"], row["id"]) for row in data["items"]}
            )
        ]
        return data


class LibraryCanonicalTargetSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    year = serializers.IntegerField(allow_null=True)
    tmdb_id = serializers.CharField(allow_blank=True)
    source_count = serializers.IntegerField()


class LibraryCanonicalTargetsSerializer(serializers.Serializer):
    results = LibraryCanonicalTargetSerializer(many=True)


class LibraryCategoryCleanupSerializer(StrictSerializer):
    category = serializers.IntegerField(min_value=1)
    account = serializers.IntegerField(min_value=1)
    title_cleanup = serializers.JSONField()


class LibraryItemSerializer(serializers.Serializer):
    key = serializers.CharField()
    id = serializers.IntegerField()
    uuid = serializers.CharField()
    content_id = serializers.IntegerField()
    content_type = serializers.ChoiceField(choices=["movie", "series"])
    source_id = serializers.IntegerField(allow_null=True)
    source_count = serializers.IntegerField()
    name = serializers.CharField()
    provider_name = serializers.CharField()
    display_name = serializers.CharField(allow_blank=True)
    clean_title = serializers.CharField(allow_blank=True)
    year = serializers.IntegerField(allow_null=True)
    description = serializers.CharField(allow_blank=True)
    genre = serializers.CharField(allow_blank=True)
    rating = serializers.CharField(allow_blank=True)
    duration_secs = serializers.IntegerField(allow_null=True)
    episode_count = serializers.IntegerField(required=False)
    is_adult = serializers.BooleanField(required=False)
    tmdb_id = serializers.CharField(allow_blank=True)
    imdb_id = serializers.CharField(allow_blank=True)
    metadata_locked = serializers.BooleanField()
    library_blocked = serializers.BooleanField()
    metadata_status = serializers.CharField(allow_blank=True)
    metadata = serializers.JSONField()
    metadata_languages = serializers.ListField(
        child=serializers.CharField(), required=False
    )
    metadata_summary = serializers.JSONField()
    metadata_origins = serializers.JSONField(
        required=False,
        help_text="Origin of each displayed value: category, series, provider, observed or manual.",
    )
    poster_url = serializers.CharField(allow_blank=True)
    backdrop_url = serializers.CharField(required=False, allow_blank=True)
    library_added_at = serializers.DateTimeField()
    enriched_at = serializers.DateTimeField(allow_null=True)
    account = serializers.JSONField(required=False)
    category = serializers.JSONField(required=False)
    provider_id = serializers.CharField(required=False)
    container_extension = serializers.CharField(required=False, allow_blank=True)
    effective_metadata = serializers.JSONField(required=False)
    manual_metadata = serializers.JSONField(required=False)
    locked_fields = serializers.ListField(child=serializers.CharField(), required=False)
    title_cleanup = serializers.JSONField(required=False)


class LibraryDetailRequestSerializer(LibraryReferenceSerializer):
    source_id = serializers.IntegerField(min_value=1, required=False)
    preferred_account = serializers.IntegerField(min_value=1, required=False)
    season = serializers.IntegerField(
        min_value=-1,
        required=False,
        help_text="Defaults to the first available season; -1 selects episodes without a season number.",
    )
    page = serializers.IntegerField(min_value=1, default=1)
    page_size = serializers.IntegerField(min_value=1, max_value=100, default=25)


class LibraryProviderMetadataSerializer(serializers.Serializer):
    name = serializers.CharField()
    poster_url = serializers.CharField(allow_blank=True)
    backdrop_url = serializers.CharField(allow_blank=True)
    description = serializers.CharField(allow_blank=True, allow_null=True)
    year = serializers.IntegerField(allow_null=True)
    release_date = serializers.CharField(allow_blank=True, allow_null=True)
    genre = serializers.CharField(allow_blank=True, allow_null=True)
    rating = serializers.CharField(allow_blank=True, allow_null=True)
    director = serializers.CharField(allow_blank=True, allow_null=True)
    actors = serializers.CharField(allow_blank=True, allow_null=True)
    crew = serializers.CharField(allow_blank=True, allow_null=True)
    country = serializers.CharField(allow_blank=True, allow_null=True)
    age_rating = serializers.CharField(allow_blank=True, allow_null=True)
    tmdb_id = serializers.CharField(allow_blank=True, allow_null=True)
    imdb_id = serializers.CharField(allow_blank=True, allow_null=True)
    youtube_trailer = serializers.CharField(allow_blank=True, allow_null=True)
    duration_secs = serializers.IntegerField(allow_null=True)
    technical = serializers.JSONField()
    details_loaded = serializers.BooleanField()


class LibraryNamedReferenceSerializer(serializers.Serializer):
    id = serializers.IntegerField(allow_null=True)
    name = serializers.CharField(allow_blank=True)


class LibraryDetailSourceSerializer(serializers.Serializer):
    source_id = serializers.IntegerField()
    content_id = serializers.IntegerField()
    content_type = serializers.ChoiceField(choices=["movie", "series"])
    provider_name = serializers.CharField()
    account = LibraryNamedReferenceSerializer()
    category = LibraryNamedReferenceSerializer()
    provider_id = serializers.CharField()
    container_extension = serializers.CharField(allow_blank=True)
    effective_metadata = serializers.JSONField()
    manual_metadata = serializers.JSONField()
    locked_fields = serializers.ListField(child=serializers.CharField())
    provider = LibraryProviderMetadataSerializer()


class LibraryDetailEpisodeSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    content_id = serializers.IntegerField()
    uuid = serializers.UUIDField()
    name = serializers.CharField()
    season_number = serializers.IntegerField(allow_null=True)
    episode_number = serializers.IntegerField(allow_null=True)
    description = serializers.CharField(allow_blank=True)
    duration_secs = serializers.IntegerField(allow_null=True)
    air_date = serializers.DateField(allow_null=True)
    rating = serializers.CharField(allow_blank=True)
    imdb_id = serializers.CharField(allow_blank=True)
    tmdb_id = serializers.CharField(allow_blank=True)
    stream_id = serializers.CharField()
    account_id = serializers.IntegerField()
    container_extension = serializers.CharField(allow_blank=True)
    poster_url = serializers.CharField(allow_blank=True)
    resolution = serializers.CharField(allow_blank=True)
    video_codec = serializers.CharField(allow_blank=True)
    genre = serializers.CharField(allow_blank=True)
    director = serializers.CharField(allow_blank=True)
    actors = serializers.CharField(allow_blank=True)
    technical = serializers.JSONField()


class LibraryDetailSeasonSerializer(serializers.Serializer):
    number = serializers.IntegerField(allow_null=True)
    count = serializers.IntegerField()


class LibraryDetailSerializer(serializers.Serializer):
    canonical = LibraryItemSerializer()
    sources = LibraryDetailSourceSerializer(many=True)
    selected_source_id = serializers.IntegerField()
    selected_season = serializers.IntegerField(required=False, allow_null=True)
    seasons = LibraryDetailSeasonSerializer(many=True, required=False)
    episodes = LibraryDetailEpisodeSerializer(many=True, required=False)
    episode_count = serializers.IntegerField(required=False)
    episode_page = serializers.IntegerField(required=False)
    episode_page_size = serializers.IntegerField(required=False)


class LibraryStateSerializer(serializers.Serializer):
    pending_enrichment_count = serializers.IntegerField(required=False)
    status = serializers.CharField()
    progress = serializers.JSONField()
    error = serializers.CharField(allow_blank=True)
    task_id = serializers.CharField(allow_blank=True)
    started_at = serializers.DateTimeField(required=False, allow_null=True)
    completed_at = serializers.DateTimeField(required=False, allow_null=True)
    updated_at = serializers.DateTimeField(required=False)


class LibraryPreviewSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    protected_count = serializers.IntegerField(required=False)
    blocked_count = serializers.IntegerField(required=False)
    results = serializers.ListField(child=serializers.DictField())
    page = serializers.IntegerField(required=False)
    page_size = serializers.IntegerField(required=False)


class LibraryOptionsSerializer(serializers.Serializer):
    accounts = serializers.ListField(child=serializers.DictField())
    categories = serializers.ListField(child=serializers.DictField())
    audio_languages = serializers.ListField(child=serializers.CharField())
    subtitle_languages = serializers.ListField(child=serializers.CharField())
    resolution = serializers.ListField(child=serializers.CharField())
    video_features = serializers.ListField(child=serializers.CharField())
    container_extensions = serializers.ListField(child=serializers.CharField())
    totals = serializers.DictField(
        child=serializers.IntegerField(),
        required=False,
        help_text="Visible canonical titles per content type, independent of filters.",
    )


class LibraryResultSerializer(serializers.Serializer):
    count = serializers.IntegerField(required=False)
    results = serializers.JSONField(required=False)
    metadata = serializers.JSONField(required=False)
    state = LibraryStateSerializer(required=False)
