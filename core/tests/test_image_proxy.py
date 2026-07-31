from unittest.mock import MagicMock, patch

from django.http import Http404
from django.test import SimpleTestCase

from core.image_proxy import image_fetch_failures, serve_local_or_remote_image


class ServeLocalOrRemoteImageTests(SimpleTestCase):
    def setUp(self):
        image_fetch_failures.clear()

    def test_empty_url_raises_http404(self):
        with self.assertRaises(Http404):
            serve_local_or_remote_image("")

    def test_non_http_remote_raises_http404(self):
        with self.assertRaises(Http404):
            serve_local_or_remote_image("ftp://example.com/x.png")

    @patch("core.image_proxy.requests.get")
    @patch(
        "core.image_proxy.CoreSettings.get_default_user_agent",
        return_value="Dispatcharr-Test/1.0",
    )
    def test_remote_success(self, _mock_ua, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.iter_content.return_value = [b"img"]
        mock_response.headers = {"Content-Type": "image/png"}
        mock_get.return_value = mock_response

        response = serve_local_or_remote_image("https://cdn.example.com/a.png")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"img")
        mock_get.assert_called_once()
        _, kwargs = mock_get.call_args
        self.assertEqual(
            kwargs.get("headers"),
            {"User-Agent": "Dispatcharr-Test/1.0"},
        )
