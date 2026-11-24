import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase
from rest_framework import viewsets

from apps.channels.api_views import BulkDeleteLogosAPIView, CleanupUnusedLogosAPIView, LogoViewSet
from apps.channels.tasks import _url_validation_cache, _validate_url
from core.utils import resolve_safe_local_data_path


class LogoDeletionSecurityTests(SimpleTestCase):
    def test_symlink_escape_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "logos").mkdir()
            (root / "victim").write_text("keep")
            (root / "logos" / "escape").symlink_to(root / "victim")

            def mapped_path(path):
                return root / path.removeprefix("/data/")

            with patch("core.utils.Path", side_effect=mapped_path):
                self.assertIsNone(resolve_safe_local_data_path("/data/logos/escape"))

    def test_all_deletion_paths_confine_local_files(self):
        for method in ("bulk", "cleanup", "single"):
            for url, expected in (
                ("/data/logos/../db/victim", None),
                ("/data/logos-other/victim", None),
                ("/data/logos/safe.png", "/data/logos/safe.png"),
            ):
                with self.subTest(method=method, url=url):
                    logo = MagicMock(url=url, name="test")
                    logo.channels.exists.return_value = False
                    logos = MagicMock()
                    logos.__iter__.return_value = iter([logo])
                    logos.delete.return_value = (1, {})
                    request = MagicMock(data={"logo_ids": [1], "delete_files": True})
                    request.query_params = {"delete_file": "true"}
                    with patch("apps.channels.api_views.Logo.objects.filter", return_value=logos), \
                         patch("apps.channels.api_views.os.path.exists", return_value=True), \
                         patch("apps.channels.api_views.os.remove") as remove, \
                         patch.object(viewsets.ModelViewSet, "destroy"):
                        if method == "bulk":
                            BulkDeleteLogosAPIView().delete(request)
                        elif method == "cleanup":
                            CleanupUnusedLogosAPIView().post(request)
                        else:
                            view = LogoViewSet()
                            view.get_object = MagicMock(return_value=logo)
                            view.destroy(request)
                    if expected:
                        remove.assert_called_once_with(expected)
                    else:
                        remove.assert_not_called()


class PosterValidationSecurityTests(SimpleTestCase):
    def setUp(self):
        _url_validation_cache.clear()
        self.addCleanup(_url_validation_cache.clear)

    def test_unsafe_addresses_are_not_requested(self):
        for url in ("http://127.0.0.1/a", "http://169.254.169.254/a"):
            with self.subTest(url=url), patch("requests.Session.head") as head:
                self.assertFalse(_validate_url(url))
                head.assert_not_called()

    def test_redirect_to_loopback_is_blocked(self):
        response = MagicMock(status_code=302, headers={"Location": "http://127.0.0.1/private"})
        with patch("core.http_security.validate_outbound_http_url", side_effect=[["8.8.8.8"], ValueError("blocked")]), \
             patch("requests.Session.head", return_value=response) as head:
            self.assertFalse(_validate_url("http://example.com/poster"))
            self.assertEqual(head.call_count, 1)
            response.close.assert_called_once()

    def test_public_response_is_closed_and_cached(self):
        response = MagicMock(status_code=200)
        response.__enter__.return_value = response
        with patch("core.http_security.get_with_validated_redirects", return_value=response) as get:
            self.assertTrue(_validate_url("https://example.com/poster"))
            self.assertTrue(_validate_url("https://example.com/poster"))
            get.assert_called_once_with("https://example.com/poster", timeout=4, method="HEAD", allow_private=True)
            response.__exit__.assert_called_once()

    def test_head_405_uses_safe_ranged_get(self):
        head, get_response = MagicMock(status_code=405), MagicMock(status_code=200)
        head.__enter__.return_value = head
        get_response.__enter__.return_value = get_response
        with patch("core.http_security.get_with_validated_redirects", side_effect=[head, get_response]) as fetch:
            self.assertTrue(_validate_url("https://example.com/poster"))
            self.assertEqual(fetch.call_count, 2)
            self.assertEqual(fetch.call_args.kwargs, {
                "timeout": 4, "headers": {"Range": "bytes=0-0"},
                "stream": True, "allow_private": True,
            })
            head.__exit__.assert_called_once()
            get_response.__exit__.assert_called_once()

    def test_lan_addresses_are_allowed(self):
        response = MagicMock(status_code=200)
        response.__enter__.return_value = response
        response.__exit__.side_effect = lambda *args: response.close()
        with patch("requests.Session.head", return_value=response) as head:
            self.assertTrue(_validate_url("http://192.168.1.1/poster"))
            head.assert_called_once()
            response.close.assert_called_once()
