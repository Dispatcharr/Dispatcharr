"""EPG history limits read from the epg_settings group."""

from django.core.cache import cache
from django.test import TestCase, override_settings

from core.models import (
    EPG_HISTORY_MAX_DAYS_DEFAULT,
    EPG_HISTORY_MIN_DAYS_DEFAULT,
    EPG_SETTINGS_KEY,
    CoreSettings,
    EpgHistoryPolicy,
)


# locmem cache: isolates these settings writes from the shared Redis-backed group cache.
@override_settings(
    CACHES={
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "epg-history-policy-tests",
        }
    }
)
class EpgHistoryPolicyTests(TestCase):
    def setUp(self):
        # A rolled-back write does not invalidate the group cache, so reset it
        # around every test.
        cache.clear()
        self.addCleanup(cache.clear)

    def _store(self, value):
        CoreSettings.objects.update_or_create(
            key=EPG_SETTINGS_KEY,
            defaults={"name": "EPG Settings", "value": value},
        )

    def test_defaults_without_a_stored_group(self):
        self.assertEqual(
            CoreSettings.get_epg_history_policy(),
            EpgHistoryPolicy(
                EPG_HISTORY_MIN_DAYS_DEFAULT, EPG_HISTORY_MAX_DAYS_DEFAULT, 0, 0
            ),
        )

    def test_group_stored_before_the_history_fields_existed_uses_defaults(self):
        self._store({"epg_match_mode": "default"})
        self.assertEqual(
            CoreSettings.get_epg_history_policy(),
            EpgHistoryPolicy(
                EPG_HISTORY_MIN_DAYS_DEFAULT, EPG_HISTORY_MAX_DAYS_DEFAULT, 0, 0
            ),
        )

    def test_stored_values_are_read(self):
        self._store(
            {
                "epg_history_min_days": 7,
                "epg_history_max_days": 14,
                "epg_default_prev_days": 3,
                "epg_default_days": 5,
            }
        )
        self.assertEqual(CoreSettings.get_epg_history_policy(), EpgHistoryPolicy(7, 14, 3, 5))

    def test_zero_is_a_real_value(self):
        self._store({"epg_history_min_days": 0, "epg_history_max_days": 0})
        policy = CoreSettings.get_epg_history_policy()
        self.assertEqual((policy.min_days, policy.max_days), (0, 0))

    def test_unreadable_values_fall_back_to_defaults(self):
        self._store(
            {
                "epg_history_min_days": "abc",
                "epg_history_max_days": None,
                "epg_default_prev_days": [],
                "epg_default_days": {},
            }
        )
        self.assertEqual(
            CoreSettings.get_epg_history_policy(),
            EpgHistoryPolicy(
                EPG_HISTORY_MIN_DAYS_DEFAULT, EPG_HISTORY_MAX_DAYS_DEFAULT, 0, 0
            ),
        )

    def test_values_are_clamped_to_the_allowed_range(self):
        self._store(
            {
                "epg_history_min_days": -4,
                "epg_history_max_days": 9999,
                "epg_default_days": 9999,
            }
        )
        policy = CoreSettings.get_epg_history_policy()
        self.assertEqual((policy.min_days, policy.max_days, policy.default_days), (0, 365, 365))

    def test_minimum_above_maximum_is_pulled_down(self):
        self._store({"epg_history_min_days": 20, "epg_history_max_days": 10})
        policy = CoreSettings.get_epg_history_policy()
        self.assertEqual((policy.min_days, policy.max_days), (10, 10))

    def test_default_days_back_cannot_exceed_the_maximum(self):
        self._store({"epg_history_max_days": 5, "epg_default_prev_days": 12})
        self.assertEqual(CoreSettings.get_epg_history_policy().default_prev_days, 5)

    def test_serializer_clamps_history_fields_on_write(self):
        from core.serializers import CoreSettingsSerializer

        obj, _ = CoreSettings.objects.update_or_create(
            key=EPG_SETTINGS_KEY,
            defaults={"name": "EPG Settings", "value": {}},
        )
        serializer = CoreSettingsSerializer(
            obj,
            data={
                "key": EPG_SETTINGS_KEY,
                "name": "EPG Settings",
                "value": {
                    "epg_history_min_days": 40,
                    "epg_history_max_days": 10,
                    "epg_default_prev_days": 50,
                    "epg_default_days": -3,
                },
            },
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        serializer.save()
        obj.refresh_from_db()
        self.assertEqual(obj.value["epg_history_max_days"], 10)
        self.assertEqual(obj.value["epg_history_min_days"], 10)
        self.assertEqual(obj.value["epg_default_prev_days"], 10)
        self.assertEqual(obj.value["epg_default_days"], 0)

    def test_serializer_clamps_history_fields_on_create(self):
        from core.serializers import CoreSettingsSerializer

        serializer = CoreSettingsSerializer(
            data={
                "key": EPG_SETTINGS_KEY,
                "name": "EPG Settings",
                "value": {
                    "epg_history_min_days": -2,
                    "epg_history_max_days": 9999,
                    "epg_default_prev_days": 3,
                    "epg_default_days": 400,
                },
            }
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        obj = serializer.save()
        self.assertEqual(obj.value["epg_history_max_days"], 365)
        self.assertEqual(obj.value["epg_history_min_days"], 0)
        self.assertEqual(obj.value["epg_default_prev_days"], 3)
        self.assertEqual(obj.value["epg_default_days"], 365)
