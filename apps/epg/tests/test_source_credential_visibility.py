import hashlib
import time
from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.epg.api_views import EPGSourceViewSet
from apps.epg.models import EPGSource
from apps.epg.sd_utils import (
    sd_auth_lockout_active, sd_credential_fingerprint, sd_get_cached_token,
    sd_set_cached_token, sd_token_cache_key,
)
from apps.epg.serializers import EPGSourceSerializer


@override_settings(SECRET_KEY="test-epg-fingerprint")
class SchedulesDirectFingerprintTests(SimpleTestCase):
    def test_fingerprint_is_keyed_and_changes_with_credentials(self):
        legacy = hashlib.sha256(b"user\0password").hexdigest()
        self.assertNotEqual(sd_credential_fingerprint("user", "password"), legacy)
        self.assertNotEqual(
            sd_credential_fingerprint("user", "password"),
            sd_credential_fingerprint("user", "different"),
        )
        original = sd_credential_fingerprint("user", "password")
        with self.settings(SECRET_KEY="another-key"):
            self.assertNotEqual(original, sd_credential_fingerprint("user", "password"))

    def test_existing_lockout_is_upgraded_without_retrying_credentials(self):
        legacy = hashlib.sha256(b"user\0password").hexdigest()
        source = MagicMock(username="user", password="password")
        source.custom_properties = {
            "sd_auth_lockout": True,
            "sd_auth_lockout_until": (timezone.now() + timedelta(hours=1)).isoformat(),
            "sd_auth_lockout_credential_fp": legacy,
            "sd_auth_lockout_code": 4004,
        }
        active, _, code = sd_auth_lockout_active(source)
        self.assertTrue(active)
        self.assertEqual(code, 4004)
        self.assertEqual(
            source.custom_properties["sd_auth_lockout_credential_fp"],
            sd_credential_fingerprint("user", "password"),
        )
        source.save.assert_called_once_with(update_fields=["custom_properties"])


class EPGSourceCredentialVisibilityTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_user(username="epg_admin", password="x", user_level=User.UserLevel.ADMIN)
        self.standard = User.objects.create_user(username="epg_standard", password="x", user_level=User.UserLevel.STANDARD)
        self.source = EPGSource.objects.create(
            name="Test EPG", source_type="xmltv", is_active=False,
            url="http://example.test/xmltv.php?username=testuser&password=test-secret",
            username="testuser", password="test-secret", status="error",
            last_message="failed password=test-secret",
            custom_properties={"sd_auth_lockout_credential_fp": "test-fingerprint"},
        )
        self.factory = APIRequestFactory()

    @patch("apps.accounts.permissions.network_access_allowed", return_value=True)
    def test_list_and_retrieve_hide_secrets_from_standard_user(self, _network):
        for action, kwargs in (("list", {}), ("retrieve", {"pk": self.source.pk})):
            with self.subTest(action=action):
                request = self.factory.get("/api/epg/sources/")
                force_authenticate(request, user=self.standard)
                response = EPGSourceViewSet.as_view({"get": action})(request, **kwargs)
                self.assertEqual(response.status_code, 200)
                data = next(x for x in response.data if x["id"] == self.source.id) if action == "list" else response.data
                self.assertNotIn("url", data)
                self.assertNotIn("username", data)
                self.assertNotIn("custom_properties", data)
                self.assertNotIn("test-secret", str(data))
                self.assertEqual(data["last_message"], "EPG refresh failed. Contact an administrator.")

    def test_admin_fields_are_preserved_and_missing_context_fails_closed(self):
        request = self.factory.get("/")
        request.user = self.admin
        admin = EPGSourceSerializer(self.source, context={"request": request}).data
        self.assertEqual(admin["url"], self.source.url)
        self.assertEqual(admin["username"], "testuser")
        self.assertEqual(admin["custom_properties"]["sd_auth_lockout_credential_fp"], "test-fingerprint")
        self.assertEqual(admin["last_message"], "failed password=test-secret")
        self.assertNotIn("url", EPGSourceSerializer(self.source).data)

    def test_schedules_direct_fingerprint_is_not_returned_to_standard_user(self):
        source = EPGSource.objects.create(
            name="Test Schedules Direct", source_type="schedules_direct", is_active=False,
            username="testuser", password="test-secret",
            custom_properties={"sd_auth_lockout_credential_fp": sd_credential_fingerprint("testuser", "test-secret")},
        )
        request = self.factory.get("/")
        request.user = self.standard
        data = EPGSourceSerializer(source, context={"request": request}).data
        self.assertNotIn("username", data)
        self.assertNotIn("custom_properties", data)


@override_settings(
    SECRET_KEY="test-epg-fingerprint",
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
)
class SchedulesDirectUpgradeTests(TestCase):
    def test_legacy_lockout_survives_refresh_without_new_authentication(self):
        from apps.epg.tasks import fetch_schedules_direct

        legacy = hashlib.sha256(b"user\0password").hexdigest()
        source = EPGSource.objects.create(
            name="Legacy locked account", source_type="schedules_direct", is_active=False,
            username="user", password="password", custom_properties={
                "sd_auth_lockout": True,
                "sd_auth_lockout_until": (timezone.now() + timedelta(hours=1)).isoformat(),
                "sd_auth_lockout_credential_fp": legacy,
                "sd_auth_lockout_code": 4003,
            },
        )
        with patch("apps.epg.sd_tasks.requests.post") as post, \
             patch("apps.epg.sd_tasks.send_epg_update"):
            fetch_schedules_direct(source)
        post.assert_not_called()
        source.refresh_from_db()
        self.assertEqual(source.status, EPGSource.STATUS_ERROR)
        self.assertEqual(
            source.custom_properties["sd_auth_lockout_credential_fp"],
            sd_credential_fingerprint("user", "password"),
        )

    def test_old_cached_token_is_invalidated_and_new_token_is_reusable(self):
        source_id = 123
        cache.set(sd_token_cache_key(source_id), {
            "token": "old-token", "expires": time.time() + 3600,
            "fp": hashlib.sha256(b"user\0password").hexdigest(),
        })
        self.assertIsNone(sd_get_cached_token(source_id, "user", "password"))
        self.assertTrue(sd_set_cached_token(source_id, "new-token", username="user", password="password"))
        self.assertEqual(sd_get_cached_token(source_id, "user", "password"), "new-token")
        self.assertIsNone(sd_get_cached_token(source_id, "user", "changed"))
