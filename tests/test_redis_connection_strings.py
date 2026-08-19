import os

from core.utils import RedisClient
from django.test import SimpleTestCase
from unittest.mock import patch

UNIVERSAL_KWARGS = {"decode_responses" : False, "health_check_interval" : 15} #retry_on_timeout should technically be part of this, but is sometimes mangled by get_connection_kwargs() into a Retry object
COMMON_TEST_KWARGS = {"host" : "localhost", "port" : 6379, "db" : 0}
COMMON_SOCKET_KWARGS = {"socket_timeout" : 60, "socket_connect_timeout" : 5, "socket_keepalive" : True}

class RedisConnectionStringsTests(SimpleTestCase):

    """
    Tests for various Redis connection schemes.

    Verifies that RedisClient is creating clients correctly based on the REDIS_* env vars
    """

    def setUp(self):

        RedisClient._client = None
        RedisClient._buffer = None
        RedisClient._pubsub_client = None
        RedisClient._netloc = None

    @patch("core.utils.redis.commands.core.CoreCommands.ping")
    def test_redis_url(self, mock_ping):

        """ Tests proper handling of the REDIS_URL variable with redis:// scheme"""

        mock_ping.return_value = True

        EXPECTED_KWARGS_REDIS = COMMON_TEST_KWARGS | {"username" : "user", "db" : 3, "retry_on_timeout" : True} | UNIVERSAL_KWARGS | COMMON_SOCKET_KWARGS

        with patch.dict(os.environ, {"REDIS_URL":"redis://user@localhost:6379/3"}, clear=False):

            client = RedisClient().get_test_client(max_retries = 1)
            self.assertEqual(EXPECTED_KWARGS_REDIS, client.get_connection_kwargs())


    @patch("core.utils.redis.commands.core.CoreCommands.ping")
    def test_unix_url(self, mock_ping):

        """ Tests proper handling of the REDIS_URL variable with unix:// scheme"""

        mock_ping.return_value = True

        EXPECTED_KWARGS_UNIX = {"path" : "/var/run/test.sock", "db" : 7, "retry_on_timeout" : True} | UNIVERSAL_KWARGS

        with patch.dict(os.environ, {"REDIS_URL":"unix:///var/run/test.sock?db=7"}, clear=False):

            client = RedisClient().get_test_client(max_retries = 1)
            self.assertEqual(EXPECTED_KWARGS_UNIX, client.get_connection_kwargs())

    @patch("core.utils.redis.commands.core.CoreCommands.ping")
    def test_rediss_url(self, mock_ping):

        """ Tests proper handling of the REDIS_URL variable with rediss:// scheme"""

        mock_ping.return_value = True

        EXPECTED_KWARGS_REDISS = COMMON_TEST_KWARGS | {"ssl_cert_reqs" : "none", "ssl_ca_certs" : "/test/testchain.crt", "ssl_certfile" : "/test/test.crt", "ssl_keyfile" : "/test/test.key", "retry_on_timeout" : True} | UNIVERSAL_KWARGS | COMMON_SOCKET_KWARGS

        with patch.dict(os.environ, {"REDIS_URL":"rediss://localhost:6379/0?ssl_cert_reqs=none&ssl_ca_certs=/test/testchain.crt&ssl_certfile=/test/test.crt&ssl_keyfile=/test/test.key"}, clear=False):

            client = RedisClient().get_test_client(max_retries = 1)
            self.assertTrue(EXPECTED_KWARGS_REDISS.items() <= client.get_connection_kwargs().items())

    @patch("core.utils.redis.commands.core.CoreCommands.ping")
    def test_redis_hostport(self, mock_ping):

        """ Tests proper handling of the REDIS_[HOST|PORT|DB] variables """

        mock_ping.return_value = True

        EXPECTED_KWARGS_HOSTPORT = COMMON_TEST_KWARGS | {"username" : "user", "password" : "secret", "db" : 1} | UNIVERSAL_KWARGS | COMMON_SOCKET_KWARGS

        with patch.dict(os.environ, {"REDIS_HOST" : "localhost", 
                                     "REDIS_USER" : "user",
                                     "REDIS_PASSWORD" : "secret", 
                                     "REDIS_DB" : '1'}, clear=False):

            client = RedisClient().get_test_client(max_retries = 1)
            self.assertTrue(EXPECTED_KWARGS_HOSTPORT.items() <= client.get_connection_kwargs().items())