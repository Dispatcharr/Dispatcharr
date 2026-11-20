"""Tests for per-connection User-Agent numbering (vary_user_agent).

Covers the free-list slot allocator in connection_pool.py and
M3UAccount.get_user_agent_string()'s connection_index substitution.
"""

from django.test import TestCase

from apps.m3u.connection_pool import reserve_ua_slot, release_ua_slot
from apps.m3u.models import M3UAccount


class FakeRedisList:
    """Minimal in-memory Redis stand-in supporting the list ops the
    free-list allocator needs (lpop/rpush) plus incr for the counter.
    """

    def __init__(self):
        self._lists = {}
        self._counters = {}

    def lpop(self, key):
        bucket = self._lists.get(key)
        if not bucket:
            return None
        return bucket.pop(0)

    def rpush(self, key, value):
        self._lists.setdefault(key, []).append(value)

    def incr(self, key):
        self._counters[key] = self._counters.get(key, 0) + 1
        return self._counters[key]


class ReserveReleaseUaSlotTests(TestCase):
    def setUp(self):
        self.redis = FakeRedisList()

    def test_first_reservations_mint_sequential_numbers(self):
        self.assertEqual(reserve_ua_slot(1, self.redis), 1)
        self.assertEqual(reserve_ua_slot(1, self.redis), 2)
        self.assertEqual(reserve_ua_slot(1, self.redis), 3)

    def test_released_slot_is_reused_before_minting_a_new_one(self):
        first = reserve_ua_slot(1, self.redis)
        second = reserve_ua_slot(1, self.redis)
        release_ua_slot(1, first, self.redis)

        reused = reserve_ua_slot(1, self.redis)

        self.assertEqual(reused, first)
        # Counter wasn't touched by the reuse, so the next *new* reservation
        # still continues from where the counter left off.
        third = reserve_ua_slot(1, self.redis)
        self.assertEqual(third, 3)
        self.assertNotEqual(second, reused)

    def test_release_with_none_slot_is_a_no_op(self):
        release_ua_slot(1, None, self.redis)
        self.assertEqual(reserve_ua_slot(1, self.redis), 1)

    def test_slots_are_independent_per_profile(self):
        self.assertEqual(reserve_ua_slot(1, self.redis), 1)
        self.assertEqual(reserve_ua_slot(2, self.redis), 1)
        self.assertEqual(reserve_ua_slot(1, self.redis), 2)

    def test_two_simultaneously_held_connections_never_share_a_number(self):
        # This is the property the free-list design exists for: unlike a
        # plain INCR/DECR counter, releasing one connection's slot can never
        # hand that same number to another connection that is still live.
        a = reserve_ua_slot(1, self.redis)
        b = reserve_ua_slot(1, self.redis)
        self.assertNotEqual(a, b)

        # a's connection ends and releases its slot...
        release_ua_slot(1, a, self.redis)
        # ...while b is still live. A third, still-concurrent connection
        # reserves next and may legitimately reuse a's freed number, but
        # must never collide with b, which never released.
        c = reserve_ua_slot(1, self.redis)
        self.assertNotEqual(c, b)


class GetUserAgentStringTests(TestCase):
    def _account(self, **kwargs):
        defaults = dict(name="test-account", account_type="STD")
        defaults.update(kwargs)
        return M3UAccount.objects.create(**defaults)

    def test_vary_disabled_returns_base_ua_unchanged(self):
        account = self._account(vary_user_agent=False)
        self.assertEqual(
            account.get_user_agent_string(connection_index=5),
            account.get_user_agent_string(connection_index=None),
        )

    def test_vary_enabled_without_connection_index_is_unchanged(self):
        from core.models import UserAgent

        ua = UserAgent.objects.create(name="plain", user_agent="TiviMate/5.1.6")
        account = self._account(vary_user_agent=True, user_agent=ua)

        self.assertEqual(
            account.get_user_agent_string(connection_index=None), "TiviMate/5.1.6"
        )

    def test_placeholder_is_substituted_when_present(self):
        from core.models import UserAgent

        ua = UserAgent.objects.create(name="placeholder-style", user_agent="VLC/3 ({#})")
        account = self._account(vary_user_agent=True, user_agent=ua)

        self.assertEqual(
            account.get_user_agent_string(connection_index=1), "VLC/3 (1)"
        )
        self.assertEqual(
            account.get_user_agent_string(connection_index=2), "VLC/3 (2)"
        )

    def test_number_is_appended_as_suffix_when_no_placeholder(self):
        from core.models import UserAgent

        ua = UserAgent.objects.create(name="tivimate", user_agent="TiviMate/5.1.6")
        account = self._account(vary_user_agent=True, user_agent=ua)

        self.assertEqual(
            account.get_user_agent_string(connection_index=1), "TiviMate/5.1.6 1"
        )
        self.assertEqual(
            account.get_user_agent_string(connection_index=2), "TiviMate/5.1.6 2"
        )

    def test_distinct_connections_get_distinct_ua_strings(self):
        from core.models import UserAgent

        ua = UserAgent.objects.create(name="tivimate2", user_agent="TiviMate/5.1.6")
        account = self._account(vary_user_agent=True, user_agent=ua)

        seen = {
            account.get_user_agent_string(connection_index=i) for i in range(1, 4)
        }
        self.assertEqual(len(seen), 3)
