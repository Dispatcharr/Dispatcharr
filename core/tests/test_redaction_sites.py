"""Tests for the provider-context redaction helpers."""

from django.test import SimpleTestCase

from core.redaction import redact_provider_text, redact_provider_url


class RedactProviderUrlTests(SimpleTestCase):
    def test_masks_bare_base_url_host(self):
        self.assertEqual(
            redact_provider_url("https://portal.example"),
            "https://[provider_host]",
        )

    def test_keeps_path_and_masks_query_credentials(self):
        self.assertEqual(
            redact_provider_url(
                "https://portal.example/playlist.m3u8?username=joe&password=s3cret"
            ),
            "https://[provider_host]/playlist.m3u8"
            "?username=[username]&password=[password]",
        )

    def test_masks_userinfo_and_host(self):
        self.assertEqual(
            redact_provider_url("http://joe:s3cret@portal.example:8080/x"),
            "http://[username]:[password]@[provider_host]/x",
        )

    def test_caller_supplied_token(self):
        self.assertEqual(
            redact_provider_url("http://epg.example/guide.xml", "[epg_host]"),
            "http://[epg_host]/guide.xml",
        )

    def test_non_url_passthrough(self):
        self.assertEqual(
            redact_provider_url("/data/epg/guide.xml"), "/data/epg/guide.xml"
        )
        self.assertEqual(redact_provider_url(None), None)


class RedactProviderTextTests(SimpleTestCase):
    def test_reduces_unshaped_urls(self):
        out = redact_provider_text(
            "bogus segment http://portal.example:8080/hls/joe/s3cret/seg1.ts ignored"
        )
        self.assertNotIn("portal.example", out)
        self.assertNotIn("s3cret", out)
        self.assertIn("http://[provider_host]/...", out)
        self.assertIn("ignored", out)

    def test_keeps_shaped_composites(self):
        self.assertEqual(
            redact_provider_text("fetch http://portal.example/live/joe/s3cret/1.ts done"),
            "fetch http://[provider_host]/live/[username]/[password]/1.ts done",
        )

    def test_caller_supplied_token(self):
        out = redact_provider_text(
            "logo http://img.example/l.png missing", "[image_host]"
        )
        self.assertIn("http://[image_host]/...", out)

    def test_is_idempotent(self):
        for line in (
            "bogus segment http://portal.example:8080/hls/joe/s3cret/seg1.ts",
            "fetch http://portal.example/live/joe/s3cret/1.ts",
            "Response headers: {'Set-Cookie': 'sid=abc; domain=.portal.example'}",
        ):
            once = redact_provider_text(line)
            self.assertEqual(redact_provider_text(once), once, line)

    def test_non_string_passthrough(self):
        self.assertEqual(redact_provider_text(None), None)
        self.assertEqual(redact_provider_text(42), 42)
