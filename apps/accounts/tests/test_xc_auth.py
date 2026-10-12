from unittest.mock import patch

from django.test import SimpleTestCase, TestCase

from apps.accounts.models import User
from apps.accounts.xc_auth import (
    XC_AUTH_CREDENTIALS,
    XC_AUTH_NETWORK,
    XC_AUTH_RATE_LIMIT,
    authorize_xc_client,
    xc_auth_error_response,
    xc_password_matches,
)


class XcPasswordMatchesTests(TestCase):
    def test_match(self):
        user = User(custom_properties={"xc_password": "secret"})
        self.assertTrue(xc_password_matches(user, "secret"))

    def test_mismatch(self):
        user = User(custom_properties={"xc_password": "secret"})
        self.assertFalse(xc_password_matches(user, "wrong"))

    def test_missing_xc_password(self):
        user = User(custom_properties={})
        self.assertFalse(xc_password_matches(user, "anything"))
        self.assertFalse(xc_password_matches(user, ""))

    def test_null_custom_properties(self):
        user = User(custom_properties=None)
        self.assertFalse(xc_password_matches(user, "x"))

    def test_coerces_non_string_password(self):
        user = User(custom_properties={"xc_password": "12345"})
        self.assertTrue(xc_password_matches(user, 12345))

    def test_non_ascii_password_is_a_mismatch_not_an_error(self):
        # compare_digest raises TypeError on non-ASCII str, and the supplied
        # password comes straight from the URL, so it must not escape as a 500.
        user = User(custom_properties={"xc_password": "secret"})
        self.assertFalse(xc_password_matches(user, "caf\u00e9"))

    def test_non_ascii_stored_password_still_matches_itself(self):
        user = User(custom_properties={"xc_password": "caf\u00e9"})
        self.assertTrue(xc_password_matches(user, "caf\u00e9"))
        self.assertFalse(xc_password_matches(user, "cafe"))


class XcAuthErrorResponseTests(SimpleTestCase):
    def test_network_is_403(self):
        response = xc_auth_error_response(XC_AUTH_NETWORK)
        self.assertEqual(response.status_code, 403)

    def test_credentials_are_401(self):
        response = xc_auth_error_response(XC_AUTH_CREDENTIALS)
        self.assertEqual(response.status_code, 401)

    def test_rate_limit_is_429_with_retry_after(self):
        response = xc_auth_error_response(XC_AUTH_RATE_LIMIT, retry_after=12.3)
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response["Retry-After"], "12")



class AuthorizeXcClientTests(SimpleTestCase):
    def _user(self):
        return User(username="alice", custom_properties={"xc_password": "secret"})

    def _authorize(self, username, password, network, key="XC_API"):
        with patch(
            "apps.accounts.xc_auth.network_access_allowed", side_effect=network
        ):
            return authorize_xc_client(None, username, password, key)

    def test_global_deny_skips_user_lookup(self):
        def deny(request, key, user=None):
            return False

        with patch("apps.accounts.xc_auth.get_xc_user") as lookup:
            user, error = self._authorize("alice", "secret", deny)

        lookup.assert_not_called()
        self.assertIsNone(user)
        self.assertEqual(error.status_code, 403)

    def test_blank_credentials_skip_lookup_when_network_allows(self):
        def allow(request, key, user=None):
            return True

        with patch("apps.accounts.xc_auth.get_xc_user") as lookup:
            user, error = self._authorize("alice", "", allow)

        lookup.assert_not_called()
        self.assertIsNone(user)
        self.assertEqual(error.status_code, 401)

    def test_user_network_deny_does_not_depend_on_password(self):
        def allow_global_only(request, key, user=None):
            return user is None

        with patch("apps.accounts.xc_auth.get_xc_user", return_value=self._user()):
            wrong, wrong_error = self._authorize("alice", "wrong", allow_global_only)
            right, right_error = self._authorize("alice", "secret", allow_global_only)

        self.assertIsNone(wrong)
        self.assertIsNone(right)
        self.assertEqual(wrong_error.status_code, 403)
        self.assertEqual(right_error.status_code, 403)

    def test_wrong_password_after_network_allows(self):
        def allow(request, key, user=None):
            return True

        with patch("apps.accounts.xc_auth.get_xc_user", return_value=self._user()):
            user, error = self._authorize("alice", "wrong", allow)

        self.assertIsNone(user)
        self.assertEqual(error.status_code, 401)

    def test_non_ascii_password_returns_401(self):
        def allow(request, key, user=None):
            return True

        with patch("apps.accounts.xc_auth.get_xc_user", return_value=self._user()):
            user, error = self._authorize("alice", "caf\u00e9", allow)

        self.assertIsNone(user)
        self.assertEqual(error.status_code, 401)

    def test_success(self):
        def allow(request, key, user=None):
            return True

        account = self._user()
        with patch("apps.accounts.xc_auth.get_xc_user", return_value=account):
            user, error = self._authorize("alice", "secret", allow, key="XC_API")

        self.assertIs(user, account)
        self.assertIsNone(error)

    def test_checks_system_then_user_network_rules(self):
        calls = []

        def track(request, key, user=None):
            calls.append(user)
            return True

        with patch("apps.accounts.xc_auth.get_xc_user", return_value=self._user()):
            user, error = self._authorize("alice", "secret", track)

        self.assertIsNone(error)
        self.assertEqual(len(calls), 2)
        self.assertIsNone(calls[0])
        self.assertEqual(calls[1].username, "alice")
        self.assertIs(user, calls[1])
