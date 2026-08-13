from __future__ import annotations

import os
import re
import subprocess
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Any

from apps.epg.utils import extract_season_episode
from apps.media_servers.dvr_library import resolve_dvr_library_path


def _text(value: Any) -> str:
    return str(value).strip() if value not in (None, "") else ""


def _add_text(parent: ET.Element, tag: str, value: Any) -> None:
    value = _text(value)
    if value:
        ET.SubElement(parent, tag).text = value


def _as_list(value: Any) -> list[Any]:
    if value in (None, ""):
        return []
    if isinstance(value, (list, tuple, set)):
        return list(value)
    return [value]


def _date_only(value: Any) -> str:
    value = _text(value)
    if not value:
        return ""
    match = re.match(r"^(\d{4}-\d{2}-\d{2})", value)
    return match.group(1) if match else value


def _number(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _duration_minutes(
    properties: dict,
    start_time: datetime | None,
    end_time: datetime | None,
) -> int | None:
    length = properties.get("length") or {}
    if isinstance(length, dict):
        try:
            amount = float(length.get("value"))
        except (TypeError, ValueError):
            amount = None
        units = _text(length.get("units")).lower()
        if amount is not None and amount > 0:
            if units.startswith("sec"):
                return max(1, round(amount / 60))
            if units.startswith("hour"):
                return max(1, round(amount * 60))
            return max(1, round(amount))
    if start_time and end_time and end_time > start_time:
        return max(1, round((end_time - start_time).total_seconds() / 60))
    return None


def _duration_seconds(
    recording_properties: dict,
    epg_properties: dict,
    start_time: datetime | None,
    end_time: datetime | None,
) -> int | None:
    explicit = _number(recording_properties.get("duration_secs"))
    if explicit is not None and explicit > 0:
        return explicit
    minutes = _duration_minutes(epg_properties, start_time, end_time)
    return minutes * 60 if minutes is not None else None


def _numeric_rating(properties: dict) -> str:
    for entry in _as_list(properties.get("star_ratings")):
        value = entry.get("value") if isinstance(entry, dict) else entry
        match = re.search(r"(\d+(?:\.\d+)?)", _text(value))
        if match:
            return match.group(1)
    rating = _text(properties.get("rating"))
    return rating if re.fullmatch(r"\d+(?:\.\d+)?", rating) else ""


def _add_people(root: ET.Element, properties: dict) -> None:
    credits = properties.get("credits") or {}
    if not isinstance(credits, dict):
        return
    for director in _as_list(credits.get("director")):
        _add_text(root, "director", director)
    for writer in _as_list(credits.get("writer")):
        _add_text(root, "credits", writer)
    for actor in _as_list(credits.get("actor")):
        actor_node = ET.SubElement(root, "actor")
        if isinstance(actor, dict):
            _add_text(actor_node, "name", actor.get("name"))
            _add_text(actor_node, "role", actor.get("role"))
        else:
            _add_text(actor_node, "name", actor)


def _add_movie_identifiers(root: ET.Element, properties: dict) -> None:
    identifiers = (
        ("imdb", properties.get("imdb.com_id")),
        ("tmdb", properties.get("themoviedb.org_id")),
        ("tvdb", properties.get("thetvdb.com_id")),
    )
    default_written = False
    for identifier_type, value in identifiers:
        value = _text(value)
        if not value:
            continue
        node = ET.SubElement(
            root,
            "uniqueid",
            {
                "type": identifier_type,
                "default": "true" if not default_written else "false",
            },
        )
        node.text = value
        default_written = True


def build_recording_nfo_xml(
    *,
    program: dict | None,
    epg_properties: dict | None,
    recording_properties: dict | None,
    channel_name: str,
    start_time: datetime | None,
    end_time: datetime | None,
) -> str:
    """Build a Kodi/Jellyfin/Emby-compatible movie or episode sidecar."""
    program = program if isinstance(program, dict) else {}
    epg_properties = epg_properties if isinstance(epg_properties, dict) else {}
    recording_properties = (
        recording_properties if isinstance(recording_properties, dict) else {}
    )

    title = _text(program.get("title")) or _text(channel_name) or "Recording"
    episode_title = _text(program.get("sub_title"))
    description = _text(program.get("description"))
    categories = [
        _text(category)
        for category in _as_list(epg_properties.get("categories"))
        if _text(category)
    ]
    category_names = {category.lower() for category in categories}
    is_movie = bool(category_names.intersection({"movie", "film"}))

    season, episode = extract_season_episode(epg_properties, description)
    if season is None:
        season = _number(recording_properties.get("season"))
    if episode is None:
        episode = _number(recording_properties.get("episode"))
    if not is_movie and not episode_title:
        episode_title = f"Episode {episode}" if episode is not None else title

    previously_shown = epg_properties.get("previously_shown_details") or {}
    aired = _date_only(
        previously_shown.get("start")
        if isinstance(previously_shown, dict)
        else None
    ) or _date_only(epg_properties.get("date"))
    if not aired and start_time:
        aired = start_time.date().isoformat()
    year = _text(epg_properties.get("date"))[:4]
    if not re.fullmatch(r"\d{4}", year):
        year = aired[:4] if re.match(r"^\d{4}", aired) else ""
    duration_seconds = _duration_seconds(
        recording_properties,
        epg_properties,
        start_time,
        end_time,
    )
    runtime = (
        max(1, round(duration_seconds / 60))
        if duration_seconds is not None
        else _duration_minutes(epg_properties, start_time, end_time)
    )
    content_rating = _text(epg_properties.get("rating"))
    numeric_rating = _numeric_rating(epg_properties)

    root = ET.Element("movie" if is_movie else "episodedetails")
    _add_text(root, "title", title if is_movie else episode_title)
    _add_text(root, "originaltitle", title if is_movie else episode_title)
    if not is_movie:
        _add_text(root, "showtitle", title)
        # The EPG date is the episode air year, not necessarily the show's
        # premiere year. Only write showyear when an explicit series year is
        # available; otherwise TMDB title matching must not be constrained by
        # an incorrect episode year.
        _add_text(
            root,
            "showyear",
            recording_properties.get("series_year")
            or epg_properties.get("series_year"),
        )
        _add_text(root, "season", season)
        _add_text(root, "episode", episode)
    _add_text(root, "plot", description)
    _add_text(root, "outline", description)
    _add_text(root, "year", year)
    _add_text(root, "aired", aired)
    _add_text(root, "premiered", aired)
    _add_text(root, "runtime", runtime)
    _add_text(root, "durationinseconds", duration_seconds)
    _add_text(root, "rating", numeric_rating)
    _add_text(root, "mpaa", content_rating)
    _add_text(root, "studio", channel_name)
    _add_text(root, "country", epg_properties.get("country"))
    _add_text(root, "language", epg_properties.get("language"))
    poster_url = _text(recording_properties.get("poster_url"))
    if poster_url.startswith(("http://", "https://")):
        poster = ET.SubElement(root, "thumb", {"aspect": "poster"})
        poster.text = poster_url
    for category in categories:
        _add_text(root, "genre", category)
    _add_people(root, epg_properties)

    program_id = _text(program.get("program_id"))
    if program_id:
        node = ET.SubElement(
            root,
            "uniqueid",
            {"type": "schedulesdirect", "default": "false"},
        )
        node.text = program_id
    if is_movie:
        _add_movie_identifiers(root, epg_properties)

    try:
        ET.indent(root, space="  ")
    except AttributeError:
        pass
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        + ET.tostring(root, encoding="unicode")
        + "\n"
    )


def write_recording_nfo(recording) -> str:
    """Write the completed recording's NFO atomically beside its video file."""
    properties = recording.custom_properties or {}
    video_path = resolve_dvr_library_path(
        properties.get("file_path"),
        must_exist=True,
        require_directory=False,
    )
    if not video_path.is_file():
        raise FileNotFoundError("The completed recording video does not exist.")

    program = properties.get("program") or {}
    if not isinstance(program, dict):
        program = {}
    epg_properties: dict = {}
    program_id = program.get("id") if isinstance(program, dict) else None
    if program_id:
        from apps.epg.models import ProgramData

        epg_program = ProgramData.objects.filter(id=program_id).only(
            "program_id",
            "custom_properties",
        ).first()
        if epg_program:
            epg_properties = epg_program.custom_properties or {}
            if epg_program.program_id and not program.get("program_id"):
                program = {**program, "program_id": epg_program.program_id}

    xml = build_recording_nfo_xml(
        program=program,
        epg_properties=epg_properties,
        recording_properties=properties,
        channel_name=getattr(recording.channel, "name", ""),
        start_time=recording.start_time,
        end_time=recording.end_time,
    )
    nfo_path = resolve_dvr_library_path(
        str(Path(video_path).with_suffix(".nfo")),
        must_exist=False,
        require_directory=False,
    )
    temporary = nfo_path.with_name(f".{nfo_path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(xml, encoding="utf-8")
        os.replace(temporary, nfo_path)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
    return str(nfo_path)


def _refresh_completed_comskip_metadata(recording, video_path: Path) -> bool:
    """Repair pre-fix Comskip metadata during an explicit DVR sync."""
    properties = dict(recording.custom_properties or {})
    comskip = properties.get("comskip") or {}
    if not isinstance(comskip, dict) or comskip.get("status") != "completed":
        return False

    try:
        file_size = video_path.stat().st_size
    except OSError:
        return False

    duration_secs = _number(properties.get("duration_secs"))
    recorded_size = _number(properties.get("file_size_bytes"))
    if duration_secs and duration_secs > 0 and recorded_size == file_size:
        return False

    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(video_path),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
        )
        exact_duration = float(result.stdout.strip())
    except (OSError, subprocess.SubprocessError, TypeError, ValueError):
        exact_duration = None

    if exact_duration is None or exact_duration <= 0:
        # Do not mark the current file size as reconciled when probing fails;
        # a later manual sync should be able to retry the repair.
        return False
    properties["duration_secs"] = max(1, round(exact_duration))
    properties["file_size_bytes"] = file_size
    recording.custom_properties = properties
    return True


def backfill_recording_nfos() -> dict[str, int]:
    """Create or refresh managed sidecars before a DVR library scan."""
    from apps.channels.models import Recording

    counts = {"written": 0, "existing": 0, "failed": 0}
    recordings = (
        Recording.objects.filter(custom_properties__status="completed")
        .select_related("channel")
        .iterator()
    )
    for recording in recordings:
        properties = dict(recording.custom_properties or {})
        try:
            video_path = resolve_dvr_library_path(
                properties.get("file_path"),
                must_exist=True,
                require_directory=False,
            )
            metadata_changed = _refresh_completed_comskip_metadata(
                recording,
                video_path,
            )
            properties = dict(recording.custom_properties or {})
            nfo_path = resolve_dvr_library_path(
                str(video_path.with_suffix(".nfo")),
                must_exist=False,
                require_directory=False,
            )
            stored_nfo_path = str(properties.get("nfo_path") or "").strip()
            managed_nfo = bool(
                stored_nfo_path
                and properties.get("nfo_managed") is not False
                and Path(stored_nfo_path).resolve(strict=False) == nfo_path
            )
            if nfo_path.is_file() and not managed_nfo:
                # An untracked sidecar may be operator-managed. Preserve it.
                counts["existing"] += 1
                nfo_managed = False
            else:
                nfo_path = Path(write_recording_nfo(recording))
                counts["written"] += 1
                nfo_managed = True

            if (
                metadata_changed
                or properties.get("nfo_path") != str(nfo_path)
                or properties.get("nfo_managed") is not nfo_managed
            ):
                recording.custom_properties = {
                    **properties,
                    "nfo_path": str(nfo_path),
                    "nfo_managed": nfo_managed,
                }
                recording.save(update_fields=["custom_properties"])
        except Exception:
            counts["failed"] += 1
    return counts
