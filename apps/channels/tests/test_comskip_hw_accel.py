"""Comskip hardware-accel setting maps to flags the bundled binary accepts."""

from django.test import SimpleTestCase
from unittest.mock import patch

from apps.channels.tasks import _comskip_hw_accel_flag
from core.models import CoreSettings


class ComskipHwAccelFlagTests(SimpleTestCase):
    def test_none_and_empty_yield_no_flag(self):
        self.assertIsNone(_comskip_hw_accel_flag("none"))
        self.assertIsNone(_comskip_hw_accel_flag(""))
        self.assertIsNone(_comskip_hw_accel_flag(None))

    def test_cuvid_maps_to_cuvid_flag(self):
        self.assertEqual(_comskip_hw_accel_flag("cuvid"), "--cuvid")

    def test_hwassist_maps_to_hwassist_flag(self):
        self.assertEqual(_comskip_hw_accel_flag("hwassist"), "--hwassist")

    def test_legacy_qsv_maps_to_hwassist_flag(self):
        """Bundled Comskip has --hwassist, not --qsv."""
        self.assertEqual(_comskip_hw_accel_flag("qsv"), "--hwassist")

    def test_unknown_setting_yields_no_flag(self):
        self.assertIsNone(_comskip_hw_accel_flag("vdpau"))


class ComskipHwAccelSettingTests(SimpleTestCase):
    @patch.object(CoreSettings, "get_dvr_settings")
    def test_getter_accepts_hwassist(self, mock_settings):
        mock_settings.return_value = {"comskip_hw_accel": "hwassist"}
        self.assertEqual(CoreSettings.get_dvr_comskip_hw_accel(), "hwassist")

    @patch.object(CoreSettings, "get_dvr_settings")
    def test_getter_normalizes_legacy_qsv(self, mock_settings):
        mock_settings.return_value = {"comskip_hw_accel": "qsv"}
        self.assertEqual(CoreSettings.get_dvr_comskip_hw_accel(), "hwassist")

    @patch.object(CoreSettings, "get_dvr_settings")
    def test_getter_rejects_unknown(self, mock_settings):
        mock_settings.return_value = {"comskip_hw_accel": "vdpau"}
        self.assertEqual(CoreSettings.get_dvr_comskip_hw_accel(), "none")
