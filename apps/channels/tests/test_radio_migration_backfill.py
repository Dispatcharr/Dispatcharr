"""Direct tests for migration 0039's radio backfill functions.

Migration modules aren't importable with a normal dotted path (the filename
starts with a digit), so importlib loads it directly. The backfill functions
only need ``schema_editor.connection``, so a tiny stand-in is enough to run
them against the real test database without going through Django's full
migration executor.
"""

import importlib
from types import SimpleNamespace

from django.db import connection
from django.test import TestCase

from apps.channels.models import Channel, ChannelStream
from apps.channels.models import Stream
from apps.m3u.models import M3UAccount

_migration = importlib.import_module(
    "apps.channels.migrations.0039_add_radio_fields"
)
backfill_stream_radio = _migration.backfill_stream_radio
backfill_channel_radio = _migration.backfill_channel_radio

_fake_schema_editor = SimpleNamespace(connection=connection)


class BackfillStreamRadioTests(TestCase):
    def setUp(self):
        self.account = M3UAccount.objects.create(
            name="Backfill Test Account", server_url="http://example.com"
        )

    def _stream(self, **custom_properties):
        return Stream.objects.create(
            name="Test Stream",
            url="http://example.com/stream",
            m3u_account=self.account,
            custom_properties=custom_properties,
        )

    def test_marks_xc_radio_streams(self):
        stream = self._stream(stream_type="radio_streams")

        backfill_stream_radio(None, _fake_schema_editor)

        stream.refresh_from_db()
        self.assertTrue(stream.is_radio)

    def test_leaves_xc_live_streams_alone(self):
        stream = self._stream(stream_type="live")

        backfill_stream_radio(None, _fake_schema_editor)

        stream.refresh_from_db()
        self.assertFalse(stream.is_radio)

    def test_marks_standard_m3u_radio_attribute(self):
        stream = self._stream(radio="true")

        backfill_stream_radio(None, _fake_schema_editor)

        stream.refresh_from_db()
        self.assertTrue(stream.is_radio)

    def test_created_live_is_not_treated_as_radio(self):
        """Provider bookkeeping value, confirmed unrelated to radio content."""
        stream = self._stream(stream_type="created_live")

        backfill_stream_radio(None, _fake_schema_editor)

        stream.refresh_from_db()
        self.assertFalse(stream.is_radio)


class BackfillChannelRadioTests(TestCase):
    def setUp(self):
        self.active_account = M3UAccount.objects.create(
            name="Active Account", server_url="http://example.com", is_active=True
        )
        self.inactive_account = M3UAccount.objects.create(
            name="Inactive Account", server_url="http://example.org", is_active=False
        )

    def _channel_with_stream(self, account, is_radio):
        channel = Channel.objects.create(channel_number=1, name="Test Channel")
        stream = Stream.objects.create(
            name="Test Stream",
            url="http://example.com/stream",
            m3u_account=account,
            is_radio=is_radio,
        )
        ChannelStream.objects.create(channel=channel, stream=stream, order=0)
        return channel

    def test_rolls_up_radio_from_active_account_stream(self):
        channel = self._channel_with_stream(self.active_account, is_radio=True)

        backfill_channel_radio(None, _fake_schema_editor)

        channel.refresh_from_db()
        self.assertTrue(channel.is_radio)

    def test_does_not_roll_up_radio_from_inactive_account_stream(self):
        """A disabled account's stream must not flag the channel: disabled
        accounts aren't refreshed, so a wrong flag from one would never
        self-correct, unlike the runtime rollup this backfill must match."""
        channel = self._channel_with_stream(self.inactive_account, is_radio=True)

        backfill_channel_radio(None, _fake_schema_editor)

        channel.refresh_from_db()
        self.assertFalse(channel.is_radio)
