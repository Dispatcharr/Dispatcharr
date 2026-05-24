"""Tests for shared ServerGroup connection pools (#1137)."""

from django.test import TestCase
from unittest.mock import patch

from apps.m3u.connection_pool import (
    extract_credentials_from_stream_url,
    get_enforced_server_group_for_profile,
    get_group_connection_count,
    get_profile_connection_count,
    get_profile_credential_fingerprint,
    group_has_capacity_for_profile,
    pool_has_capacity_for_profile,
    profile_has_capacity_for_selection,
    profile_connections_key,
    release_profile_slot,
    reserve_profile_slot,
    server_group_connections_key,
)
from apps.m3u.models import M3UAccount, M3UAccountProfile, ServerGroup


class FakeRedis:
    """Minimal in-memory Redis stand-in for counter tests."""

    def __init__(self):
        self._data = {}

    def get(self, key):
        val = self._data.get(key)
        if val is None:
            return None
        return str(val).encode()

    def set(self, key, value, ex=None):
        self._data[key] = int(value)

    def incr(self, key):
        self._data[key] = self._data.get(key, 0) + 1
        return self._data[key]

    def decr(self, key):
        self._data[key] = self._data.get(key, 0) - 1
        return self._data[key]


class ExtractCredentialsTests(TestCase):
    def test_extract_credentials_from_xc_style_url(self):
        url = "http://example.com/live/alice/secret123/99999.ts"
        user, password = extract_credentials_from_stream_url(url)
        self.assertEqual(user, "alice")
        self.assertEqual(password, "secret123")


class ManualServerGroupTests(TestCase):
    def test_group_enforced_when_max_streams_set(self):
        group = ServerGroup.objects.create(name="provider-a", max_streams=2)
        account = M3UAccount.objects.create(
            name="Account A",
            account_type="XC",
            username="user",
            password="pass",
            server_group=group,
        )
        profile = M3UAccountProfile.objects.get(m3u_account=account, is_default=True)

        self.assertEqual(get_enforced_server_group_for_profile(profile), group)

    def test_accounts_in_same_group_share_counter(self):
        group = ServerGroup.objects.create(name="shared", max_streams=1)
        account1 = M3UAccount.objects.create(
            name="XC Account",
            account_type="XC",
            username="user",
            password="pass",
            server_url="http://xc.example.com",
            server_group=group,
            max_streams=5,
        )
        account2 = M3UAccount.objects.create(
            name="M3U Account",
            account_type="STD",
            username="user",
            password="pass",
            server_group=group,
            max_streams=5,
        )
        profile1 = M3UAccountProfile.objects.get(m3u_account=account1, is_default=True)
        profile2 = M3UAccountProfile.objects.get(m3u_account=account2, is_default=True)

        redis = FakeRedis()
        reserved1, _ = reserve_profile_slot(profile1, redis)
        self.assertTrue(reserved1)

        reserved2, _ = reserve_profile_slot(profile2, redis)
        self.assertFalse(reserved2)
        self.assertFalse(group_has_capacity_for_profile(profile2, redis))

    def test_profile_rotation_when_default_profile_full(self):
        """Pre-pool behavior: try the next profile on the same account."""
        account = M3UAccount.objects.create(
            name="Multi-profile",
            account_type="XC",
            max_streams=1,
        )
        default = M3UAccountProfile.objects.get(m3u_account=account, is_default=True)
        default.max_streams = 1
        default.save()

        alt = M3UAccountProfile.objects.create(
            m3u_account=account,
            name="alt_profile",
            is_default=False,
            is_active=True,
            max_streams=1,
            search_pattern="",
            replace_pattern="",
        )

        redis = FakeRedis()
        reserved, _ = reserve_profile_slot(default, redis)
        self.assertTrue(reserved)
        self.assertFalse(profile_has_capacity_for_selection(default, redis))
        self.assertTrue(profile_has_capacity_for_selection(alt, redis))


class PoolEnforcementTests(TestCase):
    def setUp(self):
        self.redis = FakeRedis()
        self.group = ServerGroup.objects.create(
            name="test-pool",
            max_streams=1,
        )
        self.account = M3UAccount.objects.create(
            name="Test Account",
            account_type="XC",
            username="user",
            password="pass",
            server_group=self.group,
            max_streams=5,
        )
        self.profile = M3UAccountProfile.objects.get(
            m3u_account=self.account, is_default=True
        )
        self.profile.max_streams = 5
        self.profile.save()

    def test_reserve_and_release_both_counters(self):
        reserved, count = reserve_profile_slot(self.profile, self.redis)
        self.assertTrue(reserved)
        self.assertEqual(count, 1)

        group_key = server_group_connections_key(
            self.group.id,
            get_profile_credential_fingerprint(self.profile),
        )
        profile_key = profile_connections_key(self.profile.id)
        self.assertEqual(self.redis._data[group_key], 1)
        self.assertEqual(self.redis._data[profile_key], 1)

        release_profile_slot(self.profile.id, self.redis)
        self.assertEqual(self.redis._data[group_key], 0)
        self.assertEqual(self.redis._data[profile_key], 0)

    def test_reserve_fails_when_group_at_capacity(self):
        group_key = server_group_connections_key(
            self.group.id,
            get_profile_credential_fingerprint(self.profile),
        )
        self.redis.set(group_key, 1)

        reserved, _count = reserve_profile_slot(self.profile, self.redis)
        self.assertFalse(reserved)
        self.assertFalse(pool_has_capacity_for_profile(self.profile, self.redis))

    def test_different_logins_in_group_do_not_block_each_other(self):
        """Profiles with different provider logins keep separate group counters."""
        account = M3UAccount.objects.create(
            name="Grouped multi-login",
            account_type="XC",
            username="login_a",
            password="pass_a",
            server_group=self.group,
            max_streams=5,
        )
        default = M3UAccountProfile.objects.get(m3u_account=account, is_default=True)
        default.max_streams = 1
        default.save()

        alt = M3UAccountProfile.objects.create(
            m3u_account=account,
            name="alt_login",
            is_default=False,
            is_active=True,
            max_streams=1,
            search_pattern="",
            replace_pattern="",
        )

        fp_a = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        fp_b = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"

        with patch(
            "apps.m3u.connection_pool.get_profile_credential_fingerprint",
            side_effect=lambda profile: fp_a if profile.id == default.id else fp_b,
        ):
            reserved_default, _ = reserve_profile_slot(default, self.redis)
            self.assertTrue(reserved_default)

            reserved_alt, _ = reserve_profile_slot(alt, self.redis)
            self.assertTrue(reserved_alt)

            key_a = server_group_connections_key(self.group.id, fp_a)
            key_b = server_group_connections_key(self.group.id, fp_b)
            self.assertEqual(self.redis._data[key_a], 1)
            self.assertEqual(self.redis._data[key_b], 1)


class VodProfileSelectionTests(TestCase):
    def test_get_m3u_profile_skips_default_when_profile_full(self):
        from apps.proxy.vod_proxy.views import _get_m3u_profile

        account = M3UAccount.objects.create(
            name="VOD multi-profile",
            account_type="XC",
            username="xc_user_a",
            password="xc_pass_a",
            server_url="http://xc.example.com",
            max_streams=1,
        )
        default = M3UAccountProfile.objects.get(m3u_account=account, is_default=True)
        default.max_streams = 1
        default.save()

        alt = M3UAccountProfile.objects.create(
            m3u_account=account,
            name="alt_profile",
            is_default=False,
            is_active=True,
            max_streams=1,
            search_pattern="",
            replace_pattern="",
        )

        redis = FakeRedis()
        reserved, _ = reserve_profile_slot(default, redis)
        self.assertTrue(reserved)

        with patch("core.utils.RedisClient.get_client", return_value=redis):
            result = _get_m3u_profile(account, None, None)

        self.assertIsNotNone(result)
        selected, _connections = result
        self.assertEqual(selected.id, alt.id)
