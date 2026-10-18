"""The self-service `/api/accounts/users/me/` PATCH endpoint must never let a
non-admin grant themselves broader provider-profile access, XC credentials,
or other admin-managed permissions via custom_properties.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

User = get_user_model()


class UserMeAdminOnlyPropsTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username="viewer",
            password="testpass123",
            custom_properties={"allowed_m3u_profile_ids": [1]},
        )
        self.client.force_authenticate(self.user)
        self.url = "/api/accounts/users/me/"

    def test_cannot_clear_allowed_m3u_profile_ids_to_escalate_to_all(self):
        response = self.client.patch(
            self.url,
            {"custom_properties": {"allowed_m3u_profile_ids": None}},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(
            self.user.custom_properties.get("allowed_m3u_profile_ids"), [1]
        )

    def test_cannot_widen_allowed_m3u_profile_ids(self):
        response = self.client.patch(
            self.url,
            {"custom_properties": {"allowed_m3u_profile_ids": [1, 2, 3]}},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(
            self.user.custom_properties.get("allowed_m3u_profile_ids"), [1]
        )

    def test_can_still_update_own_first_name(self):
        response = self.client.patch(
            self.url,
            {
                "first_name": "New",
                "custom_properties": {"allowed_m3u_profile_ids": None},
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, "New")
        # Admin-only key stripped before it ever reaches the merge logic.
        self.assertEqual(
            self.user.custom_properties.get("allowed_m3u_profile_ids"), [1]
        )

    def test_cannot_set_xc_password_via_me(self):
        response = self.client.patch(
            self.url,
            {"custom_properties": {"xc_password": "hacked123"}},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertNotIn("xc_password", self.user.custom_properties or {})

    def test_cannot_change_user_level_via_me(self):
        response = self.client.patch(
            self.url,
            {"user_level": 10},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertNotEqual(self.user.user_level, 10)
