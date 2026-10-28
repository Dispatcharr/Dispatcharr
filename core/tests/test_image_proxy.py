from unittest.mock import MagicMock, patch

import requests
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


def _status_response(status_code: int):
    mock_response = MagicMock()
    mock_response.status_code = status_code
    mock_response.headers = {}
    return mock_response


def _host_that_rejects_double_slash():
    """requests.get stand-in: 400 for a path with ``//``, otherwise a PNG."""

    def fake_get(url, **kwargs):
        path = url.split("://", 1)[1].split("?", 1)[0].split("#", 1)[0]
        if "//" in path.split("/", 1)[1]:
            return _status_response(400)
        return _mock_ok_response(PNG_BYTES)

    return fake_get


@patch("core.image_proxy.validate_outbound_http_url")
@patch(
    "core.image_proxy.CoreSettings.get_default_user_agent",
    return_value="Dispatcharr-Test/1.0",
)
class DoubleSlashRetryTests(SimpleTestCase):
    """A failed fetch is retried once with repeated path slashes collapsed."""

    RAW = "https://logos.example.com/logos//New_Zealand/CNN.nz.png"
    COLLAPSED = "https://logos.example.com/logos/New_Zealand/CNN.nz.png"

    def setUp(self):
        image_fetch_failures.clear()

    @patch("core.image_proxy.requests.get")
    def test_raw_400_then_collapsed_200_is_served(self, mock_get, _ua, _validate):
        mock_get.side_effect = _host_that_rejects_double_slash()

        response = serve_local_or_remote_image(self.RAW)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, PNG_BYTES)
        self.assertEqual(
            [call.args[0] for call in mock_get.call_args_list],
            [self.RAW, self.COLLAPSED],
        )
        # Neither URL is remembered as a failure.
        self.assertNotIn(self.RAW, image_fetch_failures)
        self.assertNotIn(self.COLLAPSED, image_fetch_failures)

        # A second request is not blocked by the earlier raw failure.
        mock_get.reset_mock()
        response = serve_local_or_remote_image(self.RAW)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(mock_get.call_count, 2)

    @patch("core.image_proxy.requests.get")
    def test_both_urls_validated_for_ssrf(self, mock_get, _ua, mock_validate):
        mock_get.side_effect = _host_that_rejects_double_slash()

        serve_local_or_remote_image(self.RAW)

        self.assertEqual(
            [call.args[0] for call in mock_validate.call_args_list],
            [self.RAW, self.COLLAPSED],
        )

    @patch("core.image_proxy.requests.get")
    def test_raw_success_is_never_retried(self, mock_get, _ua, _validate):
        mock_get.return_value = _mock_ok_response(PNG_BYTES)

        response = serve_local_or_remote_image(self.RAW)

        self.assertEqual(response.status_code, 200)
        mock_get.assert_called_once()
        self.assertEqual(mock_get.call_args.args[0], self.RAW)

    @patch("core.image_proxy.requests.get")
    def test_request_error_on_raw_triggers_the_retry(self, mock_get, _ua, _validate):
        mock_get.side_effect = [
            requests.exceptions.ConnectionError("reset"),
            _mock_ok_response(PNG_BYTES),
        ]

        response = serve_local_or_remote_image(self.RAW)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(mock_get.call_args_list[1].args[0], self.COLLAPSED)
        self.assertNotIn(self.RAW, image_fetch_failures)

    @patch("core.image_proxy.requests.get")
    def test_query_string_is_never_changed(self, mock_get, _ua, _validate):
        mock_get.return_value = _status_response(404)

        # No repeated slash in the path: a "//" in the query must not retry.
        with self.assertRaises(Http404):
            serve_local_or_remote_image("https://logos.example.com/a/b.png?x=/y//z")
        mock_get.assert_called_once()
        self.assertEqual(
            mock_get.call_args.args[0],
            "https://logos.example.com/a/b.png?x=/y//z",
        )

        # Repeated slash in the path: only the path is collapsed on the retry.
        mock_get.reset_mock()
        with self.assertRaises(Http404):
            serve_local_or_remote_image(
                "https://logos.example.com/a//b.png?x=/y//z#f//g"
            )
        self.assertEqual(
            [call.args[0] for call in mock_get.call_args_list],
            [
                "https://logos.example.com/a//b.png?x=/y//z#f//g",
                "https://logos.example.com/a/b.png?x=/y//z#f//g",
            ],
        )

    @patch("core.image_proxy.requests.get")
    def test_no_retry_when_path_has_no_repeated_slash(self, mock_get, _ua, _validate):
        mock_get.return_value = _status_response(404)

        with self.assertRaises(Http404):
            serve_local_or_remote_image("https://logos.example.com/logos/a.png")

        mock_get.assert_called_once()

    @patch("core.image_proxy.requests.get")
    def test_at_most_one_retry_and_failure_is_cached(self, mock_get, _ua, _validate):
        mock_get.return_value = _status_response(400)
        url = "https://logos.example.com/a///b//c.png"

        with self.assertRaises(Http404):
            serve_local_or_remote_image(url)
        self.assertEqual(
            [call.args[0] for call in mock_get.call_args_list],
            [url, "https://logos.example.com/a/b/c.png"],
        )

        # Both attempts failed: the negative cache now short-circuits the URL.
        mock_get.reset_mock()
        with self.assertRaises(Http404):
            serve_local_or_remote_image(url)
        mock_get.assert_not_called()

    @patch("core.image_proxy.requests.get")
    def test_blocked_url_is_not_retried(self, mock_get, _ua, mock_validate):
        mock_validate.side_effect = ValueError("blocked")

        with self.assertRaises(Http404):
            serve_local_or_remote_image("http://127.0.0.1/a//b.png")

        mock_get.assert_not_called()
        mock_validate.assert_called_once()


class CollapseRepeatedPathSlashesTests(SimpleTestCase):
    def collapse(self, url):
        from core import image_proxy

        return image_proxy._collapse_repeated_path_slashes(url)

    def test_collapses_path_only(self):
        self.assertEqual(
            self.collapse("https://h.example.com:8080/a//b///c.png?x=//y#z//"),
            "https://h.example.com:8080/a/b/c.png?x=//y#z//",
        )

    def test_scheme_and_host_are_untouched(self):
        self.assertEqual(
            self.collapse("http://h.example.com//a.png"),
            "http://h.example.com/a.png",
        )

    def test_unchanged_when_nothing_to_collapse(self):
        for url in (
            "https://h.example.com/a/b.png",
            "https://h.example.com/a/b.png?x=/y//z",
            "https://h.example.com",
            "not a url",
        ):
            self.assertEqual(self.collapse(url), url)
