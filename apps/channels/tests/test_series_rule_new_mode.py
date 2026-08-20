"""Tests for series rule mode="new" against both XMLTV freshness conventions.

XMLTV lets a feed mark first runs with <new/> or mark repeats with
<previously-shown/>. Accepting only the first convention makes a mode="new" rule
match nothing at all on a feed that uses the second, and the failure is silent:
a rule that matches nothing looks exactly like a show that is not airing.
"""
from datetime import timedelta
from unittest.mock import patch

from apps.channels.models import Recording
from apps.channels.tests.test_series_rule_dedup import (
    SeriesRuleDedupBaseTestCase,
    _set_series_rules,
)


@patch("apps.channels.tasks.prefetch_recording_artwork")
@patch("apps.channels.signals.schedule_recording_task", return_value="mock-task-id")
class SeriesRuleNewModeTests(SeriesRuleDedupBaseTestCase):
    """mode="new" must recognise first runs under either convention."""

    def setUp(self):
        super().setUp()
        _set_series_rules([{
            "tvg_id": "test.channel.1",
            "mode": "new",
            "title": "Test Show",
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
    def test_new_tag_still_recorded(self, mock_release, mock_lock,
                                    mock_schedule, mock_artwork):
        """The existing convention keeps working."""
        from apps.channels.tasks import evaluate_series_rules_impl

        self._programme(2, {"new": True})
        self.assertEqual(evaluate_series_rules_impl()["scheduled"], 1)
        self.assertEqual(Recording.objects.count(), 1)

    @patch("apps.channels.tasks.acquire_task_lock", return_value=True)
    @patch("apps.channels.tasks.release_task_lock")
    def test_previously_shown_is_skipped(self, mock_release, mock_lock,
                                         mock_schedule, mock_artwork):
        """A repeat marked <previously-shown/> must not be recorded."""
        from apps.channels.tasks import evaluate_series_rules_impl

        self._programme(2, {"previously_shown": "2026-08-01"})
        self.assertEqual(evaluate_series_rules_impl()["scheduled"], 0)
        self.assertEqual(Recording.objects.count(), 0)

    @patch("apps.channels.tasks.acquire_task_lock", return_value=True)
    @patch("apps.channels.tasks.release_task_lock")
    def test_untagged_first_run_is_recorded(self, mock_release, mock_lock,
                                            mock_schedule, mock_artwork):
        """A feed that marks only repeats: an untagged airing is a first run.

        Before this change such a programme was skipped, so a mode="new" rule on
        such a feed recorded nothing whatsoever.
        """
        from apps.channels.tasks import evaluate_series_rules_impl

        self._programme(2, {"season": 22, "episode": 13})
        self.assertEqual(evaluate_series_rules_impl()["scheduled"], 1)
        self.assertEqual(Recording.objects.count(), 1)

    @patch("apps.channels.tasks.acquire_task_lock", return_value=True)
    @patch("apps.channels.tasks.release_task_lock")
    def test_mixed_schedule_records_only_first_runs(self, mock_release, mock_lock,
                                                    mock_schedule, mock_artwork):
        """The real shape of an affected feed: evening first runs, daytime repeats."""
        from apps.channels.tasks import evaluate_series_rules_impl

        self._programme(2, {"season": 22, "episode": 13}, sub_title="Ep 13")
        self._programme(4, {"season": 22, "episode": 12,
                            "previously_shown": "2026-08-18"}, sub_title="Ep 12")
        self._programme(6, {"season": 22, "episode": 14}, sub_title="Ep 14")

        self.assertEqual(evaluate_series_rules_impl()["scheduled"], 2)
        self.assertEqual(Recording.objects.count(), 2)

    @patch("apps.channels.tasks.acquire_task_lock", return_value=True)
    @patch("apps.channels.tasks.release_task_lock")
    def test_new_tag_wins_over_previously_shown(self, mock_release, mock_lock,
                                                mock_schedule, mock_artwork):
        """An explicit <new/> is authoritative even alongside a previously-shown date."""
        from apps.channels.tasks import evaluate_series_rules_impl

        self._programme(2, {"new": True, "previously_shown": "2026-08-01"})
        self.assertEqual(evaluate_series_rules_impl()["scheduled"], 1)
        self.assertEqual(Recording.objects.count(), 1)
