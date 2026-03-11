from django.test import TestCase
from django.contrib.auth import get_user_model
from django.core.cache import cache
from rest_framework.test import APIClient
from unittest.mock import patch, MagicMock
import time

User = get_user_model()


class InitializeSuperuserTests(TestCase):
    """Tests for the initialize_superuser endpoint"""

    def setUp(self):
        self.client = APIClient()
        self.url = "/api/accounts/initialize-superuser/"

    def test_returns_true_when_superuser_exists(self):
        """Superuser with is_superuser=True should be detected"""
        User.objects.create_superuser(
            username="admin", password="testpass123", user_level=10
        )
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["superuser_exists"])

    def test_returns_true_when_admin_level_user_exists(self):
        """User with user_level=10 but is_superuser=False should be detected"""
        user = User.objects.create_user(username="admin", password="testpass123")
        user.user_level = 10
        user.is_superuser = False
        user.save()
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["superuser_exists"])

    def test_returns_false_when_no_admin_exists(self):
        """No admin or superuser should return false"""
        # Create a non-admin user
        User.objects.create_user(username="regular", password="testpass123")
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["superuser_exists"])

    def test_returns_false_when_no_users_exist(self):
        """Empty database should return false"""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["superuser_exists"])

    def test_create_superuser_when_none_exists(self):
        """POST should create superuser when none exists"""
        response = self.client.post(
            self.url,
            {"username": "newadmin", "password": "testpass123", "email": "admin@test.com"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["superuser_exists"])
        self.assertTrue(User.objects.filter(username="newadmin", user_level=10).exists())

    def test_cannot_create_superuser_when_admin_exists(self):
        """POST should fail when an admin-level user already exists"""
        user = User.objects.create_user(username="existing", password="testpass123")
        user.user_level = 10
        user.save()
        response = self.client.post(
            self.url,
            {"username": "newadmin", "password": "testpass123"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["superuser_exists"])
        # Should NOT have created a new user
        self.assertFalse(User.objects.filter(username="newadmin").exists())


class EncryptionTests(TestCase):
    """Tests for apps/accounts/encryption.py"""

    def test_roundtrip(self):
        from apps.accounts.encryption import encrypt_secret, decrypt_secret
        plain = "super-secret-client-secret-value"
        encrypted = encrypt_secret(plain)
        self.assertNotEqual(encrypted, plain)
        self.assertTrue(encrypted.startswith("enc$"))
        self.assertEqual(decrypt_secret(encrypted), plain)

    def test_already_encrypted_is_idempotent(self):
        from apps.accounts.encryption import encrypt_secret, decrypt_secret
        plain = "my-secret"
        once = encrypt_secret(plain)
        twice = encrypt_secret(once)
        self.assertEqual(once, twice)
        self.assertEqual(decrypt_secret(twice), plain)

    def test_empty_string_passthrough(self):
        from apps.accounts.encryption import encrypt_secret, decrypt_secret
        self.assertEqual(encrypt_secret(""), "")
        self.assertEqual(decrypt_secret(""), "")

    def test_unencrypted_value_raises_value_error(self):
        """A non-empty value without the enc$ prefix must raise ValueError."""
        from apps.accounts.encryption import decrypt_secret
        with self.assertRaises(ValueError):
            decrypt_secret("unencrypted-plaintext-secret")

    def test_invalid_token_raises_value_error(self):
        """Ciphertext produced by a different key must raise ValueError, not crash."""
        from cryptography.fernet import Fernet
        from apps.accounts.encryption import decrypt_secret
        # Encrypt with a freshly generated key that differs from the test
        # SECRET_KEY so that decrypt_secret() cannot verify the HMAC.
        other_fernet = Fernet(Fernet.generate_key())
        corrupted = "enc$" + other_fernet.encrypt(b"top-secret").decode()
        with self.assertRaises(ValueError):
            decrypt_secret(corrupted)


class StateTokenTests(TestCase):
    """Tests for _generate_state / _parse_state in oidc_views."""

    def setUp(self):
        cache.clear()

    def _make_state(self, slug="test-provider", redirect_uri="http://localhost/oidc/callback"):
        from apps.accounts.oidc_views import _generate_state
        return _generate_state(slug, redirect_uri)

    def test_generate_and_parse_returns_slug_and_nonce(self):
        from apps.accounts.oidc_views import _parse_state
        state, nonce = self._make_state("my-idp")
        slug, parsed_nonce, redirect_hash = _parse_state(state)
        self.assertEqual(slug, "my-idp")
        self.assertEqual(parsed_nonce, nonce)
        self.assertIsNotNone(redirect_hash)

    def test_tampered_signature_rejected(self):
        from apps.accounts.oidc_views import _parse_state
        state, _ = self._make_state()
        # Flip the last character of the sig segment
        tampered = state[:-1] + ("X" if state[-1] != "X" else "Y")
        slug, nonce, _ = _parse_state(tampered)
        self.assertIsNone(slug)
        self.assertIsNone(nonce)

    def test_wrong_part_count_rejected(self):
        from apps.accounts.oidc_views import _parse_state
        slug, nonce, _ = _parse_state("only:three:parts")
        self.assertIsNone(slug)

    def test_expired_state_rejected(self):
        from apps.accounts.oidc_views import _parse_state, STATE_TTL
        state, _ = self._make_state()
        # Simulate the state being STATE_TTL + 1 seconds old.
        with patch("apps.accounts.oidc_views.time") as mock_time:
            mock_time.time.return_value = time.time() + STATE_TTL + 1
            slug, nonce, _ = _parse_state(state)
        self.assertIsNone(slug)
        self.assertIsNone(nonce)

    def test_fresh_state_within_ttl_accepted(self):
        from apps.accounts.oidc_views import _parse_state, STATE_TTL
        state, _ = self._make_state()
        # 1 second before expiry should still be valid.
        with patch("apps.accounts.oidc_views.time") as mock_time:
            mock_time.time.return_value = time.time() + STATE_TTL - 1
            slug, nonce, _ = _parse_state(state)
        self.assertIsNotNone(slug)


def _make_provider(**kwargs):
    """Create an OIDCProvider with test defaults (bypassing encryption save)."""
    from apps.accounts.models import OIDCProvider
    from apps.accounts.encryption import encrypt_secret
    defaults = dict(
        name="Test IdP",
        slug="test-idp",
        issuer_url="https://idp.example.com",
        client_id="client123",
        # Store already-encrypted secret so save() doesn't re-encrypt.
        client_secret=encrypt_secret("s3cr3t"),
        scopes="openid profile email",
        is_enabled=True,
        auto_create_users=True,
        # Allow localhost so tests that post redirect_uri=http://localhost/...
        # pass the host-validation check in oidc_authorize.
        allowed_redirect_uris="http://localhost/oidc/callback",
    )
    defaults.update(kwargs)
    return OIDCProvider.objects.create(**defaults)


FAKE_DISCOVERY = {
    "authorization_endpoint": "https://idp.example.com/auth",
    "token_endpoint": "https://idp.example.com/token",
    "userinfo_endpoint": "https://idp.example.com/userinfo",
    "jwks_uri": "https://idp.example.com/jwks",
    "issuer": "https://idp.example.com",
    "id_token_signing_alg_values_supported": ["RS256"],
}


class OIDCProvidersListTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_only_enabled_providers_returned(self):
        _make_provider(slug="enabled", is_enabled=True)
        _make_provider(slug="disabled", is_enabled=False)
        response = self.client.get("/api/accounts/oidc/providers/")
        self.assertEqual(response.status_code, 200)
        slugs = [p["slug"] for p in response.json()]
        self.assertIn("enabled", slugs)
        self.assertNotIn("disabled", slugs)

    def test_empty_list_when_none_enabled(self):
        _make_provider(slug="off", is_enabled=False)
        response = self.client.get("/api/accounts/oidc/providers/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])


class OIDCAuthorizeTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.provider = _make_provider()
        cache.clear()

    def test_unknown_slug_returns_404(self):
        response = self.client.get(
            "/api/accounts/oidc/authorize/no-such-provider/",
            {"redirect_uri": "http://localhost/oidc/callback"},
        )
        self.assertEqual(response.status_code, 404)

    def test_disabled_provider_returns_404(self):
        _make_provider(slug="off", is_enabled=False)
        response = self.client.get(
            "/api/accounts/oidc/authorize/off/",
            {"redirect_uri": "http://localhost/oidc/callback"},
        )
        self.assertEqual(response.status_code, 404)

    def test_missing_redirect_uri_returns_400(self):
        response = self.client.get("/api/accounts/oidc/authorize/test-idp/")
        self.assertEqual(response.status_code, 400)

    def test_disallowed_redirect_uri_returns_400(self):
        response = self.client.get(
            "/api/accounts/oidc/authorize/test-idp/",
            {"redirect_uri": "https://evil.example.com/steal"},
        )
        self.assertEqual(response.status_code, 400)

    def test_non_http_redirect_uri_scheme_returns_400(self):
        response = self.client.get(
            "/api/accounts/oidc/authorize/test-idp/",
            {"redirect_uri": "custom://localhost/oidc/callback"},
        )
        self.assertEqual(response.status_code, 400)

    @patch("apps.accounts.oidc_views._get_discovery", return_value=FAKE_DISCOVERY)
    def test_allowlist_matches_by_host_and_port(self, _mock):
        # allowlist contains one exact URL, but host+port validation should
        # still accept other paths on the same host and port.
        self.provider.allowed_redirect_uris = "http://localhost/oidc/callback"
        self.provider.save()
        response = self.client.get(
            "/api/accounts/oidc/authorize/test-idp/",
            {"redirect_uri": "http://localhost/some/other/path"},
        )
        self.assertEqual(response.status_code, 200)

    @patch("apps.accounts.oidc_views._get_discovery", return_value=FAKE_DISCOVERY)
    def test_allowlist_accepts_plain_host_entries(self, _mock):
        self.provider.allowed_redirect_uris = "localhost, example.com"
        self.provider.save()
        response = self.client.get(
            "/api/accounts/oidc/authorize/test-idp/",
            {"redirect_uri": "http://localhost/oidc/callback"},
        )
        self.assertEqual(response.status_code, 200)

    @patch("apps.accounts.oidc_views._get_discovery", return_value=FAKE_DISCOVERY)
    def test_allowlist_rejects_port_mismatch(self, _mock):
        self.provider.allowed_redirect_uris = "http://localhost/oidc/callback"
        self.provider.save()
        response = self.client.get(
            "/api/accounts/oidc/authorize/test-idp/",
            {"redirect_uri": "http://localhost:9191/oidc/callback"},
        )
        self.assertEqual(response.status_code, 400)

    @patch("apps.accounts.oidc_views._get_discovery", return_value=FAKE_DISCOVERY)
    def test_allowlist_accepts_ipv6_with_port(self, _mock):
        self.provider.allowed_redirect_uris = "http://[::1]:9191/oidc/callback"
        self.provider.save()
        response = self.client.get(
            "/api/accounts/oidc/authorize/test-idp/",
            {"redirect_uri": "http://[::1]:9191/oidc/callback"},
        )
        self.assertEqual(response.status_code, 200)

    @patch("apps.accounts.oidc_views._get_discovery", return_value=FAKE_DISCOVERY)
    def test_success_returns_authorize_url_and_state(self, _mock):
        response = self.client.get(
            "/api/accounts/oidc/authorize/test-idp/",
            {"redirect_uri": "http://localhost/oidc/callback"},
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("authorize_url", body)
        self.assertIn("state", body)
        self.assertIn("https://idp.example.com/auth", body["authorize_url"])

    @patch("apps.accounts.oidc_views._get_discovery", return_value={
        **FAKE_DISCOVERY,
        "code_challenge_methods_supported": ["S256"],
    })
    def test_pkce_challenge_included_in_authorize_url(self, _mock):
        response = self.client.get(
            "/api/accounts/oidc/authorize/test-idp/",
            {
                "redirect_uri": "http://localhost/oidc/callback",
                "code_challenge": "abc123challenge",
                "code_challenge_method": "S256",
            },
        )
        self.assertEqual(response.status_code, 200)
        url = response.json()["authorize_url"]
        self.assertIn("code_challenge=abc123challenge", url)
        self.assertIn("code_challenge_method=S256", url)
        self.assertTrue(response.json()["pkce_supported"])

    @patch("apps.accounts.oidc_views._get_discovery", return_value={
        **FAKE_DISCOVERY,
        "code_challenge_methods_supported": ["S256"],
    })
    def test_pkce_method_is_forced_to_s256(self, _mock):
        response = self.client.get(
            "/api/accounts/oidc/authorize/test-idp/",
            {
                "redirect_uri": "http://localhost/oidc/callback",
                "code_challenge": "abc123challenge",
                "code_challenge_method": "plain",
            },
        )
        self.assertEqual(response.status_code, 200)
        url = response.json()["authorize_url"]
        self.assertIn("code_challenge_method=S256", url)
        self.assertNotIn("code_challenge_method=plain", url)

    @patch("apps.accounts.oidc_views._get_discovery", return_value=FAKE_DISCOVERY)
    def test_pkce_challenge_not_sent_when_provider_does_not_support_it(self, _mock):
        """When discovery has no code_challenge_methods_supported, PKCE must not be sent."""
        response = self.client.get(
            "/api/accounts/oidc/authorize/test-idp/",
            {
                "redirect_uri": "http://localhost/oidc/callback",
                "code_challenge": "abc123challenge",
                "code_challenge_method": "S256",
            },
        )
        self.assertEqual(response.status_code, 200)
        url = response.json()["authorize_url"]
        self.assertNotIn("code_challenge", url)
        self.assertFalse(response.json()["pkce_supported"])

    @patch("apps.accounts.oidc_views._get_discovery", side_effect=Exception("unreachable"))
    def test_discovery_failure_returns_502(self, _mock):
        response = self.client.get(
            "/api/accounts/oidc/authorize/test-idp/",
            {"redirect_uri": "http://localhost/oidc/callback"},
        )
        self.assertEqual(response.status_code, 502)

    @patch("apps.accounts.oidc_views._get_discovery", return_value=FAKE_DISCOVERY)
    def test_same_host_fallback_allows_blank_allowlist(self, _mock_disc):
        self.provider.allowed_redirect_uris = ""
        self.provider.save()
        response = self.client.get(
            "/api/accounts/oidc/authorize/test-idp/",
            {"redirect_uri": "http://testserver/oidc/callback"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("authorize_url", response.json())

    @patch("apps.accounts.oidc_views._get_discovery", return_value=FAKE_DISCOVERY)
    def test_same_host_fallback_rejects_port_mismatch(self, _mock_disc):
        self.provider.allowed_redirect_uris = ""
        self.provider.save()
        response = self.client.get(
            "/api/accounts/oidc/authorize/test-idp/",
            {"redirect_uri": "http://testserver:9191/oidc/callback"},
        )
        self.assertEqual(response.status_code, 400)


class OIDCCallbackTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.provider = _make_provider()
        cache.clear()

    def _fresh_state(self, redirect_uri="http://localhost/oidc/callback"):
        from apps.accounts.oidc_views import _generate_state
        state, nonce = _generate_state(self.provider.slug, redirect_uri)
        return state, nonce

    def _fake_token_response(self, id_token="fake.id.token"):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {
            "access_token": "access-abc",
            "id_token": id_token,
        }
        return mock_resp

    def test_invalid_state_returns_400(self):
        response = self.client.post(
            "/api/accounts/oidc/callback/",
            {"code": "abc", "state": "bad:state:value:here:xx", "redirect_uri": "http://localhost/oidc/callback"},
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_missing_fields_returns_400(self):
        response = self.client.post(
            "/api/accounts/oidc/callback/",
            {"code": "abc"},
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_replayed_state_returns_400(self):
        state, _ = self._fresh_state()
        payload = {"code": "abc", "state": state, "redirect_uri": "http://localhost/oidc/callback"}

        with patch("apps.accounts.oidc_views._get_discovery", return_value=FAKE_DISCOVERY), \
             patch("apps.accounts.oidc_views.http_requests.post", return_value=self._fake_token_response()), \
             patch("apps.accounts.oidc_views._verify_id_token", return_value={
                 "sub": "u1", "preferred_username": "newuser",
                 "email": "new@example.com", "nonce": "x",
             }):
            self.client.post("/api/accounts/oidc/callback/", payload, format="json")

        # Second submission with same state must be rejected.
        response = self.client.post("/api/accounts/oidc/callback/", payload, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("already been used", response.json()["error"])

    def test_expired_state_returns_400(self):
        from apps.accounts.oidc_views import STATE_TTL
        state, _ = self._fresh_state()
        with patch("apps.accounts.oidc_views.time") as mock_time:
            mock_time.time.return_value = time.time() + STATE_TTL + 5
            response = self.client.post(
                "/api/accounts/oidc/callback/",
                {"code": "abc", "state": state, "redirect_uri": "http://localhost/oidc/callback"},
                format="json",
            )
        self.assertEqual(response.status_code, 400)

    def test_redirect_uri_mismatch_returns_400(self):
        state, _ = self._fresh_state("http://localhost/oidc/callback")
        response = self.client.post(
            "/api/accounts/oidc/callback/",
            {"code": "abc", "state": state, "redirect_uri": "http://localhost/oidc/other"},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("redirect_uri", response.json()["error"])

    @patch("apps.accounts.oidc_views._get_discovery", return_value=FAKE_DISCOVERY)
    @patch("apps.accounts.oidc_views.http_requests.post")
    def test_token_exchange_failure_returns_502(self, mock_post, _mock_disc):
        import requests as req
        mock_post.side_effect = req.RequestException("timeout")
        state, _ = self._fresh_state()
        response = self.client.post(
            "/api/accounts/oidc/callback/",
            {"code": "abc", "state": state, "redirect_uri": "http://localhost/oidc/callback"},
            format="json",
        )
        self.assertEqual(response.status_code, 502)

    @patch("apps.accounts.oidc_views._get_discovery", return_value=FAKE_DISCOVERY)
    @patch("apps.accounts.oidc_views.http_requests.post")
    def test_no_id_token_returns_502(self, mock_post, _mock_disc):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {"access_token": "abc"}  # no id_token
        mock_post.return_value = mock_resp
        state, _ = self._fresh_state()
        response = self.client.post(
            "/api/accounts/oidc/callback/",
            {"code": "abc", "state": state, "redirect_uri": "http://localhost/oidc/callback"},
            format="json",
        )
        self.assertEqual(response.status_code, 502)

    @patch("apps.accounts.oidc_views._get_discovery", return_value=FAKE_DISCOVERY)
    @patch("apps.accounts.oidc_views.http_requests.post")
    @patch("apps.accounts.oidc_views._verify_id_token", side_effect=ValueError("bad token"))
    def test_invalid_id_token_returns_401(self, _mock_verify, mock_post, _mock_disc):
        mock_post.return_value = self._fake_token_response()
        state, _ = self._fresh_state()
        response = self.client.post(
            "/api/accounts/oidc/callback/",
            {"code": "abc", "state": state, "redirect_uri": "http://localhost/oidc/callback"},
            format="json",
        )
        self.assertEqual(response.status_code, 401)

    @patch("apps.accounts.oidc_views._get_discovery", return_value=FAKE_DISCOVERY)
    @patch("apps.accounts.oidc_views.http_requests.post")
    @patch("apps.accounts.oidc_views._verify_id_token")
    def test_auto_create_disabled_unknown_user_returns_403(self, mock_verify, mock_post, _mock_disc):
        self.provider.auto_create_users = False
        self.provider.save()
        mock_post.return_value = self._fake_token_response()
        mock_verify.return_value = {
            "sub": "u99", "preferred_username": "stranger",
            "email": "stranger@example.com",
        }
        state, _ = self._fresh_state()
        response = self.client.post(
            "/api/accounts/oidc/callback/",
            {"code": "abc", "state": state, "redirect_uri": "http://localhost/oidc/callback"},
            format="json",
        )
        self.assertEqual(response.status_code, 403)

    @patch("apps.accounts.oidc_views._get_discovery", return_value=FAKE_DISCOVERY)
    @patch("apps.accounts.oidc_views.http_requests.post")
    @patch("apps.accounts.oidc_views._verify_id_token")
    def test_success_creates_user_and_returns_tokens(self, mock_verify, mock_post, _mock_disc):
        mock_post.return_value = self._fake_token_response()
        mock_verify.return_value = {
            "sub": "u1",
            "preferred_username": "oidcuser",
            "email": "oidcuser@example.com",
            "given_name": "OIDC",
            "family_name": "User",
        }
        state, _ = self._fresh_state()
        response = self.client.post(
            "/api/accounts/oidc/callback/",
            {"code": "abc", "state": state, "redirect_uri": "http://localhost/oidc/callback"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("access", response.json())
        self.assertIn("refresh", response.json())
        self.assertTrue(User.objects.filter(username="oidcuser").exists())

    @patch("apps.accounts.oidc_views._get_discovery", return_value=FAKE_DISCOVERY)
    @patch("apps.accounts.oidc_views.http_requests.post")
    @patch("apps.accounts.oidc_views._verify_id_token")
    def test_success_with_existing_user_does_not_duplicate(self, mock_verify, mock_post, _mock_disc):
        User.objects.create_user(username="existingoidc", email="existing@example.com", password="x")
        mock_post.return_value = self._fake_token_response()
        mock_verify.return_value = {
            "sub": "u2",
            "preferred_username": "existingoidc",
            "email": "existing@example.com",
        }
        state, _ = self._fresh_state()
        response = self.client.post(
            "/api/accounts/oidc/callback/",
            {"code": "abc", "state": state, "redirect_uri": "http://localhost/oidc/callback"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(User.objects.filter(username="existingoidc").count(), 1)

    @patch("apps.accounts.oidc_views._get_discovery", return_value=FAKE_DISCOVERY)
    @patch("apps.accounts.oidc_views.http_requests.post")
    @patch("apps.accounts.oidc_views._verify_id_token")
    def test_inactive_user_returns_403(self, mock_verify, mock_post, _mock_disc):
        """Disabled user account must be rejected even on valid OIDC login."""
        user = User.objects.create_user(
            username="inactive_oidc", email="inactive@example.com", password="x"
        )
        user.is_active = False
        user.save()
        mock_post.return_value = self._fake_token_response()
        mock_verify.return_value = {
            "sub": "u_inactive",
            "preferred_username": "inactive_oidc",
            "email": "inactive@example.com",
        }
        state, _ = self._fresh_state()
        response = self.client.post(
            "/api/accounts/oidc/callback/",
            {"code": "abc", "state": state, "redirect_uri": "http://localhost/oidc/callback"},
            format="json",
        )
        self.assertEqual(response.status_code, 403)

    @patch("apps.accounts.oidc_views._get_discovery", return_value=FAKE_DISCOVERY)
    @patch("apps.accounts.oidc_views.http_requests.post")
    @patch("apps.accounts.oidc_views._verify_id_token")
    def test_pkce_code_verifier_forwarded_to_token_endpoint(self, mock_verify, mock_post, _mock_disc):
        """code_verifier must be included in the token exchange POST body."""
        mock_post.return_value = self._fake_token_response()
        mock_verify.return_value = {
            "sub": "u3",
            "preferred_username": "pkceuser",
            "email": "pkce@example.com",
        }
        state, _ = self._fresh_state()
        response = self.client.post(
            "/api/accounts/oidc/callback/",
            {
                "code": "authcode",
                "state": state,
                "redirect_uri": "http://localhost/oidc/callback",
                "code_verifier": "my-pkce-verifier-string",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        # Confirm the verifier was passed to the token endpoint.
        call_kwargs = mock_post.call_args
        sent_data = call_kwargs[1].get("data") or call_kwargs[0][1]
        self.assertEqual(sent_data.get("code_verifier"), "my-pkce-verifier-string")


class ResolveUserLevelTests(TestCase):
    def setUp(self):
        self.provider = _make_provider()

    def test_no_mapping_returns_default(self):
        from apps.accounts.oidc_views import _resolve_user_level
        self.provider.group_to_level_mapping = {}
        level = _resolve_user_level({"groups": ["staff"]}, self.provider)
        self.assertEqual(level, self.provider.default_user_level)

    def test_matching_group_returns_mapped_level(self):
        from apps.accounts.oidc_views import _resolve_user_level
        self.provider.group_to_level_mapping = {"dispatcharr-admins": 10}
        level = _resolve_user_level({"groups": ["dispatcharr-admins"]}, self.provider)
        self.assertEqual(level, 10)

    def test_highest_matching_level_wins(self):
        from apps.accounts.oidc_views import _resolve_user_level
        self.provider.group_to_level_mapping = {"standard": 1, "admins": 10, "streamers": 0}
        level = _resolve_user_level({"groups": ["standard", "admins"]}, self.provider)
        self.assertEqual(level, 10)

    def test_no_matching_group_returns_default(self):
        from apps.accounts.oidc_views import _resolve_user_level
        self.provider.group_to_level_mapping = {"admins": 10}
        level = _resolve_user_level({"groups": ["other-group"]}, self.provider)
        self.assertEqual(level, self.provider.default_user_level)


class GetOrCreateUserTests(TestCase):
    def setUp(self):
        self.provider = _make_provider()

    def test_creates_new_user_from_claims(self):
        from apps.accounts.oidc_views import _get_or_create_user
        user = _get_or_create_user(
            {"sub": "x1", "preferred_username": "newbie", "email": "new@example.com"},
            self.provider,
        )
        self.assertIsNotNone(user)
        self.assertEqual(user.username, "newbie")
        self.assertFalse(user.has_usable_password())

    def test_finds_existing_user_by_username(self):
        from apps.accounts.oidc_views import _get_or_create_user
        existing = User.objects.create_user(username="alice", email="alice@example.com", password="x")
        user = _get_or_create_user(
            {"sub": "x2", "preferred_username": "alice", "email": "alice@example.com"},
            self.provider,
        )
        self.assertEqual(user.pk, existing.pk)

    def test_finds_existing_user_by_email_fallback(self):
        from apps.accounts.oidc_views import _get_or_create_user
        existing = User.objects.create_user(username="bob", email="bob@example.com", password="x")
        user = _get_or_create_user(
            {"sub": "x3", "preferred_username": "bob-idp-name", "email": "bob@example.com"},
            self.provider,
        )
        # Should match by email when username lookup fails
        self.assertEqual(user.email, "bob@example.com")

    def test_auto_create_disabled_returns_none(self):
        from apps.accounts.oidc_views import _get_or_create_user
        self.provider.auto_create_users = False
        user = _get_or_create_user(
            {"sub": "x4", "preferred_username": "ghost"},
            self.provider,
        )
        self.assertIsNone(user)
