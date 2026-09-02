"""Shared helpers for the VOD app."""

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
    """Split a ``name|type`` category filter value into ``(name, type)``.

    The trailing token is only treated as a category type when it is one of ``valid_types``.
    Otherwise the whole value is the category name, so a category whose name itself contains
    ``|`` (for example ``"|EN| 4K Movies"``) is not mis-split into a bogus name and type (#1603).

    Returns a ``(name, type_or_None)`` tuple.
    """
    if "|" in value:
        name, _, suffix = value.rpartition("|")
        if suffix in valid_types:
            return name, suffix
    return value, None
