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
    allow_create: bool = False
    selection_mode: str = "directory"
    allowed_extensions: tuple[str, ...] = ()

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

    @property
    def selects_files(self) -> bool:
        return self.selection_mode == "file"

    def allows_file(self, path: Path) -> bool:
        return not self.allowed_extensions or path.suffix.lower() in (
            extension.lower() for extension in self.allowed_extensions
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
            allow_create=bool(values.get("allow_create", False)),
            selection_mode=(
                "file" if values.get("selection_mode") == "file" else "directory"
            ),
            allowed_extensions=tuple(
                str(extension).strip()
                for extension in (values.get("allowed_extensions") or ())
                if str(extension).strip()
            ),
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


def _resolve_file(
    value: str,
    roots: tuple[Path, ...],
    scope: DirectoryBrowserScope,
) -> Path:
    raw = str(value or "").strip()
    if not raw:
        raise ValidationError("A file path is required.")
    if not roots:
        raise ValidationError(
            "No allowed directories are configured for this browser."
        )
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        raise ValidationError(
            "The file path must be absolute inside the container."
        )
    try:
        resolved = candidate.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ValidationError("The file does not exist or cannot be resolved.") from exc
    if not _is_beneath(resolved, roots):
        raise ValidationError(
            "The resolved file is outside the configured allowed roots."
        )
    if not resolved.is_file():
        raise ValidationError("The selected path is not a file.")
    if not scope.allows_file(resolved):
        raise ValidationError("The selected file type is not allowed.")
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
        "allows_create": scope.allow_create,
        "can_create": False,
        "selection_mode": scope.selection_mode,
        "selected_path": None,
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

    selected_path = None
    if scope.selects_files:
        candidate = Path(str(path).strip()).expanduser()
        try:
            resolved_candidate = candidate.resolve(strict=True)
        except (OSError, RuntimeError):
            resolved_candidate = None
        if resolved_candidate is not None and resolved_candidate.is_file():
            selected_file = _resolve_file(str(resolved_candidate), roots, scope)
            selected_path = str(selected_file)
            current = _resolve_directory(str(selected_file.parent), roots)
        else:
            current = _resolve_directory(path, roots)
    else:
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
                    if entry.is_dir(follow_symlinks=True):
                        resolved = _resolve_directory(entry.path, roots)
                        entry_type = "directory"
                    elif scope.selects_files and entry.is_file(
                        follow_symlinks=True
                    ):
                        resolved = _resolve_file(entry.path, roots, scope)
                        entry_type = "file"
                    else:
                        continue
                except (OSError, ValidationError):
                    # This also omits symlinks that resolve outside the scope.
                    continue
                entries.append(
                    {
                        "name": entry.name,
                        "path": str(resolved),
                        "symlink": entry.is_symlink(),
                        "type": entry_type,
                    }
                )
    except OSError as exc:
        raise PermissionError("The directory is not accessible.") from exc

    entries.sort(
        key=lambda item: (
            item["type"] != "directory",
            item["name"].casefold(),
        )
    )
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
            "selected_path": selected_path,
            "can_create": scope.allow_create and os.access(
                current,
                os.W_OK | os.X_OK,
            ),
        }
    )
    return response


def create_directory(
    scope_name: str,
    parent_path: str,
    name: str,
) -> dict[str, str]:
    """Create one directory below a validated path in a writable scope."""
    scope = get_directory_browser_scope(scope_name)
    if not scope.allow_create:
        raise ValidationError(
            "This directory browser scope does not allow folder creation."
        )

    roots = scope.roots
    parent = _resolve_directory(parent_path, roots)
    if not os.access(parent, os.W_OK | os.X_OK):
        raise PermissionError("The current directory is not writable.")

    directory_name = str(name or "").strip()
    if (
        not directory_name
        or directory_name in {".", ".."}
        or "/" in directory_name
        or "\\" in directory_name
        or "\x00" in directory_name
    ):
        raise ValidationError("Enter a valid folder name without path separators.")

    destination = parent / directory_name
    try:
        destination.mkdir(mode=0o755)
    except FileExistsError as exc:
        raise ValidationError("A file or folder with that name already exists.") from exc
    except PermissionError as exc:
        raise PermissionError("The current directory is not writable.") from exc
    except OSError as exc:
        raise ValidationError("The folder could not be created.") from exc

    try:
        resolved = destination.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ValidationError("The created folder could not be resolved.") from exc
    if not _is_beneath(resolved, roots) or not resolved.is_dir():
        raise ValidationError(
            "The created folder is outside the configured allowed roots."
        )

    return {
        "scope": scope.name,
        "name": directory_name,
        "path": str(resolved),
    }
