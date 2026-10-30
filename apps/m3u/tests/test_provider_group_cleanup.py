"""Per-provider-group cleanup preserves ownership and existing policies."""

import importlib
from types import SimpleNamespace

from django.apps import apps
from django.db import connection
from django.test import TestCase
from django.utils import timezone

from apps.channels.models import Channel, ChannelOverride, ChannelStream
from apps.m3u.tasks import cleanup_stale_group_relationships
from apps.m3u.tests.test_sync_correctness import (
    _attach_group_to_account,
    _make_account,
    _make_group,
    _make_stream,
    _sync,
)


class ProviderGroupCleanupTests(TestCase):
    def setUp(self):
        self.account = _make_account()

    def membership(self, name, mode="always"):
        return _attach_group_to_account(
            self.account,
            _make_group(name),
            custom_properties={"orphan_channel_cleanup": mode},
        )

    def channel(self, membership, name, **values):
        return Channel.objects.create(
            name=name,
            channel_number=None,
            channel_group=membership.channel_group,
            auto_created=True,
            auto_created_by=self.account,
            auto_created_from=membership,
            **values,
        )

    def test_cleanup_modes_are_independent_within_one_account(self):
        always = self.channel(self.membership("Always"), "Remove")
        never = self.channel(self.membership("Never", "never"), "Keep")
        customized_group = self.membership("Customized", "preserve_customized")
        plain = self.channel(customized_group, "Plain")
        customized = self.channel(customized_group, "Custom")
        ChannelOverride.objects.create(channel=customized, name="User name")
        result = _sync(self.account)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["channels_deleted"], 2)
        self.assertFalse(Channel.objects.filter(id__in=[always.id, plain.id]).exists())
        self.assertEqual(
            set(Channel.objects.values_list("id", flat=True)), {never.id, customized.id}
        )

    def test_manual_and_hidden_channels_survive_every_cleanup_mode(self):
        manual = Channel.objects.create(name="Manual", channel_number=999)
        hidden = self.channel(
            self.membership("Hidden"), "Hidden", hidden_from_output=True
        )
        _sync(self.account)
        self.assertTrue(Channel.objects.filter(id=manual.id).exists())
        self.assertTrue(Channel.objects.filter(id=hidden.id).exists())

    def test_new_channel_keeps_creating_group_after_source_disappears(self):
        membership = self.membership("Events", "never")
        stream = _make_stream(self.account, membership.channel_group)
        _sync(self.account)
        channel = Channel.objects.get(auto_created=True)
        self.assertEqual(channel.auto_created_from_id, membership.id)
        stream.delete()
        _sync(self.account)
        self.assertTrue(Channel.objects.filter(id=channel.id).exists())

    def test_backup_group_does_not_take_ownership_or_delete_retained_channel(self):
        owner = self.membership("Owner", "never")
        backup = self.membership("Backup", "always")
        stream = _make_stream(self.account, backup.channel_group, "Backup stream")
        channel = self.channel(owner, "Retained channel")
        ChannelStream.objects.create(channel=channel, stream=stream)
        _sync(self.account)
        channel.refresh_from_db()
        self.assertEqual(channel.auto_created_from_id, owner.id)
        stream.last_seen = timezone.now() - timezone.timedelta(days=1)
        stream.save(update_fields=["last_seen"])
        _sync(self.account)
        self.assertTrue(Channel.objects.filter(id=channel.id).exists())

    def test_ambiguous_legacy_channels_keep_account_fallback(self):
        self.account.custom_properties = {"orphan_channel_cleanup": "never"}
        self.account.save()
        first = self.membership("First")
        second = self.membership("Second")
        channel = Channel.objects.create(
            name="Legacy", auto_created=True, auto_created_by=self.account
        )
        for membership in (first, second):
            ChannelStream.objects.create(
                channel=channel,
                stream=_make_stream(
                    self.account,
                    membership.channel_group,
                    membership.channel_group.name,
                ),
            )
        _sync(self.account)
        channel.refresh_from_db()
        self.assertIsNone(channel.auto_created_from_id)

    def test_stale_memberships_preserve_cleanup_policy_for_retained_channels(self):
        for mode in ("never", "preserve_customized", "always"):
            membership = self.membership(mode, mode)
            channel = self.channel(
                membership, mode, hidden_from_output=mode == "always"
            )
            if mode == "preserve_customized":
                ChannelOverride.objects.create(channel=channel, name="Custom")
            membership.last_seen = timezone.now() - timezone.timedelta(days=30)
            membership.save(update_fields=["last_seen"])
        self.assertEqual(
            cleanup_stale_group_relationships(self.account, timezone.now()), 0
        )
        _sync(self.account)
        self.assertEqual(Channel.objects.count(), 3)

    def test_unprotected_stale_memberships_are_still_removed(self):
        membership = self.membership("Old", "preserve_customized")
        self.channel(membership, "Plain")
        membership.last_seen = timezone.now() - timezone.timedelta(days=30)
        membership.save(update_fields=["last_seen"])
        self.assertEqual(
            cleanup_stale_group_relationships(self.account, timezone.now()), 1
        )
        _sync(self.account)
        self.assertFalse(Channel.objects.exists())

    def test_backfill_preserves_account_mode_and_existing_group_overrides(self):
        self.account.custom_properties = {"orphan_channel_cleanup": "never"}
        self.account.save()
        inherited = _attach_group_to_account(self.account, _make_group("Inherited"))
        explicit = self.membership("Explicit", "preserve_customized")
        stream = _make_stream(self.account, inherited.channel_group)
        channel = Channel.objects.create(
            name="Legacy", auto_created=True, auto_created_by=self.account
        )
        ChannelStream.objects.create(channel=channel, stream=stream)
        migration = importlib.import_module(
            "apps.channels.migrations.0040_channel_auto_created_from"
        )
        migration.backfill_group_cleanup(apps, SimpleNamespace(connection=connection))
        inherited.refresh_from_db()
        explicit.refresh_from_db()
        channel.refresh_from_db()
        self.assertEqual(inherited.custom_properties["orphan_channel_cleanup"], "never")
        self.assertEqual(
            explicit.custom_properties["orphan_channel_cleanup"], "preserve_customized"
        )
        self.assertEqual(channel.auto_created_from_id, inherited.id)

    def test_backfill_ignores_other_provider_backup_streams(self):
        owner = self.membership("Owner")
        other = _make_account("Other")
        foreign_group = _make_group("Foreign")
        channel = Channel.objects.create(
            name="Legacy", auto_created=True, auto_created_by=self.account
        )
        ChannelStream.objects.create(
            channel=channel, stream=_make_stream(other, foreign_group, "Foreign")
        )
        ChannelStream.objects.create(
            channel=channel,
            stream=_make_stream(self.account, owner.channel_group, "Owner"),
        )
        migration = importlib.import_module(
            "apps.channels.migrations.0040_channel_auto_created_from"
        )
        migration.backfill_group_cleanup(apps, SimpleNamespace(connection=connection))
        channel.refresh_from_db()
        self.assertEqual(channel.auto_created_from_id, owner.id)
