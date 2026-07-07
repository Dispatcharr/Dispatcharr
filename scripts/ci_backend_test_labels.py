#!/usr/bin/env python3
"""Map changed repository paths to Django test package labels for CI."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from dispatcharr.test_discovery import labels_for_changed_paths  # noqa: E402


def _read_paths(argv: list[str]) -> list[str]:
    if argv:
        return argv
    if not sys.stdin.isatty():
        return [line for line in sys.stdin.read().splitlines() if line.strip()]
    return []


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    full_suite = os.environ.get("FULL_SUITE", "").lower() in {"1", "true", "yes"}
    paths = _read_paths(argv)
    labels = labels_for_changed_paths(paths, full_suite=full_suite, base=REPO_ROOT)
    print(json.dumps(labels))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
