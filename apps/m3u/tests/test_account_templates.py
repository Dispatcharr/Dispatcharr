from django.test import TestCase

from apps.channels.models import (
    ChannelGroup,
    ChannelGroupM3UAccount,
    ChannelProfile,
    Logo,
)
from apps.epg.models import EPGSource
from apps.m3u.account_templates import (
    apply_account_template,
    capture_account_template,
)
from apps.m3u.models import M3UAccount, M3UFilter, M3UGroupRule
from apps.m3u.serializers import M3UAccountSerializer
from apps.m3u.tasks import process_groups
from apps.vod.models import M3UVODCategoryRelation, VODCategory
from apps.vod.tasks import batch_create_categories
from core.models import StreamProfile


class M3UAccountTemplateTests(TestCase):
    def setUp(self):
        self.source = M3UAccount.objects.create(
            name="source-account",
            account_type=M3UAccount.Types.XC,
            server_url="https://provider.example",
            username="secret-user",
            password="secret-password",
            max_streams=3,
            refresh_interval=12,
            xc_live_refresh_min_age_minutes=20,
            stale_stream_days=14,
            priority=7,
            custom_properties={
                "enable_vod": True,
                "use_group_rules_live": True,
                "use_group_rules_movie": True,
                "use_group_rules_series": False,
                "provider_secret": "must-not-be-copied",
            },
        )
        M3UFilter.objects.create(
            m3u_account=self.source,
            filter_type="group",
            regex_pattern=r"adult|xxx",
            exclude=True,
            order=0,
        )
        M3UGroupRule.objects.create(
            m3u_account=self.source,
            scope=M3UGroupRule.Scope.MOVIE,
            regex_pattern=r"^GERMANY",
            action=M3UGroupRule.Action.ENABLE,
            metadata_defaults={
                "audio_languages": ["ger"],
                "video_features": ["hdr"],
            },
            order=0,
        )
        self.live_group = ChannelGroup.objects.create(name="Sports")
        self.output_group = ChannelGroup.objects.create(name="Sports output")
        self.channel_profile = ChannelProfile.objects.create(name="Sports profile")
        self.stream_profile = StreamProfile.objects.create(
            name="Sports stream profile",
            command="",
            parameters="",
        )
        self.epg_source = EPGSource.objects.create(
            name="Sports EPG",
            source_type="xmltv",
        )
        self.logo = Logo.objects.create(
            name="Sports logo",
            url="https://example.com/sports.png",
        )
        ChannelGroupM3UAccount.objects.create(
            channel_group=self.live_group,
            m3u_account=self.source,
            enabled=True,
            auto_channel_sync=True,
            auto_sync_channel_start=100,
            auto_sync_channel_end=199,
            custom_properties={
                "xc_id": "provider-live-id",
                "discovery_rule_id": 77,
                "channel_numbering_mode": "provider",
                "channel_numbering_fallback": 100,
                "orphan_channel_cleanup": "preserve_customized",
                "group_override": self.output_group.id,
                "channel_profile_ids": [self.channel_profile.id],
                "stream_profile_id": self.stream_profile.id,
                "custom_epg_id": self.epg_source.id,
                "custom_logo_id": self.logo.id,
            },
        )
        self.movie_category = VODCategory.objects.create(
            name="Action", category_type="movie"
        )
        self.series_category = VODCategory.objects.create(
            name="Drama", category_type="series"
        )
        M3UVODCategoryRelation.objects.create(
            m3u_account=self.source,
            category=self.movie_category,
            enabled=True,
            metadata_defaults={"audio_languages": ["eng"]},
        )
        M3UVODCategoryRelation.objects.create(
            m3u_account=self.source,
            category=self.series_category,
            enabled=False,
            metadata_defaults={"resolution": "1080p"},
        )

    def test_capture_and_apply_copy_only_portable_settings_and_rules(self):
        template = capture_account_template(
            self.source,
            name="Provider defaults",
            description="Portable setup",
        )

        serialized = str(
            {
                "settings": template.account_settings,
                "filters": template.filters,
                "rules": template.group_rules,
            }
        )
        self.assertNotIn("secret-user", serialized)
        self.assertNotIn("secret-password", serialized)
        self.assertNotIn("provider_secret", serialized)
        live_selection = template.account_settings["group_selections"]["live"][0]
        self.assertNotIn("xc_id", live_selection["custom_properties"])
        self.assertNotIn("discovery_rule_id", live_selection["custom_properties"])
        self.assertEqual(
            live_selection["references"],
            {
                "group_override": "Sports output",
                "channel_profiles": ["Sports profile"],
                "epg_source": "Sports EPG",
                "stream_profile": "Sports stream profile",
                "logo": {
                    "name": "Sports logo",
                    "url": "https://example.com/sports.png",
                },
            },
        )

        target = M3UAccount.objects.create(
            name="target-account",
            server_url="https://other-provider.example",
            username="target-user",
            password="target-password",
        )
        target_live_relation = ChannelGroupM3UAccount.objects.create(
            channel_group=self.live_group,
            m3u_account=target,
            enabled=False,
            custom_properties={
                "xc_id": "target-provider-live-id",
                "channel_numbering_mode": "fixed",
            },
        )
        target_movie_relation = M3UVODCategoryRelation.objects.create(
            m3u_account=target,
            category=self.movie_category,
            enabled=False,
        )
        target_series_relation = M3UVODCategoryRelation.objects.create(
            m3u_account=target,
            category=self.series_category,
            enabled=True,
        )
        M3UFilter.objects.create(
            m3u_account=target,
            filter_type="name",
            regex_pattern="old",
        )

        apply_account_template(target, template)
        target.refresh_from_db()

        self.assertEqual(target.server_url, "https://other-provider.example")
        self.assertEqual(target.username, "target-user")
        self.assertEqual(target.password, "target-password")
        self.assertEqual(target.max_streams, 3)
        self.assertEqual(target.refresh_interval, 12)
        self.assertEqual(target.xc_live_refresh_min_age_minutes, 20)
        self.assertTrue(target.custom_properties["enable_vod"])
        self.assertNotIn("provider_secret", target.custom_properties)
        self.assertEqual(
            list(target.filters.values_list("regex_pattern", flat=True)),
            [r"adult|xxx"],
        )
        copied_rule = target.group_rules.get()
        self.assertEqual(copied_rule.regex_pattern, r"^GERMANY")
        self.assertEqual(
            copied_rule.metadata_defaults["video_features"], ["hdr"]
        )
        target_live_relation.refresh_from_db()
        self.assertTrue(target_live_relation.enabled)
        self.assertTrue(target_live_relation.auto_channel_sync)
        self.assertEqual(target_live_relation.auto_sync_channel_start, 100)
        self.assertEqual(target_live_relation.auto_sync_channel_end, 199)
        self.assertEqual(
            target_live_relation.custom_properties["xc_id"],
            "target-provider-live-id",
        )
        self.assertEqual(
            target_live_relation.custom_properties["group_override"],
            self.output_group.id,
        )
        self.assertEqual(
            target_live_relation.custom_properties["channel_profile_ids"],
            [self.channel_profile.id],
        )
        target_movie_relation.refresh_from_db()
        self.assertTrue(target_movie_relation.enabled)
        self.assertEqual(
            target_movie_relation.metadata_defaults,
            {"audio_languages": ["eng"]},
        )
        target_series_relation.refresh_from_db()
        self.assertFalse(target_series_relation.enabled)
        self.assertEqual(
            target_series_relation.metadata_defaults,
            {"resolution": "1080p"},
        )

    def test_template_selections_apply_when_groups_are_discovered_later(self):
        template = capture_account_template(self.source, name="Discovery defaults")
        target = M3UAccount.objects.create(
            name="new-provider",
            account_type=M3UAccount.Types.XC,
            server_url="https://new-provider.example",
        )

        apply_account_template(target, template)
        process_groups(target, {"Sports": {"xc_id": "new-live-id"}})
        batch_create_categories(
            [{"category_name": "Action", "category_id": "new-movie-id"}],
            "movie",
            target,
        )

        live_relation = ChannelGroupM3UAccount.objects.get(
            m3u_account=target,
            channel_group=self.live_group,
        )
        self.assertTrue(live_relation.enabled)
        self.assertTrue(live_relation.auto_channel_sync)
        self.assertEqual(live_relation.auto_sync_channel_start, 100)
        self.assertEqual(live_relation.custom_properties["xc_id"], "new-live-id")
        movie_relation = M3UVODCategoryRelation.objects.get(
            m3u_account=target,
            category=self.movie_category,
        )
        self.assertTrue(movie_relation.enabled)
        self.assertEqual(
            movie_relation.metadata_defaults,
            {"audio_languages": ["eng"]},
        )

    def test_catalog_counts_are_split_by_content_type(self):
        self.source.custom_properties.update(
            {
                "live_catalog_counts": {
                    "provider_total": 500,
                    "selected_total": 120,
                },
                "vod_catalog_counts": {
                    "movies": {
                        "provider_total": 200,
                        "selected_total": 40,
                    },
                    "series": {
                        "provider_total": 90,
                        "selected_total": 12,
                    },
                },
            }
        )
        self.source.save(update_fields=["custom_properties"])

        counts = M3UAccountSerializer(self.source).data["catalog_counts"]

        self.assertEqual(counts["live"], {"original": 500, "selected": 120})
        self.assertEqual(counts["movies"], {"original": 200, "selected": 40})
        self.assertEqual(counts["series"], {"original": 90, "selected": 12})
