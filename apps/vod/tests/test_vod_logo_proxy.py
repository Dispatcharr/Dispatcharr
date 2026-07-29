from unittest.mock import patch, MagicMock
from django.test import TestCase
from apps.vod.models import VODLogo


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

    @patch("apps.vod.api_views.requests.get")
    def test_cache_sends_user_agent_header(self, mock_get):
        """Verify that VODLogoViewSet.cache passes the User-Agent header to requests.get."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.iter_content.return_value = [b"fake_image_bytes"]
        mock_response.headers = {"Content-Type": "image/jpeg"}
        mock_get.return_value = mock_response

        response = self.client.get(f"/api/vod/vodlogos/{self.http_logo.id}/cache/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"fake_image_bytes")
        mock_get.assert_called_once()
        _, kwargs = mock_get.call_args
        self.assertIn("headers", kwargs)
        self.assertIn("User-Agent", kwargs["headers"])
