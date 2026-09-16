"""PATCH /api/m3u/accounts/{id}/group-settings/ category_settings handling:
merge (not replace) of custom_properties, language/quality validation, and
cache invalidation."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from apps.m3u.models import M3UAccount
from apps.vod.language import get_category_metadata, invalidate_category_metadata_cache
from apps.vod.models import M3UVODCategoryRelation, VODCategory

User = get_user_model()


class GroupSettingsCategoryLanguageTests(TestCase):
    def setUp(self):
        invalidate_category_metadata_cache()
        self.addCleanup(invalidate_category_metadata_cache)

        self.user = User.objects.create_user(username="settingsuser", password="testpass123")
        self.user.user_level = 10
        self.user.save()
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

        self.account = M3UAccount.objects.create(
            name="Settings Provider",
            server_url="http://example.com/a.m3u",
        )
        self.category = VODCategory.objects.create(name="Spanish", category_type="movie")

    def _patch(self, category_settings):
        return self.client.patch(
            f"/api/m3u/accounts/{self.account.id}/group-settings/",
            {"category_settings": category_settings},
            format="json",
        )

    def test_sets_language_on_new_relation(self):
        response = self._patch([
            {"id": self.category.id, "enabled": True, "custom_properties": {"language": "es"}}
        ])
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        relation = M3UVODCategoryRelation.objects.get(
            m3u_account=self.account, category=self.category
        )
        self.assertEqual(relation.custom_properties.get("language"), "es")

    def test_merges_quality_without_wiping_existing_language(self):
        M3UVODCategoryRelation.objects.create(
            m3u_account=self.account,
            category=self.category,
            enabled=True,
            custom_properties={"language": "es"},
        )

        response = self._patch([
            {"id": self.category.id, "enabled": True, "custom_properties": {"quality": "1080p"}}
        ])
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        relation = M3UVODCategoryRelation.objects.get(
            m3u_account=self.account, category=self.category
        )
        self.assertEqual(relation.custom_properties.get("language"), "es")
        self.assertEqual(relation.custom_properties.get("quality"), "1080p")

    def test_updating_language_overwrites_only_that_key(self):
        M3UVODCategoryRelation.objects.create(
            m3u_account=self.account,
            category=self.category,
            enabled=True,
            custom_properties={"language": "es", "quality": "720p"},
        )

        response = self._patch([
            {"id": self.category.id, "enabled": True, "custom_properties": {"language": "fr"}}
        ])
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        relation = M3UVODCategoryRelation.objects.get(
            m3u_account=self.account, category=self.category
        )
        self.assertEqual(relation.custom_properties.get("language"), "fr")
        self.assertEqual(relation.custom_properties.get("quality"), "720p")

    def test_rejects_invalid_language_code(self):
        response = self._patch([
            {"id": self.category.id, "enabled": True, "custom_properties": {"language": "eng"}}
        ])
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(
            M3UVODCategoryRelation.objects.filter(
                m3u_account=self.account, category=self.category
            ).exists()
        )

    def test_rejects_invalid_quality_value(self):
        response = self._patch([
            {"id": self.category.id, "enabled": True, "custom_properties": {"quality": "8K"}}
        ])
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_batch_of_categories_in_one_patch(self):
        other_category = VODCategory.objects.create(name="French", category_type="movie")

        response = self._patch([
            {"id": self.category.id, "enabled": True, "custom_properties": {"language": "es"}},
            {"id": other_category.id, "enabled": True, "custom_properties": {"language": "fr"}},
        ])
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            M3UVODCategoryRelation.objects.get(
                m3u_account=self.account, category=self.category
            ).custom_properties.get("language"),
            "es",
        )
        self.assertEqual(
            M3UVODCategoryRelation.objects.get(
                m3u_account=self.account, category=other_category
            ).custom_properties.get("language"),
            "fr",
        )

    def test_cache_is_invalidated_after_update(self):
        # Prime the cache with the pre-update (empty) state.
        self.assertEqual(get_category_metadata(), {})

        response = self._patch([
            {"id": self.category.id, "enabled": True, "custom_properties": {"language": "es"}}
        ])
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        meta = get_category_metadata()
        self.assertEqual(meta[(self.account.id, self.category.id)]["language"], "es")
