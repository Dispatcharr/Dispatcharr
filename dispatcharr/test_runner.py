"""Django test runner for the full Dispatcharr backend suite."""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.test.runner import DiscoverRunner

from dispatcharr.test_discovery import iter_test_package_labels


class DispatcharrDiscoverRunner(DiscoverRunner):
    """Run the full backend suite when ``manage.py test`` is invoked with no labels."""

    def __init__(self, **kwargs):
        if kwargs.get("top_level") is None:
            kwargs["top_level"] = str(Path(settings.BASE_DIR))
        super().__init__(**kwargs)

    def build_suite(self, test_labels=None, extra_tests=None, **kwargs):
        if not test_labels:
            test_labels = iter_test_package_labels(base=Path(settings.BASE_DIR))
        return super().build_suite(test_labels, extra_tests=extra_tests, **kwargs)
