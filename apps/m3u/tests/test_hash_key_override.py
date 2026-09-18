"""Tests for the per-M3U-account hash key override.

Covers M3UAccount.get_effective_hash_keys() (falls back to the global
CoreSettings default when no override is set) and the serializer field
that exposes it.
"""
from django.test import TestCase

from apps.m3u.models import M3UAccount
from apps.m3u.serializers import M3UAccountSerializer
from core.models import CoreSettings, STREAM_SETTINGS_KEY


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
        self.assertIsNone(account.hash_key)
        self.assertEqual(account.get_effective_hash_keys(), ["name", "url"])

    def test_falls_back_to_global_default_when_override_is_empty_string(self):
        account = M3UAccount.objects.create(
            name="Empty Override Account", hash_key=""
        )
        self.assertEqual(account.get_effective_hash_keys(), ["name", "url"])

    def test_uses_account_override_when_set(self):
        account = M3UAccount.objects.create(
            name="Overridden Account", hash_key="tvg_id,group"
        )
        self.assertEqual(account.get_effective_hash_keys(), ["tvg_id", "group"])

    def test_override_drops_empty_entries_from_trailing_commas(self):
        account = M3UAccount.objects.create(
            name="Trailing Comma Account", hash_key="name,,tvg_id,"
        )
        self.assertEqual(account.get_effective_hash_keys(), ["name", "tvg_id"])

    def test_other_accounts_are_unaffected_by_one_accounts_override(self):
        overridden = M3UAccount.objects.create(
            name="Overridden Account 2", hash_key="name,m3u_id"
        )
        plain = M3UAccount.objects.create(name="Plain Account 2")

        self.assertEqual(overridden.get_effective_hash_keys(), ["name", "m3u_id"])
        self.assertEqual(plain.get_effective_hash_keys(), ["name", "url"])

    def test_changing_the_global_default_does_not_affect_an_override(self):
        overridden = M3UAccount.objects.create(
            name="Overridden Account 3", hash_key="name,m3u_id,group"
        )
        plain = M3UAccount.objects.create(name="Plain Account 3")

        _set_global_hash_key("name,tvg_id")

        self.assertEqual(
            overridden.get_effective_hash_keys(), ["name", "m3u_id", "group"]
        )
        self.assertEqual(plain.get_effective_hash_keys(), ["name", "tvg_id"])


class M3UAccountSerializerHashKeyTests(TestCase):
    def test_hash_key_field_is_exposed(self):
        account = M3UAccount.objects.create(
            name="Serialized Account", hash_key="name,tvg_id"
        )
        data = M3UAccountSerializer(account).data
        self.assertEqual(data["hash_key"], "name,tvg_id")

    def test_hash_key_defaults_to_null_when_not_set(self):
        account = M3UAccount.objects.create(name="Serialized Account 2")
        data = M3UAccountSerializer(account).data
        self.assertIsNone(data["hash_key"])

    def test_hash_key_accepts_null_to_clear_an_override(self):
        account = M3UAccount.objects.create(
            name="Serialized Account 3", hash_key="name,tvg_id"
        )
        serializer = M3UAccountSerializer(
            account, data={"hash_key": None}, partial=True
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        updated = serializer.save()
        self.assertIsNone(updated.hash_key)
        self.assertEqual(
            updated.get_effective_hash_keys(), CoreSettings.get_m3u_hash_key().split(",")
        )
