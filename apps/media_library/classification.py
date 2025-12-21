import os
import re
from typing import Optional

from guessit import guessit

from apps.media_library.models import Library, MediaItem
from apps.media_library.utils import ClassificationResult, _json_safe, normalize_title

SEASON_FOLDER_PATTERN = re.compile(
    r"^(?:season|series|s)[\s\._-]*([0-9]{1,3})$", re.IGNORECASE
)
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
YEAR_PATTERN = re.compile(r"(?<!\d)(19\d{2}|20\d{2})(?!\d)")
MOVIE_JUNK_TOKEN_PATTERN = re.compile(
    r"(?i)^(1080p|720p|2160p|480p|4k|web[- ]?dl|webrip|hdrip|hdtv|b[dr]rip|bluray|dvdrip|xvid|x264|x265|h264|h265|hevc|10bit|8bit|dts|ac3|aac|eac3|ddp|atmos|hdr10(?:plus)?|uhd|remux|proper|repack|unrated|extended|imax|readnfo|internal|limited|criterion|remastered|multi|dual(?:audio)?|subs?|yts|yify|rarbg|evo|fgt|psa|galaxy|amzn|nf|hmax|bd25|bd50)$"
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


def _ensure_series_name_from_path(
    relative_path: str, default: str | None = None
) -> str:
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

    sanitized = re.sub(
        r"(([^._]{2,})[\._]*)|([\._]([^._]{2,}))", r"\2\4", series_candidate
    ).replace("_", " ").replace(".", " ")
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


def _extract_year_from_text(text: str | None) -> Optional[int]:
    if not text:
        return None
    candidates = []
    for match in YEAR_PATTERN.finditer(text):
        try:
            year = int(match.group(1))
            candidates.append(year)
        except (TypeError, ValueError):
            continue
    if not candidates:
        return None
    return candidates[-1]


def _tokenize_release_name(text: str) -> list[str]:
    """
    Break a release name into tokens with punctuation stripped so we can
    drop common quality/source tags. Periods and underscores are treated
    as separators to better match scene-style names.
    """
    if not text:
        return []
    cleaned = re.sub(r"[\[\]\(\)\{\}]", " ", text)
    cleaned = re.sub(r"[._]", " ", cleaned)
    cleaned = cleaned.replace("-", " ")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return [token for token in cleaned.split(" ") if token]


def _is_release_junk(token: str) -> bool:
    if not token:
        return True
    if MOVIE_JUNK_TOKEN_PATTERN.match(token):
        return True
    if re.match(r"^\d+\.\d+$", token):
        return True
    token_lower = token.lower()
    if token_lower in {"yts.mx", "yts.ag", "yts.lt", "yts.mx", "rarbg"}:
        return True
    return False


def _sanitize_movie_title(
    title_source: str, base_name: str, year_hint: int | None = None
) -> tuple[str, int | None]:
    """
    Extract a clean movie title (and possibly year) from a release-style
    name. Removes quality/source tags and stops parsing once a year token
    is reached so entries like "6.Underground.2019.1080p..." become
    "6 Underground".
    """
    year = (
        year_hint
        or _extract_year_from_text(title_source)
        or _extract_year_from_text(base_name)
    )
    tokens = _tokenize_release_name(title_source)
    cleaned_tokens: list[str] = []
    for token in tokens:
        token_stripped = token.strip(" -_.")
        if not token_stripped:
            continue
        if year and token_stripped.isdigit() and int(token_stripped) == year:
            break
        if _is_release_junk(token_stripped):
            continue
        cleaned_tokens.append(token_stripped)
    cleaned_title = " ".join(cleaned_tokens).strip()
    if not cleaned_title and title_source != base_name:
        tokens = _tokenize_release_name(base_name)
        cleaned_tokens = []
        for token in tokens:
            token_stripped = token.strip(" -_.")
            if not token_stripped:
                continue
            if year and token_stripped.isdigit() and int(token_stripped) == year:
                break
            if _is_release_junk(token_stripped):
                continue
            cleaned_tokens.append(token_stripped)
        cleaned_title = " ".join(cleaned_tokens).strip()
    if not cleaned_title:
        cleaned_title = re.sub(r"[._]", " ", base_name)
        cleaned_title = re.sub(r"\s+", " ", cleaned_title).strip()
    return cleaned_title, year


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
    series_name = _ensure_series_name_from_path(
        relative_path, default=guessed_title or base_name
    )

    if library.library_type == Library.LIBRARY_TYPE_SHOWS:
        season_number = _safe_number(guess_data.get("season"))
        episode_number = _safe_number(guess_data.get("episode"))
        episode_title = _first_text(guess_data.get("episode_title"))

        if season_number is None:
            season_number = _season_from_segments(segments)

        if episode_number is None:
            episode_number = _safe_number(guess_data.get("episode_list"))

        episode_list_raw = guess_data.get("episode_list") or []
        if not episode_list_raw and isinstance(
            guess_data.get("episode"), (list, tuple)
        ):
            episode_list_raw = list(guess_data.get("episode") or [])
        episode_list = []
        for item in episode_list_raw:
            number = _safe_number(item)
            if number is not None and number not in episode_list:
                episode_list.append(number)

        if episode_number is None:
            match = EPISODE_PATTERN.search(file_name)
            if match:
                episode_number = _safe_number(
                    match.group("episode") or match.group("abs_episode")
                )
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

        detected_type = (
            MediaItem.TYPE_EPISODE
            if season_number is not None and episode_number is not None
            else MediaItem.TYPE_SHOW
        )
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
            episode_title=episode_title or None,
            data=data,
        )

    detected_type = (
        MediaItem.TYPE_MOVIE
        if library.library_type == Library.LIBRARY_TYPE_MOVIES
        else MediaItem.TYPE_OTHER
    )
    data = _json_safe(guess_data)
    title_candidate = guessed_title or base_name
    title, parsed_year = _sanitize_movie_title(
        title_candidate, base_name, _safe_number(guess_data.get("year"))
    )
    year = _safe_number(guess_data.get("year")) or parsed_year
    if title and title != guessed_title:
        data["parsed_title"] = title
    if year is not None:
        data["parsed_year"] = year
    return ClassificationResult(
        detected_type=detected_type,
        title=title,
        year=year,
        data=data,
    )
