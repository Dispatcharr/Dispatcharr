"""Exercise XC group discovery against the actual client method interface."""

import tempfile
from unittest.mock import patch

from django.test import TestCase, override_settings

from apps.channels.models import ChannelGroupM3UAccount
from apps.m3u.models import M3UAccount, M3UGroupRule
from apps.m3u.tasks import refresh_m3u_groups


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class XCGroupDiscoveryTests(TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        settings = self.settings(M3U_FILTER_CATALOG_ROOT=directory.name)
        settings.enable()
        self.addCleanup(settings.disable)

        self.account = M3UAccount.objects.create(
            name="XC discovery",
            account_type=M3UAccount.Types.XC,
            server_url="https://provider.example.invalid",
            username="example-user",
            password="example-password",
        )
        for target, options in (
            ("acquire_task_lock", {"return_value": True}),
            ("release_task_lock", {}),
            ("TaskLockRenewer", {}),
            ("send_m3u_update", {}),
            ("refresh_account_profiles.delay", {}),
            ("_release_task_db_connection", {}),
        ):
            patcher = patch(f"apps.m3u.tasks.{target}", **options)
            patcher.start()
            self.addCleanup(patcher.stop)

        user_agent = patch.object(
            M3UAccount, "get_user_agent_string", return_value="Example-Agent/1.0"
        )
        user_agent.start()
        self.addCleanup(user_agent.stop)

        client_factory = patch("apps.m3u.tasks.XCClient", autospec=True)
        self.client = client_factory.start().return_value
        self.addCleanup(client_factory.stop)
        self.client.__enter__.return_value = self.client
        self.client.get_live_categories.return_value = [
            {"category_id": "10", "category_name": "News"},
            {"category_id": "20", "category_name": "Sport"},
        ]
        self.client.get_all_live_streams.return_value = [
            {"category_id": 10, "name": "World News"},
            {"category_id": "10", "name": "Local Bulletin"},
            {"category_id": "20", "name": "World Sport"},
            {"category_id": "unknown", "name": "Unmapped stream"},
        ]

    def rule(self, **values):
        return M3UGroupRule.objects.create(
            m3u_account=self.account,
            **{
                "scope": "live",
                "regex_pattern": "^News$",
                "action": "enable",
                **values,
            },
        )

    def refresh(self):
        streams, groups = refresh_m3u_groups(self.account.id)
        self.assertEqual(streams, [])
        self.assertIsNotNone(groups)
        self.account.refresh_from_db()
        self.assertEqual(self.account.status, M3UAccount.Status.PENDING_SETUP)
        return groups

    def selections(self):
        return dict(
            ChannelGroupM3UAccount.objects.filter(m3u_account=self.account)
            .values_list("channel_group__name", "enabled")
        )

    def test_category_name_rule_does_not_fetch_full_stream_catalog(self):
        self.rule(match_field="group_name", regex_pattern="^News$")

        self.refresh()

        self.client.get_all_live_streams.assert_not_called()
        self.assertEqual(
            self.selections(),
            {"Default Group": False, "News": True, "Sport": False},
        )

    def test_disabled_and_vod_rules_do_not_fetch_live_stream_catalog(self):
        self.rule(enabled=False)
        self.rule(scope="movie")

        self.refresh()

        self.client.get_all_live_streams.assert_not_called()
        self.assertEqual(
            self.selections(),
            {"Default Group": False, "News": False, "Sport": False},
        )
