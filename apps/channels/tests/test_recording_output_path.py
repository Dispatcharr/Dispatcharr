"""Recording output paths must keep season/episode when the EPG row is gone.

EPG refreshes delete and bulk-recreate ProgramData rows rather than updating
them in place, so the ProgramData.id captured when a recording was scheduled
routinely resolves to nothing by the time the output path is built. When that
happens _parse_epg_tv_movie_info returns season=None/episode=None and
_build_output_paths silently falls through to the S/E-less fallback template,
naming the recording by air date instead of SxxExx.

The identity is not actually lost at that point: it survives in the booking
snapshot on Recording.custom_properties["program"], and again at the top level
of Recording.custom_properties where prefetch_recording_artwork writes it. These
tests pin both fallbacks, and pin that a live ProgramData row still wins.
"""
import re
from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from apps.channels.models import Channel, Recording
from apps.channels.tasks import _build_output_paths, _parse_epg_tv_movie_info
from apps.epg.models import EPGData, EPGSource, ProgramData


class ParseEpgIdentityTests(TestCase):
    """_parse_epg_tv_movie_info falls back to the booking snapshot."""

    def setUp(self):
        self.source = EPGSource.objects.create(name="ident-src", source_type="xmltv")
        self.epg = EPGData.objects.create(tvg_id="ident.channel", name="Ident Channel")

    def _live_program(self, props):
        start = timezone.now() + timedelta(hours=1)
        return ProgramData.objects.create(
            epg=self.epg,
            tvg_id="ident.channel",
            start_time=start,
            end_time=start + timedelta(hours=1),
            title="Ident Show",
            sub_title="",
            custom_properties=props,
        )

    def test_live_row_still_wins(self):
        """The existing path is untouched when the row is present."""
        prog = self._live_program({"season": 4, "episode": 11})
        _movie, season, episode, _year, _sub = _parse_epg_tv_movie_info(
            {"id": prog.id, "title": "Ident Show", "season": 99, "episode": 99}
        )
        self.assertEqual((season, episode), (4, 11))

    def test_snapshot_used_when_row_deleted(self):
        """The reported bug: a reissued EPG leaves the id resolving to nothing."""
        prog = self._live_program({"season": 4, "episode": 11})
        prog_id = prog.id
        prog.delete()

        _movie, season, episode, _year, _sub = _parse_epg_tv_movie_info(
            {"id": prog_id, "title": "Ident Show", "season": 26, "episode": 238}
        )
        self.assertEqual((season, episode), (26, 238))

    def test_onscreen_episode_parsed_from_snapshot(self):
        """Snapshots carrying only an onscreen string still yield an index."""
        _movie, season, episode, _year, _sub = _parse_epg_tv_movie_info(
            {"id": 999999, "title": "Ident Show", "onscreen_episode": "S03E07"}
        )
        self.assertEqual((season, episode), (3, 7))

    def test_absent_identity_stays_none(self):
        """No identity anywhere must not invent one."""
        _movie, season, episode, _year, _sub = _parse_epg_tv_movie_info(
            {"id": 999999, "title": "Ident Show"}
        )
        self.assertIsNone(season)
        self.assertIsNone(episode)


@patch("apps.channels.signals.schedule_recording_task", return_value="mock-task-id")
class BuildOutputPathIdentityTests(TestCase):
    """_build_output_paths keeps SxxExx when only the Recording knows the index."""

    def setUp(self):
        self.channel = Channel.objects.create(channel_number=91, name="Ident Channel")
        self.start = timezone.now() + timedelta(hours=1)
        self.end = self.start + timedelta(hours=1)

    def _recording(self, props, _sched):
        return Recording.objects.create(
            channel=self.channel,
            start_time=self.start,
            end_time=self.end,
            custom_properties=props,
        )

    def test_recording_properties_supply_missing_index(self, _sched):
        """prefetch_recording_artwork's season/episode rescue the filename.

        The booking snapshot here has no season/episode at all -- the shape of a
        recording scheduled before the artwork prefetch ran -- so without the
        recording-level fallback this lands on the date-based template.
        """
        rec = self._recording(
            {
                "program": {"id": 999999, "title": "Ident Show"},
                "season": "26",
                "episode": "238",
            },
            _sched,
        )
        final_path, _hls, filename = _build_output_paths(
            self.channel,
            rec.custom_properties["program"],
            self.start,
            self.end,
            rec.id,
        )
        self.assertIn("S26E238", filename)
        self.assertIn("S26E238", final_path)

    def test_snapshot_identity_reaches_the_filename(self, _sched):
        """The season/episode on the snapshot are enough on their own."""
        rec = self._recording(
            {"program": {"id": 999999, "title": "Ident Show", "season": 3, "episode": 7}},
            _sched,
        )
        _final, _hls, filename = _build_output_paths(
            self.channel,
            rec.custom_properties["program"],
            self.start,
            self.end,
            rec.id,
        )
        self.assertIn("S03E07", filename)

    def test_no_identity_anywhere_still_uses_fallback(self, _sched):
        """The fallback template must remain reachable for genuinely bare EPGs.

        Some programmes (rolling news bulletins, magazine strands) carry no
        episode numbering at all; those must keep taking the date-based name
        rather than being forced to a bogus S00E00.
        """
        rec = self._recording({"program": {"id": 999999, "title": "Ident Show"}}, _sched)
        _final, _hls, filename = _build_output_paths(
            self.channel,
            rec.custom_properties["program"],
            self.start,
            self.end,
            rec.id,
        )
        # Asserted against the shape rather than a specific fallback template,
        # since the configured fallback differs between installs.
        self.assertIsNone(re.search(r"S\d+E\d+", filename))
