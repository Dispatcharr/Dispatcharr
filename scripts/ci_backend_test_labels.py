#!/usr/bin/env python3
"""Map changed repository paths to Django test package labels for CI."""

from __future__ import annotations

import json
import os
import sys
from pathlib import PurePosixPath

# Keep in sync with dispatcharr.test_runner package discovery.
ALL_LABELS: tuple[str, ...] = (
    "apps.accounts.tests",
    "apps.backups.tests",
    "apps.channels.tests",
    "apps.connect.tests",
    "apps.dashboard.tests",
    "apps.epg.tests",
    "apps.m3u.tests",
    "apps.output.tests",
    "apps.plugins.tests",
    "apps.timeshift.tests",
    "apps.proxy.live_proxy.tests",
    "apps.proxy.vod_proxy.tests",
    "core.tests",
    "tests",
)

# Longest-prefix wins; order matters for overlapping rules.
_PATH_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("apps/channels/", ("apps.channels.tests",)),
    ("apps/epg/", ("apps.epg.tests",)),
    ("apps/m3u/", ("apps.m3u.tests",)),
    ("apps/proxy/", ("apps.proxy.live_proxy.tests", "apps.proxy.vod_proxy.tests")),
    ("apps/connect/", ("apps.connect.tests",)),
    ("apps/output/", ("apps.output.tests",)),
    ("apps/accounts/", ("apps.accounts.tests",)),
    ("apps/backups/", ("apps.backups.tests",)),
    ("apps/dashboard/", ("apps.dashboard.tests",)),
    ("apps/plugins/", ("apps.plugins.tests",)),
    ("apps/timeshift/", ("apps.timeshift.tests",)),
    ("apps/vod/", ("apps.output.tests",)),
    ("apps/hdhr/", ("apps.output.tests", "apps.channels.tests")),
    ("apps/api/", ALL_LABELS),
    ("core/", ("core.tests", "tests")),
    ("tests/", ("tests",)),
)

_SHARED_PREFIXES: tuple[str, ...] = (
    "dispatcharr/",
    "pyproject.toml",
    "manage.py",
    "version.py",
    "scripts/ci_backend_test_labels.py",
    "scripts/ci_bootstrap_backend.sh",
    ".github/workflows/backend-tests.yml",
)


def _normalize(path: str) -> str:
    return PurePosixPath(path.strip().replace("\\", "/")).as_posix()


def labels_for_paths(paths: list[str], *, full_suite: bool = False) -> list[str]:
    if full_suite:
        return list(ALL_LABELS)

    labels: set[str] = set()
    for raw in paths:
        path = _normalize(raw)
        if not path:
            continue
        if any(path == prefix.rstrip("/") or path.startswith(prefix) for prefix in _SHARED_PREFIXES):
            return list(ALL_LABELS)
        for prefix, group_labels in _PATH_RULES:
            if path.startswith(prefix):
                labels.update(group_labels)
                break

    return sorted(labels)


def _read_paths(argv: list[str]) -> list[str]:
    if argv:
        return argv
    if not sys.stdin.isatty():
        return [line for line in sys.stdin.read().splitlines() if line.strip()]
    return []


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    full_suite = os.environ.get("FULL_SUITE", "").lower() in {"1", "true", "yes"}
    if full_suite:
        print(json.dumps(list(ALL_LABELS)))
        return 0
    paths = _read_paths(argv)
    labels = labels_for_paths(paths, full_suite=False)
    print(json.dumps(labels))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
