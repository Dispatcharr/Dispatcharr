"""Tests for credential redaction."""

import os
import random
import re
import subprocess
import sys
import time

from django.test import SimpleTestCase

from dispatcharr import log_collector

from dispatcharr import log_redaction
from dispatcharr.log_redaction import redact_text


class RedactTextTests(SimpleTestCase):
    def test_masks_xtream_path_credentials(self):
        out = redact_text(
            "Starting stream for URL: http://prov.example.com/live/joe/s3cret/123.ts"
        )
        self.assertNotIn("joe", out)
        self.assertNotIn("s3cret", out)
        self.assertNotIn("prov.example.com", out)
        self.assertIn("://[provider_host]/live/[username]/[password]/", out)

    def test_masks_provider_and_epg_hosts_in_xc_api_urls(self):
        for endpoint in ("player_api.php", "get.php", "panel_api.php"):
            out = redact_text(
                f"refresh http://prov.example.com/{endpoint}?username=joe&password=s3cret"
            )
            self.assertNotIn("prov.example.com", out, endpoint)
            self.assertIn(f"://[provider_host]/{endpoint}", out, endpoint)
        epg = redact_text(
            "fetch http://prov.example.com/xmltv.php?username=joe&password=s3cret"
        )
        self.assertNotIn("prov.example.com", epg)
        self.assertIn("://[epg_host]/xmltv.php", epg)
        self.assertIn("username=[username]", epg)
        self.assertIn("password=[password]", epg)

    def test_no_type_segment_url_is_left_alone(self):
        # Two bare segments after the host are ambiguous with REST routes; not masked.
        out = redact_text("connecting to http://host/joe/notacred/900.ts")
        self.assertEqual(out, "connecting to http://host/joe/notacred/900.ts")

    def test_masks_scheme_less_path_credentials(self):
        # request.get_full_path() / access-log URIs have no scheme://host.
        out = redact_text("GET /live/joe/s3cret/500.ts")
        self.assertNotIn("s3cret", out)
        self.assertNotIn("/joe/", out)
        self.assertIn("/live/[username]/[password]/", out)
        for seg in ("movie", "series", "timeshift"):
            self.assertNotIn(
                "s3cret", redact_text(f"/{seg}/joe/s3cret/1.ts"), seg
            )

    def test_leaves_ordinary_paths_untouched(self):
        for path in ("/channels", "/api/core/settings/", "/stats/events"):
            self.assertEqual(redact_text(f"GET {path}"), f"GET {path}")

    def test_masks_userinfo_in_url(self):
        out = redact_text("proxy http://joe:s3cret@host:8080/path")
        self.assertNotIn("s3cret", out)
        self.assertNotIn("joe:s3cret", out)
        self.assertIn("://[username]:[password]@host:8080", out)

    def test_masks_userinfo_with_at_in_username(self):
        out = redact_text("proxy http://joe@mail.com:s3cret@host:8080/path")
        self.assertNotIn("s3cret", out)
        self.assertIn("://[username]:[password]@host:8080", out)

    def test_masks_query_credentials(self):
        out = redact_text(
            "GET /player_api.php?username=joe&password=s3cret&action=x"
        )
        self.assertNotIn("joe", out)
        self.assertNotIn("s3cret", out)
        self.assertIn("username=[username]", out)
        self.assertIn("password=[password]", out)
        self.assertIn("action=x", out)

    def test_masks_key_value_assignments(self):
        self.assertEqual(
            redact_text("password=hunter2 done"), "password=[password] done"
        )
        self.assertEqual(redact_text('token: "abc123"'), "token: [token]")

    def test_masks_compound_key_assignments(self):
        self.assertEqual(
            redact_text("xc_password=s3cret"), "xc_password=[xc_password]"
        )
        self.assertEqual(
            redact_text("access_token=A.B.C"), "access_token=[access_token]"
        )
        self.assertNotIn("hunter2", redact_text("client_secret: hunter2"))
        self.assertNotIn("sk-live-1", redact_text("my-api-key=sk-live-1"))
        out = redact_text("params {'xc_password': 'hunter2'}")
        self.assertNotIn("hunter2", out)
        self.assertIn("'xc_password': '[xc_password]'", out)

    def test_does_not_mask_substring_lookalike_assignments(self):
        # No delimiter before the keyword - must not trigger masking.
        for text in (
            "compass=NW",
            "bypass=true",
            "overpass=x",
            "user_agent=TiviMate/5.0",
            "content_type=json",
            "tokenizer=bpe",
            "passenger_count=4",
            "curl: -X GET",
        ):
            self.assertEqual(redact_text(text), text)

    def test_masks_credentials_in_dict_repr(self):
        out = redact_text(
            "XC request params: {'username': 'joe', 'password': 'hunter2'}"
        )
        self.assertNotIn("joe", out)
        self.assertNotIn("hunter2", out)
        self.assertIn("'username': '[username]'", out)
        self.assertIn("'password': '[password]'", out)

    def test_masks_authorization_and_api_key_headers(self):
        out = redact_text(
            "headers: {'Authorization': 'Bearer eyJabc.def.ghi', "
            "'X-Api-Key': 'sk-livesecret', 'Accept': 'application/json'}"
        )
        self.assertNotIn("eyJabc.def.ghi", out)
        self.assertNotIn("sk-livesecret", out)
        self.assertIn("'Authorization': '[authorization]'", out)
        self.assertIn("'X-Api-Key': '[x-api-key]'", out)
        self.assertIn("application/json", out)  # non-sensitive header kept

    def test_masks_bearer_token_free_text(self):
        self.assertEqual(redact_text("token=abc123def"), "token=[token]")

    def test_masks_cdn_signed_url_params(self):
        out = redact_text(
            "GET http://cdn.tld/x.m3u8?token=t1&Signature=sIg9aBc&sig=short"
        )
        self.assertNotIn("sIg9aBc", out)
        self.assertIn("cdn.tld", out)  # not an XC endpoint - host survives
        self.assertIn("token=[token]", out)
        self.assertIn("Signature=[signature]", out)
        self.assertIn("sig=[sig]", out)

    def test_masks_authorization_bearer_free_text(self):
        # The token after the auth scheme word must be masked with it.
        for line in (
            "Authorization: Bearer abcXYZ123SEKRET",
            "Outgoing request Authorization: Bearer eyJ.a.b to upstream",
            "headers authorization=Basic dXNlcjpwYXNz done",
        ):
            out = redact_text(line)
            self.assertNotIn("SEKRET", out)
            self.assertNotIn("eyJ.a.b", out)
            self.assertNotIn("dXNlcjpwYXNz", out)
            self.assertIn("[authorization]", out)

    def test_masks_url_labeled_values(self):
        out = redact_text("Processing XC account 2 with URL: https://portal.example")
        self.assertNotIn("portal.example", out)
        self.assertIn("URL: [url]", out)
        self.assertEqual(
            redact_text("server_url=https://portal.example"),
            "server_url=[server_url]",
        )
        # Values the URL battery already masked keep their informative shape.
        line = "Transformed URL: https://[provider_host]/live/[username]/[password]/1.ts"
        self.assertEqual(redact_text(line), line)

    def test_masks_quoted_host_assignments(self):
        out = redact_text(
            "HTTPSConnectionPool(host='portal.example', port=443): "
            "Max retries exceeded with url: /playlist.m3u8"
        )
        self.assertNotIn("portal.example", out)
        self.assertNotIn("/playlist.m3u8", out)
        self.assertIn("host='[host]'", out)
        self.assertIn("port=443", out)
        self.assertIn("url: [url]", out)

    def test_does_not_mask_ordinary_rest_urls(self):
        for url in (
            "http://host.tld/api/core/settings/",
            "http://host.tld/api/channels/logos/5/cache/",
            "http://host.tld/stream/123e4567-e89b-12d3-a456-426614174000/",
        ):
            self.assertEqual(redact_text(f"fetch {url}"), f"fetch {url}", url)

    def test_leaves_clean_text_untouched(self):
        line = "Scanning disk for The Crash Reel"
        self.assertEqual(redact_text(line), line)

    def test_is_idempotent_over_masked_text(self):
        for line in (
            "http://host/live/joe/s3cret/1.ts",
            "proxy http://joe:s3cret@host:8080/path",
            "?username=joe&password=s3cret",
            "params {'xc_password': 'hunter2'}",
            "Authorization: Bearer abcXYZ",
            "http://host/player_api.php?username=joe&password=s3cret",
            "http://host/xmltv.php?username=joe",
            "Processing XC account 2 with URL: https://portal.example",
            "HTTPSConnectionPool(host='portal.example', port=443): "
            "Max retries exceeded with url: /playlist.m3u8",
        ):
            once = redact_text(line)
            self.assertEqual(redact_text(once), once, line)

    def test_non_string_passthrough(self):
        self.assertEqual(redact_text(None), None)
        self.assertEqual(redact_text(42), 42)
        self.assertEqual(redact_text(""), "")


class TriggerScanTests(SimpleTestCase):
    """redact_text() skips the battery on one scan; a false negative is a leak."""

    KEYS = (
        "username", "user", "password", "passwd", "pass", "secret", "signature",
        "sig", "authorization", "auth_token", "auth-token", "authtoken", "bearer",
        "x_api_key", "x-api-key", "api_key", "api-key", "apikey", "token", "url",
        "cookie", "passphrase", "credential", "credentials",
    )
    PREFIXES = ("", "xc_", "account.", "provider-", "a.b_")
    CONTEXTS = (
        "{key}={value}",
        "?channel=1&{key}={value}",
        "{key}: {value}",
        "{key} = {value}",
        "{key}:{value}",
        "'{key}': '{value}'",
        '"{key}": "{value}"',
        "Authorization: Bearer {value} {key}={value}",
    )
    TOKENS = (
        "user", "password", "xc_password", "token", "url", "host", "sig", "apikey",
        "http://portal.example", "/live/", "/movie/", "/xmltv.php", "u1", "p1",
        "=", ":", " ", "'", '"', "&", "?", "/", "@", ".ts", "compass", "bypass",
        "user_agent", "message", "[username]", "[password]", "2026-08-18",
    )

    def assert_gate_agrees(self, line):
        """Return whether the battery masked *line*, so callers can prove substance."""
        masked = log_redaction._apply(line)
        self.assertEqual(redact_text(line), masked, repr(line))
        return masked != line

    def test_the_key_list_still_covers_the_pattern(self):
        for fragment in log_redaction._KEY_ALT.split("|"):
            pattern = re.compile(f"^(?:{fragment})$", re.IGNORECASE)
            self.assertTrue(any(pattern.match(key) for key in self.KEYS), fragment)

    def test_every_key_shape_reaches_the_battery(self):
        total = masked = 0
        for key in self.KEYS:
            for prefix in self.PREFIXES:
                for context in self.CONTEXTS:
                    body = context.format(key=prefix + key, value="portalpass")
                    total += 1
                    masked += self.assert_gate_agrees(
                        f"2026-08-18 01:00:00,100 INFO apps.m3u.tasks {body}"
                    )
        # Agreement on lines nothing masks would prove nothing.
        self.assertGreater(masked, total * 0.9)

    def test_failure_prose_reaches_the_battery(self):
        # These carry no key, no scheme and no stream path: the trigger scan is
        # the only thing standing between them and an unmasked hostname.
        for body in (
            "Failed to resolve 'portal.example'",
            "could not resolve hostname 'portal.example'",
            "connection to portal.example timed out",
        ):
            self.assertTrue(
                self.assert_gate_agrees(
                    f"2026-08-18 01:00:00,100 ERROR apps.m3u.tasks {body}"
                ),
                body,
            )
            # Bare, as redact_text() is also called on strings that are not log lines.
            self.assertTrue(self.assert_gate_agrees(body), body)

    def test_url_and_stream_path_shapes_reach_the_battery(self):
        for body in (
            "GET /live/portaluser/portalpass/1.ts",
            "GET /TimeShift/portaluser/portalpass/1.ts",
            "fetch http://portal.example/player_api.php",
            "fetch HTTP://portal.example/xmltv.php",
            "proxy http://portaluser:portalpass@portal.example:8080/path",
            "HTTPSConnectionPool(host='portal.example', port=443)",
        ):
            self.assertTrue(
                self.assert_gate_agrees(
                    f"2026-08-18 01:00:00,100 INFO apps.m3u.tasks {body}"
                ),
                body,
            )

    def test_token_soup_agrees(self):
        rng = random.Random(20260822)
        masked = 0
        for _ in range(4000):
            line = "".join(
                rng.choice(self.TOKENS) for _ in range(rng.randint(1, 12))
            )
            masked += self.assert_gate_agrees(line)
        self.assertGreater(masked, 100)

    def test_a_long_dotted_token_is_scanned_once(self):
        line = f"2026-08-18 01:00:00,100 DEBUG x token {'a.b-c_' * 3200}=v"
        start = time.perf_counter()
        redact_text(line)
        self.assertLess(time.perf_counter() - start, 0.5)

    def test_a_colon_run_after_a_scheme_is_scanned_once(self):
        line = f"2026-08-18 01:00:00,100 DEBUG x http://{'a:' * 20000}"
        start = time.perf_counter()
        redact_text(line)
        self.assertLess(time.perf_counter() - start, 0.5)


class CollectorIsolationTests(SimpleTestCase):
    """The collector is started by path so it stays free of the app package."""

    def test_importing_it_as_a_script_pulls_in_neither_celery_nor_django(self):
        pkg = os.path.dirname(os.path.abspath(log_collector.__file__))
        code = (
            "import sys; sys.path.insert(0, sys.argv[1]); import log_collector; "
            "print(any(m in sys.modules for m in ('celery', 'django')))"
        )
        out = subprocess.run(
            [sys.executable, "-c", code, pkg], capture_output=True, text=True
        )
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stdout.strip(), "False")
