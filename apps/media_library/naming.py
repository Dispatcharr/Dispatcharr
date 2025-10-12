import os
import re
from dataclasses import dataclass
from typing import Optional

from guessit import guessit

from apps.media_library.models import Library, MediaItem
from apps.media_library.utils import ClassificationResult, _json_safe, normalize_title

SEASON_FOLDER_PATTERN = re.compile(r"^(?:season|series|s)[\s\._-]*([0-9]{1,3})$", re.IGNORECASE)
EPISODE_PATTERN = re.compile(
    r"""
    (?:
        s(?P<season>\d{1,3})
        [\.\-_\s]*
        e(?P<episode>\d{1,4})
        (?:[\.\-_\s]*e?(?P<episode_end>\d{1,4}))?
    )
    |
    (?P<abs_episode>\d{1,4})
    """,
    re.IGNORECASE | re.VERBOSE,
)


def _safe_number(value):
    if isinstance(value, (list, tuple, set)):
        for entry in value:
            normalized = _safe_number(entry)
            if normalized is not None:
                return normalized
        return None
    if value in (None, "", []):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None


def _strip_extension(file_name: str) -> str:
    base, _ext = os.path.splitext(file_name)
    return base


def _first_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple, set)):
        for entry in value:
            text = _first_text(entry)
            if text:
                return text
        return ""
    if isinstance(value, dict):
        for key in ("title", "name", "value"):
            if key in value:
                text = _first_text(value[key])
                if text:
                    return text
        return ""
    return str(value)


def _ensure_series_name_from_path(relative_path: str, default: str | None = None) -> str:
    """
    Best effort extraction of a series title from a relative path.
    Matches Jellyfin's approach of sanitizing folder names by replacing
    dots/underscores with spaces when they separate words.
    """
    if not relative_path:
        return default or ""

    segments = [segment for segment in relative_path.split(os.sep) if segment]
    if not segments:
        return default or ""

    series_candidate = None
    for segment in segments:
        if SEASON_FOLDER_PATTERN.match(segment):
            continue
        series_candidate = segment
        break

    if series_candidate is None:
        series_candidate = segments[0]

    sanitized = re.sub(r"(([^._]{2,})[\._]*)|([\._]([^._]{2,}))", r"\2\4", series_candidate).replace("_", " ").replace(".", " ")
    sanitized = re.sub(r"\s+", " ", sanitized).strip()
    return sanitized or (default or "")


def _season_from_segments(segments: list[str]) -> Optional[int]:
    for segment in reversed(segments):
        match = SEASON_FOLDER_PATTERN.match(segment)
        if match:
            try:
                return int(match.group(1))
            except (TypeError, ValueError):
                continue
    return None


def classify_media_entry(
    library: Library,
    *,
    relative_path: str,
    file_name: str,
) -> ClassificationResult:
    """
    Wrapper around guessit that injects folder hints similar to Jellyfin's resolver.
    """
    base_name = _strip_extension(file_name)
    guess_data = {}
    guess_target = file_name
    if relative_path:
        guess_target = os.path.join(relative_path, file_name)
    guess_options = {}
    if library.library_type == Library.LIBRARY_TYPE_SHOWS:
        guess_options = {"type": "episode", "show_type": "series"}
    elif library.library_type == Library.LIBRARY_TYPE_MOVIES:
        guess_options = {"type": "movie"}
    guessed_title = ""

    # Provide path context to guessit.
    try:
        if guess_options:
            guess_data = guessit(guess_target, options=guess_options)
        else:
            guess_data = guessit(guess_target)
        guessed_title = _first_text(guess_data.get("title"))
    except Exception:
        guess_data = {}
        guessed_title = ""

    segments = [segment for segment in relative_path.split(os.sep) if segment]
    series_name = _ensure_series_name_from_path(relative_path, default=guessed_title or base_name)

    if library.library_type == Library.LIBRARY_TYPE_SHOWS:
        season_number = _safe_number(guess_data.get("season"))
        episode_number = _safe_number(guess_data.get("episode"))

        if season_number is None:
            season_number = _season_from_segments(segments)

        if episode_number is None:
            episode_number = _safe_number(guess_data.get("episode_list"))

        episode_list_raw = guess_data.get("episode_list") or []
        if not episode_list_raw and isinstance(guess_data.get("episode"), (list, tuple)):
            episode_list_raw = list(guess_data.get("episode") or [])
        episode_list = []
        for item in episode_list_raw:
            number = _safe_number(item)
            if number is not None and number not in episode_list:
                episode_list.append(number)

        if episode_number is None:
            match = EPISODE_PATTERN.search(file_name)
            if match:
                episode_number = _safe_number(match.group("episode") or match.group("abs_episode"))
                if season_number is None and match.group("season"):
                    try:
                        season_number = int(match.group("season"))
                    except (TypeError, ValueError):
                        season_number = None
                if match.group("episode_end"):
                    end_number = _safe_number(match.group("episode_end"))
                    if end_number:
                        if end_number not in episode_list:
                            episode_list.append(end_number)
                        if episode_number is not None and episode_number not in episode_list:
                            episode_list.append(episode_number)

        detected_type = MediaItem.TYPE_EPISODE if season_number is not None and episode_number is not None else MediaItem.TYPE_SHOW
        normalized_title = normalize_title(series_name or base_name)
        data = _json_safe(guess_data)
        if season_number is not None:
            data["season"] = season_number
        if episode_number is not None:
            data["episode"] = episode_number
        if episode_list:
            episode_list_sorted = sorted({n for n in episode_list if isinstance(n, int)})
            if episode_list_sorted:
                data["episode_list"] = episode_list_sorted
        if series_name:
            data["series"] = series_name

        return ClassificationResult(
            detected_type=detected_type,
            title=series_name or base_name,
            year=guess_data.get("year"),
            season=season_number,
            episode=episode_number,
            episode_title=guess_data.get("episode_title"),
            data=data,
        )

    # Movies & other types fall back to original logic.
    detected_type = MediaItem.TYPE_MOVIE if library.library_type == Library.LIBRARY_TYPE_MOVIES else MediaItem.TYPE_OTHER
    data = _json_safe(guess_data)
    title = guessed_title or base_name
    return ClassificationResult(
        detected_type=detected_type,
        title=title,
        year=guess_data.get("year"),
        data=data,
    )
