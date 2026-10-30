"""Finish & import keeps VOD after Live even when Live imports no streams."""

from tempfile import TemporaryDirectory
from unittest.mock import patch

from celery.exceptions import Retry
from django.test import TransactionTestCase, override_settings

from apps.channels.models import ChannelGroup, ChannelGroupM3UAccount, Stream
from apps.m3u.account_setup import advance_account_setup
from apps.m3u.models import M3UAccount, M3UFilter


class InitialImportSequenceTests(TransactionTestCase):
    def mock(self, target, **kwargs):
        patcher = patch(target, **kwargs)
        result = patcher.start()
        self.addCleanup(patcher.stop)
        return result

    def setUp(self):
        media = TemporaryDirectory()
        self.addCleanup(media.cleanup)
        self.enterContext(override_settings(MEDIA_ROOT=media.name))
        self.mock("apps.m3u.tasks.m3u_dir", new=media.name)
        self.mock("apps.m3u.signals.refresh_m3u_groups.delay")
        self.account = M3UAccount.objects.create(
            name="Initial combined import",
            account_type=M3UAccount.Types.XC,
            server_url="https://provider.example.invalid",
            setup_step=M3UAccount.SetupStep.CATEGORIES,
            status=M3UAccount.Status.PENDING_SETUP,
            custom_properties={
                "enable_vod": True,
                "setup_categories_reviewed": True,
            },
            vod_refresh_after_live=False,
        )
        group = ChannelGroup.objects.create(name="Example category")
        ChannelGroupM3UAccount.objects.create(
            m3u_account=self.account,
            channel_group=group,
            enabled=True,
            custom_properties={"xc_id": "1"},
        )
        self.mock(
            "apps.m3u.tasks.refresh_m3u_groups",
            return_value=([], {group.name: group.id}),
        )
        self.catalog = self.mock(
            "apps.m3u.tasks.collect_xc_streams",
            return_value=([], 0),
        )
        self.batches = self.mock(
            "apps.m3u.tasks._process_stream_batches_with_retry",
            return_value=(0, 0, 0, 0),
        )
        for target in (
            "apps.m3u.tasks._release_task_db_connection",
            "apps.m3u.tasks.TaskLockRenewer",
            "apps.vod.tasks.TaskLockRenewer",
            "apps.m3u.tasks.cleanup_stale_group_relationships",
            "apps.m3u.tasks.rollup_channel_catchup_fields",
            "apps.m3u.tasks.send_m3u_update",
            "apps.m3u.tasks.log_system_event",
            "apps.output.streaming_chunk_cache."
            "invalidate_output_caches_after_m3u_refresh",
        ):
            self.mock(target)
        self.mock("apps.m3u.tasks.cleanup_streams", return_value=0)
        self.mock("apps.m3u.tasks.sync_auto_channels", return_value={})
        self.events = []
        self.locked = False
        for scope in ("m3u", "vod"):
            self.mock(
                f"apps.{scope}.tasks.acquire_task_lock",
                side_effect=lambda *args, scope=scope: self.acquire(scope),
            )
            self.mock(
                f"apps.{scope}.tasks.release_task_lock",
                side_effect=lambda *args, scope=scope: self.release(scope),
            )
        self.mock(
            "apps.vod.tasks.refresh_vod_content.retry",
            side_effect=Retry("Account is still busy"),
        )
        self.vod = self.mock(
            "apps.vod.tasks._refresh_vod_content_impl",
            side_effect=lambda account_id: self.events.append("vod-import"),
        )

    def acquire(self, scope):
        if self.locked:
            self.events.append(f"{scope}-busy")
            return False
        self.locked = True
        self.events.append(f"{scope}-acquire")
        return True

    def release(self, scope):
        self.assertTrue(self.locked)
        self.events.append(f"{scope}-release")
        self.locked = False

    def assert_vod_after_live(self):
        self.vod.assert_called_once_with(self.account.id)
        self.assertEqual(
            self.events,
            ["m3u-acquire", "m3u-release", "vod-acquire", "vod-import", "vod-release"],
        )
        self.account.refresh_from_db()
        self.assertEqual(self.account.setup_step, "")
        self.assertFalse(Stream.objects.filter(m3u_account=self.account).exists())

    @override_settings(
        CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True,
    )
    def test_empty_live_catalog_still_starts_vod_after_releasing_live_lock(self):
        advance_account_setup(self.account.id, "complete")
        self.assert_vod_after_live()
        self.assertEqual(self.account.status, M3UAccount.Status.ERROR)
        self.batches.assert_not_called()

    @override_settings(
        CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True,
    )
    def test_successful_live_with_zero_imported_streams_still_starts_vod_once(self):
        M3UFilter.objects.create(
            m3u_account=self.account, filter_type="name",
            regex_pattern=".*", exclude=True,
        )
        self.catalog.return_value = ([{
            "name": "Example stream",
            "url": "https://provider.example.invalid/live.m3u8",
            "attributes": {"group-title": "Example category", "stream_id": "1"},
        }], 1)
        advance_account_setup(self.account.id, "complete")
        self.assert_vod_after_live()
        self.assertEqual(self.account.status, M3UAccount.Status.SUCCESS)
        self.assertEqual(
            self.account.custom_properties["live_catalog_counts"]["selected_total"], 0,
        )
        self.batches.assert_called_once()

    @override_settings(
        CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True,
    )
    def test_disabled_vod_does_not_start_after_empty_live(self):
        self.account.custom_properties["enable_vod"] = False
        self.account.save(update_fields=["custom_properties"])
        advance_account_setup(self.account.id, "complete")
        self.vod.assert_not_called()
        self.assertEqual(self.events, ["m3u-acquire", "m3u-release"])
