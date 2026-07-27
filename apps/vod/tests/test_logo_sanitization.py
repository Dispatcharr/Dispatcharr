"""
Unit tests for VOD logo URL sanitization and VODLogo model integration.
"""
from django.test import SimpleTestCase, TestCase
from apps.vod.models import VODLogo
from apps.vod.utils import sanitize_logo_url


class VODLogoSanitizationTests(SimpleTestCase):
    def test_exchange_cdn_movie_url_with_double_slash(self):
        url = "http://cmc.exchange-cdn.com:8080/images/movies//tMeWcpzzjvo6Y0955zRHk5lX9ak.jpg"
        expected = "https://image.tmdb.org/t/p/w500/tMeWcpzzjvo6Y0955zRHk5lX9ak.jpg"
        self.assertEqual(sanitize_logo_url(url), expected)

    def test_exchange_cdn_series_url_with_double_slash(self):
        url = "http://cmc.exchange-cdn.com:8080/images/series//uP7bWcpzzjvo6Y0955zRHk5lX9ak.png"
        expected = "https://image.tmdb.org/t/p/w500/uP7bWcpzzjvo6Y0955zRHk5lX9ak.png"
        self.assertEqual(sanitize_logo_url(url), expected)

    def test_iptv_proxy_tmdb_hash_webp(self):
        url = "http://proxy.iptvserver.net:8080/images/movies/pQWcpzzjvo6Y0955zRHk5lX9ak.webp"
        expected = "https://image.tmdb.org/t/p/w500/pQWcpzzjvo6Y0955zRHk5lX9ak.webp"
        self.assertEqual(sanitize_logo_url(url), expected)

    def test_double_slash_removal_non_tmdb_url(self):
        url = "http://provider.example.com/images/movies//poster_123.jpg"
        expected = "http://provider.example.com/images/movies/poster_123.jpg"
        self.assertEqual(sanitize_logo_url(url), expected)

    def test_tmdb_url_with_double_slash_normalized(self):
        url = "https://image.tmdb.org/t/p/w500//tMeWcpzzjvo6Y0955zRHk5lX9ak.jpg"
        expected = "https://image.tmdb.org/t/p/w500/tMeWcpzzjvo6Y0955zRHk5lX9ak.jpg"
        self.assertEqual(sanitize_logo_url(url), expected)

    def test_valid_tmdb_url_unmodified(self):
        url = "https://image.tmdb.org/t/p/original/tMeWcpzzjvo6Y0955zRHk5lX9ak.jpg"
        self.assertEqual(sanitize_logo_url(url), url)

    def test_whitespace_trimming(self):
        url = "  http://cmc.exchange-cdn.com:8080/images/movies//tMeWcpzzjvo6Y0955zRHk5lX9ak.jpg  "
        expected = "https://image.tmdb.org/t/p/w500/tMeWcpzzjvo6Y0955zRHk5lX9ak.jpg"
        self.assertEqual(sanitize_logo_url(url), expected)

    def test_empty_or_invalid_inputs(self):
        self.assertEqual(sanitize_logo_url(""), "")
        self.assertEqual(sanitize_logo_url(None), None)


class VODLogoModelSaveTests(TestCase):
    def test_model_save_sanitizes_url(self):
        logo = VODLogo.objects.create(
            name="Test Movie",
            url="http://cmc.exchange-cdn.com:8080/images/movies//tMeWcpzzjvo6Y0955zRHk5lX9ak.jpg"
        )
        self.assertEqual(logo.url, "https://image.tmdb.org/t/p/w500/tMeWcpzzjvo6Y0955zRHk5lX9ak.jpg")
