from django.core.cache import cache
from django.test import RequestFactory, TestCase

from core.models import CoreSettings, SYSTEM_SETTINGS_KEY
from core.utils import get_host_and_port


class GetHostAndPortTests(TestCase):
    """
    Covers the no-reverse-proxy Docker port-remap case (e.g. `8080:9191`)
    where none of the X-Forwarded-* signals exist and get_host_and_port()
    would otherwise bake in SERVER_PORT (the internal container-bound port)
    instead of whatever port the operator actually exposed.
    """

    def setUp(self):
        cache.clear()
        CoreSettings.objects.filter(key=SYSTEM_SETTINGS_KEY).delete()

    def tearDown(self):
        cache.clear()

    def _direct_request(self, server_port="9191"):
        # No X-Forwarded-* headers at all: simulates a client hitting the
        # container directly through a plain Docker host-port remap, with no
        # reverse proxy anywhere in the path. HTTP_HOST is set explicitly
        # (without a port) to match what a real client actually sends -
        # RequestFactory otherwise synthesizes "testserver:<SERVER_PORT>" as
        # the Host, which short-circuits at step 2 before ever reaching the
        # SERVER_PORT/public_port fallback this test is meant to exercise.
        factory = RequestFactory()
        request = factory.get(
            "/", SERVER_PORT=server_port, HTTP_HOST="dvb.example.com"
        )
        request.META.pop("HTTP_X_FORWARDED_HOST", None)
        request.META.pop("HTTP_X_FORWARDED_PORT", None)
        request.META.pop("HTTP_X_FORWARDED_PROTO", None)
        request.META.pop("HTTP_X_FORWARDED_FOR", None)
        return request

    def test_no_override_falls_back_to_server_port(self):
        """Default behavior (no public_port configured) is unchanged."""
        request = self._direct_request(server_port="9191")
        host, port = get_host_and_port(request)
        self.assertEqual(port, "9191")

    def test_public_port_override_wins_over_server_port(self):
        """
        Operator explicitly mapped `8080:9191` and set Public Port=8080 in
        Settings > System. Generated URLs must use 8080, not the internal
        9191 SERVER_PORT - this is the actual bug being fixed.
        """
        CoreSettings.set_public_port("8080")
        request = self._direct_request(server_port="9191")
        host, port = get_host_and_port(request)
        self.assertEqual(port, "8080")

    def test_public_port_override_omitted_when_standard(self):
        """If the override equals the standard port for the scheme, it's
        omitted from the URL just like every other path in this function."""
        CoreSettings.set_public_port("80")
        request = self._direct_request(server_port="9191")
        host, port = get_host_and_port(request)
        self.assertIsNone(port)

    def test_reverse_proxy_headers_still_take_priority(self):
        """A properly configured reverse proxy's own signals must not be
        shadowed by a leftover public_port override."""
        CoreSettings.set_public_port("8080")
        factory = RequestFactory()
        request = factory.get(
            "/",
            SERVER_PORT="9191",
            HTTP_X_FORWARDED_PROTO="https",
            HTTP_X_FORWARDED_HOST="tv.example.com",
        )
        host, port = get_host_and_port(request)
        self.assertEqual(host, "tv.example.com")
        self.assertIsNone(port)
