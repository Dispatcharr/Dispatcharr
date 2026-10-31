"""Shared helpers for the VOD app."""
_VOD_MOVIES_ENABLED = "vod_movies_enabled"
_VOD_SERIES_ENABLED = "vod_series_enabled"

QUALITY_ORDER = ("4K", "1080p", "720p", "480p", "SD")


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


def validate_category_custom_properties(props):
    """Validate legacy and source-owned category metadata fields.

    Raises ``ValueError`` with a message safe to return to the API caller.
    """
    if props is None:
        props = {}
    elif not isinstance(props, dict):
        raise ValueError("custom_properties must be an object.")
    props = dict(props)

    from .metadata import METADATA_FIELDS, normalize_language_code, validate_source_metadata

    language = props.get("language")
    if language is not None:
        props["language"] = normalize_language_code(language)

    quality = props.get("quality")
    if quality is not None and quality not in QUALITY_ORDER:
        raise ValueError(f"quality must be one of {', '.join(QUALITY_ORDER)} or null.")

    props.update(validate_source_metadata(
        {key: props[key] for key in METADATA_FIELDS if key in props}, allow_reset=True
    ))
    if "title_cleanup" in props:
        from .title_cleanup import normalize_group_title_cleanup
        props["title_cleanup"] = normalize_group_title_cleanup(props["title_cleanup"])

    return props




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
