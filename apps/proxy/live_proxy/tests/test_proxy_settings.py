"""Tests for proxy settings defaults, serializer validation, and migration 0026."""

from importlib import import_module
from unittest.mock import patch

from django.apps import apps
from django.test import SimpleTestCase, TestCase

from apps.proxy.config import TSConfig
from core.models import CoreSettings
from core.serializers import ProxySettingsSerializer

MIGRATION_0026 = import_module("core.migrations.0026_add_channel_client_wait_period")
MIGRATION_0032 = import_module("core.migrations.0032_add_retry_settings_to_proxy_settings")


class TSConfigProxySettingsDefaultsTests(SimpleTestCase):
    @patch.object(TSConfig, "get_proxy_settings", return_value={})
    def test_channel_init_grace_period_default(self, _mock_settings):
        self.assertEqual(TSConfig.get_channel_init_grace_period(), 60)

    @patch.object(TSConfig, "get_proxy_settings", return_value={})
    def test_channel_client_wait_period_default(self, _mock_settings):
        self.assertEqual(TSConfig.get_channel_client_wait_period(), 5)

    @patch.object(TSConfig, "get_proxy_settings", return_value={})
    def test_validate_redirect_urls_default(self, _mock_settings):
        self.assertTrue(TSConfig.get_validate_redirect_urls())

    @patch.object(TSConfig, "get_proxy_settings", return_value={})
    def test_max_retries_default(self, _mock_settings):
        self.assertEqual(TSConfig.get_max_retries(), 3)

    @patch.object(TSConfig, "get_proxy_settings", return_value={})
    def test_stream_retry_timeout_default(self, _mock_settings):
        self.assertEqual(TSConfig.get_stream_retry_timeout(), 3)

    @patch.object(
        TSConfig,
        "get_proxy_settings",
        return_value={
            "channel_init_grace_period": 120,
            "channel_client_wait_period": 15,
            "validate_redirect_urls": False,
            "max_retries": 5,
            "stream_retry_timeout": 10,
        },
    )
    def test_settings_override_db_values(self, _mock_settings):
        self.assertEqual(TSConfig.get_channel_init_grace_period(), 120)
        self.assertEqual(TSConfig.get_channel_client_wait_period(), 15)
        self.assertFalse(TSConfig.get_validate_redirect_urls())
        self.assertEqual(TSConfig.get_max_retries(), 5)
        self.assertEqual(TSConfig.get_stream_retry_timeout(), 10)


class ProxySettingsSerializerTests(SimpleTestCase):
    def _valid_payload(self, **overrides):
        payload = {
            "buffering_timeout": 15,
            "buffering_speed": 1.0,
            "redis_chunk_ttl": 60,
            "channel_shutdown_delay": 0,
            "channel_init_grace_period": 60,
            "channel_client_wait_period": 5,
            "new_client_behind_seconds": 5,
            "validate_redirect_urls": True,
            "max_retries": 3,
            "stream_retry_timeout": 3,
        }
        payload.update(overrides)
        return payload

    def test_accepts_new_client_wait_period(self):
        serializer = ProxySettingsSerializer(data=self._valid_payload())
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data["channel_client_wait_period"], 5)

    def test_accepts_validate_redirect_urls_false(self):
        serializer = ProxySettingsSerializer(
            data=self._valid_payload(validate_redirect_urls=False)
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertFalse(serializer.validated_data["validate_redirect_urls"])

    def test_validate_redirect_urls_defaults_true_when_omitted(self):
        payload = self._valid_payload()
        payload.pop("validate_redirect_urls")
        serializer = ProxySettingsSerializer(data=payload)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertTrue(serializer.validated_data["validate_redirect_urls"])

    def test_accepts_max_retries(self):
        serializer = ProxySettingsSerializer(data=self._valid_payload(max_retries=5))
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data["max_retries"], 5)

    def test_accepts_stream_retry_timeout(self):
        serializer = ProxySettingsSerializer(data=self._valid_payload(stream_retry_timeout=15))
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data["stream_retry_timeout"], 15)

    def test_max_retries_defaults_to_3_when_omitted(self):
        payload = self._valid_payload()
        payload.pop("max_retries")
        serializer = ProxySettingsSerializer(data=payload)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data["max_retries"], 3)

    def test_stream_retry_timeout_defaults_to_3_when_omitted(self):
        payload = self._valid_payload()
        payload.pop("stream_retry_timeout")
        serializer = ProxySettingsSerializer(data=payload)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data["stream_retry_timeout"], 3)

    def test_max_retries_rejects_negative(self):
        serializer = ProxySettingsSerializer(data=self._valid_payload(max_retries=-1))
        self.assertFalse(serializer.is_valid())
        self.assertIn("max_retries", serializer.errors)

    def test_stream_retry_timeout_rejects_negative(self):
        serializer = ProxySettingsSerializer(data=self._valid_payload(stream_retry_timeout=-1))
        self.assertFalse(serializer.is_valid())
        self.assertIn("stream_retry_timeout", serializer.errors)

    def test_init_grace_period_allows_up_to_300(self):
        serializer = ProxySettingsSerializer(
            data=self._valid_payload(channel_init_grace_period=300)
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_init_grace_period_rejects_above_300(self):
        serializer = ProxySettingsSerializer(
            data=self._valid_payload(channel_init_grace_period=301)
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("channel_init_grace_period", serializer.errors)


class CoreSettingsProxyDefaultsTests(TestCase):
    def test_get_proxy_settings_defaults_when_missing(self):
        CoreSettings.objects.filter(key="proxy_settings").delete()
        defaults = CoreSettings.get_proxy_settings()
        self.assertEqual(defaults["channel_init_grace_period"], 60)
        self.assertEqual(defaults["channel_client_wait_period"], 5)
        self.assertTrue(defaults["validate_redirect_urls"])
        self.assertEqual(defaults["max_retries"], 3)
        self.assertEqual(defaults["stream_retry_timeout"], 3)


class Migration0026ProxySettingsTests(TestCase):
    def _run_migration_forward(self):
        MIGRATION_0026.add_channel_client_wait_period(apps, None)

    def _set_proxy_settings(self, value):
        settings_obj, _ = CoreSettings.objects.get_or_create(
            key="proxy_settings",
            defaults={"name": "Proxy Settings", "value": value},
        )
        settings_obj.value = value
        settings_obj.save(update_fields=["value"])
        return settings_obj

    def test_bumps_legacy_init_grace_and_adds_client_wait(self):
        settings_obj = self._set_proxy_settings(
            {
                "buffering_timeout": 15,
                "buffering_speed": 1.0,
                "redis_chunk_ttl": 60,
                "channel_shutdown_delay": 0,
                "channel_init_grace_period": 5,
                "new_client_behind_seconds": 5,
            }
        )

        self._run_migration_forward()
        settings_obj.refresh_from_db()

        self.assertEqual(settings_obj.value["channel_init_grace_period"], 60)
        self.assertEqual(settings_obj.value["channel_client_wait_period"], 5)

    def test_bumps_init_grace_below_new_default(self):
        settings_obj = self._set_proxy_settings(
            {
                "buffering_timeout": 15,
                "buffering_speed": 1.0,
                "redis_chunk_ttl": 60,
                "channel_shutdown_delay": 0,
                "channel_init_grace_period": 45,
                "new_client_behind_seconds": 5,
            }
        )

        self._run_migration_forward()
        settings_obj.refresh_from_db()

        self.assertEqual(settings_obj.value["channel_init_grace_period"], 60)

    def test_preserves_init_grace_at_or_above_new_default(self):
        settings_obj = self._set_proxy_settings(
            {
                "buffering_timeout": 15,
                "buffering_speed": 1.0,
                "redis_chunk_ttl": 60,
                "channel_shutdown_delay": 0,
                "channel_init_grace_period": 90,
                "new_client_behind_seconds": 5,
            }
        )

        self._run_migration_forward()
        settings_obj.refresh_from_db()

        self.assertEqual(settings_obj.value["channel_init_grace_period"], 90)
        self.assertEqual(settings_obj.value["channel_client_wait_period"], 5)


class Migration0032ProxySettingsTests(TestCase):
    def _run_migration_forward(self):
        MIGRATION_0032.add_retry_settings_to_proxy_settings(apps, None)

    def _set_proxy_settings(self, value):
        settings_obj, _ = CoreSettings.objects.get_or_create(
            key="proxy_settings",
            defaults={"name": "Proxy Settings", "value": value},
        )
        settings_obj.value = value
        settings_obj.save(update_fields=["value"])
        return settings_obj

    def test_adds_defaults_when_missing(self):
        settings_obj = self._set_proxy_settings(
            {
                "buffering_timeout": 15,
                "buffering_speed": 1.0,
            }
        )

        self._run_migration_forward()
        settings_obj.refresh_from_db()

        self.assertEqual(settings_obj.value["max_retries"], 3)
        self.assertEqual(settings_obj.value["stream_retry_timeout"], 3)

    def test_preserves_existing_values(self):
        settings_obj = self._set_proxy_settings(
            {
                "buffering_timeout": 15,
                "max_retries": 10,
                "stream_retry_timeout": 20,
            }
        )

        self._run_migration_forward()
        settings_obj.refresh_from_db()

        self.assertEqual(settings_obj.value["max_retries"], 10)
        self.assertEqual(settings_obj.value["stream_retry_timeout"], 20)
