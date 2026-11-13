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

    def test_masks_type_less_xtream_urls(self):
        # The live shape M3U playlists list: host/user/pass/<id>, no type segment.
        for line, masked in (
            (
                "connecting to http://host/joe/s3cret/900.ts",
                "connecting to http://[provider_host]/[username]/[password]/900.ts",
            ),
            (
                "handing off to http://prov.example:8080/joe/s3cret/123456",
                "handing off to http://[provider_host]/[username]/[password]/123456",
            ),
            (
                "http://prov.example/joe/s3cret/900.ts: Server returned 403",
                "http://[provider_host]/[username]/[password]/900.ts: Server returned 403",
            ),
            (
                "Error opening input file http://prov.example/joe/s3cret/900.",
                "Error opening input file http://[provider_host]/[username]/[password]/900.",
            ),
            (
                "connecting to http://[2001:db8::1]:8080/joe/s3cret/900.ts",
                "connecting to http://[provider_host]/[username]/[password]/900.ts",
            ),
        ):
            self.assertEqual(redact_text(line), masked, line)
        # A bare path is ambiguous with REST routes, and /api/ is never a stream.
        for line in ("GET /joe/notacred/900.ts", "fetch http://host.tld/api/channels/5"):
            self.assertEqual(redact_text(line), line, line)

    def test_masks_xtream_servers_under_a_sub_path(self):
        self.assertEqual(
            redact_text("from 'http://prov.example:8080/xc/live/joe/s3cret/1.ts'"),
            "from 'http://[provider_host]/xc/live/[username]/[password]/1.ts'",
        )
        self.assertEqual(
            redact_text("GET /xc/live/joe/s3cret/1.ts"),
            "GET /xc/live/[username]/[password]/1.ts",
        )
        self.assertIn(
            "://[provider_host]/panel/player_api.php",
            redact_text("http://prov.example/panel/player_api.php?username=joe"),
        )
        self.assertIn(
            "://[epg_host]/panel/xmltv.php",
            redact_text("http://prov.example/panel/xmltv.php?username=joe"),
        )

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
        for path in (
            "/channels",
            "/api/core/settings/",
            "/stats/events",
            "/api/vod/series/5/episodes/",
            "/proxy/vod/movie/3fa85f64-5717-4562-b3fc-2c963f66afa6/abc123/2/",
        ):
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
        self.assertEqual(redact_text("secret: [hunter2]"), "secret: [secret]")

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

    def test_masks_dict_values_holding_the_other_quote(self):
        # repr() switches to double quotes for a value with an apostrophe.
        for line, masked in (
            ("{'password': \"it's\"}", "{'password': \"[password]\"}"),
            ("{'password': 'a\"b'}", "{'password': '[password]'}"),
            ("{'password': 'a\\'b\"c'}", "{'password': '[password]'}"),
        ):
            self.assertEqual(redact_text(line), masked, line)

    def test_masks_url_labelled_dict_and_json_values(self):
        out = redact_text(
            "metadata {'url': 'http://portal.example/hls/joe/s3cret/i.m3u8', 'state': 'active'}"
        )
        self.assertEqual(out, "metadata {'url': '[url]', 'state': 'active'}")
        self.assertEqual(
            redact_text('{"stream_url": "http://portal.example:8080/x"}'),
            '{"stream_url": "[stream_url]"}',
        )
        line = "{'url': 'http://[provider_host]/live/[username]/[password]/1.ts'}"
        self.assertEqual(redact_text(line), line)
        self.assertEqual(
            redact_text("{'url': 'http://joe:s3cret@portal.example/'}"),
            "{'url': '[url]'}",
        )

    def test_masks_user_only_as_a_query_parameter(self):
        self.assertEqual(
            redact_text("GET /get.php?user=joe&pass=s3cret&type=m3u"),
            "GET /get.php?user=[user]&pass=[pass]&type=m3u",
        )
        self.assertEqual(
            redact_text("fetch http://portal.example/x?xc_user=joe"),
            "fetch http://portal.example/x?xc_user=[xc_user]",
        )
        line = "Login failed: user=alice ip=192.0.2.4"
        self.assertEqual(redact_text(line), line)

    def test_masks_every_cookie_in_a_header_line(self):
        self.assertEqual(
            redact_text("Cookie: sessionid=9f2k3jx8; csrftoken=Qw3 next"),
            "Cookie: [cookie] next",
        )
        self.assertEqual(
            redact_text("Set-Cookie: PHPSESSID=8a2b; path=/; HttpOnly"),
            "Set-Cookie: [set-cookie]",
        )

    def test_masks_username_only_userinfo(self):
        self.assertEqual(
            redact_text("proxy http://joe@portal.example:8080/path"),
            "proxy http://[username]@portal.example:8080/path",
        )

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
        # Masked userinfo alone still leaves the host, so the whole value goes.
        self.assertEqual(
            redact_text("url=http://joe:s3cret@portal.example/x"), "url=[url]"
        )

    def test_an_already_masked_value_keeps_its_closing_quote(self):
        line = '{"url":"http://h/get.php?username=joe&password=s3cret","name":"Sports HD"}'
        self.assertEqual(
            redact_text(line),
            '{"url":"http://[provider_host]/get.php?username=[username]'
            '&password=[password]","name":"Sports HD"}',
        )

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
            "http://host.tld/api/vod/series/5/provider-info/",
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
            "{'password': \"it's\"}",
            "{'url': 'http://portal.example/x'}",
            "?user=joe&pass=s3cret",
            "Cookie: sessionid=9f2k3jx8; csrftoken=Qw3",
            "proxy http://joe@portal.example/path",
            '{"url":"http://h/get.php?password=s3cret","name":"Sports HD"}',
            "connecting to http://host/joe/s3cret/900.ts",
            "url=http://joe:s3cret@portal.example/x",
            "http://prov.example/joe/s3cret/900.ts: Server returned 403",
            "connecting to http://[2001:db8::1]:8080/joe/s3cret/900.ts",
            "secret: [hunter2]",
        ):
            once = redact_text(line)
            self.assertEqual(redact_text(once), once, line)

    def test_non_string_passthrough(self):
        self.assertEqual(redact_text(None), None)
        self.assertEqual(redact_text(42), 42)
        self.assertEqual(redact_text(""), "")


class CookieListAndProseTests(SimpleTestCase):
    def test_masks_cookie_headers_in_dict_repr(self):
        out = redact_text(
            "headers: {'Cookie': 'sessionid=9f2k3jx8; csrftoken=Qw3', 'Accept': '*/*'}"
        )
        self.assertNotIn("9f2k3jx8", out)
        self.assertIn("'Cookie': '[cookie]'", out)
        self.assertIn("'Accept': '*/*'", out)
        out2 = redact_text("{'Set-Cookie': 'PHPSESSID=8a2bs3cret; path=/'}")
        self.assertNotIn("8a2bs3cret", out2)
        self.assertIn("'Set-Cookie': '[set-cookie]'", out2)

    def test_cookie_lookalikes_survive(self):
        self.assertEqual(redact_text("cookiejar=default"), "cookiejar=default")

    def test_masks_hostnames_in_dns_failure_prose(self):
        out = redact_text("Failed to resolve 'portal.example' ([Errno -2])")
        self.assertNotIn("portal.example", out)
        self.assertIn("Failed to resolve '[host]'", out)
        out2 = redact_text(
            "Could not resolve hostname 'portal.example': Name or service not known"
        )
        self.assertNotIn("portal.example", out2)
        out3 = redact_text("Connection to portal.example timed out. (connect timeout=5)")
        self.assertNotIn("portal.example", out3)
        self.assertIn("Connection to [host] timed out", out3)

    def test_masks_sensitive_list_values(self):
        out = redact_text(
            "params: {'token': ['eyJhbGciOiJIUzI1NiJ9.abc'], 'utc_start': ['2026-08-01']}"
        )
        self.assertNotIn("eyJ", out)
        self.assertIn("'token': ['[token]']", out)
        self.assertIn("utc_start", out)

    def test_battery_additions_are_idempotent(self):
        for line in (
            "headers: {'Cookie': 'sessionid=9f2k3jx8'}",
            "Failed to resolve 'portal.example'",
            "Connection to portal.example timed out",
            "{'token': ['eyJx.y.z']}",
        ):
            once = redact_text(line)
            self.assertEqual(redact_text(once), once, line)


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

    def test_every_key_alone_opens_the_word_gate(self):
        # The value holds no gate word, so only the key can open the gate.
        total = masked = 0
        for key in self.KEYS:
            for prefix in self.PREFIXES:
                for context in self.CONTEXTS[:-1]:
                    body = context.format(key=prefix + key, value="hunter2")
                    total += 1
                    masked += self.assert_gate_agrees(
                        f"2026-08-18 01:00:00,100 INFO apps.m3u.tasks {body}"
                    )
        self.assertGreater(masked, total * 0.9)
        # IGNORECASE folds these non-ASCII letters onto ASCII ones.
        for body in (
            "pa\u017f\u017fword=hunter2", "to\u212aen=hunter2", "GET /l\u0131ve/a/b/1.ts"
        ):
            self.assertTrue(self.assert_gate_agrees(body), body)

    def test_failure_prose_reaches_the_battery(self):
        # These carry no key, no scheme and no stream path: the trigger scan is
        # the only thing standing between them and an unmasked hostname.
        for body in (
            "Failed to resolve 'portal.example'",
            "could not resolve hostname 'portal.example'",
            "connection to portal.example timed out",
            "FAILED TO RESOLVE 'portal.example'",
            "Connection to portal.example Timed Out",
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

    def test_mixed_case_stream_paths_reach_the_battery_bare(self):
        # No ':' or '=' here: only the word check stands between these and the battery.
        for body in (
            "GET /LIVE/portaluser/portalpass/1.ts",
            "GET /TimeShift/portaluser/portalpass/1.ts",
        ):
            self.assertTrue(self.assert_gate_agrees(body), body)

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
