"""Django test runner for the full Dispatcharr backend suite."""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.test.runner import DiscoverRunner


def iter_default_test_labels() -> list[str]:
    """Return dotted module paths for every backend test module."""
    base = Path(settings.BASE_DIR)
    labels: list[str] = []
    seen: set[str] = set()

    for root in (base / "apps", base / "core", base / "tests"):
        if not root.is_dir():
            continue
        for test_file in sorted(root.rglob("test_*.py")):
            rel = test_file.relative_to(base).with_suffix("")
            label = ".".join(rel.parts)
            if label in seen:
                continue
            seen.add(label)
            labels.append(label)

    return labels


class DispatcharrDiscoverRunner(DiscoverRunner):
    """Run the full backend suite when ``manage.py test`` is invoked with no labels."""

    def __init__(self, **kwargs):
        if kwargs.get("top_level") is None:
            kwargs["top_level"] = str(Path(settings.BASE_DIR))
        super().__init__(**kwargs)

    def build_suite(self, test_labels=None, extra_tests=None, **kwargs):
        if not test_labels:
            test_labels = iter_default_test_labels()
        return super().build_suite(test_labels, extra_tests=extra_tests, **kwargs)
