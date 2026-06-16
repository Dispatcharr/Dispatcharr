"""Tests for applying EPG auto-match results to channels."""
from unittest.mock import patch

from django.test import TestCase

from apps.channels.epg_matching import apply_matched_epg_to_channels
from apps.channels.models import Channel
from apps.epg.models import EPGData, EPGSource


class ApplyMatchedEpgToChannelsTests(TestCase):
    def setUp(self):
        self.source = EPGSource.objects.create(
            name="XML EPG",
            source_type="xmltv",
            url="http://example.com/epg.xml",
        )
        self.epg_one = EPGData.objects.create(
            tvg_id="ch.one",
            name="Channel One",
            epg_source=self.source,
        )
        self.epg_two = EPGData.objects.create(
            tvg_id="ch.two",
            name="Channel Two",
            epg_source=self.source,
        )
        self.channel = Channel.objects.create(
            channel_number=1,
            name="Channel One",
            tvg_id="ch.one",
            epg_data=self.epg_one,
        )

    @patch("apps.epg.tasks.parse_programs_for_tvg_id.delay")
    def test_skips_unchanged_assignment(self, mock_delay):
        changed = apply_matched_epg_to_channels(
            [{"id": self.channel.id, "epg_data_id": self.epg_one.id}]
        )

        self.assertEqual(changed, [])
        mock_delay.assert_not_called()
        self.channel.refresh_from_db()
        self.assertEqual(self.channel.epg_data_id, self.epg_one.id)

    @patch("apps.epg.tasks.parse_programs_for_tvg_id.delay")
    def test_updates_changed_assignment_and_dispatches_parse(self, mock_delay):
        changed = apply_matched_epg_to_channels(
            [{"id": self.channel.id, "epg_data_id": self.epg_two.id}]
        )

        self.assertEqual(
            changed,
            [{"channel_id": self.channel.id, "epg_data_id": self.epg_two.id}],
        )
        mock_delay.assert_called_once_with(self.epg_two.id)
        self.channel.refresh_from_db()
        self.assertEqual(self.channel.epg_data_id, self.epg_two.id)
