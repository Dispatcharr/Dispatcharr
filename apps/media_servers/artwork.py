from __future__ import annotations

import logging
from pathlib import Path

from django.conf import settings

from apps.vod.models import VODLogo


logger = logging.getLogger(__name__)


def media_library_artwork_path(value: str | None) -> Path | None:
    """Return a safely jailed cached-artwork path, if this logo is ours."""
    raw = str(value or "").strip()
    if not raw or raw.startswith(("http://", "https://", "/api/")):
        return None
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        return None
    root = Path(settings.MEDIA_LIBRARY_ARTWORK_ROOT).expanduser().resolve(
        strict=False
    )
    resolved = candidate.resolve(strict=False)
    if resolved != root and not resolved.is_relative_to(root):
        return None
    return candidate


def remove_media_library_artwork_file(value: str | None) -> None:
    path = media_library_artwork_path(value)
    if path is None:
        return
    try:
        path.unlink(missing_ok=True)
    except OSError:
        logger.warning("Unable to remove unused Media Library artwork %s", path)


def delete_media_library_logo_if_unused(logo_id: int | None) -> None:
    if not logo_id:
        return
    logo = VODLogo.objects.filter(id=logo_id).first()
    if not logo or media_library_artwork_path(logo.url) is None:
        return
    if logo.movie.exists() or logo.series.exists():
        return
    logo.delete()
