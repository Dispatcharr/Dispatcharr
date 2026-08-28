"""Tests for the system-settings log field coercion."""

from django.test import TestCase, override_settings

from core.models import CoreSettings, SYSTEM_SETTINGS_KEY
from core.serializers import CoreSettingsSerializer, _clamp_int


class ClampIntTests(TestCase):
    def test_coerces_and_clamps(self):
        self.assertEqual(_clamp_int("abc", 10, 1, 1000), 10)  # garbage -> default
        self.assertEqual(_clamp_int(None, 10, 1, 1000), 10)
        self.assertEqual(_clamp_int("50", 10, 1, 1000), 50)
        self.assertEqual(_clamp_int(5000, 10, 1, 1000), 1000)
        self.assertEqual(_clamp_int(0, 10, 1, 1000), 1)
        self.assertEqual(_clamp_int(10.9, 10, 1, 1000), 10)


# locmem cache: isolates this test's settings write from the shared Redis-backed group cache.
@override_settings(
    CACHES={
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "log-rotation-tests",
        }
    }
)
class SystemSettingsCoercionTests(TestCase):
    def test_update_coerces_log_settings(self):
        inst, _ = CoreSettings.objects.get_or_create(
            key=SYSTEM_SETTINGS_KEY, defaults={"value": {}}
        )
        CoreSettingsSerializer().update(
            inst, {"value": {"log_max_mb": "abc", "log_keep": 999}}
        )
        inst.refresh_from_db()
        self.assertEqual(inst.value["log_max_mb"], 10)  # garbage -> default
        self.assertEqual(inst.value["log_keep"], 50)  # above max -> clamped
