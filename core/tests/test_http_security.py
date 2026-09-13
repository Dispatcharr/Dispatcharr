from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from core.http_security import get_with_validated_redirects, validate_outbound_http_url


def _fake_addrinfo(*addrs):
    """Build getaddrinfo-style results for the given IP strings."""
    results = []
    for addr in addrs:
        # sockaddr is (ip, port) for AF_INET; port unused by validator.
        results.append((None, None, None, None, (addr, 0)))
    return results


class ValidateOutboundHttpUrlTests(SimpleTestCase):
    def test_rejects_non_http_schemes(self):
        with self.assertRaises(ValueError):
            validate_outbound_http_url("ftp://example.com/x")

    def test_rejects_missing_hostname(self):
        with self.assertRaises(ValueError):
            validate_outbound_http_url("http:///nohost")

    @patch("core.http_security.socket.getaddrinfo", return_value=_fake_addrinfo("93.184.216.34"))
    def test_allows_public_address(self, _mock_gai):
        validate_outbound_http_url("https://cdn.example.com/a.png")

    @patch("core.http_security.socket.getaddrinfo", return_value=_fake_addrinfo("192.168.1.10"))
    def test_rejects_private_by_default(self, _mock_gai):
        with self.assertRaises(ValueError):
            validate_outbound_http_url("http://nas.local/logo.png")

    @patch("core.http_security.socket.getaddrinfo", return_value=_fake_addrinfo("192.168.1.10"))
    def test_allows_private_when_enabled(self, _mock_gai):
        validate_outbound_http_url(
            "http://nas.local/logo.png",
            allow_private=True,
        )

    @patch("core.http_security.socket.getaddrinfo", return_value=_fake_addrinfo("127.0.0.1"))
    def test_rejects_loopback_even_when_private_allowed(self, _mock_gai):
        with self.assertRaises(ValueError):
            validate_outbound_http_url(
                "http://127.0.0.1/logo.png",
                allow_private=True,
            )

    @patch("core.http_security.socket.getaddrinfo", return_value=_fake_addrinfo("169.254.169.254"))
    def test_rejects_link_local_metadata(self, _mock_gai):
        with self.assertRaises(ValueError):
            validate_outbound_http_url(
                "http://169.254.169.254/latest/meta-data/",
                allow_private=True,
            )

    @patch("core.http_security.socket.getaddrinfo", return_value=_fake_addrinfo("127.0.0.1"))
    def test_allows_loopback_when_enabled(self, _mock_gai):
        validate_outbound_http_url(
            "http://127.0.0.1/logo.png",
            allow_loopback=True,
        )


class GetWithValidatedRedirectsTests(SimpleTestCase):
    @patch("core.http_security.socket.getaddrinfo")
    @patch("core.http_security.requests.get")
    def test_follows_public_redirect_and_validates_each_hop(self, mock_get, mock_gai):
        mock_gai.side_effect = [
            _fake_addrinfo("93.184.216.34"),
            _fake_addrinfo("93.184.216.35"),
        ]
        redirect = MagicMock()
        redirect.status_code = 302
        redirect.headers = {"Location": "https://cdn.example.com/final.zip"}
        final = MagicMock()
        final.status_code = 200
        final.headers = {}
        mock_get.side_effect = [redirect, final]

        response = get_with_validated_redirects("https://cdn.example.com/start.zip")
        self.assertIs(response, final)
        redirect.close.assert_called_once()
        self.assertEqual(mock_get.call_count, 2)
        self.assertFalse(mock_get.call_args_list[0].kwargs["allow_redirects"])

    @patch("core.http_security.socket.getaddrinfo")
    @patch("core.http_security.requests.get")
    def test_blocks_redirect_to_private_target(self, mock_get, mock_gai):
        mock_gai.side_effect = [
            _fake_addrinfo("93.184.216.34"),
            _fake_addrinfo("10.0.0.5"),
        ]
        redirect = MagicMock()
        redirect.status_code = 302
        redirect.headers = {"Location": "http://10.0.0.5/secret"}
        mock_get.return_value = redirect

        with self.assertRaises(ValueError):
            get_with_validated_redirects("https://cdn.example.com/start.zip")
        redirect.close.assert_called_once()
        mock_get.assert_called_once()
