from unittest.mock import patch

from django.core.cache import cache
from django.test import RequestFactory, SimpleTestCase, TestCase

from apps.accounts.models import User
from apps.channels.models import Channel, ChannelStream, Stream
from apps.channels.utils import (
    is_catchup_enabled,
    resolve_epg_output_window,
)
from apps.m3u.models import M3UAccount
from core.models import SYSTEM_SETTINGS_KEY, CoreSettings, EpgHistoryPolicy


class IsCatchupEnabledTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User(username="catchup-gate", custom_properties={})
        # Drop any leftover catchup_enabled so default-on tests see a clean slate.
        obj = CoreSettings.objects.filter(key=SYSTEM_SETTINGS_KEY).first()
        if obj is not None:
            value = dict(obj.value or {})
            if "catchup_enabled" in value:
                value.pop("catchup_enabled", None)
                obj.value = value
                obj.save()

    def tearDown(self):
        # CoreSettings writes populate Redis; DB rollback does not clear it.
        cache.clear()

    def _set_system_catchup(self, enabled):
        obj, _ = CoreSettings.objects.get_or_create(
            key=SYSTEM_SETTINGS_KEY,
            defaults={"name": "System Settings", "value": {}},
        )
        value = dict(obj.value or {})
        value["catchup_enabled"] = enabled
        obj.value = value
        obj.save()

    def test_defaults_to_enabled(self):
        self.assertTrue(is_catchup_enabled())
        self.assertTrue(is_catchup_enabled(user=self.user))

    def test_system_disable_blocks_everyone(self):
        self._set_system_catchup(False)
        self.assertFalse(is_catchup_enabled())
        self.assertFalse(is_catchup_enabled(user=self.user))

    def test_user_disable_only_affects_that_user(self):
        self._set_system_catchup(True)
        self.user.custom_properties = {"catchup_enabled": False}
        other = User(username="other", custom_properties={})
        self.assertFalse(is_catchup_enabled(user=self.user))
        self.assertTrue(is_catchup_enabled(user=other))

    def test_user_disable_skips_system_settings_lookup(self):
        self.user.custom_properties = {"catchup_enabled": False}
        with patch.object(CoreSettings, "get_catchup_enabled") as system_mock:
            self.assertFalse(is_catchup_enabled(user=self.user))
            system_mock.assert_not_called()

    def test_system_disable_overrides_user_enable(self):
        self._set_system_catchup(False)
        self.user.custom_properties = {"catchup_enabled": True}
        self.assertFalse(is_catchup_enabled(user=self.user))


class ResolveEpgOutputWindowTests(SimpleTestCase):
    """URL value, then saved user value, then system default (never a stored 0)."""

    def setUp(self):
        self.factory = RequestFactory()
        self.user = User(username="xc-prev", custom_properties={})

    def _resolve(self, query="", *, custom=None, **policy):
        self.user.custom_properties = custom if custom is not None else {}
        request = self.factory.get(f"/xmltv.php{query}")
        fields = {"min_days": 1, "max_days": 30, "default_prev_days": 0, "default_days": 0}
        fields.update(policy)
        with patch(
            "core.models.CoreSettings.get_epg_history_policy",
            return_value=EpgHistoryPolicy(**fields),
        ):
            return resolve_epg_output_window(request, self.user)

    def test_url_prev_days_zero_is_explicit(self):
        window = self._resolve("?prev_days=0", default_prev_days=7)
        self.assertEqual(window.prev_days, 0)

    def test_user_epg_prev_days_used_when_url_omitted(self):
        window = self._resolve(custom={"epg_prev_days": 5})
        self.assertEqual(window.prev_days, 5)

    def test_missing_prev_days_uses_system_default(self):
        window = self._resolve(default_prev_days=7)
        self.assertEqual(window.prev_days, 7)

    def test_blank_saved_prev_days_uses_system_default(self):
        window = self._resolve(custom={"epg_prev_days": ""}, default_prev_days=7)
        self.assertEqual(window.prev_days, 7)

    def test_saved_zero_prev_days_does_not_inherit(self):
        window = self._resolve(custom={"epg_prev_days": 0}, default_prev_days=7)
        self.assertEqual(window.prev_days, 0)

    def test_catchup_disabled_still_uses_the_system_default(self):
        window = self._resolve(
            custom={"catchup_enabled": False}, default_prev_days=4
        )
        self.assertEqual(window.prev_days, 4)

    def test_url_prev_days_is_clamped_to_the_history_maximum(self):
        self.assertEqual(self._resolve("?prev_days=40", max_days=10).prev_days, 10)

    def test_unreadable_url_values_resolve_to_zero(self):
        window = self._resolve("?prev_days=abc&days=abc", default_prev_days=7, default_days=5)
        self.assertEqual((window.forward_days, window.prev_days), (0, 0))

    def test_missing_forward_days_uses_system_default(self):
        self.assertEqual(self._resolve(default_days=5).forward_days, 5)

    def test_saved_zero_forward_days_means_all_future(self):
        window = self._resolve(custom={"epg_days": 0}, default_days=5)
        self.assertEqual(window.forward_days, 0)

    def test_url_forward_days_is_clamped_to_the_future_limit(self):
        self.assertEqual(self._resolve("?days=9999").forward_days, 365)

    def test_anonymous_request_uses_the_system_defaults(self):
        request = self.factory.get("/xmltv.php")
        with patch(
            "core.models.CoreSettings.get_epg_history_policy",
            return_value=EpgHistoryPolicy(1, 30, 2, 4),
        ):
            window = resolve_epg_output_window(request, None)
        self.assertEqual((window.forward_days, window.prev_days), (4, 2))

    def test_json_string_custom_properties_are_read(self):
        window = self._resolve(custom='{"epg_prev_days": 4}')
        self.assertEqual(window.prev_days, 4)


class CatchupRollupActiveAccountTests(TestCase):
    """Denormalized catch-up flags ignore disabled M3U accounts."""

    @classmethod
    def setUpTestData(cls):
        cls.inactive = M3UAccount.objects.create(
            name="catchup-inactive",
            server_url="http://example.test",
            account_type="XC",
            is_active=False,
        )

    def test_channelstream_signal_ignores_inactive_catchup_stream(self):
        channel = Channel.objects.create(name="inactive-only")
        stream = Stream.objects.create(
            name="inactive-catchup",
            url="http://example.test/inactive",
            m3u_account=self.inactive,
            is_catchup=True,
            catchup_days=9,
        )
        ChannelStream.objects.create(channel=channel, stream=stream, order=0)

        channel.refresh_from_db()
        self.assertFalse(channel.is_catchup)
        self.assertEqual(channel.catchup_days, 0)

    def test_rollup_ignores_inactive_catchup_stream(self):
        from apps.m3u.tasks import rollup_channel_catchup_fields

        channel = Channel.objects.create(name="rollup-inactive-only")
        stream = Stream.objects.create(
            name="rollup-inactive-catchup",
            url="http://example.test/rollup-inactive",
            m3u_account=self.inactive,
            is_catchup=True,
            catchup_days=9,
        )
        ChannelStream.objects.create(channel=channel, stream=stream, order=0)
        Channel.objects.filter(pk=channel.pk).update(is_catchup=True, catchup_days=9)

        rollup_channel_catchup_fields(self.inactive.id)

        channel.refresh_from_db()
        self.assertFalse(channel.is_catchup)
        self.assertEqual(channel.catchup_days, 0)


class BulkCreateChannelsFromStreamsCatchupTests(TestCase):
    """bulk_create skips ChannelStream post_save; task rolls up catch-up once."""

    @classmethod
    def setUpTestData(cls):
        cls.active = M3UAccount.objects.create(
            name="bulk-catchup-active",
            server_url="http://example.test",
            account_type="XC",
            is_active=True,
        )
        cls.inactive = M3UAccount.objects.create(
            name="bulk-catchup-inactive",
            server_url="http://example.test",
            account_type="XC",
            is_active=False,
        )

    @patch("core.utils.send_websocket_update")
    def test_rolls_up_catchup_from_active_stream(self, _ws):
        from apps.channels.tasks import bulk_create_channels_from_streams

        stream = Stream.objects.create(
            name="bulk-catchup",
            url="http://example.test/catchup",
            m3u_account=self.active,
            is_catchup=True,
            catchup_days=2,
            is_radio=True,
        )

        result = bulk_create_channels_from_streams.run([stream.id])

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["created_count"], 1)
        channel = Channel.objects.get(streams=stream)
        self.assertTrue(channel.is_catchup)
        self.assertEqual(channel.catchup_days, 2)
        # is_radio is still seeded at create time on this path.
        self.assertTrue(channel.is_radio)

    @patch("core.utils.send_websocket_update")
    def test_ignores_catchup_from_inactive_account(self, _ws):
        from apps.channels.tasks import bulk_create_channels_from_streams

        stream = Stream.objects.create(
            name="bulk-inactive-catchup",
            url="http://example.test/inactive-catchup",
            m3u_account=self.inactive,
            is_catchup=True,
            catchup_days=5,
        )

        result = bulk_create_channels_from_streams.run([stream.id])

        self.assertEqual(result["status"], "completed")
        channel = Channel.objects.get(streams=stream)
        self.assertFalse(channel.is_catchup)
        self.assertEqual(channel.catchup_days, 0)
