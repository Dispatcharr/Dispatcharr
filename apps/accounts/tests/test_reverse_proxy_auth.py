"""Reverse proxy header auth: off by default, and only trusted peers count.

The configured header is client-suppliable, so security rests on two checks:
an admin must enable the setting, and REMOTE_ADDR must be in the dedicated
DISPATCHARR_PROXY_AUTH_TRUSTED_PROXIES allowlist. If either regresses, anyone
who can reach the port can sign in as any user.
"""

import os
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient

from core.models import CoreSettings, REVERSE_PROXY_AUTH_KEY

User = get_user_model()

PROXY_LOGIN_URL = "/api/accounts/auth/proxy-login/"
HEADER = "X-Forwarded-User"
UNTRUSTED_PEER = "203.0.113.7"
ALLOWLIST_ENV = "DISPATCHARR_PROXY_AUTH_TRUSTED_PROXIES"


# The test client's REMOTE_ADDR is 127.0.0.1; most cases want that allowed.
@mock.patch.dict(os.environ, {ALLOWLIST_ENV: "127.0.0.0/8"}, clear=False)
class ReverseProxyAuthTests(TestCase):
    def setUp(self):
        cache.clear()
        self.api = APIClient()
        self.user = User.objects.create_user(
            username="proxyuser",
            password="unused-password",
            email="proxy.user@example.com",
            user_level=10,
        )

    def tearDown(self):
        cache.clear()

    def _configure(self, *, enabled=True, header=HEADER):
        CoreSettings.objects.update_or_create(
            key=REVERSE_PROXY_AUTH_KEY,
            defaults={
                "name": "Reverse Proxy Auth",
                "value": {"enabled": enabled, "header": header},
            },
        )
        cache.clear()

    def _post(self, **extra):
        return self.api.post(PROXY_LOGIN_URL, **extra)

    def test_disabled_by_default_even_with_the_header_present(self):
        response = self._post(**{"HTTP_X_FORWARDED_USER": "proxyuser"})
        self.assertEqual(response.status_code, 401)

    def test_enabled_trusted_peer_returns_tokens(self):
        self._configure()
        response = self._post(**{"HTTP_X_FORWARDED_USER": "proxyuser"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("access", response.json())
        self.assertIn("refresh", response.json())

    def test_header_from_untrusted_peer_is_ignored(self):
        self._configure()
        response = self._post(
            REMOTE_ADDR=UNTRUSTED_PEER, **{"HTTP_X_FORWARDED_USER": "proxyuser"}
        )
        self.assertEqual(response.status_code, 401)

    @mock.patch.dict(os.environ, {ALLOWLIST_ENV: UNTRUSTED_PEER}, clear=False)
    def test_explicitly_trusted_peer_is_honored(self):
        self._configure()
        response = self._post(
            REMOTE_ADDR=UNTRUSTED_PEER, **{"HTTP_X_FORWARDED_USER": "proxyuser"}
        )
        self.assertEqual(response.status_code, 200)

    def test_allowlist_is_required_even_for_a_local_peer(self):
        self._configure()
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(ALLOWLIST_ENV, None)
            response = self._post(**{"HTTP_X_FORWARDED_USER": "proxyuser"})
        self.assertEqual(response.status_code, 401)

    @mock.patch.dict(
        os.environ, {"DISPATCHARR_TRUSTED_PROXIES": "127.0.0.0/8"}, clear=False
    )
    def test_forwarded_header_trust_alone_does_not_grant_sign_in(self):
        """The generic X-Forwarded-For allowlist is not a sign-in allowlist."""
        self._configure()
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(ALLOWLIST_ENV, None)
            response = self._post(**{"HTTP_X_FORWARDED_USER": "proxyuser"})
        self.assertEqual(response.status_code, 401)

    def test_missing_header_does_not_sign_anyone_in(self):
        self._configure()
        self.assertEqual(self._post().status_code, 401)

    def test_unknown_identity_is_rejected(self):
        self._configure()
        response = self._post(**{"HTTP_X_FORWARDED_USER": "nobody"})
        self.assertEqual(response.status_code, 401)

    def test_inactive_user_is_rejected(self):
        self._configure()
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        response = self._post(**{"HTTP_X_FORWARDED_USER": "proxyuser"})
        self.assertEqual(response.status_code, 401)

    def test_identity_matches_email_for_proxies_that_assert_one(self):
        self._configure()
        response = self._post(
            **{"HTTP_X_FORWARDED_USER": "Proxy.User@Example.com"}
        )
        self.assertEqual(response.status_code, 200)

    def test_email_shared_by_two_accounts_matches_nobody(self):
        self._configure()
        User.objects.create_user(
            username="twin",
            password="unused-password",
            email="proxy.user@example.com",
            user_level=10,
        )
        response = self._post(
            **{"HTTP_X_FORWARDED_USER": "proxy.user@example.com"}
        )
        self.assertEqual(response.status_code, 401)

    def test_case_distinct_usernames_match_nobody(self):
        self._configure()
        User.objects.create_user(
            username="ProxyUser",
            password="unused-password",
            user_level=10,
        )
        response = self._post(**{"HTTP_X_FORWARDED_USER": "PROXYUSER"})
        self.assertEqual(response.status_code, 401)

    def test_exact_username_wins_over_a_case_variant(self):
        self._configure()
        User.objects.create_user(
            username="ProxyUser",
            password="unused-password",
            user_level=10,
        )
        access = self._post(**{"HTTP_X_FORWARDED_USER": "proxyuser"}).json()["access"]

        authed = APIClient()
        authed.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        self.assertEqual(
            authed.get("/api/accounts/users/me/").json()["username"], "proxyuser"
        )

    def test_only_the_configured_header_is_read(self):
        self._configure(header="X-Auth-Request-User")
        response = self._post(**{"HTTP_X_FORWARDED_USER": "proxyuser"})
        self.assertEqual(response.status_code, 401)

        response = self._post(**{"HTTP_X_AUTH_REQUEST_USER": "proxyuser"})
        self.assertEqual(response.status_code, 200)

    def test_returned_tokens_authenticate_api_calls(self):
        self._configure()
        access = self._post(**{"HTTP_X_FORWARDED_USER": "proxyuser"}).json()["access"]

        authed = APIClient()
        authed.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        me = authed.get("/api/accounts/users/me/")
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.json()["username"], "proxyuser")
