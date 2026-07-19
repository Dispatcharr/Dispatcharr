#!/usr/bin/env python3
"""Map changed repository paths to Django test package labels for CI.

Loads ``dispatcharr/test_discovery.py`` by file path so this script does not
import the ``dispatcharr`` package (which eagerly loads Celery). The label step
runs on the bare runner Python before the app venv exists.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_test_discovery():
    path = REPO_ROOT / "dispatcharr" / "test_discovery.py"
    spec = importlib.util.spec_from_file_location(
        "dispatcharr_test_discovery",
        path,
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load test discovery module from {path}")
    module = importlib.util.module_from_spec(spec)
    # Register before exec so dataclasses/typing edge cases that re-import
    # the module name still resolve.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_test_discovery = _load_test_discovery()
labels_for_changed_paths = _test_discovery.labels_for_changed_paths


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
