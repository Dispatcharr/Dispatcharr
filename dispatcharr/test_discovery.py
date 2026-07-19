"""Discover backend test packages from INSTALLED_APPS and changed paths."""

from __future__ import annotations

import ast
from functools import lru_cache
from pathlib import Path, PurePosixPath

# Changes here rerun every installed test package.
_SHARED_PATH_PREFIXES: tuple[str, ...] = (
    "dispatcharr/",
    "pyproject.toml",
    "manage.py",
    "version.py",
    "scripts/ci_backend_test_labels.py",
    "scripts/ci_bootstrap_backend.sh",
    ".github/workflows/backend-tests.yml",
)

# No test package of its own; route to these installed app tests instead.
_PATH_ALIASES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("apps/api/", ("__all__",)),
    ("apps/vod/", ("apps.output",)),
    ("apps/hdhr/", ("apps.output", "apps.channels")),
)


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


@lru_cache(maxsize=1)
def parse_installed_app_names(settings_path: str | None = None) -> tuple[str, ...]:
    """Read project app names from INSTALLED_APPS without importing Django."""
    path = Path(settings_path) if settings_path else repo_root() / "dispatcharr" / "settings.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == "INSTALLED_APPS":
                entries = ast.literal_eval(node.value)
                names: list[str] = []
                for entry in entries:
                    name = _app_name_from_installed_entry(entry)
                    if name:
                        names.append(name)
                return tuple(names)
    raise RuntimeError(f"INSTALLED_APPS not found in {path}")


def _app_name_from_installed_entry(entry: str) -> str | None:
    if ".apps." in entry and entry.endswith("Config"):
        name = entry.rsplit(".apps.", 1)[0]
    else:
        name = entry
    if name.startswith("apps.") or name == "core":
        return name
    return None


def _label_for_tests_dir(tests_dir: Path, base: Path) -> str | None:
    if not tests_dir.is_dir() or not any(tests_dir.glob("test_*.py")):
        return None
    package_dir = tests_dir.parent
    try:
        rel = package_dir.relative_to(base)
    except ValueError:
        return None
    return ".".join(rel.parts) + ".tests"


def _discover_test_labels_under_app(app_name: str, base: Path) -> list[str]:
    """Find test packages anywhere under an installed app's directory tree."""
    app_dir = base.joinpath(*app_name.split("."))
    if not app_dir.is_dir():
        return []

    labels: list[str] = []
    seen: set[str] = set()
    for tests_dir in app_dir.rglob("tests"):
        label = _label_for_tests_dir(tests_dir, base)
        if label and label not in seen:
            seen.add(label)
            labels.append(label)
    return labels


def iter_test_package_labels(
    *,
    base: Path | None = None,
    settings_path: str | None = None,
) -> list[str]:
    """Return dotted test package labels for installed apps that have tests/."""
    base = base or repo_root()
    labels: list[str] = []
    seen: set[str] = set()

    for app_name in parse_installed_app_names(settings_path):
        for label in _discover_test_labels_under_app(app_name, base):
            if label not in seen:
                seen.add(label)
                labels.append(label)

    root_tests = base / "tests"
    if root_tests.is_dir() and any(root_tests.glob("test_*.py")):
        labels.append("tests")

    return sorted(labels)


def _filesystem_prefix_for_app(app_name: str) -> str:
    return app_name.replace(".", "/") + "/"


def _label_to_filesystem_prefix(label: str) -> str:
    if label == "tests":
        return "tests/"
    return label.removesuffix(".tests").replace(".", "/") + "/"


def _labels_under_installed_app_tree(
    path: str,
    available: set[str],
    settings_path: str | None,
) -> set[str]:
    """Include every test package under the installed app that owns this path."""
    app_prefixes = sorted(
        (
            (_filesystem_prefix_for_app(name), name)
            for name in parse_installed_app_names(settings_path)
        ),
        key=lambda item: len(item[0]),
        reverse=True,
    )

    for app_prefix, _ in app_prefixes:
        if path == app_prefix.rstrip("/") or path.startswith(app_prefix):
            return {
                label
                for label in available
                if _label_to_filesystem_prefix(label).startswith(app_prefix)
            }
    return set()


def _normalize_path(path: str) -> str:
    return PurePosixPath(path.strip().replace("\\", "/")).as_posix()


def _resolve_alias_labels(alias_apps: tuple[str, ...], available: set[str]) -> set[str]:
    labels: set[str] = set()
    for app_name in alias_apps:
        if app_name == "__all__":
            labels.update(available)
            continue
        label = f"{app_name}.tests"
        if label in available:
            labels.add(label)
    return labels


def labels_for_changed_paths(
    paths: list[str],
    *,
    full_suite: bool = False,
    base: Path | None = None,
    settings_path: str | None = None,
) -> list[str]:
    """Map changed repository paths to Django test package labels."""
    all_labels = iter_test_package_labels(base=base, settings_path=settings_path)
    available = set(all_labels)

    if full_suite or not paths:
        return all_labels

    prefix_map = {
        _label_to_filesystem_prefix(label): label for label in available
    }
    sorted_prefixes = sorted(prefix_map, key=len, reverse=True)

    selected: set[str] = set()
    for raw in paths:
        path = _normalize_path(raw)
        if not path:
            continue
        if any(path == prefix.rstrip("/") or path.startswith(prefix) for prefix in _SHARED_PATH_PREFIXES):
            return all_labels
        for alias_prefix, alias_apps in _PATH_ALIASES:
            if path.startswith(alias_prefix):
                selected.update(_resolve_alias_labels(alias_apps, available))
                break
        else:
            matched = False
            for prefix in sorted_prefixes:
                if path.startswith(prefix):
                    selected.add(prefix_map[prefix])
                    matched = True
                    break
            if not matched:
                selected.update(
                    _labels_under_installed_app_tree(path, available, settings_path)
                )

    return sorted(selected)
