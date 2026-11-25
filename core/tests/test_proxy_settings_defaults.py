from django.test import TestCase

from core.models import CoreSettings, PROXY_SETTINGS_KEY


class ProxySettingsDefaultsTest(TestCase):
    """Verify proxy settings expose merged defaults for new resilience knobs."""

    def test_missing_proxy_setting_keys_are_backfilled_in_getter(self):
        CoreSettings.objects.update_or_create(
            key=PROXY_SETTINGS_KEY,
            defaults={
                "name": "Proxy Settings",
                "value": {"new_client_behind_seconds": 15},
            },
        )

        result = CoreSettings.get_proxy_settings()

        self.assertEqual(result["new_client_behind_seconds"], 15)
        self.assertEqual(result["connection_ready_chunks"], 16)
        self.assertEqual(result["max_retries"], 3)
        self.assertEqual(result["min_stable_time_before_reconnect"], 10)
