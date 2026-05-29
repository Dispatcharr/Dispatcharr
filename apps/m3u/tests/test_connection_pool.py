"""Tests for shared ServerGroup connection pools (#1137)."""

from django.test import TestCase
from unittest.mock import patch

from apps.m3u.connection_pool import (
    extract_credentials_from_stream_url,
    get_credential_connection_count,
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

    def pipeline(self):
        return FakeRedisPipeline(self)


class FakeRedisPipeline:
    def __init__(self, redis):
        self.redis = redis
        self._ops = []

    def decr(self, key):
        self._ops.append(("decr", key))
        return self

    def incr(self, key):
        self._ops.append(("incr", key))
        return self

    def set(self, key, value):
        self._ops.append(("set", key, value))
        return self

    def execute(self):
        for op in self._ops:
            if op[0] == "decr":
                self.redis.decr(op[1])
            elif op[0] == "incr":
                self.redis.incr(op[1])
            elif op[0] == "set":
                self.redis.set(op[1], op[2])
        self._ops = []


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

    def test_accounts_in_same_group_share_credential_counter(self):
        group = ServerGroup.objects.create(name="shared", max_streams=2)
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
        profile1.max_streams = 1
        profile1.save()
        profile2.max_streams = 1
        profile2.save()

        redis = FakeRedis()
        reserved1, _ = reserve_profile_slot(profile1, redis)
        self.assertTrue(reserved1)

        reserved2, _ = reserve_profile_slot(profile2, redis)
        self.assertFalse(reserved2)
        self.assertFalse(group_has_capacity_for_profile(profile2, redis))

    def test_profile_rotation_when_default_profile_full(self):
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
            max_streams=2,
        )
        self.account = M3UAccount.objects.create(
            name="Test Account",
            account_type="XC",
            username="user",
            password="pass",
            server_url="http://xc.example.com",
            server_group=self.group,
            max_streams=5,
        )
        self.profile = M3UAccountProfile.objects.get(
            m3u_account=self.account, is_default=True
        )
        self.profile.max_streams = 1
        self.profile.save()

    def test_reserve_and_release_both_counters(self):
        reserved, count = reserve_profile_slot(self.profile, self.redis)
        self.assertTrue(reserved)
        self.assertEqual(count, 1)

        cred_key = server_group_connections_key(
            self.group.id,
            get_profile_credential_fingerprint(self.profile),
        )
        profile_key = profile_connections_key(self.profile.id)
        self.assertEqual(self.redis._data[cred_key], 1)
        self.assertEqual(self.redis._data[profile_key], 1)

        release_profile_slot(self.profile.id, self.redis)
        self.assertEqual(self.redis._data[cred_key], 0)
        self.assertEqual(self.redis._data[profile_key], 0)

    def test_same_credential_capped_at_profile_max_not_group_max(self):
        """Maintainer example: group max=2 but each login only allows 1."""
        account2 = M3UAccount.objects.create(
            name="Second Account",
            account_type="XC",
            username="user",
            password="pass",
            server_url="http://xc.example.com",
            server_group=self.group,
            max_streams=5,
        )
        profile2 = M3UAccountProfile.objects.get(m3u_account=account2, is_default=True)
        profile2.max_streams = 1
        profile2.save()

        self.assertTrue(reserve_profile_slot(self.profile, self.redis)[0])
        self.assertFalse(reserve_profile_slot(profile2, self.redis)[0])

        fp = get_profile_credential_fingerprint(self.profile)
        cred_key = server_group_connections_key(self.group.id, fp)
        self.assertEqual(self.redis._data[cred_key], 1)

    def test_different_logins_both_stream_when_group_max_is_one(self):
        """Regression: group max=1 must not block a second login on another profile."""
        self.group.max_streams = 1
        self.group.save()

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
            self.assertTrue(reserve_profile_slot(default, self.redis)[0])
            self.assertTrue(reserve_profile_slot(alt, self.redis)[0])

            key_a = server_group_connections_key(self.group.id, fp_a)
            key_b = server_group_connections_key(self.group.id, fp_b)
            self.assertEqual(self.redis._data[key_a], 1)
            self.assertEqual(self.redis._data[key_b], 1)

    def test_no_fingerprint_skips_credential_counter(self):
        account = M3UAccount.objects.create(
            name="No creds",
            account_type="STD",
            server_group=self.group,
            max_streams=5,
        )
        profile = M3UAccountProfile.objects.get(m3u_account=account, is_default=True)
        profile.max_streams = 1
        profile.save()

        with patch(
            "apps.m3u.connection_pool.get_profile_credential_fingerprint",
            return_value=None,
        ):
            self.assertTrue(reserve_profile_slot(profile, self.redis)[0])
            self.assertEqual(get_credential_connection_count(profile, self.redis), 0)
            self.assertEqual(get_group_connection_count(profile, self.redis), 0)

    def test_release_when_profile_row_deleted(self):
        profile_id = self.profile.id
        fp = get_profile_credential_fingerprint(self.profile)
        cred_key = server_group_connections_key(self.group.id, fp)

        self.assertTrue(reserve_profile_slot(self.profile, self.redis)[0])
        self.profile.delete()

        release_profile_slot(profile_id, self.redis)

        self.assertEqual(self.redis._data[profile_connections_key(profile_id)], 0)
        self.assertEqual(self.redis._data[cred_key], 1)


class UpdateStreamProfileTests(TestCase):
    def test_switch_updates_profile_counters_when_group_assigned(self):
        from apps.channels.models import Channel, Stream

        redis = FakeRedis()
        group = ServerGroup.objects.create(name="switch-group", max_streams=2)
        account = M3UAccount.objects.create(
            name="Switch Account",
            account_type="XC",
            username="user",
            password="pass",
            server_url="http://xc.example.com",
            server_group=group,
            max_streams=5,
        )
        profile_a = M3UAccountProfile.objects.get(m3u_account=account, is_default=True)
        profile_a.max_streams = 1
        profile_a.save()
        profile_b = M3UAccountProfile.objects.create(
            m3u_account=account,
            name="alt",
            is_default=False,
            is_active=True,
            max_streams=1,
            search_pattern="",
            replace_pattern="",
        )

        stream = Stream.objects.create(name="Test Stream", m3u_account=account)
        channel = Channel.objects.create(channel_number=501, name="Switch Channel")
        channel.streams.add(stream)

        reserve_profile_slot(profile_a, redis)
        redis.set(f"channel_stream:{channel.id}", stream.id)
        redis.set(f"stream_profile:{stream.id}", profile_a.id)

        cred_key = server_group_connections_key(
            group.id, get_profile_credential_fingerprint(profile_a)
        )
        cred_before = redis._data[cred_key]

        with patch("core.utils.RedisClient.get_client", return_value=redis):
            self.assertTrue(channel.update_stream_profile(profile_b.id))

        self.assertEqual(int(redis.get(f"stream_profile:{stream.id}")), profile_b.id)
        self.assertEqual(redis._data[profile_connections_key(profile_a.id)], 0)
        self.assertEqual(redis._data[profile_connections_key(profile_b.id)], 1)
        self.assertEqual(redis._data[cred_key], cred_before)


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
        self.assertTrue(reserve_profile_slot(default, redis)[0])

        with patch("core.utils.RedisClient.get_client", return_value=redis):
            result = _get_m3u_profile(account, None, None)

        self.assertIsNotNone(result)
        selected, _connections = result
        self.assertEqual(selected.id, alt.id)
