import json
import os
import ssl
import subprocess
import sys
from unittest import TestCase
from unittest.mock import patch

from channels_redis.core import RedisChannelLayer

from dispatcharr.settings import CHANNEL_LAYERS


class ChannelsRedisSettingsTests(TestCase):
    def test_configured_pool_disables_socket_read_timeout(self):
        config = CHANNEL_LAYERS["default"]["CONFIG"]
        host = config["hosts"][0]
        self.assertIsNone(host["socket_timeout"])

        pool = RedisChannelLayer(**config).create_pool(0)
        # Explicit URL query parameters take precedence in redis-py.
        if "socket_timeout=" not in host["address"]:
            self.assertIsNone(pool.connection_kwargs["socket_timeout"])

    def pool_settings(self, **overrides):
        env = {
            k: v for k, v in os.environ.items()
            if not k.startswith("REDIS_")
            and k not in ("CELERY_BROKER_URL", "CELERY_RESULT_BACKEND")
        }
        env.update(overrides)
        code = """
import json
from channels_redis.core import RedisChannelLayer
from dispatcharr.settings import CHANNEL_LAYERS
config = CHANNEL_LAYERS['default']['CONFIG']
host = config['hosts'][0]
pool = RedisChannelLayer(**config).create_pool(0)
kwargs = {k: pool.connection_kwargs[k] for k in ('socket_timeout', 'ssl_cert_reqs') if k in pool.connection_kwargs}
print(json.dumps({'host': host, 'kwargs': kwargs}))
"""
        result = subprocess.run(
            [sys.executable, "-c", code], env=env, capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout.splitlines()[-1])

    def test_plain_and_url_configs_disable_read_timeout(self):
        for overrides in (
            {},
            {"REDIS_URL": "redis://localhost:6379/2"},
            {"REDIS_URL": "unix:///var/run/redis/redis.sock?db=2"},
        ):
            with self.subTest(overrides=overrides):
                settings = self.pool_settings(**overrides)
                self.assertIsNone(settings["kwargs"]["socket_timeout"])

    def test_discrete_tls_options_are_preserved(self):
        with patch.dict(os.environ, {
            "CELERY_BROKER_URL": "redis://localhost:6379/0",
            "CELERY_RESULT_BACKEND": "redis://localhost:6379/0",
        }):
            settings = self.pool_settings(REDIS_SSL="true", REDIS_SSL_VERIFY="false")
        self.assertTrue(settings["host"]["address"].startswith("rediss://"))
        self.assertNotIn("ssl", settings["host"])
        self.assertEqual(settings["kwargs"]["ssl_cert_reqs"], ssl.CERT_NONE)
        self.assertIsNone(settings["kwargs"]["socket_timeout"])

    def test_url_options_take_precedence(self):
        settings = self.pool_settings(
            REDIS_SSL="true",
            REDIS_URL="rediss://localhost:6379/0?ssl_cert_reqs=none&socket_timeout=30",
        )
        self.assertEqual(settings["kwargs"]["ssl_cert_reqs"], "none")
        self.assertEqual(settings["kwargs"]["socket_timeout"], 30)
