"""celery_worker_max management command: prints the configured autoscale
ceiling for the default Celery worker."""

from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase


class CeleryWorkerMaxTests(TestCase):
    def _run(self):
        out = StringIO()
        call_command("celery_worker_max", stdout=out)
        return out.getvalue().strip()

    def test_default_value(self):
        self.assertEqual(self._run(), "8")

    def test_custom_value_from_core_settings(self):
        with patch("core.models.CoreSettings.get_celery_max_workers", return_value=12):
            self.assertEqual(self._run(), "12")
