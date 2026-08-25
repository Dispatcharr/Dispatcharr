from unittest.mock import patch, MagicMock
from django.test import TestCase
from apps.vod.models import VODLogo

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"fake_image_bytes"


class VODLogoProxyTestCase(TestCase):
    def setUp(self):
        self.http_logo = VODLogo.objects.create(
            name="HTTP Poster",
            url="http://provider.example.com:8080//images//poster.jpg"
        )

    def test_url_string_is_unmodified_in_database(self):
        """Verify that the stored logo.url in the database is never modified."""
        db_logo = VODLogo.objects.get(id=self.http_logo.id)
        self.assertEqual(db_logo.url, "http://provider.example.com:8080//images//poster.jpg")

    @patch("core.image_proxy.validate_outbound_http_url")
    @patch("core.image_proxy.requests.get")
    @patch(
        "core.image_proxy.CoreSettings.get_default_user_agent",
        return_value="Dispatcharr-Test/1.0",
    )
    def test_cache_sends_user_agent_header(self, _mock_ua, mock_get, _mock_validate):
        """Verify that VODLogoViewSet.cache passes the User-Agent header to requests.get."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.iter_content.return_value = [PNG_BYTES]
        mock_response.headers = {"Content-Type": "image/jpeg"}
        mock_get.return_value = mock_response

        response = self.client.get(f"/api/vod/vodlogos/{self.http_logo.id}/cache/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, PNG_BYTES)
        mock_get.assert_called_once()
        _, kwargs = mock_get.call_args
        self.assertEqual(
            kwargs.get("headers"),
            {"User-Agent": "Dispatcharr-Test/1.0"},
        )

    @patch("core.image_proxy.validate_outbound_http_url")
    @patch("core.image_proxy.requests.get")
    @patch(
        "core.image_proxy.CoreSettings.get_default_user_agent",
        return_value="Dispatcharr-Test/1.0",
    )
    def test_cache_accepts_slash_less_url(self, _mock_ua, mock_get, _mock_validate):
        """Clients that strip trailing slashes still get the image, not a redirect."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.iter_content.return_value = [PNG_BYTES]
        mock_response.headers = {"Content-Type": "image/jpeg"}
        mock_get.return_value = mock_response

        response = self.client.get(f"/api/vod/vodlogos/{self.http_logo.id}/cache")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, PNG_BYTES)
        self.assertFalse(response.has_header("Location"))
