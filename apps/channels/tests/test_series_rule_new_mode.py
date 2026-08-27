"""Tests for the series rule mode="new" untagged_is_new toggle.

XMLTV lets a feed mark first runs with <new/> or mark repeats with
<previously-shown/>. Default mode="new" behaviour accepts only <new/>;
the per-rule untagged_is_new flag opts in to also treating a programme
carrying neither tag as new, for feeds that only tag repeats.
"""
from datetime import timedelta
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.channels.managers import program_is_new_for_rule
from apps.channels.models import Recording
from apps.channels.tests.test_series_rule_dedup import (
    SeriesRuleDedupBaseTestCase,
    _set_series_rules,
)


class ProgramIsNewForRuleTests(SimpleTestCase):
    """Unit tests for the shared mode="new" predicate."""

    def test_default_requires_new_tag(self):
        self.assertTrue(program_is_new_for_rule({"new": True}))
        self.assertFalse(program_is_new_for_rule({}))
        self.assertFalse(program_is_new_for_rule({"previously_shown": True}))

    def test_untagged_counts_when_flag_on(self):
        self.assertTrue(program_is_new_for_rule({}, untagged_is_new=True))
        self.assertTrue(
            program_is_new_for_rule(
                {"season": 1, "episode": 2}, untagged_is_new=True
            )
        )

    def test_previously_shown_excluded_when_flag_on(self):
        self.assertFalse(
            program_is_new_for_rule(
                {"previously_shown": True}, untagged_is_new=True
            )
        )

    def test_explicit_new_wins_over_previously_shown(self):
        self.assertTrue(
            program_is_new_for_rule(
                {"new": True, "previously_shown": True},
                untagged_is_new=True,
            )
        )

    def test_original_air_date_alone_is_untagged(self):
        # episode-num original-air-date fills previously_shown_details without
        # setting previously_shown; that is not a repeat tag.
        self.assertTrue(
            program_is_new_for_rule(
                {"previously_shown_details": {"start": "2026-06-24"}},
                untagged_is_new=True,
            )
        )


@patch("apps.channels.tasks.prefetch_recording_artwork")
@patch("apps.channels.signals.schedule_recording_task", return_value="mock-task-id")
class SeriesRuleNewModeTests(SeriesRuleDedupBaseTestCase):
    """mode="new" default behaviour and the untagged_is_new opt-in."""

    def _set_rule(self, **extra):
        _set_series_rules([{
            "tvg_id": "test.channel.1",
            "mode": "new",
            "title": "Test Show",
            **extra,
        }])

    def _programme(self, hours, props, sub_title="Episode 1"):
        from apps.epg.models import ProgramData
        start = self.now + timedelta(hours=hours)
        return ProgramData.objects.create(
            epg=self.epg, tvg_id="test.channel.1",
            start_time=start, end_time=start + timedelta(hours=1),
            title="Test Show", sub_title=sub_title,
            custom_properties=props,
        )

    @patch("apps.channels.tasks.acquire_task_lock", return_value=True)
    @patch("apps.channels.tasks.release_task_lock")
    def test_new_tag_recorded_by_default(self, mock_release, mock_lock,
                                         mock_schedule, mock_artwork):
        """Default: a <new/> tag records, with or without the flag."""
        from apps.channels.tasks import evaluate_series_rules_impl

        self._set_rule()
        self._programme(2, {"new": True})
        self.assertEqual(evaluate_series_rules_impl()["scheduled"], 1)
        self.assertEqual(Recording.objects.count(), 1)

    @patch("apps.channels.tasks.acquire_task_lock", return_value=True)
    @patch("apps.channels.tasks.release_task_lock")
    def test_untagged_skipped_by_default(self, mock_release, mock_lock,
                                         mock_schedule, mock_artwork):
        """Default: a programme with neither tag is not assumed new."""
        from apps.channels.tasks import evaluate_series_rules_impl

        self._set_rule()
        self._programme(2, {"season": 22, "episode": 13})
        self.assertEqual(evaluate_series_rules_impl()["scheduled"], 0)
        self.assertEqual(Recording.objects.count(), 0)

    @patch("apps.channels.tasks.acquire_task_lock", return_value=True)
    @patch("apps.channels.tasks.release_task_lock")
    def test_untagged_recorded_with_flag(self, mock_release, mock_lock,
                                         mock_schedule, mock_artwork):
        """untagged_is_new: a feed that marks only repeats records first runs."""
        from apps.channels.tasks import evaluate_series_rules_impl

        self._set_rule(untagged_is_new=True)
        self._programme(2, {"season": 22, "episode": 13})
        self.assertEqual(evaluate_series_rules_impl()["scheduled"], 1)
        self.assertEqual(Recording.objects.count(), 1)

    @patch("apps.channels.tasks.acquire_task_lock", return_value=True)
    @patch("apps.channels.tasks.release_task_lock")
    def test_previously_shown_skipped_with_flag(self, mock_release, mock_lock,
                                                mock_schedule, mock_artwork):
        """untagged_is_new: a marked repeat is still excluded."""
        from apps.channels.tasks import evaluate_series_rules_impl

        self._set_rule(untagged_is_new=True)
        self._programme(2, {
            "previously_shown": True,
            "previously_shown_details": {"start": "2026-08-01"},
        })
        self.assertEqual(evaluate_series_rules_impl()["scheduled"], 0)
        self.assertEqual(Recording.objects.count(), 0)

    @patch("apps.channels.tasks.acquire_task_lock", return_value=True)
    @patch("apps.channels.tasks.release_task_lock")
    def test_mixed_schedule_with_flag(self, mock_release, mock_lock,
                                      mock_schedule, mock_artwork):
        """untagged_is_new: evening first runs record, the daytime repeat does not."""
        from apps.channels.tasks import evaluate_series_rules_impl

        self._set_rule(untagged_is_new=True)
        self._programme(2, {"season": 22, "episode": 13}, sub_title="Ep 13")
        self._programme(4, {
            "season": 22,
            "episode": 12,
            "previously_shown": True,
            "previously_shown_details": {"start": "2026-08-18"},
        }, sub_title="Ep 12")
        self._programme(6, {"season": 22, "episode": 14}, sub_title="Ep 14")

        self.assertEqual(evaluate_series_rules_impl()["scheduled"], 2)
        self.assertEqual(Recording.objects.count(), 2)

    @patch("apps.channels.tasks.acquire_task_lock", return_value=True)
    @patch("apps.channels.tasks.release_task_lock")
    def test_new_tag_wins_over_previously_shown(self, mock_release, mock_lock,
                                                mock_schedule, mock_artwork):
        """An explicit <new/> is authoritative even alongside a previously-shown date."""
        from apps.channels.tasks import evaluate_series_rules_impl

        self._set_rule(untagged_is_new=True)
        self._programme(2, {
            "new": True,
            "previously_shown": True,
            "previously_shown_details": {"start": "2026-08-01"},
        })
        self.assertEqual(evaluate_series_rules_impl()["scheduled"], 1)
        self.assertEqual(Recording.objects.count(), 1)
