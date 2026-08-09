from django.core.cache import cache
from django.test import TestCase

from apps.m3u.models import M3UAccount
from core.models import CoreSettings, STREAM_SETTINGS_KEY, UserAgent


class M3UAccountUserAgentStringTests(TestCase):
    def setUp(self):
        cache.clear()
        CoreSettings.objects.filter(key=STREAM_SETTINGS_KEY).delete()
        self.default_ua = UserAgent.objects.create(
            name="Default UA String Test",
            user_agent="DefaultAgent/1.0",
        )
        self.account_ua = UserAgent.objects.create(
            name="Account UA String Test",
            user_agent="AccountAgent/2.0",
        )
        CoreSettings.objects.create(
            key=STREAM_SETTINGS_KEY,
            name="Stream Settings",
            value={"default_user_agent": self.default_ua.id},
        )

    def tearDown(self):
        cache.clear()

    def test_account_user_agent_preferred_over_default(self):
        account = M3UAccount.objects.create(
            name="UA Account",
            server_url="http://example.com",
            user_agent=self.account_ua,
        )
        self.assertEqual(account.get_user_agent_string(), "AccountAgent/2.0")
        self.assertEqual(account.get_user_agent(), self.account_ua)

    def test_missing_account_user_agent_uses_cached_default(self):
        account = M3UAccount.objects.create(
            name="No UA Account",
            server_url="http://example.com",
            user_agent=None,
        )
        self.assertIsNone(account.get_user_agent())
        self.assertEqual(account.get_user_agent_string(), "DefaultAgent/1.0")
        with self.assertNumQueries(0):
            self.assertEqual(account.get_user_agent_string(), "DefaultAgent/1.0")
