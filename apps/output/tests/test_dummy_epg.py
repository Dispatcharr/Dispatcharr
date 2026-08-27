"""Tests for consolidated dummy EPG generation."""

from datetime import timezone as dt_timezone
from datetime import timedelta
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase, Client
from django.urls import reverse
from uuid import uuid4
from django.utils import timezone

from apps.channels.models import ChannelGroup
from apps.epg.models import EPGData, EPGSource
from apps.output.dummy_epg import (
    ceil_to_half_hour,
    generate_custom_dummy_programs,
    generate_dummy_programs,
    generate_standard_dummy_programs,
    programme_overlaps_export_window,
)
from apps.output.tests.test_views import OutputEndpointTestMixin, _response_text


NHL_PROPS = {
    "title_pattern": r"(?<league>.*)\s\d+:\s(?<team1>.*?)(?:\s+vs\s+)(?<team2>.*?)\s*@.*",
    "time_pattern": r"(?<hour>\d{1,2}):(?<minute>\d{2})\s*(?<ampm>AM|PM)",
    "date_pattern": r"@ (?<month>[A-Za-z]+)\s+(?<day>\d{1,2})",
    "timezone": "US/Eastern",
    "program_duration": 180,
}


class DummyEpgHelperTest(SimpleTestCase):
    def test_ceil_to_half_hour_on_boundary(self):
        dt = timezone.now().replace(minute=30, second=0, microsecond=0)
        self.assertEqual(ceil_to_half_hour(dt), dt)

    def test_ceil_to_half_hour_rounds_up(self):
        dt = timezone.now().replace(minute=17, second=42, microsecond=123456)
        aligned = ceil_to_half_hour(dt)
        self.assertEqual(aligned.minute, 30)
        self.assertEqual(aligned.second, 0)
        self.assertGreaterEqual(aligned, dt.replace(microsecond=0))

    def test_programme_overlaps_export_window(self):
        now = timezone.now()
        self.assertTrue(
            programme_overlaps_export_window(
                now, now + timedelta(hours=1), now - timedelta(hours=1), now + timedelta(hours=2)
            )
        )
        self.assertFalse(
            programme_overlaps_export_window(
                now, now + timedelta(hours=1), now + timedelta(hours=2), None
            )
        )


class CustomDummyEpgTest(TestCase):
    def setUp(self):
        self.group = ChannelGroup.objects.create(name="Sports Group")

    def _epg_source(self, **overrides):
        props = {**NHL_PROPS, **overrides.pop("custom_properties", {})}
        return EPGSource.objects.create(
            name=overrides.pop("name", "NHL Dummy"),
            source_type="dummy",
            custom_properties=props,
            **overrides,
        )

    def test_past_event_outside_window_fills_with_ended(self):
        epg_source = self._epg_source()
        channel_name = (
            "NHL 01: Washington Capitals vs Philadelphia Flyers @ April 16 07:30 PM ET"
        )
        now = timezone.now()
        lookback = now - timedelta(days=7)

        programs = generate_dummy_programs(
            channel_id="nhl01",
            channel_name=channel_name,
            num_days=7,
            epg_source=epg_source,
            export_lookback=lookback,
            export_cutoff=now + timedelta(days=7),
        )

        self.assertGreater(len(programs), 0)
        self.assertTrue(all(p["end_time"] >= lookback for p in programs))
        self.assertTrue(any("Ended" in p["description"] for p in programs))
        for program in programs:
            start = program["start_time"]
            self.assertIn(start.minute, (0, 30))
        self.assertGreaterEqual(programs[0]["start_time"], lookback)

    def test_future_event_fills_grid_window_with_upcoming(self):
        epg_source = self._epg_source(name="NHL Dummy Future")
        now = timezone.now()
        grid_start = now - timedelta(hours=1)
        grid_end = now + timedelta(hours=24)
        future = now + timedelta(days=3)
        channel_name = (
            f"NHL 01: Washington Capitals vs Philadelphia Flyers @ "
            f"{future.strftime('%B')} {future.day} 07:30 PM ET"
        )

        programs = generate_dummy_programs(
            channel_id="nhl01",
            channel_name=channel_name,
            num_days=1,
            epg_source=epg_source,
            export_lookback=grid_start,
            export_cutoff=grid_end,
        )

        self.assertGreater(len(programs), 0)
        self.assertTrue(
            all(
                programme_overlaps_export_window(
                    p["start_time"], p["end_time"], grid_start, grid_end
                )
                for p in programs
            )
        )
        self.assertTrue(any("Upcoming" in p.get("description", "") for p in programs))

    def test_upcoming_starts_from_now_not_event_day_midnight(self):
        epg_source = self._epg_source(name="NHL Dummy Tonight")
        fixed_now = timezone.datetime(2026, 8, 26, 20, 0, 0, tzinfo=dt_timezone.utc)
        event_day = fixed_now + timedelta(days=1)
        channel_name = (
            f"NHL 01: Washington Capitals vs Philadelphia Flyers @ "
            f"{event_day.strftime('%B')} {event_day.day} 07:00 PM ET"
        )
        lookback = fixed_now - timedelta(hours=1)
        cutoff = fixed_now + timedelta(days=3)

        with patch("apps.output.dummy_epg.django_timezone.now", return_value=fixed_now):
            programs = generate_dummy_programs(
                channel_id="nhl01",
                channel_name=channel_name,
                num_days=3,
                epg_source=epg_source,
                export_lookback=lookback,
                export_cutoff=cutoff,
            )

        self.assertGreater(len(programs), 0)
        self.assertGreaterEqual(programs[0]["start_time"], fixed_now)
        self.assertTrue(any("Upcoming" in p.get("description", "") for p in programs))

    def test_dated_event_includes_main_program_in_window(self):
        epg_source = self._epg_source()
        fixed_now = timezone.datetime(2026, 8, 27, 15, 0, 0, tzinfo=dt_timezone.utc)
        channel_name = (
            "NHL 01: Washington Capitals vs Philadelphia Flyers @ August 27 07:00 PM ET"
        )

        with patch("apps.output.dummy_epg.django_timezone.now", return_value=fixed_now):
            programs = generate_dummy_programs(
                channel_id="nhl01",
                channel_name=channel_name,
                num_days=1,
                epg_source=epg_source,
                export_lookback=fixed_now - timedelta(hours=1),
                export_cutoff=fixed_now + timedelta(hours=12),
            )

        main = [p for p in programs if "Upcoming" not in p["description"] and "Ended" not in p["description"]]
        self.assertEqual(len(main), 1)
        self.assertIn("Capitals", main[0]["title"])

    def test_time_only_recurring_generates_multi_day(self):
        epg_source = self._epg_source(
            name="Daily Show",
            custom_properties={
                **NHL_PROPS,
                "date_pattern": "",
            },
        )
        channel_name = "NHL 01: Washington Capitals vs Philadelphia Flyers @ 07:30 PM ET"
        now = timezone.now().replace(minute=0, second=0, microsecond=0)

        programs = generate_custom_dummy_programs(
            channel_id="nhl01",
            channel_name=channel_name,
            now=now,
            num_days=2,
            custom_properties=epg_source.custom_properties,
            export_lookback=now,
            export_cutoff=now + timedelta(days=2),
        )

        self.assertGreater(len(programs), 0)
        self.assertLessEqual(programs[0]["start_time"], now + timedelta(days=1))

    def test_no_time_pattern_fills_day_blocks(self):
        epg_source = self._epg_source(
            name="Static Dummy",
            custom_properties={
                "title_pattern": r"(?<title>.*)",
                "time_pattern": "",
                "date_pattern": "",
                "program_duration": 240,
            },
        )
        now = timezone.now().replace(minute=0, second=0, microsecond=0)
        programs = generate_custom_dummy_programs(
            channel_id="static1",
            channel_name="Static Channel Title",
            now=now,
            num_days=1,
            custom_properties=epg_source.custom_properties,
            export_lookback=now,
            export_cutoff=now + timedelta(days=1),
        )
        self.assertGreaterEqual(len(programs), 4)

    def test_fallback_templates_when_pattern_misses(self):
        epg_source = self._epg_source(
            custom_properties={
                **NHL_PROPS,
                "fallback_title_template": "No match for {team1}",
                "fallback_description_template": "Fallback description",
            },
        )
        programs = generate_dummy_programs(
            channel_id="nhl01",
            channel_name="Completely unrelated channel name",
            num_days=1,
            epg_source=epg_source,
        )
        self.assertEqual(len(programs), 6)
        self.assertEqual(programs[0]["title"], "No match for {team1}")

    def test_fallback_templates_respect_export_window(self):
        epg_source = self._epg_source(
            custom_properties={
                **NHL_PROPS,
                "fallback_title_template": "Fallback title",
                "fallback_description_template": "Fallback description",
            },
        )
        now = timezone.now().replace(minute=0, second=0, microsecond=0)
        window_start = now + timedelta(hours=2)
        window_end = now + timedelta(hours=10)
        programs = generate_dummy_programs(
            channel_id="nhl01",
            channel_name="Completely unrelated channel name",
            num_days=1,
            epg_source=epg_source,
            export_lookback=window_start,
            export_cutoff=window_end,
        )
        self.assertGreater(len(programs), 0)
        self.assertTrue(
            all(
                programme_overlaps_export_window(
                    p["start_time"], p["end_time"], window_start, window_end
                )
                for p in programs
            )
        )

    def test_standard_dummy_respects_export_window(self):
        now = timezone.now().replace(minute=0, second=0, microsecond=0)
        window_start = now + timedelta(hours=2)
        window_end = now + timedelta(hours=10)
        programs = generate_standard_dummy_programs(
            "ch1",
            "Test Channel",
            now,
            num_days=1,
            program_length_hours=4,
            export_lookback=window_start,
            export_cutoff=window_end,
        )
        self.assertGreater(len(programs), 0)
        self.assertTrue(
            all(
                programme_overlaps_export_window(
                    p["start_time"], p["end_time"], window_start, window_end
                )
                for p in programs
            )
        )

    def test_dated_event_one_month_out_caps_at_export_cutoff(self):
        """Upcoming filler stops at the export cutoff, not at the far-future event."""
        epg_source = self._epg_source(name="Far Future")
        fixed_now = timezone.datetime(2026, 8, 26, 12, 0, 0, tzinfo=dt_timezone.utc)
        event_day = fixed_now + timedelta(days=30)
        channel_name = (
            f"NHL 01: Washington Capitals vs Philadelphia Flyers @ "
            f"{event_day.strftime('%B')} {event_day.day} 07:00 PM ET"
        )
        export_cutoff = fixed_now + timedelta(days=7)

        with patch("apps.output.dummy_epg.django_timezone.now", return_value=fixed_now):
            programs = generate_dummy_programs(
                channel_id="nhl01",
                channel_name=channel_name,
                num_days=7,
                epg_source=epg_source,
                export_lookback=fixed_now,
                export_cutoff=export_cutoff,
            )

        self.assertGreater(len(programs), 0)
        self.assertLess(programs[-1]["end_time"], export_cutoff + timedelta(minutes=1))
        self.assertTrue(all("Upcoming" in p["description"] for p in programs))
        self.assertTrue(
            all(
                programme_overlaps_export_window(
                    p["start_time"], p["end_time"], fixed_now, export_cutoff
                )
                for p in programs
            )
        )

    def test_dated_event_one_month_out_respects_grid_window(self):
        """Grid-style 25h window yields only upcoming filler, not a month of blocks."""
        epg_source = self._epg_source(name="Grid Window")
        fixed_now = timezone.datetime(2026, 8, 26, 12, 0, 0, tzinfo=dt_timezone.utc)
        event_day = fixed_now + timedelta(days=30)
        channel_name = (
            f"NHL 01: Washington Capitals vs Philadelphia Flyers @ "
            f"{event_day.strftime('%B')} {event_day.day} 07:00 PM ET"
        )
        grid_start = fixed_now - timedelta(hours=1)
        grid_end = fixed_now + timedelta(hours=24)

        with patch("apps.output.dummy_epg.django_timezone.now", return_value=fixed_now):
            programs = generate_dummy_programs(
                channel_id="nhl01",
                channel_name=channel_name,
                num_days=1,
                epg_source=epg_source,
                export_lookback=grid_start,
                export_cutoff=grid_end,
            )

        self.assertGreater(len(programs), 0)
        self.assertLess(programs[-1]["end_time"], grid_end + timedelta(minutes=1))
        self.assertTrue(all("Upcoming" in p["description"] for p in programs))


class DummyEpgXmltvIntegrationTest(OutputEndpointTestMixin, TestCase):
    """Custom dummy programmes still appear in XMLTV export (cache bypassed in tests)."""

    def setUp(self):
        super().setUp()
        self.client = Client()
        self.group = ChannelGroup.objects.create(name=f"Dummy XMLTV {uuid4().hex[:8]}")
        self.profile = self._create_isolated_profile("dummy-xmltv")

    def _add_channel(self, **kwargs):
        return self._add_channel_to_profile(self.profile, self.group, **kwargs)

    def _epg_url(self, query="days=1&prev_days=0"):
        base = reverse("output:epg_endpoint", kwargs={"profile_name": self.profile.name})
        return f"{base}?{query}"

    def test_custom_dummy_emits_programmes_in_xmltv(self):
        epg_source = EPGSource.objects.create(
            name="XMLTV Dummy",
            source_type="dummy",
            custom_properties=NHL_PROPS,
        )
        epg_data = EPGData.objects.get(epg_source=epg_source)
        self._add_channel(
            channel_number=501.0,
            name="NHL 01: Washington Capitals vs Philadelphia Flyers @ August 27 07:00 PM ET",
            epg_data=epg_data,
        )

        response = self.client.get(self._epg_url())
        self.assertEqual(response.status_code, 200)
        content = _response_text(response)
        self.assertIn("<programme ", content)
        self.assertIn("Capitals", content)
