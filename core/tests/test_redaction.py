"""Tests for credential redaction."""

import logging
import sys

from django.test import SimpleTestCase

from core.redaction import (
    RedactingFormatter,
    redact_mapping,
    redact_text,
    redact_url,
)


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
        # The endpoint names the role: player_api/get/panel_api are the
        # provider API, xmltv.php serves the EPG guide.
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
        # No Xtream type segment - must not be masked.
        for path in ("/channels", "/api/core/settings/", "/stats/events"):
            self.assertEqual(redact_text(f"GET {path}"), f"GET {path}")

    def test_masks_userinfo_in_url(self):
        out = redact_text("proxy http://joe:s3cret@host:8080/path")
        self.assertNotIn("s3cret", out)
        self.assertNotIn("joe:s3cret", out)
        self.assertIn("://[username]:[password]@host:8080", out)

    def test_masks_userinfo_with_at_in_username(self):
        # Greedy to the last '@' so an email-shaped username doesn't leak the password.
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
        # A sensitive word as a delimiter-bounded segment of a longer key.
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
        # Quoted dict keys defeat the plain kv/query patterns.
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
        # A bare provider base URL has no shape; the url label is the signal.
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
        # The shape requests exception text uses; port and prose survive.
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
        # No Xtream type segment - must not be mistaken for user/pass.
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
        # Every replacement is a fixed point, so re-sweeping masked text is a no-op.
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


class RedactUrlTests(SimpleTestCase):
    def test_reduces_to_scheme_and_host(self):
        self.assertEqual(
            redact_url("http://host.tld/live/joe/s3cret/1.ts"),
            "http://host.tld/...",
        )

    def test_drops_userinfo(self):
        self.assertEqual(
            redact_url("http://joe:s3cret@host.tld/x"), "http://host.tld/..."
        )

    def test_drops_userinfo_with_at_in_username(self):
        # Split on the last '@' so an email-shaped username doesn't leak the password.
        self.assertEqual(
            redact_url("http://joe@mail.com:s3cret@host.tld/x"),
            "http://host.tld/...",
        )

    def test_non_url_passthrough(self):
        self.assertEqual(redact_url("not a url"), "not a url")
        self.assertEqual(redact_url(None), None)


class RedactMappingTests(SimpleTestCase):
    def test_masks_sensitive_keys(self):
        out = redact_mapping(
            {
                "username": "joe",
                "password": "s3cret",
                "xc_password": "s3cret",
                "api_token": "abc",
                "channel_name": "CNN",
            }
        )
        self.assertEqual(out["password"], "[password]")
        self.assertEqual(out["xc_password"], "[xc_password]")
        self.assertEqual(out["api_token"], "[api_token]")
        self.assertEqual(out["channel_name"], "CNN")  # non-sensitive kept

    def test_masks_hyphenated_and_authorization_keys(self):
        out = redact_mapping(
            {
                "X-Api-Key": "sk-secret",
                "Authorization": "Bearer eyJ",
                "Accept": "application/json",
            }
        )
        self.assertEqual(out["X-Api-Key"], "[x-api-key]")
        self.assertEqual(out["Authorization"], "[authorization]")
        self.assertEqual(out["Accept"], "application/json")

    def test_url_valued_key_masked_by_content_not_key_name(self):
        # The credentialed URL value is masked by content; structure stays.
        out = redact_mapping(
            {"stream_url": "http://host.tld/live/joe/s3cret/1.ts"}
        )
        self.assertNotIn("s3cret", out["stream_url"])
        self.assertIn("host.tld", out["stream_url"])

    def test_url_keys_reduced_to_host_only(self):
        # Any *_url value is reduced to scheme://host/... (drops path/query secrets).
        out = redact_mapping(
            {
                "logo_url": "http://host.tld/logos/cnn.png",
                "webhook_url": "http://host.tld/api/webhook/fakeslug9988",
            }
        )
        self.assertEqual(out["logo_url"], "http://host.tld/...")
        self.assertEqual(out["webhook_url"], "http://host.tld/...")
        self.assertNotIn("fakeslug9988", out["webhook_url"])  # slug dropped

    def test_masks_signature_and_sig_dict_keys(self):
        out = redact_mapping({"signature": "RAWSIG==", "sig": "abc123"})
        self.assertEqual(out["signature"], "[signature]")
        self.assertEqual(out["sig"], "[sig]")
        # ...but sig_alg / signature_version are metadata, not secrets
        meta = redact_mapping({"sig_alg": "RS256", "signature_version": "1.0"})
        self.assertEqual(meta["sig_alg"], "RS256")
        self.assertEqual(meta["signature_version"], "1.0")

    def test_preserves_type_of_non_string_sensitive_values(self):
        # A sensitive-keyed non-string is metadata about a secret; keep it and its type.
        out = redact_mapping(
            {
                "has_password": True,
                "is_secret": False,
                "token_count": 42,
                "token_bucket": {"capacity": 10, "rate": 5},
            }
        )
        self.assertIs(out["has_password"], True)
        self.assertIs(out["is_secret"], False)
        self.assertEqual(out["token_count"], 42)
        self.assertEqual(out["token_bucket"], {"capacity": 10, "rate": 5})

    def test_still_masks_real_secret_keys(self):
        out = redact_mapping(
            {"secret_key": "django-insecure-x", "access_token": "A.B.C"}
        )
        self.assertEqual(out["secret_key"], "[secret_key]")
        self.assertEqual(out["access_token"], "[access_token]")

    def test_masks_bare_pass_and_passphrase_keys(self):
        # "pass"/"passphrase" are sensitive as whole words; lookalikes must survive.
        out = redact_mapping(
            {
                "pass": "s3cret",
                "xc_pass": "s3cret",
                "passphrase": "correct-horse",
                "passenger_count": 4,
                "compass_heading": "NW",
            }
        )
        self.assertEqual(out["pass"], "[pass]")
        self.assertEqual(out["xc_pass"], "[xc_pass]")
        self.assertEqual(out["passphrase"], "[passphrase]")
        self.assertEqual(out["passenger_count"], 4)  # lookalike kept
        self.assertEqual(out["compass_heading"], "NW")  # lookalike kept

    def test_masks_scalar_secrets_in_sensitive_list(self):
        # A sensitive key proves the whole value secret; lists mask element-wise.
        out = redact_mapping(
            {
                "tokens": ["abc123", "def456"],
                "api_keys": ("sk-one", "sk-two"),
                "credentials": [{"password": "p1"}, "raw-secret"],
            }
        )
        self.assertEqual(out["tokens"], ["[tokens]", "[tokens]"])
        self.assertEqual(out["api_keys"], ("[api_keys]", "[api_keys]"))
        self.assertIsInstance(out["api_keys"], tuple)  # type preserved
        self.assertEqual(out["credentials"][0]["password"], "[password]")
        self.assertEqual(out["credentials"][1], "[credentials]")

    def test_does_not_mask_lookalike_keys(self):
        # Whole-word key matching: sensitive substrings alone must not trigger.
        out = redact_mapping(
            {
                "secretary": "Jane Smith",
                "tokenizer": "bpe",
                "hourly_rate": 25,
                "curling_channel": "Winter Sports",
                "user_agent": "TiviMate/5.0",
                "username": "joe",
            }
        )
        self.assertEqual(out["secretary"], "Jane Smith")
        self.assertEqual(out["tokenizer"], "bpe")
        self.assertEqual(out["hourly_rate"], 25)
        self.assertEqual(out["curling_channel"], "Winter Sports")
        self.assertEqual(out["user_agent"], "TiviMate/5.0")
        self.assertEqual(out["username"], "joe")  # deliberate: identifier kept

    def test_sweeps_non_sensitive_string_values(self):
        out = redact_mapping(
            {"message": "connect http://host/live/joe/s3cret/1.ts failed"}
        )
        self.assertNotIn("s3cret", out["message"])

    def test_recurses_nested_structures(self):
        out = redact_mapping(
            {"a": {"password": "s3cret"}, "b": [{"token": "t"}, "clean"]}
        )
        self.assertEqual(out["a"]["password"], "[password]")
        self.assertEqual(out["b"][0]["token"], "[token]")
        self.assertEqual(out["b"][1], "clean")

    def test_does_not_mutate_input(self):
        source = {"password": "s3cret"}
        redact_mapping(source)
        self.assertEqual(source["password"], "s3cret")


class RedactingFormatterTests(SimpleTestCase):
    def _record(self, msg, *args, exc_info=None):
        return logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg=msg,
            args=args,
            exc_info=exc_info,
        )

    def test_masks_interpolated_message(self):
        formatter = RedactingFormatter("%(message)s")
        record = self._record(
            "URL: %s", "http://host/live/joe/s3cret/1.ts"
        )
        out = formatter.format(record)
        self.assertNotIn("s3cret", out)
        self.assertIn("/live/[username]/[password]/", out)

    def test_masks_credentials_in_traceback(self):
        formatter = RedactingFormatter("%(message)s")
        try:
            raise ValueError(
                "auth failed for http://host/live/joe/s3cret/1.ts"
            )
        except ValueError:
            record = self._record("boom", exc_info=sys.exc_info())
        out = formatter.format(record)
        self.assertNotIn("s3cret", out)
        self.assertIn("/live/[username]/[password]/", out)
