"""_get_m3u_profile must never fall back to a profile outside the Redirect-mode
allowlist, even when the requested/default profile is at capacity."""

from unittest.mock import patch

from django.test import TestCase

from apps.m3u.models import M3UAccount, M3UAccountProfile
from apps.proxy.vod_proxy.views import _get_m3u_profile


class FakeRedis:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def get(self, key):
        return self.values.get(key)

    def hgetall(self, key):
        return {}


class GetM3uProfileRestrictionTests(TestCase):
    def setUp(self):
        self.account = M3UAccount.objects.create(name="Provider")
        self.default_profile = self.account.profiles.get(is_default=True)
        self.default_profile.max_streams = 1
        self.default_profile.save()
        self.allowed_profile = M3UAccountProfile.objects.create(
            m3u_account=self.account,
            name="Allowed",
            search_pattern="^(.*)$",
            replace_pattern="$1",
            max_streams=1,
        )
        self.disallowed_profile = M3UAccountProfile.objects.create(
            m3u_account=self.account,
            name="Disallowed",
            search_pattern="^(.*)$",
            replace_pattern="$1",
            max_streams=1,
        )

    def _patch_redis(self, values=None):
        return patch(
            "core.utils.RedisClient.get_client",
            return_value=FakeRedis(values),
        )

    def test_unrestricted_falls_back_to_default_profile(self):
        with self._patch_redis():
            result = _get_m3u_profile(self.account, profile_id=None)
        self.assertIsNotNone(result)
        self.assertEqual(result[0].id, self.default_profile.id)

    def test_requested_profile_at_capacity_falls_back_within_allowlist_only(self):
        # Requested (allowed) profile is full; default profile has capacity but
        # is not in the allowlist, so it must never be selected.
        values = {
            f"profile_connections:{self.allowed_profile.id}": "1",
        }
        with self._patch_redis(values):
            result = _get_m3u_profile(
                self.account,
                profile_id=self.allowed_profile.id,
                restrict_to_profile_ids={self.allowed_profile.id},
            )
        self.assertIsNone(result)

    def test_falls_back_to_other_allowed_profile_on_same_account(self):
        # Requested profile is full, but a second allowed profile on the same
        # account has capacity: that one should be used, not the disallowed default.
        values = {
            f"profile_connections:{self.allowed_profile.id}": "1",
        }
        with self._patch_redis(values):
            result = _get_m3u_profile(
                self.account,
                profile_id=self.allowed_profile.id,
                restrict_to_profile_ids={
                    self.allowed_profile.id,
                    self.disallowed_profile.id,
                },
            )
        self.assertIsNotNone(result)
        self.assertEqual(result[0].id, self.disallowed_profile.id)

    def test_never_returns_a_profile_outside_the_allowlist(self):
        # Both allowed profiles are full; the account's default profile has
        # capacity but is not allowed, so selection must fail closed.
        values = {
            f"profile_connections:{self.allowed_profile.id}": "1",
            f"profile_connections:{self.disallowed_profile.id}": "1",
        }
        with self._patch_redis(values):
            result = _get_m3u_profile(
                self.account,
                profile_id=self.allowed_profile.id,
                restrict_to_profile_ids={
                    self.allowed_profile.id,
                    self.disallowed_profile.id,
                },
            )
        self.assertIsNone(result)

    def test_session_reuse_ignores_profile_outside_the_allowlist(self):
        values = {}

        class ReuseRedis(FakeRedis):
            def hgetall(self, key):
                return {"m3u_profile_id": str(self.outer_profile_id)}

        redis_client = ReuseRedis(values)
        redis_client.outer_profile_id = self.default_profile.id  # not allowed

        with patch("core.utils.RedisClient.get_client", return_value=redis_client):
            result = _get_m3u_profile(
                self.account,
                profile_id=self.allowed_profile.id,
                session_id="session-1",
                restrict_to_profile_ids={self.allowed_profile.id},
            )
        self.assertIsNotNone(result)
        self.assertEqual(result[0].id, self.allowed_profile.id)
