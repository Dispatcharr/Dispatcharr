"""Tests for the EPG grid endpoint's on-demand dummy program generation.

The grid returns real programmes plus dummy programmes generated per request for
channels that have no EPG data (standard dummy) or a dummy EPG source (custom
regex dummy).
"""

from datetime import datetime, timedelta, timezone as dt_timezone
from unittest import mock

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.channels.models import Channel, ChannelGroup, ChannelStream, ChannelOverride, Stream
from apps.epg.api_grid import custom_dummy_channels_queryset
from apps.epg.models import EPGData, EPGSource, ProgramData
from apps.m3u.models import M3UAccount
from apps.output.dummy_epg import resolve_channel_parse_name

User = get_user_model()

GRID_URL = "/api/epg/grid/"

NHL_PROPS = {
    "title_pattern": r"(?<league>.*)\s\d+:\s(?<team1>.*?)(?:\s+vs\s+)(?<team2>.*?)\s*@.*",
    "time_pattern": r"(?<hour>\d{1,2}):(?<minute>\d{2})\s*(?<ampm>AM|PM)",
    "timezone": "UTC",
    "program_duration": 180,
}

# Mid-day so evening fixture events are still ahead of the request clock.
FIXED_NOW = datetime(2026, 1, 15, 12, 0, tzinfo=dt_timezone.utc)


class EPGGridDummyProgramTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="griduser", password="testpass123"
        )
        self.user.user_level = 10
        self.user.save()
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

        self.group = ChannelGroup.objects.create(name="Grid Group")
        self.account = M3UAccount.objects.create(
            name="Grid Account", server_url="http://example.com", priority=1
        )

    def _make_stream(self, name, index):
        return Stream.objects.create(
            name=name,
            url=f"http://example.com/{index}.ts",
            m3u_account=self.account,
        )

    def _get_grid(self):
        with mock.patch.object(timezone, "now", return_value=FIXED_NOW):
            response = self.client.get(GRID_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        return response.data["data"]

    @staticmethod
    def _for_channel(programs, channel):
        return [p for p in programs if p["tvg_id"] == str(channel.uuid)]

    def _dummy_source(self, custom_properties):
        source = EPGSource.objects.create(
            name=f"Dummy {len(custom_properties)}",
            source_type="dummy",
            custom_properties=custom_properties,
        )
        return source, EPGData.objects.get(epg_source=source)

    def test_channel_without_epg_gets_standard_dummy_programs(self):
        channel = Channel.objects.create(
            channel_number=1.0, name="No EPG Channel", channel_group=self.group
        )

        programs = self._for_channel(self._get_grid(), channel)

        # 24h window in 4h blocks.
        self.assertEqual(len(programs), 6)
        for program in programs:
            self.assertEqual(program["title"], "No EPG Channel")
            self.assertTrue(program["id"].startswith("dummy-standard-"))
            self.assertEqual(program["epg"]["name"], "No EPG Channel")
            self.assertTrue(program["description"])
            self.assertIsNone(program["custom_properties"])
            self.assertFalse(program["is_new"])
            self.assertFalse(program["is_live"])

    def test_effective_name_override_used_for_standard_dummy(self):
        channel = Channel.objects.create(
            channel_number=2.0,
            name="Provider Name",
            channel_group=self.group,
            auto_created=True,
        )
        ChannelOverride.objects.create(channel=channel, name="User Renamed Channel")

        programs = self._for_channel(self._get_grid(), channel)

        self.assertTrue(programs)
        self.assertEqual(programs[0]["title"], "User Renamed Channel")
        self.assertEqual(programs[0]["epg"]["name"], "User Renamed Channel")

    def test_effective_name_override_used_when_pattern_misses(self):
        _, epg_data = self._dummy_source(NHL_PROPS)
        channel = Channel.objects.create(
            channel_number=3.0,
            name="Unrelated Provider Title",
            channel_group=self.group,
            epg_data=epg_data,
            auto_created=True,
        )
        ChannelOverride.objects.create(channel=channel, name="Also Unrelated")

        programs = self._for_channel(self._get_grid(), channel)

        # Pattern miss falls back to standard dummy using the effective display name.
        self.assertEqual(len(programs), 6)
        self.assertEqual(programs[0]["title"], "Also Unrelated")
        self.assertEqual(programs[0]["epg"]["name"], "Also Unrelated")

    def test_program_ids_are_unique(self):
        Channel.objects.create(
            channel_number=1.0, name="No EPG Channel", channel_group=self.group
        )
        _, epg_data = self._dummy_source(NHL_PROPS)
        Channel.objects.create(
            channel_number=2.0,
            name="NHL 01: Capitals vs Flyers @ 11:00 PM ET",
            channel_group=self.group,
            epg_data=epg_data,
        )

        ids = [p["id"] for p in self._get_grid()]
        self.assertEqual(len(ids), len(set(ids)))

    def test_custom_dummy_channel_uses_regex_derived_titles(self):
        _, epg_data = self._dummy_source(
            {
                **NHL_PROPS,
                "title_template": "{team1} vs {team2}",
                "upcoming_title_template": "Upcoming: {team1}",
            }
        )
        channel = Channel.objects.create(
            channel_number=10.0,
            name="NHL 01: Capitals vs Flyers @ 11:00 PM ET",
            channel_group=self.group,
            epg_data=epg_data,
        )

        programs = self._for_channel(self._get_grid(), channel)

        self.assertTrue(programs)
        titles = {p["title"] for p in programs}
        self.assertTrue(
            titles <= {"Capitals vs Flyers", "Upcoming: Capitals"},
            f"unexpected titles: {titles}",
        )
        for program in programs:
            self.assertTrue(program["id"].startswith("dummy-custom-"))

    def test_custom_dummy_respects_grid_window(self):
        _, epg_data = self._dummy_source(NHL_PROPS)
        channel = Channel.objects.create(
            channel_number=11.0,
            name="NHL 02: Bruins vs Rangers @ 08:00 PM ET",
            channel_group=self.group,
            epg_data=epg_data,
        )

        programs = self._for_channel(self._get_grid(), channel)

        self.assertTrue(programs)
        for program in programs:
            start = timezone.datetime.fromisoformat(program["start_time"])
            end = timezone.datetime.fromisoformat(program["end_time"])
            self.assertLess(start, FIXED_NOW + timedelta(hours=24))
            self.assertGreater(end, FIXED_NOW - timedelta(hours=1, minutes=5))

    def test_stream_name_source_resolves_by_channelstream_order(self):
        """stream_index must follow channelstream order, not Stream's own ordering.

        Stream.Meta.ordering is ``-updated_at``, so an unordered prefetch would
        return the most recently created stream first. channelstream order here
        is Jets (0) then Oilers (1); ``stream_index`` 2 must pick Oilers.
        """
        _, epg_data = self._dummy_source(
            {
                **NHL_PROPS,
                "name_source": "stream",
                "stream_index": 2,
                "title_template": "{team1} vs {team2}",
            }
        )
        channel = Channel.objects.create(
            channel_number=12.0,
            name="Unparseable channel name",
            channel_group=self.group,
            epg_data=epg_data,
        )
        first = self._make_stream("NHL 04: Jets vs Canucks @ 10:00 PM ET", 1)
        second = self._make_stream("NHL 03: Oilers vs Flames @ 09:00 PM ET", 2)
        ChannelStream.objects.create(channel=channel, stream=first, order=0)
        ChannelStream.objects.create(channel=channel, stream=second, order=1)

        programs = self._for_channel(self._get_grid(), channel)

        self.assertTrue(programs)
        titles = {p["title"] for p in programs}
        self.assertIn("Oilers vs Flames", titles)
        self.assertNotIn("Jets vs Canucks", titles)

    def test_unmatched_stream_index_falls_back_to_stream_1(self):
        """Out-of-range stream_index uses the first stream, not the channel name."""
        _, epg_data = self._dummy_source(
            {
                **NHL_PROPS,
                "name_source": "stream",
                "stream_index": 5,
                "title_template": "{team1} vs {team2}",
            }
        )
        channel = Channel.objects.create(
            channel_number=13.0,
            name="Unparseable channel name",
            channel_group=self.group,
            epg_data=epg_data,
        )
        first = self._make_stream("NHL 01: Capitals vs Flyers @ 07:00 PM ET", 1)
        second = self._make_stream("NHL 02: Bruins vs Rangers @ 08:00 PM ET", 2)
        ChannelStream.objects.create(channel=channel, stream=first, order=0)
        ChannelStream.objects.create(channel=channel, stream=second, order=1)

        programs = self._for_channel(self._get_grid(), channel)

        self.assertTrue(programs)
        titles = {p["title"] for p in programs}
        self.assertIn("Capitals vs Flyers", titles)
        self.assertNotIn("Bruins vs Rangers", titles)

    def test_unmatched_stream_index_with_no_streams_uses_channel_name(self):
        _, epg_data = self._dummy_source(
            {**NHL_PROPS, "name_source": "stream", "stream_index": 5}
        )
        channel = Channel.objects.create(
            channel_number=14.0,
            name="Fallback Channel",
            channel_group=self.group,
            epg_data=epg_data,
        )

        programs = self._for_channel(self._get_grid(), channel)

        # No streams and channel name does not match, so standard dummy runs.
        self.assertEqual(len(programs), 6)
        self.assertEqual(programs[0]["title"], "Fallback Channel")

    def test_real_programs_are_returned_without_dummy_generation(self):
        source = EPGSource.objects.create(
            name="Real XMLTV",
            source_type="xmltv",
            url="http://example.com/epg.xml",
        )
        epg_data = EPGData.objects.create(
            tvg_id="real.channel", name="Real Channel", epg_source=source
        )
        Channel.objects.create(
            channel_number=20.0,
            name="Real Channel",
            channel_group=self.group,
            epg_data=epg_data,
        )
        ProgramData.objects.create(
            epg=epg_data,
            start_time=FIXED_NOW - timedelta(minutes=30),
            end_time=FIXED_NOW + timedelta(minutes=30),
            title="Live Show",
            description="Airing now",
            tvg_id="real.channel",
        )

        titles = [p["title"] for p in self._get_grid()]
        self.assertIn("Live Show", titles)

    def test_broken_regex_does_not_fail_the_request(self):
        _, epg_data = self._dummy_source({"title_pattern": "(?<unclosed"})
        channel = Channel.objects.create(
            channel_number=30.0,
            name="Broken Pattern Channel",
            channel_group=self.group,
            epg_data=epg_data,
        )

        programs = self._for_channel(self._get_grid(), channel)

        # Invalid pattern falls through to the standard dummy generator.
        self.assertEqual(len(programs), 6)

    def test_dummy_generation_does_not_scale_queries_with_channel_count(self):
        """Resolving stream-based names must not issue a query per channel."""
        _, epg_data = self._dummy_source(
            {**NHL_PROPS, "name_source": "stream", "stream_index": 1}
        )

        def build_channels(count, offset):
            for i in range(count):
                channel = Channel.objects.create(
                    channel_number=float(100 + offset + i),
                    name=f"Dummy Channel {offset + i}",
                    channel_group=self.group,
                    epg_data=epg_data,
                )
                stream = self._make_stream(
                    f"NHL {offset + i}: A vs B @ 07:00 PM ET", offset + i
                )
                ChannelStream.objects.create(channel=channel, stream=stream, order=0)

        def count_queries(channel_count):
            with CaptureQueriesContext(connection) as ctx:
                resolved = [
                    resolve_channel_parse_name(channel, channel.epg_data.epg_source)
                    for channel in custom_dummy_channels_queryset()
                ]
            self.assertEqual(len(resolved), channel_count)
            for name in resolved:
                self.assertTrue(name.startswith("NHL "), name)
            return len(ctx.captured_queries)

        build_channels(2, 0)
        few = count_queries(2)

        build_channels(8, 100)
        many = count_queries(10)

        self.assertEqual(
            few, many, "grid dummy name resolution issues per-channel queries"
        )


class EPGGridWindowParamTests(TestCase):
    """Tests for the days/prev_days/start/end query parameters on the grid."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="windowuser", password="testpass123"
        )
        self.user.user_level = 10
        self.user.save()
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

        self.group = ChannelGroup.objects.create(name="Window Group")

        source = EPGSource.objects.create(
            name="Window XMLTV",
            source_type="xmltv",
            url="http://example.com/epg.xml",
        )
        self.epg_data = EPGData.objects.create(
            tvg_id="window.channel", name="Window Channel", epg_source=source
        )
        Channel.objects.create(
            channel_number=1.0,
            name="Window Channel",
            channel_group=self.group,
            epg_data=self.epg_data,
        )

    def _create_program(self, start_offset_hours, duration_hours=1, title="Test"):
        start = FIXED_NOW + timedelta(hours=start_offset_hours)
        end = start + timedelta(hours=duration_hours)
        return ProgramData.objects.create(
            epg=self.epg_data,
            start_time=start,
            end_time=end,
            title=title,
            description="desc",
            tvg_id="window.channel",
        )

    def _get_grid(self, params=None):
        with mock.patch.object(timezone, "now", return_value=FIXED_NOW):
            response = self.client.get(GRID_URL, params or {})
        return response

    # ── default (no params) ──────────────────────────────────────────────

    def test_default_window_returns_programs_in_25h_span(self):
        """No params: now-1h to now+24h (same as before)."""
        inside = self._create_program(-0.5, title="Currently On")
        future = self._create_program(12, title="Tonight")
        outside_past = self._create_program(-3, title="Old")
        outside_future = self._create_program(25, title="Too Far")

        response = self._get_grid()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        titles = [p["title"] for p in response.data["data"]]
        self.assertIn("Currently On", titles)
        self.assertIn("Tonight", titles)
        self.assertNotIn("Old", titles)
        self.assertNotIn("Too Far", titles)

    # ── days / prev_days ─────────────────────────────────────────────────

    def test_days_extends_forward_window(self):
        far_future = self._create_program(30, title="Day 2 Show")
        response = self._get_grid({"days": "2"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        titles = [p["title"] for p in response.data["data"]]
        self.assertIn("Day 2 Show", titles)

    def test_prev_days_extends_lookback(self):
        old = self._create_program(-20, title="Yesterday Show")
        response = self._get_grid({"prev_days": "1"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        titles = [p["title"] for p in response.data["data"]]
        self.assertIn("Yesterday Show", titles)

    def test_days_zero_treated_as_one(self):
        """days=0 is clamped to 1 (no unlimited payloads)."""
        response = self._get_grid({"days": "0"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_prev_days_zero_starts_at_now(self):
        """prev_days=0 means lookback=now, no 1h buffer."""
        recently_ended = self._create_program(-1, 0.5, title="Just Ended")
        response = self._get_grid({"prev_days": "0"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        titles = [p["title"] for p in response.data["data"]]
        self.assertNotIn("Just Ended", titles)

    def test_days_and_prev_days_together(self):
        old = self._create_program(-20, title="Yesterday")
        far = self._create_program(30, title="Tomorrow Night")
        response = self._get_grid({"days": "2", "prev_days": "1"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        titles = [p["title"] for p in response.data["data"]]
        self.assertIn("Yesterday", titles)
        self.assertIn("Tomorrow Night", titles)

    def test_days_clamped_to_max(self):
        """days > 365 is clamped without error."""
        response = self._get_grid({"days": "9999"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_prev_days_clamped_to_max(self):
        """prev_days > 30 is clamped without error."""
        response = self._get_grid({"prev_days": "999"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    # ── start / end (absolute) ───────────────────────────────────────────

    def test_absolute_start_end(self):
        tomorrow_start = (FIXED_NOW + timedelta(hours=24)).isoformat()
        tomorrow_end = (FIXED_NOW + timedelta(hours=48)).isoformat()
        prog = self._create_program(30, title="Tomorrow Show")
        response = self._get_grid({"start": tomorrow_start, "end": tomorrow_end})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        titles = [p["title"] for p in response.data["data"]]
        self.assertIn("Tomorrow Show", titles)

    def test_absolute_start_only_defaults_end_to_plus_24h(self):
        start = FIXED_NOW.isoformat()
        future = self._create_program(12, title="Later Today")
        response = self._get_grid({"start": start})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        titles = [p["title"] for p in response.data["data"]]
        self.assertIn("Later Today", titles)

    def test_absolute_end_only_defaults_start_to_minus_1h(self):
        end = (FIXED_NOW + timedelta(hours=12)).isoformat()
        current = self._create_program(-0.5, title="On Now")
        response = self._get_grid({"end": end})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        titles = [p["title"] for p in response.data["data"]]
        self.assertIn("On Now", titles)

    def test_absolute_overrides_days(self):
        """start/end takes precedence, days is ignored."""
        start = FIXED_NOW.isoformat()
        end = (FIXED_NOW + timedelta(hours=2)).isoformat()
        far = self._create_program(30, title="Far Away")
        response = self._get_grid({"start": start, "end": end, "days": "5"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        titles = [p["title"] for p in response.data["data"]]
        self.assertNotIn("Far Away", titles)

    def test_bare_date_accepted_as_start(self):
        """A date-only string like 2026-01-15 is parsed as midnight UTC."""
        date_str = FIXED_NOW.strftime("%Y-%m-%d")
        response = self._get_grid({"start": date_str})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    # ── error cases ──────────────────────────────────────────────────────

    def test_invalid_days_returns_400(self):
        response = self._get_grid({"days": "abc"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_invalid_prev_days_returns_400(self):
        response = self._get_grid({"prev_days": "xyz"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_invalid_start_returns_400(self):
        response = self._get_grid({"start": "not-a-date"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_end_before_start_returns_400(self):
        start = (FIXED_NOW + timedelta(hours=24)).isoformat()
        end = FIXED_NOW.isoformat()
        response = self._get_grid({"start": start, "end": end})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


# `now` is intentionally not hour-aligned here: aligning dummy generation to
# the current hour must never leave a gap between the last generated block
# and the requested cutoff, and the original grid's hardcoded window happened
# to hide that class of bug whenever `now` fell exactly on the hour.
UNALIGNED_NOW = datetime(2026, 1, 15, 12, 47, 31, tzinfo=dt_timezone.utc)


class EPGGridDummyWindowCoverageTests(TestCase):
    """Standard dummy programs must cover the full requested window, with no
    gap at the boundary, even when `now` isn't hour-aligned and the window is
    rewound via prev_days or shifted entirely into the future via start/end.
    """

    def setUp(self):
        self.user = User.objects.create_user(
            username="coverageuser", password="testpass123"
        )
        self.user.user_level = 10
        self.user.save()
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.group = ChannelGroup.objects.create(name="Coverage Group")
        self.channel = Channel.objects.create(
            channel_number=1.0, name="No EPG Channel", channel_group=self.group
        )

    def _get_grid(self, params=None):
        with mock.patch.object(timezone, "now", return_value=UNALIGNED_NOW):
            response = self.client.get(GRID_URL, params or {})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        return [
            p for p in response.data["data"] if p["tvg_id"] == str(self.channel.uuid)
        ]

    @staticmethod
    def _latest_end(programs):
        return max(
            timezone.datetime.fromisoformat(p["end_time"]) for p in programs
        )

    @staticmethod
    def _earliest_start(programs):
        return min(
            timezone.datetime.fromisoformat(p["start_time"]) for p in programs
        )

    def test_prev_days_rewind_reaches_cutoff(self):
        """The default 24h forward cutoff must be reached even after rewinding
        via prev_days, regardless of `now`'s minute/second offset.
        """
        programs = self._get_grid({"prev_days": "1"})
        self.assertTrue(programs)
        cutoff = UNALIGNED_NOW + timedelta(hours=24)
        self.assertGreaterEqual(self._latest_end(programs), cutoff)

    def test_future_only_window_reaches_cutoff(self):
        """An absolute future window must be covered through its end, even
        though the window start gets floored to the hour for block alignment.
        """
        start = (UNALIGNED_NOW + timedelta(hours=24)).isoformat()
        end = (UNALIGNED_NOW + timedelta(hours=48)).isoformat()
        programs = self._get_grid({"start": start, "end": end})
        self.assertTrue(programs)
        self.assertGreaterEqual(
            self._latest_end(programs), UNALIGNED_NOW + timedelta(hours=48)
        )
        self.assertLess(
            self._earliest_start(programs), UNALIGNED_NOW + timedelta(hours=25)
        )

    def test_days_and_prev_days_combo_reaches_cutoff(self):
        programs = self._get_grid({"days": "3", "prev_days": "2"})
        self.assertTrue(programs)
        cutoff = UNALIGNED_NOW + timedelta(days=3)
        self.assertGreaterEqual(self._latest_end(programs), cutoff)



