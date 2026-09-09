from unittest.mock import MagicMock

from django.test import TestCase

from apps.accounts.models import User
from apps.m3u.models import M3UAccount, M3UAccountProfile
from apps.m3u.utils import (
    get_allowed_m3u_profiles,
    scrub_allowed_m3u_profile_id,
)


class AllowedProfilesTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="viewer", password="password")
        self.account = M3UAccount.objects.create(name="Provider")
        self.default_profile = self.account.profiles.get(is_default=True)
        self.extra_profile = M3UAccountProfile.objects.create(
            m3u_account=self.account,
            name="Extra",
            search_pattern="^(.*)$",
            replace_pattern="$1",
        )

    def test_missing_key_preserves_unrestricted_routing(self):
        self.assertIsNone(get_allowed_m3u_profiles(self.user))

    def test_null_value_preserves_unrestricted_routing(self):
        self.user.custom_properties = {"allowed_m3u_profile_ids": None}
        self.assertIsNone(get_allowed_m3u_profiles(self.user))

    def test_non_dict_custom_properties_preserves_unrestricted_routing(self):
        self.assertIsNone(get_allowed_m3u_profiles(MagicMock()))

    def test_empty_list_means_no_profiles(self):
        self.user.custom_properties = {"allowed_m3u_profile_ids": []}
        self.assertEqual(get_allowed_m3u_profiles(self.user), {})

    def test_malformed_value_fails_closed(self):
        self.user.custom_properties = {"allowed_m3u_profile_ids": "1,2"}
        self.assertEqual(get_allowed_m3u_profiles(self.user), {})

    def test_profiles_are_active_and_grouped_by_account(self):
        self.extra_profile.is_active = False
        self.extra_profile.save()
        self.user.custom_properties = {
            "allowed_m3u_profile_ids": [self.extra_profile.id, self.default_profile.id]
        }

        self.assertEqual(
            get_allowed_m3u_profiles(self.user),
            {self.account.id: [self.default_profile]},
        )

    def test_orphan_ids_only_yield_empty_map_not_unrestricted(self):
        self.user.custom_properties = {"allowed_m3u_profile_ids": [999999]}
        self.assertEqual(get_allowed_m3u_profiles(self.user), {})

    def test_scrub_removes_profile_id_and_keeps_empty_key(self):
        other = User.objects.create_user(username="other", password="password")
        self.user.custom_properties = {
            "allowed_m3u_profile_ids": [self.default_profile.id, self.extra_profile.id]
        }
        self.user.save(update_fields=["custom_properties"])
        other.custom_properties = {
            "allowed_m3u_profile_ids": [self.extra_profile.id]
        }
        other.save(update_fields=["custom_properties"])

        scrub_allowed_m3u_profile_id(self.extra_profile.id)

        self.user.refresh_from_db()
        other.refresh_from_db()
        self.assertEqual(
            self.user.custom_properties["allowed_m3u_profile_ids"],
            [self.default_profile.id],
        )
        self.assertEqual(other.custom_properties["allowed_m3u_profile_ids"], [])
        self.assertEqual(get_allowed_m3u_profiles(other), {})

    def test_profile_delete_scrubs_user_allowlists(self):
        self.user.custom_properties = {
            "allowed_m3u_profile_ids": [self.extra_profile.id]
        }
        self.user.save(update_fields=["custom_properties"])

        profile_id = self.extra_profile.id
        self.extra_profile.delete()

        self.user.refresh_from_db()
        self.assertEqual(self.user.custom_properties["allowed_m3u_profile_ids"], [])
        self.assertNotIn(profile_id, self.user.custom_properties["allowed_m3u_profile_ids"])
