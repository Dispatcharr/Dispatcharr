"""Deterministic provider metadata projected onto canonical VOD titles.

Provider payloads stay on their concrete relations.  The shared Movie/Series
row receives a field-by-field projection so its metadata does not depend on
which account happened to refresh last.  A preferred-language category wins,
then the configured M3U account priority; lower-ranked sources only fill fields
that higher-ranked sources do not provide.
"""

from __future__ import annotations

from collections import defaultdict
import re

from django.utils import timezone

from core.models import CoreSettings

from .models import Movie, M3UMovieRelation, M3USeriesRelation, Series


PROVENANCE_KEY = "_provider_metadata_sources"
MANUAL_METADATA_KEY = "_manual_metadata"

LANGUAGE_CATEGORY_ALIASES = {
    "de": {"de", "ger", "german", "deutsch"},
    "en": {"en", "eng", "english"},
    "fr": {"fr", "fre", "fra", "french", "francais"},
    "es": {"es", "spa", "spanish", "espanol"},
    "it": {"it", "ita", "italian"},
    "nl": {"nl", "dut", "nld", "dutch"},
}

SCALAR_FIELDS = {
    "display_name": ("name", "title"),
    "description": ("plot", "description"),
    "rating": ("rating", "vote_average"),
    "genre": ("genre",),
    "year": (
        "year",
        "release_date",
        "releasedate",
        "releaseDate",
        "first_air_date",
    ),
}

MOVIE_SCALAR_FIELDS = {
    **SCALAR_FIELDS,
    "duration_secs": ("duration_secs", "duration"),
}

CUSTOM_FIELDS = {
    "release_date": (
        "release_date",
        "releasedate",
        "releaseDate",
        "first_air_date",
    ),
    "youtube_trailer": ("youtube_trailer", "trailer"),
    "director": ("director",),
    "actors": ("actors", "cast"),
    "crew": ("crew",),
    "country": ("country", "production_country", "origin_country"),
    "age": ("age", "age_rating", "rating_mpaa"),
    "backdrop_path": ("backdrop_path",),
    "poster_path": ("poster_path",),
    "movie_image": ("movie_image", "cover_big", "stream_icon", "cover"),
}


def _meaningful(value):
    if value in (None, "", [], {}):
        return False
    if isinstance(value, (list, tuple, set)):
        return any(_meaningful(item) for item in value)
    return True


def _relation_payloads(relation):
    properties = relation.custom_properties or {}
    payloads = []
    for key in ("detailed_info", "movie_data", "series_data", "basic_data"):
        value = properties.get(key)
        if isinstance(value, dict):
            payloads.append(value)
    payloads.append(properties)
    return payloads


def _relation_value(relation, aliases):
    for payload in _relation_payloads(relation):
        for alias in aliases:
            value = payload.get(alias)
            if _meaningful(value):
                return value
    return None


def _preferred_language_aliases():
    language = (CoreSettings.get_tmdb_languages()[0] or "en").split("-", 1)[0]
    return LANGUAGE_CATEGORY_ALIASES.get(language, {language})


def _category_language_rank(relation, aliases):
    category_name = str(getattr(getattr(relation, "category", None), "name", ""))
    tokens = re.findall(r"[a-z]+", category_name.lower())
    return 1 if tokens and tokens[0] in aliases else 0


def relation_priority_key(relation, preferred_aliases=None):
    """Sort highest-quality provider relations first with stable tie-breaks."""
    preferred_aliases = preferred_aliases or _preferred_language_aliases()
    account = getattr(relation, "m3u_account", None)
    properties = relation.custom_properties or {}
    return (
        -_category_language_rank(relation, preferred_aliases),
        -int(getattr(account, "priority", 0) or 0),
        -int(bool(properties.get("detailed_info"))),
        int(getattr(relation, "id", 0) or 0),
    )


def _normalize_text(value):
    if isinstance(value, (list, tuple, set)):
        parts = []
        for item in value:
            raw = item.get("name") if isinstance(item, dict) else item
            text = str(raw or "").strip()
            if text:
                parts.append(text)
        return ", ".join(parts)
    if isinstance(value, dict):
        return ""
    return str(value or "").strip()


def _normalize_year(value):
    match = re.search(r"(?:19|20)\d{2}", str(value or ""))
    return int(match.group(0)) if match else None


def _normalize_duration(value, *, assume_minutes=False):
    if isinstance(value, (int, float)) and value > 0:
        return int(value * 60) if assume_minutes else int(value)
    raw = str(value or "").strip()
    if not raw:
        return None
    if raw.isdigit():
        return int(raw) * 60 if assume_minutes else int(raw)
    parts = raw.split(":")
    try:
        if len(parts) == 3:
            hours, minutes, seconds = map(int, parts)
            return hours * 3600 + minutes * 60 + seconds
        if len(parts) == 2:
            minutes, seconds = map(int, parts)
            return minutes * 60 + seconds
    except ValueError:
        return None
    return None


def _normalize_field(field, value):
    if field == "year":
        return _normalize_year(value)
    if field == "duration_secs":
        return _normalize_duration(value)
    if field == "rating":
        try:
            return str(float(str(value).replace(",", ".")))
        except (TypeError, ValueError):
            return None
    if field == "backdrop_path":
        if isinstance(value, (list, tuple)):
            return [item for item in value if _meaningful(item)]
        text = _normalize_text(value)
        return [text] if text else []
    return _normalize_text(value)


def _source_descriptor(relation):
    account = getattr(relation, "m3u_account", None)
    category = getattr(relation, "category", None)
    return {
        "relation_id": int(getattr(relation, "id", 0) or 0),
        "account_id": int(getattr(relation, "m3u_account_id", 0) or 0),
        "account": str(getattr(account, "name", "") or ""),
        "category_id": int(getattr(relation, "category_id", 0) or 0),
        "category": str(getattr(category, "name", "") or ""),
    }


def project_provider_metadata(
    relations, *, content_type, preferred_aliases=None
):
    """Return scalar/custom projections plus field-level source provenance."""
    preferred_aliases = preferred_aliases or _preferred_language_aliases()
    ordered = sorted(
        relations,
        key=lambda relation: relation_priority_key(
            relation, preferred_aliases=preferred_aliases
        ),
    )
    scalar_definitions = (
        MOVIE_SCALAR_FIELDS if content_type == "movie" else SCALAR_FIELDS
    )
    scalar = {}
    custom = {}
    sources = {}
    for target, aliases in scalar_definitions.items():
        for relation in ordered:
            if target == "duration_secs":
                raw_value = _relation_value(relation, ("duration_secs",))
                value = _normalize_duration(raw_value)
                if not _meaningful(value):
                    raw_value = _relation_value(relation, ("duration",))
                    value = _normalize_duration(raw_value, assume_minutes=True)
            else:
                value = _normalize_field(
                    target, _relation_value(relation, aliases)
                )
            if _meaningful(value):
                scalar[target] = value
                sources[target] = _source_descriptor(relation)
                break
    for target, aliases in CUSTOM_FIELDS.items():
        for relation in ordered:
            value = _normalize_field(target, _relation_value(relation, aliases))
            if _meaningful(value):
                custom[target] = value
                sources[target] = _source_descriptor(relation)
                break
    return {"scalar": scalar, "custom": custom, "sources": sources}


def _apply_projection(content, projection, *, content_type):
    changed_fields = []
    previous_properties = content.custom_properties or {}
    previous_sources = previous_properties.get(PROVENANCE_KEY) or {}
    manual = previous_properties.get(MANUAL_METADATA_KEY) or {}

    scalar_definitions = (
        MOVIE_SCALAR_FIELDS if content_type == "movie" else SCALAR_FIELDS
    )
    for field in scalar_definitions:
        if field in manual:
            value = manual[field]
        elif field == "display_name" and content.tmdb_status == "matched":
            # A completed TMDB title is the canonical layer. Provider refreshes
            # may continue filling other missing fields underneath it.
            continue
        elif field in projection["scalar"]:
            value = projection["scalar"][field]
        elif field in previous_sources:
            value = None if field != "description" and field != "genre" else ""
        else:
            continue
        if getattr(content, field) != value:
            setattr(content, field, value)
            changed_fields.append(field)

    properties = {
        key: value
        for key, value in previous_properties.items()
        if key != PROVENANCE_KEY
    }
    for field in CUSTOM_FIELDS:
        if field in manual:
            properties[field] = manual[field]
        elif field in projection["custom"]:
            properties[field] = projection["custom"][field]
        elif field in previous_sources:
            properties.pop(field, None)
    if projection["sources"]:
        properties[PROVENANCE_KEY] = projection["sources"]
    if properties != previous_properties:
        content.custom_properties = properties or None
        changed_fields.append("custom_properties")

    if changed_fields:
        content.updated_at = timezone.now()
        changed_fields.append("updated_at")
    return changed_fields


def _chunks(values, size=1000):
    values = list(dict.fromkeys(int(value) for value in values if value))
    for index in range(0, len(values), size):
        yield values[index : index + size]


def _reconcile(model, relation_model, relation_field, ids, content_type):
    changed = 0
    preferred_aliases = _preferred_language_aliases()
    for batch in _chunks(ids):
        content_by_id = model.objects.defer("tmdb_metadata").in_bulk(batch)
        relations_by_id = defaultdict(list)
        relations = (
            relation_model.objects.filter(
                **{
                    f"{relation_field}_id__in": batch,
                    "m3u_account__is_active": True,
                }
            )
            .select_related("m3u_account", "category")
            .order_by(f"{relation_field}_id", "id")
        )
        for relation in relations.iterator(chunk_size=1000):
            relations_by_id[getattr(relation, f"{relation_field}_id")].append(
                relation
            )
        updates = []
        all_update_fields = set()
        for content_id, content in content_by_id.items():
            projection = project_provider_metadata(
                relations_by_id[content_id],
                content_type=content_type,
                preferred_aliases=preferred_aliases,
            )
            changed_fields = _apply_projection(
                content, projection, content_type=content_type
            )
            if changed_fields:
                updates.append(content)
                all_update_fields.update(changed_fields)
        if updates:
            model.objects.bulk_update(
                updates, sorted(all_update_fields), batch_size=1000
            )
            changed += len(updates)
    return changed


def reconcile_movie_provider_metadata(movie_ids):
    return _reconcile(
        Movie, M3UMovieRelation, "movie", movie_ids, content_type="movie"
    )


def reconcile_series_provider_metadata(series_ids):
    return _reconcile(
        Series, M3USeriesRelation, "series", series_ids, content_type="series"
    )
