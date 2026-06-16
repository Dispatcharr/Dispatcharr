from unittest.mock import patch

from django.test import SimpleTestCase

from dispatcharr.db.process_label import get_process_role


class ProcessLabelTests(SimpleTestCase):
    def test_celery_worker_not_labeled_as_uwsgi(self):
        role = get_process_role(
            ["/dispatcharrpy/bin/celery", "-A", "dispatcharr", "worker"]
        )
        self.assertEqual(role, "celery-worker")

    def test_uwsgi_labeled_when_gevent_support(self):
        with patch.dict("os.environ", {"GEVENT_SUPPORT": "True"}):
            role = get_process_role(["uwsgi"])
        self.assertEqual(role, "uwsgi")
