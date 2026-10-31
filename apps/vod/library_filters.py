"""Database-side Library filters using the source metadata precedence."""

from datetime import timedelta

from django.db.models import (
    Case,
    CharField,
    Exists,
    F,
    JSONField,
    OuterRef,
    Q,
    Subquery,
    Value,
    When,
)
from django.db.models.fields.json import KeyTransform, KeyTextTransform
from django.db.models.functions import Coalesce
from django.utils import timezone

from .models import M3UEpisodeRelation, M3UVODCategoryRelation

TECHNICAL_FILTERS = {
    "audio_language": "audio_languages",
    "subtitle_language": "subtitle_languages",
    "resolution": "resolution",
    "video_feature": "video_features",
}


SOURCE_METADATA_PATHS = (
    "manual_metadata",
    "observed_metadata",
    "declared_metadata",
    "custom_properties__detailed_info",
    "custom_properties__basic_data",
    "custom_properties__info",
)


def own_metadata_value(field, default=None):
    """Resolve a value stored on the source itself, above category defaults."""
    cases = []
    for path in SOURCE_METADATA_PATHS:
        present = Q(**{f"{path}__has_key": field}) & ~Q(**{f"{path}__{field}": None})
        cases.append(When(present, then=KeyTransform(field, F(path))))
    return Case(*cases, default=default, output_field=JSONField())


def metadata_value(field):
    category = M3UVODCategoryRelation.objects.filter(
        m3u_account_id=OuterRef("m3u_account_id"),
        category_id=OuterRef("category_id"),
    ).values(f"metadata_defaults__{field}")[:1]
    return own_metadata_value(field, default=Subquery(category))


def _video_height(*keys):
    expression = "custom_properties"
    for key in keys:
        expression = KeyTransform(key, expression)
    return KeyTextTransform("height", KeyTransform("video", expression))


# Provider episode details report the actual video height of a series source.
EPISODE_HEIGHT = Coalesce(
    _video_height("info", "info"),
    _video_height("info"),
    _video_height(),
    output_field=CharField(),
)


def series_episodes(series_relation):
    """Episode sources of the same provider series, as used by the preview."""
    return M3UEpisodeRelation.objects.filter(
        series_relation=series_relation,
        m3u_account_id=F("series_relation__m3u_account_id"),
        episode__series_id=F("series_relation__series_id"),
    ).annotate(_height=EPISODE_HEIGHT)


def series_resolution_match(queryset, value):
    """Match the provider episode resolution unless the source sets its own."""
    own, effective = "_library_own_resolution", "_library_resolution"
    queryset = queryset.annotate(
        **{own: own_metadata_value("resolution"), effective: metadata_value("resolution")}
    )
    episodes = series_episodes(OuterRef("pk"))
    inherited = Q(**{f"{own}__isnull": True})
    match = Q(**{own: value}) | (
        inherited
        & ~Exists(episodes.filter(_height__isnull=False))
        & Q(**{effective: value})
    )
    height = value[:-1] if value.endswith("p") else ""
    if height.isdigit():
        match |= inherited & Exists(episodes.filter(_height=str(int(height))))
    return queryset.filter(match)


def technical_values(queryset):
    return queryset.annotate(
        **{
            f"_library_{field}": metadata_value(field)
            for field in TECHNICAL_FILTERS.values()
        }
    )


def filter_relations(queryset, kind, filters):
    for parameter, field in TECHNICAL_FILTERS.items():
        value = filters.get(parameter)
        if not value:
            continue
        if field == "resolution" and kind == "series":
            queryset = series_resolution_match(queryset, value)
            continue
        name = f"_library_{field}"
        queryset = queryset.annotate(**{name: metadata_value(field)})
        queryset = queryset.filter(
            **{
                name if field == "resolution" else f"{name}__contains": (
                    value if field == "resolution" else [value]
                )
            }
        )
    if filters.get("container_extension"):
        queryset = (
            queryset.filter(container_extension__iexact=filters["container_extension"])
            if kind == "movie"
            else queryset.none()
        )
    genres = [part.strip() for part in (filters.get("genre") or "").split(",")]
    if any(genres):
        field = f"{kind}__tmdb_metadata"
        matching = Q()
        for genre in filter(None, genres):
            matching |= Q(**{f"{field}__genres__icontains": genre}) | (
                ~Q(**{f"{field}__has_key": "genres"})
                & Q(**{f"{kind}__genre__icontains": genre})
            )
        queryset = queryset.filter(matching)
    if filters.get("anime_mode"):
        anime = Q(**{f"{kind}__tmdb_metadata__is_anime": True}) & Q(
            **{f"{kind}__tmdb_metadata__is_anime__isnull": False}
        )
        queryset = queryset.filter(anime if filters["anime_mode"] == "only" else ~anime)
    if filters.get("adult_mode"):
        adult = Q(**{f"{kind}__tmdb_metadata__adult": True}) & Q(
            **{f"{kind}__tmdb_metadata__adult__isnull": False}
        )
        if kind == "movie":
            adult |= Q(movie__is_adult=True)
        queryset = queryset.filter(adult if filters["adult_mode"] == "only" else ~adult)
    if filters.get("added_after_days"):
        queryset = queryset.filter(
            **{
                f"{kind}__library_added_at__gte": timezone.now()
                - timedelta(days=filters["added_after_days"])
            }
        )
    if filters.get("added_since"):
        queryset = queryset.filter(
            **{f"{kind}__library_added_at__date__gte": filters["added_since"]}
        )
    if filters.get("added_until"):
        queryset = queryset.filter(
            **{f"{kind}__library_added_at__date__lte": filters["added_until"]}
        )
    if filters.get("released_since") or filters.get("released_until"):
        queryset = queryset.annotate(
            _library_release_date=Case(
                When(
                    Q(**{f"{kind}__tmdb_metadata__has_key": "release_date"}),
                    then=KeyTextTransform("release_date", F(f"{kind}__tmdb_metadata")),
                ),
                default=KeyTextTransform(
                    "release_date", F(f"{kind}__custom_properties")
                ),
                output_field=CharField(),
            )
        ).filter(_library_release_date__regex=r"^\d{4}-\d{2}-\d{2}$")
        for parameter, lookup in (("released_since", "gte"), ("released_until", "lte")):
            if filters.get(parameter):
                queryset = queryset.filter(
                    **{f"_library_release_date__{lookup}": str(filters[parameter])}
                )
    return queryset


def episode_resolutions(queryset):
    """Provider episode resolutions of series sources without their own value."""
    from .library_preview import video_facts

    inherited = queryset.annotate(_own=own_metadata_value("resolution")).filter(
        _own__isnull=True
    )
    heights = (
        M3UEpisodeRelation.objects.filter(
            series_relation__in=inherited.values("pk"),
            m3u_account_id=F("series_relation__m3u_account_id"),
            episode__series_id=F("series_relation__series_id"),
        )
        .annotate(_height=EPISODE_HEIGHT)
        .exclude(_height__isnull=True)
        .order_by()
        .values_list("_height", flat=True)
        .distinct()
    )
    return {
        label
        for label in (video_facts({"height": height})["resolution"] for height in heights)
        if label
    }


def available_values(querysets):
    """Read actual source values once, without N+1 category lookups."""
    values = {field: set() for field in TECHNICAL_FILTERS.values()}
    values.update(container_extensions=set())
    for kind, queryset in querysets:
        fields = [f"_library_{field}" for field in TECHNICAL_FILTERS.values()]
        series = kind == "series"
        rows = (
            technical_values(queryset)
            .annotate(
                # Provider episode resolutions replace an inherited category value.
                _library_episode_video=(
                    Exists(
                        series_episodes(OuterRef("pk")).filter(_height__isnull=False)
                    )
                    if series
                    else Value(False)
                ),
                _library_own_resolution=own_metadata_value("resolution"),
            )
            .annotate(
                _library_container=(
                    F("container_extension")
                    if kind == "movie"
                    else Value("", output_field=CharField())
                ),
            )
            .values(
                *fields,
                "_library_container",
                "_library_episode_video",
                "_library_own_resolution",
            )
        )
        for row in rows.iterator(chunk_size=1000):
            episode_values = (
                row["_library_episode_video"] and row["_library_own_resolution"] is None
            )
            for field in TECHNICAL_FILTERS.values():
                if field == "resolution" and episode_values:
                    continue
                value = row[f"_library_{field}"]
                items = (
                    [value]
                    if field == "resolution"
                    else value if isinstance(value, list) else []
                )
                values[field].update(
                    item for item in items if isinstance(item, str) and item
                )
            if row["_library_container"]:
                values["container_extensions"].add(row["_library_container"].lower())
        if series:
            values["resolution"].update(episode_resolutions(queryset))
    return {field: sorted(items, key=str.casefold) for field, items in values.items()}
