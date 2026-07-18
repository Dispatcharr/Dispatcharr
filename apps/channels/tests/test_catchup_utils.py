from unittest.mock import patch

from django.core.cache import cache
from django.test import RequestFactory, TestCase

from apps.accounts.models import User
from apps.channels.models import Channel, ChannelStream, Stream
from apps.channels.utils import is_catchup_enabled, resolve_xc_epg_prev_days
from apps.m3u.models import M3UAccount
from core.models import SYSTEM_SETTINGS_KEY, CoreSettings


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


class ResolveXcEpgPrevDaysTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = User(username="xc-prev", custom_properties={})

    def test_url_prev_days_zero_is_explicit(self):
        request = self.factory.get("/xmltv.php?prev_days=0")
        self.assertEqual(resolve_xc_epg_prev_days(request, self.user), 0)

    def test_user_epg_prev_days_used_when_url_omitted(self):
        self.user.custom_properties = {"epg_prev_days": 5}
        request = self.factory.get("/xmltv.php")
        self.assertEqual(resolve_xc_epg_prev_days(request, self.user), 5)

    @patch("apps.channels.utils.compute_provider_archive_days_capped", return_value=14)
    def test_auto_detect_only_when_no_url_or_user_default(self, mock_compute):
        request = self.factory.get("/xmltv.php")
        self.assertEqual(resolve_xc_epg_prev_days(request, self.user), 14)
        mock_compute.assert_called_once()

    @patch("apps.channels.utils.compute_provider_archive_days_capped", return_value=14)
    def test_per_channel_epg_skips_global_auto_detect(self, mock_compute):
        request = self.factory.get("/player_api.php")
        self.assertEqual(
            resolve_xc_epg_prev_days(request, self.user, auto_detect_fallback=False),
            0,
        )
        mock_compute.assert_not_called()

    @patch("apps.channels.utils.compute_provider_archive_days_capped", return_value=14)
    def test_user_default_prevents_auto_detect(self, mock_compute):
        self.user.custom_properties = {"epg_prev_days": 3}
        request = self.factory.get("/xmltv.php")
        self.assertEqual(resolve_xc_epg_prev_days(request, self.user), 3)
        mock_compute.assert_not_called()

    @patch("apps.channels.utils.compute_provider_archive_days_capped", return_value=14)
    def test_auto_detect_still_runs_when_catchup_disabled(self, mock_compute):
        """Catchup disable must not suppress historical EPG lookback."""
        self.user.custom_properties = {"catchup_enabled": False}
        request = self.factory.get("/xmltv.php")
        self.assertEqual(resolve_xc_epg_prev_days(request, self.user), 14)
        mock_compute.assert_called_once()


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
