"""Tests for shared ServerGroup connection pools (#1137)."""

import fnmatch
import json

from django.test import TestCase
from unittest.mock import patch

from apps.m3u.connection_pool import (
    extract_credentials_from_stream_url,
    get_credential_connection_count,
    get_enforced_server_group_for_profile,
    get_profile_connection_count,
    get_profile_credential_fingerprint,
    group_has_capacity_for_profile,
    pool_has_capacity_for_profile,
    profile_has_capacity_for_selection,
    profile_connections_key,
    profile_connections_version_key,
    profile_credential_release_key,
    reconcile_profile_connection_count,
    release_profile_slot,
    reserve_profile_slot,
    server_group_connections_key,
    vod_profile_reservation_key,
)
from apps.m3u.models import M3UAccount, M3UAccountProfile, ServerGroup


class FakeRedis:
    """Minimal in-memory Redis stand-in for counter tests."""

    def __init__(self):
        self._data = {}
        self._hashes = {}

    def get(self, key):
        val = self._data.get(key)
        if val is None:
            return None
        if isinstance(val, str):
            return val.encode()
        return str(val).encode()

    def set(self, key, value, ex=None, nx=False):
        if nx and key in self._data:
            return False
        try:
            self._data[key] = int(value)
        except (ValueError, TypeError):
            self._data[key] = value
        return True

    def incr(self, key):
        self._data[key] = self._data.get(key, 0) + 1
        return self._data[key]

    def decr(self, key):
        self._data[key] = self._data.get(key, 0) - 1
        return self._data[key]

    def delete(self, *keys):
        for key in keys:
            self._data.pop(key, None)
            self._hashes.pop(key, None)

    def exists(self, key):
        return key in self._data or key in self._hashes

    def expire(self, key, seconds):
        return key in self._data or key in self._hashes

    def ttl(self, key):
        return 3600 if key in self._data or key in self._hashes else -2

    def mget(self, keys):
        return [self.get(key) for key in keys]

    def hmget(self, key, *fields):
        row = self._hashes.get(key, {})
        return [row.get(field) for field in fields]

    def hset(self, key, mapping):
        self._hashes.setdefault(key, {}).update(
            {str(field): str(value) for field, value in mapping.items()}
        )

    def scan_iter(self, match=None, count=None):
        for key in list(self._data) + list(self._hashes):
            if match is None or fnmatch.fnmatch(key, match):
                yield key

    def pipeline(self, transaction=True):
        return FakeRedisPipeline(self)

    def register_script(self, script):
        scripts = fake_owned_profile_scripts(self)
        if "-- release_orphaned_credential" in script:
            return scripts["release_orphaned_credential"]
        if "-- release_credential" in script:
            return scripts["release_credential"]
        if "-- reserve_owned_profile" in script:
            return scripts["reserve_owned"]
        if "-- release_owned_profile" in script:
            return scripts["release_owned"]
        if "-- reconcile_profile_counter" in script:
            return scripts["reconcile"]
        raise AssertionError("Unexpected Lua script")


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

    def hmget(self, key, *fields):
        self._ops.append(("hmget", key, fields))
        return self

    def execute(self):
        results = []
        for op in self._ops:
            if op[0] == "decr":
                results.append(self.redis.decr(op[1]))
            elif op[0] == "incr":
                results.append(self.redis.incr(op[1]))
            elif op[0] == "set":
                results.append(self.redis.set(op[1], op[2]))
            elif op[0] == "hmget":
                results.append(self.redis.hmget(op[1], *op[2]))
        self._ops = []
        return results


def fake_owned_profile_scripts(redis):
    """Python equivalents of the small profile accounting Lua scripts."""

    def reserve_owned(*, keys, args):
        counter_key, marker_key, version_key, credential_release_key = keys
        profile_id, max_streams, _ttl = map(int, args[:3])
        credential_key = str(args[3])
        credential_payload = str(args[4])
        marker = redis.get(marker_key)
        current = int(redis.get(counter_key) or 0)
        if marker is not None and int(marker) == profile_id:
            if credential_key and not redis.exists(credential_release_key):
                credential_count = redis.incr(credential_key)
                if credential_count > max_streams:
                    redis.decr(credential_key)
                    redis.delete(marker_key)
                    if current > 0:
                        current = redis.decr(counter_key)
                        redis.incr(version_key)
                    return [-2, current]
                redis.set(credential_release_key, credential_payload)
            return [2, current]
        if marker is not None:
            return [-1, current]
        new_count = redis.incr(counter_key)
        redis.incr(version_key)
        if new_count > max_streams:
            redis.decr(counter_key)
            redis.incr(version_key)
            return [0, new_count - 1]
        if credential_key:
            credential_count = redis.incr(credential_key)
            if credential_count > max_streams:
                redis.decr(credential_key)
                redis.decr(counter_key)
                redis.incr(version_key)
                return [-2, new_count - 1]
            redis.set(credential_release_key, credential_payload)
        redis.set(marker_key, profile_id)
        return [1, new_count]

    def release_owned(*, keys, args):
        counter_key, marker_key, version_key, credential_release_key = keys
        profile_id = int(args[0])
        marker = redis.get(marker_key)
        current = int(redis.get(counter_key) or 0)
        if marker is None or int(marker) != profile_id:
            return [0, current]
        redis.delete(marker_key)
        credential_payload = redis.get(credential_release_key)
        if credential_payload:
            decoded = json.loads(credential_payload.decode())
            credential_key = decoded.get("credential_key")
            if credential_key and int(redis.get(credential_key) or 0) > 0:
                redis.decr(credential_key)
            redis.delete(credential_release_key)
        if current > 0:
            current = redis.decr(counter_key)
            redis.incr(version_key)
        return [1, current]

    def reconcile(*, keys, args):
        counter_key, version_key = keys
        observed_count, observed_version, expected_count = map(int, args)
        current = int(redis.get(counter_key) or 0)
        version = int(redis.get(version_key) or 0)
        if (
            current == observed_count
            and version == observed_version
            and expected_count < current
        ):
            redis.set(counter_key, expected_count)
            redis.incr(version_key)
            return [1, expected_count]
        return [0, current]

    def release_credential(*, keys, args):
        release_key = keys[0]
        expected_payload, credential_key = args[:2]
        stored = redis.get(release_key)
        stored = stored.decode() if isinstance(stored, bytes) else stored
        if stored != expected_payload:
            return 0
        redis.delete(release_key)
        if int(redis.get(credential_key) or 0) > 0:
            redis.decr(credential_key)
        return 1

    def release_orphaned_credential(*, keys, args):
        release_key, owner_key = keys
        expected_payload, credential_key, profile_id = args
        owner = redis.get(owner_key)
        owner = owner.decode() if isinstance(owner, bytes) else owner
        if str(owner) == str(profile_id):
            return 0
        return release_credential(
            keys=[release_key],
            args=[expected_payload, credential_key],
        )

    return {
        "reserve_owned": reserve_owned,
        "release_owned": release_owned,
        "reconcile": reconcile,
        "release_credential": release_credential,
        "release_orphaned_credential": release_orphaned_credential,
    }


class ExtractCredentialsTests(TestCase):
    def test_extract_credentials_from_xc_style_url(self):
        url = "http://example.com/live/alice/secret123/99999.ts"
        user, password = extract_credentials_from_stream_url(url)
        self.assertEqual(user, "alice")
        self.assertEqual(password, "secret123")


class ManualServerGroupTests(TestCase):
    def test_group_enforced_when_account_assigned(self):
        group = ServerGroup.objects.create(name="provider-a")
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
        group = ServerGroup.objects.create(name="shared")
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
        reserved1, _, _ = reserve_profile_slot(profile1, redis)
        self.assertTrue(reserved1)

        reserved2, _, _ = reserve_profile_slot(profile2, redis)
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
        reserved, _, _ = reserve_profile_slot(default, redis)
        self.assertTrue(reserved)
        self.assertFalse(profile_has_capacity_for_selection(default, redis))
        self.assertTrue(profile_has_capacity_for_selection(alt, redis))


class PoolEnforcementTests(TestCase):
    def setUp(self):
        self.redis = FakeRedis()
        self.group = ServerGroup.objects.create(name="test-pool")
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

    def test_group_has_capacity_reads_credential_counter_directly(self):
        cred_key = server_group_connections_key(
            self.group.id,
            get_profile_credential_fingerprint(self.profile),
        )
        self.redis.set(cred_key, 1)

        self.assertFalse(group_has_capacity_for_profile(self.profile, self.redis))

        self.redis.set(cred_key, 0)
        self.assertTrue(group_has_capacity_for_profile(self.profile, self.redis))

    def test_reserve_and_release_both_counters(self):
        reserved, count, _ = reserve_profile_slot(self.profile, self.redis)
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

    def test_owned_vod_reservation_and_release_are_idempotent(self):
        reservation_key = vod_profile_reservation_key("session-1")
        credential_key = server_group_connections_key(
            self.group.id,
            get_profile_credential_fingerprint(self.profile),
        )

        with patch(
            "apps.m3u.connection_pool._profile_scripts",
            return_value=fake_owned_profile_scripts(self.redis),
        ):
            first = reserve_profile_slot(
                self.profile,
                self.redis,
                reservation_key=reservation_key,
            )
            second = reserve_profile_slot(
                self.profile,
                self.redis,
                reservation_key=reservation_key,
            )

            self.assertTrue(first[0])
            self.assertTrue(second[0])
            self.assertEqual(
                self.redis._data[profile_connections_key(self.profile.id)], 1
            )

            release_profile_slot(
                self.profile.id,
                self.redis,
                reservation_key=reservation_key,
            )
            release_profile_slot(
                self.profile.id,
                self.redis,
                reservation_key=reservation_key,
            )

        self.assertEqual(
            self.redis._data[profile_connections_key(self.profile.id)], 0
        )
        self.assertEqual(self.redis._data[credential_key], 0)
        self.assertNotIn(reservation_key, self.redis._data)

    def test_owned_vod_reservation_rolls_back_when_credential_pool_is_full(self):
        other_account = M3UAccount.objects.create(
            name="Second owned account",
            account_type="XC",
            username=self.account.username,
            password=self.account.password,
            server_url=self.account.server_url,
            server_group=self.group,
            max_streams=1,
        )
        other_profile = M3UAccountProfile.objects.get(
            m3u_account=other_account,
            is_default=True,
        )
        other_profile.max_streams = 1
        other_profile.save()

        first_key = vod_profile_reservation_key("owned-1")
        second_key = vod_profile_reservation_key("owned-2")
        with patch(
            "apps.m3u.connection_pool._profile_scripts",
            side_effect=lambda redis: fake_owned_profile_scripts(redis),
        ):
            self.assertTrue(
                reserve_profile_slot(
                    self.profile,
                    self.redis,
                    reservation_key=first_key,
                )[0]
            )
            reserved, count, reason = reserve_profile_slot(
                other_profile,
                self.redis,
                reservation_key=second_key,
            )

        self.assertFalse(reserved)
        self.assertEqual(count, 0)
        self.assertEqual(reason, "credential_full")
        self.assertNotIn(second_key, self.redis._data)
        self.assertEqual(
            self.redis._data.get(profile_connections_key(other_profile.id), 0),
            0,
        )

    def test_reconcile_repairs_only_the_stale_part_of_profile_counter(self):
        profile_id = self.profile.id
        profile_key = profile_connections_key(profile_id)
        self.redis.set(profile_key, 4)
        self.redis.set(profile_connections_version_key(profile_id), 7)
        self.redis.set("stream_profile:10", profile_id)
        self.redis.set(vod_profile_reservation_key("vod-1"), profile_id)
        self.redis.hset(
            "timeshift:pool:catchup-1",
            {"profile_id": profile_id, "busy": "1"},
        )

        with patch(
            "apps.m3u.connection_pool._profile_scripts",
            return_value=fake_owned_profile_scripts(self.redis),
        ):
            result = reconcile_profile_connection_count(profile_id, self.redis)

        self.assertEqual(result, 3)
        self.assertEqual(self.redis._data[profile_key], 3)

    def test_reconcile_does_not_overwrite_a_concurrent_counter_change(self):
        profile_id = self.profile.id
        profile_key = profile_connections_key(profile_id)
        version_key = profile_connections_version_key(profile_id)
        self.redis.set(profile_key, 1)
        self.redis.set(version_key, 3)
        scripts = fake_owned_profile_scripts(self.redis)
        original_reconcile = scripts["reconcile"]

        def concurrent_reconcile(*, keys, args):
            self.redis.incr(version_key)
            return original_reconcile(keys=keys, args=args)

        scripts["reconcile"] = concurrent_reconcile
        with patch(
            "apps.m3u.connection_pool._profile_scripts",
            return_value=scripts,
        ):
            result = reconcile_profile_connection_count(profile_id, self.redis)

        self.assertEqual(result, 1)
        self.assertEqual(self.redis._data[profile_key], 1)

    def test_reconcile_releases_expired_owned_vod_and_credential_slots(self):
        profile_id = self.profile.id
        reservation_key = vod_profile_reservation_key("expired-vod")
        credential_key = server_group_connections_key(
            self.group.id,
            get_profile_credential_fingerprint(self.profile),
        )

        with patch(
            "apps.m3u.connection_pool._profile_scripts",
            return_value=fake_owned_profile_scripts(self.redis),
        ):
            self.assertTrue(
                reserve_profile_slot(
                    self.profile,
                    self.redis,
                    reservation_key=reservation_key,
                )[0]
            )
            # Redis expires abandoned setup ownership; the aggregate counters
            # intentionally remain for reconciliation on the next full check.
            self.redis.delete(reservation_key)
            result = reconcile_profile_connection_count(profile_id, self.redis)

        self.assertEqual(result, 0)
        self.assertEqual(self.redis._data[profile_connections_key(profile_id)], 0)
        self.assertEqual(self.redis._data[credential_key], 0)

    def test_same_credential_capped_at_profile_max(self):
        """Shared credential counter is capped by each profile's max_streams."""
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

    def test_different_logins_both_stream_in_same_group(self):
        """Different provider logins keep separate credential counters in one group."""
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

    def test_xc_credential_transform_failure_denies_group_reservation(self):
        """
        A grouped XC profile whose search/replace pattern doesn't match must be
        denied a shared-pool slot, not silently treated as unlimited/unpooled.
        """
        broken = M3UAccountProfile.objects.create(
            m3u_account=self.account,
            name="broken-pattern",
            max_streams=1,
            is_active=True,
            search_pattern="no/match/here",
            replace_pattern="user1/user1pass",
        )

        self.assertIsNone(get_profile_credential_fingerprint(broken))
        self.assertFalse(group_has_capacity_for_profile(broken, self.redis))

        reserved, _, failure_reason = reserve_profile_slot(broken, self.redis)
        self.assertFalse(reserved)
        self.assertEqual(failure_reason, "credential_full")
        self.assertEqual(
            self.redis._data.get(profile_connections_key(broken.id), 0), 0
        )

    def test_no_fingerprint_fails_closed_on_credential_counter(self):
        """
        A profile in an enforced ServerGroup whose login can't be fingerprinted
        must not bypass the shared-credential capacity check: the profile slot
        reservation is rolled back and the reservation is denied.
        """
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
            reserved, _, failure_reason = reserve_profile_slot(profile, self.redis)
            self.assertFalse(reserved)
            self.assertEqual(failure_reason, "credential_full")
            self.assertEqual(get_credential_connection_count(profile, self.redis), 0)
            # Profile-level counter must be rolled back too, not left incremented.
            self.assertEqual(
                self.redis._data.get(profile_connections_key(profile.id), 0), 0
            )

    def test_release_when_profile_row_deleted(self):
        profile_id = self.profile.id
        fp = get_profile_credential_fingerprint(self.profile)
        cred_key = server_group_connections_key(self.group.id, fp)

        reserved, _, failure_reason = reserve_profile_slot(
            self.profile, self.redis
        )
        self.assertTrue(reserved)
        self.assertIsNone(failure_reason)
        self.profile.delete()

        release_profile_slot(profile_id, self.redis)

        self.assertEqual(self.redis._data[profile_connections_key(profile_id)], 0)
        self.assertEqual(self.redis._data[cred_key], 0)
        self.assertNotIn(profile_credential_release_key(profile_id), self.redis._data)

    def test_release_uses_stored_credential_key_without_db_lookup(self):
        profile_id = self.profile.id
        cred_key = server_group_connections_key(
            self.group.id,
            get_profile_credential_fingerprint(self.profile),
        )

        self.assertTrue(reserve_profile_slot(self.profile, self.redis)[0])

        with patch("apps.m3u.models.M3UAccountProfile.objects.get") as mock_get:
            release_profile_slot(profile_id, self.redis)
            mock_get.assert_not_called()

        self.assertEqual(self.redis._data[profile_connections_key(profile_id)], 0)
        self.assertEqual(self.redis._data[cred_key], 0)

    def test_reserve_returns_failure_reason_without_extra_checks(self):
        account2 = M3UAccount.objects.create(
            name="Reason Account",
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
        reserved, _count, reason = reserve_profile_slot(profile2, self.redis)
        self.assertFalse(reserved)
        self.assertEqual(reason, "credential_full")


class StaleAssignmentTests(TestCase):
    def test_stale_assignment_releases_counters(self):
        from apps.channels.models import Channel, Stream

        redis = FakeRedis()
        group = ServerGroup.objects.create(name="stale-group")
        account = M3UAccount.objects.create(
            name="Stale Account",
            account_type="XC",
            username="user",
            password="pass",
            server_url="http://xc.example.com",
            server_group=group,
            max_streams=5,
        )
        profile = M3UAccountProfile.objects.get(m3u_account=account, is_default=True)
        profile.max_streams = 1
        profile.save()

        stream = Stream.objects.create(name="Stale Stream", m3u_account=account)
        channel = Channel.objects.create(channel_number=502, name="Stale Channel")
        channel.streams.add(stream)

        reserve_profile_slot(profile, redis)
        redis.set(f"channel_stream:{channel.id}", stream.id)
        redis.set(f"stream_profile:{stream.id}", profile.id)

        profile_key = profile_connections_key(profile.id)
        cred_key = server_group_connections_key(
            group.id, get_profile_credential_fingerprint(profile)
        )
        self.assertEqual(redis._data[profile_key], 1)
        self.assertEqual(redis._data[cred_key], 1)

        with patch("core.utils.RedisClient.get_client", return_value=redis):
            channel._release_stale_stream_assignment(redis, stream.id)

        self.assertNotIn(f"channel_stream:{channel.id}", redis._data)
        self.assertNotIn(f"stream_profile:{stream.id}", redis._data)
        self.assertEqual(redis._data[profile_key], 0)
        self.assertEqual(redis._data[cred_key], 0)


class UpdateStreamProfileTests(TestCase):
    def test_switch_updates_profile_counters_when_group_assigned(self):
        from apps.channels.models import Channel, Stream

        redis = FakeRedis()
        group = ServerGroup.objects.create(name="switch-group")
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

    def test_switch_moves_credential_counter_when_login_changes(self):
        from apps.channels.models import Channel, Stream

        redis = FakeRedis()
        group = ServerGroup.objects.create(name="cred-switch-group")
        account = M3UAccount.objects.create(
            name="Cred Switch Account",
            account_type="XC",
            username="login_a",
            password="pass_a",
            server_url="http://xc.example.com",
            server_group=group,
            max_streams=5,
        )
        profile_a = M3UAccountProfile.objects.get(m3u_account=account, is_default=True)
        profile_a.max_streams = 1
        profile_a.save()
        profile_b = M3UAccountProfile.objects.create(
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
        key_a = server_group_connections_key(group.id, fp_a)
        key_b = server_group_connections_key(group.id, fp_b)

        stream = Stream.objects.create(name="Cred Switch Stream", m3u_account=account)
        channel = Channel.objects.create(channel_number=503, name="Cred Switch Channel")
        channel.streams.add(stream)

        with patch(
            "apps.m3u.connection_pool.get_profile_credential_fingerprint",
            side_effect=lambda profile: fp_a if profile.id == profile_a.id else fp_b,
        ):
            reserve_profile_slot(profile_a, redis)
            redis.set(f"channel_stream:{channel.id}", stream.id)
            redis.set(f"stream_profile:{stream.id}", profile_a.id)
            self.assertEqual(redis._data[key_a], 1)
            self.assertNotIn(key_b, redis._data)

            with patch("core.utils.RedisClient.get_client", return_value=redis):
                self.assertTrue(channel.update_stream_profile(profile_b.id))

            self.assertEqual(redis._data[key_a], 0)
            self.assertEqual(redis._data[key_b], 1)


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
        redis.set("stream_profile:900", default.id)

        with patch("core.utils.RedisClient.get_client", return_value=redis):
            result = _get_m3u_profile(account, None, None)

        self.assertIsNotNone(result)
        selected, _connections = result
        self.assertEqual(selected.id, alt.id)

    def test_get_m3u_profile_repairs_stale_counter_before_selection(self):
        from apps.proxy.vod_proxy.views import _get_m3u_profile

        account = M3UAccount.objects.create(
            name="VOD stale profile",
            account_type="XC",
            username="xc_user_stale",
            password="xc_pass_stale",
            server_url="http://xc.example.com",
            max_streams=1,
        )
        default = M3UAccountProfile.objects.get(
            m3u_account=account, is_default=True
        )
        default.max_streams = 1
        default.save()
        redis = FakeRedis()
        redis.set(profile_connections_key(default.id), 1)

        def repair(profile_id, redis_client):
            redis_client.set(profile_connections_key(profile_id), 0)
            return 0

        with (
            patch("core.utils.RedisClient.get_client", return_value=redis),
            patch(
                "apps.m3u.connection_pool.reconcile_profile_connection_count",
                side_effect=repair,
            ) as mock_reconcile,
        ):
            result = _get_m3u_profile(account, None, None)

        self.assertIsNotNone(result)
        self.assertEqual(result[0].id, default.id)
        self.assertEqual(result[1], 0)
        mock_reconcile.assert_called_once_with(default.id, redis)

    def test_get_m3u_profile_skips_default_when_credential_pool_full(self):
        from apps.proxy.vod_proxy.views import _get_m3u_profile

        group = ServerGroup.objects.create(name="vod-cred-pool")
        account = M3UAccount.objects.create(
            name="VOD pooled",
            account_type="XC",
            username="shared_user",
            password="shared_pass",
            server_url="http://xc.example.com",
            server_group=group,
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

        other_account = M3UAccount.objects.create(
            name="Other pooled account",
            account_type="XC",
            username="shared_user",
            password="shared_pass",
            server_url="http://xc.example.com",
            server_group=group,
            max_streams=5,
        )
        other_profile = M3UAccountProfile.objects.get(
            m3u_account=other_account, is_default=True
        )
        other_profile.max_streams = 1
        other_profile.save()

        fp_shared = "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
        fp_alt = "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd"

        redis = FakeRedis()
        with patch(
            "apps.m3u.connection_pool.get_profile_credential_fingerprint",
            side_effect=lambda profile: (
                fp_shared
                if profile.id in (default.id, other_profile.id)
                else fp_alt
            ),
        ):
            self.assertTrue(reserve_profile_slot(other_profile, redis)[0])

            with patch("core.utils.RedisClient.get_client", return_value=redis):
                result = _get_m3u_profile(account, None, None)

        self.assertIsNotNone(result)
        selected, _connections = result
        self.assertEqual(selected.id, alt.id)
