"""Tests for the per-M3U-account hash key override.

Covers M3UAccount.get_effective_hash_keys() (falls back to the global
CoreSettings default when no override is set), the serializer field that
exposes/persists it under custom_properties["hash_key"], and the scoping
of the unscoped (global-key-change) rehash_streams run so it never locks
or rewrites streams for accounts that have their own override.
"""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.channels.models import Channel, ChannelStream, Stream
from apps.m3u.models import CUSTOM_M3U_ACCOUNT_NAME, M3UAccount
from apps.m3u.serializers import M3UAccountSerializer
from apps.m3u.utils import parse_m3u_hash_keys
from core.models import CoreSettings, STREAM_SETTINGS_KEY
from core.tasks import (
    REHASH_LOCK_HANDOFF_TTL,
    REHASH_LOCK_TTL,
    confirm_preacquired_rehash_locks,
    rehash_streams,
    release_rehash_locks,
    try_acquire_rehash_locks,
)
from core.utils import (
    RedisClient,
    acquire_task_lock,
    is_task_lock_held,
    release_task_lock,
)

User = get_user_model()


def _set_global_hash_key(value):
    """Set the global M3U Hash Key setting the same way the Settings page does."""
    CoreSettings._update_group(
        STREAM_SETTINGS_KEY, "Stream Settings", {"m3u_hash_key": value}
    )


class ParseM3UHashKeysTests(TestCase):
    def test_strips_whitespace_and_keeps_order(self):
        self.assertEqual(
            parse_m3u_hash_keys("name, url , tvg_id"),
            ["name", "url", "tvg_id"],
        )

    def test_drops_unknown_tokens_by_default(self):
        self.assertEqual(parse_m3u_hash_keys("name,bogus,url"), ["name", "url"])

    def test_strict_mode_rejects_unknown_tokens(self):
        with self.assertRaises(ValueError) as ctx:
            parse_m3u_hash_keys("name,bogus", strict=True)
        self.assertIn("bogus", str(ctx.exception))

    def test_all_invalid_returns_empty_list(self):
        self.assertEqual(parse_m3u_hash_keys("bogus"), [])

    def test_deduplicates_while_preserving_first_order(self):
        self.assertEqual(parse_m3u_hash_keys("url,name,url"), ["url", "name"])

    def test_rejects_already_parsed_lists(self):
        with self.assertRaises(TypeError):
            parse_m3u_hash_keys(["name", "url"])


class GetEffectiveHashKeysTests(TestCase):
    def setUp(self):
        _set_global_hash_key("name,url")

    def test_falls_back_to_global_default_when_no_override(self):
        account = M3UAccount.objects.create(name="No Override Account")
        self.assertNotIn("hash_key", account.custom_properties or {})
        self.assertEqual(account.get_effective_hash_keys(), ["name", "url"])

    def test_falls_back_to_global_default_when_custom_properties_is_none(self):
        account = M3UAccount.objects.create(
            name="Null Custom Properties Account", custom_properties=None
        )
        self.assertEqual(account.get_effective_hash_keys(), ["name", "url"])

    def test_falls_back_to_global_default_when_override_is_empty_string(self):
        account = M3UAccount.objects.create(
            name="Empty Override Account", custom_properties={"hash_key": ""}
        )
        self.assertEqual(account.get_effective_hash_keys(), ["name", "url"])

    def test_uses_account_override_when_set(self):
        account = M3UAccount.objects.create(
            name="Overridden Account", custom_properties={"hash_key": "tvg_id,group"}
        )
        self.assertEqual(account.get_effective_hash_keys(), ["tvg_id", "group"])

    def test_override_drops_empty_entries_from_trailing_commas(self):
        account = M3UAccount.objects.create(
            name="Trailing Comma Account",
            custom_properties={"hash_key": "name,,tvg_id,"},
        )
        self.assertEqual(account.get_effective_hash_keys(), ["name", "tvg_id"])

    def test_override_strips_whitespace_around_fields(self):
        account = M3UAccount.objects.create(
            name="Spaced Override Account",
            custom_properties={"hash_key": "name, url"},
        )
        self.assertEqual(account.get_effective_hash_keys(), ["name", "url"])

    def test_all_invalid_override_falls_back_to_global(self):
        # Defensive: a stored invalid value must not collapse every stream
        # onto one empty hash.
        account = M3UAccount.objects.create(
            name="Bogus Override Account",
            custom_properties={"hash_key": "bogus"},
        )
        self.assertEqual(account.get_effective_hash_keys(), ["name", "url"])

    def test_other_accounts_are_unaffected_by_one_accounts_override(self):
        overridden = M3UAccount.objects.create(
            name="Overridden Account 2", custom_properties={"hash_key": "name,m3u_id"}
        )
        plain = M3UAccount.objects.create(name="Plain Account 2")

        self.assertEqual(overridden.get_effective_hash_keys(), ["name", "m3u_id"])
        self.assertEqual(plain.get_effective_hash_keys(), ["name", "url"])

    def test_changing_the_global_default_does_not_affect_an_override(self):
        overridden = M3UAccount.objects.create(
            name="Overridden Account 3",
            custom_properties={"hash_key": "name,m3u_id,group"},
        )
        plain = M3UAccount.objects.create(name="Plain Account 3")

        _set_global_hash_key("name,tvg_id")

        self.assertEqual(
            overridden.get_effective_hash_keys(), ["name", "m3u_id", "group"]
        )
        self.assertEqual(plain.get_effective_hash_keys(), ["name", "tvg_id"])

    def test_override_survives_unrelated_custom_properties(self):
        account = M3UAccount.objects.create(
            name="Mixed Custom Properties Account",
            custom_properties={"enable_vod": True, "hash_key": "tvg_id"},
        )
        self.assertEqual(account.get_effective_hash_keys(), ["tvg_id"])


class M3UAccountSerializerHashKeyTests(TestCase):
    """hash_key is not a model column - it's popped in create()/update() and
    stored under custom_properties["hash_key"], the same pattern used for
    enable_vod and the auto_enable_new_groups_* fields."""

    def test_hash_key_field_is_exposed(self):
        account = M3UAccount.objects.create(
            name="Serialized Account", custom_properties={"hash_key": "name,tvg_id"}
        )
        data = M3UAccountSerializer(account).data
        self.assertEqual(data["hash_key"], "name,tvg_id")

    def test_hash_key_defaults_to_null_when_not_set(self):
        account = M3UAccount.objects.create(name="Serialized Account 2")
        data = M3UAccountSerializer(account).data
        self.assertIsNone(data["hash_key"])

    def test_create_stores_hash_key_under_custom_properties(self):
        serializer = M3UAccountSerializer(
            data={"name": "Created Account", "hash_key": "tvg_id,group"}
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        created = serializer.save()

        self.assertEqual(created.custom_properties.get("hash_key"), "tvg_id,group")
        self.assertEqual(created.get_effective_hash_keys(), ["tvg_id", "group"])

    def test_create_without_hash_key_leaves_the_key_unset(self):
        serializer = M3UAccountSerializer(data={"name": "Created Account 2"})
        self.assertTrue(serializer.is_valid(), serializer.errors)
        created = serializer.save()

        self.assertNotIn("hash_key", created.custom_properties or {})

    def test_update_sets_hash_key_under_custom_properties(self):
        account = M3UAccount.objects.create(name="Serialized Account 3")
        serializer = M3UAccountSerializer(
            account, data={"hash_key": "name,group"}, partial=True
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        updated = serializer.save()

        self.assertEqual(updated.custom_properties.get("hash_key"), "name,group")

    def test_hash_key_accepts_null_to_clear_an_override(self):
        account = M3UAccount.objects.create(
            name="Serialized Account 4", custom_properties={"hash_key": "name,tvg_id"}
        )
        serializer = M3UAccountSerializer(
            account, data={"hash_key": None}, partial=True
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        updated = serializer.save()

        # Clearing removes the key entirely rather than storing null/empty.
        self.assertNotIn("hash_key", updated.custom_properties or {})
        self.assertEqual(
            updated.get_effective_hash_keys(),
            parse_m3u_hash_keys(CoreSettings.get_m3u_hash_key()),
        )

    def test_hash_key_accepts_empty_string_to_clear_an_override(self):
        account = M3UAccount.objects.create(
            name="Serialized Account 5", custom_properties={"hash_key": "name,tvg_id"}
        )
        serializer = M3UAccountSerializer(
            account, data={"hash_key": ""}, partial=True
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        updated = serializer.save()

        self.assertNotIn("hash_key", updated.custom_properties or {})

    def test_update_preserves_unrelated_custom_properties(self):
        account = M3UAccount.objects.create(
            name="Serialized Account 6", custom_properties={"enable_vod": True}
        )
        serializer = M3UAccountSerializer(
            account, data={"hash_key": "name"}, partial=True
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        updated = serializer.save()

        self.assertTrue(updated.custom_properties.get("enable_vod"))
        self.assertEqual(updated.custom_properties.get("hash_key"), "name")

    def test_hash_key_normalizes_whitespace_on_write(self):
        account = M3UAccount.objects.create(name="Serialized Account 7")
        serializer = M3UAccountSerializer(
            account, data={"hash_key": "name, url"}, partial=True
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        updated = serializer.save()
        self.assertEqual(updated.custom_properties.get("hash_key"), "name,url")

    def test_hash_key_rejects_unknown_fields(self):
        account = M3UAccount.objects.create(name="Serialized Account 8")
        serializer = M3UAccountSerializer(
            account, data={"hash_key": "name,bogus"}, partial=True
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("hash_key", serializer.errors)

    def test_hash_key_rejects_only_unknown_fields(self):
        account = M3UAccount.objects.create(name="Serialized Account 9")
        serializer = M3UAccountSerializer(
            account, data={"hash_key": "bogus"}, partial=True
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("hash_key", serializer.errors)

    def test_custom_properties_hash_key_is_ignored_on_update(self):
        """Raw custom_properties cannot set hash_key; use the typed field."""
        account = M3UAccount.objects.create(
            name="Serialized Account 10",
            custom_properties={"enable_vod": True},
        )
        serializer = M3UAccountSerializer(
            account,
            data={"custom_properties": {"hash_key": "tvg_id", "enable_vod": True}},
            partial=True,
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        updated = serializer.save()
        self.assertNotIn("hash_key", updated.custom_properties or {})
        self.assertTrue(updated.custom_properties.get("enable_vod"))

    def test_custom_properties_hash_key_is_ignored_on_create(self):
        serializer = M3UAccountSerializer(
            data={
                "name": "Created Via Custom Props",
                "custom_properties": {"hash_key": "tvg_id"},
            }
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        created = serializer.save()
        self.assertNotIn("hash_key", created.custom_properties or {})


class RehashStreamsScopingTests(TestCase):
    """Covers the reviewer-requested scoping of the unscoped rehash run:
    accounts with their own hash_key override are skipped entirely (not
    locked, not loaded, not rewritten). Every other account is locked,
    active or inactive. Streams with no account, and streams on an
    inactive account without an override, are still rehashed.
    """

    def setUp(self):
        _set_global_hash_key("name,url")
        # Stream pre_save assigns the locked "custom" account when m3u_account
        # is omitted. Keepdb runs can lose that migration row.
        M3UAccount.objects.get_or_create(
            name=CUSTOM_M3U_ACCOUNT_NAME,
            locked=True,
            defaults={"is_active": True, "max_streams": 0},
        )

    def _make_stream(self, account, name, url, keys, tvg_id=None):
        old_hash = Stream.generate_hash_key(name, url, tvg_id, keys, m3u_id=account.id if account else None)
        return Stream.objects.create(
            name=name,
            url=url,
            tvg_id=tvg_id,
            m3u_account=account,
            stream_hash=old_hash,
        )

    def test_unscoped_rehash_leaves_override_account_streams_untouched(self):
        override_account = M3UAccount.objects.create(
            name="Override Account",
            is_active=True,
            custom_properties={"hash_key": "tvg_id"},
        )
        stream = self._make_stream(
            override_account, "Stream A", "http://a", ["tvg_id"], tvg_id="a1"
        )
        old_hash = stream.stream_hash

        # Simulate the global default changing to something else.
        _set_global_hash_key("name,url,group")
        new_global_keys = parse_m3u_hash_keys(CoreSettings.get_m3u_hash_key())

        result = rehash_streams(new_global_keys)

        stream.refresh_from_db()
        self.assertEqual(
            stream.stream_hash, old_hash,
            "An account with its own hash_key override should not be rewritten "
            "by an unscoped rehash of the global default.",
        )
        self.assertIn("Successfully rehashed", result)

    def test_unscoped_rehash_updates_plain_account_and_accountless_streams(self):
        plain_account = M3UAccount.objects.create(name="Plain Account", is_active=True)
        old_keys = ["name", "url"]
        plain_stream = self._make_stream(
            plain_account, "Stream B", "http://b", old_keys
        )
        accountless_stream = self._make_stream(
            None, "Stream C", "http://c", old_keys
        )
        old_plain_hash = plain_stream.stream_hash
        old_accountless_hash = accountless_stream.stream_hash

        _set_global_hash_key("name,url,group")
        new_keys = parse_m3u_hash_keys(CoreSettings.get_m3u_hash_key())

        rehash_streams(new_keys)

        plain_stream.refresh_from_db()
        accountless_stream.refresh_from_db()
        self.assertNotEqual(plain_stream.stream_hash, old_plain_hash)
        self.assertNotEqual(accountless_stream.stream_hash, old_accountless_hash)

    def test_unscoped_rehash_updates_inactive_account_without_override(self):
        inactive_account = M3UAccount.objects.create(
            name="Inactive Account", is_active=False
        )
        old_keys = ["name", "url"]
        stream = self._make_stream(
            inactive_account, "Stream D", "http://d", old_keys
        )
        old_hash = stream.stream_hash

        _set_global_hash_key("name,url,group")
        new_keys = parse_m3u_hash_keys(CoreSettings.get_m3u_hash_key())

        rehash_streams(new_keys)

        stream.refresh_from_db()
        self.assertNotEqual(
            stream.stream_hash, old_hash,
            "Inactive accounts without an override still follow the global "
            "key and should still be rehashed.",
        )

    def test_unscoped_rehash_is_not_blocked_by_an_override_account_refreshing(self):
        override_account = M3UAccount.objects.create(
            name="Refreshing Override Account",
            is_active=True,
            custom_properties={"hash_key": "tvg_id"},
        )
        plain_account = M3UAccount.objects.create(
            name="Plain Account 2", is_active=True
        )
        old_keys = ["name", "url"]
        plain_stream = self._make_stream(
            plain_account, "Stream E", "http://e", old_keys
        )
        old_plain_hash = plain_stream.stream_hash

        # Simulate a concurrent refresh holding the lock for the override
        # account. Since override accounts are skipped entirely by the
        # unscoped run, this must not block the rest of the rehash.
        self.assertTrue(
            acquire_task_lock("refresh_single_m3u_account", override_account.id)
        )
        try:
            _set_global_hash_key("name,url,group")
            new_keys = parse_m3u_hash_keys(CoreSettings.get_m3u_hash_key())

            result = rehash_streams(new_keys)

            self.assertNotIn("blocked", result.lower())
            plain_stream.refresh_from_db()
            self.assertNotEqual(plain_stream.stream_hash, old_plain_hash)
        finally:
            release_task_lock("refresh_single_m3u_account", override_account.id)

    def test_scoped_rehash_still_locks_and_rewrites_an_override_account(self):
        # The per-account save path (account_id set) is unchanged: it always
        # locks and rehashes exactly the target account, override or not.
        override_account = M3UAccount.objects.create(
            name="Directly Scoped Override Account",
            is_active=True,
            custom_properties={"hash_key": "tvg_id"},
        )
        stream = self._make_stream(
            override_account, "Stream F", "http://f", ["name", "url"]
        )
        old_hash = stream.stream_hash

        result = rehash_streams(["tvg_id"], account_id=override_account.id)

        stream.refresh_from_db()
        self.assertNotEqual(stream.stream_hash, old_hash)
        self.assertIn("Successfully rehashed", result)

    def test_blocked_rehash_returns_without_retrying(self):
        plain_account = M3UAccount.objects.create(
            name="Refreshing Plain Account", is_active=True
        )
        self.assertTrue(
            acquire_task_lock("refresh_single_m3u_account", plain_account.id)
        )
        try:
            with patch.object(rehash_streams, "apply_async") as mock_apply:
                result = rehash_streams(
                    ["name", "url", "group"], account_id=plain_account.id
                )

            self.assertIn("blocked", result.lower())
            self.assertNotIn("retry", result.lower())
            mock_apply.assert_not_called()
        finally:
            release_task_lock("refresh_single_m3u_account", plain_account.id)

    def test_preacquired_locks_are_released_by_the_task(self):
        plain_account = M3UAccount.objects.create(
            name="Preacquired Lock Account", is_active=True
        )
        acquired, blocked, token = try_acquire_rehash_locks(account_id=plain_account.id)
        self.assertEqual(blocked, [])
        self.assertEqual(acquired, [plain_account.id])
        self.assertTrue(
            is_task_lock_held("refresh_single_m3u_account", plain_account.id)
        )

        rehash_streams(
            ["name", "url"],
            account_id=plain_account.id,
            locks_preacquired=True,
            preacquired_lock_ids=acquired,
            preacquired_lock_token=token,
        )

        self.assertFalse(
            is_task_lock_held("refresh_single_m3u_account", plain_account.id)
        )

    def test_expired_preacquired_lock_is_taken_again(self):
        plain_account = M3UAccount.objects.create(
            name="Expired Preacquired Lock Account", is_active=True
        )
        acquired, blocked, token = try_acquire_rehash_locks(account_id=plain_account.id)
        self.assertEqual(blocked, [])
        RedisClient.get_client().delete(
            f"task_lock_refresh_single_m3u_account_{plain_account.id}"
        )

        result = rehash_streams(
            ["name", "url"],
            account_id=plain_account.id,
            locks_preacquired=True,
            preacquired_lock_ids=acquired,
            preacquired_lock_token=token,
        )

        self.assertIn("Successfully rehashed", result)
        self.assertFalse(
            is_task_lock_held("refresh_single_m3u_account", plain_account.id)
        )

    def test_preacquired_lock_held_by_someone_else_blocks_without_deleting_it(self):
        plain_account = M3UAccount.objects.create(
            name="Stolen Preacquired Lock Account", is_active=True
        )
        acquired, blocked, token = try_acquire_rehash_locks(account_id=plain_account.id)
        self.assertEqual(blocked, [])
        lock_key = f"task_lock_refresh_single_m3u_account_{plain_account.id}"
        RedisClient.get_client().set(lock_key, "refresh-owner", ex=300)
        try:
            result = rehash_streams(
                ["name", "url"],
                account_id=plain_account.id,
                locks_preacquired=True,
                preacquired_lock_ids=acquired,
                preacquired_lock_token=token,
            )

            self.assertIn("blocked", result.lower())
            self.assertEqual(RedisClient.get_client().get(lock_key), "refresh-owner")
        finally:
            release_task_lock("refresh_single_m3u_account", plain_account.id)

    def test_rehash_renews_locks_for_the_duration_of_the_run(self):
        plain_account = M3UAccount.objects.create(
            name="Renewed Lock Account", is_active=True
        )
        renewer = patch("core.tasks.TaskLockRenewer").start()
        self.addCleanup(patch.stopall)
        instance = renewer.return_value

        rehash_streams(["name", "url"], account_id=plain_account.id)

        args, kwargs = renewer.call_args
        self.assertEqual(args, ("refresh_single_m3u_account", plain_account.id))
        self.assertEqual(kwargs.get("ttl"), REHASH_LOCK_TTL)
        self.assertTrue(kwargs.get("expected_value"))
        instance.start.assert_called_once()
        instance.stop.assert_called_once()

    def test_try_acquire_uses_handoff_ttl(self):
        plain_account = M3UAccount.objects.create(
            name="Handoff TTL Account", is_active=True
        )
        acquired, blocked, token = try_acquire_rehash_locks(account_id=plain_account.id)
        self.assertEqual(blocked, [])
        self.assertEqual(acquired, [plain_account.id])
        lock_key = f"task_lock_refresh_single_m3u_account_{plain_account.id}"
        redis_client = RedisClient.get_client()
        try:
            ttl = redis_client.ttl(lock_key)
            self.assertGreater(ttl, REHASH_LOCK_TTL)
            self.assertLessEqual(ttl, REHASH_LOCK_HANDOFF_TTL)
            current = redis_client.get(lock_key)
            if isinstance(current, bytes):
                current = current.decode()
            self.assertEqual(current, token)
        finally:
            release_task_lock("refresh_single_m3u_account", plain_account.id)


class HashKeySaveLockGateTests(TestCase):
    """Saving a changed hash_key must acquire the refresh lock first and
    fail closed (no DB write) when that account is refreshing.
    """

    def setUp(self):
        _set_global_hash_key("name,url")
        self.client = APIClient()
        self.admin = User.objects.create_user(
            username="hashkey_admin", password="pw", user_level=10
        )
        self.client.force_authenticate(user=self.admin)
        self.account = M3UAccount.objects.create(
            name="Gate Account", is_active=True
        )

    def test_hash_key_change_is_rejected_while_account_is_refreshing(self):
        self.assertTrue(
            acquire_task_lock("refresh_single_m3u_account", self.account.id)
        )
        try:
            with patch("apps.m3u.api_views.rehash_streams.delay") as mock_delay:
                response = self.client.patch(
                    f"/api/m3u/accounts/{self.account.id}/",
                    {"hash_key": "tvg_id"},
                    format="json",
                )

            self.assertEqual(response.status_code, 409)
            mock_delay.assert_not_called()
            self.account.refresh_from_db()
            self.assertNotIn("hash_key", self.account.custom_properties or {})
        finally:
            release_task_lock("refresh_single_m3u_account", self.account.id)

    def test_unrelated_edit_does_not_require_the_rehash_lock(self):
        self.assertTrue(
            acquire_task_lock("refresh_single_m3u_account", self.account.id)
        )
        try:
            response = self.client.patch(
                f"/api/m3u/accounts/{self.account.id}/",
                {"name": "Renamed Gate Account"},
                format="json",
            )

            self.assertEqual(response.status_code, 200)
            self.account.refresh_from_db()
            self.assertEqual(self.account.name, "Renamed Gate Account")
        finally:
            release_task_lock("refresh_single_m3u_account", self.account.id)

    def test_hash_key_change_queues_rehash_with_preacquired_locks(self):
        def fake_delay(*args, **kwargs):
            # Simulate the Celery task releasing the locks it was handed.
            for aid in kwargs.get("preacquired_lock_ids") or []:
                release_task_lock("refresh_single_m3u_account", aid)

        with patch(
            "apps.m3u.api_views.rehash_streams.delay", side_effect=fake_delay
        ) as mock_delay:
            response = self.client.patch(
                f"/api/m3u/accounts/{self.account.id}/",
                {"hash_key": "tvg_id,group"},
                format="json",
            )

        self.assertEqual(response.status_code, 200)
        self.account.refresh_from_db()
        self.assertEqual(
            self.account.custom_properties.get("hash_key"), "tvg_id,group"
        )
        mock_delay.assert_called_once()
        args, kwargs = mock_delay.call_args
        self.assertEqual(args[0], ["tvg_id", "group"])
        self.assertEqual(kwargs["account_id"], self.account.id)
        self.assertTrue(kwargs["locks_preacquired"])
        self.assertEqual(kwargs["preacquired_lock_ids"], [self.account.id])
        self.assertTrue(kwargs["preacquired_lock_token"])
        self.assertFalse(
            is_task_lock_held("refresh_single_m3u_account", self.account.id)
        )

    def test_reorder_only_hash_key_does_not_queue_rehash(self):
        self.account.custom_properties = {"hash_key": "name,url"}
        self.account.save(update_fields=["custom_properties"])

        with patch("apps.m3u.api_views.rehash_streams.delay") as mock_delay:
            response = self.client.patch(
                f"/api/m3u/accounts/{self.account.id}/",
                {"hash_key": "url,name"},
                format="json",
            )

        self.assertEqual(response.status_code, 200)
        mock_delay.assert_not_called()
        self.account.refresh_from_db()
        # Serializer still normalizes order from the typed field write.
        self.assertEqual(
            self.account.custom_properties.get("hash_key"), "url,name"
        )

    def test_custom_properties_hash_key_does_not_bypass_lock_gate(self):
        self.assertTrue(
            acquire_task_lock("refresh_single_m3u_account", self.account.id)
        )
        try:
            with patch("apps.m3u.api_views.rehash_streams.delay") as mock_delay:
                response = self.client.patch(
                    f"/api/m3u/accounts/{self.account.id}/",
                    {"custom_properties": {"hash_key": "tvg_id"}},
                    format="json",
                )

            self.assertEqual(response.status_code, 200)
            mock_delay.assert_not_called()
            self.account.refresh_from_db()
            self.assertNotIn("hash_key", self.account.custom_properties or {})
        finally:
            release_task_lock("refresh_single_m3u_account", self.account.id)

    def test_activate_with_hash_key_change_requires_lock(self):
        inactive = M3UAccount.objects.create(
            name="Inactive Gate Account", is_active=False
        )
        self.assertTrue(
            acquire_task_lock("refresh_single_m3u_account", inactive.id)
        )
        try:
            with patch("apps.m3u.api_views.rehash_streams.delay") as mock_delay:
                response = self.client.patch(
                    f"/api/m3u/accounts/{inactive.id}/",
                    {"is_active": True, "hash_key": "tvg_id"},
                    format="json",
                )

            self.assertEqual(response.status_code, 409)
            mock_delay.assert_not_called()
            inactive.refresh_from_db()
            self.assertFalse(inactive.is_active)
            self.assertNotIn("hash_key", inactive.custom_properties or {})
        finally:
            release_task_lock("refresh_single_m3u_account", inactive.id)

    def test_inactive_hash_key_change_is_rejected_while_lock_held(self):
        inactive = M3UAccount.objects.create(
            name="Inactive Rehash Account", is_active=False
        )
        self.assertTrue(
            acquire_task_lock("refresh_single_m3u_account", inactive.id)
        )
        try:
            with patch("apps.m3u.api_views.rehash_streams.delay") as mock_delay:
                response = self.client.patch(
                    f"/api/m3u/accounts/{inactive.id}/",
                    {"hash_key": "tvg_id"},
                    format="json",
                )

            self.assertEqual(response.status_code, 409)
            mock_delay.assert_not_called()
            inactive.refresh_from_db()
            self.assertNotIn("hash_key", inactive.custom_properties or {})
        finally:
            release_task_lock("refresh_single_m3u_account", inactive.id)

    def test_inactive_hash_key_change_acquires_lock_and_queues_rehash(self):
        inactive = M3UAccount.objects.create(
            name="Inactive Rehash Account 2", is_active=False
        )

        def fake_delay(*args, **kwargs):
            for aid in kwargs.get("preacquired_lock_ids") or []:
                release_task_lock("refresh_single_m3u_account", aid)

        with patch(
            "apps.m3u.api_views.rehash_streams.delay", side_effect=fake_delay
        ) as mock_delay:
            response = self.client.patch(
                f"/api/m3u/accounts/{inactive.id}/",
                {"hash_key": "tvg_id"},
                format="json",
            )

        self.assertEqual(response.status_code, 200)
        mock_delay.assert_called_once()
        args, kwargs = mock_delay.call_args
        self.assertEqual(kwargs["account_id"], inactive.id)
        self.assertEqual(kwargs["preacquired_lock_ids"], [inactive.id])
        self.assertTrue(kwargs["locks_preacquired"])
        self.assertTrue(kwargs["preacquired_lock_token"])
        inactive.refresh_from_db()
        self.assertEqual(inactive.custom_properties.get("hash_key"), "tvg_id")
        self.assertFalse(
            is_task_lock_held("refresh_single_m3u_account", inactive.id)
        )

    def test_deactivate_with_hash_key_change_requires_lock(self):
        self.assertTrue(
            acquire_task_lock("refresh_single_m3u_account", self.account.id)
        )
        try:
            with patch("apps.m3u.api_views.rehash_streams.delay") as mock_delay:
                response = self.client.patch(
                    f"/api/m3u/accounts/{self.account.id}/",
                    {"is_active": False, "hash_key": "tvg_id"},
                    format="json",
                )

            self.assertEqual(response.status_code, 409)
            mock_delay.assert_not_called()
            self.account.refresh_from_db()
            self.assertTrue(self.account.is_active)
            self.assertNotIn("hash_key", self.account.custom_properties or {})
        finally:
            release_task_lock("refresh_single_m3u_account", self.account.id)


class GlobalHashKeySavePathTests(TestCase):
    """CoreSettings stream-settings save must pre-acquire locks and queue
    rehash the same way as the per-account override path.
    """

    def setUp(self):
        _set_global_hash_key("name,url")
        self.client = APIClient()
        self.admin = User.objects.create_user(
            username="global_hashkey_admin", password="pw", user_level=10
        )
        self.client.force_authenticate(user=self.admin)
        self.settings = CoreSettings.objects.get(key=STREAM_SETTINGS_KEY)
        self.plain = M3UAccount.objects.create(
            name="Global Plain Account", is_active=True
        )
        self.inactive = M3UAccount.objects.create(
            name="Global Inactive Account", is_active=False
        )
        self.override = M3UAccount.objects.create(
            name="Global Override Account",
            is_active=True,
            custom_properties={"hash_key": "tvg_id"},
        )

    def _patch_hash_key(self, value):
        new_value = dict(self.settings.value)
        new_value["m3u_hash_key"] = value
        return self.client.patch(
            f"/api/core/settings/{self.settings.id}/",
            {"value": new_value},
            format="json",
        )

    def test_global_hash_key_change_queues_rehash_with_preacquired_locks(self):
        def fake_delay(*args, **kwargs):
            for aid in kwargs.get("preacquired_lock_ids") or []:
                release_task_lock("refresh_single_m3u_account", aid)

        with patch(
            "core.api_views.rehash_streams.delay", side_effect=fake_delay
        ) as mock_delay:
            response = self._patch_hash_key("name,url,group")

        self.assertEqual(response.status_code, 200)
        self.settings.refresh_from_db()
        self.assertEqual(self.settings.value.get("m3u_hash_key"), "name,url,group")
        mock_delay.assert_called_once()
        args, kwargs = mock_delay.call_args
        self.assertEqual(args[0], ["name", "url", "group"])
        self.assertNotIn("account_id", kwargs)
        self.assertTrue(kwargs["locks_preacquired"])
        self.assertIn(self.plain.id, kwargs["preacquired_lock_ids"])
        self.assertIn(self.inactive.id, kwargs["preacquired_lock_ids"])
        self.assertNotIn(self.override.id, kwargs["preacquired_lock_ids"])
        self.assertTrue(kwargs["preacquired_lock_token"])
        self.assertFalse(
            is_task_lock_held("refresh_single_m3u_account", self.plain.id)
        )
        self.assertFalse(
            is_task_lock_held("refresh_single_m3u_account", self.inactive.id)
        )
        self.assertFalse(
            is_task_lock_held("refresh_single_m3u_account", self.override.id)
        )

    def test_global_hash_key_change_is_rejected_while_plain_account_refreshing(self):
        self.assertTrue(
            acquire_task_lock("refresh_single_m3u_account", self.plain.id)
        )
        try:
            with patch("core.api_views.rehash_streams.delay") as mock_delay:
                response = self._patch_hash_key("tvg_id")

            self.assertEqual(response.status_code, 409)
            mock_delay.assert_not_called()
            self.settings.refresh_from_db()
            self.assertEqual(self.settings.value.get("m3u_hash_key"), "name,url")
        finally:
            release_task_lock("refresh_single_m3u_account", self.plain.id)

    def test_global_hash_key_change_is_rejected_while_inactive_account_lock_held(self):
        self.assertTrue(
            acquire_task_lock("refresh_single_m3u_account", self.inactive.id)
        )
        try:
            with patch("core.api_views.rehash_streams.delay") as mock_delay:
                response = self._patch_hash_key("group")

            self.assertEqual(response.status_code, 409)
            mock_delay.assert_not_called()
            self.settings.refresh_from_db()
            self.assertEqual(self.settings.value.get("m3u_hash_key"), "name,url")
        finally:
            release_task_lock("refresh_single_m3u_account", self.inactive.id)

    def test_global_reorder_only_does_not_queue_rehash(self):
        with patch("core.api_views.rehash_streams.delay") as mock_delay:
            response = self._patch_hash_key("url,name")

        self.assertEqual(response.status_code, 200)
        mock_delay.assert_not_called()
        self.settings.refresh_from_db()
        self.assertEqual(self.settings.value.get("m3u_hash_key"), "url,name")

    def test_rehash_endpoint_preacquires_locks(self):
        class _Task:
            id = "rehash-task-id"

        def fake_delay(*args, **kwargs):
            for aid in kwargs.get("preacquired_lock_ids") or []:
                release_task_lock("refresh_single_m3u_account", aid)
            return _Task()

        with patch(
            "core.api_views.rehash_streams.delay", side_effect=fake_delay
        ) as mock_delay:
            response = self.client.post("/api/core/rehash-streams/")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data.get("success"))
        self.assertEqual(response.data.get("task_id"), "rehash-task-id")
        mock_delay.assert_called_once()
        args, kwargs = mock_delay.call_args
        self.assertEqual(args[0], ["name", "url"])
        self.assertTrue(kwargs["locks_preacquired"])
        self.assertIn(self.plain.id, kwargs["preacquired_lock_ids"])
        self.assertIn(self.inactive.id, kwargs["preacquired_lock_ids"])
        self.assertNotIn(self.override.id, kwargs["preacquired_lock_ids"])
        self.assertTrue(kwargs["preacquired_lock_token"])


class RehashConflictAndConcurrencyTests(TestCase):
    """Exercise real rehash merge and lock contention paths.

    These call ``rehash_streams`` and the Redis lock helpers directly with
    real Stream/Channel rows, not mocked merge logic.
    """

    def setUp(self):
        _set_global_hash_key("name,url")
        self.client = APIClient()
        self.admin = User.objects.create_user(
            username="rehash_conflict_admin", password="pw", user_level=10
        )
        self.client.force_authenticate(user=self.admin)
        self.account = M3UAccount.objects.create(
            name="Conflict Rehash Account", is_active=True
        )

    def _stream(self, name, url, keys, tvg_id=None):
        stream_hash = Stream.generate_hash_key(
            name, url, tvg_id, keys, m3u_id=self.account.id
        )
        return Stream.objects.create(
            name=name,
            url=url,
            tvg_id=tvg_id,
            m3u_account=self.account,
            stream_hash=stream_hash,
        )

    def test_rehash_merges_duplicate_hashes_and_keeps_channel_stream(self):
        # Same name, different URLs: distinct under name+url, collide under name.
        kept = self._stream("Dup Name", "http://keep", ["name", "url"])
        dropped = self._stream("Dup Name", "http://drop", ["name", "url"])
        channel = Channel.objects.create(name="Dup Channel", channel_number=101)
        ChannelStream.objects.create(channel=channel, stream=kept, order=0)

        result = rehash_streams(["name"], account_id=self.account.id)

        self.assertIn("Successfully rehashed", result)
        self.assertTrue(Stream.objects.filter(id=kept.id).exists())
        self.assertFalse(Stream.objects.filter(id=dropped.id).exists())
        kept.refresh_from_db()
        self.assertEqual(
            kept.stream_hash,
            Stream.generate_hash_key(
                "Dup Name", "http://keep", None, ["name"], m3u_id=self.account.id
            ),
        )
        self.assertEqual(
            ChannelStream.objects.filter(channel=channel).count(), 1
        )
        self.assertEqual(
            ChannelStream.objects.get(channel=channel).stream_id, kept.id
        )

    def test_rehash_moves_channel_link_when_orphan_is_canonical_first(self):
        # Process order is by stream id. Create the orphan first so it is the
        # first hash owner; the channel-linked stream must still win the merge.
        orphan = self._stream("Dup Name 2", "http://orphan", ["name", "url"])
        linked = self._stream("Dup Name 2", "http://linked", ["name", "url"])
        channel = Channel.objects.create(name="Dup Channel 2", channel_number=102)
        ChannelStream.objects.create(channel=channel, stream=linked, order=0)

        result = rehash_streams(["name"], account_id=self.account.id)

        self.assertIn("Successfully rehashed", result)
        self.assertTrue(Stream.objects.filter(id=linked.id).exists())
        self.assertFalse(Stream.objects.filter(id=orphan.id).exists())
        self.assertEqual(
            ChannelStream.objects.get(channel=channel).stream_id, linked.id
        )

    def test_second_try_acquire_is_blocked_while_first_holds_locks(self):
        first, blocked, token = try_acquire_rehash_locks(account_id=self.account.id)
        self.assertEqual(blocked, [])
        self.assertEqual(first, [self.account.id])
        try:
            second, blocked2, token2 = try_acquire_rehash_locks(
                account_id=self.account.id
            )
            self.assertEqual(second, [])
            self.assertEqual(blocked2, [self.account.id])
            self.assertNotEqual(token, token2)
            self.assertTrue(
                is_task_lock_held("refresh_single_m3u_account", self.account.id)
            )
        finally:
            release_rehash_locks(first, token)

    def test_rehash_blocked_while_refresh_lock_is_held(self):
        self.assertTrue(
            acquire_task_lock("refresh_single_m3u_account", self.account.id)
        )
        try:
            result = rehash_streams(["name", "url"], account_id=self.account.id)
            self.assertIn("blocked", result.lower())
            self.assertTrue(
                is_task_lock_held("refresh_single_m3u_account", self.account.id)
            )
        finally:
            release_task_lock("refresh_single_m3u_account", self.account.id)

    def test_hash_key_save_409_while_refresh_then_succeeds_after_release(self):
        self.assertTrue(
            acquire_task_lock("refresh_single_m3u_account", self.account.id)
        )
        try:
            with patch("apps.m3u.api_views.rehash_streams.delay") as mock_delay:
                blocked = self.client.patch(
                    f"/api/m3u/accounts/{self.account.id}/",
                    {"hash_key": "tvg_id"},
                    format="json",
                )
            self.assertEqual(blocked.status_code, 409)
            mock_delay.assert_not_called()
            self.account.refresh_from_db()
            self.assertNotIn("hash_key", self.account.custom_properties or {})
        finally:
            release_task_lock("refresh_single_m3u_account", self.account.id)

        def fake_delay(*args, **kwargs):
            for aid in kwargs.get("preacquired_lock_ids") or []:
                release_task_lock("refresh_single_m3u_account", aid)

        with patch(
            "apps.m3u.api_views.rehash_streams.delay", side_effect=fake_delay
        ) as mock_delay:
            ok = self.client.patch(
                f"/api/m3u/accounts/{self.account.id}/",
                {"hash_key": "tvg_id"},
                format="json",
            )
        self.assertEqual(ok.status_code, 200)
        mock_delay.assert_called_once()
        self.account.refresh_from_db()
        self.assertEqual(self.account.custom_properties.get("hash_key"), "tvg_id")

    def test_two_preacquired_rehashes_second_confirm_blocks(self):
        # Simulate two saves that both thought they could proceed: the first
        # task still owns the token; the second confirm must abort.
        first_ids, blocked, token1 = try_acquire_rehash_locks(
            account_id=self.account.id
        )
        self.assertEqual(blocked, [])
        try:
            owned, stolen = confirm_preacquired_rehash_locks(first_ids, token1)
            self.assertEqual(owned, [self.account.id])
            self.assertEqual(stolen, [])

            # A second acquire fails while the first token still owns the key.
            second_ids, blocked2, token2 = try_acquire_rehash_locks(
                account_id=self.account.id
            )
            self.assertEqual(second_ids, [])
            self.assertEqual(blocked2, [self.account.id])

            # Confirm with a different token against the held key blocks.
            owned2, blocked3 = confirm_preacquired_rehash_locks(
                [self.account.id], token2
            )
            self.assertEqual(owned2, [])
            self.assertEqual(blocked3, [self.account.id])
            self.assertTrue(
                is_task_lock_held("refresh_single_m3u_account", self.account.id)
            )
        finally:
            release_rehash_locks(first_ids, token1)

    def test_end_to_end_hash_key_change_rehashes_and_merges(self):
        kept = self._stream("Live Dup", "http://a", ["name", "url"])
        dropped = self._stream("Live Dup", "http://b", ["name", "url"])
        channel = Channel.objects.create(name="Live Dup Channel", channel_number=103)
        ChannelStream.objects.create(channel=channel, stream=kept, order=0)

        # Real save path acquires locks, then we run the queued rehash body
        # with those preacquired locks (Celery is not eager in tests).
        captured = {}

        def capture_delay(*args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs

        with patch(
            "apps.m3u.api_views.rehash_streams.delay", side_effect=capture_delay
        ):
            response = self.client.patch(
                f"/api/m3u/accounts/{self.account.id}/",
                {"hash_key": "name"},
                format="json",
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(captured)
        result = rehash_streams(
            captured["args"][0],
            account_id=captured["kwargs"]["account_id"],
            locks_preacquired=captured["kwargs"]["locks_preacquired"],
            preacquired_lock_ids=captured["kwargs"]["preacquired_lock_ids"],
            preacquired_lock_token=captured["kwargs"]["preacquired_lock_token"],
        )

        self.assertIn("Successfully rehashed", result)
        self.assertTrue(Stream.objects.filter(id=kept.id).exists())
        self.assertFalse(Stream.objects.filter(id=dropped.id).exists())
        self.assertEqual(
            ChannelStream.objects.get(channel=channel).stream_id, kept.id
        )
        self.assertFalse(
            is_task_lock_held("refresh_single_m3u_account", self.account.id)
        )
