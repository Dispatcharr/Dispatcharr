from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.mac_panel.credentials import build_xc_payload
from apps.mac_panel.models import MacPanelDevice

User = get_user_model()


class BuildXcPayloadTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="streamer1",
            password="testpass123",
            custom_properties={"xc_password": "supersecret"},
        )
        self.device = MacPanelDevice.objects.create(
            user=self.user,
            panel="iboxx",
            mac_address="aa:bb:cc:dd:ee:ff",
            device_key="devicekey",
            playlist_name="My Playlist",
        )

    def test_basic_fields(self):
        payload = build_xc_payload(self.user, self.device, "https://teve.example.com")
        self.assertEqual(payload["playlist_type"], "xc")
        self.assertEqual(payload["playlist_url"], "https://teve.example.com")
        self.assertEqual(payload["username"], "streamer1")
        self.assertEqual(payload["password"], "supersecret")
        self.assertEqual(payload["playlist_name"], "My Playlist")
        self.assertEqual(payload["protect"], 0)
        self.assertEqual(payload["pin"], "")
        self.assertEqual(payload["provider_email"], "")
        self.assertEqual(payload["provider_number"], "")

    def test_epg_url_present_when_include_epg_true(self):
        self.device.include_epg = True
        payload = build_xc_payload(self.user, self.device, "https://teve.example.com")
        self.assertEqual(
            payload["xml_url"],
            "https://teve.example.com/xmltv.php?username=streamer1&password=supersecret",
        )

    def test_epg_url_absent_when_include_epg_false(self):
        self.device.include_epg = False
        payload = build_xc_payload(self.user, self.device, "https://teve.example.com")
        self.assertEqual(payload["xml_url"], "")

    def test_current_playlist_id_is_minus_one_when_no_prior_push(self):
        self.device.last_playlist_id = ""
        payload = build_xc_payload(self.user, self.device, "https://teve.example.com")
        self.assertEqual(payload["current_playlist_url_id"], -1)

    def test_current_playlist_id_reused_on_repush(self):
        self.device.last_playlist_id = "abc123"
        payload = build_xc_payload(self.user, self.device, "https://teve.example.com")
        self.assertEqual(payload["current_playlist_url_id"], "abc123")

    def test_missing_xc_password_defaults_to_empty_string(self):
        self.user.custom_properties = {}
        payload = build_xc_payload(self.user, self.device, "https://teve.example.com")
        self.assertEqual(payload["password"], "")

    def test_protect_and_pin_absent_when_no_pin_set(self):
        self.device.protect_pin = ""
        payload = build_xc_payload(self.user, self.device, "https://teve.example.com")
        self.assertEqual(payload["protect"], 0)
        self.assertEqual(payload["pin"], "")

    def test_protect_and_pin_present_when_pin_set(self):
        self.device.protect_pin = "1234"
        payload = build_xc_payload(self.user, self.device, "https://teve.example.com")
        self.assertEqual(payload["protect"], 1)
        self.assertEqual(payload["pin"], "1234")
