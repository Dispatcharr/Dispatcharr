"""Tests for the system-settings log field coercion."""

from django.test import TestCase, override_settings

from core.models import CoreSettings, SYSTEM_SETTINGS_KEY
from core.serializers import CoreSettingsSerializer, _clamp_int


class ClampIntTests(TestCase):
    def test_coerces_and_clamps(self):
        self.assertEqual(_clamp_int("abc", 10, 1, 1000), 10)  # garbage -> default
        self.assertEqual(_clamp_int(None, 10, 1, 1000), 10)  # missing -> default
        self.assertEqual(_clamp_int("50", 10, 1, 1000), 50)  # numeric string
        self.assertEqual(_clamp_int(5000, 10, 1, 1000), 1000)  # above hi -> hi
        self.assertEqual(_clamp_int(0, 10, 1, 1000), 1)  # below lo -> lo
        self.assertEqual(_clamp_int(10.9, 10, 1, 1000), 10)  # float truncates


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
        # A raw API payload with garbage log settings must persist as clamped ints, so the collector never reads back garbage.
        inst, _ = CoreSettings.objects.get_or_create(
            key=SYSTEM_SETTINGS_KEY, defaults={"value": {}}
        )
        CoreSettingsSerializer().update(
            inst, {"value": {"log_max_mb": "abc", "log_keep": 999}}
        )
        inst.refresh_from_db()
        self.assertEqual(inst.value["log_max_mb"], 10)  # garbage -> default
        self.assertEqual(inst.value["log_keep"], 50)  # above max -> clamped
