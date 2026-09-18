from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.m3u.models import M3UAccount
from apps.vod.defaults import ensure_default_vod_policy
from apps.vod.models import (
    M3UVODCategoryRelation,
    VODAccessPolicy,
    VODCategory,
    VODPolicyCategory,
)
from apps.vod.policies import policy_category_map
from apps.vod.profile_selection import profile_ids_using_source_categories


class DefaultVODPolicyTests(TestCase):
    def test_default_policy_uses_compact_clean_title_output(self):
        policy = ensure_default_vod_policy()
        account = M3UAccount.objects.create(
            name="Default profile provider",
            server_url="http://provider.example.com",
            username="user",
            password="pass",
            account_type=M3UAccount.Types.XC,
            is_active=True,
        )
        category = VODCategory.objects.create(
            name="Movies",
            category_type="movie",
        )
        M3UVODCategoryRelation.objects.create(
            m3u_account=account,
            category=category,
            enabled=True,
        )

        self.assertEqual(policy.name, "All")
        self.assertEqual(policy.export_mode, VODAccessPolicy.ExportMode.COMPACT)
        self.assertEqual(policy.name_template, "{title}")
        self.assertEqual(
            policy.canonical_title_source,
            VODAccessPolicy.CanonicalTitleSource.PRIMARY,
        )
        self.assertEqual(
            policy.metadata_source,
            VODAccessPolicy.MetadataSource.CANONICAL,
        )
        self.assertIn((account.id, category.id), policy_category_map(policy))

    def test_new_users_receive_the_default_policy(self):
        user = get_user_model().objects.create_user(
            username="default-vod-user",
            password="password",
        )

        self.assertEqual(
            list(user.vod_access_policies.values_list("name", flat=True)),
            ["All"],
        )

    def test_existing_default_policy_configuration_is_preserved(self):
        policy = ensure_default_vod_policy()
        policy.name_template = "{title} ({year}) {edition}"
        policy.edition_rules = [
            {
                "id": "edition-4k",
                "name": "4K",
                "title_suffix": "4K",
                "enabled": True,
                "min_resolution": 2160,
                "max_resolution": 0,
                "required_audio_languages": [],
                "required_subtitle_languages": [],
                "required_video_features": [],
            }
        ]
        policy.save(update_fields=["name_template", "edition_rules"])

        ensured = ensure_default_vod_policy()
        ensured.refresh_from_db()

        self.assertEqual(
            ensured.name_template,
            "{title} ({year}) {edition}",
        )
        self.assertEqual(ensured.edition_rules, policy.edition_rules)

    def test_existing_assignment_is_not_replaced(self):
        user = get_user_model().objects.create_user(
            username="custom-vod-user",
            password="password",
        )
        custom = VODAccessPolicy.objects.create(name="Custom")
        user.vod_access_policies.clear()
        custom.users.add(user)

        ensure_default_vod_policy()

        self.assertEqual(list(user.vod_access_policies.all()), [custom])

    def test_source_changes_only_outdate_profiles_allowing_that_category(self):
        account = M3UAccount.objects.create(
            name="Scoped provider",
            server_url="http://provider.example.com",
            username="user",
            password="pass",
            account_type=M3UAccount.Types.XC,
            is_active=True,
        )
        included_category = VODCategory.objects.create(
            name="Included movies",
            category_type="movie",
        )
        excluded_category = VODCategory.objects.create(
            name="Other movies",
            category_type="movie",
        )
        included_relation = M3UVODCategoryRelation.objects.create(
            m3u_account=account,
            category=included_category,
            enabled=True,
        )
        excluded_relation = M3UVODCategoryRelation.objects.create(
            m3u_account=account,
            category=excluded_category,
            enabled=True,
        )
        included = VODAccessPolicy.objects.create(
            name="Included profile",
            active_selection_generation="included-generation",
        )
        excluded = VODAccessPolicy.objects.create(
            name="Excluded profile",
            active_selection_generation="excluded-generation",
        )
        VODPolicyCategory.objects.create(
            policy=included,
            category_relation=included_relation,
            enabled=True,
        )
        VODPolicyCategory.objects.create(
            policy=excluded,
            category_relation=excluded_relation,
            enabled=True,
        )

        self.assertEqual(
            profile_ids_using_source_categories(
                [(account.id, included_category.id)]
            ),
            [included.id],
        )
