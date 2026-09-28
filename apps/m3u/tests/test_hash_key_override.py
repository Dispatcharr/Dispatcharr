"""Tests for the per-M3U-account hash key override.

Covers M3UAccount.get_effective_hash_keys() (falls back to the global
CoreSettings default when no override is set), the serializer field that
exposes/persists it under custom_properties["hash_key"], and the scoping
of the unscoped (global-key-change) rehash_streams run so it never locks
or rewrites streams for accounts that have their own override.
"""
from django.test import TestCase

from apps.channels.models import Stream
from apps.m3u.models import M3UAccount
from apps.m3u.serializers import M3UAccountSerializer
from core.models import CoreSettings, STREAM_SETTINGS_KEY
from core.tasks import rehash_streams
from core.utils import acquire_task_lock, release_task_lock


def _set_global_hash_key(value):
    """Set the global M3U Hash Key setting the same way the Settings page does."""
    CoreSettings._update_group(
        STREAM_SETTINGS_KEY, "Stream Settings", {"m3u_hash_key": value}
    )


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
            updated.get_effective_hash_keys(), CoreSettings.get_m3u_hash_key().split(",")
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


class RehashStreamsScopingTests(TestCase):
    """Covers the reviewer-requested scoping of the unscoped rehash run:
    accounts with their own hash_key override are skipped entirely (not
    locked, not loaded, not rewritten), only active accounts without an
    override are locked, and streams with no account (or on an inactive,
    non-overridden account) are still rehashed.
    """

    def setUp(self):
        _set_global_hash_key("name,url")

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
        new_global_keys = CoreSettings.get_m3u_hash_key().split(",")

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
        new_keys = CoreSettings.get_m3u_hash_key().split(",")

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
        new_keys = CoreSettings.get_m3u_hash_key().split(",")

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
            new_keys = CoreSettings.get_m3u_hash_key().split(",")

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
