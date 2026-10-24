"""Connection preflight uses synthetic responses and never contacts providers."""

import json
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlsplit

import requests
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from rest_framework.test import APIClient

from apps.m3u.connection_check import check_account_connection
from apps.m3u.models import M3UAccount
from core.models import UserAgent
from core.http_security import get_with_validated_redirects


class ConnectionProbeTests(SimpleTestCase):
    def setUp(self):
        self.values = {
            "account_type": "XC",
            "server_url": "https://provider.example.invalid/base/get.php?old=1",
            "username": "example&user",
            "password": "synthetic?secret&=",
            "user_agent_string": "ExampleAgent/1.0",
        }
        patcher = patch("apps.m3u.connection_check.get_with_validated_redirects")
        self.get = patcher.start()
        self.addCleanup(patcher.stop)

    def response(self, body, status=200):
        response = MagicMock()
        response.status_code = status
        response.iter_content.return_value = iter([body])
        self.get.return_value.__enter__.return_value = response
        return response

    def test_xc_checks_encoded_login_with_bounded_public_get(self):
        self.response(b'{"user_info":{"auth":1,"status":"Active"}}')
        self.assertTrue(check_account_connection(self.values)["success"])
        args, options = self.get.call_args
        parsed = urlsplit(args[0])
        self.assertEqual(parsed.path, "/base/player_api.php")
        self.assertEqual(parse_qs(parsed.query), {
            "username": [self.values["username"]],
            "password": [self.values["password"]],
        })
        self.assertEqual(options["headers"], {"User-Agent": "ExampleAgent/1.0"})
        self.assertEqual(options["timeout"], (3, 5))
        self.assertEqual(options["max_redirects"], 2)
        self.assertTrue(options["stream"])
        self.assertNotIn("allow_private", options)
        self.assertNotIn("allow_loopback", options)
        self.get.return_value.__exit__.assert_called_once()

    def test_missing_password_does_not_make_a_request(self):
        self.values.pop("password")
        self.assertEqual(
            check_account_connection(self.values)["code"], "password_required"
        )
        self.get.assert_not_called()

    def test_playlist_reads_only_the_header_and_keeps_full_playlist_query(self):
        self.values["account_type"] = "STD"
        response = self.response(b'\xef\xbb\xbf#EXTM3U\n')
        response.iter_content.return_value = iter([
            b'\xef\xbb\xbf#EXTM3U\n', b"large remaining playlist that must not be read",
        ])
        self.assertTrue(check_account_connection(self.values)["success"])
        self.assertEqual(
            next(response.iter_content.return_value),
            b"large remaining playlist that must not be read",
        )
        self.assertEqual(self.get.call_args.args[0], self.values["server_url"])

    def test_playlist_rejects_html_even_with_http_200(self):
        self.values["account_type"] = "STD"
        self.response(b"<html>Login required</html>")
        self.assertEqual(
            check_account_connection(self.values)["code"], "invalid_playlist"
        )

    def test_http_failure_returns_only_status_not_upstream_body_or_url(self):
        response = self.response(b"secret upstream error", 403)
        result = check_account_connection(self.values)
        self.assertEqual(result["http_status"], 403)
        self.assertFalse(result["success"])
        response.iter_content.assert_not_called()
        self.assertNotIn("secret", json.dumps(result))
        self.assertNotIn("provider.example", json.dumps(result))

    def test_invalid_xc_responses_and_inactive_logins(self):
        for body, code in (
            (b"<html>secret</html>", "invalid_response"),
            (b"[]", "invalid_response"),
            (b'{"user_info":{}}', "invalid_response"),
            (b'{"user_info":{"message":"unknown"}}', "invalid_response"),
            (b'{"user_info":{"auth":0}}', "authentication_failed"),
            (b'{"user_info":{"auth":1,"status":"Expired"}}', "account_unavailable"),
        ):
            with self.subTest(code=code, body=body):
                self.response(body)
                self.assertEqual(check_account_connection(self.values)["code"], code)

    def test_transport_and_policy_failures_never_echo_exception_text(self):
        for error, code in (
            (requests.exceptions.Timeout, "timeout"),
            (requests.exceptions.SSLError, "tls_error"),
            (requests.exceptions.ConnectionError, "connection_error"),
            (requests.exceptions.RequestException, "request_failed"),
            (ValueError, "unavailable"),
        ):
            with self.subTest(code=code):
                self.get.side_effect = error("https://private.invalid/?password=secret")
                result = check_account_connection(self.values)
                self.assertEqual(result["code"], code)
                self.assertNotIn("secret", json.dumps(result))
                self.assertNotIn("private.invalid", json.dumps(result))

    def test_slow_stream_stops_and_closes_response(self):
        self.response(b'{"user_info":{"auth":1}}')
        with patch("apps.m3u.connection_check.monotonic", side_effect=[0, 11]):
            self.assertEqual(check_account_connection(self.values)["code"], "timeout")
        self.get.return_value.__exit__.assert_called_once()

    def test_oversized_xc_response_is_not_read_in_full(self):
        response = self.response(b"")
        response.iter_content.return_value = iter([b"x" * 1024] * 100)
        self.assertEqual(
            check_account_connection(self.values)["code"], "invalid_response"
        )
        self.assertEqual(len(list(response.iter_content.return_value)), 36)

    @patch("core.http_security.requests.get")
    @patch("core.http_security.socket.getaddrinfo")
    def test_internal_targets_are_blocked(self, resolve, request):
        self.get.side_effect = get_with_validated_redirects
        for address in ("127.0.0.1", "10.0.0.1", "169.254.169.254", "::1"):
            with self.subTest(address=address):
                resolve.return_value = [(2, 1, 6, "", (address, 80))]
                self.assertEqual(
                    check_account_connection(self.values)["code"], "unavailable"
                )
        request.assert_not_called()


class ConnectionCheckAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = get_user_model().objects.create_user(
            username="connection-admin", user_level=10,
        )
        self.standard = get_user_model().objects.create_user(
            username="connection-viewer", user_level=1,
        )
        self.client.force_authenticate(self.admin)
        self.payload = {
            "account_type": "XC", "server_url": "https://example.invalid/base",
            "username": "example", "password": "synthetic",
        }
        self.url = "/api/m3u/accounts/check-connection/"
        for target in (
            "apps.m3u.signals.refresh_m3u_groups.delay",
            "apps.m3u.models.M3UAccount.get_user_agent_string",
        ):
            patcher = patch(target, return_value="DefaultAgent/1.0")
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch("apps.m3u.connection_check.check_account_connection")
        self.probe = patcher.start()
        self.probe.return_value = {
            "success": True, "code": "connected",
            "message": "Connection verified.",
        }
        self.addCleanup(patcher.stop)

    def test_draft_check_does_not_create_or_modify_an_account(self):
        before = M3UAccount.objects.count()
        response = self.client.post(self.url, self.payload, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["success"])
        self.assertEqual(M3UAccount.objects.count(), before)
        self.assertEqual(
            self.probe.call_args.args[0]["user_agent_string"], "DefaultAgent/1.0"
        )
        self.assertNotIn("synthetic", json.dumps(response.data))

    def test_saved_password_is_used_only_for_unchanged_normalized_server(self):
        account = M3UAccount.objects.create(name="Stored connection", **self.payload)
        payload = {**self.payload, "password": "", "account_id": account.id}
        response = self.client.post(self.url, payload, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.probe.call_args.args[0]["password"], "synthetic")
        account.refresh_from_db()
        self.assertEqual(account.server_url, self.payload["server_url"])
        self.assertIsNone(account.updated_at)
        self.assertEqual(account.status, "idle")
        payload["server_url"] = "https://different.invalid/base"
        response = self.client.post(self.url, payload, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.probe.call_args.args[0].get("password"))
        payload["password"] = "reentered-secret"
        self.client.post(self.url, payload, format="json")
        self.assertEqual(self.probe.call_args.args[0]["password"], "reentered-secret")

    def test_account_specific_user_agent_is_used(self):
        agent = UserAgent.objects.create(
            name="Connection check agent", user_agent="CustomAgent/2.0"
        )
        response = self.client.post(
            self.url, {**self.payload, "user_agent": agent.id}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            self.probe.call_args.args[0]["user_agent_string"], "CustomAgent/2.0"
        )

    def test_only_admin_may_probe_and_get_does_not_probe(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)
        self.client.force_authenticate(self.standard)
        self.assertEqual(
            self.client.post(self.url, self.payload, format="json").status_code,
            403,
        )
        self.client.force_authenticate(None)
        self.assertEqual(
            self.client.post(self.url, self.payload, format="json").status_code,
            401,
        )
        self.probe.assert_not_called()

    def test_invalid_input_never_reaches_the_probe(self):
        for changes in (
            {"server_url": "file:///etc/passwd"}, {"server_url": ""},
            {"server_url": "https://example.invalid:99999"},
            {"account_type": "other"}, {"username": ""}, {"account_id": 999999},
        ):
            with self.subTest(changes=changes):
                response = self.client.post(
                    self.url, {**self.payload, **changes}, format="json"
                )
                self.assertEqual(response.status_code, 400)
        self.probe.assert_not_called()
