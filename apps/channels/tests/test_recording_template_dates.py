"""Broadcast-date placeholders in DVR path templates.

``{start_date}``, ``{start_year}``, ``{start_month}`` and ``{start_day}`` are
the programme's broadcast date in the configured system time zone — distinct
from ``{original_air_date}`` (TV fallback template only) and from
``{start}``/``{end}``, which keep their UTC form.
"""
import datetime as dt
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.test import TestCase

from apps.channels.models import Channel
from apps.channels.tasks import _build_output_paths, _system_timezone
from apps.epg.models import EPGData, EPGSource, ProgramData

# 20:30 UTC is the 16th in Asia/Singapore (UTC+8) but still the 15th in
# America/Chicago (UTC-6); 02:30 UTC is the 14th in America/Chicago. Both
# directions, so a pass cannot come from the local date matching UTC by chance.
EVENING_UTC = dt.datetime(2026, 1, 15, 20, 30, 0, tzinfo=dt.timezone.utc)
EARLY_UTC = dt.datetime(2026, 1, 15, 2, 30, 0, tzinfo=dt.timezone.utc)


class DvrBroadcastDateTemplateTests(TestCase):
    def setUp(self):
        self.epg_source = EPGSource.objects.create(
            name="Broadcast Date Test", source_type="xmltv"
        )
        self.epg = EPGData.objects.create(
            tvg_id="broadcast-date.test",
            name="Broadcast Date Test",
            epg_source=self.epg_source,
        )
        self.channel = Channel.objects.create(
            channel_number=92, name="Broadcast Channel"
        )

    def _program(self, custom_properties, start, end, title="Example Show"):
        program = ProgramData.objects.create(
            epg=self.epg,
            title=title,
            sub_title="",
            start_time=start,
            end_time=end,
            custom_properties=custom_properties,
        )
        return {"id": program.id, "title": program.title, "sub_title": ""}

    def _build(self, program, start, end, *, time_zone="UTC", tv_template=None,
               tv_fallback=None, movie_template=None, movie_fallback=None):
        tv_template = tv_template or "TV/{show}/S{season:02d}E{episode:02d}.mkv"
        tv_fallback = tv_fallback or "TV/{show}/{start}.mkv"
        movie_template = movie_template or "Movies/{title} ({year}).mkv"
        movie_fallback = movie_fallback or "Movies/{start}.mkv"

        with patch(
            "apps.channels.tasks.CoreSettings.get_dvr_tv_template",
            return_value=tv_template,
        ), patch(
            "apps.channels.tasks.CoreSettings.get_dvr_tv_fallback_template",
            return_value=tv_fallback,
        ), patch(
            "apps.channels.tasks.CoreSettings.get_dvr_movie_template",
            return_value=movie_template,
        ), patch(
            "apps.channels.tasks.CoreSettings.get_dvr_movie_fallback_template",
            return_value=movie_fallback,
        ), patch(
            "apps.channels.tasks.CoreSettings.get_system_time_zone",
            return_value=time_zone,
        ), patch("os.stat", side_effect=OSError), patch("os.makedirs"):
            return _build_output_paths(
                self.channel, program, start, end, recording_id=1
            )[0]

    def _episode(self, start, end):
        """A programme with season/episode, so the normal TV template is used."""
        return self._program({"season": 1, "episode": 2}, start, end)

    def test_start_date_uses_the_configured_time_zone(self):
        end = EVENING_UTC + dt.timedelta(hours=1)
        program = self._episode(EVENING_UTC, end)
        cases = (
            ("UTC", "2026-01-15"),
            ("Asia/Singapore", "2026-01-16"),
            ("America/Chicago", "2026-01-15"),
        )
        for zone, expected in cases:
            with self.subTest(time_zone=zone):
                final_path = self._build(
                    program, EVENING_UTC, end,
                    time_zone=zone,
                    tv_template="TV/{show}/{show} - {start_date}.mkv",
                )
                self.assertTrue(final_path.endswith(
                    f"TV/Example Show/Example Show - {expected}.mkv"
                ), final_path)

    def test_start_date_rolls_backward_for_a_negative_offset(self):
        end = EARLY_UTC + dt.timedelta(hours=1)
        program = self._episode(EARLY_UTC, end)
        final_path = self._build(
            program, EARLY_UTC, end,
            time_zone="America/Chicago",
            tv_template="TV/{show}/{show} - {start_date}.mkv",
        )
        self.assertTrue(final_path.endswith(
            "TV/Example Show/Example Show - 2026-01-14.mkv"
        ), final_path)

    def test_numeric_components_accept_format_specifiers(self):
        """Integers, like {season}, so the documented {x:02d} idiom pads them."""
        end = EVENING_UTC + dt.timedelta(hours=1)
        program = self._episode(EVENING_UTC, end)
        final_path = self._build(
            program, EVENING_UTC, end,
            time_zone="Asia/Singapore",
            tv_template=(
                "TV/{show}/{start_year}/{start_month:02d}/"
                "{start_year}-{start_month:02d}-{start_day:02d}.mkv"
            ),
        )
        self.assertTrue(final_path.endswith(
            "TV/Example Show/2026/01/2026-01-16.mkv"
        ), final_path)

    def test_numeric_components_are_unpadded_without_a_specifier(self):
        """A bare {start_month} is the integer, matching {season}'s behaviour."""
        end = EVENING_UTC + dt.timedelta(hours=1)
        program = self._episode(EVENING_UTC, end)
        final_path = self._build(
            program, EVENING_UTC, end,
            time_zone="Asia/Singapore",
            tv_template="TV/{show}/{start_month}-{start_day}.mkv",
        )
        self.assertTrue(final_path.endswith(
            "TV/Example Show/1-16.mkv"
        ), final_path)

    def test_placeholders_reach_the_tv_fallback_template(self):
        """A programme with no season/episode still gets the broadcast date."""
        end = EVENING_UTC + dt.timedelta(hours=1)
        program = self._program({}, EVENING_UTC, end)
        final_path = self._build(
            program, EVENING_UTC, end,
            time_zone="Asia/Singapore",
            tv_fallback="TV/{show}/Season {start_year}/{show} - {start_date}.mkv",
        )
        self.assertTrue(final_path.endswith(
            "TV/Example Show/Season 2026/Example Show - 2026-01-16.mkv"
        ), final_path)

    def test_placeholders_reach_the_movie_templates(self):
        end = EVENING_UTC + dt.timedelta(hours=1)
        program = self._program(
            {"categories": ["Movie"]}, EVENING_UTC, end, title="A Film"
        )
        final_path = self._build(
            program, EVENING_UTC, end,
            time_zone="Asia/Singapore",
            movie_template="Movies/{title} - {start_date}.mkv",
        )
        self.assertTrue(final_path.endswith(
            "Movies/A Film - 2026-01-16.mkv"
        ), final_path)

    def test_start_and_end_keep_their_utc_form(self):
        """Existing templates are unaffected by the new local-time values."""
        end = EVENING_UTC + dt.timedelta(hours=1)
        program = self._episode(EVENING_UTC, end)
        final_path = self._build(
            program, EVENING_UTC, end,
            time_zone="Asia/Singapore",
            tv_template="TV/{show}/{start}-{end}.mkv",
        )
        self.assertTrue(final_path.endswith(
            "TV/Example Show/20260115_203000-20260115_213000.mkv"
        ), final_path)

    def test_unusable_time_zone_falls_back_without_failing(self):
        """A stored zone the platform cannot resolve must not break naming."""
        end = EVENING_UTC + dt.timedelta(hours=1)
        program = self._episode(EVENING_UTC, end)
        final_path = self._build(
            program, EVENING_UTC, end,
            time_zone="Not/AZone",
            tv_template="TV/{show}/{show} - {start_date}.mkv",
        )
        self.assertTrue(final_path.endswith(
            "TV/Example Show/Example Show - 2026-01-15.mkv"
        ), final_path)


class SystemTimezoneHelperTests(TestCase):
    """_system_timezone backs both DVR naming and recurring-rule scheduling."""

    def test_configured_zone_is_returned(self):
        with patch(
            "apps.channels.tasks.CoreSettings.get_system_time_zone",
            return_value="Asia/Singapore",
        ):
            self.assertEqual(_system_timezone(), ZoneInfo("Asia/Singapore"))

    def test_unresolvable_zone_falls_back_to_the_server_zone(self):
        from django.utils import timezone

        with patch(
            "apps.channels.tasks.CoreSettings.get_system_time_zone",
            return_value="Not/AZone",
        ):
            self.assertEqual(
                _system_timezone(), timezone.get_current_timezone()
            )
