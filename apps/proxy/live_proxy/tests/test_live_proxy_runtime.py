"""Live-proxy runtime role: full worker vs Redis client-only."""

from unittest.mock import patch

from django.test import SimpleTestCase

from apps.proxy.live_proxy.runtime import (
    should_run_live_proxy_runtime,
    start_live_proxy_if_stream_worker,
)
from apps.proxy.live_proxy.server import ProxyServer


class LiveProxyRuntimeRoleTests(SimpleTestCase):
    def test_uwsgi_runs_full_runtime(self):
        self.assertTrue(
            should_run_live_proxy_runtime(
                ["/dispatcharrpy/bin/uwsgi", "--ini", "/app/docker/uwsgi.ini"]
            )
        )

    def test_celery_does_not_run_full_runtime(self):
        self.assertFalse(
            should_run_live_proxy_runtime(
                ["/dispatcharrpy/bin/celery", "-A", "dispatcharr", "worker"]
            )
        )
        self.assertFalse(
            should_run_live_proxy_runtime(
                ["/dispatcharrpy/bin/celery", "-A", "dispatcharr", "beat"]
            )
        )
        self.assertFalse(
            should_run_live_proxy_runtime(
                [
                    "/dispatcharrpy/bin/celery",
                    "-A",
                    "dispatcharr",
                    "worker",
                    "-Q",
                    "dvr",
                ]
            )
        )

    def test_daphne_does_not_run_full_runtime(self):
        self.assertFalse(
            should_run_live_proxy_runtime(
                ["/dispatcharrpy/bin/daphne", "-b", "0.0.0.0", "-p", "8001"]
            )
        )

    def test_manage_does_not_run_full_runtime(self):
        self.assertFalse(should_run_live_proxy_runtime(["manage.py", "migrate"]))

    def test_gunicorn_runs_full_runtime(self):
        self.assertTrue(
            should_run_live_proxy_runtime(
                ["/dispatcharrpy/bin/gunicorn", "dispatcharr.wsgi:application"]
            )
        )

    def test_start_skips_non_runtime_processes(self):
        with patch(
            "apps.proxy.live_proxy.runtime.should_run_live_proxy_runtime",
            return_value=False,
        ):
            with patch("apps.proxy.live_proxy.server.ProxyServer.get_instance") as get_inst:
                self.assertIsNone(start_live_proxy_if_stream_worker())
                get_inst.assert_not_called()

    def test_start_calls_get_instance_for_runtime(self):
        sentinel = object()
        with patch(
            "apps.proxy.live_proxy.runtime.should_run_live_proxy_runtime",
            return_value=True,
        ):
            with patch(
                "apps.proxy.live_proxy.server.ProxyServer.get_instance",
                return_value=sentinel,
            ) as get_inst:
                self.assertIs(start_live_proxy_if_stream_worker(), sentinel)
                get_inst.assert_called_once()


class ProxyServerClientOnlyModeTests(SimpleTestCase):
    def tearDown(self):
        ProxyServer._instance = None

    def test_client_only_skips_background_threads(self):
        with patch(
            "apps.proxy.live_proxy.runtime.should_run_live_proxy_runtime",
            return_value=False,
        ), patch(
            "apps.proxy.live_proxy.server.RedisClient.get_client",
            return_value=None,
        ), patch.object(
            ProxyServer, "_setup_redis_connection"
        ), patch.object(
            ProxyServer, "_start_cleanup_thread"
        ) as cleanup, patch.object(
            ProxyServer, "_start_event_listener"
        ) as listener:
            # Bypass get_instance sentinel path; construct directly.
            server = ProxyServer.__new__(ProxyServer)
            ProxyServer.__init__(server)
            cleanup.assert_not_called()
            listener.assert_not_called()

    def test_runtime_starts_background_threads(self):
        with patch(
            "apps.proxy.live_proxy.runtime.should_run_live_proxy_runtime",
            return_value=True,
        ), patch(
            "apps.proxy.live_proxy.server.RedisClient.get_client",
            return_value=None,
        ), patch.object(
            ProxyServer, "_setup_redis_connection"
        ), patch.object(
            ProxyServer, "_start_cleanup_thread"
        ) as cleanup, patch.object(
            ProxyServer, "_start_event_listener"
        ) as listener:
            server = ProxyServer.__new__(ProxyServer)
            ProxyServer.__init__(server)
            cleanup.assert_called_once()
            listener.assert_called_once()
