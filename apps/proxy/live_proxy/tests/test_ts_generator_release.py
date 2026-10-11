import time
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

CHANNEL_ID = "11111111-2222-3333-4444-555555555555"


def make_generator():
    from apps.proxy.live_proxy.output.ts.generator import StreamGenerator

    generator = StreamGenerator.__new__(StreamGenerator)
    generator.channel_id = CHANNEL_ID
    generator.channel_name = "Channel"
    generator.client_id = "client_1"
    generator.client_ip = "127.0.0.1"
    generator.client_user_agent = "test"
    generator.user = None
    generator.bytes_sent = 0
    generator.stream_start_time = time.time()
    return generator


def make_proxy_server(total_clients):
    client_manager = MagicMock()
    client_manager.clients = {}
    client_manager.get_client_count.return_value = 0
    client_manager.get_total_client_count.return_value = total_clients
    proxy_server = MagicMock()
    proxy_server.client_managers = {CHANNEL_ID: client_manager}
    return proxy_server


class LastClientReleasesStreamTests(SimpleTestCase):
    def cleanup(self, total_clients, shutdown_delay):
        generator = make_generator()
        module = "apps.proxy.live_proxy.output.ts.generator"
        with patch(f"{module}.ProxyServer.get_instance", return_value=make_proxy_server(total_clients)), \
                patch(f"{module}.ConfigHelper.channel_shutdown_delay", return_value=shutdown_delay), \
                patch(f"{module}.log_system_event"), \
                patch(f"{module}.logger") as logger, \
                patch("apps.proxy.live_proxy.url_utils.release_worker_stream", return_value=True) as release:
            generator._cleanup()
        return release, logger

    def test_last_client_releases_the_stream_without_a_shutdown_delay(self):
        release, logger = self.cleanup(total_clients=1, shutdown_delay=0)
        release.assert_called_once_with(CHANNEL_ID)
        logger.error.assert_not_called()

    def test_a_remaining_client_keeps_the_stream(self):
        release, _ = self.cleanup(total_clients=2, shutdown_delay=0)
        release.assert_not_called()

    def test_a_shutdown_delay_leaves_the_release_to_the_coordinated_stop(self):
        release, _ = self.cleanup(total_clients=1, shutdown_delay=5)
        release.assert_not_called()
