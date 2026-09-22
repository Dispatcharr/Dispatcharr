from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.m3u.api_views import M3UAccountViewSet
from apps.m3u.models import M3UAccount


class GroupSettingsCatalogInvalidationTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_user(
            username="group-settings-admin",
            password="test-password",
            user_level=10,
        )
        self.account = M3UAccount.objects.create(
            name="provider",
            account_type=M3UAccount.Types.XC,
            server_url="https://provider.example",
            username="account",
            password="secret",
        )

    def test_live_only_group_save_keeps_vod_selection_generation_current(self):
        request = APIRequestFactory().patch(
            f"/api/m3u/accounts/{self.account.pk}/group-settings/",
            {"group_settings": [], "category_settings": []},
            format="json",
        )
        force_authenticate(request, user=self.admin)

        with (
            patch(
                "apps.vod.catalog_cache.bump_catalog_generation"
            ) as bump_catalog,
            patch(
                "apps.vod.profile_selection.enqueue_all_profile_selection_rebuilds"
            ) as enqueue_profiles,
        ):
            response = M3UAccountViewSet.as_view(
                {"patch": "update_group_settings"}
            )(request, pk=self.account.pk)

        self.assertEqual(response.status_code, 200, response.data)
        bump_catalog.assert_called_once_with(invalidate_selections=False)
        enqueue_profiles.assert_not_called()
