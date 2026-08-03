"""Series rule dedup when EPG programme times drift between refreshes.

The suite in test_series_rule_dedup.py simulates a refresh by recreating
ProgramData with new IDs but IDENTICAL start/end times -- exactly the churn the
(tvg_id, start_time, end_time) key was introduced to absorb, and it does.

Real XMLTV feeds also move the boundaries themselves by small amounts between
refreshes. The exact key cannot absorb that: the refreshed programme no longer
matches the stored snapshot, so the same airing is scheduled a second time. Both
recordings then resolve to the same output path and overwrite each other.

These tests cover that second kind of refresh, and the case that must keep
working: a genuinely separate later airing of the same title is still recorded.

The base class is imported rather than duplicated so both suites stay on one
definition of the fixture.
"""
from datetime import timedelta
from unittest.mock import patch

from apps.channels.models import Recording
from apps.channels.tests.test_series_rule_dedup import SeriesRuleDedupBaseTestCase


@patch("apps.channels.tasks.prefetch_recording_artwork")
@patch("apps.channels.signals.schedule_recording_task", return_value="mock-task-id")
class EPGTimeDriftTests(SeriesRuleDedupBaseTestCase):
    """A refresh that nudges programme boundaries must not duplicate the airing."""

    def _refresh_with_drift(self, prog, start_delta=None, end_delta=None):
        """Re-create the programme with its boundaries moved by the given deltas."""
        return self._simulate_epg_refresh([{
            "tvg_id": prog.tvg_id,
            "start_time": prog.start_time + (start_delta or timedelta(0)),
            "end_time": prog.end_time + (end_delta or timedelta(0)),
            "title": prog.title,
            "sub_title": prog.sub_title,
        }])

    @patch("apps.channels.tasks.acquire_task_lock", return_value=True)
    @patch("apps.channels.tasks.release_task_lock")
    def test_no_duplicate_when_start_time_drifts(self, mock_release, mock_lock,
                                                 mock_schedule, mock_artwork):
        """A start time nudged by seconds is the same airing, not a new one."""
        from apps.channels.tasks import evaluate_series_rules_impl

        prog = self._create_program(hours_from_now=2)
        self.assertEqual(evaluate_series_rules_impl()["scheduled"], 1)
        self.assertEqual(Recording.objects.count(), 1)

        self._refresh_with_drift(prog, start_delta=timedelta(seconds=45))

        result = evaluate_series_rules_impl()
        self.assertEqual(result["scheduled"], 0)
        self.assertEqual(Recording.objects.count(), 1)

    @patch("apps.channels.tasks.acquire_task_lock", return_value=True)
    @patch("apps.channels.tasks.release_task_lock")
    def test_no_duplicate_when_only_end_time_drifts(self, mock_release, mock_lock,
                                                    mock_schedule, mock_artwork):
        """Drift in either boundary defeats the exact key -- here only the end moves."""
        from apps.channels.tasks import evaluate_series_rules_impl

        prog = self._create_program(hours_from_now=2)
        self.assertEqual(evaluate_series_rules_impl()["scheduled"], 1)

        self._refresh_with_drift(prog, end_delta=timedelta(minutes=-2))

        result = evaluate_series_rules_impl()
        self.assertEqual(result["scheduled"], 0)
        self.assertEqual(Recording.objects.count(), 1)

    @patch("apps.channels.tasks.acquire_task_lock", return_value=True)
    @patch("apps.channels.tasks.release_task_lock")
    def test_no_duplicate_across_repeated_drifting_refreshes(self, mock_release, mock_lock,
                                                             mock_schedule, mock_artwork):
        """Drift accumulating over successive refreshes must not accumulate recordings."""
        from apps.channels.tasks import evaluate_series_rules_impl

        prog = self._create_program(hours_from_now=3)
        self.assertEqual(evaluate_series_rules_impl()["scheduled"], 1)

        for _ in range(4):
            prog = self._refresh_with_drift(
                prog, start_delta=timedelta(seconds=30), end_delta=timedelta(seconds=30)
            )[0]
            evaluate_series_rules_impl()

        self.assertEqual(Recording.objects.count(), 1)

    @patch("apps.channels.tasks.acquire_task_lock", return_value=True)
    @patch("apps.channels.tasks.release_task_lock")
    def test_episode_identity_dedups_drift_beyond_tolerance(self, mock_release, mock_lock,
                                                            mock_schedule, mock_artwork):
        """season/episode is exact and stable, so it absorbs drift of any size.

        The drift here is deliberately far wider than the start-time tolerance,
        so only the identity guard can catch it.
        """
        from apps.channels.tasks import evaluate_series_rules_impl
        from apps.epg.models import ProgramData

        start = self.now + timedelta(hours=2)
        ProgramData.objects.create(
            epg=self.epg,
            tvg_id="test.channel.1",
            start_time=start,
            end_time=start + timedelta(hours=1),
            title="Test Show",
            sub_title="",
            custom_properties={"season": 2026, "episode": 24},
        )
        self.assertEqual(evaluate_series_rules_impl()["scheduled"], 1)

        self._simulate_epg_refresh([{
            "tvg_id": "test.channel.1",
            "start_time": start + timedelta(minutes=30),
            "end_time": start + timedelta(hours=1, minutes=30),
            "title": "Test Show",
            "sub_title": "",
            "custom_properties": {"season": 2026, "episode": 24},
        }])

        result = evaluate_series_rules_impl()
        self.assertEqual(result["scheduled"], 0)
        self.assertEqual(Recording.objects.count(), 1)

    @patch("apps.channels.tasks.acquire_task_lock", return_value=True)
    @patch("apps.channels.tasks.release_task_lock")
    def test_tolerance_covers_programme_with_no_identity(self, mock_release, mock_lock,
                                                         mock_schedule, mock_artwork):
        """With no season/episode, onscreen id or sub-title, the window is all there is.

        This is the shape that actually duplicated in the wild: a news bulletin
        carrying no episode identity at all.
        """
        from apps.channels.tasks import evaluate_series_rules_impl
        from apps.epg.models import ProgramData

        start = self.now + timedelta(hours=2)
        prog = ProgramData.objects.create(
            epg=self.epg,
            tvg_id="test.channel.1",
            start_time=start,
            end_time=start + timedelta(hours=1),
            title="Test Show",
            sub_title="",
        )
        self.assertEqual(evaluate_series_rules_impl()["scheduled"], 1)

        self._refresh_with_drift(prog, start_delta=timedelta(seconds=45))

        result = evaluate_series_rules_impl()
        self.assertEqual(result["scheduled"], 0)
        self.assertEqual(Recording.objects.count(), 1)

    @patch("apps.channels.tasks.acquire_task_lock", return_value=True)
    @patch("apps.channels.tasks.release_task_lock")
    def test_shared_subtitle_different_episode_inside_window(self, mock_release, mock_lock,
                                                             mock_schedule, mock_artwork):
        """A generic sub-title must not let the window swallow a distinct episode.

        Back-to-back programmes can share a boilerplate sub-title while differing
        by season/episode. Identity is authoritative whenever it exists, so the
        second airing is scheduled even though it starts inside the window.
        """
        from apps.channels.tasks import evaluate_series_rules_impl
        from apps.epg.models import ProgramData

        start = self.now + timedelta(hours=2)
        ProgramData.objects.create(
            epg=self.epg, tvg_id="test.channel.1",
            start_time=start, end_time=start + timedelta(minutes=10),
            title="Test Show", sub_title="News Update",
            custom_properties={"season": 3, "episode": 1},
        )
        self.assertEqual(evaluate_series_rules_impl()["scheduled"], 1)

        ProgramData.objects.create(
            epg=self.epg, tvg_id="test.channel.1",
            start_time=start + timedelta(minutes=10),
            end_time=start + timedelta(minutes=20),
            title="Test Show", sub_title="News Update",
            custom_properties={"season": 3, "episode": 2},
        )

        result = evaluate_series_rules_impl()
        self.assertEqual(result["scheduled"], 1)
        self.assertEqual(Recording.objects.count(), 2)

    @patch("apps.channels.tasks.acquire_task_lock", return_value=True)
    @patch("apps.channels.tasks.release_task_lock")
    def test_later_episode_still_recorded(self, mock_release, mock_lock,
                                          mock_schedule, mock_artwork):
        """A later episode of the same series must still get its own recording.

        The guard against over-merging: the tolerance must never swallow a
        programme that is genuinely a different airing.
        """
        from apps.channels.tasks import evaluate_series_rules_impl

        self._create_program(hours_from_now=2, sub_title="Episode 1")
        self.assertEqual(evaluate_series_rules_impl()["scheduled"], 1)

        self._create_program(hours_from_now=3, sub_title="Episode 2")

        result = evaluate_series_rules_impl()
        self.assertEqual(result["scheduled"], 1)
        self.assertEqual(Recording.objects.count(), 2)

    @patch("apps.channels.tasks.acquire_task_lock", return_value=True)
    @patch("apps.channels.tasks.release_task_lock")
    def test_distinct_episodes_inside_window_not_merged(self, mock_release, mock_lock,
                                                        mock_schedule, mock_artwork):
        """Two different episodes closer together than the tolerance stay distinct.

        The tolerance is scoped by episode identity, not just series, so short
        back-to-back programmes cannot be collapsed into one another the way a
        purely series-scoped window would collapse them.
        """
        from apps.channels.tasks import evaluate_series_rules_impl

        first = self._create_program(hours_from_now=2, sub_title="Episode 1")
        self.assertEqual(evaluate_series_rules_impl()["scheduled"], 1)

        ProgramData = type(first)
        ProgramData.objects.create(
            epg=self.epg,
            tvg_id=first.tvg_id,
            start_time=first.start_time + timedelta(minutes=10),
            end_time=first.end_time + timedelta(minutes=10),
            title=first.title,
            sub_title="Episode 2",
        )

        result = evaluate_series_rules_impl()
        self.assertEqual(result["scheduled"], 1)
        self.assertEqual(Recording.objects.count(), 2)

    @patch("apps.channels.tasks.acquire_task_lock", return_value=True)
    @patch("apps.channels.tasks.release_task_lock")
    def test_different_titles_at_same_time_not_merged(self, mock_release, mock_lock,
                                                      mock_schedule, mock_artwork):
        """The tolerance is scoped per title, so a different show is unaffected."""
        from apps.channels.tasks import evaluate_series_rules_impl

        self._create_program(hours_from_now=2)
        self.assertEqual(evaluate_series_rules_impl()["scheduled"], 1)

        # A different programme starting inside the tolerance window. It does not
        # match the rule, so it must not be scheduled -- and equally must not be
        # confused with the scheduled airing.
        self._create_program(hours_from_now=2, title="Another Show")

        result = evaluate_series_rules_impl()
        self.assertEqual(result["scheduled"], 0)
        self.assertEqual(Recording.objects.count(), 1)
