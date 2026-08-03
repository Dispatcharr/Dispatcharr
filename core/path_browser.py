from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.exceptions import ValidationError


@dataclass(frozen=True)
class DirectoryBrowserScope:
    name: str
    label: str
    setting_name: str
    configuration_hint: str = ""

    @property
    def roots(self) -> tuple[Path, ...]:
        values = getattr(settings, self.setting_name, ()) or ()
        if isinstance(values, str):
            values = [
                value for value in values.split(os.pathsep) if value.strip()
            ]
        return tuple(
            Path(str(value).strip()).expanduser().resolve(strict=False)
            for value in values
            if str(value).strip()
        )


def _configured_scopes() -> dict[str, DirectoryBrowserScope]:
    configured = getattr(settings, "SAFE_DIRECTORY_BROWSER_SCOPES", {}) or {}
    scopes: dict[str, DirectoryBrowserScope] = {}
    for name, values in configured.items():
        if not isinstance(values, dict) or not values.get("setting_name"):
            continue
        scopes[name] = DirectoryBrowserScope(
            name=name,
            label=str(values.get("label") or name),
            setting_name=str(values["setting_name"]),
            configuration_hint=str(values.get("configuration_hint") or ""),
        )
    return scopes


def get_directory_browser_scope(name: str) -> DirectoryBrowserScope:
    try:
        return _configured_scopes()[name]
    except KeyError as exc:
        raise ValidationError(
            "The requested directory browser scope is not available."
        ) from exc


def _is_beneath(path: Path, roots: tuple[Path, ...]) -> bool:
    return any(path == root or path.is_relative_to(root) for root in roots)


def _resolve_directory(value: str, roots: tuple[Path, ...]) -> Path:
    raw = str(value or "").strip()
    if not raw:
        raise ValidationError("A directory path is required.")
    if not roots:
        raise ValidationError(
            "No allowed directories are configured for this browser."
        )
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        raise ValidationError(
            "The directory path must be absolute inside the container."
        )
    try:
        resolved = candidate.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ValidationError("The directory does not exist or cannot be resolved.") from exc
    if not _is_beneath(resolved, roots):
        raise ValidationError(
            "The resolved directory is outside the configured allowed roots."
        )
    if not resolved.is_dir():
        raise ValidationError("The selected path is not a directory.")
    return resolved


def browse_directories(scope_name: str, path: str = "") -> dict[str, Any]:
    """
    Browse directories inside a server-owned, named root scope.

    Callers select only the scope name. Roots always come from server settings;
    a request can never supply or broaden the allowed roots.
    """
    scope = get_directory_browser_scope(scope_name)
    roots = scope.roots
    response: dict[str, Any] = {
        "scope": scope.name,
        "label": scope.label,
        "configured": bool(roots),
        "configuration_hint": scope.configuration_hint,
    }

    if not str(path or "").strip():
        response["roots"] = [
            {
                "name": root.name or str(root),
                "path": str(root),
                "available": root.is_dir(),
                "readable": root.is_dir() and os.access(root, os.R_OK | os.X_OK),
            }
            for root in roots
        ]
        return response

    current = _resolve_directory(path, roots)
    current_root = max(
        (root for root in roots if _is_beneath(current, (root,))),
        key=lambda root: len(root.parts),
    )
    entries = []
    try:
        with os.scandir(current) as iterator:
            for entry in iterator:
                try:
                    if not entry.is_dir(follow_symlinks=True):
                        continue
                    resolved = _resolve_directory(entry.path, roots)
                except (OSError, ValidationError):
                    # This also omits symlinks that resolve outside the scope.
                    continue
                entries.append(
                    {
                        "name": entry.name,
                        "path": str(resolved),
                        "symlink": entry.is_symlink(),
                    }
                )
    except OSError as exc:
        raise PermissionError("The directory is not accessible.") from exc

    entries.sort(key=lambda item: item["name"].casefold())
    parent = current.parent.resolve(strict=False)
    response.update(
        {
            "path": str(current),
            "root": {
                "name": current_root.name or str(current_root),
                "path": str(current_root),
            },
            "parent": (
                str(parent)
                if parent != current and _is_beneath(parent, roots)
                else None
            ),
            "entries": entries,
        }
    )
    return response
