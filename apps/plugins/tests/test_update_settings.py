"""PluginManager.update_settings: table/multiselect validation and handling
of settings keys with no matching declared field."""

from contextlib import nullcontext
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, TestCase

from apps.plugins.loader import LoadedPlugin, PluginManager
from apps.plugins.models import PluginConfig


class UpdateSettingsTests(SimpleTestCase):
    def setUp(self):
        super().setUp()
        self.atomic = patch("apps.plugins.loader.transaction.atomic", return_value=nullcontext())
        self.atomic.start()
        self.addCleanup(self.atomic.stop)

    def _lp(self, fields):
        return LoadedPlugin(key="my-plugin", name="My Plugin", fields=fields)

    def _pm_with_plugin(self, lp):
        pm = PluginManager()
        pm.get_plugin = MagicMock(return_value=lp)
        return pm

    def test_unknown_keys_are_dropped_not_rejected(self):
        lp = self._lp([{"id": "known", "type": "string"}])
        pm = self._pm_with_plugin(lp)
        cfg = MagicMock(settings={})

        with patch("apps.plugins.loader.PluginConfig.objects.select_for_update") as lock:
            lock.return_value.get.return_value = cfg
            result = pm.update_settings("my-plugin", {"known": "a", "stale_removed_field": "b"})

        self.assertEqual(result, {"known": "a"})

    def test_preserves_plugin_managed_settings_and_ignores_unknown_input(self):
        lp = self._lp([{"id": "known", "type": "string"}, {"id": "removed", "type": "string"}])
        pm = self._pm_with_plugin(lp)
        cfg = MagicMock(settings={"known": "old", "removed": "old", "multiview_order": ["abc"],
                                  "multiview_abc_channel_1": "42"})
        with patch("apps.plugins.loader.PluginConfig.objects.select_for_update") as lock:
            lock.return_value.get.return_value = cfg
            result = pm.update_settings("my-plugin", {"known": "new", "multiview_order": ["bad"],
                                                       "unknown": "ignored"})
        self.assertEqual(result, {"known": "new", "multiview_order": ["abc"],
                                  "multiview_abc_channel_1": "42"})
        lock.return_value.get.assert_called_once_with(key="my-plugin")

    def test_multiselect_rejects_value_outside_options(self):
        lp = self._lp([
            {"id": "tags", "type": "multiselect", "options": [{"value": "x"}, {"value": "y"}]},
        ])
        pm = self._pm_with_plugin(lp)

        with self.assertRaises(ValueError):
            pm.update_settings("my-plugin", {"tags": ["x", "not-an-option"]})

    def test_multiselect_accepts_declared_options(self):
        lp = self._lp([
            {"id": "tags", "type": "multiselect", "options": [{"value": "x"}, {"value": "y"}]},
        ])
        pm = self._pm_with_plugin(lp)
        cfg = MagicMock(settings={})

        with patch("apps.plugins.loader.PluginConfig.objects.select_for_update") as lock:
            lock.return_value.get.return_value = cfg
            result = pm.update_settings("my-plugin", {"tags": ["x", "y"]})

        self.assertEqual(result, cfg.settings)


    def test_multiselect_requires_list(self):
        lp = self._lp([{"id": "tags", "type": "multiselect", "options": [{"value": "x"}]}])
        pm = self._pm_with_plugin(lp)

        with self.assertRaises(ValueError):
            pm.update_settings("my-plugin", {"tags": "x"})

    def test_no_known_fields_passes_settings_through_unfiltered(self):
        """Plugin failed to load / has no manifest fields; don't wipe settings."""
        lp = self._lp([])
        pm = self._pm_with_plugin(lp)
        cfg = MagicMock(settings={})

        with patch("apps.plugins.loader.PluginConfig.objects.select_for_update") as lock:
            lock.return_value.get.return_value = cfg
            result = pm.update_settings("my-plugin", {"anything": "goes"})

        self.assertEqual(result, cfg.settings)


class UpdateSettingsDatabaseTests(TestCase):
    def test_native_save_preserves_plugin_state_in_database(self):
        cfg = PluginConfig.objects.create(
            key="multiview", name="Multiview", settings={
                "output_fps": "30",
                "multiview_order": ["abc"],
                "multiview_abc_channel_1": "42",
                "obsolete_field": "kept",
            },
        )
        pm = PluginManager()
        pm.get_plugin = MagicMock(return_value=LoadedPlugin(
            key="multiview", name="Multiview", fields=[{"id": "output_fps", "type": "select"}],
        ))

        pm.update_settings("multiview", {"output_fps": "60000/1001", "multiview_order": ["stale"]})
        cfg.refresh_from_db()
        self.assertEqual(cfg.settings, {
            "output_fps": "60000/1001",
            "multiview_order": ["abc"],
            "multiview_abc_channel_1": "42",
            "obsolete_field": "kept",
        })
