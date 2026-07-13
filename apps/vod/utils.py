def _first_text(*values):
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, (list, tuple)):
            for item in value:
                if isinstance(item, str) and item.strip():
                    return item.strip()
    return None


def _relation_metadata(series_relation):
    properties = getattr(series_relation, "custom_properties", None) or {}
    if not isinstance(properties, dict):
        return {}, {}

    detailed_info = properties.get("detailed_info") or {}
    basic_data = properties.get("basic_data") or {}
    return (
        detailed_info if isinstance(detailed_info, dict) else {},
        basic_data if isinstance(basic_data, dict) else {},
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
