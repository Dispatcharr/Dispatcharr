from __future__ import annotations

import os

DEFAULT_STRM_OUTPUT_PATH = "/data/media/strm"

_LEGACY_MEDIA_ROOT = "/data/media"
_LEGACY_MOVIES_PATH = "/data/media/Movies"
_LEGACY_TV_PATH = "/data/media/TV Shows"


def normalize_local_path(path_value: str) -> str:
    raw = str(path_value or "").strip()
    if not raw:
        return ""
    return os.path.realpath(os.path.abspath(os.path.expanduser(raw)))


def normalize_strm_output_path(
    path_value: str,
    *,
    fallback: str = DEFAULT_STRM_OUTPUT_PATH,
) -> str:
    normalized = normalize_local_path(path_value)
    if not normalized:
        normalized = normalize_local_path(fallback)

    if normalized in {
        normalize_local_path(_LEGACY_MEDIA_ROOT),
        normalize_local_path(_LEGACY_MOVIES_PATH),
        normalize_local_path(_LEGACY_TV_PATH),
    }:
        return normalize_local_path(DEFAULT_STRM_OUTPUT_PATH)
    return normalized


def paths_overlap(path_a: str, path_b: str) -> bool:
    left = normalize_local_path(path_a)
    right = normalize_local_path(path_b)
    if not left or not right:
        return False
    try:
        common = os.path.commonpath([left, right])
    except ValueError:
        return False
    return common == left or common == right


def sanitize_output_settings_paths(settings_value: dict) -> tuple[dict, bool]:
    if not isinstance(settings_value, dict):
        return {}, False

    next_value = dict(settings_value)
    changed = False

    strm_output_path = normalize_strm_output_path(next_value.get("strm_output_path"))
    if str(next_value.get("strm_output_path") or "").strip() != strm_output_path:
        next_value["strm_output_path"] = strm_output_path
        changed = True

    raw_profiles = next_value.get("output_integrations")
    if isinstance(raw_profiles, list):
        normalized_profiles = []
        profiles_changed = False
        for raw_profile in raw_profiles:
            if not isinstance(raw_profile, dict):
                normalized_profiles.append(raw_profile)
                continue
            profile = dict(raw_profile)
            profile_strm_output_path = normalize_strm_output_path(
                profile.get("strm_output_path"),
                fallback=strm_output_path,
            )
            if (
                str(profile.get("strm_output_path") or "").strip()
                != profile_strm_output_path
            ):
                profile["strm_output_path"] = profile_strm_output_path
                profiles_changed = True
            normalized_profiles.append(profile)
        if profiles_changed:
            next_value["output_integrations"] = normalized_profiles
            changed = True

    return next_value, changed
