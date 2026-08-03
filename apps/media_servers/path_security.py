from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable

from django.conf import settings
from django.core.exceptions import ValidationError


def _configured_roots(setting_name: str) -> tuple[Path, ...]:
    values = getattr(settings, setting_name, ()) or ()
    if isinstance(values, str):
        values = [entry for entry in values.split(os.pathsep) if entry.strip()]
    roots: list[Path] = []
    for value in values:
        raw = str(value or "").strip()
        if not raw:
            continue
        roots.append(Path(raw).expanduser().resolve(strict=False))
    return tuple(roots)


def import_roots() -> tuple[Path, ...]:
    return _configured_roots("MEDIA_LIBRARY_IMPORT_ROOTS")


def export_roots() -> tuple[Path, ...]:
    return _configured_roots("MEDIA_LIBRARY_EXPORT_ROOTS")


def artwork_root() -> Path:
    return Path(
        getattr(
            settings,
            "MEDIA_LIBRARY_ARTWORK_ROOT",
            "/data/logos/media-library",
        )
    ).expanduser().resolve(strict=False)


def is_beneath(path: Path, roots: Iterable[Path]) -> bool:
    return any(path == root or path.is_relative_to(root) for root in roots)


def resolve_allowed_path(
    value: str,
    *,
    roots: Iterable[Path],
    must_exist: bool = False,
    require_directory: bool = False,
) -> Path:
    raw = str(value or "").strip()
    if not raw:
        raise ValidationError("A path is required.")
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        raise ValidationError("The path must be absolute inside the Dispatcharr container.")
    try:
        resolved = candidate.resolve(strict=must_exist)
    except (OSError, RuntimeError) as exc:
        raise ValidationError(f"Unable to resolve path: {exc}") from exc
    configured = tuple(roots)
    if not configured:
        raise ValidationError("No allowed media roots are configured.")
    if not is_beneath(resolved, configured):
        raise ValidationError("The resolved path is outside the configured allowed roots.")
    if require_directory and resolved.exists() and not resolved.is_dir():
        raise ValidationError("The path must be a directory.")
    return resolved


def resolve_import_path(
    value: str,
    *,
    must_exist: bool = False,
    require_directory: bool = False,
) -> Path:
    return resolve_allowed_path(
        value,
        roots=import_roots(),
        must_exist=must_exist,
        require_directory=require_directory,
    )


def resolve_export_path(
    value: str,
    *,
    must_exist: bool = False,
    require_directory: bool = False,
) -> Path:
    return resolve_allowed_path(
        value,
        roots=export_roots(),
        must_exist=must_exist,
        require_directory=require_directory,
    )


def paths_overlap(left: str | Path, right: str | Path) -> bool:
    left_path = Path(left).expanduser().resolve(strict=False)
    right_path = Path(right).expanduser().resolve(strict=False)
    return (
        left_path == right_path
        or left_path.is_relative_to(right_path)
        or right_path.is_relative_to(left_path)
    )


def validate_no_import_export_overlap(
    output_root: Path,
    import_paths: Iterable[str],
    other_output_paths: Iterable[str],
) -> None:
    for raw in import_paths:
        if raw and paths_overlap(output_root, raw):
            raise ValidationError("Export paths may not overlap local import locations.")
    for raw in other_output_paths:
        if raw and paths_overlap(output_root, raw):
            raise ValidationError("Export target paths may not overlap.")


def client_ip(request) -> str:
    # Match the existing STREAMS network gate. Reverse proxies must own and
    # overwrite X-Real-IP; clients must not be able to inject it directly.
    return request.META.get("HTTP_X_REAL_IP") or request.META.get("REMOTE_ADDR") or ""

