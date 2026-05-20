"""Tests for shared credential connection pools (#1137)."""

from django.test import TestCase
from unittest.mock import patch

from apps.m3u.connection_pool import (
    compute_credential_fingerprint,
    extract_credentials_from_stream_url,
    get_enforced_server_group_for_profile,
    get_profile_credential_fingerprint,
    pool_has_capacity_for_profile,
    release_profile_slot,
    reserve_profile_slot,
    server_group_connections_key,
    sync_account_credential_pool,
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


class CredentialFingerprintTests(TestCase):
    def test_same_credentials_same_fingerprint(self):
        fp1 = compute_credential_fingerprint("User", "pass")
        fp2 = compute_credential_fingerprint("user", "pass")
        self.assertEqual(fp1, fp2)
        self.assertIsNotNone(fp1)

    def test_different_password_different_fingerprint(self):
        fp1 = compute_credential_fingerprint("user", "pass1")
        fp2 = compute_credential_fingerprint("user", "pass2")
        self.assertNotEqual(fp1, fp2)

    def test_empty_credentials_returns_none(self):
        self.assertIsNone(compute_credential_fingerprint("", "pass"))
        self.assertIsNone(compute_credential_fingerprint("user", ""))

    def test_extract_credentials_from_xc_style_url(self):
        url = "http://example.com/live/alice/secret123/99999.ts"
        user, password = extract_credentials_from_stream_url(url)
        self.assertEqual(user, "alice")
        self.assertEqual(password, "secret123")


class AutoAssignTests(TestCase):
    def test_accounts_with_same_credentials_share_server_group(self):
        account1 = M3UAccount.objects.create(
            name="Provider A",
            account_type="XC",
            username="user1",
            password="secret",
            server_url="http://a.example.com",
            max_streams=2,
        )
        account2 = M3UAccount.objects.create(
            name="Provider B",
            account_type="XC",
            username="user1",
            password="secret",
            server_url="http://b.example.com",
            max_streams=3,
        )

        account1.refresh_from_db()
        account2.refresh_from_db()

        self.assertIsNotNone(account1.server_group_id)
        self.assertEqual(account1.server_group_id, account2.server_group_id)
        self.assertTrue(account1.server_group.credential_fingerprint)
        self.assertEqual(account1.server_group.max_streams, 2)

    def test_exclude_from_pool_opt_out(self):
        account1 = M3UAccount.objects.create(
            name="Pooled",
            account_type="XC",
            username="shared",
            password="secret",
            max_streams=1,
        )
        account2 = M3UAccount.objects.create(
            name="Opt-out",
            account_type="XC",
            username="shared",
            password="secret",
            custom_properties={"exclude_from_credential_pool": True},
            max_streams=1,
        )

        account1.refresh_from_db()
        account2.refresh_from_db()

        self.assertIsNotNone(account1.server_group_id)
        self.assertIsNone(account2.server_group_id)


class MultiProfilePoolTests(TestCase):
    def test_profiles_with_different_credentials_get_separate_pools(self):
        account = M3UAccount.objects.create(
            name="Multi-login XC",
            account_type="XC",
            username="xc_user_a",
            password="xc_pass_a",
            server_url="http://xc.example.com",
            max_streams=1,
        )
        base = M3UAccountProfile.objects.get(m3u_account=account, is_default=True)
        base.search_pattern = r"^http://xc\.example\.com/live/xc_user_a/xc_pass_a/(.*)$"
        base.replace_pattern = r"http://xc.example.com/live/xc_user_a/xc_pass_a/\1"
        base.save()

        p2 = M3UAccountProfile.objects.create(
            m3u_account=account,
            name="login_b",
            is_default=False,
            is_active=True,
            max_streams=1,
            search_pattern=r"^http://xc\.example\.com/live/xc_user_a/xc_pass_a/(.*)$",
            replace_pattern=r"http://xc.example.com/live/xc_user_b/xc_pass_b/\1",
        )

        sync_account_credential_pool(account)

        fp1 = get_profile_credential_fingerprint(base)
        fp2 = get_profile_credential_fingerprint(p2)
        self.assertNotEqual(fp1, fp2)

        g1 = get_enforced_server_group_for_profile(base)
        g2 = get_enforced_server_group_for_profile(p2)
        self.assertIsNotNone(g1)
        self.assertIsNotNone(g2)
        self.assertNotEqual(g1.id, g2.id)
        self.assertIsNone(account.server_group_id)


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

    def test_reserve_and_release_pool_counter(self):
        reserved, count = reserve_profile_slot(self.profile, self.redis)
        self.assertTrue(reserved)
        self.assertEqual(count, 1)

        group_key = server_group_connections_key(self.group.id)
        self.assertEqual(self.redis._data[group_key], 1)

        release_profile_slot(self.profile.id, self.redis)
        self.assertEqual(self.redis._data[group_key], 0)

    def test_reserve_fails_when_pool_at_capacity(self):
        group_key = server_group_connections_key(self.group.id)
        self.redis.set(group_key, 1)

        reserved, _count = reserve_profile_slot(self.profile, self.redis)
        self.assertFalse(reserved)
        self.assertFalse(pool_has_capacity_for_profile(self.profile, self.redis))

    def test_live_slot_blocks_second_reserve_same_profile(self):
        reserved1, _ = reserve_profile_slot(self.profile, self.redis)
        self.assertTrue(reserved1)

        reserved2, _ = reserve_profile_slot(self.profile, self.redis)
        self.assertFalse(reserved2)


class VodProfileSelectionTests(TestCase):
    """VOD must try alternate profiles when the default pool is full (live TV)."""

    def test_get_m3u_profile_skips_default_when_pool_full(self):
        from apps.proxy.vod_proxy.views import _get_m3u_profile

        account = M3UAccount.objects.create(
            name="VOD multi-login",
            account_type="XC",
            username="xc_user_a",
            password="xc_pass_a",
            server_url="http://xc.example.com",
            max_streams=1,
        )
        default = M3UAccountProfile.objects.get(m3u_account=account, is_default=True)
        default.search_pattern = (
            r"^http://xc\.example\.com/live/xc_user_a/xc_pass_a/(.*)$"
        )
        default.replace_pattern = (
            r"http://xc.example.com/live/xc_user_a/xc_pass_a/\1"
        )
        default.save()

        alt = M3UAccountProfile.objects.create(
            m3u_account=account,
            name="login_b",
            is_default=False,
            is_active=True,
            max_streams=1,
            search_pattern=r"^http://xc\.example\.com/live/xc_user_a/xc_pass_a/(.*)$",
            replace_pattern=r"http://xc.example.com/live/xc_user_b/xc_pass_b/\1",
        )

        sync_account_credential_pool(account)

        redis = FakeRedis()
        reserved, _ = reserve_profile_slot(default, redis)
        self.assertTrue(reserved)

        with patch("core.utils.RedisClient.get_client", return_value=redis):
            result = _get_m3u_profile(account, None, None)

        self.assertIsNotNone(result)
        selected, _connections = result
        self.assertEqual(selected.id, alt.id)
