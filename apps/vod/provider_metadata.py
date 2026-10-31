"""Project concrete provider payloads onto an unlocked canonical Library title."""

import re
from collections import defaultdict

from django.db import transaction
from django.utils import timezone

from .canonical_import import import_title
from .models import (
    M3UMovieRelation,
    M3USeriesRelation,
    M3UVODCategoryRelation,
    Movie,
    Series,
    VODLogo,
)
from .title_cleanup import extract_year_from_title, remove_title_text

PROVENANCE_KEY = "_provider_metadata_sources"
SCALAR_FIELDS = {
    "description": ("plot", "description", "overview"),
    "rating": ("rating", "vote_average"),
    "genre": ("genre",),
    "year": ("year", "release_date", "releasedate", "releaseDate", "first_air_date"),
}
CUSTOM_FIELDS = {
    "release_date": ("release_date", "releasedate", "releaseDate", "first_air_date"),
    "youtube_trailer": ("youtube_trailer", "trailer"),
    "director": ("director",),
    "actors": ("actors", "cast"),
    "crew": ("crew",),
    "country": ("country", "production_country", "origin_country"),
    "age": ("age", "age_rating", "rating_mpaa"),
    "backdrop_path": ("backdrop_path",),
}


def meaningful(value):
    return value not in (None, "", [], {})


def source_priority_key(relation):
    return (
        -int(relation.m3u_account.priority or 0),
        relation.m3u_account_id,
        -int(bool((relation.custom_properties or {}).get("detailed_info"))),
        relation.pk,
    )


def source_value(relation, aliases):
    properties = relation.custom_properties or {}
    for payload in [
        properties.get(key)
        for key in ("detailed_info", "movie_data", "series_data", "basic_data")
    ] + [properties]:
        if not isinstance(payload, dict):
            continue
        for alias in aliases:
            value = payload.get(alias)
            if meaningful(value):
                return value
    return None


def normalize(field, value):
    if isinstance(value, (list, tuple)):
        value = ", ".join(
            str(row.get("name") if isinstance(row, dict) else row).strip()
            for row in value
            if row
        )
    if isinstance(value, dict):
        return None
    text = str(value if value is not None else "").strip()
    if field == "year":
        match = re.match(r"(18\d{2}|19\d{2}|20\d{2}|21\d{2})", text)
        year = int(match[0]) if match else None
        return year if year and year <= timezone.now().year + 5 else None
    if field == "rating":
        try:
            rating = float(text.replace(",", "."))
        except ValueError:
            return None
        return str(rating) if 0 <= rating <= 10 else None
    if field in {"genre", "clean_title"}:
        return text[:255]
    return text


def source_year(relation, year_rules, *, title=None, removal_rules=None):
    """Resolve this source's release year independently of a stale canonical year."""
    explicit = normalize("year", source_value(relation, SCALAR_FIELDS["year"]))
    return explicit or extract_year_from_title(
        remove_title_text(
            title if title is not None else source_value(relation, ("name", "title")),
            removal_rules,
        ),
        year_rules,
    )


def project_provider_metadata(relations, *, settings, category_rules):
    from .tasks import extract_duration_from_data

    ordered = sorted(relations, key=source_priority_key)
    values, sources = {}, {}
    for field, aliases in {
        **SCALAR_FIELDS,
        **CUSTOM_FIELDS,
        "title": ("name", "title"),
        "logo": ("stream_icon", "cover", "movie_image"),
    }.items():
        for relation in ordered:
            value = (
                source_year(
                    relation,
                    settings["year_rules"],
                    removal_rules=settings.get("removal_rules"),
                )
                if field == "year"
                else normalize(field, source_value(relation, aliases))
            )
            if meaningful(value):
                values[field] = value
                sources[field] = {
                    "account_id": relation.m3u_account_id,
                    "relation_id": relation.pk,
                }
                break
    for relation in ordered:
        seconds = extract_duration_from_data(
            {
                "duration_secs": source_value(relation, ("duration_secs",)),
                "duration": source_value(relation, ("duration",)),
            }
        )
        if seconds is not None:
            values["duration_secs"] = seconds
            sources["duration_secs"] = {
                "account_id": relation.m3u_account_id,
                "relation_id": relation.pk,
            }
            break
    title_source = next(
        (
            row
            for row in ordered
            if row.pk == (sources.get("title") or {}).get("relation_id")
        ),
        None,
    )
    if title_source:
        values["clean_title"] = import_title(
            values["title"],
            values.get("year"),
            settings,
            category_rules.get((title_source.m3u_account_id, title_source.category_id)),
        )
        sources["clean_title"] = sources.pop("title")
    values.pop("title", None)
    return values, sources


# Unsuccessful lookups are retried once the cleaned title or year changes.
RETRY_LOOKUP_STATUSES = {"not_found", "ambiguous", "not_checked"}


@transaction.atomic
def reconcile_provider_metadata(kind, ids):
    """Recompute from all active sources; locked canonical values are immutable."""
    from .library import library_settings

    model, relation_model = (
        (Movie, M3UMovieRelation) if kind == "movie" else (Series, M3USeriesRelation)
    )
    ids = sorted(set(ids))
    changed = 0
    settings = library_settings()
    for offset in range(0, len(ids), 500):
        content = list(
            model.objects.select_for_update()
            .filter(pk__in=ids[offset : offset + 500], tmdb_lookup_excluded=False)
            .order_by("pk")
        )
        relations = list(
            relation_model.objects.filter(
                **{f"{kind}_id__in": [row.pk for row in content]},
                m3u_account__is_active=True,
            ).select_related("m3u_account", "category")
        )
        rules = {
            (row.m3u_account_id, row.category_id): row
            for row in M3UVODCategoryRelation.objects.filter(
                m3u_account_id__in={row.m3u_account_id for row in relations},
                category_id__in={row.category_id for row in relations},
            )
        }
        grouped = defaultdict(list)
        for relation in relations:
            grouped[getattr(relation, f"{kind}_id")].append(relation)
        projections = {
            item.pk: project_provider_metadata(
                grouped[item.pk], settings=settings, category_rules=rules
            )
            for item in content
        }
        logo_names = {}
        for item in content:
            url = projections[item.pk][0].get("logo") or ""
            if url and len(url) <= 500 and url.startswith(("http://", "https://")):
                logo_names.setdefault(url, item.name[:255])
        logos = {row.url: row for row in VODLogo.objects.filter(url__in=logo_names)}
        missing = [
            VODLogo(url=url, name=name)
            for url, name in logo_names.items()
            if url not in logos
        ]
        if missing:
            VODLogo.objects.bulk_create(missing, ignore_conflicts=True)
            logos = {row.url: row for row in VODLogo.objects.filter(url__in=logo_names)}
        updates, update_fields = [], set()
        for item in content:
            values, sources = projections[item.pk]
            fields = []
            previous = item.custom_properties or {}
            previous_sources = previous.get(PROVENANCE_KEY) or {}
            for field in [
                *SCALAR_FIELDS,
                "clean_title",
                *(["duration_secs"] if kind == "movie" else []),
            ]:
                if field in values:
                    value = values[field]
                elif field in previous_sources:
                    if field == "duration_secs" and any(
                        row.pk == previous_sources[field].get("relation_id")
                        for row in grouped[item.pk]
                    ):
                        sources[field] = previous_sources[field]
                        continue
                    value = (
                        "" if field in {"description", "genre", "clean_title"} else None
                    )
                else:
                    continue
                if getattr(item, field) != value:
                    setattr(item, field, value)
                    fields.append(field)
            properties = dict(previous)
            for field in CUSTOM_FIELDS:
                if field in values:
                    properties[field] = (
                        [values[field]] if field == "backdrop_path" else values[field]
                    )
                elif field in previous_sources:
                    properties.pop(field, None)
            properties[PROVENANCE_KEY] = sources
            if properties != previous:
                item.custom_properties = properties
                fields.append("custom_properties")
            logo_url = values.get("logo") or ""
            if logo_url in logos:
                logo = logos[logo_url]
                if item.logo_id != logo.pk:
                    item.logo = logo
                    fields.append("logo")
            key = (item.tmdb_metadata or {}).get("_lookup_key")
            if (
                item.tmdb_status in RETRY_LOOKUP_STATUSES
                and key is not None
                and key != [item.clean_title, item.year]
            ):
                item.tmdb_status = ""
                fields.append("tmdb_status")
            if fields:
                item.updated_at = timezone.now()
                updates.append(item)
                update_fields.update([*fields, "updated_at"])
        if updates:
            model.objects.bulk_update(updates, sorted(update_fields), batch_size=500)
            changed += len(updates)
    return changed
