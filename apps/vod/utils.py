"""Shared helpers for the VOD app."""
import re

_VOD_MOVIES_ENABLED = "vod_movies_enabled"
_VOD_SERIES_ENABLED = "vod_series_enabled"

QUALITY_ORDER = ("4K", "1080p", "720p", "480p", "SD")

_LANGUAGE_CODE_RE = re.compile(r"[A-Za-z]{2}")
_LANG_SUFFIX_RE = re.compile(r"\[([A-Za-z]{2})\]\s*$")


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
    """Return a copy of ``props`` with ``language`` lowercased.

    Raises ``ValueError`` with a message safe to return to the API caller.
    """
    if props is None:
        props = {}
    elif not isinstance(props, dict):
        raise ValueError("custom_properties must be an object.")
    props = dict(props)

    language = props.get("language")
    if language is not None:
        if not isinstance(language, str) or not _LANGUAGE_CODE_RE.fullmatch(language):
            raise ValueError("language must be a 2-letter ISO 639-1 code or null.")
        props["language"] = language.lower()

    quality = props.get("quality")
    if quality is not None and quality not in QUALITY_ORDER:
        raise ValueError(f"quality must be one of {', '.join(QUALITY_ORDER)} or null.")

    return props


def category_language(category_relation):
    """Identity language for content ingested under this category relation (``''`` when untagged)."""
    if category_relation is None:
        return ''
    props = category_relation.custom_properties or {}
    language = props.get("language")
    return language.lower() if isinstance(language, str) else ''


def xc_language_suffix(name, language):
    """Append ``[XX]`` for XC display. Empty language and an existing matching tag are unchanged."""
    if not language or not name:
        return name
    tag = language.upper()
    match = _LANG_SUFFIX_RE.search(name)
    if match and match.group(1).upper() == tag:
        return name
    return f"{name} [{tag}]"


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
