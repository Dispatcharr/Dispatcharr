"""Tests for the bulk "set channel TVG-IDs / names from EPG" tasks."""
from django.test import TestCase

from apps.channels.models import Channel
from apps.channels.tasks import (
    set_channels_names_from_epg,
    set_channels_tvg_ids_from_epg,
)
from apps.epg.models import EPGData, EPGSource


class SetChannelsFromEpgTests(TestCase):
    def setUp(self):
        self.source = EPGSource.objects.create(
            name="XML EPG",
            source_type="xmltv",
            url="http://example.com/epg.xml",
        )
        # Creating a dummy source auto-creates a shared EPGData row
        # (apps/epg/signals.py: create_dummy_epg_data) whose tvg_id and name
        # describe the source, not any one channel.
        dummy_source = EPGSource.objects.create(name="US Sports", source_type="dummy")
        self.shared_epg_data = EPGData.objects.get(epg_source=dummy_source)

    def test_copies_tvg_id_from_a_real_epg_source(self):
        epg_data = EPGData.objects.create(
            tvg_id="ch.one", name="Channel One", epg_source=self.source
        )
        channel = Channel.objects.create(
            channel_number=1, name="Channel One", tvg_id="stale.id", epg_data=epg_data
        )

        result = set_channels_tvg_ids_from_epg([channel.id])

        channel.refresh_from_db()
        self.assertEqual(channel.tvg_id, "ch.one")
        self.assertEqual(result["updated_count"], 1)
        self.assertEqual(result["errors"], [])

    def test_copies_tvg_id_when_epg_data_has_no_source(self):
        epg_data = EPGData.objects.create(
            tvg_id="orphan.id", name="Orphan", epg_source=None
        )
        channel = Channel.objects.create(
            channel_number=2, name="Orphan", tvg_id="stale.id", epg_data=epg_data
        )

        result = set_channels_tvg_ids_from_epg([channel.id])

        channel.refresh_from_db()
        self.assertEqual(channel.tvg_id, "orphan.id")
        self.assertEqual(result["updated_count"], 1)
        self.assertEqual(result["errors"], [])

    def test_leaves_dummy_epg_channels_tvg_ids_alone(self):
        nba = Channel.objects.create(
            channel_number=100,
            name="NBA",
            tvg_id="nba.us",
            epg_data=self.shared_epg_data,
        )
        mlb = Channel.objects.create(
            channel_number=101,
            name="MLB",
            tvg_id="mlb.us",
            epg_data=self.shared_epg_data,
        )

        result = set_channels_tvg_ids_from_epg([nba.id, mlb.id])

        nba.refresh_from_db()
        mlb.refresh_from_db()
        self.assertEqual(nba.tvg_id, "nba.us")
        self.assertEqual(mlb.tvg_id, "mlb.us")
        self.assertEqual(result["updated_count"], 0)
        self.assertEqual(result["errors"], [])

    def test_copies_name_from_a_real_epg_source(self):
        epg_data = EPGData.objects.create(
            tvg_id="ch.two", name="Channel Two", epg_source=self.source
        )
        channel = Channel.objects.create(
            channel_number=3, name="Stale Name", epg_data=epg_data
        )

        result = set_channels_names_from_epg([channel.id])

        channel.refresh_from_db()
        self.assertEqual(channel.name, "Channel Two")
        self.assertEqual(result["updated_count"], 1)
        self.assertEqual(result["errors"], [])

    def test_leaves_dummy_epg_channel_names_alone(self):
        nba = Channel.objects.create(
            channel_number=100, name="NBA", epg_data=self.shared_epg_data
        )
        mlb = Channel.objects.create(
            channel_number=101, name="MLB", epg_data=self.shared_epg_data
        )

        result = set_channels_names_from_epg([nba.id, mlb.id])

        nba.refresh_from_db()
        mlb.refresh_from_db()
        self.assertEqual(nba.name, "NBA")
        self.assertEqual(mlb.name, "MLB")
        self.assertEqual(result["updated_count"], 0)
        self.assertEqual(result["errors"], [])
