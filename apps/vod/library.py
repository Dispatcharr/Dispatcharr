"""Library editing and enrichment; no output-profile or list dependencies."""

import copy
import os
import re
import uuid
from itertools import batched

from django.db import transaction
from django.db.models import Count, Exists, F, OuterRef, Q, Value
from django.db.models.functions import Lower
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from core.models import CoreSettings

from .identity import handle_identity_conflicts, remember_alias
from .metadata import category_key, category_metadata_map, effective_source_metadata
from .models import (
    Episode,
    M3UEpisodeRelation,
    M3UMovieRelation,
    M3USeriesRelation,
    M3UVODCategoryRelation,
    Movie,
    Series,
    VODMetadataState,
)
from .presentation import (
    canonical_title,
    canonical_title_expression,
    canonical_title_search,
)
from .title_cleanup import (
    DEFAULT_TITLE_YEAR_RULES,
    clean_lookup_title,
    normalize_group_title_cleanup,
    normalize_title_rules,
    normalize_removal_rules,
    normalize_year_rules,
)
from .tmdb import (
    MAX_METADATA_LANGUAGES,
    Client,
    TMDBAuthenticationError,
    TMDBError,
    TMDBNotFound,
    apply_manual_overrides,
    normalize_language_order,
)

SETTINGS_KEY = "vod_library"
KINDS = {"movie": (Movie, M3UMovieRelation), "series": (Series, M3USeriesRelation)}
DEFAULTS = {
    "languages": ["en-US"],
    "auto_enrich": False,
    "match_missing": False,
    "prefer_artwork": True,
    "title_rules": [],
    "removal_rules": [],
    "year_rules": list(DEFAULT_TITLE_YEAR_RULES),
}


def library_settings(*, private=False):
    from .library_connection import connection_status

    settings = {**copy.deepcopy(DEFAULTS), **CoreSettings._get_group(SETTINGS_KEY)}
    settings["languages"] = normalize_language_order(settings["languages"])
    environment = os.environ.get("TMDB_API_READ_ACCESS_TOKEN") or os.environ.get(
        "TMDB_API_KEY"
    )
    token = environment or settings.get("api_token") or ""
    settings["connection"] = connection_status(
        token, settings.pop("_credential_check", None)
    )
    settings["token_configured"] = bool(token)
    settings["token_source"] = (
        "environment" if environment else "stored" if token else ""
    )
    settings.pop("api_token", None)
    if private:
        settings["api_token"] = token
    return settings


@transaction.atomic
def save_library_settings(values):
    updates = dict(values)
    if "languages" in updates:
        languages = []
        for raw in updates["languages"]:
            match = re.fullmatch(r"([a-zA-Z]{2})(?:-([a-zA-Z]{2}))?", raw)
            if not match:
                raise ValueError(
                    "Use TMDB language-region codes such as en-US or de-DE."
                )
            language = match[1].lower() + (f"-{match[2].upper()}" if match[2] else "")
            if language not in languages:
                languages.append(language)
        if not 1 <= len(languages) <= MAX_METADATA_LANGUAGES:
            raise ValueError(
                f"Choose between one and {MAX_METADATA_LANGUAGES} metadata languages."
            )
        updates["languages"] = languages
    updates.update(normalized_cleanup_rules(updates))
    if updates.pop("clear_api_token", False):
        updates["api_token"] = ""
    row, _ = CoreSettings.objects.get_or_create(
        key=SETTINGS_KEY, defaults={"name": "VOD library", "value": {}}
    )
    row = CoreSettings.objects.select_for_update().get(pk=row.pk)
    search_enabled = updates.get("match_missing") is True and not (
        row.value or {}
    ).get("match_missing", DEFAULTS["match_missing"])
    row.value = {**(row.value or {}), **updates}
    row.save(update_fields=["value"])
    if search_enabled:
        # Titles skipped only because search was disabled become eligible again.
        for model, _relation in KINDS.values():
            model.objects.filter(
                tmdb_lookup_excluded=False,
                tmdb_status="not_checked",
                tmdb_metadata___lookup_skip_reason="search_disabled",
            ).update(tmdb_status="")
    if VODMetadataState.objects.filter(pk=1).exclude(pending_enrichment=[]).exists():
        from .library_jobs import publish_pending_enrichment

        transaction.on_commit(publish_pending_enrichment)
    return library_settings()


def normalized_cleanup_rules(values):
    updates = {}
    for name, normalize in (
        ("title_rules", normalize_title_rules),
        ("removal_rules", normalize_removal_rules),
        ("year_rules", normalize_year_rules),
    ):
        if name in values:
            normalized = normalize(values[name])
            raw_values = [normalize([raw])[0]["value"] for raw in values[name]]
            if len(raw_values) != len(set(raw_values)):
                label = {
                    "title_rules": "title prefix",
                    "removal_rules": "title text removal",
                    "year_rules": "year format",
                }[name]
                raise ValueError(f"Duplicate {label}; edit the existing rule instead.")
            updates[name] = normalized
    return updates


def model_for(kind, *, source=False):
    if kind not in KINDS:
        raise ValueError("Choose movie or series content.")
    return KINDS[kind][1 if source else 0]


def relation_queryset(kind, filters=None):
    filters = filters or {}
    qs = model_for(kind, source=True).objects.filter(m3u_account__is_active=True)
    if kind == "movie" and filters.get("_hide_adult"):
        qs = qs.filter(movie__is_adult=False)
    if filters.get("account"):
        qs = qs.filter(m3u_account_id=filters["account"])
    if filters.get("category"):
        qs = qs.filter(category_id=filters["category"])
    if filters.get("content_id"):
        qs = qs.filter(**{f"{kind}_id": filters["content_id"]})
    if filters.get("search"):
        qs = qs.filter(
            canonical_title_search(
                f"{kind}__", library_settings()["languages"], filters["search"]
            )
        )
    if filters.get("locked") in ("true", "false"):
        qs = qs.filter(**{f"{kind}__tmdb_lookup_excluded": filters["locked"] == "true"})
    if filters.get("_hide_blocked"):
        qs = qs.filter(**{f"{kind}__library_blocked": False})
    elif filters.get("blocked") in ("true", "false"):
        qs = qs.filter(**{f"{kind}__library_blocked": filters["blocked"] == "true"})
    if filters.get("metadata_status"):
        state = filters["metadata_status"]
        if state == "missing_id":
            qs = qs.filter(missing_tmdb_id(f"{kind}__"))
        elif state == "missing_external_ids":
            qs = qs.filter(
                Q(**{f"{kind}__tmdb_id__isnull": True}) | Q(**{f"{kind}__tmdb_id": ""}),
                Q(**{f"{kind}__imdb_id__isnull": True}) | Q(**{f"{kind}__imdb_id": ""}),
                **{f"{kind}__tmdb_match_id": "", f"{kind}__tmdb_imdb_id": ""},
            )
            for field in ("imdb_id", "tvdb_id", "wikidata_id"):
                path = f"{kind}__tmdb_metadata__external_ids__{field}"
                qs = qs.filter(
                    Q(**{f"{path}__isnull": True}) | Q(**{path: None}) | Q(**{path: ""})
                )
        elif state == "missing_metadata":
            qs = qs.filter(**{f"{kind}__tmdb_enriched_at__isnull": True})
        elif state == "enriched":
            qs = qs.filter(**{f"{kind}__tmdb_enriched_at__isnull": False})
        elif state == "pending_lookup":
            # Internal: never looked up, reset after a changed lookup title, or failed.
            qs = qs.filter(**{f"{kind}__tmdb_status__in": ["", "failed"]})
        else:
            qs = qs.filter(**{f"{kind}__tmdb_status": state})
    from .library_filters import filter_relations

    return filter_relations(qs, kind, filters)


def missing_tmdb_id(prefix=""):
    """Titles neither matched in the Library nor identified by their provider."""
    return Q(**{f"{prefix}tmdb_match_id": ""}) & (
        Q(**{f"{prefix}tmdb_id__isnull": True}) | Q(**{f"{prefix}tmdb_id": ""})
    )


def available_accounts(filters, allowed):
    from apps.m3u.models import M3UAccount

    accounts = M3UAccount.objects.filter(is_active=True)
    present = Q()
    for kind in allowed:
        if filters.get("type", "all") not in ("all", kind):
            continue
        sources = relation_queryset(
            kind,
            {
                "_hide_adult": filters.get("_hide_adult"),
                "_hide_blocked": filters.get("_hide_blocked"),
            },
        )
        present |= Q(Exists(sources.filter(m3u_account_id=OuterRef("pk"))))
    if not present:
        return []
    return list(accounts.filter(present).order_by("name", "pk").values("id", "name"))


def library_query(filters, *, sources=False, allowed=("movie", "series")):
    parts = []
    languages = library_settings()["languages"]
    wanted = filters.get("type", "all")
    for kind in allowed:
        if wanted not in ("all", kind):
            continue
        relations = relation_queryset(kind, filters)
        if sources:
            qs = relations.annotate(
                content_id=F(f"{kind}_id"),
                sort_name=Lower(canonical_title_expression(f"{kind}__", languages)),
                content_type=Value(kind),
            )
        else:
            qs = (
                model_for(kind)
                .objects.filter(pk__in=relations.values(f"{kind}_id"))
                .annotate(
                    content_id=F("pk"),
                    sort_name=Lower(canonical_title_expression("", languages)),
                    content_type=Value(kind),
                )
            )
        parts.append(
            qs.order_by().values("id", "content_id", "sort_name", "content_type")
        )
    if not parts:
        return Movie.objects.none().values("id")
    return parts[0].union(*parts[1:]).order_by("sort_name", "content_type", "id")


def title_totals(filters, allowed):
    """Count visible canonical titles per type, ignoring the Library filters."""
    visibility = {key: value for key, value in filters.items() if key.startswith("_")}
    return {
        kind: model_for(kind)
        .objects.filter(pk__in=relation_queryset(kind, visibility).values(f"{kind}_id"))
        .count()
        for kind in allowed
    }


def source_title(relation, content):
    props = relation.custom_properties or {}
    for layer in (
        props.get("basic_data"),
        props.get("movie_data"),
        props.get("detailed_info"),
        props,
    ):
        if isinstance(layer, dict):
            name = layer.get("name") or layer.get("title")
            if isinstance(name, str) and name.strip():
                return name.strip()
    return content.name


def cleanup_for_source(relation, settings=None, *, group_rule=None):
    from .provider_metadata import normalize, source_year

    kind = "movie" if isinstance(relation, M3UMovieRelation) else "series"
    content = getattr(relation, kind)
    if group_rule is None:
        category = M3UVODCategoryRelation.objects.filter(
            m3u_account_id=relation.m3u_account_id, category_id=relation.category_id
        ).first()
        group_rule = (
            ((category.custom_properties or {}).get("title_cleanup") or {})
            if category
            else {}
        )
    settings = settings or library_settings()
    name = source_title(relation, content)
    year = source_year(
        relation,
        settings["year_rules"],
        title=name,
        removal_rules=settings.get("removal_rules"),
    ) or normalize("year", (content.tmdb_metadata or {}).get("release_date"))
    return (
        clean_lookup_title(
            name,
            year=year,
            rules=settings["title_rules"],
            year_rules=settings["year_rules"],
            removal_rules=settings.get("removal_rules"),
            group_rule=group_rule,
        ),
        year,
    )


def canonical_document(content, settings=None):
    settings = settings or library_settings()
    metadata = dict(content.tmdb_metadata or {})
    provider = content.custom_properties or {}
    for field, source in (
        ("release_date", "release_date"),
        ("director", "director"),
        ("actors", "actors"),
        ("crew", "crew"),
        ("country", "country"),
        ("age_rating", "age"),
        ("youtube_trailer", "youtube_trailer"),
    ):
        if field not in metadata and provider.get(source):
            metadata[field] = provider[source]
    if "poster_url" not in metadata:
        metadata["poster_url"] = content.tmdb_poster_url or (
            content.logo.url if content.logo_id else ""
        )
    if "backdrop_url" not in metadata:
        backdrops = provider.get("backdrop_path") or ""
        fallback = (
            next(iter(backdrops), "") if isinstance(backdrops, list) else backdrops
        )
        metadata["backdrop_url"] = content.tmdb_backdrop_url or (
            fallback if isinstance(fallback, str) else ""
        )
    overrides = metadata.get("_manual_overrides") or {}
    title = canonical_title(content, settings["languages"])
    base = overrides.get("library") or {}
    # Earlier 04 builds stored base edits in one localized override. Keep an
    # unambiguous existing edit without making language order a preference.
    descriptions = {
        row["overview"]
        for row in (overrides.get("localized") or {}).values()
        if isinstance(row, dict) and "overview" in row
    }
    overview = base.get(
        "overview",
        (
            next(iter(descriptions))
            if len(descriptions) == 1
            else content.description or metadata.get("overview", "")
        ),
    )
    date = str(metadata.get("release_date") or "")
    return {
        "id": content.pk,
        "uuid": str(content.uuid),
        "name": title,
        "provider_name": content.name,
        "clean_title": content.clean_title,
        "display_name": content.display_name,
        "year": overrides.get(
            "year",
            (
                int(date[:4])
                if re.match(r"\d{4}", date)
                else (
                    None
                    if "release_date" in overrides
                    else content.year or metadata.get("_cleanup_year")
                )
            ),
        ),
        "description": overview,
        "genre": (
            ", ".join(
                row["name"]
                for row in metadata.get("genres", [])
                if isinstance(row, dict) and row.get("name")
            )
            if "genres" in metadata
            else content.genre or ""
        ),
        "rating": str(
            metadata.get("rating")
            if metadata.get("rating") is not None
            else content.rating or ""
        ),
        "duration_secs": (
            (
                int(metadata["runtime_minutes"] * 60)
                if metadata.get("runtime_minutes") is not None
                else None
            )
            if "runtime_minutes" in metadata
            else getattr(content, "duration_secs", None)
        ),
        "tmdb_id": content.tmdb_match_id or content.tmdb_id or "",
        "imdb_id": (metadata.get("external_ids") or {}).get(
            "imdb_id", content.tmdb_imdb_id or content.imdb_id or ""
        ),
        "metadata_locked": content.tmdb_lookup_excluded,
        "library_blocked": content.library_blocked,
        "metadata_status": content.tmdb_status,
        "metadata": metadata,
        "is_adult": bool(getattr(content, "is_adult", False) or metadata.get("adult")),
        "library_added_at": content.library_added_at,
        "enriched_at": content.tmdb_enriched_at,
    }


def client_document(content, language, settings=None):
    """Library metadata for client details of a profile using Library metadata."""
    from .presentation import profile_overview

    document = canonical_document(content, settings)
    metadata = document["metadata"]
    return {
        "description": profile_overview(content, language, document["description"]),
        "year": document["year"],
        "genre": document["genre"],
        "rating": document["rating"],
        "duration_secs": document["duration_secs"],
        "tmdb_id": document["tmdb_id"],
        "imdb_id": document["imdb_id"],
        **{
            field: metadata.get(field) or ""
            for field in (
                "director",
                "actors",
                "country",
                "release_date",
                "youtube_trailer",
            )
        },
        "poster_url": content.tmdb_poster_url,
        "backdrop_url": content.tmdb_backdrop_url,
    }


# Later origins take precedence, matching effective_source_metadata.
METADATA_ORIGIN_RANK = {"category": 0, "series": 1, "provider": 2, "observed": 3, "manual": 4}
LIST_METADATA_FIELDS = (
    "audio_languages",
    "subtitle_languages",
    "resolution",
    "video_features",
)


def with_episode_resolutions(metadata, facts):
    """Use provider episode resolutions unless the source sets its own value."""
    resolutions = (facts or {}).get("episode_resolutions")
    if not resolutions or METADATA_ORIGIN_RANK.get(
        metadata["provenance"].get("resolution"), -1
    ) >= METADATA_ORIGIN_RANK["provider"]:
        return metadata
    return {
        "values": {**metadata["values"], "resolution": resolutions},
        "provenance": {**metadata["provenance"], "resolution": "provider"},
    }


def metadata_origins(values):
    """Map each displayed value to its strongest origin across sources."""
    origins = {field: {} for field in LIST_METADATA_FIELDS}
    for metadata in values:
        for field in LIST_METADATA_FIELDS:
            raw = metadata["values"].get(field)
            origin = metadata["provenance"].get(field)
            for value in raw if isinstance(raw, list) else [raw]:
                current = origins[field].get(value)
                if value and (
                    current is None
                    or METADATA_ORIGIN_RANK.get(origin, -1)
                    > METADATA_ORIGIN_RANK.get(current, -1)
                ):
                    origins[field][value] = origin
    return origins


def page_documents(rows, request, *, sources=False, filters=None):
    from .image_proxy import rewrite_single_image_url, vodlogo_cache_url
    from .library_preview import series_video_facts

    rows = list(rows)
    relations_by_kind = {}
    all_relations = []
    counts = {}
    for kind in KINDS:
        content_ids = {row["content_id"] for row in rows if row["content_type"] == kind}
        qs = (
            relation_queryset(kind, filters)
            .filter(**{f"{kind}_id__in": content_ids})
            .select_related(kind, f"{kind}__logo", "category", "m3u_account")
        )
        counts.update(
            {
                (kind, row[f"{kind}_id"]): row["count"]
                for row in qs.order_by()
                .values(f"{kind}_id")
                .annotate(count=Count("pk"))
            }
        )
        if sources:
            qs = qs.filter(
                pk__in=[row["id"] for row in rows if row["content_type"] == kind]
            )
        relations = list(qs.order_by("pk"))
        relations_by_kind[kind] = relations
        all_relations.extend(relations)
    defaults = category_metadata_map(all_relations)
    cleanup = {
        (rel.m3u_account_id, rel.category_id): (rel.custom_properties or {}).get(
            "title_cleanup", {}
        )
        for rel in M3UVODCategoryRelation.objects.filter(
            m3u_account_id__in={rel.m3u_account_id for rel in all_relations},
            category_id__in={rel.category_id for rel in all_relations},
        )
    }
    by_source = {
        ("movie" if isinstance(rel, M3UMovieRelation) else "series", rel.pk): rel
        for rel in all_relations
    }
    by_content = {}
    for kind, relations in relations_by_kind.items():
        for rel in relations:
            by_content.setdefault((kind, getattr(rel, f"{kind}_id")), []).append(rel)
    settings = library_settings()
    episode_counts = {
        row["series_id"]: row["count"]
        for row in Episode.objects.filter(
            series_id__in={
                row["content_id"] for row in rows if row["content_type"] == "series"
            }
        )
        .values("series_id")
        .annotate(count=Count("pk"))
    }
    prefer_artwork = settings["prefer_artwork"]
    episode_facts = (
        series_video_facts(relations_by_kind["series"])
        if relations_by_kind.get("series")
        else {}
    )
    result = []
    for row in rows:
        kind = row["content_type"]
        relations = by_content.get((kind, row["content_id"]), [])
        if not relations:
            continue
        relation = by_source[(kind, row["id"])] if sources else relations[0]
        content = getattr(relation, kind)
        item = canonical_document(content, settings)
        item["metadata_languages"] = settings["languages"]
        if kind == "series":
            item["episode_count"] = episode_counts.get(content.pk, 0)
        item.update(
            {
                "key": f"{kind}:{row['id']}",
                "content_type": kind,
                "content_id": content.pk,
                "source_count": counts.get((kind, content.pk), 0),
                "source_id": relation.pk if sources else None,
            }
        )
        if prefer_artwork and content.tmdb_poster_url:
            item["poster_url"] = rewrite_single_image_url(
                request, kind, content.pk, "tmdb_poster", content.tmdb_poster_url
            )
        else:
            item["poster_url"] = (
                vodlogo_cache_url(request, content.logo) if content.logo else ""
            )
        visible_relations = [relation] if sources else relations
        values = [
            with_episode_resolutions(
                effective_source_metadata(
                    rel, category_defaults=defaults.get(category_key(rel), {})
                ),
                episode_facts.get(rel.pk) if kind == "series" else None,
            )
            for rel in visible_relations
        ]
        origins = metadata_origins(values)
        item["metadata_summary"] = {
            field: sorted(origins[field]) for field in LIST_METADATA_FIELDS
        }
        item["metadata_origins"] = origins
        item["metadata_summary"]["container_extensions"] = (
            sorted(
                {
                    rel.container_extension.strip().lower()
                    for rel in visible_relations
                    if rel.container_extension and rel.container_extension.strip()
                }
            )
            if kind == "movie"
            else []
        )
        if sources:
            item.update(
                {
                    "provider_name": source_title(relation, content),
                    "account": {
                        "id": relation.m3u_account_id,
                        "name": relation.m3u_account.name,
                    },
                    "category": {
                        "id": relation.category_id,
                        "name": relation.category.name if relation.category else "",
                    },
                    "provider_id": (
                        relation.stream_id
                        if kind == "movie"
                        else relation.external_series_id
                    ),
                    "container_extension": getattr(relation, "container_extension", "")
                    or "",
                    "effective_metadata": effective_source_metadata(
                        relation,
                        category_defaults=defaults.get(category_key(relation), {}),
                    ),
                    "manual_metadata": relation.manual_metadata,
                    "locked_fields": relation.locked_fields,
                    "title_cleanup": cleanup.get(
                        (relation.m3u_account_id, relation.category_id), {}
                    ),
                }
            )
        result.append(item)
    return result


@transaction.atomic
def update_content(data, matched_metadata=None):
    from urllib.parse import parse_qs, urlparse

    from django.shortcuts import get_object_or_404

    item = get_object_or_404(
        model_for(data["content_type"]).objects.select_for_update(), pk=data["id"]
    )
    if matched_metadata is not None:
        item = apply_tmdb(item, matched_metadata)
    metadata = dict(item.tmdb_metadata or {})
    overrides = copy.deepcopy(metadata.get("_manual_overrides") or {})
    base = dict(overrides.get("library") or {})
    for field, key in (("display_name", "title"), ("description", "overview")):
        if field in data:
            base[key] = data[field]
    if base:
        overrides["library"] = base
    if "year" in data:
        overrides["year"] = data["year"]
    if "genre" in data:
        overrides["genres"] = [
            {"name": value.strip()}
            for value in data["genre"].split(",")
            if value.strip()
        ]
    if "rating" in data:
        overrides["rating"] = data["rating"]
    patch = copy.deepcopy(data.get("metadata") or {})
    if data.get("year") and "release_date" not in patch:
        known_date = metadata.get(
            "release_date", (item.custom_properties or {}).get("release_date")
        )
        if (
            re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(known_date or ""))
            and int(str(known_date)[:4]) != data["year"]
        ):
            raise ValidationError(
                {"year": "Update or clear the release date to match the year."}
            )
    if "release_date" in patch:
        date = patch["release_date"]
        if data.get("year") and date and date.year != data["year"]:
            raise ValidationError({"year": "Release date and year must agree."})
        if date and "year" not in data:
            overrides.pop("year", None)
            metadata.pop("year", None)
        patch["release_date"] = date.isoformat() if date else ""
    if "youtube_trailer" in patch:
        value = patch["youtube_trailer"]
        if value.startswith(("https://", "http://")):
            parsed = urlparse(value)
            if parsed.hostname in {"youtu.be", "www.youtu.be"}:
                value = parsed.path.strip("/")
            elif parsed.hostname in {"youtube.com", "www.youtube.com", "m.youtube.com"}:
                value = (parse_qs(parsed.query).get("v") or [""])[0]
            else:
                value = "invalid"
        if value and not re.fullmatch(r"[A-Za-z0-9_-]{11}", value):
            raise ValueError("Use a YouTube video ID or watch URL.")
        patch["youtube_trailer"] = value
    if "keywords" in patch:
        patch["keywords"] = [
            {"name": value} for value in dict.fromkeys(patch["keywords"])
        ]
    if "country" in patch:
        patch["countries"] = [
            value.strip() for value in patch["country"].split(",") if value.strip()
        ]
    for key, value in patch.items():
        if key in {"localized", "external_ids"}:
            current = overrides.setdefault(key, {})
            for name, fields in value.items():
                current[name] = (
                    {**current.get(name, {}), **fields}
                    if key == "localized"
                    else fields
                )
        else:
            overrides[key] = value
    item.tmdb_metadata = apply_manual_overrides(metadata, overrides)
    fields = ["tmdb_metadata", "tmdb_lookup_excluded"]
    if "adult" in patch and isinstance(item, Movie):
        item.is_adult = patch["adult"]
        fields.append("is_adult")
    for field in ("display_name", "clean_title"):
        if field in data:
            setattr(item, field, data[field])
            fields.append(field)
    for field, key in (
        ("tmdb_poster_url", "poster_url"),
        ("tmdb_backdrop_url", "backdrop_url"),
    ):
        if key in patch:
            setattr(item, field, patch[key])
            fields.append(field)
    item.tmdb_lookup_excluded = True
    item.save(update_fields=fields)
    return canonical_document(item)


def selected_content(selection, *, sources=False):
    """Resolve a stable snapshot; selectors never silently mean the full library."""
    if selection.get("all_matching"):
        rows = library_query(selection.get("filters") or {}, sources=sources)
        excluded = {
            (row["content_type"], row["id"]) for row in selection.get("excluded", [])
        }
        field = "id" if sources else "content_id"
        return [
            [row["content_type"], row[field]]
            for row in rows.iterator(chunk_size=1000)
            if (row["content_type"], row[field]) not in excluded
        ]
    return list(
        dict.fromkeys(
            (row["content_type"], row["id"]) for row in selection.get("items", [])
        )
    )


def patch_selected_sources(refs, patch):
    """Update a filtered source selection in bounded, locked batches."""
    count = 0
    for kind in KINDS:
        ids = [pk for selected_kind, pk in refs if selected_kind == kind]
        model = model_for(kind, source=True)
        for batch in batched(ids, 1000):
            rows = list(model.objects.select_for_update().filter(pk__in=batch))
            for row in rows:
                manual = dict(row.manual_metadata or {})
                for field, value in patch.items():
                    if value is None:
                        manual.pop(field, None)
                    else:
                        manual[field] = value
                row.manual_metadata = manual
            model.objects.bulk_update(rows, ["manual_metadata"], batch_size=1000)
            count += len(rows)
    return count


def cleanup_preview(refs, *, limit=50, settings=None):
    settings = library_settings() if settings is None else settings
    result = []
    for kind, pk in refs[:limit]:
        content = model_for(kind).objects.filter(pk=pk).first()
        if content is None:
            continue
        relation = (
            content.m3u_relations.select_related(kind, "m3u_account")
            .order_by("-m3u_account__priority", "m3u_account_id", "pk")
            .first()
        )
        title, year = (
            cleanup_for_source(relation, settings)
            if relation
            else (content.name, content.year)
        )
        result.append(
            {
                "id": pk,
                "content_type": kind,
                "before": content.display_name or content.name,
                "after": title,
                "year": year,
                "locked": content.tmdb_lookup_excluded,
                "item": {
                    "content_type": kind,
                    "content_id": pk,
                    "name": canonical_title(content, settings["languages"]),
                    "provider_name": (
                        source_title(relation, content) if relation else content.name
                    ),
                    "tmdb_id": content.tmdb_match_id or content.tmdb_id or "",
                    "metadata_status": content.tmdb_status,
                    "metadata": {
                        "_lookup_skip_reason": (content.tmdb_metadata or {}).get(
                            "_lookup_skip_reason"
                        )
                    },
                },
            }
        )
    return result


def preview_cleanup_request(data):
    settings = {**library_settings(), **normalized_cleanup_rules(data)}
    if data.get("scope") == "category":
        category = (
            M3UVODCategoryRelation.objects.select_related("category")
            .filter(
                category_id=data["category"],
                m3u_account_id=data["account"],
            )
            .first()
        )
        if category is None:
            raise ValueError("The account category was not found.")
        rule = normalize_group_title_cleanup(
            data.get(
                "title_cleanup", (category.custom_properties or {}).get("title_cleanup")
            )
        )
        kind = category.category.category_type
        sources = (
            model_for(kind, source=True)
            .objects.filter(
                m3u_account_id=data["account"], category_id=data["category"]
            )
            .select_related(kind)
            .order_by("pk")
        )
        page, size = data["page"], data["page_size"]
        result = []
        for source in sources[(page - 1) * size : page * size]:
            content = getattr(source, kind)
            title, year = cleanup_for_source(source, settings, group_rule=rule)
            result.append(
                {
                    "id": content.pk,
                    "source_id": source.pk,
                    "content_type": kind,
                    "before": source_title(source, content),
                    "after": title,
                    "year": year,
                    "locked": content.tmdb_lookup_excluded,
                }
            )
        return {
            "count": sources.count(),
            "page": page,
            "page_size": size,
            "results": result,
        }
    if data.get("scope", "selection") == "selection":
        refs = selected_content(data)
        page, size = data["page"], data["page_size"]
        return {
            "count": len(refs),
            "protected_count": sum(
                model_for(kind)
                .objects.filter(pk__in=batch, tmdb_lookup_excluded=True)
                .count()
                for kind in KINDS
                for batch in batched(
                    [pk for selected_kind, pk in refs if selected_kind == kind], 1000
                )
            ),
            "blocked_count": sum(
                model_for(kind)
                .objects.filter(pk__in=batch, library_blocked=True)
                .count()
                for kind in KINDS
                for batch in batched(
                    [pk for selected_kind, pk in refs if selected_kind == kind], 1000
                )
            ),
            "page": page,
            "page_size": size,
            "results": cleanup_preview(
                refs[(page - 1) * size : page * size], settings=settings
            ),
        }
    filters = {"search": data.get("search", "")}
    if data.get("missing_tmdb_only"):
        filters["metadata_status"] = "missing_id"
    rows = library_query(filters)
    page, page_size = data["page"], data["page_size"]
    start = (page - 1) * page_size
    refs = [
        (row["content_type"], row["content_id"])
        for row in rows[start : start + page_size]
    ]
    return {
        "count": rows.count(),
        "page": page,
        "page_size": page_size,
        "results": cleanup_preview(refs, settings=settings),
    }


def _combined_overrides(rows):
    def combine(left, right):
        result = copy.deepcopy(left)
        for key, value in right.items():
            if (
                key in result
                and isinstance(result[key], dict)
                and isinstance(value, dict)
            ):
                result[key] = combine(result[key], value)
            elif key in result and result[key] != value:
                raise ValueError("Conflicting manual metadata; matching was cancelled.")
            else:
                result[key] = copy.deepcopy(value)
        return result

    overrides = {}
    for row in rows:
        overrides = combine(
            overrides, (row.tmdb_metadata or {}).get("_manual_overrides") or {}
        )
    return overrides


def merge_library_state(current, rows):
    """Keep local presentation when provider detail ingest merges identities."""
    preferred = current
    if not current.tmdb_metadata and not current.tmdb_lookup_excluded:
        preferred = next(
            (row for row in rows if row.tmdb_lookup_excluded or row.tmdb_metadata),
            current,
        )
    current.tmdb_metadata = apply_manual_overrides(
        preferred.tmdb_metadata, _combined_overrides(rows)
    )
    current.library_added_at = min(row.library_added_at for row in rows)
    current.tmdb_lookup_excluded = any(row.tmdb_lookup_excluded for row in rows)
    current.library_blocked = any(row.library_blocked for row in rows)
    for field in (
        "display_name",
        "clean_title",
        "tmdb_match_id",
        "tmdb_imdb_id",
        "tmdb_poster_url",
        "tmdb_backdrop_url",
        "tmdb_status",
        "tmdb_enriched_at",
    ):
        if not getattr(current, field) and getattr(preferred, field):
            setattr(current, field, getattr(preferred, field))


@transaction.atomic
def apply_tmdb(content, metadata, *, lock=True):
    model = type(content)
    content = model.objects.select_for_update().get(pk=content.pk)
    query = Q(tmdb_id=metadata["id"])
    imdb = metadata.get("imdb_id") or None
    if imdb:
        query |= Q(imdb_id=imdb)
    matches = list(
        model.objects.select_for_update()
        .filter(query | Q(pk=content.pk))
        .order_by("pk")
    )
    overrides = _combined_overrides(matches)
    protected = lock or any(row.tmdb_lookup_excluded for row in matches)
    earliest = min(row.library_added_at for row in matches)
    stored_translations = {}
    for row in matches:
        previous = row.tmdb_metadata or {}
        if str(previous.get("id") or row.tmdb_match_id or "") == str(metadata["id"]):
            stored_translations.update(copy.deepcopy(previous.get("localized") or {}))
    if stored_translations:
        metadata = {
            **metadata,
            "localized": {**stored_translations, **(metadata.get("localized") or {})},
        }
    content, _ = handle_identity_conflicts(content, None, metadata["id"], imdb)
    document = apply_manual_overrides(metadata, overrides)
    content.tmdb_metadata = document
    content.tmdb_match_id = metadata["id"]
    content.tmdb_imdb_id = imdb or ""
    content.tmdb_poster_url = document.get("poster_url") or ""
    content.tmdb_backdrop_url = document.get("backdrop_url") or ""
    base = overrides.get("library") or {}
    if "title" in base:
        content.display_name = base["title"][:255]
    content.tmdb_status = "matched"
    content.tmdb_lookup_excluded = protected
    content.tmdb_enriched_at = timezone.now()
    if isinstance(content, Movie):
        content.is_adult = content.is_adult or bool(document.get("adult"))
    content.library_added_at = earliest
    content.save()
    return content


@transaction.atomic
def move_source_to_tmdb(kind, pk, metadata):
    relation = (
        model_for(kind, source=True)
        .objects.select_for_update()
        .select_related(kind)
        .get(pk=pk)
    )
    current = getattr(relation, kind)
    relation.tmdb_override_id = str(metadata["id"])
    relation.save(update_fields=["tmdb_override_id"])
    if (
        current.m3u_relations.count() == 1
        and not current.tmdb_id
        and not current.imdb_id
    ) or str(current.tmdb_id or "") == str(metadata["id"]):
        return apply_tmdb(current, metadata)
    model = model_for(kind)
    target = model.objects.filter(tmdb_id=metadata["id"]).first()
    if target is None:
        target = model.objects.create(
            name=(metadata.get("original_title") or current.name)[:255],
            tmdb_id=metadata["id"],
        )
    return _relocate_source(kind, relation, target, metadata=metadata)


def _relocate_source(kind, relation, target, *, metadata=None):
    current = getattr(relation, kind)
    if kind == "series":
        for episode_relation in M3UEpisodeRelation.objects.filter(
            series_relation=relation
        ).select_related("episode"):
            old = episode_relation.episode
            episode = None
            if old.season_number is not None and old.episode_number is not None:
                episode = Episode.objects.filter(
                    series=target,
                    season_number=old.season_number,
                    episode_number=old.episode_number,
                ).first()
            shared = old.m3u_relations.exclude(pk=episode_relation.pk).exists()
            if episode:
                for field in ("tmdb_id", "imdb_id"):
                    if (
                        getattr(old, field)
                        and getattr(episode, field)
                        and getattr(old, field) != getattr(episode, field)
                    ):
                        raise ValueError(
                            "Conflicting episode identifiers; source matching was cancelled."
                        )
            if episode is None and not shared:
                old.series = target
                old.save(update_fields=["series"])
                continue
            if episode is None:
                episode = Episode.objects.create(
                    series=target,
                    **{
                        field: getattr(old, field)
                        for field in (
                            "name",
                            "description",
                            "air_date",
                            "rating",
                            "duration_secs",
                            "season_number",
                            "episode_number",
                            "tmdb_id",
                            "imdb_id",
                            "custom_properties",
                        )
                    },
                )
            episode_relation.episode = episode
            episode_relation.save(update_fields=["episode"])
            if not shared:
                remember_alias(old, episode, "episode")
                old.delete()
    setattr(relation, kind, target)
    relation.save(update_fields=[kind])
    if metadata is not None:
        target = apply_tmdb(target, metadata)
    if not current.m3u_relations.exists() and (
        kind != "series" or not current.episodes.exists()
    ):
        remember_alias(current, target, kind)
        current.delete()
    return target


@transaction.atomic
def move_source_to_content(
    kind,
    pk,
    *,
    target_id=None,
    create_from_provider=False,
    title_name=None,
    title_year=None,
):
    from .provider_metadata import normalize, reconcile_provider_metadata, source_value

    relation = (
        model_for(kind, source=True)
        .objects.select_for_update()
        .select_related(kind)
        .get(pk=pk)
    )
    old_id = getattr(relation, f"{kind}_id")
    model = model_for(kind)
    if create_from_provider:
        name = (
            title_name or source_title(relation, getattr(relation, kind)).strip()[:255]
        )
        year = (
            title_year
            if title_name is not None
            else normalize(
                "year",
                source_value(relation, ("year", "release_date", "first_air_date")),
            )
        )
        if not name:
            raise ValueError("The provider source has no usable title.")
        target, created = model.objects.get_or_create(
            name=name, year=year, tmdb_id=None, imdb_id=None
        )
        if title_name is not None and created:
            update_content(
                {
                    "content_type": kind,
                    "id": target.pk,
                    "display_name": name,
                    "clean_title": name,
                    "year": year,
                }
            )
    else:
        from django.shortcuts import get_object_or_404

        target = get_object_or_404(model.objects.select_for_update(), pk=target_id)
    relation.tmdb_override_id = str(target.tmdb_match_id or target.tmdb_id or "")
    relation.custom_properties = {
        **(relation.custom_properties or {}),
        "_library_manual_assignment": True,
    }
    relation.save(update_fields=["tmdb_override_id", "custom_properties"])
    if old_id != target.pk:
        target = _relocate_source(kind, relation, target)
    reconcile_provider_metadata(kind, [old_id, target.pk])
    target.refresh_from_db()
    return target


def canonical_targets(data):
    settings = library_settings()
    query = (
        Q(tmdb_id=data["tmdb_id"]) | Q(tmdb_match_id=data["tmdb_id"])
        if data.get("tmdb_id")
        else canonical_title_search("", settings["languages"], data["query"])
    )
    rows = model_for(data["content_type"]).objects.filter(
        query, m3u_relations__m3u_account__is_active=True
    )
    if data.get("year") and not data.get("tmdb_id"):
        year = data["year"]
        rows = rows.filter(
            Q(tmdb_metadata__year=year)
            | (
                ~Q(tmdb_metadata__has_key="year")
                & (
                    Q(tmdb_metadata__release_date__startswith=f"{year}-")
                    | (~Q(tmdb_metadata__has_key="release_date") & Q(year=year))
                )
            )
        )
    rows = rows.annotate(
        source_count=Count("m3u_relations", distinct=True),
        presentation_title=canonical_title_expression("", settings["languages"]),
    ).order_by(Lower("presentation_title"), "pk")[:20]
    return [
        {
            "id": row.pk,
            "name": doc["name"],
            "year": doc["year"],
            "tmdb_id": str(doc["tmdb_id"]),
            "source_count": row.source_count,
        }
        for row in rows
        for doc in [canonical_document(row, settings)]
    ]


def browse_document(content, request=None, settings=None):
    """Overlay library presentation without rewriting provider-owned fields."""
    from .image_proxy import rewrite_single_image_url

    if not (content.display_name or content.clean_title or content.tmdb_metadata):
        return {}
    settings = settings or library_settings()
    document = canonical_document(content, settings)
    fields = {
        name: document[name]
        for name in (
            "name",
            "description",
            "year",
            "genre",
            "rating",
            "duration_secs",
            "imdb_id",
        )
    }
    if settings["prefer_artwork"] and content.tmdb_poster_url:
        kind = "movie" if isinstance(content, Movie) else "series"
        url = rewrite_single_image_url(
            request, kind, content.pk, "tmdb_poster", content.tmdb_poster_url
        )
        fields["logo"] = {
            "id": None,
            "name": document["name"],
            "url": url,
            "cache_url": url,
            "movie_count": 0,
            "series_count": 0,
            "is_used": True,
        }
    return fields


def overlay_provider_document(data, content, request):
    settings = library_settings()
    fields = browse_document(content, request, settings)
    logo = fields.pop("logo", None)
    data.update(fields)
    if "description" in fields:
        data["plot"] = fields["description"]
    if logo:
        for field in ("cover", "cover_big", "movie_image", "series_image"):
            if field in data:
                data[field] = (
                    logo
                    if field == "cover" and isinstance(content, Series)
                    else logo["cache_url"]
                )
    if settings["prefer_artwork"] and content.tmdb_backdrop_url:
        from .image_proxy import rewrite_single_image_url

        kind = "movie" if isinstance(content, Movie) else "series"
        data["backdrop_path"] = [
            rewrite_single_image_url(
                request, kind, content.pk, "tmdb_backdrop", content.tmdb_backdrop_url
            )
        ]
    metadata = content.tmdb_metadata or {}
    for source, target in (
        ("release_date", "release_date"),
        ("youtube_trailer", "youtube_trailer"),
        ("director", "director"),
        ("actors", "actors"),
        ("country", "country"),
        ("age_rating", "age"),
    ):
        if source in metadata:
            data[target] = metadata[source] or ""
    return data


def tmdb_client():
    return Client(library_settings(private=True)["api_token"])


def state_payload(state=None):
    state = state or VODMetadataState.objects.filter(pk=1).first()
    if state is None:
        return {"status": "idle", "progress": {}, "error": "", "task_id": ""}
    return {
        "pending_enrichment_count": len(state.pending_enrichment),
        **{
            key: getattr(state, key)
            for key in (
                "status",
                "progress",
                "error",
                "task_id",
                "started_at",
                "completed_at",
                "updated_at",
            )
        },
    }


@transaction.atomic
def queue_library_job(
    operation, refs, *, automatic=False, include_protected=False, job_settings=None
):
    if operation not in {"cleanup", "enrich"}:
        raise ValueError("Unsupported library operation.")
    if automatic and include_protected:
        raise ValueError("Automatic jobs cannot override metadata protection.")
    if operation == "enrich" and not library_settings()["token_configured"]:
        raise ValueError("Configure a TMDB token before starting enrichment.")
    defaults = library_settings()
    option_keys = (
        "languages",
        "title_rules",
        "removal_rules",
        "year_rules",
        "match_missing",
    )
    options = {
        key: copy.deepcopy((job_settings or {}).get(key, defaults[key]))
        for key in option_keys
    }
    options.update(normalized_cleanup_rules(options))
    state, _ = VODMetadataState.objects.get_or_create(pk=1)
    state = VODMetadataState.objects.select_for_update().get(pk=1)
    refs = [list(ref) for ref in refs]
    if state.status in {"queued", "running"}:
        if (
            automatic
            and state.progress.get("operation") == operation
            and not state.progress.get("include_protected")
            and state.progress.get("settings", options) == options
        ):
            state.selection = [
                list(ref)
                for ref in dict.fromkeys(
                    tuple(ref) for ref in [*state.selection, *refs]
                )
            ]
            state.progress = {**state.progress, "total": len(state.selection)}
            state.save(update_fields=["selection", "progress", "updated_at"])
            return state_payload(state)
        raise ValueError("A library job is already queued or running.")
    state.task_id = uuid.uuid4().hex
    state.status = "queued"
    state.selection = refs
    state.progress = {
        "operation": operation,
        "include_protected": include_protected,
        "settings": options,
        "total": len(refs),
        "processed": 0,
        "matched": 0,
        "not_found": 0,
        "ambiguous": 0,
        "failed": 0,
        "skipped": 0,
    }
    state.error = ""
    state.started_at = None
    state.job_heartbeat = timezone.now()
    state.completed_at = None
    state.save()
    task_id = state.task_id

    def publish():
        from .tasks import enrich_vod_library

        try:
            enrich_vod_library.apply_async(args=[task_id], task_id=task_id)
        except Exception:
            VODMetadataState.objects.filter(pk=1, task_id=task_id).update(
                status="failed",
                error="Could not queue the library job.",
                completed_at=timezone.now(),
            )

    transaction.on_commit(publish)
    return state_payload(state)


def run_library_job(task_id):
    settings = library_settings()
    client = None
    while True:
        with transaction.atomic():
            state = VODMetadataState.objects.select_for_update().get(pk=1)
            if state.task_id != task_id or state.status not in {"queued", "running"}:
                return
            index = state.progress["processed"]
            if index >= len(state.selection):
                state.status = "complete"
                state.completed_at = timezone.now()
                state.save()
                if state.pending_enrichment:
                    from .library_jobs import publish_pending_enrichment

                    transaction.on_commit(publish_pending_enrichment)
                return
            state.status = "running"
            state.job_heartbeat = timezone.now()
            state.started_at = state.started_at or timezone.now()
            kind, pk = state.selection[index]
            operation = state.progress["operation"]
            include_protected = state.progress.get("include_protected", False)
            settings = {**settings, **state.progress.get("settings", {})}
            state.save()
        outcome, document, skip_reason = "skipped", None, ""
        content = model_for(kind).objects.filter(pk=pk).first()
        if content and (not content.tmdb_lookup_excluded or include_protected):
            try:
                from .provider_metadata import reconcile_provider_metadata

                reconcile_provider_metadata(kind, [pk])
                content.refresh_from_db()
                relation = (
                    content.m3u_relations.select_related(kind, "m3u_account")
                    .order_by("-m3u_account__priority", "m3u_account_id", "pk")
                    .first()
                )
                title, year = (
                    cleanup_for_source(relation, settings)
                    if relation
                    else (content.name, content.year)
                )
                if operation == "cleanup":
                    document = {"clean_title": title[:255], "year": year}
                    outcome = "matched"
                else:
                    identity = canonical_document(content, settings)
                    match_id, outcome = str(identity["tmdb_id"] or ""), "matched"
                    searched = False
                    if not match_id and identity["imdb_id"]:
                        client = client or tmdb_client()
                        match_id = client.find_by_imdb(identity["imdb_id"], kind)
                        searched = True
                    if not match_id and settings["match_missing"] and year:
                        client = client or tmdb_client()
                        match_id, outcome, _ = client.search_outcome(
                            title, year, kind, settings["languages"]
                        )
                        searched = True
                    if match_id:
                        client = client or tmdb_client()
                        document = client.details(
                            match_id,
                            kind,
                            settings["languages"],
                            match_method="automatic",
                        )
                    elif searched:
                        outcome = (
                            outcome
                            if outcome in {"ambiguous", "not_found"}
                            else "not_found"
                        )
                    else:
                        outcome = "skipped"
                        skip_reason = (
                            "year_missing"
                            if settings["match_missing"]
                            else "search_disabled"
                        )
            except TMDBAuthenticationError:
                VODMetadataState.objects.filter(
                    pk=1, task_id=task_id, status__in=["queued", "running"]
                ).update(
                    status="failed",
                    error="TMDB rejected the token. Update Settings > Metadata, then resume.",
                    completed_at=timezone.now(),
                )
                return
            except TMDBNotFound:
                outcome = "not_found"
            except (TMDBError, ValueError):
                outcome = "failed"
        with transaction.atomic():
            state = VODMetadataState.objects.select_for_update().get(pk=1)
            if (
                state.task_id != task_id
                or state.status not in {"queued", "running"}
                or state.progress["processed"] != index
            ):
                return
            content = model_for(kind).objects.select_for_update().filter(pk=pk).first()
            if content and (not content.tmdb_lookup_excluded or include_protected):
                try:
                    if operation == "cleanup" and document:
                        content.clean_title = document["clean_title"]
                        content.tmdb_metadata = {
                            **(content.tmdb_metadata or {}),
                            "_cleanup_year": document["year"],
                        }
                        content.tmdb_lookup_excluded = True
                        content.save(
                            update_fields=[
                                "clean_title",
                                "tmdb_metadata",
                                "tmdb_lookup_excluded",
                            ]
                        )
                    elif document:
                        apply_tmdb(content, document)
                    else:
                        content.tmdb_status = "not_checked" if skip_reason else outcome
                        metadata = dict(content.tmdb_metadata or {})
                        metadata.pop("_lookup_skip_reason", None)
                        if skip_reason:
                            metadata["_lookup_skip_reason"] = skip_reason
                        # A provider refresh retries the lookup once this changes.
                        metadata["_lookup_key"] = [content.clean_title, content.year]
                        content.tmdb_metadata = metadata
                        content.save(update_fields=["tmdb_status", "tmdb_metadata"])
                except ValueError:
                    outcome = "failed"
                    content.tmdb_status = "failed"
                    content.save(update_fields=["tmdb_status"])
            else:
                outcome = "skipped"
            state.progress = {
                **state.progress,
                "processed": index + 1,
                outcome: state.progress.get(outcome, 0) + 1,
            }
            state.job_heartbeat = timezone.now()
            state.save(update_fields=["progress", "job_heartbeat", "updated_at"])
