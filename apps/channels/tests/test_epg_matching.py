"""Tests for the _match_epg_program_by_timeslot() helper in tasks.py.

Covers:
  - Exact time-slot match returns program dict
  - 80% overlap threshold: at boundary, above, and below
  - Multiple overlapping programs: dominant vs. evenly split
  - Edge cases: None inputs, zero-duration recording, no EPG data
  - Returned dict structure (id, title, sub_title, description)
"""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from apps.channels.models import Channel
from apps.epg.models import EPGSource, EPGData, ProgramData
from apps.channels.tasks import _match_epg_program_by_timeslot


class EpgMatchingSetupMixin:
    """Shared setup for EPG matching tests."""

    def setUp(self):
        self.source = EPGSource.objects.create(name="Test Source")
        self.epg = EPGData.objects.create(
            tvg_id="test.channel", name="Test Channel EPG", epg_source=self.source,
        )
        self.channel = Channel.objects.create(
            channel_number=50, name="EPG Match Channel", epg_data=self.epg,
        )
        self.base = timezone.now().replace(second=0, microsecond=0)

    def _prog(self, offset_min, duration_min, title="Test Show", **kwargs):
        """Create a ProgramData starting offset_min from self.base."""
        start = self.base + timedelta(minutes=offset_min)
        end = start + timedelta(minutes=duration_min)
        return ProgramData.objects.create(
            epg=self.epg, start_time=start, end_time=end, title=title, **kwargs,
        )


class ExactMatchTests(EpgMatchingSetupMixin, TestCase):
    """Recording window exactly matches an EPG program."""

    def test_exact_match_returns_program_dict(self):
        prog = self._prog(0, 60, title="News at 9", sub_title="Top Stories",
                          description="Evening news broadcast")
        result = _match_epg_program_by_timeslot(
            self.epg, prog.start_time, prog.end_time,
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["id"], prog.id)
        self.assertEqual(result["title"], "News at 9")
        self.assertEqual(result["sub_title"], "Top Stories")
        self.assertEqual(result["description"], "Evening news broadcast")

    def test_missing_optional_fields_returned_as_empty_strings(self):
        prog = self._prog(0, 30, title="Minimal Show")
        result = _match_epg_program_by_timeslot(
            self.epg, prog.start_time, prog.end_time,
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["sub_title"], "")
        self.assertEqual(result["description"], "")


class OverlapThresholdTests(EpgMatchingSetupMixin, TestCase):
    """80% overlap threshold boundary tests."""

    def test_exactly_80_percent_overlap_returns_match(self):
        """Program covers exactly 80% of the recording window."""
        # Program: 0-60min, Recording: 0-75min → overlap = 60/75 = 80%
        prog = self._prog(0, 60, title="Borderline Show")
        rec_start = self.base
        rec_end = self.base + timedelta(minutes=75)
        result = _match_epg_program_by_timeslot(self.epg, rec_start, rec_end)
        self.assertIsNotNone(result)
        self.assertEqual(result["title"], "Borderline Show")

    def test_below_80_percent_returns_none(self):
        """Program covers 79% of the recording — below threshold."""
        # Program: 0-60min, Recording: 0-76min → overlap = 60/76 ≈ 78.9%
        prog = self._prog(0, 60, title="Too Short")
        rec_start = self.base
        rec_end = self.base + timedelta(minutes=76)
        result = _match_epg_program_by_timeslot(self.epg, rec_start, rec_end)
        self.assertIsNone(result)

    def test_above_80_percent_returns_match(self):
        """Program covers 90% of the recording."""
        # Program: 0-60min, Recording: 0-66min → overlap = 60/66 ≈ 90.9%
        prog = self._prog(0, 60, title="Good Match")
        rec_start = self.base
        rec_end = self.base + timedelta(minutes=66)
        result = _match_epg_program_by_timeslot(self.epg, rec_start, rec_end)
        self.assertIsNotNone(result)
        self.assertEqual(result["title"], "Good Match")


class MultipleProgramTests(EpgMatchingSetupMixin, TestCase):
    """Recording spans multiple EPG programs."""

    def test_dominant_program_returned(self):
        """Recording spans 2 programs; one covers 85%, the other 15%."""
        # Show A: 0-60min, Show B: 60-120min
        # Recording: 9-69min → A overlap=51/60=85%, B overlap=9/60=15%
        self._prog(0, 60, title="Show A")
        self._prog(60, 60, title="Show B")
        rec_start = self.base + timedelta(minutes=9)
        rec_end = self.base + timedelta(minutes=69)
        result = _match_epg_program_by_timeslot(self.epg, rec_start, rec_end)
        self.assertIsNotNone(result)
        self.assertEqual(result["title"], "Show A")

    def test_evenly_split_returns_none(self):
        """Recording spans 2 equal programs — neither reaches 80%."""
        # Show A: 0-60min, Show B: 60-120min
        # Recording: 30-90min → each covers 50%
        self._prog(0, 60, title="Show A")
        self._prog(60, 60, title="Show B")
        rec_start = self.base + timedelta(minutes=30)
        rec_end = self.base + timedelta(minutes=90)
        result = _match_epg_program_by_timeslot(self.epg, rec_start, rec_end)
        self.assertIsNone(result)

    def test_three_programs_one_dominant(self):
        """Recording spans 3 programs; middle one is dominant."""
        # A: 0-30min, B: 30-90min, C: 90-120min
        # Recording: 25-95min (70min window) → B overlap=60/70≈85.7%
        self._prog(0, 30, title="Show A")
        self._prog(30, 60, title="Show B")
        self._prog(90, 30, title="Show C")
        rec_start = self.base + timedelta(minutes=25)
        rec_end = self.base + timedelta(minutes=95)
        result = _match_epg_program_by_timeslot(self.epg, rec_start, rec_end)
        self.assertIsNotNone(result)
        self.assertEqual(result["title"], "Show B")


class EdgeCaseTests(EpgMatchingSetupMixin, TestCase):
    """Edge cases and error handling."""

    def test_none_epg_data_returns_none(self):
        result = _match_epg_program_by_timeslot(None, self.base, self.base + timedelta(hours=1))
        self.assertIsNone(result)

    def test_none_start_time_returns_none(self):
        result = _match_epg_program_by_timeslot(self.epg, None, self.base + timedelta(hours=1))
        self.assertIsNone(result)

    def test_none_end_time_returns_none(self):
        result = _match_epg_program_by_timeslot(self.epg, self.base, None)
        self.assertIsNone(result)

    def test_zero_duration_returns_none(self):
        """Recording with start == end should return None."""
        result = _match_epg_program_by_timeslot(self.epg, self.base, self.base)
        self.assertIsNone(result)

    def test_negative_duration_returns_none(self):
        """Recording with end before start should return None."""
        result = _match_epg_program_by_timeslot(
            self.epg, self.base + timedelta(hours=1), self.base,
        )
        self.assertIsNone(result)

    def test_no_overlapping_programs_returns_none(self):
        """No EPG programs in the recording window."""
        self._prog(0, 60, title="Earlier Show")
        rec_start = self.base + timedelta(hours=5)
        rec_end = rec_start + timedelta(hours=1)
        result = _match_epg_program_by_timeslot(self.epg, rec_start, rec_end)
        self.assertIsNone(result)

    def test_empty_epg_no_programs_returns_none(self):
        """EPGData exists but has no programs."""
        result = _match_epg_program_by_timeslot(
            self.epg, self.base, self.base + timedelta(hours=1),
        )
        self.assertIsNone(result)
