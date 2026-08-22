"""The on_after_configure logging hook must run clean on worker start."""

from django.test import SimpleTestCase

from dispatcharr.celery import setup_celery_logging


class CeleryLoggingSetupTests(SimpleTestCase):
    def test_setup_runs_without_raising(self):
        # A loop variable shadowing the module logger once raised
        # UnboundLocalError here on every worker start, silently skipping
        # the noisy-celery-logger filters.
        setup_celery_logging()
