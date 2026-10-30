"""Log privacy is unconditional, including exception output and old exports."""

import io
import logging
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest import TestCase, mock

from dispatcharr.log_redaction import (
    REDACTED,
    redact_log_bytes,
    redact_log_data,
    redact_log_text,
    redacted_log_lines,
)
from dispatcharr.startup_log import DisplayTimezoneFormatter, startup_log


class LogRedactionTests(TestCase):
    def test_structured_details_mask_nested_credentials_without_mutating_input(self):
        original = {
            "message": (
                "Forbidden https://example.invalid/player_api.php?password=secret"
            ),
            "nested": [{"username": "alice", "xc_password": "with spaces, and quotes"}],
            "token": ["first-secret", {"value": "second-secret"}],
            "attempts": 3,
            "elapsed": 1.25,
            "active": False,
            "missing": None,
        }
        result = redact_log_data(original)
        self.assertEqual(
            result["nested"],
            [{"username": REDACTED, "xc_password": REDACTED}],
        )
        self.assertEqual(result["token"], REDACTED)
        self.assertEqual(result["attempts"], 3)
        self.assertEqual(result["elapsed"], 1.25)
        self.assertIs(result["active"], False)
        self.assertIsNone(result["missing"])
        self.assertIn("player_api.php", result["message"])
        self.assertNotIn("example.invalid", result["message"])
        self.assertEqual(original["nested"][0]["username"], "alice")
        self.assertEqual(original["token"][0], "first-secret")
        self.assertEqual(redact_log_data(result), result)

    def test_structured_addresses_use_existing_url_policy(self):
        original = {
            "url": "/get.php?username=alice&password=secret&type=m3u_plus",
            "server_host": "example.invalid:8080",
            "stream_url": ["https://example.invalid/live/alice/secret/123.ts"],
            "poster_url": "https://image.tmdb.org/t/p/w500/example.jpg",
            "help_url": "https://dispatcharr.github.io/Dispatcharr-Docs/",
        }
        result = redact_log_data(original)
        self.assertEqual(
            result["url"],
            f"/get.php?username={REDACTED}&password={REDACTED}&type=m3u_plus",
        )
        self.assertEqual(result["server_host"], "redacted.invalid:8080")
        self.assertEqual(
            result["stream_url"],
            [f"https://redacted.invalid/live/{REDACTED}/{REDACTED}/123.ts"],
        )
        self.assertEqual(result["poster_url"], original["poster_url"])
        self.assertEqual(result["help_url"], original["help_url"])
        self.assertEqual(redact_log_data(result), result)

    def test_structured_secret_fields_hide_non_string_values_too(self):
        original = {"PASSWORD": 123456, "Authorization": {"value": "secret"}}
        self.assertEqual(
            redact_log_data(original),
            {"PASSWORD": REDACTED, "Authorization": REDACTED},
        )

    def test_structured_tuple_values_are_redacted_before_json_serialization(self):
        original = ({"password": "secret"}, "https://example.invalid/live/u/p/123.ts")
        self.assertEqual(
            redact_log_data(original),
            (
                {"password": REDACTED},
                f"https://redacted.invalid/live/{REDACTED}/{REDACTED}/123.ts",
            ),
        )
        self.assertEqual(original[0]["password"], "secret")

    def test_structured_diagnostic_labels_and_scalar_types_are_preserved(self):
        original = {
            "account_name": "Provider A",
            "user_agent": "Example Player/1.0",
            "status": 403,
            "error_type": "connection_failed",
            "values": [True, False, None, 0, 1.5],
        }
        self.assertEqual(redact_log_data(original), original)
        self.assertEqual(redact_log_data("status=403"), "status=403")

    def test_direct_collector_script_needs_no_application_bootstrap(self):
        script = Path(__file__).resolve().parents[2] / "dispatcharr/log_collector.py"
        with tempfile.TemporaryDirectory() as log_dir:
            result = subprocess.run(
                [sys.executable, "-S", str(script), log_dir],
                input=b'Failed https://example.invalid?password=secret status=403\n',
                capture_output=True,
                timeout=15,
                check=True,
            )
            self.assertNotIn(b'example.invalid', result.stdout)
            self.assertNotIn(b'secret', result.stdout)
            self.assertIn(b'status=403', result.stdout)

    def test_provider_urls_keep_known_endpoints_but_never_credentials(self):
        cases = (
            (
                "https://user:password@example.invalid/live/user/password/123.ts?token=secret",
                "https://redacted@redacted.invalid/live/"
                f"{REDACTED}/{REDACTED}/123.ts?token={REDACTED}",
            ),
            (
                "http://example.invalid:8080/player_api.php"
                "?username=alice&password=secret&action=get_live_streams",
                "http://redacted.invalid:8080/player_api.php"
                f"?username={REDACTED}&password={REDACTED}&action=get_live_streams",
            ),
            (
                "rtsp://alice:secret@example.invalid/stream",
                f"rtsp://redacted@redacted.invalid/{REDACTED}",
            ),
            (
                r"https:\/\/example.invalid\/player_api.php?password=secret",
                f"https://redacted.invalid/player_api.php?password={REDACTED}",
            ),
            (
                "https%3A%2F%2Fexample.invalid%2Fstream%3Fpassword%3Dsecret",
                f"https://redacted.invalid/{REDACTED}?password={REDACTED}",
            ),
        )
        for url, expected in cases:
            with self.subTest(url=url):
                message = f"Failed {url} status=403"
                result = f"Failed {expected} status=403"
                self.assertEqual(
                    redact_log_text(message), result,
                )
                self.assertEqual(redact_log_text(result), result)

    def test_repeated_json_escaping_cannot_expose_url_credentials(self):
        original = "https://example.invalid/live/alice/secret/123.ts"
        expected = f"https://redacted.invalid/live/{REDACTED}/{REDACTED}/123.ts"
        for depth in (1, 2, 4):
            with self.subTest(depth=depth):
                escaped = original.replace("/", "\\" * depth + "/")
                self.assertEqual(redact_log_text(escaped), expected)
                self.assertEqual(redact_log_text(expected), expected)

    def test_public_poster_and_project_help_urls_remain_readable(self):
        urls = (
            "https://image.tmdb.org/t/p/w500/example.jpg",
            "https://image.tmdb.org/t/p/original/example_poster-1.webp",
            "https://dispatcharr.github.io/Dispatcharr-Docs/",
            "https://dispatcharr.github.io/Dispatcharr-Docs/guides/setup/",
            "https://github.com/Dispatcharr/Dispatcharr/issues/123",
            "https://github.com/Dispatcharr/Dispatcharr/blob/main/CONTRIBUTING.md",
        )
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(redact_log_text(f"Resource {url}"), f"Resource {url}")

    def test_public_url_exceptions_do_not_allow_domain_or_path_spoofing(self):
        urls = (
            "https://image.tmdb.org.evil.invalid/t/p/w500/example.jpg",
            "https://image.tmdb.org/private/alice/secret",
            "https://dispatcharr.github.io/OtherProject/alice/secret",
            "https://github.com/private/alice/secret",
            "https://alice:secret@image.tmdb.org.evil.invalid/t/p/w500/example.jpg",
        )
        for url in urls:
            with self.subTest(url=url):
                result = redact_log_text(url)
                self.assertNotIn("alice", result)
                self.assertNotIn("secret", result)
                self.assertNotIn("evil.invalid", result)
                self.assertEqual(redact_log_text(result), result)

    def test_credentials_and_unknown_values_are_hidden_even_on_public_urls(self):
        url = (
            "https://alice:secret@image.tmdb.org/t/p/w500/example.jpg"
            "?username=alice&password=secret&signature=secret#secret"
        )
        expected = (
            "https://redacted@image.tmdb.org/t/p/w500/example.jpg"
            f"?username={REDACTED}&password={REDACTED}&signature={REDACTED}#{REDACTED}"
        )
        self.assertEqual(redact_log_text(url), expected)
        self.assertEqual(redact_log_text(expected), expected)

    def test_only_known_safe_query_values_are_visible(self):
        url = (
            "https://example.invalid/player_api.php?action=get_vod_info&vod_id=123"
            "&category_id=4&page=2&page_size=50&output=ts&type=m3u_plus"
            "&token=secret&key=secret&unknown=secret&limit=secret&action=secret"
        )
        expected = (
            "https://redacted.invalid/player_api.php?action=get_vod_info&vod_id=123"
            "&category_id=4&page=2&page_size=50&output=ts&type=m3u_plus"
            f"&token={REDACTED}&key={REDACTED}&{REDACTED}={REDACTED}"
            f"&limit={REDACTED}&action={REDACTED}"
        )
        self.assertEqual(redact_log_text(url), expected)
        self.assertEqual(redact_log_text(expected), expected)

    def test_encoded_credentials_and_unknown_query_names_cannot_escape(self):
        cases = (
            "https://example.invalid/player_api.php?%75sername=alice&%70assword=secret",
            "https://example.invalid/live/alice%2Fsecret/secret%3Ftoken/123.ts",
            "https://example.invalid/player_api.php?alice%40secret=secret",
            "https://example.invalid/player_api.php?alice=secret",
            "https://example.invalid/player_api.php?secret",
            "https://example.invalid/player_api.php?password=secret;token=secret",
        )
        for url in cases:
            with self.subTest(url=url):
                result = redact_log_text(f"url='{url}'")
                self.assertNotIn("alice", result)
                self.assertNotIn("secret", result)
                self.assertEqual(redact_log_text(result), result)

    def test_xc_stream_and_timeshift_ids_stay_visible(self):
        for path, expected in (
            ("/movie/alice/secret/123.mp4", f"/movie/{REDACTED}/{REDACTED}/123.mp4"),
            ("/series/alice/secret/456.mkv", f"/series/{REDACTED}/{REDACTED}/456.mkv"),
            ("/live/alice/secret/789", f"/live/{REDACTED}/{REDACTED}/789"),
            (
                "/timeshift/alice/secret/60/2026-10-16:12-00/123.ts",
                f"/timeshift/{REDACTED}/{REDACTED}/60/2026-10-16:12-00/123.ts",
            ),
        ):
            with self.subTest(path=path):
                self.assertEqual(
                    redact_log_text(f"GET https://example.invalid{path} status=403"),
                    f"GET https://redacted.invalid{expected} status=403",
                )

    def test_unknown_path_tails_and_prefixes_are_not_exposed(self):
        for url, expected in (
            (
                "https://example.invalid/alice/secret/player_api.php?action=get_series",
                f"https://redacted.invalid/{REDACTED}/player_api.php?action=get_series",
            ),
            (
                "https://example.invalid/live/alice/secret/private-secret.ts?action=get_series",
                f"https://redacted.invalid/{REDACTED}?action={REDACTED}",
            ),
            (
                "https://example.invalid/private-secret.xml?page=2",
                f"https://redacted.invalid/{REDACTED}?page={REDACTED}",
            ),
        ):
            with self.subTest(url=url):
                self.assertEqual(redact_log_text(url), expected)

    def test_local_urls_and_relative_request_targets_keep_diagnostic_routes(self):
        for text in (
            "GET http://localhost:9191/api/vod/movies/?page=2 status=200",
            "GET http://127.0.0.1:9191/api/status/ status=200",
            "GET http://[::1]:9191/api/core/logs/ status=200",
            "GET /api/core/logs/dispatcharr.log/ HTTP/1.1 200",
            "url='/api/vod/categories/?page_size=50'",
            "broker=redis://localhost:6379/0",
        ):
            with self.subTest(text=text):
                self.assertEqual(redact_log_text(text), text)
        self.assertEqual(
            redact_log_text(
                "GET /get.php?username=alice&password=secret&type=m3u_plus HTTP/1.1 403"
            ),
            f"GET /get.php?username={REDACTED}&password={REDACTED}&type=m3u_plus HTTP/1.1 403",
        )

    def test_labelled_urls_use_the_same_rules_as_unlabelled_urls(self):
        for label in ("url", "server_url", "logo_url", "uri", "--url"):
            with self.subTest(label=label):
                text = f'{label}="https://example.invalid/get.php?password=secret&type=m3u_plus"'
                expected = (
                    f'{label}="https://redacted.invalid/get.php'
                    f'?password={REDACTED}&type=m3u_plus"'
                )
                self.assertEqual(redact_log_text(text), expected)
                self.assertEqual(redact_log_text(expected), expected)

    def test_malformed_urls_and_unsupported_schemes_fail_closed(self):
        for url in (
            "https://example.invalid:secret/get.php?password=secret",
            "https://[bad-address]/secret",
            "file:///home/alice/secret",
        ):
            with self.subTest(url=url):
                self.assertEqual(redact_log_text(url), REDACTED)

    def test_separate_host_fields_hide_addresses_but_keep_ports(self):
        for original, expected in (
            ("host='example.invalid:8080'", "host='redacted.invalid:8080'"),
            ("host='localhost:9191'", "host='localhost:9191'"),
            ("hostname='[::1]:9191'", "hostname='[::1]:9191'"),
            ("host='[2001:db8::1]:8080'", "host='redacted.invalid:8080'"),
        ):
            with self.subTest(original=original):
                self.assertEqual(redact_log_text(original), expected)
                self.assertEqual(redact_log_text(expected), expected)

    def test_unquoted_relative_url_values_with_commas_do_not_leak(self):
        text = "url=/get.php?username=alice&password=secret,another-secret"
        self.assertEqual(
            redact_log_text(text),
            f"url=/get.php?username={REDACTED}&password={REDACTED}",
        )

    def test_oversized_urls_are_redacted_without_parsing_their_fields(self):
        url = "https://example.invalid/player_api.php?password=" + "secret" * 5000
        self.assertEqual(redact_log_text(url), REDACTED)

    def test_endpoint_wrappers_and_non_address_prose_remain_readable(self):
        self.assertEqual(
            redact_log_text("Request failed (https://example.invalid/player_api.php). status=403"),
            "Request failed (https://redacted.invalid/player_api.php). status=403",
        )
        text = "Host not found. URL validation failed."
        self.assertEqual(redact_log_text(text), text)

    def test_labelled_credentials_and_headers_are_removed(self):
        messages = (
            'username=alice password=secret status=403',
            '''{"username": "alice", "password": "secret", "status": 403}''',
            "{'xc_username': 'alice', 'xc_password': 'secret'}",
            "USERNAME: alice; PASSWORD: secret",
            "username alice password secret",
            "username is alice password is secret",
            "--username alice --password 'secret value'",
            'Authorization: Bearer secret',
            'Proxy-Authorization: Basic secret',
            'access_token=secret refresh_token=secret API_KEY=secret',
            'Cookie: sessionid=secret; another=secret',
            'Set-Cookie: sessionid=secret; HttpOnly',
            'password="secret value without a closing quote',
        )
        for message in messages:
            with self.subTest(message=message):
                redacted = redact_log_text(message)
                self.assertNotIn("alice", redacted)
                self.assertNotIn("secret", redacted)
                self.assertIn(REDACTED, redacted)
                self.assertEqual(redact_log_text(redacted), redacted)

    def test_relative_xc_paths_do_not_expose_path_credentials(self):
        for kind in ("live", "movie", "series", "timeshift"):
            with self.subTest(kind=kind):
                redacted = redact_log_text(f'GET /{kind}/alice/secret/123.ts HTTP/1.1 403')
                self.assertEqual(
                    redacted,
                    f'GET /{kind}/{REDACTED}/{REDACTED}/123.ts HTTP/1.1 403',
                )

    def test_split_request_exception_parts_do_not_expose_the_provider(self):
        message = (
            "HTTPConnectionPool(host='example.invalid', port=80): "
            "failed with url: /get.php?username=alice&password=secret"
        )
        redacted = redact_log_text(message)
        for sensitive in ('example.invalid', 'alice', 'secret'):
            self.assertNotIn(sensitive, redacted)
        self.assertIn('port=80', redacted)
        self.assertIn(f'url: /get.php?username={REDACTED}&password={REDACTED}', redacted)

    def test_credential_sql_does_not_expose_positional_values(self):
        line = (
            "ERROR postgres INSERT INTO accounts_user "
            "(username,password) VALUES ('alice','secret')"
        )
        self.assertEqual(
            redact_log_text(line),
            'ERROR postgres [REDACTED credential SQL statement]',
        )

    def test_diagnostic_fields_routes_and_non_ascii_bytes_are_preserved(self):
        text = 'WARNING provider account_id=4 status=403 elapsed=1.2 GET /api/core/logs/'
        self.assertEqual(redact_log_text(text), text)
        self.assertEqual(redact_log_bytes(b'unchanged \xff\n'), b'unchanged \xff\n')

    def test_bounded_stream_does_not_leak_credentials_across_chunk_boundaries(self):
        limit = 128
        line = b'x' * 113 + b' password="cross-boundary-secret" tail\nnext record\n'
        result = b''.join(redacted_log_lines(io.BytesIO(line), max_line_bytes=limit))
        self.assertNotIn(b'cross', result)
        self.assertNotIn(b'boundary', result)
        self.assertNotIn(b'secret', result)
        self.assertIn(REDACTED.encode(), result)
        self.assertIn(b'omitted oversized continuation', result)
        self.assertTrue(result.endswith(b'next record\n'))

    def test_stream_keeps_complete_normal_lines_and_redacts_a_final_fragment(self):
        data = b'normal\npassword=secret'
        self.assertEqual(
            b''.join(redacted_log_lines(io.BytesIO(data))),
            b'normal\npassword=[REDACTED]',
        )

    def test_all_credential_split_positions_fail_closed(self):
        for position in range(110, 133):
            for field in (
                b'password="cross-boundary-secret"',
                b'https://alice:secret@example.invalid/path',
            ):
                with self.subTest(position=position, field=field):
                    data = b'x' * position + b' ' + field + b'\nafter\n'
                    output = b''.join(redacted_log_lines(io.BytesIO(data), max_line_bytes=128))
                    self.assertNotIn(b'alice', output)
                    self.assertNotIn(b'cross', output)
                    self.assertNotIn(b'secret', output)
                    self.assertTrue(output.endswith(b'after\n'))

    def test_startup_messages_and_both_formatter_modes_redact_without_mutating_records(self):
        message = 'Failed https://example.invalid?password=secret username=alice'
        output = io.StringIO()
        startup_log(message, stream=output)
        self.assertNotIn('secret', output.getvalue())
        self.assertNotIn('alice', output.getvalue())
        for fronted in (False, True):
            with mock.patch('dispatcharr.startup_log.collector_running', return_value=fronted):
                formatter = DisplayTimezoneFormatter()
            record = logging.LogRecord('test', logging.ERROR, __file__, 1, '%s', (message,), None)
            rendered = formatter.format(record)
            self.assertNotIn('secret', rendered)
            self.assertNotIn('alice', rendered)
            self.assertEqual(record.msg, '%s')
            self.assertEqual(record.args, (message,))

    def test_exception_traceback_is_redacted_too(self):
        with mock.patch('dispatcharr.startup_log.collector_running', return_value=False):
            formatter = DisplayTimezoneFormatter()
        try:
            raise ValueError('Failed https://example.invalid?password=secret')
        except ValueError:
            record = logging.LogRecord(
                'test', logging.ERROR, __file__, 1,
                'Request failed', (), sys.exc_info(),
            )
        rendered = formatter.format(record)
        self.assertIn('ValueError', rendered)
        self.assertNotIn('example.invalid', rendered)
        self.assertNotIn('secret', rendered)
