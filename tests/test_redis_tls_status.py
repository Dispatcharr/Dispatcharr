from django.test import SimpleTestCase, TestCase

from dispatcharr.settings import redis_tls_status_from_url


class RedisTlsStatusFromUrlTests(SimpleTestCase):
    """REDIS_URL drives TLS status when discrete REDIS_SSL_* vars are not applied."""

    def test_plaintext_and_unix_are_disabled(self):
        self.assertEqual(
            redis_tls_status_from_url("redis://localhost:6379/0"),
            {"enabled": False, "verify": False, "mtls": False},
        )
        self.assertEqual(
            redis_tls_status_from_url("unix:///var/run/redis/redis.sock?db=7"),
            {"enabled": False, "verify": False, "mtls": False},
        )

    def test_rediss_defaults_to_verified(self):
        self.assertEqual(
            redis_tls_status_from_url("rediss://localhost:6379/0"),
            {"enabled": True, "verify": True, "mtls": False},
        )

    def test_rediss_query_controls_verify_and_mtls(self):
        url = (
            "rediss://localhost:6379/0"
            "?ssl_cert_reqs=none"
            "&ssl_certfile=/test/test.crt"
            "&ssl_keyfile=/test/test.key"
        )
        self.assertEqual(
            redis_tls_status_from_url(url),
            {"enabled": True, "verify": False, "mtls": True},
        )

    def test_certfile_without_key_is_not_mtls(self):
        url = "rediss://localhost:6379/0?ssl_cert_reqs=required&ssl_certfile=/test/test.crt"
        self.assertEqual(
            redis_tls_status_from_url(url),
            {"enabled": True, "verify": True, "mtls": False},
        )


class EnvironmentEndpointRedisTlsTests(TestCase):
    def test_environment_endpoint_reports_redis_tls_status(self):
        """The /api/core/settings/env/ endpoint must surface REDIS_TLS_STATUS."""
        from django.contrib.auth import get_user_model
        from rest_framework.test import APIClient
        from django.test import override_settings

        user = get_user_model().objects.create_user("redis_tls_tester", password="pw")
        client = APIClient()
        client.force_authenticate(user=user)

        expected = {"enabled": True, "verify": True, "mtls": False}
        with override_settings(ENABLE_IP_LOOKUP=False, REDIS_TLS_STATUS=expected):
            response = client.get("/api/core/settings/env/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data.get("redis_tls"), expected)
