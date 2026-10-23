"""Tests for proxy settings defaults, serializer validation, and migrations."""

from importlib import import_module
from unittest.mock import MagicMock, patch

from django.apps import apps
from django.test import SimpleTestCase, TestCase

from apps.proxy.config import TSConfig
from apps.proxy.live_proxy.config_helper import ConfigHelper
from apps.proxy.live_proxy.input.manager import StreamManager
from core.models import CoreSettings
from core.serializers import ProxySettingsSerializer

MIGRATION_0026 = import_module("core.migrations.0026_add_channel_client_wait_period")


class TSConfigProxySettingsDefaultsTests(SimpleTestCase):
    @patch.object(TSConfig, "get_proxy_settings", return_value={})
    def test_channel_init_grace_period_default(self, _mock_settings):
        self.assertEqual(TSConfig.get_channel_init_grace_period(), 60)

    @patch.object(TSConfig, "get_proxy_settings", return_value={})
    def test_channel_client_wait_period_default(self, _mock_settings):
        self.assertEqual(TSConfig.get_channel_client_wait_period(), 5)

    @patch.object(TSConfig, "get_proxy_settings", return_value={})
    def test_stream_startup_timeout_default(self, _mock_settings):
        self.assertEqual(TSConfig.get_stream_startup_timeout(), 8)

    @patch.object(TSConfig, "get_proxy_settings", return_value={})
    def test_connection_timeout_default(self, _mock_settings):
        self.assertEqual(TSConfig.get_connection_timeout(), 10)

    @patch.object(TSConfig, "get_proxy_settings", return_value={})
    def test_validate_redirect_urls_default(self, _mock_settings):
        self.assertTrue(TSConfig.get_validate_redirect_urls())

    @patch.object(
        TSConfig,
        "get_proxy_settings",
        return_value={
            "channel_init_grace_period": 120,
            "channel_client_wait_period": 15,
            "stream_startup_timeout": 5,
            "connection_timeout": 12,
            "validate_redirect_urls": False,
        },
    )
    def test_settings_override_db_values(self, _mock_settings):
        self.assertEqual(TSConfig.get_channel_init_grace_period(), 120)
        self.assertEqual(TSConfig.get_channel_client_wait_period(), 15)
        self.assertEqual(TSConfig.get_stream_startup_timeout(), 5)
        self.assertEqual(TSConfig.get_connection_timeout(), 12)
        self.assertFalse(TSConfig.get_validate_redirect_urls())


class HealthInactivityThresholdTests(SimpleTestCase):
    """A connection with no data yet uses stream_startup_timeout."""

    def _manager(self, awaiting_data):
        sm = StreamManager.__new__(StreamManager)
        sm.connected = True
        sm._connection_awaiting_data = awaiting_data
        return sm

    @patch.object(ConfigHelper, "stream_startup_timeout", return_value=8)
    @patch.object(ConfigHelper, "connection_timeout", return_value=10)
    def test_new_connection_uses_stream_startup_timeout(self, _conn, _startup):
        self.assertEqual(self._manager(True)._health_inactivity_threshold(), 8)

    @patch.object(ConfigHelper, "stream_startup_timeout", return_value=8)
    @patch.object(ConfigHelper, "connection_timeout", return_value=10)
    def test_connection_with_data_uses_connection_timeout(self, _conn, _startup):
        self.assertEqual(self._manager(False)._health_inactivity_threshold(), 10)

    @patch.object(ConfigHelper, "channel_init_grace_period", return_value=60)
    @patch.object(ConfigHelper, "stream_startup_timeout", return_value=8)
    @patch.object(ConfigHelper, "connection_timeout", return_value=10)
    def test_no_other_stream_and_empty_buffer_waits_the_init_grace(
        self, _conn, _startup, _grace
    ):
        sm = self._manager(True)
        sm._startup_failover_exhausted = True
        sm.buffer = MagicMock(index=0)
        self.assertEqual(sm._health_inactivity_threshold(), 60)

    @patch.object(ConfigHelper, "channel_init_grace_period", return_value=60)
    @patch.object(ConfigHelper, "stream_startup_timeout", return_value=8)
    @patch.object(ConfigHelper, "connection_timeout", return_value=10)
    def test_no_other_stream_but_buffer_has_data_uses_connection_timeout(
        self, _conn, _startup, _grace
    ):
        sm = self._manager(True)
        sm._startup_failover_exhausted = True
        sm.buffer = MagicMock(index=4)
        self.assertEqual(sm._health_inactivity_threshold(), 10)

    @patch.object(ConfigHelper, "channel_init_grace_period", return_value=60)
    @patch.object(ConfigHelper, "stream_startup_timeout", return_value=8)
    @patch.object(ConfigHelper, "connection_timeout", return_value=10)
    def test_connection_that_sent_data_never_uses_the_init_grace(
        self, _conn, _startup, _grace
    ):
        sm = self._manager(False)
        sm._startup_failover_exhausted = True
        sm.buffer = MagicMock(index=0)
        self.assertEqual(sm._health_inactivity_threshold(), 10)


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
            "stream_startup_timeout": 8,
            "connection_timeout": 10,
            "validate_redirect_urls": True,
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

    def test_stream_timeouts_default_when_omitted(self):
        payload = self._valid_payload()
        payload.pop("stream_startup_timeout")
        payload.pop("connection_timeout")
        serializer = ProxySettingsSerializer(data=payload)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data["stream_startup_timeout"], 8)
        self.assertEqual(serializer.validated_data["connection_timeout"], 10)

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

    def test_connection_timeout_rejects_above_120(self):
        serializer = ProxySettingsSerializer(
            data=self._valid_payload(connection_timeout=121)
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("connection_timeout", serializer.errors)

    def test_connection_timeout_allows_120(self):
        serializer = ProxySettingsSerializer(
            data=self._valid_payload(connection_timeout=120)
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_stream_startup_timeout_rejects_zero(self):
        serializer = ProxySettingsSerializer(
            data=self._valid_payload(stream_startup_timeout=0)
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("stream_startup_timeout", serializer.errors)


class CoreSettingsProxyDefaultsTests(TestCase):
    def test_get_proxy_settings_defaults_when_missing(self):
        CoreSettings.objects.filter(key="proxy_settings").delete()
        defaults = CoreSettings.get_proxy_settings()
        self.assertEqual(defaults["channel_init_grace_period"], 60)
        self.assertEqual(defaults["channel_client_wait_period"], 5)
        self.assertEqual(defaults["stream_startup_timeout"], 8)
        self.assertEqual(defaults["connection_timeout"], 10)
        self.assertTrue(defaults["validate_redirect_urls"])


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
