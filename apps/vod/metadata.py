"""Source-owned VOD metadata shared by import, API and playback selection."""

import re

from .language_codes import LANGUAGES

METADATA_FIELDS = frozenset(
    {
        "audio_languages",
        "subtitle_languages",
        "resolution",
        "video_features",
    }
)
VIDEO_FEATURES = frozenset({"3d", "hdr", "dv"})
RESOLUTIONS = ("4320p", "2160p", "1440p", "1080p", "720p", "576p", "480p", "360p", "SD")
LANGUAGE_ALIASES = {
    alias: code
    for code, entry in LANGUAGES.items()
    for alias in (code, entry.get("alpha2"), entry.get("terminological"))
    if alias
}


def normalize_language_code(value):
    if not isinstance(value, str):
        raise ValueError("Language codes must be strings.")
    code = LANGUAGE_ALIASES.get(value.strip().lower())
    if code is None:
        raise ValueError("Use a valid ISO 639-2 language code.")
    return code


def normalize_languages(value):
    if not isinstance(value, list):
        raise ValueError("Languages must be a list of ISO 639-2 codes.")
    return list(dict.fromkeys(normalize_language_code(item) for item in value))


def normalize_resolution(value):
    if not isinstance(value, str):
        raise ValueError("Resolution must be a string.")
    aliases = {"4k": "2160p", "8k": "4320p", "fhd": "1080p", "hd": "720p", "sd": "SD"}
    resolution = aliases.get(value.strip().lower(), value.strip().lower())
    if resolution not in RESOLUTIONS:
        raise ValueError("Use a supported resolution tier.")
    return resolution


def normalize_video_feature(value):
    if not isinstance(value, str):
        raise ValueError("Video features must be strings.")
    feature = value.strip().lower()
    if feature in VIDEO_FEATURES:
        return feature
    if feature.startswith("custom:"):
        slug = feature.removeprefix("custom:")
        if re.fullmatch(r"[a-z0-9](?:[a-z0-9._-]*[a-z0-9])?", slug):
            return slug if slug in VIDEO_FEATURES else feature
    raise ValueError("Use 3d, hdr, dv or a custom:<tag> video feature.")


def validate_source_metadata(payload, *, allow_reset=False):
    """Missing keys inherit, [] explicitly clears a list, null resets an override."""
    if not isinstance(payload, dict):
        raise ValueError("Source metadata must be an object.")
    if set(payload) - METADATA_FIELDS:
        raise ValueError("Unsupported source metadata field.")
    normalized = {}
    for key, value in payload.items():
        if value is None and allow_reset:
            normalized[key] = None
        elif key in {"audio_languages", "subtitle_languages"}:
            normalized[key] = normalize_languages(value)
        elif key == "resolution":
            normalized[key] = normalize_resolution(value)
        elif key == "video_features":
            if not isinstance(value, list):
                raise ValueError("Video features must be a list.")
            normalized[key] = list(
                dict.fromkeys(normalize_video_feature(item) for item in value)
            )
    return normalized


def legacy_category_metadata(properties):
    """Read old scalar category fields without using them as content identity."""
    properties = properties if isinstance(properties, dict) else {}
    result = {}
    if properties.get("language"):
        try:
            result["audio_languages"] = [
                normalize_language_code(properties["language"])
            ]
        except ValueError:
            pass
    if properties.get("quality"):
        try:
            result["resolution"] = normalize_resolution(properties["quality"])
        except ValueError:
            pass
    for key in METADATA_FIELDS:
        if key in properties and properties[key] is not None:
            result.update(validate_source_metadata({key: properties[key]}))
    return result


def provider_source_metadata(payload):
    """Read explicit facts, including the retained XC episode_data.info shape.

    Nested episode details override list-level facts field by field. Reading
    the retained raw payload also repairs effective metadata for existing
    sources without requiring a refresh or rewriting an applied migration.
    """
    payload = payload if isinstance(payload, dict) else {}
    result = {}
    for layer in (payload, payload.get("info")):
        if not isinstance(layer, dict):
            continue
        facts = {}
        for key in METADATA_FIELDS:
            if key in layer and layer[key] is not None:
                try:
                    facts.update(validate_source_metadata({key: layer[key]}))
                except ValueError:
                    # Keep invalid/partial fields in the original provider
                    # payload; they must not erase other valid declarations.
                    continue
        if "resolution" not in facts and layer.get("quality"):
            try:
                facts["resolution"] = normalize_resolution(layer["quality"])
            except ValueError:
                pass
        result.update(facts)
    return result


def update_declared_metadata(relation, payload):
    """A partial provider refresh must not erase other explicit source facts."""
    relation.declared_metadata = {
        **(relation.declared_metadata or {}),
        **provider_source_metadata(payload),
    }


def category_key(relation):
    category_id = getattr(relation, "category_id", None)
    if category_id is None:
        series_relation = getattr(relation, "series_relation", None)
        category_id = series_relation.category_id if series_relation else None
    return relation.m3u_account_id, category_id


def category_metadata_map(relations):
    from .models import M3UVODCategoryRelation

    keys = {category_key(relation) for relation in relations}
    if not keys:
        return {}
    accounts = {key[0] for key in keys}
    categories = {key[1] for key in keys if key[1] is not None}
    return {
        (row.m3u_account_id, row.category_id): {
            **legacy_category_metadata(row.custom_properties),
            **(row.metadata_defaults or {}),
        }
        for row in M3UVODCategoryRelation.objects.filter(
            m3u_account_id__in=accounts, category_id__in=categories
        )
        if (row.m3u_account_id, row.category_id) in keys
    }


def effective_source_metadata(relation, *, category_defaults=None):
    if category_defaults is None:
        category_defaults = category_metadata_map([relation]).get(
            category_key(relation), {}
        )
    values, provenance = {}, {}
    props = relation.custom_properties or {}
    provider = {
        **provider_source_metadata(props.get("info")),
        **provider_source_metadata(props.get("basic_data")),
        **provider_source_metadata(props.get("detailed_info")),
        **(relation.declared_metadata or {}),
    }
    series_source = getattr(relation, "series_relation", None)
    inherited = (
        effective_source_metadata(series_source, category_defaults=category_defaults)[
            "values"
        ]
        if series_source is not None
        else {}
    )
    for source, payload in (
        ("category", category_defaults),
        ("series", inherited),
        ("provider", provider),
        ("observed", relation.observed_metadata or {}),
        ("manual", relation.manual_metadata or {}),
    ):
        for key, value in payload.items():
            if key in METADATA_FIELDS and value is not None:
                values[key] = value
                provenance[key] = source
    return {"values": values, "provenance": provenance}


def requirements_from_metadata(metadata):
    """A selection records constraints, not a synthetic language-group identity."""
    result = {key: metadata[key] for key in METADATA_FIELDS if metadata.get(key)}
    for key in ("audio_languages", "subtitle_languages"):
        if key in result:
            result[key] = [
                code for code in result[key] if code not in {"und", "mul", "mis"}
            ]
            if not result[key]:
                result.pop(key)
    return result


def metadata_satisfies(metadata, requirements):
    for key in ("audio_languages", "subtitle_languages", "video_features"):
        if not set(requirements.get(key, [])).issubset(metadata.get(key, [])):
            return False
    if (
        requirements.get("resolution")
        and metadata.get("resolution") != requirements["resolution"]
    ):
        return False
    return not requirements.get("unresolved_language")


def metadata_suffix(name, metadata):
    """Describe the selected source without asserting facts about every source."""
    tags = [
        "/".join(code.upper() for code in metadata.get("audio_languages", [])),
        metadata.get("resolution", ""),
        "/".join(
            feature.removeprefix("custom:").upper()
            for feature in metadata.get("video_features", [])
        ),
    ]
    suffix = " · ".join(tag for tag in tags if tag)
    return f"{name} [{suffix}]" if name and suffix else name
