import contextlib
import datetime
import os
import socket
import ssl
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import MagicMock, patch

import requests
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from django.test import SimpleTestCase

from core.http_security import (
    get_ssrf_safe,
    get_with_validated_redirects,
    validate_outbound_http_url,
)


def _fake_addrinfo(*addrs):
    """Build getaddrinfo-style results for the given IP strings."""
    results = []
    for addr in addrs:
        # sockaddr is (ip, port) for AF_INET; port unused by validator.
        results.append((None, None, None, None, (addr, 0)))
    return results


def _dns_override(names):
    """Patch getaddrinfo so *names* resolve to the mapped IPs and others stay real.

    The patch targets the shared ``socket`` module, so the HTTP client's own
    lookup of the pinned IP literal still needs a real answer.
    """
    real = socket.getaddrinfo

    def fake(host, port, *args, **kwargs):
        if host in names:
            return real(names[host], port, *args, **kwargs)
        return real(host, port, *args, **kwargs)

    return patch("core.http_security.socket.getaddrinfo", side_effect=fake)


def _write_self_signed_cert(directory, dns_name):
    """Write a self-signed cert and key valid for *dns_name*; return both paths."""
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, dns_name)])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(dns_name)]), critical=False)
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(key.public_key()),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    cert_path = os.path.join(directory, f"{dns_name}.pem")
    key_path = os.path.join(directory, f"{dns_name}.key")
    with open(cert_path, "wb") as fh:
        fh.write(cert.public_bytes(serialization.Encoding.PEM))
    with open(key_path, "wb") as fh:
        fh.write(
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.TraditionalOpenSSL,
                serialization.NoEncryption(),
            )
        )
    return cert_path, key_path


class _QuietServer(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        # Failed TLS handshakes are expected in the negative tests.
        pass


@contextlib.contextmanager
def _local_server(tls=None):
    """Serve a tiny body on 127.0.0.1; yield (port, seen) where seen["host"] is the Host header."""
    seen = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            seen["host"] = self.headers.get("Host")
            body = b"pinned-ok"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt, *args):
            return

    server = _QuietServer(("127.0.0.1", 0), Handler)
    if tls is not None:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(*tls)
        server.socket = ctx.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1], seen
    finally:
        server.shutdown()
        server.server_close()


def _env_with_proxies(**proxy_vars):
    """Patch os.environ so only *proxy_vars* configure proxies."""
    env = {k: v for k, v in os.environ.items() if not k.lower().endswith("_proxy")}
    env.update(proxy_vars)
    return patch.dict(os.environ, env, clear=True)


class ValidateOutboundHttpUrlTests(SimpleTestCase):
    def test_rejects_non_http_schemes(self):
        with self.assertRaises(ValueError):
            validate_outbound_http_url("ftp://example.com/x")

    def test_rejects_missing_hostname(self):
        with self.assertRaises(ValueError):
            validate_outbound_http_url("http:///nohost")

    @patch("core.http_security.socket.getaddrinfo", return_value=_fake_addrinfo("93.184.216.34"))
    def test_allows_public_address(self, _mock_gai):
        ips = validate_outbound_http_url("https://cdn.example.com/a.png")
        self.assertEqual(ips, ["93.184.216.34"])

    @patch("core.http_security.socket.getaddrinfo", return_value=_fake_addrinfo("192.168.1.10"))
    def test_rejects_private_by_default(self, _mock_gai):
        with self.assertRaises(ValueError):
            validate_outbound_http_url("http://nas.local/logo.png")

    @patch("core.http_security.socket.getaddrinfo", return_value=_fake_addrinfo("192.168.1.10"))
    def test_allows_private_when_enabled(self, _mock_gai):
        ips = validate_outbound_http_url(
            "http://nas.local/logo.png",
            allow_private=True,
        )
        self.assertEqual(ips, ["192.168.1.10"])

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
        ips = validate_outbound_http_url(
            "http://127.0.0.1/logo.png",
            allow_loopback=True,
        )
        self.assertEqual(ips, ["127.0.0.1"])


class GetSsrfSafePinningTests(SimpleTestCase):
    @patch("core.http_security.socket.getaddrinfo", return_value=_fake_addrinfo("93.184.216.34"))
    @patch("requests.Session.get")
    def test_connects_to_validated_ip_with_original_host_header(self, mock_get, _mock_gai):
        """Validation IP is dialed; hostname is not left for a second DNS lookup."""
        mock_get.return_value = MagicMock(status_code=200, headers={})

        get_ssrf_safe("https://cdn.example.com/a.png", headers={"User-Agent": "Test/1.0"})

        mock_get.assert_called_once()
        args, kwargs = mock_get.call_args
        self.assertEqual(args[0], "https://93.184.216.34/a.png")
        self.assertEqual(kwargs["headers"]["Host"], "cdn.example.com")
        self.assertEqual(kwargs["headers"]["User-Agent"], "Test/1.0")
        self.assertFalse(kwargs["allow_redirects"])

    @patch("core.http_security.socket.getaddrinfo", return_value=_fake_addrinfo("93.184.216.34"))
    @patch("requests.Session.get")
    def test_rebinding_cannot_reach_loopback(self, mock_get, _mock_gai):
        """Even if a later DNS answer would be loopback, the client dials the validated IP."""
        mock_get.return_value = MagicMock(status_code=200, headers={})

        get_ssrf_safe("http://rebind.example/logo.png", allow_private=True)

        pinned_url = mock_get.call_args.args[0]
        self.assertEqual(pinned_url, "http://93.184.216.34/logo.png")
        self.assertNotIn("127.0.0.1", pinned_url)
        self.assertEqual(mock_get.call_args.kwargs["headers"]["Host"], "rebind.example")

    @patch(
        "core.http_security.socket.getaddrinfo",
        return_value=_fake_addrinfo("2606:2800:220:1:248:1893:25c8:1946"),
    )
    @patch("requests.Session.get")
    def test_ipv6_pinned_url_is_bracketed(self, mock_get, _mock_gai):
        mock_get.return_value = MagicMock(status_code=200, headers={})

        get_ssrf_safe("https://cdn.example.com:8443/a.png")

        self.assertEqual(
            mock_get.call_args.args[0],
            "https://[2606:2800:220:1:248:1893:25c8:1946]:8443/a.png",
        )
        self.assertEqual(mock_get.call_args.kwargs["headers"]["Host"], "cdn.example.com:8443")

    @patch("core.http_security.socket.getaddrinfo", return_value=_fake_addrinfo("93.184.216.34"))
    @patch("requests.Session.get")
    def test_preserves_userinfo_and_non_default_port(self, mock_get, _mock_gai):
        mock_get.return_value = MagicMock(status_code=200, headers={})

        get_ssrf_safe("https://user:p%40ss@cdn.example.com:8443/a.png?x=1")

        self.assertEqual(
            mock_get.call_args.args[0],
            "https://user:p%40ss@93.184.216.34:8443/a.png?x=1",
        )
        self.assertEqual(mock_get.call_args.kwargs["headers"]["Host"], "cdn.example.com:8443")

    @patch("core.http_security.socket.getaddrinfo", return_value=_fake_addrinfo("93.184.216.34"))
    @patch("requests.Session.get")
    def test_host_header_uses_idna(self, mock_get, _mock_gai):
        mock_get.return_value = MagicMock(status_code=200, headers={})

        get_ssrf_safe("https://bücher.example/logo.png")

        self.assertEqual(mock_get.call_args.kwargs["headers"]["Host"], "xn--bcher-kva.example")
        self.assertTrue(mock_get.call_args.args[0].startswith("https://93.184.216.34/"))

    @patch(
        "core.http_security.socket.getaddrinfo",
        return_value=_fake_addrinfo("93.184.216.34", "93.184.216.34"),
    )
    @patch("requests.Session.get")
    def test_duplicate_dns_answers_connect_once(self, mock_get, _mock_gai):
        mock_get.return_value = MagicMock(status_code=200, headers={})

        get_ssrf_safe("http://cdn.example.com/a.png")

        mock_get.assert_called_once()

    @patch(
        "core.http_security.socket.getaddrinfo",
        return_value=_fake_addrinfo(
            "2606:2800:220:1:248:1893:25c8:1946",
            "93.184.216.34",
        ),
    )
    @patch("requests.Session.get")
    def test_falls_back_when_first_address_cannot_connect(self, mock_get, _mock_gai):
        mock_get.side_effect = [
            requests.ConnectionError("unreachable"),
            MagicMock(status_code=200, headers={}),
        ]

        response = get_ssrf_safe("http://cdn.example.com/a.png")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            mock_get.call_args_list[0].args[0],
            "http://[2606:2800:220:1:248:1893:25c8:1946]/a.png",
        )
        self.assertEqual(mock_get.call_args_list[1].args[0], "http://93.184.216.34/a.png")

    @patch(
        "core.http_security.socket.getaddrinfo",
        return_value=_fake_addrinfo("93.184.216.34", "93.184.216.35"),
    )
    @patch("requests.Session.get")
    def test_http_error_does_not_try_the_next_address(self, mock_get, _mock_gai):
        mock_get.return_value = MagicMock(status_code=500, headers={})

        response = get_ssrf_safe("http://cdn.example.com/a.png")

        self.assertEqual(response.status_code, 500)
        mock_get.assert_called_once()

    @patch("core.http_security.socket.getaddrinfo", return_value=_fake_addrinfo("93.184.216.34"))
    @patch("requests.Session.get")
    def test_does_not_mount_adapter_on_caller_session(self, mock_get, _mock_gai):
        mock_get.return_value = MagicMock(status_code=200, headers={})
        caller = requests.Session()
        caller.trust_env = False
        original = caller.get_adapter("https://cdn.example.com/a.png")

        get_ssrf_safe("https://cdn.example.com/a.png", session=caller)

        self.assertIs(caller.get_adapter("https://cdn.example.com/a.png"), original)
        caller.close()

    @patch(
        "core.http_security.socket.getaddrinfo",
        return_value=_fake_addrinfo("93.184.216.34", "93.184.216.35"),
    )
    @patch("requests.Session.get")
    def test_tls_error_does_not_try_the_next_address(self, mock_get, _mock_gai):
        """A certificate failure must surface as-is, not as a later address's error."""
        mock_get.side_effect = requests.exceptions.SSLError("certificate verify failed")

        with self.assertRaises(requests.exceptions.SSLError):
            get_ssrf_safe("https://cdn.example.com/a.png")

        mock_get.assert_called_once()

    @patch(
        "core.http_security.socket.getaddrinfo",
        return_value=_fake_addrinfo("93.184.216.34", "93.184.216.35"),
    )
    @patch("requests.Session.get")
    def test_proxy_error_does_not_try_the_next_address(self, mock_get, _mock_gai):
        mock_get.side_effect = requests.exceptions.ProxyError("proxy unreachable")

        with self.assertRaises(requests.exceptions.ProxyError):
            get_ssrf_safe("http://cdn.example.com/a.png")

        mock_get.assert_called_once()


class GetSsrfSafeLiveTests(SimpleTestCase):
    """Exercise real sockets and TLS, which the mocked tests above cannot cover."""

    def _fetch(self, url, *, verify=True, **kwargs):
        session = requests.Session()
        session.trust_env = False
        session.verify = verify
        try:
            return get_ssrf_safe(
                url, allow_loopback=True, timeout=3, session=session, **kwargs
            )
        finally:
            session.close()

    def test_streamed_body_survives_session_close(self):
        """Closing the private session must not drop a streamed response body."""
        with _local_server() as (port, seen), _dns_override({"artwork.example": "127.0.0.1"}):
            response = self._fetch(f"http://artwork.example:{port}/logo.png", stream=True)
            try:
                body = b"".join(response.iter_content(64))
            finally:
                response.close()

        self.assertEqual(body, b"pinned-ok")
        self.assertEqual(seen["host"], f"artwork.example:{port}")

    def test_https_verifies_certificate_against_original_hostname(self):
        """The socket goes to the pinned IP, but TLS still verifies the hostname."""
        with tempfile.TemporaryDirectory() as tmp:
            cert = _write_self_signed_cert(tmp, "artwork.example")
            with _local_server(tls=cert) as (port, seen), _dns_override(
                {"artwork.example": "127.0.0.1"}
            ):
                response = self._fetch(
                    f"https://artwork.example:{port}/logo.png", verify=cert[0]
                )
                response.close()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(seen["host"], f"artwork.example:{port}")

    def test_https_rejects_certificate_for_a_different_hostname(self):
        """Pinning must not weaken verification: a cert for another name is refused."""
        with tempfile.TemporaryDirectory() as tmp:
            cert = _write_self_signed_cert(tmp, "other.example")
            with _local_server(tls=cert) as (port, _seen), _dns_override(
                {"artwork.example": "127.0.0.1"}
            ):
                with self.assertRaises(requests.exceptions.SSLError):
                    self._fetch(f"https://artwork.example:{port}/logo.png", verify=cert[0])

    def test_https_rejects_untrusted_certificate(self):
        with tempfile.TemporaryDirectory() as tmp:
            cert = _write_self_signed_cert(tmp, "artwork.example")
            with _local_server(tls=cert) as (port, _seen), _dns_override(
                {"artwork.example": "127.0.0.1"}
            ):
                with self.assertRaises(requests.exceptions.SSLError):
                    self._fetch(f"https://artwork.example:{port}/logo.png", verify=True)


class GetSsrfSafeProxyTests(SimpleTestCase):
    """NO_PROXY is a hostname policy, so pinning to an IP must not change it."""

    DEAD_PROXY = "http://127.0.0.1:1"

    def test_no_proxy_hostname_still_bypasses_the_proxy(self):
        with _local_server() as (port, seen), _dns_override(
            {"artwork.example": "127.0.0.1"}
        ), _env_with_proxies(
            HTTP_PROXY=self.DEAD_PROXY,
            ALL_PROXY=self.DEAD_PROXY,
            NO_PROXY="artwork.example",
        ):
            response = get_ssrf_safe(
                f"http://artwork.example:{port}/logo.png", allow_loopback=True, timeout=3
            )
            response.close()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(seen["host"], f"artwork.example:{port}")

    def test_proxy_is_still_used_when_host_is_not_exempt(self):
        with _local_server() as (port, _seen), _dns_override(
            {"artwork.example": "127.0.0.1"}
        ), _env_with_proxies(HTTP_PROXY=self.DEAD_PROXY):
            with self.assertRaises(requests.exceptions.ProxyError):
                get_ssrf_safe(
                    f"http://artwork.example:{port}/logo.png", allow_loopback=True, timeout=3
                )


class GetWithValidatedRedirectsTests(SimpleTestCase):
    @patch("core.http_security.socket.getaddrinfo")
    @patch("requests.Session.get")
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
        self.assertEqual(mock_get.call_args_list[0].args[0], "https://93.184.216.34/start.zip")
        self.assertEqual(mock_get.call_args_list[1].args[0], "https://93.184.216.35/final.zip")

    @patch("core.http_security.socket.getaddrinfo")
    @patch("requests.Session.get")
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
