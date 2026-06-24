from unittest.mock import patch

from django.test import SimpleTestCase

from dispatcharr.db.process_label import get_process_role


class ProcessLabelTests(SimpleTestCase):
    def test_celery_worker_not_labeled_as_uwsgi(self):
        role = get_process_role(
            ["/dispatcharrpy/bin/celery", "-A", "dispatcharr", "worker"]
        )
        self.assertEqual(role, "celery-worker")

    def test_uwsgi_labeled_from_argv(self):
        role = get_process_role(["/dispatcharrpy/bin/uwsgi", "--ini", "/app/docker/uwsgi.ini"])
        self.assertEqual(role, "uwsgi")

    def test_uwsgi_labeled_when_worker_module_present(self):
        fake_uwsgi = type("uwsgi", (), {"worker_id": staticmethod(lambda: 2)})()
        with patch.dict("sys.modules", {"uwsgi": fake_uwsgi}):
            role = get_process_role(["/dispatcharrpy/bin/python", "-c", "pass"])
        self.assertEqual(role, "uwsgi")

    def test_uwsgi_master_not_labeled_as_uwsgi(self):
        fake_uwsgi = type("uwsgi", (), {"worker_id": staticmethod(lambda: 0)})()
        with patch.dict("sys.modules", {"uwsgi": fake_uwsgi}):
            role = get_process_role(["/dispatcharrpy/bin/python", "-c", "pass"])
        self.assertEqual(role, "django")
