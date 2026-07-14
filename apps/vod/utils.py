def _first_text(*values):
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, (list, tuple)):
            for item in value:
                if isinstance(item, str) and item.strip():
                    return item.strip()
    return None


def _relation_properties(relation_or_properties):
    if isinstance(relation_or_properties, dict):
        return relation_or_properties

    properties = getattr(
        relation_or_properties,
        "custom_properties",
        None,
    ) or {}
    return properties if isinstance(properties, dict) else {}


def _relation_metadata(relation_or_properties):
    properties = _relation_properties(relation_or_properties)
    if not isinstance(properties, dict):
        return {}, {}

    detailed_info = properties.get("detailed_info") or {}
    basic_data = properties.get("basic_data") or {}
    return (
        detailed_info if isinstance(detailed_info, dict) else {},
        basic_data if isinstance(basic_data, dict) else {},
    )


def get_vod_source_name(relation_or_properties, fallback_name):
    """Return the exact provider-list title for a movie or series relation.

    ``basic_data.name`` is captured from the provider's get_vod_streams or
    get_series response and therefore retains source prefixes such as NF, DE,
    or NICK. Detailed metadata is only a fallback because providers commonly
    return a cleaned title there.
    """
    properties = _relation_properties(relation_or_properties)
    detailed_info, basic_data = _relation_metadata(properties)
    movie_data = properties.get("movie_data") or {}
    if not isinstance(movie_data, dict):
        movie_data = {}

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


def get_series_original_name(series, series_relation=None):
    """Return provider metadata's original title without guessing prefixes."""
    detailed_info, basic_data = _relation_metadata(series_relation)
    series_properties = getattr(series, "custom_properties", None) or {}
    if not isinstance(series_properties, dict):
        series_properties = {}

    return _first_text(
        detailed_info.get("original_name"),
        detailed_info.get("o_name"),
        basic_data.get("original_name"),
        basic_data.get("o_name"),
        series_properties.get("original_name"),
        series_properties.get("o_name"),
    )


def get_series_display_name(series, series_relation=None):
    """Mirror movie title selection using relation-specific provider details."""
    detailed_info, _basic_data = _relation_metadata(series_relation)
    return (
        _first_text(detailed_info.get("name"))
        or get_series_original_name(series, series_relation)
        or series.name
    )
