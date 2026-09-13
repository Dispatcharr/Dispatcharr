"""The on_after_configure logging hook must run clean on worker start."""

from django.test import SimpleTestCase

from dispatcharr.celery import setup_celery_logging


class CeleryLoggingSetupTests(SimpleTestCase):
    def test_setup_runs_without_raising(self):
        setup_celery_logging()
