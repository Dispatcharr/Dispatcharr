"""Shared helpers for VOD naming, metadata, and per-user access."""

import re

from .metadata import normalize_language_list


def _first_text(*values):
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, (list, tuple)):
            for item in value:
                if isinstance(item, str) and item.strip():
                    return item.strip()
    return None


def canonical_output_name(name, *, display_name="", year=None):
    """Build a client title without making implicit provider-prefix guesses."""
    result = _first_text(display_name, name) or ""
    if year and not re.search(rf"\({re.escape(str(year))}\)\s*$", result):
        result = f"{result} ({year})"
    return result


def policy_output_name(
    content,
    relation,
    policy,
    *,
    edition=None,
    metadata=None,
    canonical_languages=None,
):
    """Render a profile title without mutating canonical or provider data."""
    edition = edition or {}
    metadata = metadata or {}
    provider = get_vod_source_name(relation, getattr(content, "name", "") or "")
    title_source = getattr(policy, "canonical_title_source", "primary")
    selected_canonical_title = ""
    if title_source == "provider":
        title = provider
        canonical = provider
    else:
        tmdb_metadata = getattr(content, "tmdb_metadata", None)
        if isinstance(tmdb_metadata, dict):
            localized = tmdb_metadata.get("localized") or {}
            try:
                from core.models import CoreSettings

                languages = (
                    list(canonical_languages)
                    if canonical_languages is not None
                    else CoreSettings.get_tmdb_languages()
                )
            except Exception:
                languages = []
            language_index = 1 if title_source == "secondary" else 0
            if len(languages) > language_index:
                language_values = localized.get(languages[language_index]) or {}
                selected_canonical_title = str(
                    language_values.get("title") or ""
                ).strip()
        if title_source == "primary":
            display_title = str(
                getattr(content, "display_name", "") or ""
            ).strip()
            clean_title = str(
                getattr(content, "clean_title", "") or ""
            ).strip()
            selected_canonical_title = (
                (display_title or selected_canonical_title)
                if getattr(content, "tmdb_status", "") in {"matched", "manual"}
                else selected_canonical_title
            ) or clean_title or provider

        if not selected_canonical_title:
            # A secondary TMDB localization is optional. The shared clean
            # title is the first fallback for every canonical title mode; only
            # then do we expose the concrete provider title.
            selected_canonical_title = str(
                getattr(content, "clean_title", "") or ""
            ).strip() or provider

        if selected_canonical_title:
            title = canonical_output_name(
                getattr(content, "name", "") or "",
                display_name=selected_canonical_title,
            )
            canonical = canonical_output_name(
                getattr(content, "name", "") or "",
                display_name=selected_canonical_title,
                year=getattr(content, "year", None),
            )
        else:
            title = provider
            canonical = provider
    suffix = str(edition.get("suffix") or "").strip()
    naming_mode = getattr(policy, "naming_mode", "mode_default")
    if naming_mode == "provider":
        return provider
    if naming_mode == "mode_default":
        if getattr(policy, "export_mode", "compact") == "variants":
            return provider
        return " ".join(part for part in (canonical, suffix) if part).strip()
    if naming_mode == "canonical":
        return " ".join(part for part in (canonical, suffix) if part).strip()

    raw_features = metadata.get("video_features") or metadata.get("features") or []
    features = [raw_features] if isinstance(raw_features, str) else raw_features
    values = {
        "canonical": canonical,
        "title": title,
        "year": str(getattr(content, "year", None) or ""),
        "edition": suffix,
        "edition_name": str(edition.get("name") or ""),
        "provider": str(getattr(relation.m3u_account, "name", "") or ""),
        "source": provider,
        "dub": "+".join(
            code.upper()
            for code in normalize_language_list(
                metadata.get("audio_languages") or metadata.get("languages")
            )
        ),
        "sub": "+".join(
            code.upper()
            for code in normalize_language_list(metadata.get("subtitle_languages"))
        ),
        "resolution": str(
            metadata.get("height")
            or metadata.get("resolution")
            or metadata.get("quality")
            or ""
        ),
        "format": str(
            metadata.get("container_extension")
            or getattr(relation, "container_extension", "")
            or ""
        ).lower(),
        "features": "+".join(
            str(feature).upper()
            for feature in features
            if str(feature).strip()
        ),
    }
    template = getattr(policy, "name_template", "") or (
        "{title} ({year}) {edition}"
        if getattr(policy, "export_mode", "compact") == "compact"
        else "{title}"
    )
    try:
        rendered = template.format_map(values)
    except (KeyError, ValueError):
        rendered = " ".join(part for part in (canonical, suffix) if part)
    # Optional values should not leave visibly empty wrappers in client names.
    rendered = re.sub(r"\(\s*\)|\[\s*\]", "", rendered)
    return re.sub(r"\s+", " ", rendered).strip() or provider or canonical


def _relation_metadata(relation_or_properties):
    if isinstance(relation_or_properties, dict):
        properties = relation_or_properties
    else:
        properties = getattr(
            relation_or_properties,
            "custom_properties",
            None,
        ) or {}

    if not isinstance(properties, dict):
        return {}, {}, {}

    detailed_info = properties.get("detailed_info") or {}
    basic_data = properties.get("basic_data") or {}
    movie_data = properties.get("movie_data") or {}
    return (
        detailed_info if isinstance(detailed_info, dict) else {},
        basic_data if isinstance(basic_data, dict) else {},
        movie_data if isinstance(movie_data, dict) else {},
    )


def get_vod_source_name(relation_or_properties, fallback_name):
    """Return the provider-list title retained on a concrete VOD relation."""
    detailed_info, basic_data, movie_data = _relation_metadata(
        relation_or_properties
    )
    return _first_text(
        basic_data.get("name"),
        movie_data.get("name"),
        detailed_info.get("name"),
        detailed_info.get("original_name"),
        detailed_info.get("o_name"),
        basic_data.get("original_name"),
        basic_data.get("o_name"),
        fallback_name,
    )


def get_vod_display_name(content, relation_or_properties=None):
    """Return a clean provider detail title without guessing/removing prefixes."""
    detailed_info, basic_data, movie_data = _relation_metadata(
        relation_or_properties
    )
    content_properties = getattr(content, "custom_properties", None) or {}
    if not isinstance(content_properties, dict):
        content_properties = {}

    return _first_text(
        detailed_info.get("name"),
        detailed_info.get("original_name"),
        detailed_info.get("o_name"),
        movie_data.get("original_name"),
        movie_data.get("o_name"),
        content_properties.get("original_name"),
        content_properties.get("o_name"),
        getattr(content, "name", None),
    )


def get_series_display_name(series, series_relation=None):
    """Prefer a provider's clean detailed title, then the canonical title."""
    detailed_info, basic_data, _movie_data = _relation_metadata(
        series_relation
    )
    series_properties = getattr(series, "custom_properties", None) or {}
    if not isinstance(series_properties, dict):
        series_properties = {}

    return _first_text(
        detailed_info.get("name"),
        detailed_info.get("original_name"),
        detailed_info.get("o_name"),
        basic_data.get("original_name"),
        basic_data.get("o_name"),
        series_properties.get("original_name"),
        series_properties.get("o_name"),
        series.name,
    )

_VOD_MOVIES_ENABLED = "vod_movies_enabled"
_VOD_SERIES_ENABLED = "vod_series_enabled"


def _is_vod_access_enabled(*, prop_key, user=None):
    """Read a VOD access flag from *user*'s custom_properties (default True)."""
    if user is None:
        return True

    props = getattr(user, "custom_properties", None) or {}
    return props.get(prop_key) is not False


def is_vod_movies_enabled(*, user=None):
    """Return whether movies are allowed for *user*.

    Reads ``custom_properties.vod_movies_enabled``, which defaults to True when
    absent so existing users keep their current access. No DB query: the flag
    lives on the already-loaded user row. An anonymous *user* (``None``) is not
    restricted here; callers that can identify a user are the ones that gate.
    """
    return _is_vod_access_enabled(prop_key=_VOD_MOVIES_ENABLED, user=user)


def is_vod_series_enabled(*, user=None):
    """Return whether series and episodes are allowed for *user*.

    Same semantics as :func:`is_vod_movies_enabled`, but for
    ``custom_properties.vod_series_enabled``.
    """
    return _is_vod_access_enabled(prop_key=_VOD_SERIES_ENABLED, user=user)


def parse_category_filter_value(value, valid_types):
    """Return ``(name, type_or_None)`` for a category filter value.

    Only the trailing ``|token`` is treated as a type, and only when that token is in
    ``valid_types``. Category names may themselves contain ``|``, so any other value is
    kept as the full name.
    """
    if "|" in value:
        name, _, suffix = value.rpartition("|")
        if suffix in valid_types:
            return name, suffix
    return value, None
