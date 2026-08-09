from unittest.mock import MagicMock, patch

from django.http import Http404
from django.test import SimpleTestCase

from core.image_proxy import (
    image_fetch_failures,
    serve_local_or_remote_image,
    sniff_image_content_type,
)

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"fake-png-body"
JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"fake-jpeg-body"
SVG_BYTES = b'<svg xmlns="http://www.w3.org/2000/svg"><rect width="1" height="1"/></svg>'
HTML_BYTES = b"<!DOCTYPE html><html><script>alert(1)</script></html>"


def _mock_ok_response(body: bytes, status_code: int = 200, headers=None):
    mock_response = MagicMock()
    mock_response.status_code = status_code
    mock_response.iter_content.return_value = [body]
    mock_response.headers = headers or {"Content-Type": "application/octet-stream"}
    return mock_response


class SniffImageContentTypeTests(SimpleTestCase):
    def test_png_jpeg_gif_webp_svg(self):
        self.assertEqual(sniff_image_content_type(PNG_BYTES), "image/png")
        self.assertEqual(sniff_image_content_type(JPEG_BYTES), "image/jpeg")
        self.assertEqual(sniff_image_content_type(b"GIF89a" + b"xxxx"), "image/gif")
        self.assertEqual(
            sniff_image_content_type(b"RIFF" + b"xxxx" + b"WEBP" + b"data"),
            "image/webp",
        )
        self.assertEqual(sniff_image_content_type(SVG_BYTES), "image/svg+xml")

    def test_ico_and_bmp(self):
        self.assertEqual(
            sniff_image_content_type(b"\x00\x00\x01\x00" + b"icon-data"),
            "image/x-icon",
        )
        self.assertEqual(
            sniff_image_content_type(b"BM" + b"bmp-header-and-data"),
            "image/bmp",
        )

    def test_xml_wrapped_svg(self):
        body = b'<?xml version="1.0"?>\n<svg xmlns="http://www.w3.org/2000/svg"></svg>'
        self.assertEqual(sniff_image_content_type(body), "image/svg+xml")

    def test_svg_with_doctype_and_comment(self):
        doctype = (
            b'<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN" '
            b'"http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd">\n'
            b'<svg xmlns="http://www.w3.org/2000/svg"></svg>'
        )
        self.assertEqual(sniff_image_content_type(doctype), "image/svg+xml")
        comment = b'<!-- logo -->\n<svg xmlns="http://www.w3.org/2000/svg"></svg>'
        self.assertEqual(sniff_image_content_type(comment), "image/svg+xml")

    def test_rejects_html_and_unknown(self):
        self.assertIsNone(sniff_image_content_type(HTML_BYTES))
        self.assertIsNone(
            sniff_image_content_type(
                b"<html><body><svg xmlns='http://www.w3.org/2000/svg'></svg></body></html>"
            )
        )
        self.assertIsNone(sniff_image_content_type(b"not-an-image"))
        self.assertIsNone(sniff_image_content_type(b""))


class ServeLocalOrRemoteImageTests(SimpleTestCase):
    def setUp(self):
        image_fetch_failures.clear()

    def test_empty_url_raises_http404(self):
        with self.assertRaises(Http404):
            serve_local_or_remote_image("")

    def test_non_http_remote_raises_http404(self):
        with self.assertRaises(Http404):
            serve_local_or_remote_image("ftp://example.com/x.png")

    @patch("core.image_proxy.validate_outbound_http_url")
    @patch("core.image_proxy.requests.get")
    @patch(
        "core.image_proxy.CoreSettings.get_default_user_agent",
        return_value="Dispatcharr-Test/1.0",
    )
    def test_remote_success(self, _mock_ua, mock_get, mock_validate):
        mock_get.return_value = _mock_ok_response(PNG_BYTES)

        response = serve_local_or_remote_image("https://cdn.example.com/a.png")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, PNG_BYTES)
        self.assertEqual(response["Content-Type"], "image/png")
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        mock_validate.assert_called_once()
        mock_get.assert_called_once()
        _, kwargs = mock_get.call_args
        self.assertEqual(
            kwargs.get("headers"),
            {"User-Agent": "Dispatcharr-Test/1.0"},
        )
        self.assertFalse(kwargs.get("allow_redirects"))

    @patch("core.image_proxy.validate_outbound_http_url")
    @patch("core.image_proxy.requests.get")
    @patch(
        "core.image_proxy.CoreSettings.get_default_user_agent",
        return_value="Dispatcharr-Test/1.0",
    )
    def test_svg_gets_csp(self, _mock_ua, mock_get, _mock_validate):
        mock_get.return_value = _mock_ok_response(
            SVG_BYTES,
            headers={"Content-Type": "text/html"},
        )

        response = serve_local_or_remote_image("https://cdn.example.com/logo.svg")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/svg+xml")
        self.assertIn("sandbox", response["Content-Security-Policy"])

    @patch("core.image_proxy.validate_outbound_http_url")
    @patch("core.image_proxy.requests.get")
    @patch(
        "core.image_proxy.CoreSettings.get_default_user_agent",
        return_value="Dispatcharr-Test/1.0",
    )
    def test_rejects_html_despite_image_content_type(self, _mock_ua, mock_get, _mock_validate):
        mock_get.return_value = _mock_ok_response(
            HTML_BYTES,
            headers={"Content-Type": "image/png"},
        )

        with self.assertRaises(Http404):
            serve_local_or_remote_image("https://cdn.example.com/evil.png")

    @patch("core.image_proxy.validate_outbound_http_url")
    @patch("core.image_proxy.requests.get")
    @patch(
        "core.image_proxy.CoreSettings.get_default_user_agent",
        return_value="Dispatcharr-Test/1.0",
    )
    def test_follows_redirect_and_revalidates(self, _mock_ua, mock_get, mock_validate):
        redirect = MagicMock()
        redirect.status_code = 302
        redirect.headers = {"Location": "https://cdn.example.com/final.png"}
        final = _mock_ok_response(JPEG_BYTES)
        mock_get.side_effect = [redirect, final]

        response = serve_local_or_remote_image("https://cdn.example.com/start.png")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/jpeg")
        self.assertEqual(mock_get.call_count, 2)
        self.assertEqual(mock_validate.call_count, 2)
        self.assertEqual(
            mock_validate.call_args_list[0].args[0],
            "https://cdn.example.com/start.png",
        )
        self.assertEqual(
            mock_validate.call_args_list[1].args[0],
            "https://cdn.example.com/final.png",
        )

    @patch(
        "core.image_proxy.validate_outbound_http_url",
        side_effect=[None, ValueError("blocked")],
    )
    @patch("core.image_proxy.requests.get")
    @patch(
        "core.image_proxy.CoreSettings.get_default_user_agent",
        return_value="Dispatcharr-Test/1.0",
    )
    def test_blocks_redirect_to_unsafe_target(self, _mock_ua, mock_get, _mock_validate):
        redirect = MagicMock()
        redirect.status_code = 302
        redirect.headers = {"Location": "http://127.0.0.1/secret"}
        mock_get.return_value = redirect

        with self.assertRaises(Http404):
            serve_local_or_remote_image("https://cdn.example.com/start.png")

        self.assertEqual(mock_get.call_count, 1)

    @patch(
        "core.image_proxy.validate_outbound_http_url",
        side_effect=ValueError("blocked"),
    )
    @patch("core.image_proxy.requests.get")
    @patch(
        "core.image_proxy.CoreSettings.get_default_user_agent",
        return_value="Dispatcharr-Test/1.0",
    )
    def test_blocks_unsafe_url_before_fetch(self, _mock_ua, mock_get, _mock_validate):
        with self.assertRaises(Http404):
            serve_local_or_remote_image("http://127.0.0.1/logo.png")
        mock_get.assert_not_called()
