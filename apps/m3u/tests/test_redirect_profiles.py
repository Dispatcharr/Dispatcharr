from unittest.mock import MagicMock

from django.test import TestCase

from apps.accounts.models import User
from apps.m3u.models import M3UAccount, M3UAccountProfile
from apps.m3u.redirect_profiles import get_redirect_profiles


class RedirectProfilesTests(TestCase):
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

    def test_empty_setting_preserves_unrestricted_routing(self):
        self.assertIsNone(get_redirect_profiles(self.user))

    def test_non_dict_custom_properties_preserves_unrestricted_routing(self):
        self.assertIsNone(get_redirect_profiles(MagicMock()))

    def test_profiles_are_active_and_ordered_by_id(self):
        self.extra_profile.is_active = False
        self.extra_profile.save()
        self.user.custom_properties = {
            "redirect_mode_profile_ids": [self.extra_profile.id, self.default_profile.id]
        }

        self.assertEqual(get_redirect_profiles(self.user), [self.default_profile])
