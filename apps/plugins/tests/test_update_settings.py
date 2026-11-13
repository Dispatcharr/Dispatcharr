"""PluginManager.update_settings: table/multiselect validation and handling
of settings keys with no matching declared field."""

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from apps.plugins.loader import LoadedPlugin, PluginManager


class UpdateSettingsTests(SimpleTestCase):
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

        with patch("apps.plugins.loader.PluginConfig.objects.get", return_value=cfg):
            result = pm.update_settings("my-plugin", {"known": "a", "stale_removed_field": "b"})

        self.assertEqual(result, {"known": "a"})

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

        with patch("apps.plugins.loader.PluginConfig.objects.get", return_value=cfg):
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

        with patch("apps.plugins.loader.PluginConfig.objects.get", return_value=cfg):
            result = pm.update_settings("my-plugin", {"anything": "goes"})

        self.assertEqual(result, cfg.settings)
