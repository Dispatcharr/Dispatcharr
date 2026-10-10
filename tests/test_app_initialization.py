import sys
import types
from unittest.mock import patch

from django.test import SimpleTestCase

from dispatcharr.app_initialization import should_skip_initialization


def _uwsgi(worker_id):
    return types.SimpleNamespace(worker_id=lambda: worker_id)


class ShouldSkipInitializationTests(SimpleTestCase):
    def test_first_uwsgi_worker_initializes(self):
        with patch.dict(sys.modules, {"uwsgi": _uwsgi(1)}):
            self.assertFalse(should_skip_initialization())

    def test_other_uwsgi_workers_skip(self):
        with patch.dict(sys.modules, {"uwsgi": _uwsgi(2)}):
            self.assertTrue(should_skip_initialization())

    def test_uwsgi_master_that_loads_the_app_initializes(self):
        with patch.dict(sys.modules, {"uwsgi": _uwsgi(0)}):
            self.assertFalse(should_skip_initialization())

    def test_celery_worker_skips_whatever_its_queue(self):
        argv = ["/dispatcharrpy/bin/celery", "--quiet", "-A", "dispatcharr", "worker", "-Q", "dvr"]
        with patch.dict(sys.modules, {"uwsgi": None}), patch.object(sys, "argv", argv):
            self.assertTrue(should_skip_initialization())

    def test_migrate_skips(self):
        with patch.dict(sys.modules, {"uwsgi": None}), patch.object(sys, "argv", ["manage.py", "migrate"]):
            self.assertTrue(should_skip_initialization())

    @patch("dispatcharr.app_initialization._is_worker_process", return_value=False)
    def test_runserver_initializes(self, _):
        with patch.dict(sys.modules, {"uwsgi": None}), patch.object(sys, "argv", ["manage.py", "runserver"]):
            self.assertFalse(should_skip_initialization())
