import logging
import os
import subprocess
import tempfile
import time
from typing import Iterable, Optional

import requests
from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage

from apps.media_library.models import MediaItem, SubtitleAsset

logger = logging.getLogger(__name__)

OS_API_URL = getattr(settings, "OPENSUBTITLES_API_URL", "https://api.opensubtitles.com/api/v1")
OS_API_KEY = getattr(settings, "OPENSUBTITLES_API_KEY", "")
OS_USERNAME = getattr(settings, "OPENSUBTITLES_USERNAME", "")
OS_PASSWORD = getattr(settings, "OPENSUBTITLES_PASSWORD", "")
OS_USER_AGENT = getattr(settings, "OPENSUBTITLES_USER_AGENT", "Dispatcharr/1.0")

_OS_SESSION = requests.Session()
_OS_SESSION.headers.update({"Api-Key": OS_API_KEY, "User-Agent": OS_USER_AGENT})
_OS_TOKEN: Optional[str] = None
_OS_TOKEN_EXPIRES_AT: float = 0.0


def _ensure_token() -> Optional[str]:
    global _OS_TOKEN, _OS_TOKEN_EXPIRES_AT
    if not OS_API_KEY:
        logger.debug("OpenSubtitles API key not configured")
        return None
    now = time.time()
    if _OS_TOKEN and now < _OS_TOKEN_EXPIRES_AT:
        return _OS_TOKEN
    if not OS_USERNAME or not OS_PASSWORD:
        # Tokenless mode is allowed but download limits apply.
        return None
    try:
        response = _OS_SESSION.post(
            f"{OS_API_URL}/login",
            json={"username": OS_USERNAME, "password": OS_PASSWORD},
            timeout=10,
        )
    except requests.RequestException as exc:
        logger.warning("OpenSubtitles login failed: %s", exc)
        return None
    if response.status_code != 200:
        logger.warning("OpenSubtitles login returned status %s", response.status_code)
        return None
    token = (response.json() or {}).get("token")
    if not token:
        return None
    _OS_TOKEN = token
    # Token TTL is undocumented; cache for 6 hours.
    _OS_TOKEN_EXPIRES_AT = now + 6 * 60 * 60
    return _OS_TOKEN


def _headers(with_token: bool = True) -> dict:
    headers = {"Api-Key": OS_API_KEY, "User-Agent": OS_USER_AGENT}
    if with_token:
        token = _ensure_token()
        if token:
            headers["Authorization"] = f"Bearer {token}"
    return headers


def _language_pref(media_item: MediaItem) -> Optional[str]:
    library = getattr(media_item, "library", None)
    if library and library.metadata_language:
        return library.metadata_language
    return None


def _store_subtitle(media_item: MediaItem, language: str, fmt: str, content: bytes) -> SubtitleAsset:
    safe_language = language or "und"
    extension = ".vtt" if fmt == SubtitleAsset.FORMAT_VTT else ".srt"
    relative_path = os.path.join("subtitles", str(media_item.id), f"{safe_language}{extension}")

    if default_storage.exists(relative_path):
        try:
            default_storage.delete(relative_path)
        except Exception:
            pass

    default_storage.save(relative_path, ContentFile(content))

    subtitle, _ = SubtitleAsset.objects.update_or_create(
        media_item=media_item,
        language=safe_language,
        format=fmt,
        source="opensubtitles",
        defaults={
            "file_path": relative_path,
            "external_url": "",
            "is_forced": False,
        },
    )
    return subtitle


def download_subtitles_for_media_item(media_item: MediaItem, language: Optional[str] = None) -> list[SubtitleAsset]:
    """
    Fetch subtitles from OpenSubtitles and persist them. Returns a list of SubtitleAsset objects.
    """
    if not OS_API_KEY:
        raise RuntimeError("OpenSubtitles API key is not configured.")

    language = (language or _language_pref(media_item) or "en").lower()

    query_params = {"languages": language, "order_by": "downloads", "order_direction": "desc"}

    imdb_id_raw = media_item.imdb_id or ""
    imdb_numeric = ""
    if imdb_id_raw:
        imdb_numeric = imdb_id_raw.replace("tt", "").strip()
        imdb_numeric = "".join(ch for ch in imdb_numeric if ch.isdigit())

    if imdb_numeric:
        query_params["imdb_id"] = imdb_numeric

    if media_item.item_type == MediaItem.TYPE_MOVIE:
        query_params["type"] = "movie"
        query_params["query"] = media_item.title
        if media_item.release_year:
            query_params["year"] = media_item.release_year
    elif media_item.item_type in (MediaItem.TYPE_SHOW, MediaItem.TYPE_EPISODE):
        query_params["type"] = "episode"
        series_title = media_item.title
        if media_item.item_type == MediaItem.TYPE_EPISODE and media_item.parent:
            series_title = media_item.parent.title or series_title
        query_params["query"] = series_title
        if media_item.season_number is not None:
            query_params["season_number"] = media_item.season_number
        if media_item.episode_number is not None:
            query_params["episode_number"] = media_item.episode_number
        if media_item.release_year:
            query_params["year"] = media_item.release_year

    try:
        response = _OS_SESSION.get(
            f"{OS_API_URL}/subtitles",
            params=query_params,
            headers=_headers(with_token=False),
            timeout=12,
        )
    except requests.RequestException as exc:
        raise RuntimeError(f"OpenSubtitles search failed: {exc}") from exc

    if response.status_code != 200:
        raise RuntimeError(f"OpenSubtitles search returned status {response.status_code}.")

    payload = response.json() or {}
    data = payload.get("data") or []
    if not isinstance(data, list) or not data:
        raise RuntimeError("No subtitles found for this item.")

    best = None
    best_downloads = -1
    for entry in data:
        attributes = entry.get("attributes", {})
        files = attributes.get("files") or []
        if not files:
            continue
        file_entry = files[0] or {}
        file_id = file_entry.get("file_id")
        if not file_id:
            continue
        downloads = attributes.get("downloads") or 0
        if downloads > best_downloads:
            best_downloads = downloads
            best = {"file_id": file_id, "attributes": attributes}

    if not best:
        raise RuntimeError("No suitable subtitle candidate found.")

    file_id = best["file_id"]
    try:
        download_resp = _OS_SESSION.post(
            f"{OS_API_URL}/download",
            json={"file_id": file_id},
            headers=_headers(with_token=True),
            timeout=12,
        )
    except requests.RequestException as exc:
        raise RuntimeError(f"OpenSubtitles download failed: {exc}") from exc

    if download_resp.status_code != 200:
        raise RuntimeError(f"OpenSubtitles download returned status {download_resp.status_code}.")

    download_payload = download_resp.json() or {}
    link = (download_payload.get("data") or {}).get("link")
    subtitle_format = (download_payload.get("data") or {}).get("file_name", "").lower()
    fmt = SubtitleAsset.FORMAT_VTT if subtitle_format.endswith(".vtt") else SubtitleAsset.FORMAT_SRT

    if not link:
        raise RuntimeError("OpenSubtitles did not return a download link.")

    try:
        file_response = _OS_SESSION.get(link, timeout=20)
        file_response.raise_for_status()
    except requests.RequestException as exc:
        raise RuntimeError(f"Unable to fetch subtitle file: {exc}") from exc

    content = file_response.content or b""
    if not content:
        raise RuntimeError("Downloaded subtitle is empty.")

    subtitle = _store_subtitle(media_item, language, fmt, content)
    return [subtitle]


def _extract_embedded_subtitles_for_media_item(media_item: MediaItem, language: Optional[str] = None) -> list[SubtitleAsset]:
    """
    Extract the first matching embedded subtitle track from the media item's files.
    """
    assets: list[SubtitleAsset] = []
    lang_normalized = (language or _language_pref(media_item) or "").lower()

    for media_file in media_item.files.order_by("-duration_ms", "-size_bytes"):
        extra = media_file.extra_streams or {}
        streams = extra.get("streams") or []
        candidates = []
        for stream in streams:
            if stream.get("codec_type") != "subtitle":
                continue
            stream_lang = (stream.get("tags", {}) or {}).get("language") or ""
            stream_lang = stream_lang.lower()
            score = 0
            if lang_normalized and stream_lang == lang_normalized:
                score = 2
            elif lang_normalized and stream_lang.startswith(lang_normalized):
                score = 1
            candidates.append(
                {
                    "index": stream.get("index"),
                    "language": stream_lang or "und",
                    "score": score,
                    "media_file": media_file,
                }
            )

        if not candidates:
            continue

        candidates.sort(key=lambda c: c["score"], reverse=True)
        chosen = candidates[0]
        stream_idx = chosen.get("index")
        if stream_idx is None:
            continue

        # Extract using ffmpeg to WebVTT for browser compatibility.
        with tempfile.NamedTemporaryFile(suffix=".vtt", delete=False) as tmp_file:
            tmp_path = tmp_file.name
        try:
            command = [
                "ffmpeg",
                "-y",
                "-i",
                chosen["media_file"].absolute_path,
                "-map",
                f"0:s:{stream_idx}",
                "-c:s",
                "webvtt",
                tmp_path,
            ]
            subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            with open(tmp_path, "rb") as handle:
                content = handle.read()
            subtitle = _store_subtitle(media_item, chosen["language"], SubtitleAsset.FORMAT_VTT, content)
            assets.append(subtitle)
            return assets
        except Exception as exc:  # noqa: BLE001
            logger.debug("Failed to extract embedded subtitle: %s", exc)
            continue
        finally:
            try:
                os.remove(tmp_path)
            except OSError:
                pass

    return assets


def _find_sidecar_subtitles(media_item: MediaItem, language: Optional[str] = None) -> list[SubtitleAsset]:
    """
    Locate sidecar subtitle files next to the media files.
    """
    assets: list[SubtitleAsset] = []
    lang_normalized = (language or _language_pref(media_item) or "").lower()
    suffixes = [".vtt", ".srt", ".ass", ".ssa"]

    for media_file in media_item.files.order_by("-duration_ms", "-size_bytes"):
        base_path = os.path.splitext(media_file.absolute_path)[0]
        directory = os.path.dirname(media_file.absolute_path)
        if not os.path.isdir(directory):
            continue

        candidate_paths = []
        for suffix in suffixes:
            candidate_paths.append(base_path + suffix)
            if lang_normalized:
                candidate_paths.append(f"{base_path}.{lang_normalized}{suffix}")

        for path in candidate_paths:
            if not os.path.exists(path):
                continue
            ext = os.path.splitext(path)[1].lower()
            fmt = SubtitleAsset.FORMAT_VTT if ext == ".vtt" else SubtitleAsset.FORMAT_SRT
            language_code = lang_normalized or "und"
            subtitle, _ = SubtitleAsset.objects.update_or_create(
                media_item=media_item,
                language=language_code,
                format=fmt,
                source="sidecar",
                defaults={
                    "file_path": path,
                    "external_url": "",
                    "is_forced": False,
                },
            )
            assets.append(subtitle)
            return assets

    return assets


def ensure_subtitles_for_media_item(media_item: MediaItem, language: Optional[str] = None) -> list[SubtitleAsset]:
    """
    Try to obtain subtitles in priority order:
    1) Use existing SubtitleAssets if present.
    2) Extract embedded subtitles.
    3) Locate sidecar subtitles.
    4) Download from OpenSubtitles.
    """
    existing = list(media_item.subtitles.all())
    if existing:
        return existing

    embedded = _extract_embedded_subtitles_for_media_item(media_item, language=language)
    if embedded:
        return embedded

    sidecar = _find_sidecar_subtitles(media_item, language=language)
    if sidecar:
        return sidecar

    try:
        return download_subtitles_for_media_item(media_item, language=language)
    except RuntimeError as exc:
        logger.debug("Unable to download subtitles: %s", exc)
        return []
