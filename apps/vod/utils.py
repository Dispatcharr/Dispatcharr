"""Shared helpers for the VOD app."""

VOD_KIND_MOVIE = "movie"
VOD_KIND_SERIES = "series"

# Which custom_properties flag guards each kind of VOD.
_ACCESS_PROPS = {
    VOD_KIND_MOVIE: "vod_movies_enabled",
    VOD_KIND_SERIES: "vod_series_enabled",
}


def is_vod_enabled(*, kind, user=None):
    """Return whether VOD of *kind* is allowed for *user*.

    *kind* is ``VOD_KIND_MOVIE`` or ``VOD_KIND_SERIES``. Reads the matching
    ``custom_properties`` JSON boolean, which defaults to True when absent so
    existing users keep their current access. No DB query — the flags live on
    the already-loaded user row. An anonymous *user* (``None``) is not
    restricted here; the callers that can identify a user are the ones that
    gate.
    """
    if kind not in _ACCESS_PROPS:
        raise ValueError(f"unknown VOD kind: {kind!r}")

    if user is None:
        return True

    props = getattr(user, "custom_properties", None) or {}
    return props.get(_ACCESS_PROPS[kind]) is not False


def vod_kind_for_content_type(content_type):
    """Map a VOD proxy ``content_type`` to its access-flag kind.

    Episodes are gated by the series flag. Returns None for anything the
    access flags do not cover, so callers leave unknown types alone.
    """
    if content_type == VOD_KIND_MOVIE:
        return VOD_KIND_MOVIE
    if content_type in (VOD_KIND_SERIES, "episode"):
        return VOD_KIND_SERIES
    return None
