from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from apps.plugins.service_health import get_service_health, publish_service_health


class ServiceHealthTests(SimpleTestCase):
    def test_publish_checks_lease_owner(self):
        client = MagicMock()
        publish_service_health(client, "example", "worker", "running", 0, 60)
        args = client.eval.call_args.args
        self.assertIn("redis.call('GET', KEYS[1]) ~= ARGV[1]", args[0])
        self.assertEqual(args[2:5], ("plugin:example:leader", "plugin:example:service_health", "worker"))

    def test_missing_health_is_unknown(self):
        client = MagicMock()
        client.get.return_value = None
        with patch("core.utils.RedisClient.get_client", return_value=client):
            self.assertEqual(get_service_health("example"), {"state": "unknown"})
