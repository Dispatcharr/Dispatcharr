from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.mac_panel.models import MacPanelDevice, normalize_mac_address

User = get_user_model()


class MacAddressNormalizationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="owner", password="testpass123")

    def _make(self, mac_address):
        return MacPanelDevice.objects.create(
            user=self.user,
            panel="iboxx",
            mac_address=mac_address,
            device_key="key123",
        )

    def test_normalizes_lowercase_colon_separated(self):
        device = self._make("aa:bb:cc:dd:ee:ff")
        self.assertEqual(device.mac_address, "AA:BB:CC:DD:EE:FF")

    def test_normalizes_hyphen_separated(self):
        device = self._make("aa-bb-cc-dd-ee-ff")
        self.assertEqual(device.mac_address, "AA:BB:CC:DD:EE:FF")

    def test_normalizes_no_separator(self):
        device = self._make("aabbccddeeff")
        self.assertEqual(device.mac_address, "AA:BB:CC:DD:EE:FF")

    def test_rejects_invalid_mac(self):
        with self.assertRaises(ValidationError):
            self._make("not-a-mac")

    def test_normalize_helper_handles_empty(self):
        self.assertEqual(normalize_mac_address(""), "")
        self.assertIsNone(normalize_mac_address(None))

    def test_unique_together_panel_and_mac(self):
        self._make("aa:bb:cc:dd:ee:ff")
        with self.assertRaises(Exception):
            self._make("aa:bb:cc:dd:ee:ff")
