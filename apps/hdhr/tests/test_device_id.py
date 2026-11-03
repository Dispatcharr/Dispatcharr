"""HDHR DeviceID: per-instance random part, device.xml consistency, identity API."""
import json
import re
import xml.etree.ElementTree as ET
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.hdhr.models import HDHRDevice
from core.models import CoreSettings, HDHR_IDENTITY_KEY

DEVICE_ID_RE = re.compile(r"^dispatcharr-[a-z0-9]{8}$")


class HDHRDeviceIdTestBase(TestCase):
    def setUp(self):
        self._network_patch = patch(
            "apps.hdhr.api_views.network_access_allowed", return_value=True
        )
        self._network_patch.start()
        self.addCleanup(self._network_patch.stop)
        # Settings groups are cached in Redis, which is not rolled back with
        # the test transaction.
        CoreSettings.invalidate_group_cache(HDHR_IDENTITY_KEY)
        self.addCleanup(CoreSettings.invalidate_group_cache, HDHR_IDENTITY_KEY)
        HDHRDevice.objects.all().delete()
        CoreSettings.objects.filter(key=HDHR_IDENTITY_KEY).delete()

    def _discover(self, path="/hdhr/discover.json"):
        response = self.client.get(path)
        self.assertEqual(response.status_code, 200)
        return json.loads(response.content)

    def _device_xml(self):
        response = self.client.get("/hdhr/device.xml")
        self.assertEqual(response.status_code, 200)
        return ET.fromstring(response.content)


class HDHRDeviceIdTests(HDHRDeviceIdTestBase):
    def test_default_device_id_has_random_instance_part(self):
        device_id = self._discover()["DeviceID"]
        self.assertRegex(device_id, DEVICE_ID_RE)
        self.assertNotEqual(device_id, "12345678")

    def test_device_id_is_persisted_and_stable(self):
        first = self._discover()["DeviceID"]
        CoreSettings.invalidate_group_cache(HDHR_IDENTITY_KEY)
        self.assertEqual(self._discover()["DeviceID"], first)
        stored = CoreSettings.objects.get(key=HDHR_IDENTITY_KEY).value
        self.assertEqual(f"dispatcharr-{stored['instance_id']}", first)

    def test_regenerating_changes_device_id(self):
        first = self._discover()["DeviceID"]
        CoreSettings.regenerate_hdhr_instance_id()
        second = self._discover()["DeviceID"]
        self.assertRegex(second, DEVICE_ID_RE)
        self.assertNotEqual(first, second)

    def test_invalid_stored_instance_id_is_replaced(self):
        CoreSettings._update_group(
            HDHR_IDENTITY_KEY, "HDHR Identity", {"instance_id": "123"}
        )
        self.assertRegex(self._discover()["DeviceID"], DEVICE_ID_RE)

    def test_device_xml_matches_discover_without_device(self):
        root = self._device_xml()
        data = self._discover()
        self.assertEqual(root.findtext("DeviceID"), data["DeviceID"])
        self.assertEqual(root.findtext("FriendlyName"), data["FriendlyName"])

    def test_profile_urls_extend_the_instance_id(self):
        base = self._discover()["DeviceID"]
        self.assertEqual(
            self._discover("/hdhr/Sports/discover.json")["DeviceID"], f"{base}-Sports"
        )
        self.assertEqual(
            self._discover("/hdhr/output_profile/3/discover.json")["DeviceID"],
            f"{base}-3",
        )
        self.assertEqual(
            self._discover("/hdhr/Sports/output_profile/3/discover.json")["DeviceID"],
            f"{base}-Sports-3",
        )

    def test_existing_device_id_is_kept_everywhere(self):
        HDHRDevice.objects.create(friendly_name="Living Room", device_id="12345678")
        self.assertEqual(self._discover()["DeviceID"], "12345678")
        self.assertEqual(
            self._discover("/hdhr/Sports/discover.json")["DeviceID"], "12345678"
        )
        self.assertEqual(self._device_xml().findtext("DeviceID"), "12345678")

    def test_device_xml_escapes_values(self):
        HDHRDevice.objects.create(friendly_name="A & B <tv>", device_id="dev-1")
        self.assertEqual(self._device_xml().findtext("FriendlyName"), "A & B <tv>")


class HDHRIdentityAPITests(HDHRDeviceIdTestBase):
    url = "/api/hdhr/identity/"

    def setUp(self):
        super().setUp()
        User = get_user_model()
        self.admin = User.objects.create_user(
            username="hdhr-admin", password="pw", user_level=10
        )
        self.standard = User.objects.create_user(
            username="hdhr-user", password="pw", user_level=1
        )
        self.api = APIClient()

    def test_requires_admin(self):
        self.assertIn(self.api.get(self.url).status_code, (401, 403))
        self.api.force_authenticate(self.standard)
        self.assertEqual(self.api.get(self.url).status_code, 403)
        self.assertEqual(self.api.post(self.url).status_code, 403)

    def test_get_and_regenerate(self):
        self.api.force_authenticate(self.admin)
        first = self.api.get(self.url).json()
        self.assertRegex(first["device_id"], DEVICE_ID_RE)
        self.assertEqual(first["device_id"], f"dispatcharr-{first['instance_id']}")
        self.assertFalse(first["device_override"])
        self.assertEqual(self._discover()["DeviceID"], first["device_id"])

        second = self.api.post(self.url).json()
        self.assertNotEqual(second["instance_id"], first["instance_id"])
        self.assertEqual(self._discover()["DeviceID"], second["device_id"])

    def test_reports_device_override(self):
        HDHRDevice.objects.create(friendly_name="Living Room", device_id="fixed-id")
        self.api.force_authenticate(self.admin)
        data = self.api.get(self.url).json()
        self.assertEqual(data["device_id"], "fixed-id")
        self.assertTrue(data["device_override"])
