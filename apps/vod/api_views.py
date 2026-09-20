from rest_framework import viewsets, status
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework.filters import SearchFilter, OrderingFilter
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import AllowAny
from rest_framework.exceptions import (
    PermissionDenied,
    ValidationError as DRFValidationError,
)
from django_filters.rest_framework import DjangoFilterBackend
from django.db import connection, transaction
from django.db.models import Count, Prefetch, Q, Sum
from django.db.models.expressions import RawSQL
from django.db.models.fields.json import KeyTextTransform
from django.utils.dateparse import parse_date, parse_datetime
import django_filters
import logging
import os
import re
from datetime import datetime, time, timedelta
from apps.accounts.permissions import (
    Authenticated,
    permission_classes_by_action,
)
from core.models import CoreSettings
from .models import (
    Series, VODCategory, Movie, Episode, VODLogo,
    M3USeriesRelation, M3UMovieRelation, M3UEpisodeRelation, M3UVODCategoryRelation,
    VODAccessPolicy, VODPlaybackSession,
    VODMovieProfileSelection, VODSeriesProfileSelection, VODMetadataState,
)
from .serializers import (
    MovieSerializer,
    EpisodeSerializer,
    SeriesSerializer,
    VODCategorySerializer,
    VODLogoSerializer,
    M3UMovieRelationSerializer,
    M3USeriesRelationSerializer,
    M3UEpisodeRelationSerializer,
    VODAccessPolicySerializer,
    VODPlaybackSessionSerializer,
    M3UVODCategoryRelationSerializer,
    EpisodeWithProvidersSerializer,
    MovieProviderInfoSerializer,
    SeriesProviderInfoSerializer,
    UnifiedContentListSerializer,
    VODLogoBulkDeleteRequestSerializer,
    VODLogoBulkDeleteResponseSerializer,
    VODLogoCleanupResponseSerializer,
)
from .image_proxy import (
    is_proxyable_image_url,
    prefer_relation_artwork,
    rewrite_backdrop_paths,
    rewrite_single_image_url,
    serve_vod_image,
    vod_image_action,
    vod_image_url_parts,
    vodlogo_cache_url,
)
from core.image_proxy import RawImageContentNegotiationMixin
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiResponse
from drf_spectacular.types import OpenApiTypes
from .tasks import refresh_series_episodes, refresh_movie_advanced_data
from .utils import (
    get_series_display_name,
    is_vod_movies_enabled,
    is_vod_series_enabled,
    parse_category_filter_value,
)
from .metadata import (
    IMAGE_VIDEO_CODECS,
    compatible_video_features,
    effective_relation_metadata,
    merge_episode_provider_video_metadata,
    normalize_language_code,
    normalize_video_features,
    relation_declared_metadata,
    summarize_series_relation_metadata,
)
from .catalog_cache import catalog_generation, safe_cache_get, safe_cache_set
from django.utils import timezone
from rest_framework.utils.urls import replace_query_param, remove_query_param

logger = logging.getLogger(__name__)
PLAYBACK_METADATA_INLINE_TITLE_LIMIT = 25


def _tmdb_content_payload(content):
    """Public, provider-safe TMDB projection for movie/series detail views."""
    metadata = (
        content.tmdb_metadata if isinstance(content.tmdb_metadata, dict) else {}
    )
    from .tmdb import apply_manual_overrides

    metadata = apply_manual_overrides(
        metadata,
        metadata.get("_manual_overrides") or {},
    )
    external_ids = metadata.get("external_ids") or {}
    effective_id = str(
        content.tmdb_match_id
        or metadata.get("id")
        or content.tmdb_id
        or ""
    )
    languages = CoreSettings.get_tmdb_languages()
    return {
        "id": effective_id,
        "provider_id": str(content.tmdb_id or ""),
        "match_method": metadata.get("match_method") or "",
        "status": content.tmdb_status or "",
        "metadata_auto_locked": _tmdb_auto_lookup_locked(content),
        "candidate_count": int(metadata.get("candidate_count") or 0),
        "clean_title": content.clean_title or "",
        "external_ids": {
            "imdb_id": str(
                external_ids.get("imdb_id")
                or metadata.get("imdb_id")
                or content.imdb_id
                or ""
            ),
            "tvdb_id": str(
                external_ids.get("tvdb_id") or metadata.get("tvdb_id") or ""
            ),
            "wikidata_id": str(
                external_ids.get("wikidata_id")
                or metadata.get("wikidata_id")
                or ""
            ),
        },
        "localized": metadata.get("localized") or {},
        "languages": languages,
        "primary_language": languages[0] if languages else "",
        "secondary_language": languages[1] if len(languages) > 1 else "",
        "overview": metadata.get("overview") or "",
        "release_date": metadata.get("release_date") or "",
        "runtime_minutes": metadata.get("runtime_minutes"),
        "rating": metadata.get("rating"),
        "genres": metadata.get("genres") or [],
        "director": metadata.get("director") or "",
        "actors": metadata.get("actors") or "",
        "crew": metadata.get("crew") or "",
        "country": metadata.get("country") or "",
        "age_rating": metadata.get("age_rating") or "",
        "youtube_trailer": metadata.get("youtube_trailer") or "",
        "keywords": metadata.get("keywords") or [],
        "is_anime": bool(metadata.get("is_anime", False)),
        "adult": bool(metadata.get("adult", False)),
        "poster_url": metadata.get("poster_url") or "",
        "backdrop_url": metadata.get("backdrop_url") or "",
    }


def _tmdb_auto_lookup_locked(content):
    return bool(content.tmdb_enrichment_signature)


def _canonical_library_title(content):
    if content.tmdb_status in {"matched", "manual"} and content.display_name:
        return content.display_name
    return content.clean_title or content.display_name or content.name


def _canonical_provider_payload(content):
    """Provider-derived fields stored on the shared canonical title."""
    properties = content.custom_properties or {}
    actors = properties.get("actors") or properties.get("cast") or ""
    return {
        "id": content.id,
        "name": content.display_name or content.name,
        "description": content.description or "",
        "year": content.year,
        "rating": content.rating or "",
        "genre": content.genre or "",
        "duration_secs": getattr(content, "duration_secs", None),
        "release_date": properties.get("release_date") or "",
        "director": properties.get("director") or "",
        "actors": actors,
        "cast": actors,
        "crew": properties.get("crew") or "",
        "country": properties.get("country") or "",
        "age": properties.get("age") or "",
        "youtube_trailer": properties.get("youtube_trailer") or "",
        "backdrop_path": properties.get("backdrop_path") or [],
        "movie_image": properties.get("movie_image") or "",
    }


def _relation_property(relation, *keys):
    payload = relation.custom_properties or {}
    candidates = [payload]
    for key in ("detailed_info", "basic_data", "movie_data", "series_data"):
        nested = payload.get(key)
        if isinstance(nested, dict):
            candidates.append(nested)
    for candidate in candidates:
        for key in keys:
            value = candidate.get(key)
            if value not in (None, "", 0, "0"):
                return value
    return ""


def _relation_provider_title(relation):
    canonical = (
        relation.movie
        if isinstance(relation, M3UMovieRelation)
        else relation.series
    )
    return str(
        _relation_property(relation, "name", "title") or canonical.name or ""
    ).strip()


def _relation_provider_year(relation):
    raw_value = _relation_property(
        relation,
        "year",
        "release_date",
        "releasedate",
        "releaseDate",
        "first_air_date",
    )
    match = re.search(r"(?:19|20)\d{2}", str(raw_value or ""))
    if match:
        return int(match.group(0))
    canonical = (
        relation.movie
        if isinstance(relation, M3UMovieRelation)
        else relation.series
    )
    return canonical.year


def _relation_import_year(relation, year_rules):
    """Return the year list import would recognize before title cleanup."""
    raw_year = _relation_property(relation, "year")
    try:
        year = int(str(raw_year).strip())
        if 1900 <= year <= timezone.now().year + 5:
            return year
    except (TypeError, ValueError):
        pass
    for field in ("releaseDate", "release_date"):
        raw_date = str(_relation_property(relation, field) or "").strip()
        try:
            year = int(raw_date.split("-", 1)[0])
        except (TypeError, ValueError):
            continue
        if 1900 <= year <= timezone.now().year + 5:
            return year
    from .tmdb import extract_year_from_title

    return extract_year_from_title(
        _relation_provider_title(relation),
        rules=year_rules,
    )


def _relation_provider_external_ids(relation):
    return {
        "tmdb_id": str(_relation_property(relation, "tmdb_id", "tmdb") or ""),
        "imdb_id": str(_relation_property(relation, "imdb_id", "imdb") or ""),
    }


def _tmdb_target_defaults(metadata, media_type):
    from .tmdb import preferred_title

    languages = CoreSettings.get_tmdb_languages()
    localized = metadata.get("localized") or {}
    primary = localized.get(languages[0]) or {}
    title = preferred_title(metadata, languages[0]) or f"TMDB {metadata['id']}"
    release_date = str(metadata.get("release_date") or "")
    year_match = re.match(r"(\d{4})", release_date)
    defaults = {
        "name": title,
        "display_name": title,
        "clean_title": title,
        "description": str(primary.get("overview") or metadata.get("overview") or ""),
        "year": int(year_match.group(1)) if year_match else None,
        "rating": str(metadata.get("rating") or ""),
        "genre": ", ".join(
            row.get("name") or "" for row in metadata.get("genres") or []
            if row.get("name")
        ),
        "tmdb_match_id": str(metadata.get("id") or ""),
        "tmdb_imdb_id": str(metadata.get("imdb_id") or ""),
        "tmdb_poster_url": str(metadata.get("poster_url") or ""),
        "tmdb_backdrop_url": str(metadata.get("backdrop_url") or ""),
        "tmdb_metadata": {**metadata, "status": "matched"},
        "tmdb_status": "matched",
        "tmdb_enriched_at": timezone.now(),
        "tmdb_enrichment_signature": "",
    }
    if media_type == "movie" and metadata.get("runtime_minutes"):
        defaults["duration_secs"] = int(metadata["runtime_minutes"] * 60)
    return defaults


def _materialize_tmdb_target(media_type, tmdb_id):
    model = Movie if media_type == "movie" else Series
    target = model.objects.filter(
        Q(tmdb_id=tmdb_id) | Q(tmdb_match_id=tmdb_id)
    ).order_by("id").first()
    if target is not None and target.tmdb_status == "matched":
        return target

    token = CoreSettings.get_tmdb_api_token()
    if not token:
        raise DRFValidationError(
            {"tmdb_id": "Configure a TMDB API token before assigning a new title."}
        )
    from .tmdb import Client as TMDBClient, TMDBError

    try:
        metadata = TMDBClient(token).details(
            tmdb_id,
            "movie" if media_type == "movie" else "tv",
            CoreSettings.get_tmdb_languages(),
            match_method="source_override",
        )
    except TMDBError as exc:
        raise DRFValidationError({"tmdb_id": str(exc)}) from exc

    defaults = _tmdb_target_defaults(metadata, media_type)
    if target is None:
        target = model.objects.create(tmdb_id=tmdb_id, **defaults)
    else:
        model.objects.filter(pk=target.pk).update(**defaults)
        target.refresh_from_db()
    from .tasks import TMDB_ENRICHMENT_LOCK_VALUE

    model.objects.filter(pk=target.pk).update(
        tmdb_enrichment_signature=TMDB_ENRICHMENT_LOCK_VALUE
    )
    target.tmdb_enrichment_signature = TMDB_ENRICHMENT_LOCK_VALUE
    return target


def _move_series_relation(relation, target):
    """Re-home one provider series and its episode sources atomically."""
    if relation.series_id == target.id:
        M3USeriesRelation.objects.filter(pk=relation.pk).update(
            tmdb_override_id=str(target.tmdb_match_id or target.tmdb_id or "")
        )
        return
    episode_relations = list(
        relation.episode_relations.select_related("episode").order_by("id")
    )
    for episode_relation in episode_relations:
        source = episode_relation.episode
        episode, _ = Episode.objects.get_or_create(
            series=target,
            season_number=source.season_number,
            episode_number=source.episode_number,
            defaults={
                "name": source.name,
                "description": source.description,
                "air_date": source.air_date,
                "rating": source.rating,
                "duration_secs": source.duration_secs,
                "tmdb_id": source.tmdb_id,
                "imdb_id": source.imdb_id,
                "custom_properties": source.custom_properties,
                "library_added_at": source.library_added_at,
            },
        )
        M3UEpisodeRelation.objects.filter(pk=episode_relation.pk).update(
            episode=episode
        )
    M3USeriesRelation.objects.filter(pk=relation.pk).update(
        series=target,
        tmdb_override_id=str(target.tmdb_match_id or target.tmdb_id or ""),
    )


def _vod_metadata_state_payload():
    state, _ = VODMetadataState.objects.get_or_create(pk=1)
    return {
        "status": state.status,
        "task_id": state.task_id,
        "progress": state.progress or {},
        "started_at": state.started_at,
        "completed_at": state.completed_at,
        "error": state.error,
        "updated_at": state.updated_at,
    }


def _source_relation_model(content_type):
    return {
        "movie": M3UMovieRelation,
        "series": M3USeriesRelation,
        "episode": M3UEpisodeRelation,
    }.get(str(content_type or "").lower())


def _playback_source_relation(playback):
    model = _source_relation_model(playback.content_type)
    if model is None or not playback.relation_id:
        return None
    return model.objects.filter(pk=playback.relation_id).first()


def _effective_json_array_match(field, value, relation_alias="relation"):
    """PostgreSQL SQL for one effective-metadata array membership check."""
    # Keep the key/membership operators directly on the indexed JSONB columns.
    # COALESCE around the column would prevent PostgreSQL from using their GIN
    # indexes. Only the boolean existence result needs a NULL fallback.
    manual = f"{relation_alias}.manual_metadata"
    observed = f"{relation_alias}.observed_metadata"
    declared = f"{relation_alias}.declared_metadata"
    category = "category_relation.metadata_defaults"
    sql = f"""(
        ({manual} ? %s AND ({manual} -> %s) ? %s)
        OR (
            NOT COALESCE({manual} ? %s, false)
            AND {observed} ? %s
            AND ({observed} -> %s) ? %s
        )
        OR (
            NOT COALESCE({manual} ? %s, false)
            AND NOT COALESCE({observed} ? %s, false)
            AND {declared} ? %s
            AND ({declared} -> %s) ? %s
        )
        OR (
            NOT COALESCE({manual} ? %s, false)
            AND NOT COALESCE({observed} ? %s, false)
            AND NOT COALESCE({declared} ? %s, false)
            AND ({category} -> %s) ? %s
        )
    )"""
    params = [
        field, field, value,
        field, field, field, value,
        field, field, field, field, value,
        field, field, field, field, value,
    ]
    return sql, params


def _effective_json_scalar_match(
    field, value, relation_fallback="NULL", relation_alias="relation"
):
    """PostgreSQL SQL for a case-insensitive effective scalar match."""
    manual = f"{relation_alias}.manual_metadata"
    observed = f"{relation_alias}.observed_metadata"
    declared = f"{relation_alias}.declared_metadata"
    category = "category_relation.metadata_defaults"
    expression = f"""CASE
        WHEN COALESCE({manual} ? %s, false) THEN {manual} ->> %s
        WHEN COALESCE({observed} ? %s, false) THEN {observed} ->> %s
        WHEN COALESCE({declared} ? %s, false) THEN {declared} ->> %s
        WHEN COALESCE({category} ? %s, false) THEN {category} ->> %s
        ELSE {relation_fallback}
    END"""
    return f"LOWER(COALESCE(({expression}), '')) = LOWER(%s)", [
        field, field,
        field, field,
        field, field,
        field, field,
        value,
    ]


def _effective_json_value_expression(
    field, *, relation_alias="relation", category_alias="category_relation"
):
    """Return the effective JSON value for a trusted metadata field name."""
    manual = f"{relation_alias}.manual_metadata"
    observed = f"{relation_alias}.observed_metadata"
    declared = f"{relation_alias}.declared_metadata"
    category = f"{category_alias}.metadata_defaults"
    return f"""CASE
        WHEN COALESCE({manual} ? '{field}', false) THEN {manual} -> '{field}'
        WHEN COALESCE({observed} ? '{field}', false) THEN {observed} -> '{field}'
        WHEN COALESCE({declared} ? '{field}', false) THEN {declared} -> '{field}'
        WHEN COALESCE({category} ? '{field}', false) THEN {category} -> '{field}'
        ELSE '[]'::jsonb
    END"""


def _effective_json_scalar_expression(
    field,
    *,
    relation_alias="relation",
    category_alias="category_relation",
    relation_fallback="NULL",
):
    """Return the effective text value for a trusted metadata field name."""
    manual = f"{relation_alias}.manual_metadata"
    observed = f"{relation_alias}.observed_metadata"
    declared = f"{relation_alias}.declared_metadata"
    category = f"{category_alias}.metadata_defaults"
    return f"""CASE
        WHEN COALESCE({manual} ? '{field}', false) THEN {manual} ->> '{field}'
        WHEN COALESCE({observed} ? '{field}', false) THEN {observed} ->> '{field}'
        WHEN COALESCE({declared} ? '{field}', false) THEN {declared} ->> '{field}'
        WHEN COALESCE({category} ? '{field}', false) THEN {category} ->> '{field}'
        ELSE {relation_fallback}
    END"""


def _vod_relation_sql(filters, relation_type):
    """Build one relation-exact SQL source predicate for VOD list/bulk use."""
    filters = filters if isinstance(filters, dict) else {}
    if relation_type == "movie":
        table = "vod_m3umovierelation"
        canonical_column = "movie_id"
        container_fallback = "relation.container_extension"
    else:
        table = "vod_m3useriesrelation"
        canonical_column = "series_id"
        container_fallback = "NULL"
    joins = f"""
        {table} relation
        JOIN m3u_m3uaccount account
          ON relation.m3u_account_id = account.id
        LEFT JOIN vod_vodcategory category
          ON relation.category_id = category.id
        LEFT JOIN vod_m3uvodcategoryrelation category_relation
          ON category_relation.m3u_account_id = relation.m3u_account_id
         AND category_relation.category_id = relation.category_id
    """
    conditions = ["account.is_active = true"]
    params = []
    technical_conditions = []
    technical_params = []
    episode_conditions = []
    episode_params = []

    m3u_account = str(filters.get("m3u_account") or "").strip()
    if m3u_account.isdigit():
        conditions.append("relation.m3u_account_id = %s")
        params.append(int(m3u_account))

    category_value = str(filters.get("category") or "").strip()
    if category_value:
        category_name = category_value
        category_type = None
        if "|" in category_value:
            category_name, category_type = category_value.rsplit("|", 1)
        if category_type and category_type != relation_type:
            conditions.append("1 = 0")
        else:
            conditions.append("category.name = %s")
            params.append(category_name)

    for parameter, field in (
        ("audio_language", "audio_languages"),
        ("subtitle_language", "subtitle_languages"),
    ):
        value = normalize_language_code(filters.get(parameter))
        if value:
            sql, sql_params = _effective_json_array_match(field, value)
            technical_conditions.append(sql)
            technical_params.extend(sql_params)
            if relation_type == "series":
                sql, sql_params = _effective_json_array_match(
                    field, value, relation_alias="episode_relation"
                )
                episode_conditions.append(sql)
                episode_params.extend(sql_params)

    feature_values = normalize_video_features([filters.get("video_feature")])
    if feature_values:
        compatible_features = compatible_video_features(feature_values[0])
        feature_clauses = []
        feature_params = []
        for feature in compatible_features:
            sql, sql_params = _effective_json_array_match("video_features", feature)
            feature_clauses.append(sql)
            feature_params.extend(sql_params)
        technical_conditions.append(f"({' OR '.join(feature_clauses)})")
        technical_params.extend(feature_params)
        if relation_type == "series":
            feature_clauses = []
            feature_params = []
            for feature in compatible_features:
                sql, sql_params = _effective_json_array_match(
                    "video_features", feature, relation_alias="episode_relation"
                )
                feature_clauses.append(sql)
                feature_params.extend(sql_params)
            episode_conditions.append(f"({' OR '.join(feature_clauses)})")
            episode_params.extend(feature_params)

    resolution = str(filters.get("resolution") or "").strip().lower()
    if resolution:
        sql, sql_params = _effective_json_scalar_match("resolution", resolution)
        technical_conditions.append(sql)
        technical_params.extend(sql_params)
        if relation_type == "series":
            sql, sql_params = _effective_json_scalar_match(
                "resolution", resolution, relation_alias="episode_relation"
            )
            episode_conditions.append(sql)
            episode_params.extend(sql_params)

    container = str(filters.get("container_extension") or "").strip().lower()
    if container:
        sql, sql_params = _effective_json_scalar_match(
            "container_extension", container, container_fallback
        )
        technical_conditions.append(sql)
        technical_params.extend(sql_params)
        if relation_type == "series":
            sql, sql_params = _effective_json_scalar_match(
                "container_extension",
                container,
                "episode_relation.container_extension",
                relation_alias="episode_relation",
            )
            episode_conditions.append(sql)
            episode_params.extend(sql_params)

    if relation_type == "series" and technical_conditions:
        # Series-level defaults/relations are cheap to test. Technical data
        # learned from actual episode playback lives on episode relations, so
        # use one correlated EXISTS for the complete filter set. This ensures
        # DUB/SUB/resolution/format all describe the same source edition.
        episode_sql = f"""EXISTS (
            SELECT 1
            FROM vod_m3uepisoderelation episode_relation
            WHERE episode_relation.series_relation_id = relation.id
              AND {' AND '.join(episode_conditions)}
        )"""
        conditions.append(
            f"(({' AND '.join(technical_conditions)}) OR {episode_sql})"
        )
        params.extend(technical_params)
        params.extend(episode_params)
    else:
        conditions.extend(technical_conditions)
        params.extend(technical_params)

    return joins, conditions, params, canonical_column


def _vod_source_relation_prefetch(model):
    return Prefetch(
        "m3u_relations",
        queryset=model.objects.filter(
            m3u_account__is_active=True,
        ).select_related("m3u_account", "category"),
    )


def _validated_source_metadata(value):
    from .metadata import validate_configurable_source_metadata

    try:
        return validate_configurable_source_metadata(value)
    except ValueError as exc:
        raise DRFValidationError({"metadata": str(exc)})


def _validated_manual_source_metadata(value, locked_fields=None):
    """Validate metadata administrators may override on a concrete source.

    Container format and provider identifiers describe the physical source and
    are intentionally immutable. They continue to come from the provider,
    detailed source response, or playback inspection.
    """
    from .metadata import MANUALLY_EDITABLE_SOURCE_METADATA_FIELDS

    unsupported = sorted(
        set(value or {}) - MANUALLY_EDITABLE_SOURCE_METADATA_FIELDS
    )
    normalized_locked_fields = {
        str(field)
        for field in (locked_fields if locked_fields is not None else value)
    }
    unsupported_locked = sorted(
        normalized_locked_fields - MANUALLY_EDITABLE_SOURCE_METADATA_FIELDS
    )
    if unsupported or unsupported_locked:
        fields = sorted(set(unsupported) | set(unsupported_locked))
        raise DRFValidationError(
            {
                "metadata": (
                    "Provider source fields cannot be changed manually: "
                    + ", ".join(fields)
                )
            }
        )
    return _validated_source_metadata(value), sorted(normalized_locked_fields)


def _is_admin(user):
    return bool(user and getattr(user, "user_level", 0) >= 10)


def _filtered_vod_content(filters):
    """Return Movie/Series querysets matching the VOD list controls."""
    filters = filters if isinstance(filters, dict) else {}
    content_type = filters.get("type") or "all"
    search = str(filters.get("search") or "").strip()

    movie_joins, movie_conditions, movie_params, movie_column = (
        _vod_relation_sql(filters, "movie")
    )
    series_joins, series_conditions, series_params, series_column = (
        _vod_relation_sql(filters, "series")
    )
    movies = Movie.objects.filter(
        id__in=RawSQL(
            f"SELECT relation.{movie_column} FROM {movie_joins} "
            f"WHERE {' AND '.join(movie_conditions)}",
            movie_params,
        )
    )
    series = Series.objects.filter(
        id__in=RawSQL(
            f"SELECT relation.{series_column} FROM {series_joins} "
            f"WHERE {' AND '.join(series_conditions)}",
            series_params,
        )
    )
    if content_type == "movies":
        series = series.none()
    elif content_type == "series":
        movies = movies.none()

    if search:
        # The unified "All" endpoint currently searches names only, while
        # the dedicated movie and series endpoints also search description
        # and genre. Mirror those list endpoints exactly so a bulk operation
        # never reaches rows that were not included in the visible result set.
        if content_type == "all":
            movies = movies.filter(name__icontains=search)
            series = series.filter(name__icontains=search)
        else:
            movies = movies.filter(
                Q(name__icontains=search)
                | Q(description__icontains=search)
                | Q(genre__icontains=search)
            )
            series = series.filter(
                Q(name__icontains=search)
                | Q(description__icontains=search)
                | Q(genre__icontains=search)
            )

    metadata_status = str(filters.get("metadata_status") or "").strip()
    if metadata_status:
        movies = movies.filter(_vod_metadata_filter_q(metadata_status))
        series = series.filter(_vod_metadata_filter_q(metadata_status))

    movies = _apply_vod_canonical_filters(movies, filters, "movie")
    series = _apply_vod_canonical_filters(series, filters, "series")

    return movies.distinct(), series.distinct()


def _vod_metadata_filter_q(value, prefix=""):
    field = lambda name: f"{prefix}{name}"
    missing_tmdb = (
        Q(**{field("tmdb_match_id"): ""})
        & (Q(**{f'{field("tmdb_id")}__isnull': True}) | Q(**{field("tmdb_id"): ""}))
    )
    if value == "missing_tmdb":
        return missing_tmdb
    if value == "missing_external_ids":
        return (
            missing_tmdb
            & Q(**{field("tmdb_imdb_id"): ""})
            & (
                Q(**{f'{field("imdb_id")}__isnull': True})
                | Q(**{field("imdb_id"): ""})
            )
            & (
                Q(
                    **{
                        f'{field("tmdb_metadata")}__external_ids__tvdb_id__isnull': True
                    }
                )
                | Q(
                    **{
                        f'{field("tmdb_metadata")}__external_ids__tvdb_id': ""
                    }
                )
            )
            & (
                Q(
                    **{
                        f'{field("tmdb_metadata")}__external_ids__wikidata_id__isnull': True
                    }
                )
                | Q(
                    **{
                        f'{field("tmdb_metadata")}__external_ids__wikidata_id': ""
                    }
                )
            )
        )
    if value == "missing_metadata":
        return ~Q(**{field("tmdb_status"): "matched"})
    return Q()


def _vod_metadata_sql_condition(value, alias):
    effective_tmdb = (
        f"COALESCE(NULLIF({alias}.tmdb_match_id, ''), "
        f"NULLIF({alias}.tmdb_id, ''))"
    )
    effective_imdb = (
        f"COALESCE(NULLIF({alias}.tmdb_imdb_id, ''), "
        f"NULLIF({alias}.imdb_id, ''))"
    )
    effective_tvdb = (
        f"NULLIF({alias}.tmdb_metadata -> 'external_ids' ->> 'tvdb_id', '')"
    )
    effective_wikidata = (
        f"NULLIF({alias}.tmdb_metadata -> 'external_ids' ->> 'wikidata_id', '')"
    )
    if value == "missing_tmdb":
        return f"{effective_tmdb} IS NULL"
    if value == "missing_external_ids":
        return (
            f"{effective_tmdb} IS NULL AND {effective_imdb} IS NULL "
            f"AND {effective_tvdb} IS NULL AND {effective_wikidata} IS NULL"
        )
    if value == "missing_metadata":
        return f"COALESCE({alias}.tmdb_status, '') <> 'matched'"
    return ""


def _parse_vod_filter_datetime(value):
    raw_value = str(value or "").strip()
    if not raw_value:
        return None
    parsed_value = parse_datetime(raw_value)
    if parsed_value is None:
        parsed_date = parse_date(raw_value)
        if parsed_date is not None:
            parsed_value = datetime.combine(parsed_date, time.min)
    if parsed_value is None:
        raise DRFValidationError("Enter a valid ISO 8601 date or date and time.")
    if timezone.is_naive(parsed_value):
        parsed_value = timezone.make_aware(parsed_value)
    return parsed_value


def _apply_vod_canonical_filters(queryset, filters, content_type, prefix=""):
    """Apply title-level list filters to a Movie/Series queryset."""
    filters = filters if isinstance(filters, dict) else {}
    field = lambda name: f"{prefix}{name}"
    genre = str(filters.get("genre") or "").strip()
    if genre:
        queryset = queryset.filter(
            Q(**{f'{field("genre")}__icontains': genre})
            | Q(**{f'{field("tmdb_metadata")}__genres__icontains': genre})
        )

    anime_mode = str(filters.get("anime_mode") or "").strip()
    if anime_mode == "yes":
        queryset = queryset.filter(
            **{f'{field("tmdb_metadata")}__is_anime': True}
        )
    elif anime_mode == "no":
        queryset = queryset.exclude(
            **{f'{field("tmdb_metadata")}__is_anime': True}
        )

    adult_query = Q(**{f'{field("tmdb_metadata")}__adult': True})
    if content_type == "movie":
        adult_query |= Q(**{field("is_adult"): True})
    adult_mode = str(filters.get("adult_mode") or "").strip()
    if adult_mode == "yes":
        queryset = queryset.filter(adult_query)
    elif adult_mode == "no":
        queryset = queryset.exclude(adult_query)

    added_after = _parse_vod_filter_datetime(filters.get("library_added_after"))
    if added_after is not None:
        queryset = queryset.filter(
            **{f'{field("library_added_at")}__gte': added_after}
        )
    added_before = _parse_vod_filter_datetime(filters.get("library_added_before"))
    if added_before is not None:
        queryset = queryset.filter(
            **{f'{field("library_added_at")}__lte': added_before}
        )
    return queryset


def _vod_canonical_sql_filters(filters, alias, content_type):
    """Return SQL predicates and parameters matching the ORM helper above."""
    filters = filters if isinstance(filters, dict) else {}
    conditions = []
    params = []
    genre = str(filters.get("genre") or "").strip()
    if genre:
        value = f"%{genre.lower()}%"
        conditions.append(
            "(LOWER(COALESCE({alias}.genre, '')) LIKE %s OR "
            "LOWER(COALESCE(({alias}.tmdb_metadata -> 'genres')::text, '')) "
            "LIKE %s)".format(alias=alias)
        )
        params.extend([value, value])

    anime_mode = str(filters.get("anime_mode") or "").strip()
    if anime_mode in {"yes", "no"}:
        operator = "=" if anime_mode == "yes" else "<>"
        conditions.append(
            f"LOWER(COALESCE({alias}.tmdb_metadata ->> 'is_anime', 'false')) "
            f"{operator} 'true'"
        )

    adult_mode = str(filters.get("adult_mode") or "").strip()
    if adult_mode in {"yes", "no"}:
        adult_expression = (
            f"({alias}.is_adult = TRUE OR "
            f"LOWER(COALESCE({alias}.tmdb_metadata ->> 'adult', 'false')) = 'true')"
            if content_type == "movie"
            else f"LOWER(COALESCE({alias}.tmdb_metadata ->> 'adult', 'false')) = 'true'"
        )
        conditions.append(
            adult_expression if adult_mode == "yes" else f"NOT ({adult_expression})"
        )

    added_after = _parse_vod_filter_datetime(filters.get("library_added_after"))
    if added_after is not None:
        conditions.append(f"{alias}.library_added_at >= %s")
        params.append(added_after)
    added_before = _parse_vod_filter_datetime(filters.get("library_added_before"))
    if added_before is not None:
        conditions.append(f"{alias}.library_added_at <= %s")
        params.append(added_before)
    return conditions, params


def _selected_relation_queryset(request, relation_type):
    relation_model, canonical_field = (
        (M3UMovieRelation, "movie")
        if relation_type == "movie"
        else (M3USeriesRelation, "series")
    )
    selections = request.data.get("selections", [])
    exclusions = request.data.get("exclude_selections", [])
    select_all = request.data.get("select_all") is True
    filters = request.data.get("filters")
    filters = filters if isinstance(filters, dict) else {}
    ids = {
        int(item["relation_id"])
        for item in selections
        if isinstance(item, dict)
        and item.get("content_type") == relation_type
        and str(item.get("relation_id", "")).isdigit()
    }
    excluded_ids = {
        int(item["relation_id"])
        for item in exclusions
        if isinstance(item, dict)
        and item.get("content_type") == relation_type
        and str(item.get("relation_id", "")).isdigit()
    }
    queryset = relation_model.objects.filter(
        _filtered_vod_relation_query(filters, relation_type)
    ).select_related(canonical_field, "m3u_account", "category")
    if not select_all:
        queryset = queryset.filter(pk__in=ids)
    elif excluded_ids:
        queryset = queryset.exclude(pk__in=excluded_ids)

    requested_type = str(filters.get("type") or "all")
    expected_filter_type = "movies" if relation_type == "movie" else "series"
    if requested_type not in {"all", expected_filter_type}:
        return queryset.none()
    search = str(filters.get("search") or "").strip()
    if search:
        canonical_lookup = f"{canonical_field}__name__icontains"
        queryset = queryset.filter(
            Q(**{canonical_lookup: search})
            | Q(custom_properties__detailed_info__name__icontains=search)
            | Q(custom_properties__basic_data__name__icontains=search)
            | Q(custom_properties__movie_data__name__icontains=search)
            | Q(custom_properties__series_data__name__icontains=search)
        )
    metadata_status = str(filters.get("metadata_status") or "").strip()
    if metadata_status:
        queryset = queryset.filter(
            _vod_metadata_filter_q(metadata_status, f"{canonical_field}__")
        )
    queryset = _apply_vod_canonical_filters(
        queryset,
        filters,
        relation_type,
        prefix=f"{canonical_field}__",
    )
    return queryset


def _filtered_vod_relation_query(filters, relation_type):
    """Limit bulk edits to the source relations represented by list filters.

    Search and content-type filters select canonical Movie/Series rows. Account
    and category filters additionally describe which concrete source relations
    made those rows visible, so they must remain in force during mass editing.
    """
    filters = filters if isinstance(filters, dict) else {}
    query = Q(m3u_account__is_active=True)

    m3u_account = str(filters.get("m3u_account") or "").strip()
    if m3u_account.isdigit():
        query &= Q(m3u_account_id=int(m3u_account))

    category = str(filters.get("category") or "").strip()
    technical_filters = any(
        filters.get(key)
        for key in (
            "audio_language",
            "subtitle_language",
            "resolution",
            "container_extension",
            "video_feature",
        )
    )
    if not category and not technical_filters:
        return query

    category_name = category
    category_type = None
    if "|" in category:
        category_name, category_type = category.rsplit("|", 1)

    expected_type = "movie" if relation_type == "movie" else "series"
    if category_type and category_type != expected_type:
        return Q(pk__in=[])

    category_field = (
        "category__name"
        if relation_type in {"movie", "series"}
        else "series_relation__category__name"
    )
    if category:
        query &= Q(**{category_field: category_name})
    if technical_filters and relation_type in {"movie", "series"}:
        joins, conditions, params, _canonical_column = _vod_relation_sql(
            filters, relation_type
        )
        query &= Q(
            pk__in=RawSQL(
                f"SELECT relation.id FROM {joins} "
                f"WHERE {' AND '.join(conditions)}",
                params,
            )
        )
    return query


class VODSourceRelationViewSet(viewsets.ViewSet):
    """Manage metadata and canonical placement for provider relations."""

    def get_permissions(self):
        return [Authenticated()]

    @action(
        detail=False,
        methods=["patch"],
        url_path="manual-metadata",
    )
    def manual_metadata(self, request):
        """Set locked metadata on exactly one provider relation."""
        if not _is_admin(request.user):
            return Response(status=status.HTTP_403_FORBIDDEN)

        relation_type = str(request.data.get("content_type") or "").lower()
        relation_model = {
            "movie": M3UMovieRelation,
            "series": M3USeriesRelation,
            "episode": M3UEpisodeRelation,
        }.get(relation_type)
        try:
            relation_id = int(request.data.get("relation_id"))
        except (TypeError, ValueError):
            relation_id = None
        if relation_model is None or relation_id is None:
            return Response(
                {"detail": "content_type and a numeric relation_id are required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        relation = relation_model.objects.select_related(
            "m3u_account",
            "category" if relation_type != "episode" else "series_relation__category",
        ).filter(pk=relation_id).first()
        if relation is None:
            return Response(status=status.HTTP_404_NOT_FOUND)

        metadata = request.data.get("metadata", {})
        locked_fields = request.data.get("locked_fields", list(metadata))
        if not isinstance(metadata, dict) or not isinstance(locked_fields, list):
            return Response(
                {"detail": "metadata must be an object and locked_fields a list"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        from .metadata import effective_relation_metadata

        metadata, locked_fields = _validated_manual_source_metadata(
            metadata, locked_fields
        )
        with transaction.atomic():
            relation_model.objects.filter(pk=relation.pk).update(
                manual_metadata=metadata,
                locked_fields=locked_fields,
                updated_at=timezone.now(),
            )
            relation.manual_metadata = metadata
            relation.locked_fields = locked_fields

        from .catalog_cache import bump_catalog_generation
        from .profile_selection import (
            mark_profile_selections_outdated,
            profile_ids_using_source_categories,
        )

        bump_catalog_generation(invalidate_selections=False)
        affected_profiles = mark_profile_selections_outdated(
            trigger_reason="VOD source metadata was edited manually",
            policy_ids=profile_ids_using_source_categories(
                [(
                    relation.m3u_account_id,
                    relation.category_id
                    if relation_type != "episode"
                    else relation.series_relation.category_id,
                )]
            ),
        )
        return Response(
            {
                "source_relation": {
                    "content_type": relation_type,
                    "relation_id": relation.pk,
                },
                "source_metadata": effective_relation_metadata(relation),
                "profile_update": (
                    "outdated" if affected_profiles else "not_required"
                ),
                "profiles_affected": affected_profiles,
            }
        )

    @action(detail=False, methods=["get"], url_path="canonical-targets")
    def canonical_targets(self, request):
        """Search the existing canonical library before moving a source."""
        if not _is_admin(request.user):
            return Response(status=status.HTTP_403_FORBIDDEN)
        content_type = str(request.query_params.get("content_type") or "").lower()
        model = {"movie": Movie, "series": Series}.get(content_type)
        if model is None:
            raise DRFValidationError(
                {"content_type": "Choose movie or series."}
            )
        search = str(request.query_params.get("search") or "").strip()
        if not search:
            raise DRFValidationError({"search": "Enter a title."})
        raw_year = str(request.query_params.get("year") or "").strip()
        try:
            year = int(raw_year) if raw_year else None
        except ValueError as exc:
            raise DRFValidationError({"year": "Enter a valid year."}) from exc

        title_filter = (
            Q(name__icontains=search)
            | Q(display_name__icontains=search)
            | Q(clean_title__icontains=search)
        )
        if search.isdigit():
            title_filter |= Q(tmdb_match_id=search) | Q(tmdb_id=search)
        if search.lower().startswith("tt"):
            title_filter |= Q(imdb_id__iexact=search) | Q(
                tmdb_imdb_id__iexact=search
            )
        queryset = model.objects.filter(
            title_filter,
            m3u_relations__m3u_account__is_active=True,
        )
        if year is not None:
            queryset = queryset.filter(year=year)
        queryset = queryset.annotate(
            source_count=Count(
                "m3u_relations",
                filter=Q(m3u_relations__m3u_account__is_active=True),
                distinct=True,
            )
        ).order_by("display_name", "name", "id")[:20]
        return Response(
            {
                "results": [
                    {
                        "id": content.id,
                        "title": (
                            content.display_name
                            or content.clean_title
                            or content.name
                        ),
                        "year": content.year,
                        "tmdb_id": str(
                            content.tmdb_match_id or content.tmdb_id or ""
                        ),
                        "imdb_id": str(
                            content.tmdb_imdb_id or content.imdb_id or ""
                        ),
                        "source_count": int(content.source_count or 0),
                    }
                    for content in queryset
                ]
            }
        )

    @action(detail=False, methods=["patch"], url_path="relation-tmdb-match")
    def relation_tmdb_match(self, request):
        """Move selected provider sources to an existing or new canonical title."""
        if not _is_admin(request.user):
            return Response(status=status.HTTP_403_FORBIDDEN)
        tmdb_id = str(request.data.get("tmdb_id") or "").strip()
        raw_target_id = request.data.get("target_id")
        create_from_provider = request.data.get("create_from_provider") is True
        target_modes = sum(
            bool(value)
            for value in (tmdb_id, raw_target_id, create_from_provider)
        )
        if target_modes != 1:
            raise DRFValidationError(
                {
                    "target": (
                        "Choose one existing canonical title, one TMDB ID, "
                        "or create a title from provider data."
                    )
                }
            )
        if tmdb_id and (not tmdb_id.isdigit() or int(tmdb_id) < 1):
            raise DRFValidationError(
                {"tmdb_id": "Enter the positive numeric ID from the TMDB URL."}
            )
        try:
            target_id = (
                int(raw_target_id)
                if raw_target_id not in (None, "")
                else None
            )
        except (TypeError, ValueError) as exc:
            raise DRFValidationError(
                {"target_id": "Choose a valid canonical title."}
            ) from exc
        if target_id is not None and target_id < 1:
            raise DRFValidationError(
                {"target_id": "Choose a valid canonical title."}
            )

        movie_relations = list(_selected_relation_queryset(request, "movie"))
        series_relations = list(_selected_relation_queryset(request, "series"))
        relations = movie_relations + series_relations
        if not relations:
            raise DRFValidationError(
                {"selections": "Select at least one provider source."}
            )
        if movie_relations and series_relations:
            raise DRFValidationError(
                {
                    "selections": (
                        "Assign movies and series separately because TMDB uses "
                        "different catalogs for the same numeric ID."
                    )
                }
            )
        if create_from_provider and len(relations) != 1:
            raise DRFValidationError(
                {
                    "selections": (
                        "Create a canonical title from exactly one provider source."
                    )
                }
            )

        content_type = "movie" if movie_relations else "series"
        model = Movie if movie_relations else Series
        target = None
        if target_id is not None:
            target = model.objects.filter(pk=target_id).first()
            if target is None:
                raise DRFValidationError(
                    {"target_id": "The selected canonical title no longer exists."}
                )

        already_enriched = 0
        for relation in relations:
            content = (
                relation.movie
                if isinstance(relation, M3UMovieRelation)
                else relation.series
            )
            already_at_target = (
                target is not None and content.pk == target.pk
            ) or (
                bool(tmdb_id)
                and tmdb_id
                in {
                    str(content.tmdb_match_id or ""),
                    str(content.tmdb_id or ""),
                }
            )
            has_existing_metadata = bool(
                content.tmdb_enriched_at
                or content.tmdb_status == "matched"
                or content.tmdb_metadata
            )
            if has_existing_metadata and not already_at_target:
                already_enriched += 1
        if already_enriched and request.data.get("confirmed") is not True:
            return Response(
                {
                    "requires_confirmation": True,
                    "affected_sources": len(relations),
                    "previously_enriched_sources": already_enriched,
                    "detail": (
                        "Metadata was already stored for one or more selected "
                        "sources. Confirm to move all selected sources."
                    ),
                },
                status=status.HTTP_409_CONFLICT,
            )

        if target is None and tmdb_id:
            target = _materialize_tmdb_target(content_type, tmdb_id)
        if target is None and create_from_provider:
            provider_relation = relations[0]
            provider_title = _relation_provider_title(provider_relation)
            provider_year = _relation_provider_year(provider_relation)
            if not provider_title:
                raise DRFValidationError(
                    {"target": "The provider source has no usable title."}
                )
            target = model.objects.filter(
                name=provider_title,
                year=provider_year,
                tmdb_id__isnull=True,
                imdb_id__isnull=True,
            ).order_by("id").first()
        if target is None and create_from_provider:
            target = model.objects.create(
                name=provider_title,
                year=provider_year,
            )

        old_movie_ids = {relation.movie_id for relation in movie_relations}
        old_series_ids = {relation.series_id for relation in series_relations}
        target_tmdb_id = str(target.tmdb_match_id or target.tmdb_id or "")
        with transaction.atomic():
            if movie_relations:
                M3UMovieRelation.objects.filter(
                    pk__in=[relation.pk for relation in movie_relations]
                ).update(movie=target, tmdb_override_id=target_tmdb_id)
            for relation in series_relations:
                _move_series_relation(relation, target)

        from .provider_metadata import (
            reconcile_movie_provider_metadata,
            reconcile_series_provider_metadata,
        )

        if movie_relations:
            reconcile_movie_provider_metadata(old_movie_ids | {target.id})
        else:
            reconcile_series_provider_metadata(old_series_ids | {target.id})
        from .tasks import refresh_canonical_clean_titles

        refresh_canonical_clean_titles(
            [target.id] if movie_relations else [],
            [target.id] if series_relations else [],
        )
        target.refresh_from_db()

        from .catalog_cache import bump_catalog_generation
        from .profile_selection import (
            mark_profile_selections_outdated,
            profile_ids_using_source_categories,
        )

        bump_catalog_generation(invalidate_selections=False)
        affected_profiles = mark_profile_selections_outdated(
            trigger_reason="A provider source was assigned to different metadata",
            policy_ids=profile_ids_using_source_categories(
                [
                    (relation.m3u_account_id, relation.category_id)
                    for relation in relations
                ]
            ),
        )
        return Response(
            {
                "moved_sources": len(relations),
                "profile_update": (
                    "outdated" if affected_profiles else "not_required"
                ),
                "profiles_affected": affected_profiles,
                "target": {
                    "id": target.id,
                    "title": (
                        target.display_name
                        or target.clean_title
                        or target.name
                    ),
                    "year": target.year,
                    "tmdb_id": target_tmdb_id,
                    "content_type": content_type,
                    "relation_id": (
                        relations[0].id if len(relations) == 1 else None
                    ),
                },
                "targets": {
                    "movie": _tmdb_content_payload(target)
                    if movie_relations else None,
                    "series": _tmdb_content_payload(target)
                    if series_relations else None,
                },
            }
        )

    @action(detail=False, methods=["patch"], url_path="bulk-manual-metadata")
    def bulk_manual_metadata(self, request):
        """Set locked metadata on the selected concrete provider sources."""
        if not _is_admin(request.user):
            return Response(status=status.HTTP_403_FORBIDDEN)
        selections = request.data.get("selections", [])
        exclude_selections = request.data.get("exclude_selections", [])
        select_all = request.data.get("select_all") is True
        filters = request.data.get("filters")
        filters = filters if isinstance(filters, dict) else {}
        metadata = request.data.get("metadata", {})
        if (
            not isinstance(selections, list)
            or not isinstance(exclude_selections, list)
            or not isinstance(metadata, dict)
        ):
            return Response(
                {
                    "detail": (
                        "selections and exclude_selections must be lists and "
                        "metadata must be an object"
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        if any(
            not isinstance(item, dict)
            for item in selections + exclude_selections
        ):
            return Response(
                {"detail": "Every selection must be an object"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        metadata, _locked_fields = _validated_manual_source_metadata(metadata)
        if not metadata:
            raise DRFValidationError(
                {"detail": "Choose at least one provider-source metadata value."}
            )
        movie_relations = _selected_relation_queryset(request, "movie")
        series_relations = _selected_relation_queryset(request, "series")
        source_category_keys = set(
            movie_relations.values_list("m3u_account_id", "category_id")
        ) | set(
            series_relations.values_list("m3u_account_id", "category_id")
        )
        relation_querysets = [movie_relations, series_relations]
        updated_source_keys = set()
        updated_at = timezone.now()

        def update_relations(relations):
            relations = list(relations)
            if not relations:
                return
            model = relations[0].__class__
            relation_type = (
                "movie" if model is M3UMovieRelation
                else "series" if model is M3USeriesRelation
                else "episode"
            )
            changed = []
            for relation in relations:
                source_key = (relation_type, relation.pk)
                if source_key in updated_source_keys:
                    continue
                relation.manual_metadata = {
                    **(relation.manual_metadata or {}),
                    **metadata,
                }
                relation.locked_fields = sorted(
                    set(relation.locked_fields or []) | set(metadata)
                )
                relation.updated_at = updated_at
                changed.append(relation)
                updated_source_keys.add(source_key)
            if changed:
                model.objects.bulk_update(
                    changed,
                    ["manual_metadata", "locked_fields", "updated_at"],
                    batch_size=1000,
                )

        for queryset in relation_querysets:
            batch = []
            for relation in queryset.iterator(chunk_size=1000):
                batch.append(relation)
                if len(batch) == 1000:
                    update_relations(batch)
                    batch = []
            if batch:
                update_relations(batch)

        from .catalog_cache import bump_catalog_generation
        from .profile_selection import (
            mark_profile_selections_outdated,
            profile_ids_using_source_categories,
        )

        bump_catalog_generation(invalidate_selections=False)
        affected_profiles = mark_profile_selections_outdated(
            trigger_reason="VOD source metadata was edited manually",
            policy_ids=profile_ids_using_source_categories(source_category_keys),
        )
        return Response(
            {
                "updated_sources": len(updated_source_keys),
                "updated_titles": 0,
                "profile_update": (
                    "outdated" if affected_profiles else "not_required"
                ),
                "profiles_affected": affected_profiles,
            }
        )

class M3UVODCategoryRelationViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = M3UVODCategoryRelation.objects.select_related(
        "m3u_account", "category"
    )
    serializer_class = M3UVODCategoryRelationSerializer
    pagination_class = None

    def get_permissions(self):
        return [Authenticated()]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return self.queryset.none()
        return self.queryset if _is_admin(self.request.user) else self.queryset.none()

    @action(detail=True, methods=["patch"], url_path="title-cleanup")
    def title_cleanup(self, request, pk=None):
        if not _is_admin(request.user):
            return Response(status=status.HTTP_403_FORBIDDEN)
        from .tmdb import normalize_group_title_cleanup

        relation = self.get_object()
        try:
            cleanup = normalize_group_title_cleanup(
                request.data.get("title_cleanup")
            )
        except ValueError as exc:
            raise DRFValidationError({"title_cleanup": str(exc)}) from exc
        properties = dict(relation.custom_properties or {})
        if cleanup:
            properties["title_cleanup"] = cleanup
        else:
            properties.pop("title_cleanup", None)
        relation.custom_properties = properties
        relation.save(update_fields=["custom_properties", "updated_at"])
        return Response(self.get_serializer(relation).data)

    @action(detail=True, methods=["post"], url_path="title-cleanup-preview")
    def title_cleanup_preview(self, request, pk=None):
        """Preview a category removal rule against stored provider titles."""
        if not _is_admin(request.user):
            return Response(status=status.HTTP_403_FORBIDDEN)
        from .tmdb import clean_lookup_title, normalize_group_title_cleanup

        category_relation = self.get_object()
        try:
            page = max(1, int(request.data.get("page") or 1))
        except (TypeError, ValueError) as exc:
            raise DRFValidationError(
                {"page": "Enter a valid preview page."}
            ) from exc
        try:
            page_size = min(
                250, max(1, int(request.data.get("page_size") or 25))
            )
        except (TypeError, ValueError) as exc:
            raise DRFValidationError(
                {"page_size": "Enter a valid preview page size."}
            ) from exc

        if category_relation.category.category_type == "movie":
            relations = M3UMovieRelation.objects.filter(
                m3u_account_id=category_relation.m3u_account_id,
                category_id=category_relation.category_id,
            ).select_related("movie")
            content_type = "movie"
        elif category_relation.category.category_type == "series":
            relations = M3USeriesRelation.objects.filter(
                m3u_account_id=category_relation.m3u_account_id,
                category_id=category_relation.category_id,
            ).select_related("series")
            content_type = "series"
        else:
            relations = M3UMovieRelation.objects.none()
            content_type = category_relation.category.category_type

        total_in_category = relations.count()
        empty_result = {
            "results": [],
            "page_match_count": 0,
            "page": page,
            "page_size": page_size,
            "total_in_category": total_in_category,
            "error": None,
        }
        try:
            cleanup = normalize_group_title_cleanup(
                request.data.get("title_cleanup")
            )
        except ValueError as exc:
            return Response({**empty_result, "error": str(exc)})

        pattern = None
        if cleanup:
            flags = 0 if cleanup["case_sensitive"] else re.IGNORECASE
            pattern = re.compile(cleanup["pattern"], flags)
        title_rules = CoreSettings.get_tmdb_title_rules()
        year_rules = CoreSettings.get_tmdb_year_rules()
        offset = (page - 1) * page_size
        results = []
        page_match_count = 0
        for relation in relations.order_by("id")[offset : offset + page_size]:
            before = _relation_provider_title(relation)
            matched = bool(before and pattern and pattern.search(before))
            if matched:
                page_match_count += 1
            year = _relation_import_year(relation, year_rules)
            after = clean_lookup_title(
                before,
                year=year,
                rules=title_rules,
                year_rules=year_rules,
                group_rule=cleanup,
            )
            results.append(
                {
                    "relation_id": relation.id,
                    "content_type": content_type,
                    "before": before,
                    "after": after,
                    "year": year,
                    "matched": matched,
                    "changed": before != after,
                }
            )
        return Response(
            {
                "results": results,
                "page_match_count": page_match_count,
                "page": page,
                "page_size": page_size,
                "total_in_category": total_in_category,
                "error": None,
            }
        )

    @action(detail=True, methods=["patch"], url_path="metadata-defaults")
    def metadata_defaults(self, request, pk=None):
        if not _is_admin(request.user):
            return Response(status=status.HTTP_403_FORBIDDEN)
        relation = self.get_object()
        serializer = self.get_serializer(
            relation,
            data={
                "metadata_defaults": _validated_source_metadata(
                    request.data.get("metadata_defaults", {})
                )
            },
            partial=True,
        )
        serializer.is_valid(raise_exception=True)
        relation._skip_vod_profile_invalidation = True
        serializer.save()
        from .metadata import sync_category_relation_metadata

        updated_sources = sync_category_relation_metadata(relation)
        from .catalog_cache import bump_catalog_generation
        from .profile_selection import (
            mark_profile_selections_outdated,
            profile_ids_using_source_categories,
        )

        bump_catalog_generation(invalidate_selections=False)
        affected_profiles = mark_profile_selections_outdated(
            trigger_reason="VOD category metadata defaults changed",
            policy_ids=profile_ids_using_source_categories(
                [(relation.m3u_account_id, relation.category_id)]
            ),
        )
        payload = dict(serializer.data)
        payload.update(
            profile_update="outdated" if affected_profiles else "not_required",
            profiles_affected=affected_profiles,
            updated_sources=updated_sources,
        )
        return Response(payload)

    @action(detail=False, methods=["patch"], url_path="bulk-metadata-defaults")
    def bulk_metadata_defaults(self, request):
        if not _is_admin(request.user):
            return Response(status=status.HTTP_403_FORBIDDEN)
        relation_ids = request.data.get("relation_ids", [])
        metadata = request.data.get("metadata_defaults", {})
        if not isinstance(relation_ids, list) or not isinstance(metadata, dict):
            return Response(
                {"detail": "relation_ids must be a list and metadata_defaults an object"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            relation_ids = [int(relation_id) for relation_id in relation_ids]
        except (TypeError, ValueError):
            return Response(
                {"detail": "relation_ids must contain integers"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        normalized = _validated_source_metadata(metadata)
        relations = list(self.get_queryset().filter(pk__in=relation_ids))
        updated_at = timezone.now()
        for relation in relations:
            relation.metadata_defaults = {
                **(relation.metadata_defaults or {}),
                **normalized,
            }
            relation.updated_at = updated_at
        M3UVODCategoryRelation.objects.bulk_update(
            relations, ["metadata_defaults", "updated_at"], batch_size=1000
        )
        from .metadata import sync_category_relations_metadata

        updated_sources = sync_category_relations_metadata(relations)
        from .catalog_cache import bump_catalog_generation
        from .profile_selection import (
            mark_profile_selections_outdated,
            profile_ids_using_source_categories,
        )

        bump_catalog_generation(invalidate_selections=False)
        affected_profiles = mark_profile_selections_outdated(
            trigger_reason="VOD category metadata defaults changed",
            policy_ids=profile_ids_using_source_categories(
                [
                    (relation.m3u_account_id, relation.category_id)
                    for relation in relations
                ]
            ),
        )
        return Response(
            {
                "updated_categories": len(relations),
                "updated_sources": updated_sources,
                "profile_update": (
                    "outdated" if affected_profiles else "not_required"
                ),
                "profiles_affected": affected_profiles,
            }
        )


class VODMetadataViewSet(viewsets.ViewSet):
    """Configure and monitor canonical TMDB enrichment."""

    permission_classes = [Authenticated]

    def _admin_only(self, request):
        if not _is_admin(request.user):
            raise PermissionDenied(
                "Only administrators can manage VOD metadata enrichment."
            )

    @staticmethod
    def _settings_payload():
        settings = CoreSettings.get_vod_settings()
        env_configured = bool(
            os.environ.get("TMDB_API_READ_ACCESS_TOKEN")
            or os.environ.get("TMDB_API_KEY")
        )
        return {
            "token_configured": bool(CoreSettings.get_tmdb_api_token()),
            "token_source": "environment" if env_configured else (
                "stored" if settings.get("tmdb_api_token") else ""
            ),
            "languages": CoreSettings.get_tmdb_languages(),
            "auto_enrich": CoreSettings.get_tmdb_auto_enrich(),
            "match_missing": CoreSettings.get_tmdb_match_missing(),
            "prefer_artwork": CoreSettings.get_tmdb_prefer_artwork(),
            "title_rules": CoreSettings.get_tmdb_title_rules(),
            "year_rules": CoreSettings.get_tmdb_year_rules(),
        }

    def list(self, request):
        self._admin_only(request)
        settings_payload = self._settings_payload()
        if request.query_params.get("settings_only") == "1":
            return Response({"settings": settings_payload})
        movie_total = Movie.objects.filter(
            m3u_relations__m3u_account__is_active=True
        ).distinct().count()
        series_total = Series.objects.filter(
            m3u_relations__m3u_account__is_active=True
        ).distinct().count()
        return Response(
            {
                "settings": settings_payload,
                "catalog": {
                    "movies": movie_total,
                    "series": series_total,
                    "enriched_movies": Movie.objects.filter(
                        m3u_relations__m3u_account__is_active=True,
                        tmdb_status="matched",
                    ).distinct().count(),
                    "enriched_series": Series.objects.filter(
                        m3u_relations__m3u_account__is_active=True,
                        tmdb_status="matched",
                    ).distinct().count(),
                },
                "state": _vod_metadata_state_payload(),
            }
        )

    @action(detail=False, methods=["put"], url_path="settings")
    def update_settings(self, request):
        self._admin_only(request)
        current_languages = CoreSettings.get_tmdb_languages()
        raw_languages = request.data.get("languages", current_languages)
        if not isinstance(raw_languages, list) or not 1 <= len(raw_languages) <= 2:
            raise DRFValidationError(
                {"languages": "Choose one or two TMDB language-region codes."}
            )
        languages = []
        for raw in raw_languages:
            value = str(raw or "").strip()
            match = re.fullmatch(r"([A-Za-z]{2})(?:-([A-Za-z]{2}))?", value)
            if not match:
                raise DRFValidationError(
                    {"languages": f"Invalid TMDB language code: {value}"}
                )
            value = match.group(1).lower() + (
                f"-{match.group(2).upper()}" if match.group(2) else ""
            )
            if value not in languages:
                languages.append(value)
        token = None
        if request.data.get("clear_api_token") is True:
            token = ""
        elif "api_token" in request.data:
            token = str(request.data.get("api_token") or "").strip()
        previous_prefer_artwork = CoreSettings.get_tmdb_prefer_artwork()
        title_rules = CoreSettings.get_tmdb_title_rules()
        if "title_rules" in request.data:
            from .tmdb import normalize_title_rules

            try:
                title_rules = normalize_title_rules(request.data.get("title_rules"))
            except ValueError as exc:
                raise DRFValidationError({"title_rules": str(exc)}) from exc
        year_rules = CoreSettings.get_tmdb_year_rules()
        if "year_rules" in request.data:
            from .tmdb import normalize_year_rules

            try:
                year_rules = normalize_year_rules(request.data.get("year_rules"))
            except ValueError as exc:
                raise DRFValidationError({"year_rules": str(exc)}) from exc
        CoreSettings.set_vod_metadata_settings(
            api_token=token,
            languages=languages,
            auto_enrich=(
                request.data.get("auto_enrich") is True
                if "auto_enrich" in request.data
                else CoreSettings.get_tmdb_auto_enrich()
            ),
            match_missing=(
                request.data.get("match_missing") is True
                if "match_missing" in request.data
                else CoreSettings.get_tmdb_match_missing()
            ),
            prefer_artwork=request.data.get(
                "prefer_artwork", previous_prefer_artwork
            ) is not False,
            title_rules=title_rules,
            year_rules=year_rules,
        )
        if previous_prefer_artwork != CoreSettings.get_tmdb_prefer_artwork():
            from .catalog_cache import bump_catalog_generation

            bump_catalog_generation(invalidate_selections=False)
        return Response({"settings": self._settings_payload()})

    @action(detail=False, methods=["post"], url_path="tmdb-lookup")
    def tmdb_lookup(self, request):
        """Search TMDB or preview one exact result without changing the catalog."""
        self._admin_only(request)
        token = CoreSettings.get_tmdb_api_token()
        if not token:
            raise DRFValidationError(
                {"api_token": "Configure a TMDB API read access token first."}
            )
        content_type = str(request.data.get("content_type") or "")
        if content_type not in {"movie", "series"}:
            raise DRFValidationError({"content_type": "Choose movie or series."})
        media_type = "movie" if content_type == "movie" else "tv"
        from .tmdb import Client as TMDBClient, TMDBError

        client = TMDBClient(token)
        tmdb_id = str(request.data.get("tmdb_id") or "").strip()
        try:
            if tmdb_id:
                if not tmdb_id.isdigit() or int(tmdb_id) < 1:
                    raise DRFValidationError(
                        {"tmdb_id": "Enter a positive numeric TMDB ID."}
                    )
                metadata = client.details(
                    tmdb_id,
                    media_type,
                    CoreSettings.get_tmdb_languages(),
                    match_method="manual_preview",
                )
                languages = CoreSettings.get_tmdb_languages()
                return Response(
                    {
                        "metadata": {
                            **metadata,
                            "languages": languages,
                            "primary_language": languages[0],
                            "secondary_language": (
                                languages[1] if len(languages) > 1 else ""
                            ),
                        }
                    }
                )

            query = str(request.data.get("query") or "").strip()
            if not query:
                raise DRFValidationError({"query": "Enter a title to search."})
            if len(query) > 255:
                raise DRFValidationError({"query": "The title is too long."})
            raw_year = request.data.get("year")
            year = None
            if raw_year not in (None, ""):
                try:
                    year = int(raw_year)
                except (TypeError, ValueError) as exc:
                    raise DRFValidationError(
                        {"year": "Enter a valid release year."}
                    ) from exc
                if year < 1800 or year > 2200:
                    raise DRFValidationError(
                        {"year": "Enter a valid release year."}
                    )
            results = client.search_candidates(
                query,
                year,
                media_type,
                CoreSettings.get_tmdb_languages()[0],
            )
            return Response({"results": results})
        except TMDBError as exc:
            raise DRFValidationError({"detail": str(exc)}) from exc

    @action(detail=False, methods=["patch"], url_path="content")
    def update_content(self, request):
        """Persist administrator-owned canonical metadata overrides."""
        self._admin_only(request)
        content_type = str(request.data.get("content_type") or "")
        model = Movie if content_type == "movie" else (
            Series if content_type == "series" else None
        )
        if model is None:
            raise DRFValidationError({"content_type": "Choose movie or series."})
        try:
            content_id = int(request.data.get("id"))
        except (TypeError, ValueError) as exc:
            raise DRFValidationError({"id": "Invalid canonical content ID."}) from exc
        values = request.data.get("values")
        if not isinstance(values, dict):
            raise DRFValidationError({"values": "Metadata values must be an object."})
        content = model.objects.filter(pk=content_id).first()
        if content is None:
            raise DRFValidationError({"id": "Canonical content was not found."})

        def text_value(key, limit=10000):
            value = str(values.get(key) or "").strip()
            if len(value) > limit:
                raise DRFValidationError({key: f"Maximum length is {limit}."})
            return value

        title = text_value("title", 255)
        if not title:
            raise DRFValidationError({"title": "A canonical title is required."})
        description = text_value("description", 50000)
        secondary_title = text_value("secondary_title", 255)
        secondary_description = text_value("secondary_description", 50000)
        release_date = text_value("release_date", 32)
        if release_date and parse_date(release_date) is None:
            raise DRFValidationError(
                {"release_date": "Use an ISO date such as 2021-02-05."}
            )
        raw_year = values.get("year")
        year = None
        if raw_year not in (None, ""):
            try:
                year = int(raw_year)
            except (TypeError, ValueError) as exc:
                raise DRFValidationError({"year": "Enter a valid year."}) from exc
            if year < 1800 or year > 2200:
                raise DRFValidationError({"year": "Enter a valid year."})
        raw_duration = values.get("duration_minutes")
        duration_minutes = None
        if raw_duration not in (None, ""):
            try:
                duration_minutes = int(raw_duration)
            except (TypeError, ValueError) as exc:
                raise DRFValidationError(
                    {"duration_minutes": "Enter a duration in minutes."}
                ) from exc
            if duration_minutes < 0 or duration_minutes > 10000:
                raise DRFValidationError(
                    {"duration_minutes": "Enter a duration in minutes."}
                )

        external_ids = {
            "imdb_id": text_value("imdb_id", 50),
            "tvdb_id": text_value("tvdb_id", 50),
            "wikidata_id": text_value("wikidata_id", 50),
        }
        tmdb_id = text_value("tmdb_id", 50)
        clean_title = (
            title
            if tmdb_id
            else (
                text_value("clean_title", 255)
                if "clean_title" in values
                else content.clean_title
            )
        )
        if tmdb_id and (not tmdb_id.isdigit() or int(tmdb_id) < 1):
            raise DRFValidationError({"tmdb_id": "Enter a positive numeric TMDB ID."})
        raw_keywords = values.get("keywords") or []
        if isinstance(raw_keywords, str):
            raw_keywords = raw_keywords.split(",")
        if not isinstance(raw_keywords, list) or len(raw_keywords) > 100:
            raise DRFValidationError({"keywords": "Enter at most 100 keywords."})
        keyword_names = []
        for raw_keyword in raw_keywords:
            raw_value = (
                raw_keyword.get("name")
                if isinstance(raw_keyword, dict)
                else raw_keyword
            )
            keyword = str(raw_value or "").strip()
            if keyword and keyword.casefold() not in {
                value.casefold() for value in keyword_names
            }:
                keyword_names.append(keyword[:100])

        languages = CoreSettings.get_tmdb_languages()
        primary_language = languages[0]
        localized = {
            primary_language: {
                "title": title,
                "overview": description,
            }
        }
        if len(languages) > 1:
            localized[languages[1]] = {
                "title": secondary_title,
                "overview": secondary_description,
            }
        genres = [
            {"id": None, "name": name.strip()}
            for name in text_value("genre", 1000).split(",")
            if name.strip()
        ]
        manual_overrides = {
            "localized": localized,
            "overview": description,
            "release_date": release_date,
            "runtime_minutes": duration_minutes,
            "rating": text_value("rating", 20),
            "genres": genres,
            "director": text_value("director", 2000),
            "actors": text_value("actors", 10000),
            "crew": text_value("crew", 10000),
            "country": text_value("country", 1000),
            "age_rating": text_value("age_rating", 50),
            "youtube_trailer": text_value("youtube_trailer", 500),
            "poster_url": text_value("poster_url", 1000),
            "backdrop_url": text_value("backdrop_url", 1000),
            "external_ids": external_ids,
            "imdb_id": external_ids["imdb_id"],
            "tvdb_id": external_ids["tvdb_id"],
            "wikidata_id": external_ids["wikidata_id"],
            "keywords": [
                {"id": None, "name": keyword} for keyword in keyword_names
            ],
            "is_anime": values.get("is_anime") is True,
            "adult": values.get("adult") is True,
        }
        from .tmdb import apply_manual_overrides

        current_metadata = (
            content.tmdb_metadata
            if isinstance(content.tmdb_metadata, dict)
            else {}
        )
        metadata = apply_manual_overrides(current_metadata, manual_overrides)
        if tmdb_id:
            metadata["id"] = tmdb_id
        else:
            metadata.pop("id", None)
        provider_properties = dict(content.custom_properties or {})
        provider_properties["_manual_metadata"] = {
            "display_name": title,
            "description": description,
            "year": year,
            "rating": manual_overrides["rating"],
            "genre": ", ".join(row["name"] for row in genres),
            "release_date": release_date,
            "director": manual_overrides["director"],
            "actors": manual_overrides["actors"],
            "crew": manual_overrides["crew"],
            "country": manual_overrides["country"],
            "age": manual_overrides["age_rating"],
            "youtube_trailer": manual_overrides["youtube_trailer"],
            "movie_image": manual_overrides["poster_url"],
            "backdrop_path": (
                [manual_overrides["backdrop_url"]]
                if manual_overrides["backdrop_url"]
                else []
            ),
        }
        update = {
            "display_name": title,
            "clean_title": clean_title,
            "tmdb_lookup_excluded": False,
            "description": description,
            "year": year,
            "rating": manual_overrides["rating"],
            "genre": ", ".join(row["name"] for row in genres),
            "custom_properties": provider_properties,
            "tmdb_metadata": metadata,
            "tmdb_match_id": tmdb_id,
            "tmdb_imdb_id": external_ids["imdb_id"],
            "tmdb_poster_url": manual_overrides["poster_url"],
            "tmdb_backdrop_url": manual_overrides["backdrop_url"],
            "tmdb_status": "matched" if tmdb_id else "manual",
            "tmdb_enriched_at": content.tmdb_enriched_at or timezone.now(),
            "tmdb_enrichment_signature": "",
            "updated_at": timezone.now(),
        }
        if content_type == "movie":
            update["duration_secs"] = (
                duration_minutes * 60 if duration_minutes is not None else None
            )

        merge_target = None
        duplicate_ids = []
        moved_relation_id = None
        if tmdb_id:
            duplicates = list(
                model.objects.filter(
                    Q(tmdb_match_id=tmdb_id)
                    | (Q(tmdb_match_id="") & Q(tmdb_id=tmdb_id))
                )
                .exclude(pk=content_id)
                .annotate(source_count=Count("m3u_relations"))
                .order_by("-source_count", "id")
            )
            if duplicates:
                merge_target = duplicates[0]
                duplicate_ids = [row.id for row in duplicates[1:]]
                moved_relation_id = content.m3u_relations.order_by("id").values_list(
                    "id", flat=True
                ).first()

        from .profile_selection import (
            mark_profile_selections_outdated,
            profile_ids_using_canonical_content,
        )

        affected_content_ids = [content_id, *duplicate_ids]
        if merge_target is not None:
            affected_content_ids.append(merge_target.id)
        affected_policy_ids = profile_ids_using_canonical_content(
            movie_ids=affected_content_ids if content_type == "movie" else [],
            series_ids=affected_content_ids if content_type == "series" else [],
        )

        with transaction.atomic():
            if merge_target is None:
                model.objects.filter(pk=content_id).update(**update)
                content.refresh_from_db()
            else:
                target_properties = dict(merge_target.custom_properties or {})
                target_properties["_manual_metadata"] = provider_properties[
                    "_manual_metadata"
                ]
                target_update = {
                    **update,
                    "custom_properties": target_properties,
                }
                model.objects.filter(pk=merge_target.id).update(**target_update)

                from .tasks import _merge_canonical_tmdb_duplicate

                for duplicate_id in [content_id, *duplicate_ids]:
                    _merge_canonical_tmdb_duplicate(
                        model,
                        duplicate_id,
                        merge_target.id,
                        set_override=True,
                    )
                content = model.objects.get(pk=merge_target.id)

        from .tasks import TMDB_ENRICHMENT_LOCK_VALUE

        model.objects.filter(pk=content.id).update(
            tmdb_enrichment_signature=TMDB_ENRICHMENT_LOCK_VALUE
        )
        content.tmdb_enrichment_signature = TMDB_ENRICHMENT_LOCK_VALUE

        from .catalog_cache import bump_catalog_generation

        bump_catalog_generation(invalidate_selections=False)
        affected_profiles = mark_profile_selections_outdated(
            trigger_reason="Canonical VOD metadata was edited manually",
            policy_ids=affected_policy_ids,
        )
        merged = merge_target is not None
        return Response(
            {
                "tmdb": _tmdb_content_payload(content),
                "canonical": _canonical_provider_payload(content),
                "merged": merged,
                "target": (
                    {
                        "id": content.id,
                        "title": (
                            content.display_name
                            or content.clean_title
                            or content.name
                        ),
                        "year": content.year,
                        "tmdb_id": str(
                            content.tmdb_match_id or content.tmdb_id or ""
                        ),
                        "content_type": content_type,
                        "relation_id": moved_relation_id,
                    }
                    if merged
                    else None
                ),
                "profile_update": (
                    "outdated" if affected_profiles else "not_required"
                ),
                "profiles_affected": affected_profiles,
            }
        )

    @action(detail=False, methods=["post"], url_path="refresh")
    def refresh(self, request):
        self._admin_only(request)
        if not CoreSettings.get_tmdb_api_token():
            raise DRFValidationError(
                {"api_token": "Configure a TMDB API read access token first."}
            )
        select_all = request.data.get("select_all") is True
        selections = request.data.get("selections") or []
        exclusions = request.data.get("exclude_selections") or []
        if not isinstance(selections, list) or not isinstance(exclusions, list):
            raise DRFValidationError({"selections": "Invalid selection."})
        if select_all:
            if selections or len(exclusions) > 500:
                raise DRFValidationError(
                    {
                        "selections": (
                            "Select-all accepts at most 500 explicitly excluded "
                            "canonical titles."
                        )
                    }
                )
        elif not 1 <= len(selections) <= 500:
            raise DRFValidationError(
                {"selections": "Choose between 1 and 500 canonical titles."}
            )

        def selection_ids(rows):
            movie_ids = []
            series_ids = []
            for row in rows:
                if not isinstance(row, dict):
                    raise DRFValidationError(
                        {"selections": "Invalid selection."}
                    )
                try:
                    content_id = int(row.get("id"))
                except (TypeError, ValueError) as exc:
                    raise DRFValidationError(
                        {"selections": "Invalid content ID."}
                    ) from exc
                target = movie_ids if row.get("content_type") == "movie" else (
                    series_ids if row.get("content_type") == "series" else None
                )
                if target is None:
                    raise DRFValidationError(
                        {"selections": "Invalid content type."}
                    )
                target.append(content_id)
            return movie_ids, series_ids

        movie_ids, series_ids = selection_ids(selections)
        exclude_movie_ids, exclude_series_ids = selection_ids(exclusions)
        selection_filters = None
        if select_all:
            filters = request.data.get("filters")
            filters = filters if isinstance(filters, dict) else {}
            content_type = str(filters.get("type") or "all")
            metadata_status = str(filters.get("metadata_status") or "")
            if content_type not in {"all", "movies", "series"}:
                raise DRFValidationError({"filters": "Invalid content type."})
            if metadata_status not in {
                "",
                "missing_tmdb",
                "missing_external_ids",
                "missing_metadata",
            }:
                raise DRFValidationError({"filters": "Invalid metadata state."})
            allowed_filter_names = {
                "type", "search", "category", "m3u_account",
                "audio_language", "subtitle_language", "resolution",
                "container_extension", "video_feature", "metadata_status",
                "genre", "anime_mode", "adult_mode", "library_added_after",
                "library_added_before",
            }
            selection_filters = {
                key: value
                for key, value in filters.items()
                if key in allowed_filter_names
            }
            selection_filters["type"] = content_type
            selection_filters["search"] = str(
                selection_filters.get("search") or ""
            ).strip()[:255]
            selection_filters["metadata_status"] = metadata_status

        from .tasks import enqueue_tmdb_enrichment

        state = VODMetadataState.objects.filter(pk=1).first()
        if state and state.status in {
            VODMetadataState.Status.QUEUED,
            VODMetadataState.Status.RUNNING,
        }:
            return Response(
                {"detail": "A TMDB metadata batch is already running."},
                status=status.HTTP_409_CONFLICT,
            )

        result = enqueue_tmdb_enrichment(
            trigger_reason="Manual TMDB metadata refresh",
            # An explicit manual request is the escape hatch for titles that
            # were already processed and locked. Automatic refreshes continue
            # to respect the enrichment signature.
            force=True,
            search_missing=True,
            movie_ids=None if select_all else movie_ids,
            series_ids=None if select_all else series_ids,
            selection_filters=selection_filters,
            exclude_movie_ids=exclude_movie_ids,
            exclude_series_ids=exclude_series_ids,
        )
        return Response(
            {**result, "state": _vod_metadata_state_payload()},
            status=status.HTTP_202_ACCEPTED,
        )

    def _lock_selection_querysets(self, request):
        selections = request.data.get("selections") or []
        exclusions = request.data.get("exclude_selections") or []
        select_all = request.data.get("select_all") is True
        if not isinstance(selections, list) or not isinstance(exclusions, list):
            raise DRFValidationError({"selections": "Invalid selection."})
        if select_all:
            if selections or len(exclusions) > 500:
                raise DRFValidationError(
                    {
                        "selections": (
                            "Select-all accepts at most 500 explicitly excluded "
                            "canonical titles."
                        )
                    }
                )
        elif not 1 <= len(selections) <= 500:
            raise DRFValidationError(
                {"selections": "Choose between 1 and 500 canonical titles."}
            )

        def ids_by_type(rows):
            result = {"movie": set(), "series": set()}
            for row in rows:
                if not isinstance(row, dict):
                    raise DRFValidationError({"selections": "Invalid selection."})
                content_type = str(row.get("content_type") or "")
                if content_type not in result:
                    raise DRFValidationError(
                        {"selections": "Invalid content type."}
                    )
                try:
                    result[content_type].add(int(row.get("id")))
                except (TypeError, ValueError) as exc:
                    raise DRFValidationError(
                        {"selections": "Invalid content ID."}
                    ) from exc
            return result

        selected = ids_by_type(selections)
        excluded = ids_by_type(exclusions)
        filters = request.data.get("filters")
        filters = filters if isinstance(filters, dict) else {}
        filtered_movies, filtered_series = (
            _filtered_vod_content(filters)
            if select_all
            else (Movie.objects.none(), Series.objects.none())
        )
        querysets = []
        for model, content_type, filtered in (
            (Movie, "movie", filtered_movies),
            (Series, "series", filtered_series),
        ):
            queryset = filtered if select_all else model.objects.filter(
                pk__in=selected[content_type]
            )
            if select_all:
                queryset = queryset.exclude(pk__in=excluded[content_type])
            querysets.append((model, queryset))
        return querysets

    @action(detail=False, methods=["post"], url_path="unlock")
    def unlock(self, request):
        """Allow selected titles to enter automatic matching again."""
        self._admin_only(request)
        unlocked = 0
        for _model, queryset in self._lock_selection_querysets(request):
            unlocked += queryset.exclude(
                tmdb_enrichment_signature=""
            ).update(tmdb_enrichment_signature="")

        return Response(
            {
                "unlocked": unlocked,
                "profile_update": "not_required",
                "profiles_affected": 0,
            }
        )

    @action(detail=False, methods=["post"], url_path="lock")
    def lock(self, request):
        """Keep selected titles out of automatic metadata matching."""
        self._admin_only(request)
        from .tasks import TMDB_ENRICHMENT_LOCK_VALUE

        querysets = list(self._lock_selection_querysets(request))
        fields = (
            "id",
            "tmdb_enrichment_signature",
        )
        if request.data.get("toggle") is True:
            selected_count = 0
            all_locked = True
            for _model, queryset in querysets:
                for content in queryset.values(*fields).iterator(chunk_size=1000):
                    selected_count += 1
                    if not content["tmdb_enrichment_signature"]:
                        all_locked = False
                        break
                if not all_locked:
                    break
            if selected_count and all_locked:
                unlocked = sum(
                    queryset.exclude(tmdb_enrichment_signature="").update(
                        tmdb_enrichment_signature=""
                    )
                    for _model, queryset in querysets
                )
                return Response(
                    {
                        "action": "unlocked",
                        "locked": 0,
                        "unlocked": unlocked,
                        "profile_update": "not_required",
                        "profiles_affected": 0,
                    }
                )

        locked = 0
        for model, queryset in querysets:
            pending = []
            for content in queryset.values(*fields).iterator(chunk_size=1000):
                if content["tmdb_enrichment_signature"]:
                    continue
                pending.append(
                    model(
                        pk=content["id"],
                        tmdb_enrichment_signature=TMDB_ENRICHMENT_LOCK_VALUE,
                    )
                )
                if len(pending) == 1000:
                    model.objects.bulk_update(
                        pending,
                        ["tmdb_enrichment_signature"],
                    )
                    locked += len(pending)
                    pending = []
            if pending:
                model.objects.bulk_update(
                    pending,
                    ["tmdb_enrichment_signature"],
                )
                locked += len(pending)

        return Response(
            {
                "action": "locked",
                "locked": locked,
                "unlocked": 0,
                "profile_update": "not_required",
                "profiles_affected": 0,
            }
        )

    @action(detail=False, methods=["post"], url_path="reset")
    def reset(self, request):
        """Reload selected canonical metadata from provider data, TMDB, or both."""
        self._admin_only(request)
        mode = str(request.data.get("mode") or "").strip()
        if mode not in {"provider", "tmdb", "all"}:
            raise DRFValidationError(
                {"mode": "Choose provider, tmdb, or all."}
            )
        selections = request.data.get("selections") or []
        if not isinstance(selections, list) or not 1 <= len(selections) <= 500:
            raise DRFValidationError(
                {"selections": "Choose between 1 and 500 canonical titles."}
            )
        movie_ids = []
        series_ids = []
        for row in selections:
            if not isinstance(row, dict):
                raise DRFValidationError({"selections": "Invalid selection."})
            try:
                content_id = int(row.get("id"))
            except (TypeError, ValueError) as exc:
                raise DRFValidationError(
                    {"selections": "Invalid content ID."}
                ) from exc
            target = movie_ids if row.get("content_type") == "movie" else (
                series_ids if row.get("content_type") == "series" else None
            )
            if target is None:
                raise DRFValidationError(
                    {"selections": "Invalid content type."}
                )
            target.append(content_id)

        if mode in {"tmdb", "all"}:
            if not CoreSettings.get_tmdb_api_token():
                raise DRFValidationError(
                    {"api_token": "Configure a TMDB API read access token first."}
                )
            state = VODMetadataState.objects.filter(pk=1).first()
            if state and state.status in {
                VODMetadataState.Status.QUEUED,
                VODMetadataState.Status.RUNNING,
            }:
                return Response(
                    {"detail": "A TMDB metadata batch is already running."},
                    status=status.HTTP_409_CONFLICT,
                )

        # Remove the derived TMDB layer before provider reconciliation. This is
        # important for the provider title fallback: a previous matched status
        # must not keep blocking the newly projected provider title.
        reset_values = {
            "display_name": "",
            "clean_title": "",
            "tmdb_metadata": {},
            "tmdb_poster_url": "",
            "tmdb_backdrop_url": "",
            "tmdb_status": "",
            "tmdb_enriched_at": None,
            "tmdb_enrichment_signature": "",
            "tmdb_lookup_excluded": False,
        }
        if mode in {"provider", "all"}:
            reset_values.update(
                tmdb_match_id="",
                tmdb_imdb_id="",
                description="",
                year=None,
                rating="",
                genre="",
            )
        movie_reset_values = dict(reset_values)
        if mode in {"provider", "all"}:
            movie_reset_values["duration_secs"] = None
        Movie.objects.filter(pk__in=movie_ids).update(**movie_reset_values)
        Series.objects.filter(pk__in=series_ids).update(**reset_values)

        if mode in {"provider", "all"}:
            from .provider_metadata import (
                MANUAL_METADATA_KEY,
                reconcile_movie_provider_metadata,
                reconcile_series_provider_metadata,
            )

            # Provider/all reset also releases administrator-owned provider
            # projections before recalculating them from the stored sources.
            for model, content_ids in (
                (Movie, movie_ids),
                (Series, series_ids),
            ):
                changed = []
                for content in model.objects.filter(pk__in=content_ids).only(
                    "id", "custom_properties"
                ):
                    properties = dict(content.custom_properties or {})
                    if MANUAL_METADATA_KEY not in properties:
                        continue
                    properties.pop(MANUAL_METADATA_KEY, None)
                    content.custom_properties = properties or None
                    changed.append(content)
                if changed:
                    model.objects.bulk_update(
                        changed, ["custom_properties"], batch_size=500
                    )

            reconcile_movie_provider_metadata(movie_ids)
            reconcile_series_provider_metadata(series_ids)
            from .tasks import refresh_canonical_clean_titles

            refresh_canonical_clean_titles(movie_ids, series_ids)

        from .catalog_cache import bump_catalog_generation

        bump_catalog_generation(invalidate_selections=False)
        if mode == "provider":
            from .profile_selection import (
                mark_profile_selections_outdated,
                profile_ids_using_canonical_content,
            )

            affected_profiles = mark_profile_selections_outdated(
                trigger_reason="Canonical VOD metadata was reloaded manually",
                policy_ids=profile_ids_using_canonical_content(
                    movie_ids=movie_ids,
                    series_ids=series_ids,
                ),
            )
            return Response(
                {
                    "reloaded": len(set(movie_ids)) + len(set(series_ids)),
                    "mode": mode,
                    "state": _vod_metadata_state_payload(),
                    "profile_update": (
                        "outdated" if affected_profiles else "not_required"
                    ),
                    "profiles_affected": affected_profiles,
                }
            )

        from .tasks import enqueue_tmdb_enrichment

        result = enqueue_tmdb_enrichment(
            trigger_reason="Selected VOD metadata was reset",
            force=True,
            movie_ids=movie_ids,
            series_ids=series_ids,
        )
        return Response(
            {**result, "mode": mode, "state": _vod_metadata_state_payload()},
            status=status.HTTP_202_ACCEPTED,
        )

    @action(detail=False, methods=["post"], url_path="title-preview")
    def title_preview(self, request):
        """Preview lookup-only title cleanup against real canonical rows."""
        self._admin_only(request)
        from .tmdb import (
            clean_lookup_title,
            normalize_title_rules,
            normalize_year_rules,
        )

        try:
            rules = normalize_title_rules(
                request.data.get("title_rules", CoreSettings.get_tmdb_title_rules())
            )
        except ValueError as exc:
            raise DRFValidationError({"title_rules": str(exc)}) from exc
        try:
            year_rules = normalize_year_rules(
                request.data.get("year_rules", CoreSettings.get_tmdb_year_rules())
            )
        except ValueError as exc:
            raise DRFValidationError({"year_rules": str(exc)}) from exc
        search = str(request.data.get("search") or "").strip()
        missing_tmdb_only = request.data.get("missing_tmdb_only") is True
        requested_items = request.data.get("items")
        select_all = request.data.get("select_all") is True
        exclusions = request.data.get("exclude_selections") or []
        try:
            page = max(1, int(request.data.get("page") or 1))
            page_size = min(100, max(1, int(request.data.get("page_size") or 50)))
        except (TypeError, ValueError) as exc:
            raise DRFValidationError(
                {"page": "Enter a valid preview page."}
            ) from exc
        if (
            requested_items is None
            and not select_all
            and not missing_tmdb_only
            and not search
        ):
            raise DRFValidationError(
                {"search": "Enter a title to search."}
            )
        rows = []

        def with_tmdb_preview_fields(queryset):
            return queryset.annotate(
                preview_tmdb_status=KeyTextTransform(
                    "status", "tmdb_metadata"
                ),
                preview_tmdb_id=KeyTextTransform("id", "tmdb_metadata"),
                preview_candidate_count=KeyTextTransform(
                    "candidate_count", "tmdb_metadata"
                ),
                preview_match_method=KeyTextTransform(
                    "match_method", "tmdb_metadata"
                ),
            )

        def preview_row(content, content_type, before, after):
            try:
                candidate_count = int(
                    content.get("preview_candidate_count") or 0
                )
            except (TypeError, ValueError):
                candidate_count = 0
            return {
                "id": content["id"],
                "content_type": content_type,
                "before": before,
                "current": content["clean_title"] or "",
                "after": after,
                "changed": before != after,
                "year": content["year"],
                "tmdb_status": str(
                    content["tmdb_status"]
                    or content.get("preview_tmdb_status")
                    or ""
                ),
                "tmdb_id": str(
                    content["tmdb_match_id"]
                    or content["tmdb_id"]
                    or content.get("preview_tmdb_id")
                    or ""
                ),
                "candidate_count": candidate_count,
                "match_method": str(
                    content.get("preview_match_method") or ""
                ),
            }

        if requested_items is not None and not select_all:
            if not isinstance(requested_items, list) or len(requested_items) > 500:
                raise DRFValidationError(
                    {"items": "Choose at most 500 canonical titles to preview."}
                )
            requested_keys = []
            ids_by_type = {"movie": set(), "series": set()}
            for item in requested_items:
                if not isinstance(item, dict):
                    raise DRFValidationError({"items": "Invalid preview item."})
                content_type = str(item.get("content_type") or "")
                if content_type not in ids_by_type:
                    raise DRFValidationError({"items": "Invalid content type."})
                try:
                    content_id = int(item.get("id"))
                except (TypeError, ValueError) as exc:
                    raise DRFValidationError({"items": "Invalid content ID."}) from exc
                requested_keys.append((content_type, content_id))
                ids_by_type[content_type].add(content_id)

            content_by_key = {}
            from .tasks import category_cleanup_rules_for_content

            for model, content_type in ((Movie, "movie"), (Series, "series")):
                queryset = with_tmdb_preview_fields(
                    model.objects.filter(id__in=ids_by_type[content_type])
                )
                content_rows = list(queryset.values(
                    "id", "name", "display_name", "clean_title", "year",
                    "tmdb_status", "tmdb_match_id", "tmdb_id",
                    "preview_tmdb_status", "preview_tmdb_id",
                    "preview_candidate_count", "preview_match_method",
                ))
                group_rules = category_cleanup_rules_for_content(
                    model, content_rows
                )
                for content in content_rows:
                    content["_group_rule"] = group_rules.get(content["id"])
                    content_by_key[(content_type, content["id"])] = content

            for content_type, content_id in requested_keys:
                content = content_by_key.get((content_type, content_id))
                if content is None:
                    continue
                before = str(content["display_name"] or content["name"] or "")
                if (
                    content["tmdb_status"] == "matched"
                    and (content["tmdb_match_id"] or content["tmdb_id"])
                    and content["display_name"]
                ):
                    after = content["display_name"].strip()
                else:
                    after = clean_lookup_title(
                        content["name"],
                        display_name=content["display_name"],
                        year=content["year"],
                        rules=rules,
                        year_rules=year_rules,
                        group_rule=content.get("_group_rule"),
                    )
                rows.append(preview_row(content, content_type, before, after))
            return Response(
                {
                    "results": rows,
                    "total": len(rows),
                    "page": 1,
                    "page_size": len(rows) or page_size,
                }
            )

        excluded_ids = {"movie": set(), "series": set()}
        if select_all:
            if not isinstance(exclusions, list) or len(exclusions) > 500:
                raise DRFValidationError(
                    {"exclude_selections": "Choose at most 500 exclusions."}
                )
            for item in exclusions:
                content_type = str((item or {}).get("content_type") or "")
                if content_type not in excluded_ids:
                    raise DRFValidationError(
                        {"exclude_selections": "Invalid content type."}
                    )
                try:
                    excluded_ids[content_type].add(int(item.get("id")))
                except (TypeError, ValueError) as exc:
                    raise DRFValidationError(
                        {"exclude_selections": "Invalid content ID."}
                    ) from exc
            filtered_movies, filtered_series = _filtered_vod_content(
                request.data.get("filters") or {}
            )

        querysets = []
        for model, content_type, relation_name in (
            (Movie, "movie", "m3u_relations"),
            (Series, "series", "m3u_relations"),
        ):
            if select_all:
                queryset = (
                    filtered_movies if content_type == "movie"
                    else filtered_series
                ).exclude(pk__in=excluded_ids[content_type])
            else:
                queryset = model.objects.filter(
                    **{f"{relation_name}__m3u_account__is_active": True}
                )
            if missing_tmdb_only:
                queryset = queryset.filter(
                    Q(tmdb_match_id=""),
                    Q(tmdb_id__isnull=True) | Q(tmdb_id=""),
                )
            queryset = queryset.distinct()
            if search:
                queryset = queryset.filter(
                    Q(name__icontains=search) | Q(display_name__icontains=search)
                )
            queryset = queryset.order_by("id")
            querysets.append((content_type, queryset, queryset.count()))

        total = sum(queryset_count for _, _, queryset_count in querysets)
        offset = (page - 1) * page_size
        remaining = page_size
        for content_type, queryset, queryset_count in querysets:
            if offset >= queryset_count:
                offset -= queryset_count
                continue
            page_rows = list(with_tmdb_preview_fields(queryset).values(
                "id", "name", "display_name", "clean_title", "year",
                "tmdb_status", "tmdb_match_id", "tmdb_id",
                "preview_tmdb_status", "preview_tmdb_id",
                "preview_candidate_count", "preview_match_method",
            )[offset : offset + remaining])
            from .tasks import category_cleanup_rules_for_content

            group_rules = category_cleanup_rules_for_content(
                Movie if content_type == "movie" else Series,
                page_rows,
            )
            for content in page_rows:
                before = str(content["display_name"] or content["name"] or "")
                if (
                    content["tmdb_status"] == "matched"
                    and (content["tmdb_match_id"] or content["tmdb_id"])
                    and content["display_name"]
                ):
                    after = content["display_name"].strip()
                else:
                    after = clean_lookup_title(
                        content["name"],
                        display_name=content["display_name"],
                        year=content["year"],
                        rules=rules,
                        year_rules=year_rules,
                        group_rule=group_rules.get(content["id"]),
                    )
                rows.append(preview_row(content, content_type, before, after))
            remaining = page_size - len(rows)
            offset = 0
            if remaining <= 0:
                break
        return Response(
            {
                "results": rows,
                "total": total,
                "page": page,
                "page_size": page_size,
            }
        )

    @action(detail=False, methods=["post"], url_path="apply-title-cleanup")
    def apply_title_cleanup(self, request):
        """Persist rule-derived lookup titles for selected canonical rows."""
        self._admin_only(request)
        from .catalog_cache import bump_catalog_generation
        from .profile_selection import (
            mark_profile_selections_outdated,
            profile_ids_using_canonical_content,
        )
        from .tasks import (
            TMDB_ENRICHMENT_LOCK_VALUE,
            category_cleanup_rules_for_content,
        )
        from .tmdb import (
            clean_lookup_title,
            normalize_title_rules,
            normalize_year_rules,
        )

        try:
            rules = normalize_title_rules(
                request.data.get("title_rules", CoreSettings.get_tmdb_title_rules())
            )
        except ValueError as exc:
            raise DRFValidationError({"title_rules": str(exc)}) from exc
        try:
            year_rules = normalize_year_rules(
                request.data.get("year_rules", CoreSettings.get_tmdb_year_rules())
            )
        except ValueError as exc:
            raise DRFValidationError({"year_rules": str(exc)}) from exc
        selections = request.data.get("selections") or []
        select_all = request.data.get("select_all") is True
        exclusions = request.data.get("exclude_selections") or []
        filters = request.data.get("filters") or {}
        if not isinstance(selections, list) or not isinstance(exclusions, list):
            raise DRFValidationError({"selections": "Invalid selection."})
        if select_all and (selections or len(exclusions) > 500):
            raise DRFValidationError(
                {"selections": "Select-all accepts at most 500 exclusions."}
            )
        if not select_all and not 1 <= len(selections) <= 500:
            raise DRFValidationError(
                {"selections": "Choose between 1 and 500 canonical titles."}
            )

        def ids_by_type(rows):
            result = {"movie": set(), "series": set()}
            for row in rows:
                content_type = str((row or {}).get("content_type") or "")
                if content_type not in result:
                    raise DRFValidationError({"selections": "Invalid content type."})
                try:
                    result[content_type].add(int(row.get("id")))
                except (TypeError, ValueError) as exc:
                    raise DRFValidationError({"selections": "Invalid content ID."}) from exc
            return result

        selected = ids_by_type(selections)
        excluded = ids_by_type(exclusions)
        filtered_movies, filtered_series = (
            _filtered_vod_content(filters)
            if select_all
            else (Movie.objects.none(), Series.objects.none())
        )
        changed = {"movie": [], "series": []}
        output_changed = {"movie": [], "series": []}
        processed_count = 0
        locked_skipped = 0
        for model, content_type in (
            (Movie, "movie"),
            (Series, "series"),
        ):
            queryset = model.objects.all()
            if select_all:
                queryset = (
                    filtered_movies if content_type == "movie" else filtered_series
                )
                queryset = queryset.exclude(pk__in=excluded[content_type])
            else:
                queryset = queryset.filter(pk__in=selected[content_type])
            locked_skipped += queryset.exclude(
                tmdb_enrichment_signature=""
            ).count()
            queryset = queryset.filter(tmdb_enrichment_signature="")
            content_ids = list(queryset.values_list("id", flat=True))
            for offset in range(0, len(content_ids), 500):
                contents = list(model.objects.filter(
                    id__in=content_ids[offset : offset + 500]
                ).only(
                    "id", "name", "display_name", "clean_title", "year",
                    "tmdb_status", "tmdb_match_id", "tmdb_id",
                    "tmdb_enrichment_signature",
                ))
                group_rules = category_cleanup_rules_for_content(model, contents)
                updates = []
                for content in contents:
                    processed_count += 1
                    if (
                        content.tmdb_status == "matched"
                        and (content.tmdb_match_id or content.tmdb_id)
                        and content.display_name
                    ):
                        clean_title = content.display_name.strip()[:255]
                    else:
                        clean_title = clean_lookup_title(
                            content.name,
                            display_name=content.display_name,
                            year=content.year,
                            rules=rules,
                            year_rules=year_rules,
                            group_rule=group_rules.get(content.id),
                        )[:255]
                    if clean_title != content.clean_title:
                        output_changed[content_type].append(content.id)
                        changed[content_type].append(content.id)
                        content.clean_title = clean_title
                    content.tmdb_enrichment_signature = (
                        TMDB_ENRICHMENT_LOCK_VALUE
                    )
                    updates.append(content)
                model.objects.bulk_update(
                    updates,
                    ["clean_title", "tmdb_enrichment_signature"],
                    batch_size=500,
                )

        changed_count = len(changed["movie"]) + len(changed["series"])
        affected_profiles = []
        if changed_count:
            bump_catalog_generation(invalidate_selections=False)
        output_changed_count = (
            len(output_changed["movie"]) + len(output_changed["series"])
        )
        if output_changed_count:
            affected_profiles = mark_profile_selections_outdated(
                trigger_reason="Canonical VOD cleanup titles changed",
                policy_ids=profile_ids_using_canonical_content(
                    movie_ids=output_changed["movie"],
                    series_ids=output_changed["series"],
                ),
            )
        return Response({
            "updated": changed_count,
            "processed": processed_count,
            "locked_skipped": locked_skipped,
            "profile_update": "outdated" if affected_profiles else "not_required",
            "profiles_affected": affected_profiles,
        })


class VODAccessPolicyViewSet(viewsets.ModelViewSet):
    queryset = VODAccessPolicy.objects.prefetch_related(
        "users",
        "vodpolicycategory_set__category_relation__category",
        "vodpolicycategory_set__category_relation__m3u_account",
    )
    serializer_class = VODAccessPolicySerializer
    pagination_class = None

    def get_permissions(self):
        return [Authenticated()]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return self.queryset.none()
        if _is_admin(self.request.user):
            return self.queryset
        return self.queryset.filter(
            Q(users=self.request.user) | Q(is_default=True)
        ).distinct()

    def _admin_only(self, request):
        return None if _is_admin(request.user) else Response(status=status.HTTP_403_FORBIDDEN)

    def create(self, request, *args, **kwargs):
        denied = self._admin_only(request)
        if denied is not None:
            return denied
        return super().create(request, *args, **kwargs)

    def update(self, request, *args, **kwargs):
        denied = self._admin_only(request)
        if denied is not None:
            return denied
        return super().update(request, *args, **kwargs)

    def partial_update(self, request, *args, **kwargs):
        denied = self._admin_only(request)
        if denied is not None:
            return denied
        return super().partial_update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        denied = self._admin_only(request)
        if denied is not None:
            return denied
        policy = self.get_object()
        replacement = None
        if policy.is_default:
            replacement = (
                VODAccessPolicy.objects.filter(is_active=True)
                .exclude(pk=policy.pk)
                .order_by("name", "id")
                .first()
            )
            if replacement is None:
                return Response(
                    {
                        "detail": (
                            "The last active default VOD output profile cannot "
                            "be deleted. Create or activate another profile first."
                        )
                    },
                    status=status.HTTP_409_CONFLICT,
                )
        with transaction.atomic():
            self.perform_destroy(policy)
            if replacement is not None:
                VODAccessPolicy.objects.filter(pk=replacement.pk).update(
                    is_default=True
                )
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"], url_path="rebuild")
    def rebuild(self, request, pk=None):
        """Explicitly rebuild one saved output profile catalog."""
        denied = self._admin_only(request)
        if denied is not None:
            return denied
        policy = self.get_object()
        if policy.selection_status in {
            VODAccessPolicy.SelectionStatus.PENDING,
            VODAccessPolicy.SelectionStatus.BUILDING,
        }:
            return Response(VODAccessPolicySerializer(policy).data)

        from .profile_selection import enqueue_profile_selection_rebuild

        enqueue_profile_selection_rebuild(
            policy.pk,
            trigger_reason="VOD output profile catalog was rebuilt manually",
        )
        policy.refresh_from_db()
        return Response(VODAccessPolicySerializer(policy).data)

    @action(detail=True, methods=["get"], url_path="selections")
    def selections(self, request, pk=None):
        denied = self._admin_only(request)
        if denied is not None:
            return denied
        policy = self.get_object()
        content_type = request.query_params.get("type", "movie")
        if content_type not in {"movie", "series"}:
            return Response(
                {"detail": "type must be movie or series"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        selection_state = VODAccessPolicySerializer(policy).data
        if not selection_state["selection_available"]:
            return Response(
                {
                    "status": policy.selection_status,
                    "current": False,
                    "available": False,
                    "counts": policy.selection_counts or {},
                    "results": [],
                    "count": 0,
                },
                status=status.HTTP_409_CONFLICT,
            )

        is_movie = content_type == "movie"
        selection_model = (
            VODMovieProfileSelection if is_movie else VODSeriesProfileSelection
        )
        canonical = "movie" if is_movie else "series"
        queryset = selection_model.objects.filter(
            policy=policy,
            generation=policy.active_selection_generation,
        ).select_related(
            canonical,
            "relation__m3u_account",
            "category",
        )
        search = request.query_params.get("search", "").strip()
        if search:
            queryset = queryset.filter(
                Q(output_name__icontains=search)
                | Q(**{f"{canonical}__name__icontains": search})
            )
        if request.query_params.get("m3u_account"):
            queryset = queryset.filter(
                relation__m3u_account_id=request.query_params["m3u_account"]
            )
        if request.query_params.get("category"):
            queryset = queryset.filter(category_id=request.query_params["category"])
        metadata_status = str(
            request.query_params.get("metadata_status") or ""
        ).strip()
        if metadata_status:
            queryset = queryset.filter(
                _vod_metadata_filter_q(metadata_status, prefix=f"{canonical}__")
            )
        queryset = _apply_vod_canonical_filters(
            queryset,
            request.query_params,
            content_type,
            prefix=f"{canonical}__",
        )
        if request.query_params.get("container_extension"):
            queryset = queryset.filter(
                container_extension__iexact=request.query_params[
                    "container_extension"
                ]
            )
        video_features = normalize_video_features(
            [request.query_params.get("video_feature", "")]
        )
        video_feature = video_features[0] if video_features else ""
        compatible_features = compatible_video_features(video_feature)
        resolution = request.query_params.get("resolution", "").lower().rstrip("p")
        if resolution:
            try:
                queryset = queryset.filter(resolution_height=int(resolution))
            except ValueError:
                return Response(
                    {"detail": "resolution must be a vertical pixel count"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        audio = normalize_language_code(
            request.query_params.get("audio_language", "")
        )
        subtitles = normalize_language_code(
            request.query_params.get("subtitle_language", "")
        )
        python_language_filter = connection.vendor != "postgresql" and (
            audio or subtitles or video_feature
        )
        if not python_language_filter:
            if audio:
                queryset = queryset.filter(audio_languages__contains=[audio])
            if subtitles:
                queryset = queryset.filter(subtitle_languages__contains=[subtitles])
            if video_feature:
                feature_query = Q()
                for feature in compatible_features:
                    feature_query |= Q(
                        effective_metadata__video_features__contains=[feature]
                    )
                queryset = queryset.filter(feature_query)

        queryset = queryset.order_by(f"{canonical}__name", "id")
        try:
            page = max(int(request.query_params.get("page", 1)), 1)
            page_size = min(
                max(int(request.query_params.get("page_size", 50)), 1), 200
            )
        except ValueError:
            return Response(
                {"detail": "page and page_size must be integers"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if python_language_filter:
            matching = [
                row
                for row in queryset
                if (not audio or audio in (row.audio_languages or []))
                and (
                    not subtitles
                    or subtitles in (row.subtitle_languages or [])
                )
                and (
                    not video_feature
                    or not set(compatible_features).isdisjoint(
                        normalize_video_features(
                            (row.effective_metadata or {}).get("video_features")
                        )
                    )
                )
            ]
            matching_count = len(matching)
            rows = matching[(page - 1) * page_size : page * page_size]
        else:
            matching_count = queryset.count()
            rows = list(queryset[(page - 1) * page_size : page * page_size])

        from .utils import canonical_output_name, get_vod_source_name

        # The preview represents the last activated catalog while a newer
        # configuration may already be building.  Base its presentation on
        # that activated mode so switching Compact/Variants does not make the
        # unchanged catalog briefly look like the newly saved mode.
        preview_mode = (
            selection_state.get("selection_active_mode") or policy.export_mode
        )
        compact_source_counts = {}
        if preview_mode == VODAccessPolicy.ExportMode.COMPACT and rows:
            from .policies import (
                policy_category_map,
                relation_edition,
                relation_metadata,
                relation_policy_evaluation,
            )

            category_mapping = policy_category_map(policy)
            canonical_ids = {
                getattr(row, f"{canonical}_id") for row in rows
            }
            relation_model = M3UMovieRelation if is_movie else M3USeriesRelation
            candidate_relations = relation_model.objects.filter(
                m3u_account__is_active=True,
                **{f"{canonical}_id__in": canonical_ids},
            ).select_related(
                canonical,
                "m3u_account",
                "category",
            )
            for candidate in candidate_relations.iterator(chunk_size=1000):
                category_relation = category_mapping.get(
                    (candidate.m3u_account_id, candidate.category_id)
                )
                metadata = relation_metadata(candidate, category_relation)
                if not relation_policy_evaluation(
                    candidate,
                    policy,
                    category_mapping=category_mapping,
                    metadata=metadata,
                )["allowed"]:
                    continue
                edition = relation_edition(
                    candidate,
                    policy,
                    category_mapping=category_mapping,
                    metadata=metadata,
                )
                key = (getattr(candidate, f"{canonical}_id"), edition["key"])
                compact_source_counts[key] = compact_source_counts.get(key, 0) + 1

        results = []
        for row in rows:
            content = getattr(row, canonical)
            relation = row.relation
            source_name = get_vod_source_name(relation, content.name)
            results.append(
                {
                    "id": row.id,
                    "content_type": content_type,
                    "canonical_id": content.id,
                    "name": row.output_name
                    or (
                        canonical_output_name(
                            content.name,
                            display_name=content.display_name,
                            year=content.year,
                        )
                        if preview_mode == VODAccessPolicy.ExportMode.COMPACT
                        else source_name
                    ),
                    "year": content.year,
                    "relation_id": relation.id,
                    "source_name": source_name,
                    "m3u_account_id": relation.m3u_account_id,
                    "m3u_account_name": relation.m3u_account.name,
                    "category_id": row.category_id,
                    "category_name": row.category.name if row.category else "",
                    "metadata": row.effective_metadata,
                    "resolution": row.resolution_height,
                    "container_extension": row.container_extension,
                    "edition_key": row.edition_key,
                    "edition_name": row.edition_name,
                    "edition_suffix": row.edition_suffix,
                    "source_count": compact_source_counts.get(
                        (content.id, row.edition_key), 1
                    ),
                }
            )
        return Response(
            {
                "status": policy.selection_status,
                "current": selection_state["selection_current"],
                "available": True,
                "counts": policy.selection_counts or {},
                "count": matching_count,
                "page": page,
                "page_size": page_size,
                "results": results,
            }
        )

    @action(detail=True, methods=["get"], url_path="candidates")
    def candidates(self, request, pk=None):
        """Return one title's sources in the exact Compact/failover order."""
        denied = self._admin_only(request)
        if denied is not None:
            return denied
        policy = self.get_object()
        content_type = request.query_params.get("type", "movie")
        try:
            canonical_id = int(request.query_params.get("canonical_id", ""))
        except (TypeError, ValueError):
            return Response(
                {"detail": "canonical_id must be an integer"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if content_type == "movie":
            canonical = Movie.objects.filter(pk=canonical_id).first()
            relations = list(
                M3UMovieRelation.objects.filter(movie_id=canonical_id)
                .select_related("movie", "m3u_account", "category")
                .order_by("id")
            )
        elif content_type == "series":
            canonical = Series.objects.filter(pk=canonical_id).first()
            relations = list(
                M3USeriesRelation.objects.filter(series_id=canonical_id)
                .select_related("series", "m3u_account", "category")
                .order_by("id")
            )
        elif content_type == "episode":
            canonical = Episode.objects.select_related("series").filter(
                pk=canonical_id
            ).first()
            relations = list(
                M3UEpisodeRelation.objects.filter(episode_id=canonical_id)
                .select_related(
                    "episode__series",
                    "m3u_account",
                    "series_relation__category",
                )
                .order_by("id")
            )
        else:
            return Response(
                {"detail": "type must be movie, series, or episode"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if canonical is None:
            return Response(
                {"detail": "Content not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        from .policies import (
            policy_category_map,
            relation_category,
            relation_edition,
            relation_metadata,
            relation_policy_evaluation,
            relation_rank,
        )
        from .utils import canonical_output_name, get_vod_source_name

        category_mapping = policy_category_map(policy)
        requested_edition_key = str(
            request.query_params.get("edition_key") or ""
        )
        current_relation_id = request.query_params.get("current_relation_id")
        try:
            current_relation_id = int(current_relation_id)
        except (TypeError, ValueError):
            current_relation_id = None
        current_relation = next(
            (
                relation
                for relation in relations
                if relation.id == current_relation_id
            ),
            None,
        )
        if not requested_edition_key and current_relation is not None:
            requested_edition_key = relation_edition(
                current_relation,
                policy,
                category_mapping=category_mapping,
            )["key"]
        evaluated = []
        for relation in relations:
            category = relation_category(relation)
            category_relation = category_mapping.get(
                (relation.m3u_account_id, getattr(category, "id", None))
            )
            metadata = relation_metadata(relation, category_relation)
            evaluation = relation_policy_evaluation(
                relation,
                policy,
                category_mapping=category_mapping,
                metadata=metadata,
            )
            edition = relation_edition(
                relation,
                policy,
                category_mapping=category_mapping,
                metadata=metadata,
            )
            if not relation.m3u_account.is_active:
                evaluation = {
                    "allowed": False,
                    "reason": "provider_inactive",
                    "rule_id": "",
                }
            elif (
                requested_edition_key
                and edition["key"] != requested_edition_key
                and evaluation["allowed"]
            ):
                evaluation = {
                    "allowed": False,
                    "reason": "different_edition",
                    "rule_id": edition["rule_id"],
                }
            evaluated.append(
                (
                    relation_rank(
                        relation,
                        category_mapping,
                        policy,
                        metadata=metadata,
                    ),
                    relation,
                    category,
                    metadata,
                    evaluation,
                    edition,
                )
            )

        eligible = sorted(
            (entry for entry in evaluated if entry[4]["allowed"]),
            key=lambda entry: entry[0],
            reverse=True,
        )
        excluded = sorted(
            (entry for entry in evaluated if not entry[4]["allowed"]),
            key=lambda entry: (
                entry[1].m3u_account.name.lower(),
                entry[1].id,
            ),
        )
        rows = []
        for position, (
            _, relation, category, metadata, evaluation, edition
        ) in enumerate(
            eligible + excluded,
            start=1,
        ):
            allowed = evaluation["allowed"]
            eligible_position = position if position <= len(eligible) else None
            content_name = (
                relation.movie.name
                if content_type == "movie"
                else relation.series.name
                if content_type == "series"
                else relation.episode.name
            )
            source_relation = (
                relation.series_relation
                if content_type == "episode" and relation.series_relation
                else relation
            )
            source_name = get_vod_source_name(source_relation, content_name)
            if content_type == "episode":
                provider_episode = relation.custom_properties or {}
                if not isinstance(provider_episode, dict):
                    provider_episode = {}
                provider_info = provider_episode.get("info") or {}
                if not isinstance(provider_info, dict):
                    provider_info = {}
                source_name = (
                    provider_episode.get("title")
                    or provider_info.get("name")
                    or content_name
                )
            rows.append(
                {
                    "relation_id": relation.id,
                    "provider_asset_id": str(
                        getattr(relation, "stream_id", None)
                        or getattr(relation, "external_series_id", None)
                        or ""
                    ),
                    "source_name": source_name,
                    "m3u_account_id": relation.m3u_account_id,
                    "m3u_account_name": relation.m3u_account.name,
                    "category_id": getattr(category, "id", None),
                    "category_name": getattr(category, "name", "") or "",
                    "metadata": metadata,
                    "container_extension": (
                        getattr(relation, "container_extension", "")
                        or metadata.get("container_extension")
                        or ""
                    ),
                    "allowed": allowed,
                    "position": eligible_position,
                    "selected": bool(
                        allowed
                        and eligible_position == 1
                        and policy.export_mode == VODAccessPolicy.ExportMode.COMPACT
                    ),
                    "current": relation.id == current_relation_id,
                    "reason": evaluation["reason"],
                    "rule_id": evaluation["rule_id"],
                    "edition_key": edition["key"],
                    "edition_name": edition["name"],
                    "edition_suffix": edition["suffix"],
                }
            )

        canonical_name = canonical.name
        if content_type in {"movie", "series"}:
            canonical_name = canonical_output_name(
                canonical.name,
                display_name=canonical.display_name,
            )
        return Response(
            {
                "profile_id": policy.id,
                "profile_name": policy.name,
                "export_mode": policy.export_mode,
                "content_type": content_type,
                "canonical_id": canonical.id,
                "canonical_name": canonical_name,
                "edition_key": requested_edition_key,
                "count": len(rows),
                "eligible_count": len(eligible),
                "results": rows,
            }
        )

    @action(detail=False, methods=["post"], url_path="preview-stream-filter")
    def preview_stream_filter(self, request):
        """Evaluate one draft filter against the current source inventory.

        This intentionally does not build or mutate a profile.  It evaluates
        the complete ordered draft, then returns only sources for which the
        requested rule is the first match.  The bounded sample keeps this
        useful on very large provider catalogs without materializing another
        catalog in PostgreSQL.
        """
        denied = self._admin_only(request)
        if denied is not None:
            return denied

        source_rules = request.data.get("source_rules", [])
        target_rule_id = str(request.data.get("target_rule_id") or "")
        category_relation_ids = request.data.get("category_relation_ids", [])
        restrict_to_categories = (
            request.data.get("restrict_to_categories") is True
        )
        if not isinstance(category_relation_ids, list):
            return Response(
                {"detail": "category_relation_ids must be a list"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        validator = VODAccessPolicySerializer()
        try:
            hard_constraints = validator.validate_hard_constraints(
                {"source_rules": source_rules}
            )
            category_relation_ids = [
                int(relation_id) for relation_id in category_relation_ids
            ]
        except (DRFValidationError, TypeError, ValueError) as exc:
            detail = getattr(exc, "detail", str(exc))
            return Response(detail, status=status.HTTP_400_BAD_REQUEST)

        normalized_rules = hard_constraints.get("source_rules", [])
        if not target_rule_id or target_rule_id not in {
            str(rule.get("id")) for rule in normalized_rules
        }:
            return Response(
                {"detail": "target_rule_id must identify a draft filter"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        from .policies import (
            _relation_source_name,
            content_rules_use_canonical_metadata,
            enabled_category_map,
            relation_metadata,
            relation_stream_filter_match,
        )

        if restrict_to_categories or category_relation_ids:
            category_relations = list(
                M3UVODCategoryRelation.objects.filter(
                    pk__in=category_relation_ids,
                    enabled=True,
                    m3u_account__is_active=True,
                ).select_related("m3u_account", "category")
            )
            category_mapping = {
                (relation.m3u_account_id, relation.category_id): (
                    relation.metadata_defaults or {}
                )
                for relation in category_relations
            }
        else:
            category_mapping = enabled_category_map()

        category_query = Q(pk__in=[])
        categories_by_account = {}
        for account_id, category_id in category_mapping:
            categories_by_account.setdefault(account_id, []).append(category_id)
        for account_id, category_ids in categories_by_account.items():
            category_query |= Q(
                m3u_account_id=account_id,
                category_id__in=category_ids,
            )

        policy = VODAccessPolicy(hard_constraints=hard_constraints)
        rows = []
        matching_count = 0
        inventory_count = 0
        sample_limit = 200
        truncated = False
        needs_canonical_metadata = content_rules_use_canonical_metadata(
            normalized_rules
        )

        for content_type, relation_model, canonical_field in (
            ("movie", M3UMovieRelation, "movie"),
            ("series", M3USeriesRelation, "series"),
        ):
            only_fields = [
                "id",
                "m3u_account",
                "m3u_account__name",
                "category",
                "category__name",
                "declared_metadata",
                "observed_metadata",
                "manual_metadata",
                "custom_properties",
                canonical_field,
                f"{canonical_field}__name",
                f"{canonical_field}__display_name",
            ]
            if content_type == "movie":
                only_fields.append("container_extension")
            if needs_canonical_metadata:
                only_fields.extend(
                    [
                        f"{canonical_field}__custom_properties",
                        f"{canonical_field}__tmdb_metadata",
                        f"{canonical_field}__tmdb_status",
                        f"{canonical_field}__tmdb_match_id",
                        f"{canonical_field}__tmdb_id",
                        f"{canonical_field}__genre",
                        f"{canonical_field}__year",
                        f"{canonical_field}__rating",
                    ]
                )
                if content_type == "movie":
                    only_fields.append("movie__is_adult")
            queryset = (
                relation_model.objects.filter(
                    m3u_account__is_active=True,
                )
                .filter(category_query)
                .select_related(
                    canonical_field,
                    "m3u_account",
                    "category",
                )
                .only(*only_fields)
                .order_by("pk")
            )
            for relation in queryset.iterator(chunk_size=2000):
                inventory_count += 1
                metadata = relation_metadata(
                    relation,
                    category_mapping.get(
                        (relation.m3u_account_id, relation.category_id), {}
                    ),
                )
                match = relation_stream_filter_match(relation, policy, metadata)
                if match is None or match[0] != target_rule_id:
                    continue
                if len(rows) >= sample_limit:
                    truncated = True
                    break
                matching_count += 1
                content = getattr(relation, canonical_field)
                provider_title = _relation_source_name(relation)
                rows.append(
                    {
                        "id": relation.id,
                        "relation_id": relation.id,
                        "content_type": content_type,
                        "canonical_id": content.id,
                        "title": provider_title,
                        "provider_title": provider_title,
                        "canonical_title": (
                            content.display_name or content.name or ""
                        ),
                        "m3u_account_name": relation.m3u_account.name,
                        "category_name": (
                            relation.category.name if relation.category else ""
                        ),
                        "result": "include" if match[1] else "exclude",
                    }
                )
            if truncated:
                break

        return Response(
            {
                "count": matching_count,
                "inventory_count": inventory_count,
                "truncated": truncated,
                "first_match_wins": True,
                "results": rows,
            }
        )


class VODPlaybackSessionViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = VODPlaybackSession.objects.select_related(
        "user", "m3u_account", "category"
    )
    serializer_class = VODPlaybackSessionSerializer

    class Pagination(PageNumberPagination):
        page_size = 50
        page_size_query_param = "page_size"
        max_page_size = 200

    pagination_class = Pagination

    def get_permissions(self):
        return [Authenticated()]

    def _base_queryset(self):
        queryset = self.queryset
        if getattr(self, "swagger_fake_view", False):
            return queryset.none()
        if not _is_admin(self.request.user):
            queryset = queryset.filter(user=self.request.user)
        return queryset

    @staticmethod
    def _datetime_bound(value, *, end=False):
        if not value:
            return None
        parsed = parse_datetime(str(value))
        if parsed is None:
            parsed_date = parse_date(str(value))
            if parsed_date is not None:
                parsed = datetime.combine(
                    parsed_date,
                    time.max if end else time.min,
                )
        if parsed is None:
            raise DRFValidationError(
                {"detail": f"Invalid date/time value: {value}"}
            )
        if timezone.is_naive(parsed):
            parsed = timezone.make_aware(parsed)
        return parsed

    def _apply_history_filters(self, queryset, filters):
        search = str(filters.get("search") or "").strip()
        if search:
            queryset = queryset.filter(
                Q(content_name__icontains=search)
                | Q(provider_asset_id__icontains=search)
            )

        username = str(filters.get("username") or "").strip()
        if username:
            queryset = queryset.filter(user__username__icontains=username)

        for field in ("user", "m3u_account", "category"):
            value = str(filters.get(field) or "").strip()
            if value:
                queryset = queryset.filter(**{f"{field}_id": value})

        for field in ("status", "mode"):
            value = str(filters.get(field) or "").strip()
            if value:
                queryset = queryset.filter(**{field: value})

        content_type = str(filters.get("content_type") or "").strip()
        if content_type == "series":
            queryset = queryset.filter(content_type__in=("series", "episode"))
        elif content_type:
            queryset = queryset.filter(content_type=content_type)

        started_after = self._datetime_bound(filters.get("started_after"))
        started_before = self._datetime_bound(
            filters.get("started_before"), end=True
        )
        if started_after:
            queryset = queryset.filter(started_at__gte=started_after)
        if started_before:
            queryset = queryset.filter(started_at__lte=started_before)
        return queryset.order_by("-started_at", "-id")

    def get_queryset(self):
        return self._apply_history_filters(
            self._base_queryset(), self.request.query_params
        )

    @action(detail=False, methods=["get"], url_path="facets")
    def facets(self, request):
        queryset = self._base_queryset()
        users = list(
            queryset.exclude(user_id=None)
            .order_by("user__username")
            .values("user_id", "user__username")
            .distinct()
        )
        accounts = list(
            queryset.exclude(m3u_account_id=None)
            .order_by("m3u_account__name")
            .values("m3u_account_id", "m3u_account__name")
            .distinct()
        )
        categories = list(
            queryset.exclude(category_id=None)
            .order_by("category__name")
            .values("category_id", "category__name", "m3u_account_id")
            .distinct()
        )
        return Response(
            {
                "users": [
                    {
                        "value": str(row["user_id"]),
                        "label": row["user__username"],
                    }
                    for row in users
                ],
                "accounts": [
                    {
                        "value": str(row["m3u_account_id"]),
                        "label": row["m3u_account__name"],
                    }
                    for row in accounts
                ],
                "categories": [
                    {
                        "value": str(row["category_id"]),
                        "label": row["category__name"],
                        "m3u_account": str(row["m3u_account_id"]),
                    }
                    for row in categories
                ],
                "retention_days": (
                    CoreSettings.get_vod_playback_history_retention_days()
                ),
                "can_manage_history": _is_admin(request.user),
            }
        )

    @action(detail=False, methods=["put"], url_path="retention")
    def retention(self, request):
        if not _is_admin(request.user):
            raise PermissionDenied(
                "Only administrators can change playback history retention."
            )
        try:
            retention_days = int(request.data.get("retention_days", 0))
            retention_days = CoreSettings.set_vod_playback_history_retention_days(
                retention_days
            )
        except (TypeError, ValueError) as exc:
            raise DRFValidationError({"retention_days": str(exc)})

        if retention_days > 0:
            from .tasks import cleanup_vod_playback_history

            cleanup_vod_playback_history.delay()
        return Response({"retention_days": retention_days})

    @action(detail=False, methods=["get"], url_path="stats")
    def stats(self, request):
        queryset = self._apply_history_filters(
            self._base_queryset(), request.query_params
        )
        totals = queryset.aggregate(
            sessions=Count("id"),
            watched_seconds=Sum("watched_seconds"),
            bytes_sent=Sum("bytes_sent"),
        )
        failovers = queryset.filter(failover_count__gt=0).count()
        popular = list(
            queryset.exclude(content_name="")
            .values("content_name", "content_type")
            .annotate(plays=Count("id"), watched_seconds=Sum("watched_seconds"))
            .order_by("-plays", "-watched_seconds", "content_name")[:10]
        )
        return Response(
            {
                **{key: value or 0 for key, value in totals.items()},
                "failover_sessions": failovers,
                "popular": popular,
            }
        )

    def _selected_history(self, request):
        if not _is_admin(request.user):
            raise PermissionDenied(
                "Only administrators can modify playback history."
            )
        filters = request.data.get("filters")
        filters = filters if isinstance(filters, dict) else {}
        queryset = self._apply_history_filters(self._base_queryset(), filters)

        selected_ids = request.data.get("ids", [])
        excluded_ids = request.data.get("exclude_ids", [])
        if not isinstance(selected_ids, list) or not isinstance(excluded_ids, list):
            raise DRFValidationError(
                {"detail": "ids and exclude_ids must be arrays"}
            )
        try:
            selected_ids = [int(value) for value in selected_ids]
            excluded_ids = [int(value) for value in excluded_ids]
        except (TypeError, ValueError):
            raise DRFValidationError(
                {"detail": "ids and exclude_ids must contain integers"}
            )

        if request.data.get("select_all") is True:
            if excluded_ids:
                queryset = queryset.exclude(pk__in=excluded_ids)
            return queryset
        if not selected_ids:
            return queryset.none()
        return queryset.filter(pk__in=selected_ids)

    @action(detail=False, methods=["post"], url_path="bulk-delete")
    def bulk_delete(self, request):
        queryset = self._selected_history(request)
        selected_count = queryset.count()
        queryset.delete()
        return Response({"deleted_sessions": selected_count})

    @action(detail=False, methods=["patch"], url_path="bulk-metadata")
    def bulk_metadata(self, request):
        queryset = self._selected_history(request).exclude(relation_id=None)
        selected_count = queryset.count()
        updates = request.data.get("updates", {})
        if not isinstance(updates, dict):
            return Response(
                {"detail": "updates must be an object"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        allowed_fields = {
            "audio_languages",
            "subtitle_languages",
            "resolution",
            "video_features",
        }
        normalized_updates = {}
        values_to_validate = {}
        for field, spec in updates.items():
            if field not in allowed_fields or not isinstance(spec, dict):
                return Response(
                    {"detail": f"Unsupported metadata update: {field}"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            mode = spec.get("mode")
            if mode not in {"set", "clear"}:
                return Response(
                    {"detail": f"{field} mode must be set or clear"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            normalized_updates[field] = {"mode": mode}
            if mode == "set":
                values_to_validate[field] = spec.get("value")

        if not normalized_updates:
            return Response(
                {"detail": "At least one metadata field must change"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        validated_values, _locked_fields = _validated_manual_source_metadata(
            values_to_validate
        )
        for field, value in validated_values.items():
            normalized_updates[field]["value"] = value

        source_refs = set(
            queryset.order_by().values_list("content_type", "relation_id").distinct()
        )
        updated_count = 0
        movie_ids = set()
        series_ids = set()
        with transaction.atomic():
            for content_type, model in (
                ("movie", M3UMovieRelation),
                ("series", M3USeriesRelation),
                ("episode", M3UEpisodeRelation),
            ):
                relation_ids = {
                    relation_id
                    for source_type, relation_id in source_refs
                    if source_type == content_type and relation_id
                }
                relations = list(model.objects.filter(pk__in=relation_ids))
                for relation in relations:
                    manual = dict(relation.manual_metadata or {})
                    locked = set(relation.locked_fields or [])
                    for field, spec in normalized_updates.items():
                        if spec["mode"] == "clear":
                            manual.pop(field, None)
                            locked.discard(field)
                        else:
                            manual[field] = spec.get("value")
                            locked.add(field)
                    relation.manual_metadata = manual
                    relation.locked_fields = sorted(locked)
                    if content_type == "movie":
                        movie_ids.add(relation.movie_id)
                    elif content_type == "series":
                        series_ids.add(relation.series_id)
                    else:
                        series_ids.add(relation.episode.series_id)
                if relations:
                    model.objects.bulk_update(
                        relations,
                        ["manual_metadata", "locked_fields"],
                        batch_size=500,
                    )
                    updated_count += len(relations)

        profile_update = "not_required"
        affected_titles = 0
        if updated_count:
            affected_titles = None
            if request.data.get("select_all") is not True:
                if (
                    len(movie_ids) + len(series_ids)
                    <= PLAYBACK_METADATA_INLINE_TITLE_LIMIT
                ):
                    affected_titles = len(movie_ids) + len(series_ids)

            from .catalog_cache import bump_catalog_generation
            from .profile_selection import mark_profile_selections_outdated

            bump_catalog_generation(invalidate_selections=False)
            affected_profiles = mark_profile_selections_outdated(
                trigger_reason="Playback-derived VOD source metadata was edited",
            )
            profile_update = (
                "outdated" if affected_profiles else "not_required"
            )
        else:
            affected_profiles = 0

        return Response(
            {
                "selected_sessions": selected_count,
                "updated_sources": updated_count,
                "affected_titles": affected_titles,
                "profile_update": profile_update,
                "profiles_affected": affected_profiles,
            }
        )

    @action(detail=True, methods=["post"], url_path="telemetry")
    def telemetry(self, request, pk=None):
        playback = self.get_object()
        event = request.data.get("event")
        metadata = request.data.get("metadata", {})
        if metadata and not isinstance(metadata, dict):
            return Response(
                {"detail": "metadata must be an object"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        status_by_event = {
            "started": VODPlaybackSession.Status.PROXYING,
            "progress": playback.status,
            "stopped": VODPlaybackSession.Status.STOPPED,
            "completed": VODPlaybackSession.Status.COMPLETED,
            "failed": VODPlaybackSession.Status.FAILED,
        }
        if event not in status_by_event:
            return Response(
                {"detail": "Unsupported telemetry event"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        playback.mode = VODPlaybackSession.Mode.PLAYER
        playback.status = status_by_event[event]
        try:
            bytes_sent = int(request.data.get("bytes_sent") or 0)
            watched_seconds = int(request.data.get("watched_seconds") or 0)
        except (TypeError, ValueError):
            return Response(
                {"detail": "bytes_sent and watched_seconds must be integers"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        playback.bytes_sent = max(playback.bytes_sent, bytes_sent)
        playback.watched_seconds = max(
            playback.watched_seconds, watched_seconds
        )
        playback.observed_metadata = {
            **(playback.observed_metadata or {}),
            **metadata,
        }
        if event in {"stopped", "completed", "failed"}:
            playback.ended_at = timezone.now()
        if event == "failed":
            playback.error = str(request.data.get("error") or "")[:2000]
        playback.save()
        if metadata:
            relation = _playback_source_relation(playback)
            if relation is not None:
                relation.apply_observation(metadata)
        return Response(self.get_serializer(playback).data)


def _authenticated_user(request):
    """Return the request user when authenticated, else None."""
    user = getattr(request, "user", None)
    if user is not None and getattr(user, "is_authenticated", False):
        return user
    return None


def _request_query_params(request):
    """Return query parameters for DRF requests and direct Django view tests."""
    return getattr(request, "query_params", getattr(request, "GET", {}))


class VODPagination(PageNumberPagination):
    page_size = 20  # Default page size to match frontend default
    page_size_query_param = "page_size"  # Allow clients to specify page size
    max_page_size = 100  # Prevent excessive page sizes for VOD content


class MovieFilter(django_filters.FilterSet):
    name = django_filters.CharFilter(lookup_expr="icontains")
    m3u_account = django_filters.NumberFilter(field_name="m3u_relations__m3u_account__id")
    category = django_filters.CharFilter(method='filter_category')
    year = django_filters.NumberFilter()
    year_gte = django_filters.NumberFilter(field_name="year", lookup_expr="gte")
    year_lte = django_filters.NumberFilter(field_name="year", lookup_expr="lte")
    is_adult = django_filters.BooleanFilter()
    library_added_after = django_filters.IsoDateTimeFilter(
        field_name="library_added_at", lookup_expr="gte"
    )
    library_added_before = django_filters.IsoDateTimeFilter(
        field_name="library_added_at", lookup_expr="lte"
    )

    class Meta:
        model = Movie
        fields = ['name', 'm3u_account', 'category', 'year', 'is_adult']

    def filter_category(self, queryset, name, value):
        """Custom category filter that handles 'name|type' format"""
        if not value:
            return queryset

        valid_types = {choice[0] for choice in VODCategory.CATEGORY_TYPE_CHOICES}
        category_name, category_type = parse_category_filter_value(value, valid_types)
        if category_type is not None:
            return queryset.filter(
                m3u_relations__category__name=category_name,
                m3u_relations__category__category_type=category_type,
            )
        return queryset.filter(m3u_relations__category__name=category_name)


class MovieViewSet(RawImageContentNegotiationMixin, viewsets.ReadOnlyModelViewSet):
    """ViewSet for Movie content"""
    queryset = Movie.objects.all()
    serializer_class = MovieSerializer
    pagination_class = VODPagination

    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_class = MovieFilter
    search_fields = ['name', 'description', 'genre']
    ordering_fields = ['name', 'year', 'created_at', 'library_added_at']
    ordering = ['name']

    def get_permissions(self):
        try:
            return [perm() for perm in permission_classes_by_action[self.action]]
        except KeyError:
            if self.action == 'image':
                return [AllowAny()]
            return [Authenticated()]

    def get_queryset(self):
        user = _authenticated_user(self.request)
        if not is_vod_movies_enabled(user=user):
            return Movie.objects.none()

        query_params = _request_query_params(self.request)

        # Apply active account, selected account, and category to the same
        # concrete source relation. The filter backend may repeat the latter
        # two predicates, but cannot broaden this relation-exact result set.
        filters = {
            "m3u_account": query_params.get("m3u_account", ""),
            "category": query_params.get("category", ""),
            "audio_language": query_params.get("audio_language", ""),
            "subtitle_language": query_params.get("subtitle_language", ""),
            "resolution": query_params.get("resolution", ""),
            "container_extension": query_params.get("container_extension", ""),
            "video_feature": query_params.get("video_feature", ""),
        }
        movies, _ = _filtered_vod_content(filters)
        qs = movies.select_related('logo').prefetch_related(
            _vod_source_relation_prefetch(M3UMovieRelation)
        )
        if (
            user is not None
            and user.user_level < 10
            and (user.custom_properties or {}).get('hide_adult_content', False)
        ):
            qs = qs.filter(is_adult=False)
        return qs

    @extend_schema(responses=M3UMovieRelationSerializer(many=True))
    @action(detail=True, methods=['get'], url_path='providers')
    def get_providers(self, request, pk=None):
        """Get all providers (M3U accounts) that have this movie"""
        movie = self.get_object()
        relations = M3UMovieRelation.objects.filter(
            movie=movie,
            m3u_account__is_active=True
        ).select_related('m3u_account', 'category').order_by(
            '-m3u_account__priority', 'id'
        )

        serializer = M3UMovieRelationSerializer(relations, many=True)
        return Response(serializer.data)


    @extend_schema(
        parameters=[
            OpenApiParameter(
                name='relation_id',
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                required=False,
                description='Specific M3U movie relation ID to use',
            ),
            OpenApiParameter(
                name='force_refresh',
                type=OpenApiTypes.BOOL,
                location=OpenApiParameter.QUERY,
                required=False,
                description='Force refresh of advanced provider data',
            ),
        ],
        responses={
            200: MovieProviderInfoSerializer,
            400: OpenApiResponse(description='Invalid relation or no active provider'),
            404: OpenApiResponse(description='Relation not found or not active'),
        },
    )
    @action(detail=True, methods=['get'], url_path='provider-info')
    def provider_info(self, request, pk=None):
        """Get provider details, fetching them once unless refresh is forced."""
        movie = self.get_object()

        relation_id = request.query_params.get('relation_id')
        if relation_id is not None:
            try:
                relation_id = int(relation_id)
            except (TypeError, ValueError):
                return Response(
                    {'error': 'Invalid relation_id'},
                    status=status.HTTP_400_BAD_REQUEST
                )

        qs = M3UMovieRelation.objects.filter(
            movie=movie,
            m3u_account__is_active=True
        ).select_related('m3u_account')

        if relation_id is not None:
            relation = qs.filter(id=relation_id).first()
            if not relation:
                return Response(
                    {'error': 'Relation not found or not active'},
                    status=status.HTTP_404_NOT_FOUND
                )
        else:
            relation = qs.order_by('-m3u_account__priority', 'id').first()

        if not relation:
            return Response(
                {'error': 'No active M3U account associated with this movie'},
                status=status.HTTP_400_BAD_REQUEST
            )

        force_refresh = request.query_params.get('force_refresh', 'false').lower() == 'true'
        detailed_fetched = (relation.custom_properties or {}).get('detailed_fetched', False)
        needs_refresh = force_refresh or not detailed_fetched

        if needs_refresh:
            # Trigger advanced data refresh
            logger.debug(f"Refreshing advanced data for movie {movie.id} (relation ID: {relation.id})")
            refresh_movie_advanced_data(relation.id, force_refresh=force_refresh)

            # Refresh objects from database after task completion
            movie.refresh_from_db()
            relation.refresh_from_db()

        # Use refreshed data from database
        custom_props = relation.custom_properties or {}
        info = custom_props.get('detailed_info', {})
        movie_data = custom_props.get('movie_data', {})

        movie_props = movie.custom_properties or {}
        artwork = prefer_relation_artwork(
            custom_props,
            movie_props,
            tmdb_poster_url=movie.tmdb_poster_url,
            tmdb_backdrop_url=movie.tmdb_backdrop_url,
            prefer_tmdb=CoreSettings.get_tmdb_prefer_artwork(),
        )
        account_id = relation.m3u_account_id
        backdrop_path = rewrite_backdrop_paths(
            request,
            'movie',
            movie.id,
            artwork['backdrop_path'],
            m3u_account_id=account_id,
        )
        # Relation/object still first; synced VODLogo only when none is available.
        if is_proxyable_image_url(artwork['movie_image']):
            movie_image = rewrite_single_image_url(
                request,
                'movie',
                movie.id,
                'movie_image',
                artwork['movie_image'],
                m3u_account_id=account_id,
            )
        elif movie.logo:
            movie_image = vodlogo_cache_url(request, movie.logo)
        else:
            movie_image = ''
        tmdb = _tmdb_content_payload(movie)
        canonical = _canonical_provider_payload(movie)

        # Coerce loose provider values so serializer output matches OpenAPI types.
        raw_rating = movie.rating or info.get('rating')
        if raw_rating is None or raw_rating == '':
            rating_value = None
        else:
            rating_value = str(raw_rating)

        year_value = movie.year if movie.year is not None else info.get('year')
        try:
            year_value = int(year_value) if year_value not in (None, '') else None
        except (TypeError, ValueError):
            year_value = movie.year

        duration_value = movie.duration_secs if movie.duration_secs is not None else info.get('duration_secs')
        try:
            duration_value = int(duration_value) if duration_value not in (None, '') else None
        except (TypeError, ValueError):
            duration_value = movie.duration_secs

        try:
            bitrate_value = int(info.get('bitrate', 0) or 0)
        except (TypeError, ValueError):
            bitrate_value = 0

        # Build response with available data, then coerce through the serializer so
        # runtime JSON types match the OpenAPI schema used by generated clients.
        response_data = {
            'id': movie.id,
            'uuid': movie.uuid,
            'stream_id': relation.stream_id,
            'name': info.get('name', movie.name),
            'o_name': info.get('o_name', '') or '',
            'description': info.get('description', info.get('plot', movie.description)),
            'plot': info.get('plot', info.get('description', movie.description)),
            'year': year_value,
            'release_date': (movie.custom_properties or {}).get('release_date') or info.get('release_date') or info.get('releasedate', '') or '',
            'genre': movie.genre or info.get('genre', '') or '',
            'director': (movie.custom_properties or {}).get('director') or info.get('director', '') or '',
            'actors': (movie.custom_properties or {}).get('actors') or info.get('actors', '') or '',
            'country': (movie.custom_properties or {}).get('country') or info.get('country', '') or '',
            'rating': rating_value,
            'tmdb_id': tmdb['id'] or movie.tmdb_id or info.get('tmdb_id') or None,
            'imdb_id': (
                tmdb['external_ids']['imdb_id']
                or movie.imdb_id
                or info.get('imdb_id')
                or None
            ),
            'tmdb': tmdb,
            'canonical': canonical,
            'youtube_trailer': (movie.custom_properties or {}).get('youtube_trailer') or info.get('youtube_trailer') or info.get('trailer', '') or '',
            'duration_secs': duration_value,
            'age': info.get('age', '') or '',
            'backdrop_path': backdrop_path,
            # All three mirror the resolved cover so the UI never falls back to a
            # raw provider URL that bypasses the proxy.
            'cover': movie_image,
            'cover_big': movie_image,
            'movie_image': movie_image,
            'bitrate': bitrate_value,
            'video': info.get('video', {}) or {},
            'audio': info.get('audio', {}) or {},
            'container_extension': movie_data.get('container_extension', 'mp4') or 'mp4',
            'direct_source': movie_data.get('direct_source', '') or '',
            'category_id': str(movie_data.get('category_id', '') or ''),
            'added': movie_data.get('added', '') or '',
            'source_metadata': effective_relation_metadata(relation),
            'm3u_account': {
                'id': relation.m3u_account.id,
                'name': relation.m3u_account.name,
                'account_type': relation.m3u_account.account_type
            }
        }
        return Response(MovieProviderInfoSerializer(response_data).data)

    @action(detail=True, methods=['get'], url_path='image', permission_classes=[AllowAny])
    def image(self, request, pk=None):
        """Proxy a stored movie image (backdrop, movie_image, poster_path)."""
        return vod_image_action(self, request, 'movie')


class EpisodeFilter(django_filters.FilterSet):
    name = django_filters.CharFilter(lookup_expr="icontains")
    series = django_filters.NumberFilter(field_name="series__id")
    m3u_account = django_filters.NumberFilter(field_name="m3u_relations__m3u_account__id")
    season_number = django_filters.NumberFilter()
    episode_number = django_filters.NumberFilter()
    library_added_after = django_filters.IsoDateTimeFilter(
        field_name="library_added_at", lookup_expr="gte"
    )
    library_added_before = django_filters.IsoDateTimeFilter(
        field_name="library_added_at", lookup_expr="lte"
    )

    class Meta:
        model = Episode
        fields = ['name', 'series', 'm3u_account', 'season_number', 'episode_number']


class SeriesFilter(django_filters.FilterSet):
    name = django_filters.CharFilter(lookup_expr="icontains")
    m3u_account = django_filters.NumberFilter(field_name="m3u_relations__m3u_account__id")
    category = django_filters.CharFilter(method='filter_category')
    year = django_filters.NumberFilter()
    year_gte = django_filters.NumberFilter(field_name="year", lookup_expr="gte")
    year_lte = django_filters.NumberFilter(field_name="year", lookup_expr="lte")
    library_added_after = django_filters.IsoDateTimeFilter(
        field_name="library_added_at", lookup_expr="gte"
    )
    library_added_before = django_filters.IsoDateTimeFilter(
        field_name="library_added_at", lookup_expr="lte"
    )

    class Meta:
        model = Series
        fields = ['name', 'm3u_account', 'category', 'year']

    def filter_category(self, queryset, name, value):
        """Custom category filter that handles 'name|type' format"""
        if not value:
            return queryset

        valid_types = {choice[0] for choice in VODCategory.CATEGORY_TYPE_CHOICES}
        category_name, category_type = parse_category_filter_value(value, valid_types)
        if category_type is not None:
            return queryset.filter(
                m3u_relations__category__name=category_name,
                m3u_relations__category__category_type=category_type,
            )
        return queryset.filter(m3u_relations__category__name=category_name)


class EpisodeViewSet(RawImageContentNegotiationMixin, viewsets.ReadOnlyModelViewSet):
    """ViewSet for Episode content"""
    queryset = Episode.objects.all()
    serializer_class = EpisodeSerializer
    pagination_class = VODPagination

    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_class = EpisodeFilter
    search_fields = ['name', 'description']
    ordering_fields = [
        'name', 'season_number', 'episode_number', 'created_at',
        'library_added_at',
    ]
    ordering = ['series__name', 'season_number', 'episode_number']

    def get_permissions(self):
        try:
            return [perm() for perm in permission_classes_by_action[self.action]]
        except KeyError:
            if self.action == 'image':
                return [AllowAny()]
            return [Authenticated()]

    def get_queryset(self):
        user = _authenticated_user(self.request)
        if not is_vod_series_enabled(user=user):
            return Episode.objects.none()

        # Only return episodes that have active M3U relations
        return Episode.objects.select_related('series').filter(
            m3u_relations__m3u_account__is_active=True
        ).distinct()

    @action(detail=True, methods=['get'], url_path='image', permission_classes=[AllowAny])
    def image(self, request, pk=None):
        """Proxy a stored episode image (movie_image, backdrop, poster_path)."""
        return vod_image_action(self, request, 'episode')


class SeriesViewSet(RawImageContentNegotiationMixin, viewsets.ReadOnlyModelViewSet):
    """ViewSet for Series management"""
    queryset = Series.objects.all()
    serializer_class = SeriesSerializer
    pagination_class = VODPagination

    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_class = SeriesFilter
    search_fields = ['name', 'description', 'genre']
    ordering_fields = ['name', 'year', 'created_at', 'library_added_at']
    ordering = ['name']

    def get_permissions(self):
        try:
            return [perm() for perm in permission_classes_by_action[self.action]]
        except KeyError:
            if self.action == 'image':
                return [AllowAny()]
            return [Authenticated()]

    def get_queryset(self):
        user = _authenticated_user(self.request)
        if not is_vod_series_enabled(user=user):
            return Series.objects.none()

        query_params = _request_query_params(self.request)

        filters = {
            "m3u_account": query_params.get("m3u_account", ""),
            "category": query_params.get("category", ""),
            "audio_language": query_params.get("audio_language", ""),
            "subtitle_language": query_params.get("subtitle_language", ""),
            "resolution": query_params.get("resolution", ""),
            "container_extension": query_params.get("container_extension", ""),
            "video_feature": query_params.get("video_feature", ""),
        }
        _, series = _filtered_vod_content(filters)
        return series.select_related('logo').prefetch_related(
            _vod_source_relation_prefetch(M3USeriesRelation)
        )

    @extend_schema(responses=M3USeriesRelationSerializer(many=True))
    @action(detail=True, methods=['get'], url_path='providers')
    def get_providers(self, request, pk=None):
        """Get all providers (M3U accounts) that have this series"""
        series = self.get_object()
        relations = M3USeriesRelation.objects.filter(
            series=series,
            m3u_account__is_active=True
        ).select_related('m3u_account', 'category').prefetch_related(
            Prefetch(
                'episode_relations',
                queryset=M3UEpisodeRelation.objects.only(
                    'id', 'series_relation_id', 'custom_properties'
                ),
                to_attr='metadata_episode_relations',
            )
        ).order_by(
            '-m3u_account__priority', 'id'
        )

        serializer = M3USeriesRelationSerializer(
            relations,
            many=True,
            context={"include_episode_technical_summary": True},
        )
        return Response(serializer.data)

    @extend_schema(responses=EpisodeWithProvidersSerializer(many=True))
    @action(detail=True, methods=['get'], url_path='episodes')
    def get_episodes(self, request, pk=None):
        """Get episodes for this series with provider information"""
        series = self.get_object()
        episodes = Episode.objects.filter(series=series).prefetch_related(
            Prefetch(
                'm3u_relations',
                queryset=M3UEpisodeRelation.objects.filter(
                    m3u_account__is_active=True
                ).select_related('m3u_account'),
            )
        ).order_by('season_number', 'episode_number')

        return Response(
            EpisodeWithProvidersSerializer(episodes, many=True).data
        )

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name='relation_id',
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                required=False,
                description='Specific M3U series relation ID to use',
            ),
            OpenApiParameter(
                name='force_refresh',
                type=OpenApiTypes.BOOL,
                location=OpenApiParameter.QUERY,
                required=False,
                description='Force refresh of series/episode data from provider',
            ),
            OpenApiParameter(
                name='refresh_interval',
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                required=False,
                description='Hours before provider data is considered stale (default 24)',
            ),
            OpenApiParameter(
                name='include_episodes',
                type=OpenApiTypes.BOOL,
                location=OpenApiParameter.QUERY,
                required=False,
                description='Include episodes grouped by season (default true)',
            ),
        ],
        responses={
            200: SeriesProviderInfoSerializer,
            400: OpenApiResponse(description='Invalid relation or no active provider'),
            404: OpenApiResponse(description='Relation not found or not active'),
            500: OpenApiResponse(description='Failed to fetch series information'),
        },
    )
    @action(detail=True, methods=['get'], url_path='provider-info')
    def series_info(self, request, pk=None):
        """Get detailed series information, refreshing from provider if needed"""
        logger.debug(f"SeriesViewSet.series_info called for series ID: {pk}")
        series = self.get_object()
        logger.debug(f"Retrieved series: {series.name} (ID: {series.id})")

        relation_id = request.query_params.get('relation_id')
        if relation_id is not None:
            try:
                relation_id = int(relation_id)
            except (TypeError, ValueError):
                return Response(
                    {'error': 'Invalid relation_id'},
                    status=status.HTTP_400_BAD_REQUEST
                )

        qs = M3USeriesRelation.objects.filter(
            series=series,
            m3u_account__is_active=True
        ).select_related('m3u_account', 'category')

        if relation_id is not None:
            relation = qs.filter(id=relation_id).first()
            if not relation:
                return Response(
                    {'error': 'Relation not found or not active'},
                    status=status.HTTP_404_NOT_FOUND
                )
        else:
            relation = qs.order_by('-m3u_account__priority', 'id').first()

        if not relation:
            return Response(
                {'error': 'No active M3U account associated with this series'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            # Check if we should refresh data (optional force refresh parameter)
            force_refresh = request.query_params.get('force_refresh', 'false').lower() == 'true'
            refresh_interval_hours = int(request.query_params.get("refresh_interval", 24))  # Default to 24 hours

            now = timezone.now()
            last_refreshed = relation.last_episode_refresh

            # Check if detailed data has been fetched
            custom_props = relation.custom_properties or {}
            episodes_fetched = custom_props.get('episodes_fetched', False)
            detailed_fetched = custom_props.get('detailed_fetched', False)

            # Force refresh if episodes have never been fetched or if forced
            if not episodes_fetched or not detailed_fetched or force_refresh:
                force_refresh = True
                logger.debug(f"Series {series.id} needs detailed/episode refresh, forcing refresh")
            elif last_refreshed is None or (now - last_refreshed) > timedelta(hours=refresh_interval_hours):
                force_refresh = True
                logger.debug(f"Series {series.id} refresh interval exceeded or never refreshed, forcing refresh")

            if force_refresh:
                logger.debug(f"Refreshing series {series.id} data from provider")
                # Use existing refresh logic with external_series_id
                from .tasks import refresh_series_episodes
                account = relation.m3u_account
                if account and account.is_active:
                    refresh_series_episodes(account, series, relation.external_series_id)
                    series.refresh_from_db()  # Reload from database after refresh
                    relation.refresh_from_db()  # Reload relation too

            # Return the database data (which should now be fresh)
            custom_props = relation.custom_properties or {}
            series_props = series.custom_properties or {}
            series_artwork = prefer_relation_artwork(
                custom_props,
                series_props,
                tmdb_poster_url=series.tmdb_poster_url,
                tmdb_backdrop_url=series.tmdb_backdrop_url,
                prefer_tmdb=CoreSettings.get_tmdb_prefer_artwork(),
            )
            account_id = relation.m3u_account_id
            # Relation/object cover first; synced VODLogo object only as fallback
            # (UI expects the logo-shaped cover payload when a VODLogo exists).
            if is_proxyable_image_url(series_artwork['movie_image']):
                proxied = rewrite_single_image_url(
                    request,
                    'series',
                    series.id,
                    'movie_image',
                    series_artwork['movie_image'],
                    m3u_account_id=account_id,
                )
                cover = {
                    'id': None,
                    'url': series_artwork['movie_image'],
                    'cache_url': proxied,
                    'name': series.name,
                }
            elif series.logo:
                cover = {
                    'id': series.logo.id,
                    'url': series.logo.url,
                    'cache_url': vodlogo_cache_url(request, series.logo),
                    'name': series.logo.name,
                }
            else:
                cover = None
            tmdb = _tmdb_content_payload(series)
            canonical = _canonical_provider_payload(series)
            include_episodes = (
                request.query_params.get('include_episodes', 'true').lower()
                == 'true'
            )
            episode_relations = []
            if custom_props.get('episodes_fetched', False):
                episode_relations = list(
                    M3UEpisodeRelation.objects.filter(
                        series_relation=relation,
                        m3u_account__is_active=True,
                    ).select_related('episode').order_by(
                        'episode__season_number',
                        'episode__episode_number',
                        'id',
                    )
                )
            source_metadata = merge_episode_provider_video_metadata(
                effective_relation_metadata(relation),
                episode_relations,
            )

            response_data = {
                'id': series.id,
                'series_id': relation.external_series_id,
                'name': get_series_display_name(series, relation),
                'description': series.description,
                'year': series.year,
                'genre': series.genre,
                'rating': series.rating,
                'tmdb_id': tmdb['id'],
                'imdb_id': tmdb['external_ids']['imdb_id'],
                'tmdb': tmdb,
                'canonical': canonical,
                'category_id': relation.category.id if relation.category else None,
                'category_name': relation.category.name if relation.category else None,
                'cover': cover,
                'backdrop_path': rewrite_backdrop_paths(
                    request,
                    'series',
                    series.id,
                    series_artwork['backdrop_path'],
                    m3u_account_id=account_id,
                ),
                'last_refreshed': series.updated_at,
                'custom_properties': series.custom_properties,
                'm3u_account': {
                    'id': relation.m3u_account.id,
                    'name': relation.m3u_account.name,
                    'account_type': relation.m3u_account.account_type
                },
                'episodes_fetched': custom_props.get('episodes_fetched', False),
                'detailed_fetched': custom_props.get('detailed_fetched', False),
                'source_metadata': source_metadata,
            }

            # Always include episodes for series info if they've been fetched
            if include_episodes and custom_props.get('episodes_fetched', False):
                logger.debug(f"Including episodes for series {series.id}")
                episodes_by_season = {}
                episode_image_parts = vod_image_url_parts(request, 'episode')

                for episode_relation in episode_relations:
                    episode = episode_relation.episode
                    season_key = str(
                        episode.season_number if episode.season_number is not None else 0
                    )
                    if season_key not in episodes_by_season:
                        episodes_by_season[season_key] = []

                    relation_props = episode_relation.custom_properties or {}
                    provider_episode = relation_props.get('info') or {}
                    if not isinstance(provider_episode, dict):
                        provider_episode = {}
                    provider_info = provider_episode.get('info') or {}
                    if not isinstance(provider_info, dict):
                        provider_info = {}
                    episode_title = (
                        provider_episode.get('title')
                        or provider_info.get('name')
                        or episode.name
                    )
                    episode_description = (
                        provider_info.get('plot')
                        or provider_info.get('overview')
                        or episode.description
                    )
                    episode_artwork = prefer_relation_artwork(
                        relation_props,
                        episode.custom_properties,
                    )
                    episode_technical = relation_declared_metadata(
                        episode_relation
                    )
                    raw_episode_image = episode_artwork['movie_image']
                    episode_data = {
                        'id': episode.id,
                        'relation_id': episode_relation.id,
                        'stream_id': episode_relation.stream_id,
                        'uuid': episode.uuid,
                        'name': episode_title,
                        'title': episode_title,
                        'episode_number': provider_episode.get(
                            'episode_num', episode.episode_number
                        ),
                        'season_number': episode.season_number,
                        'description': episode_description,
                        'air_date': provider_info.get('air_date') or episode.air_date,
                        'plot': episode_description,
                        'duration_secs': provider_info.get(
                            'duration_secs', episode.duration_secs
                        ),
                        'rating': provider_info.get('rating') or episode.rating,
                        'tmdb_id': provider_info.get('tmdb_id') or episode.tmdb_id,
                        'imdb_id': provider_info.get('imdb_id') or episode.imdb_id,
                        'movie_image': rewrite_single_image_url(
                            request,
                            'episode',
                            episode.id,
                            'movie_image',
                            raw_episode_image,
                            url_parts=episode_image_parts,
                            m3u_account_id=account_id,
                        ),
                        'container_extension': episode_relation.container_extension or 'mp4',
                        'resolution': episode_technical.get('resolution', ''),
                        'video_codec': episode_technical.get('video_codec', ''),
                        'type': 'episode',
                        'series': {
                            'id': series.id,
                            'name': series.name
                        }
                    }
                    episodes_by_season[season_key].append(episode_data)

                response_data['episodes'] = episodes_by_season
                logger.debug(f"Added {len(episodes_by_season)} seasons of episodes to response")
            elif include_episodes:
                # Episodes not yet fetched, include empty episodes list
                response_data['episodes'] = {}

            logger.debug(f"Returning series info response for series {series.id}")
            # Coerce through the serializer so runtime JSON types match OpenAPI.
            return Response(SeriesProviderInfoSerializer(response_data).data)

        except Exception as e:
            logger.error(f"Error fetching series info for series {pk}: {str(e)}")
            return Response(
                {'error': f'Failed to fetch series information: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=True, methods=['get'], url_path='image', permission_classes=[AllowAny])
    def image(self, request, pk=None):
        """Proxy a stored series image (backdrop, movie_image, poster_path)."""
        return vod_image_action(self, request, 'series')


class VODCategoryFilter(django_filters.FilterSet):
    name = django_filters.CharFilter(lookup_expr="icontains")
    category_type = django_filters.ChoiceFilter(choices=VODCategory.CATEGORY_TYPE_CHOICES)
    m3u_account = django_filters.NumberFilter(field_name="m3u_relations__m3u_account__id")

    class Meta:
        model = VODCategory
        fields = ['name', 'category_type', 'm3u_account']


class VODCategoryViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for VOD Categories"""
    queryset = VODCategory.objects.all()
    serializer_class = VODCategorySerializer

    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_class = VODCategoryFilter
    search_fields = ['name']
    ordering = ['name']

    def get_permissions(self):
        try:
            return [perm() for perm in permission_classes_by_action[self.action]]
        except KeyError:
            return [Authenticated()]

    def get_queryset(self):
        qs = VODCategory.objects.all()
        user = _authenticated_user(self.request)
        movies_allowed = is_vod_movies_enabled(user=user)
        series_allowed = is_vod_series_enabled(user=user)
        if movies_allowed and series_allowed:
            return qs
        if movies_allowed:
            return qs.filter(category_type="movie")
        if series_allowed:
            return qs.filter(category_type="series")
        return qs.none()

    def list(self, request, *args, **kwargs):
        """Override list to ensure Uncategorized categories and relations exist for all XC accounts with VOD enabled"""
        from apps.m3u.models import M3UAccount

        # Ensure Uncategorized categories exist
        movie_category, _ = VODCategory.objects.get_or_create(
            name="Uncategorized",
            category_type="movie",
            defaults={}
        )

        series_category, _ = VODCategory.objects.get_or_create(
            name="Uncategorized",
            category_type="series",
            defaults={}
        )

        # Get all active XC accounts with VOD enabled
        xc_accounts = M3UAccount.objects.filter(
            account_type=M3UAccount.Types.XC,
            is_active=True
        )

        for account in xc_accounts:
            if account.custom_properties:
                custom_props = account.custom_properties or {}
                vod_enabled = custom_props.get("enable_vod", False)

                if vod_enabled:
                    # Ensure relations exist for this account
                    auto_enable_new = False

                    M3UVODCategoryRelation.objects.get_or_create(
                        category=movie_category,
                        m3u_account=account,
                        defaults={
                            'enabled': auto_enable_new,
                            'custom_properties': {}
                        }
                    )

                    M3UVODCategoryRelation.objects.get_or_create(
                        category=series_category,
                        m3u_account=account,
                        defaults={
                            'enabled': auto_enable_new,
                            'custom_properties': {}
                        }
                    )

        # Now proceed with normal list operation
        return super().list(request, *args, **kwargs)


class UnifiedContentViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet that combines Movies and Series for unified 'All' view"""
    queryset = Movie.objects.none()  # Empty queryset, we override list method
    serializer_class = MovieSerializer  # Default serializer, overridden in list
    pagination_class = VODPagination

    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    search_fields = ['name', 'description', 'genre']
    ordering_fields = ['name', 'year', 'created_at', 'library_added_at']
    ordering = ['name']

    def get_permissions(self):
        try:
            return [perm() for perm in permission_classes_by_action[self.action]]
        except KeyError:
            return [Authenticated()]

    @action(detail=False, methods=["get"], url_path="filter-options")
    def filter_options(self, request):
        """Return technical filters that occur in the selected VOD scope."""
        user = _authenticated_user(request)
        movies_allowed = is_vod_movies_enabled(user=user)
        series_allowed = is_vod_series_enabled(user=user)
        content_type = str(request.query_params.get("type") or "all").lower()
        if content_type not in {"all", "movie", "movies", "series"}:
            raise DRFValidationError(
                {"type": "Choose all, movies, or series."}
            )
        include_movies = movies_allowed and content_type in {
            "all", "movie", "movies",
        }
        include_series = series_allowed and content_type in {"all", "series"}
        if not include_movies and not include_series:
            return Response(
                {
                    "audio_languages": [],
                    "subtitle_languages": [],
                    "resolutions": [],
                    "container_extensions": [],
                    "video_features": [],
                }
            )

        base_filters = {
            "m3u_account": request.query_params.get("m3u_account", ""),
            "category": request.query_params.get("category", ""),
        }
        cache_key = (
            f"vod_filter_options:{catalog_generation()}:"
            f"{int(include_movies)}:{int(include_series)}:"
            f"{base_filters['m3u_account']}:{base_filters['category']}"
        )
        cached = safe_cache_get(cache_key)
        if isinstance(cached, dict):
            return Response(cached)

        def source_select(joins, conditions, *, container_fallback):
            return f"""
                SELECT
                    {_effective_json_value_expression('audio_languages')}
                        AS audio_languages,
                    {_effective_json_value_expression('subtitle_languages')}
                        AS subtitle_languages,
                    {_effective_json_value_expression('video_features')}
                        AS video_features,
                    {_effective_json_scalar_expression('resolution')}
                        AS resolution,
                    {_effective_json_scalar_expression(
                        'container_extension',
                        relation_fallback=container_fallback,
                    )} AS container_extension
                FROM {joins}
                WHERE {' AND '.join(conditions)}
            """

        selects = []
        params = []
        if include_movies:
            joins, conditions, query_params, _ = _vod_relation_sql(
                base_filters, "movie"
            )
            selects.append(
                source_select(
                    joins,
                    conditions,
                    container_fallback="relation.container_extension",
                )
            )
            params.extend(query_params)
        if include_series:
            joins, conditions, query_params, _ = _vod_relation_sql(
                base_filters, "series"
            )
            selects.append(
                source_select(joins, conditions, container_fallback="NULL")
            )
            params.extend(query_params)

            episode_conditions = ["account.is_active = true"]
            episode_params = []
            account_id = str(base_filters["m3u_account"] or "").strip()
            if account_id.isdigit():
                episode_conditions.append("relation.m3u_account_id = %s")
                episode_params.append(int(account_id))
            category_value = str(base_filters["category"] or "").strip()
            if category_value:
                category_name = category_value
                category_type = None
                if "|" in category_value:
                    category_name, category_type = category_value.rsplit("|", 1)
                if category_type and category_type != "series":
                    episode_conditions.append("1 = 0")
                else:
                    episode_conditions.append("category.name = %s")
                    episode_params.append(category_name)
            episode_joins = """
                vod_m3uepisoderelation relation
                JOIN m3u_m3uaccount account
                  ON relation.m3u_account_id = account.id
                JOIN vod_m3useriesrelation parent_relation
                  ON relation.series_relation_id = parent_relation.id
                LEFT JOIN vod_vodcategory category
                  ON parent_relation.category_id = category.id
                LEFT JOIN vod_m3uvodcategoryrelation category_relation
                  ON category_relation.m3u_account_id = relation.m3u_account_id
                 AND category_relation.category_id = parent_relation.category_id
            """
            selects.append(
                source_select(
                    episode_joins,
                    episode_conditions,
                    container_fallback="relation.container_extension",
                )
            )
            params.extend(episode_params)

        sql = f"""
            WITH source_metadata AS (
                {' UNION ALL '.join(selects)}
            ), facet_values AS (
                SELECT 'audio_languages' AS facet, expanded.value
                FROM source_metadata source
                CROSS JOIN LATERAL jsonb_array_elements_text(
                    CASE
                        WHEN jsonb_typeof(source.audio_languages) = 'array'
                        THEN source.audio_languages
                        ELSE '[]'::jsonb
                    END
                ) AS expanded(value)
                UNION ALL
                SELECT 'subtitle_languages' AS facet, expanded.value
                FROM source_metadata source
                CROSS JOIN LATERAL jsonb_array_elements_text(
                    CASE
                        WHEN jsonb_typeof(source.subtitle_languages) = 'array'
                        THEN source.subtitle_languages
                        ELSE '[]'::jsonb
                    END
                ) AS expanded(value)
                UNION ALL
                SELECT 'video_features' AS facet, expanded.value
                FROM source_metadata source
                CROSS JOIN LATERAL jsonb_array_elements_text(
                    CASE
                        WHEN jsonb_typeof(source.video_features) = 'array'
                        THEN source.video_features
                        ELSE '[]'::jsonb
                    END
                ) AS expanded(value)
                UNION ALL
                SELECT 'resolutions' AS facet, source.resolution AS value
                FROM source_metadata source
                UNION ALL
                SELECT 'container_extensions' AS facet,
                       source.container_extension AS value
                FROM source_metadata source
            )
            SELECT facet, LOWER(BTRIM(value)) AS value
            FROM facet_values
            WHERE NULLIF(BTRIM(value), '') IS NOT NULL
            GROUP BY facet, LOWER(BTRIM(value))
            ORDER BY facet, LOWER(BTRIM(value))
        """
        available = {
            "audio_languages": set(),
            "subtitle_languages": set(),
            "resolutions": set(),
            "container_extensions": set(),
            "video_features": set(),
        }
        with connection.cursor() as cursor:
            cursor.execute(sql, params)
            for facet, value in cursor.fetchall():
                if facet in available and value:
                    if facet in {"audio_languages", "subtitle_languages"}:
                        value = normalize_language_code(value)
                    elif (
                        facet == "container_extensions"
                        and value in IMAGE_VIDEO_CODECS
                    ):
                        continue
                    available[facet].add(value)
        result = {
            facet: sorted(values) for facet, values in available.items()
        }
        safe_cache_set(cache_key, result, timeout=3600)
        return Response(result)

    def _list_variants(self, request):
        """Return one paginated row per concrete provider movie/series source."""
        user = _authenticated_user(request)
        movies_allowed = is_vod_movies_enabled(user=user)
        series_allowed = is_vod_series_enabled(user=user)
        if not movies_allowed and not series_allowed:
            return Response(
                {"count": 0, "next": False, "previous": False, "results": []}
            )

        try:
            page_size = max(
                1, min(200, int(request.query_params.get("page_size", 24)))
            )
            page_number = max(1, int(request.query_params.get("page", 1)))
        except (TypeError, ValueError):
            raise DRFValidationError(
                {"page": "Page and page_size must be numeric."}
            )
        offset = (page_number - 1) * page_size
        content_filter = request.query_params.get("type", "all")
        filters = {
            key: request.query_params.get(key, "")
            for key in (
                "m3u_account",
                "category",
                "audio_language",
                "subtitle_language",
                "resolution",
                "container_extension",
                "video_feature",
            )
        }
        movie_joins, movie_conditions, movie_params, _ = _vod_relation_sql(
            filters, "movie"
        )
        series_joins, series_conditions, series_params, _ = _vod_relation_sql(
            filters, "series"
        )
        category = filters["category"]
        category_type = category.rsplit("|", 1)[1] if "|" in category else None
        movie_enabled = (
            movies_allowed
            and content_filter != "series"
            and category_type != "series"
        )
        series_enabled = (
            series_allowed
            and content_filter != "movies"
            and category_type != "movie"
        )
        if not movie_enabled:
            movie_conditions.append("1 = 0")
        if not series_enabled:
            series_conditions.append("1 = 0")

        metadata_status = request.query_params.get("metadata_status", "")
        movie_metadata_condition = _vod_metadata_sql_condition(
            metadata_status, "movies"
        )
        series_metadata_condition = _vod_metadata_sql_condition(
            metadata_status, "series"
        )
        if movie_metadata_condition:
            movie_conditions.append(movie_metadata_condition)
        if series_metadata_condition:
            series_conditions.append(series_metadata_condition)
        movie_canonical_conditions, movie_canonical_params = (
            _vod_canonical_sql_filters(request.query_params, "movies", "movie")
        )
        series_canonical_conditions, series_canonical_params = (
            _vod_canonical_sql_filters(request.query_params, "series", "series")
        )
        movie_conditions.extend(movie_canonical_conditions)
        movie_params.extend(movie_canonical_params)
        series_conditions.extend(series_canonical_conditions)
        series_params.extend(series_canonical_params)

        movie_title = """COALESCE(
            relation.custom_properties -> 'detailed_info' ->> 'name',
            relation.custom_properties -> 'basic_data' ->> 'name',
            relation.custom_properties -> 'movie_data' ->> 'name',
            movies.name
        )"""
        series_title = """COALESCE(
            relation.custom_properties -> 'detailed_info' ->> 'name',
            relation.custom_properties -> 'basic_data' ->> 'name',
            relation.custom_properties -> 'series_data' ->> 'name',
            series.name
        )"""
        search = str(request.query_params.get("search") or "").strip()
        if search:
            search_param = f"%{search.lower()}%"
            movie_conditions.append(f"LOWER({movie_title}) LIKE %s")
            movie_params.append(search_param)
            series_conditions.append(f"LOWER({series_title}) LIKE %s")
            series_params.append(search_param)

        sql = f"""
            WITH unified_variants AS (
                SELECT relation.id AS relation_id,
                       relation.movie_id AS canonical_id,
                       {movie_title} AS source_name,
                       'movie' AS content_type
                FROM {movie_joins}
                JOIN vod_movie movies ON movies.id = relation.movie_id
                WHERE {' AND '.join(movie_conditions)}
                UNION ALL
                SELECT relation.id AS relation_id,
                       relation.series_id AS canonical_id,
                       {series_title} AS source_name,
                       'series' AS content_type
                FROM {series_joins}
                JOIN vod_series series ON series.id = relation.series_id
                WHERE {' AND '.join(series_conditions)}
            )
            SELECT relation_id, canonical_id, source_name, content_type,
                   COUNT(*) OVER() AS total_count
            FROM unified_variants
            ORDER BY LOWER(source_name), relation_id
            LIMIT %s OFFSET %s
        """
        params = movie_params + series_params + [page_size, offset]
        with connection.cursor() as cursor:
            cursor.execute(sql, params)
            columns = [column[0] for column in cursor.description]
            rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
        total = int(rows[0]["total_count"]) if rows else 0

        movie_ids = [
            row["relation_id"] for row in rows if row["content_type"] == "movie"
        ]
        series_ids = [
            row["relation_id"] for row in rows if row["content_type"] == "series"
        ]
        relation_map = {}
        if movie_ids:
            relation_map.update(
                {
                    ("movie", relation.id): relation
                    for relation in M3UMovieRelation.objects.filter(pk__in=movie_ids)
                    .select_related(
                        "movie__logo", "m3u_account", "category"
                    )
                    .defer("movie__tmdb_metadata")
                }
            )
        if series_ids:
            relation_map.update(
                {
                    ("series", relation.id): relation
                    for relation in M3USeriesRelation.objects.filter(pk__in=series_ids)
                    .select_related(
                        "series__logo", "m3u_account", "category"
                    )
                    .defer("series__tmdb_metadata")
                }
            )

        prefer_tmdb_artwork = CoreSettings.get_tmdb_prefer_artwork()
        image_parts = {
            "movie": vod_image_url_parts(request, "movie"),
            "series": vod_image_url_parts(request, "series"),
        }
        results = []
        for row in rows:
            relation = relation_map.get(
                (row["content_type"], row["relation_id"])
            )
            if relation is None:
                continue
            content = (
                relation.movie
                if row["content_type"] == "movie"
                else relation.series
            )
            effective = effective_relation_metadata(relation).get("values") or {}
            resolution = effective.get("resolution") or (
                f"{effective['height']}p" if effective.get("height") else ""
            )
            art = prefer_relation_artwork(
                relation.custom_properties or {},
                content.custom_properties or {},
                tmdb_poster_url=content.tmdb_poster_url,
                tmdb_backdrop_url=content.tmdb_backdrop_url,
                prefer_tmdb=prefer_tmdb_artwork,
            )
            artwork_url = ""
            if is_proxyable_image_url(art["movie_image"]):
                artwork_url = rewrite_single_image_url(
                    request,
                    row["content_type"],
                    content.id,
                    "movie_image",
                    art["movie_image"],
                    url_parts=image_parts[row["content_type"]],
                    m3u_account_id=relation.m3u_account_id,
                )
            elif content.logo:
                artwork_url = vodlogo_cache_url(request, content.logo)
            results.append(
                {
                    "id": content.id,
                    "uuid": str(content.uuid),
                    "canonical_id": content.id,
                    "relation_id": relation.id,
                    "is_variant": True,
                    "content_type": row["content_type"],
                    "name": _relation_provider_title(relation),
                    "canonical_name": _canonical_library_title(content),
                    "clean_title": content.clean_title or "",
                    "year": content.year,
                    "rating": content.rating or "",
                    "genre": content.genre or "",
                    "artwork_url": artwork_url,
                    "source_count": 1,
                    "source_metadata": {
                        "audio_languages": effective.get("audio_languages")
                        or effective.get("languages")
                        or [],
                        "subtitle_languages": effective.get(
                            "subtitle_languages"
                        )
                        or [],
                        "resolutions": [resolution] if resolution else [],
                        "container_extensions": [
                            effective.get("container_extension")
                        ]
                        if effective.get("container_extension")
                        else [],
                        "video_features": effective.get("video_features") or [],
                        "source_count": 1,
                    },
                    "m3u_account": {
                        "id": relation.m3u_account_id,
                        "name": relation.m3u_account.name,
                    },
                    "category": {
                        "id": relation.category_id,
                        "name": relation.category.name
                        if relation.category
                        else "Uncategorized",
                    },
                    "provider_external_ids": _relation_provider_external_ids(
                        relation
                    ),
                    "tmdb_override_id": relation.tmdb_override_id,
                    "tmdb_id": content.tmdb_match_id or content.tmdb_id or "",
                    "imdb_id": content.tmdb_imdb_id or content.imdb_id or "",
                    "tmdb_status": content.tmdb_status or "",
                    "metadata_requested": bool(content.tmdb_enriched_at),
                    "metadata_auto_locked": _tmdb_auto_lookup_locked(content),
                }
            )

        if not rows and offset:
            count_sql = f"""
                SELECT COUNT(*) FROM (
                    SELECT 1 FROM {movie_joins}
                    JOIN vod_movie movies ON movies.id = relation.movie_id
                    WHERE {' AND '.join(movie_conditions)}
                    UNION ALL
                    SELECT 1 FROM {series_joins}
                    JOIN vod_series series ON series.id = relation.series_id
                    WHERE {' AND '.join(series_conditions)}
                ) counted
            """
            with connection.cursor() as cursor:
                cursor.execute(count_sql, movie_params + series_params)
                total = cursor.fetchone()[0]
        return Response(
            {
                "count": total,
                "next": offset + page_size < total,
                "previous": page_number > 1,
                "results": results,
            }
        )

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name='category',
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Category filter. Supports 'name' or 'name|movie' / 'name|series'",
            ),
            OpenApiParameter(
                name='search',
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
            ),
            OpenApiParameter(
                name='page',
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                required=False,
            ),
            OpenApiParameter(
                name='page_size',
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                required=False,
            ),
        ],
        responses=UnifiedContentListSerializer,
    )
    def list(self, request, *args, **kwargs):
        """Override list to handle unified content properly - database-level approach"""
        from django.db import connection

        try:
            if request.query_params.get("representation") == "variants":
                return self._list_variants(request)
            user = _authenticated_user(request)
            movies_allowed = is_vod_movies_enabled(user=user)
            series_allowed = is_vod_series_enabled(user=user)
            if not movies_allowed and not series_allowed:
                return Response(
                    {"count": 0, "next": None, "previous": None, "results": []}
                )

            # Keep accidental or malicious requests from hydrating an
            # unbounded number of large canonical metadata rows at once.
            try:
                page_size = max(
                    1, min(200, int(request.query_params.get("page_size", 24)))
                )
                page_number = max(1, int(request.query_params.get("page", 1)))
            except (TypeError, ValueError):
                raise DRFValidationError(
                    {"page": "Page and page_size must be numeric."}
                )

            # Calculate offset for unified pagination
            offset = (page_number - 1) * page_size

            # For high page numbers, use raw SQL for efficiency
            # This avoids loading and sorting massive amounts of data in Python

            search = request.query_params.get('search', '')
            category = request.query_params.get('category', '')
            m3u_account = request.query_params.get('m3u_account', '')
            content_filter = request.query_params.get('type', 'all')
            list_filters = {
                "m3u_account": m3u_account,
                "category": category,
                "audio_language": request.query_params.get(
                    'audio_language', ''
                ),
                "subtitle_language": request.query_params.get(
                    'subtitle_language', ''
                ),
                "resolution": request.query_params.get('resolution', ''),
                "container_extension": request.query_params.get(
                    'container_extension', ''
                ),
                "video_feature": request.query_params.get('video_feature', ''),
            }
            (
                movie_joins,
                movie_source_conditions,
                movie_params,
                _movie_column,
            ) = _vod_relation_sql(list_filters, "movie")
            (
                series_joins,
                series_source_conditions,
                series_params,
                _series_column,
            ) = _vod_relation_sql(list_filters, "series")
            movie_source_conditions.insert(0, "relation.movie_id = movies.id")
            series_source_conditions.insert(0, "relation.series_id = series.id")

            category_type = None
            if category and '|' in category:
                _category_name, category_type = category.rsplit('|', 1)
            movie_enabled = (
                category_type != 'series' and content_filter != 'series'
            )
            series_enabled = (
                category_type != 'movie' and content_filter != 'movies'
            )

            where_conditions = [
                "EXISTS ("
                f"SELECT 1 FROM {movie_joins} "
                f"WHERE {' AND '.join(movie_source_conditions)}"
                ")"
                if movie_enabled else "1=0",
                "EXISTS ("
                f"SELECT 1 FROM {series_joins} "
                f"WHERE {' AND '.join(series_source_conditions)}"
                ")"
                if series_enabled else "1=0",
            ]
            if not movie_enabled:
                movie_params = []
            if not series_enabled:
                series_params = []

            if not movies_allowed:
                where_conditions[0] = "1=0"
            if not series_allowed:
                where_conditions[1] = "1=0"

            if search:
                search_param = f"%{search.lower()}%"
                if movie_enabled and movies_allowed:
                    where_conditions[0] += (
                        " AND LOWER(COALESCE("
                        "CASE WHEN movies.tmdb_status IN ('matched', 'manual') "
                        "THEN NULLIF(movies.display_name, '') END, "
                        "NULLIF(movies.clean_title, ''), "
                        "NULLIF(movies.display_name, ''), movies.name)) LIKE %s"
                    )
                    movie_params.append(search_param)
                if series_enabled and series_allowed:
                    where_conditions[1] += (
                        " AND LOWER(COALESCE("
                        "CASE WHEN series.tmdb_status IN ('matched', 'manual') "
                        "THEN NULLIF(series.display_name, '') END, "
                        "NULLIF(series.clean_title, ''), "
                        "NULLIF(series.display_name, ''), series.name)) LIKE %s"
                    )
                    series_params.append(search_param)

            metadata_status = request.query_params.get("metadata_status", "")
            movie_metadata_condition = _vod_metadata_sql_condition(
                metadata_status, "movies"
            )
            series_metadata_condition = _vod_metadata_sql_condition(
                metadata_status, "series"
            )
            if movie_metadata_condition and movie_enabled and movies_allowed:
                where_conditions[0] += f" AND {movie_metadata_condition}"
            if series_metadata_condition and series_enabled and series_allowed:
                where_conditions[1] += f" AND {series_metadata_condition}"
            movie_canonical_conditions, movie_canonical_params = (
                _vod_canonical_sql_filters(
                    request.query_params, "movies", "movie"
                )
            )
            series_canonical_conditions, series_canonical_params = (
                _vod_canonical_sql_filters(
                    request.query_params, "series", "series"
                )
            )
            if movie_enabled and movies_allowed:
                for condition in movie_canonical_conditions:
                    where_conditions[0] += f" AND {condition}"
                movie_params.extend(movie_canonical_params)
            if series_enabled and series_allowed:
                for condition in series_canonical_conditions:
                    where_conditions[1] += f" AND {condition}"
                series_params.extend(series_canonical_params)

            params = movie_params + series_params

            # Sort and page only narrow identity rows. Selecting the complete
            # canonical records here makes PostgreSQL carry large JSON metadata
            # through both sides of the UNION and into its parallel sort even
            # though the client only needs one small page. The bounded ORM
            # queries below hydrate details for those page identities only.
            sql = f"""
            WITH unified_content AS (
                SELECT
                    movies.id,
                    COALESCE(
                        CASE
                            WHEN movies.tmdb_status IN ('matched', 'manual')
                            THEN NULLIF(movies.display_name, '')
                        END,
                        NULLIF(movies.clean_title, ''),
                        NULLIF(movies.display_name, ''),
                        movies.name
                    ) as name,
                    'movie' as content_type
                FROM vod_movie movies
                WHERE {where_conditions[0]}

                UNION ALL

                SELECT
                    series.id,
                    COALESCE(
                        CASE
                            WHEN series.tmdb_status IN ('matched', 'manual')
                            THEN NULLIF(series.display_name, '')
                        END,
                        NULLIF(series.clean_title, ''),
                        NULLIF(series.display_name, ''),
                        series.name
                    ) as name,
                    'series' as content_type
                FROM vod_series series
                WHERE {where_conditions[1]}
            )
            SELECT id, name, content_type, COUNT(*) OVER() AS total_count
            FROM unified_content
            ORDER BY LOWER(name), content_type, id
            LIMIT %s OFFSET %s
            """

            params.extend([page_size, offset])

            from .tmdb import clean_lookup_title

            title_rules = CoreSettings.get_tmdb_title_rules()
            year_rules = CoreSettings.get_tmdb_year_rules()
            with connection.cursor() as cursor:
                cursor.execute(sql, params)
                columns = [col[0] for col in cursor.description]
                page_rows = [
                    dict(zip(columns, row)) for row in cursor.fetchall()
                ]
            total_count = (
                int(page_rows[0]["total_count"]) if page_rows else 0
            )

            movie_page_ids = [
                row["id"] for row in page_rows
                if row["content_type"] == "movie"
            ]
            series_page_ids = [
                row["id"] for row in page_rows
                if row["content_type"] == "series"
            ]
            content_by_key = {
                ("movie", content.id): content
                for content in Movie.objects.filter(
                    pk__in=movie_page_ids
                ).select_related("logo").defer("tmdb_metadata")
            }
            content_by_key.update(
                {
                    ("series", content.id): content
                    for content in Series.objects.filter(
                        pk__in=series_page_ids
                    ).select_related("logo").defer("tmdb_metadata")
                }
            )

            results = []
            for row in page_rows:
                content_type = row["content_type"]
                content = content_by_key.get((content_type, row["id"]))
                if content is None:
                    continue
                logo_data = None
                if content.logo_id:
                    logo_data = {
                        "id": content.logo_id,
                        "name": content.logo.name,
                        "url": content.logo.url,
                        "cache_url": vodlogo_cache_url(request, content.logo),
                        "movie_count": 0,
                        "series_count": 0,
                        "is_used": True,
                    }
                formatted_item = {
                    "id": content.id,
                    "uuid": str(content.uuid),
                    "name": row["name"],
                    "year": content.year,
                    "rating": float(content.rating) if content.rating else 0.0,
                    "genre": content.genre or "",
                    "duration": (
                        content.duration_secs if content_type == "movie" else None
                    ),
                    "library_added_at": (
                        content.library_added_at.isoformat()
                        if content.library_added_at else None
                    ),
                    "created_at": (
                        content.created_at.isoformat() if content.created_at else None
                    ),
                    "updated_at": (
                        content.updated_at.isoformat() if content.updated_at else None
                    ),
                    # Used only while deriving artwork for this page. Provider
                    # JSON does not belong in the lightweight list response.
                    "_custom_properties": content.custom_properties or {},
                    "tmdb_id": content.tmdb_match_id or content.tmdb_id or "",
                    "imdb_id": content.tmdb_imdb_id or content.imdb_id or "",
                    "tmdb_status": content.tmdb_status or "",
                    "clean_title": content.clean_title or "",
                    "tmdb_enriched_at": (
                        content.tmdb_enriched_at.isoformat()
                        if content.tmdb_enriched_at else None
                    ),
                    "metadata_auto_locked": _tmdb_auto_lookup_locked(content),
                    "_tmdb_poster_url": content.tmdb_poster_url or "",
                    "_tmdb_backdrop_url": content.tmdb_backdrop_url or "",
                    "logo": logo_data,
                    "content_type": content_type,
                }
                formatted_item["tmdb_lookup_title"] = clean_lookup_title(
                    row["name"],
                    year=content.year,
                    rules=title_rules,
                    year_rules=year_rules,
                )
                results.append(formatted_item)

            # Add technical source summaries with two bounded relation queries
            # for the current page.  This keeps the unified list free of N+1
            # lookups even when a title has several source editions.
            from collections import defaultdict
            from .metadata import summarize_relation_metadata
            from .policies import enabled_category_map

            movie_ids = [
                item["id"] for item in results
                if item["content_type"] == "movie"
            ]
            series_ids = [
                item["id"] for item in results
                if item["content_type"] == "series"
            ]
            relations_by_content = defaultdict(list)
            episode_relations_by_content = defaultdict(list)
            edition_counts = defaultdict(int)
            if movie_ids:
                for relation in M3UMovieRelation.objects.filter(
                    _filtered_vod_relation_query(list_filters, "movie"),
                    movie_id__in=movie_ids,
                ).select_related("m3u_account").order_by(
                    "movie_id", "-m3u_account__priority", "id"
                ):
                    relations_by_content[("movie", relation.movie_id)].append(
                        relation
                    )
                    edition_counts[("movie", relation.movie_id)] += 1
            if series_ids:
                for relation in M3USeriesRelation.objects.filter(
                    _filtered_vod_relation_query(list_filters, "series"),
                    series_id__in=series_ids,
                ).select_related("m3u_account").order_by(
                    "series_id", "-m3u_account__priority", "id"
                ):
                    relations_by_content[("series", relation.series_id)].append(
                        relation
                    )
                    edition_counts[("series", relation.series_id)] += 1
                # Episode video facts belong to the selected series edition,
                # not to an additional library source. Keep them separate so
                # a provider-derived resolution replaces that edition's
                # category default instead of displaying both as if they were
                # two independent source qualities.
                for relation in M3UEpisodeRelation.objects.filter(
                    _filtered_vod_relation_query(list_filters, "episode"),
                    episode__series_id__in=series_ids,
                ).select_related("episode", "series_relation"):
                    episode_relations_by_content[
                        ("series", relation.episode.series_id)
                    ].append(relation)
            category_mapping = enabled_category_map()
            prefer_tmdb_artwork = CoreSettings.get_tmdb_prefer_artwork()
            image_parts = {
                "movie": vod_image_url_parts(request, "movie"),
                "series": vod_image_url_parts(request, "series"),
            }
            for item in results:
                key = (item["content_type"], item["id"])
                if item["content_type"] == "series":
                    source_metadata = summarize_series_relation_metadata(
                        relations_by_content[key],
                        episode_relations_by_content[key],
                        category_mapping,
                    )
                else:
                    source_metadata = summarize_relation_metadata(
                        relations_by_content[key],
                        category_mapping,
                    )
                item["source_metadata"] = source_metadata
                # A series edition is one provider/category series relation,
                # not every episode source used to summarize its formats.
                item["source_count"] = edition_counts[key]
                item["source_metadata"]["source_count"] = edition_counts[key]
                first_relation = (
                    relations_by_content[key][0]
                    if relations_by_content[key]
                    else None
                )
                art = prefer_relation_artwork(
                    first_relation.custom_properties if first_relation else {},
                    item.pop("_custom_properties", {}),
                    tmdb_poster_url=item.pop("_tmdb_poster_url", ""),
                    tmdb_backdrop_url=item.pop("_tmdb_backdrop_url", ""),
                    prefer_tmdb=prefer_tmdb_artwork,
                )
                item["artwork_url"] = ""
                if is_proxyable_image_url(art["movie_image"]):
                    item["artwork_url"] = rewrite_single_image_url(
                        request,
                        item["content_type"],
                        item["id"],
                        "movie_image",
                        art["movie_image"],
                        url_parts=image_parts[item["content_type"]],
                        m3u_account_id=(
                            first_relation.m3u_account_id if first_relation else None
                        ),
                    )
                elif item["logo"]:
                    item["artwork_url"] = item["logo"]["cache_url"]

            # A window count reuses the already filtered narrow result instead
            # of repeating both full source/catalog scans for every page. Only
            # an out-of-range page has no row carrying that count and needs a
            # small fallback query so the UI can recover its pagination.
            if not page_rows and offset:
                count_sql = f"""
                SELECT COUNT(*) FROM (
                    SELECT 1 FROM vod_movie movies WHERE {where_conditions[0]}
                    UNION ALL
                    SELECT 1 FROM vod_series series WHERE {where_conditions[1]}
                ) as total_count
                """
                with connection.cursor() as cursor:
                    cursor.execute(count_sql, params[:-2])
                    total_count = cursor.fetchone()[0]

            # Standard DRF-style next/previous page URIs (null when absent)
            base_url = request.build_absolute_uri()
            if offset + page_size < total_count:
                next_url = replace_query_param(base_url, 'page', page_number + 1)
            else:
                next_url = None

            if page_number > 1:
                prev_page = page_number - 1
                if prev_page == 1:
                    previous_url = remove_query_param(base_url, 'page')
                else:
                    previous_url = replace_query_param(base_url, 'page', prev_page)
            else:
                previous_url = None

            response_data = {
                'count': total_count,
                'next': next_url,
                'previous': previous_url,
                'results': results
            }

            return Response(UnifiedContentListSerializer(response_data).data)

        except Exception as e:
            logger.error(f"Error in UnifiedContentViewSet.list(): {e}")
            import traceback
            logger.error(traceback.format_exc())
            return Response({'error': str(e)}, status=500)


class VODLogoPagination(PageNumberPagination):
    page_size = 100
    page_size_query_param = "page_size"
    max_page_size = 1000


class VODLogoViewSet(RawImageContentNegotiationMixin, viewsets.ModelViewSet):
    """ViewSet for VOD Logo management"""
    queryset = VODLogo.objects.all()
    serializer_class = VODLogoSerializer
    pagination_class = VODLogoPagination
    filter_backends = [SearchFilter, OrderingFilter]
    search_fields = ['name', 'url']
    ordering_fields = ['name', 'id']
    ordering = ['name']

    def get_permissions(self):
        try:
            return [perm() for perm in permission_classes_by_action[self.action]]
        except KeyError:
            if self.action == 'cache':
                return [AllowAny()]
            return [Authenticated()]

    def get_queryset(self):
        """Optimize queryset with prefetch and add filtering"""
        queryset = VODLogo.objects.prefetch_related('movie', 'series').order_by('name')

        # Filter by specific IDs
        ids = self.request.query_params.getlist('ids')
        if ids:
            try:
                id_list = [int(id_str) for id_str in ids if id_str.isdigit()]
                if id_list:
                    queryset = queryset.filter(id__in=id_list)
            except (ValueError, TypeError):
                queryset = VODLogo.objects.none()

        # Filter by usage
        used_filter = self.request.query_params.get('used', None)
        if used_filter == 'true':
            # Return logos that are used by movies OR series
            queryset = queryset.filter(
                Q(movie__isnull=False) | Q(series__isnull=False)
            ).distinct()
        elif used_filter == 'false':
            # Return logos that are NOT used by either
            queryset = queryset.filter(
                movie__isnull=True,
                series__isnull=True
            )
        elif used_filter == 'movies':
            # Return logos that are used by movies (may also be used by series)
            queryset = queryset.filter(movie__isnull=False).distinct()
        elif used_filter == 'series':
            # Return logos that are used by series (may also be used by movies)
            queryset = queryset.filter(series__isnull=False).distinct()


        # Filter by name
        name_query = self.request.query_params.get('name', None)
        if name_query:
            queryset = queryset.filter(name__icontains=name_query)

        # No pagination mode
        if self.request.query_params.get('no_pagination', 'false').lower() == 'true':
            self.pagination_class = None

        return queryset

    @extend_schema(
        responses={
            (200, 'image/*'): OpenApiTypes.BINARY,
            404: OpenApiResponse(description='Logo not found or unreachable'),
            500: OpenApiResponse(description='Error serving logo file'),
        },
    )
    @action(detail=True, methods=["get"], permission_classes=[AllowAny])
    def cache(self, request, pk=None):
        """Streams the VOD logo file, whether it's local or remote."""
        logo = self.get_object()
        return serve_vod_image(logo.url)

    @extend_schema(
        request=VODLogoBulkDeleteRequestSerializer,
        responses={
            200: VODLogoBulkDeleteResponseSerializer,
            400: OpenApiResponse(description='No logo IDs provided'),
            500: OpenApiResponse(description='Bulk delete failed'),
        },
    )
    @action(detail=False, methods=["delete"], url_path="bulk-delete")
    def bulk_delete(self, request):
        """Delete multiple VOD logos at once"""
        logo_ids = request.data.get('logo_ids', [])

        if not logo_ids:
            return Response(
                {"error": "No logo IDs provided"},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            # Get logos to delete
            logos = VODLogo.objects.filter(id__in=logo_ids)
            deleted_count = logos.count()

            # Delete them
            logos.delete()

            return Response({
                "deleted_count": deleted_count,
                "message": f"Successfully deleted {deleted_count} VOD logo(s)"
            })
        except Exception as e:
            logger.error(f"Error during bulk VOD logo deletion: {str(e)}")
            return Response(
                {"error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @extend_schema(
        request=None,
        responses={
            200: VODLogoCleanupResponseSerializer,
            500: OpenApiResponse(description='Cleanup failed'),
        },
    )
    @action(detail=False, methods=["post"])
    def cleanup(self, request):
        """Delete all VOD logos that are not used by any movies or series"""
        try:
            # Find unused logos
            unused_logos = VODLogo.objects.filter(
                movie__isnull=True,
                series__isnull=True
            )

            deleted_count = unused_logos.count()
            logo_names = list(unused_logos.values_list('name', flat=True))

            # Delete them
            unused_logos.delete()

            logger.info(f"Cleaned up {deleted_count} unused VOD logos: {logo_names}")

            return Response({
                "deleted_count": deleted_count,
                "deleted_logos": logo_names,
                "message": f"Successfully deleted {deleted_count} unused VOD logo(s)"
            })
        except Exception as e:
            logger.error(f"Error during VOD logo cleanup: {str(e)}")
            return Response(
                {"error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
