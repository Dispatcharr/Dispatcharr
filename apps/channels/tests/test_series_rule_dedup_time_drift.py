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

Two dedup paths are exercised separately:
- Episode identity (season/episode, onscreen, or sub_title). The default
  _create_program fixture includes sub_title="Episode 1", so tests that use it
  hit this path, not the time window.
- A 15-minute start-time window for programmes with no identity at all, and
  only when the recording's original start/end is gone from the current EPG.

The base class is imported rather than duplicated so both suites stay on one
definition of the fixture.
"""
from datetime import timedelta
from unittest.mock import patch

from apps.channels.models import Recording
from apps.channels.tests.test_series_rule_dedup import SeriesRuleDedupBaseTestCase
from apps.epg.models import ProgramData


@patch("apps.channels.tasks.prefetch_recording_artwork")
@patch("apps.channels.signals.schedule_recording_task", return_value="mock-task-id")
class EPGTimeDriftTests(SeriesRuleDedupBaseTestCase):
    """A refresh that nudges programme boundaries must not duplicate the airing."""

    def _refresh_with_drift(self, prog, start_delta=None, end_delta=None):
        """Re-create the programme with its boundaries moved by the given deltas."""
        data = {
            "tvg_id": prog.tvg_id,
            "start_time": prog.start_time + (start_delta or timedelta(0)),
            "end_time": prog.end_time + (end_delta or timedelta(0)),
            "title": prog.title,
            "sub_title": prog.sub_title,
        }
        if prog.custom_properties:
            data["custom_properties"] = prog.custom_properties
        return self._simulate_epg_refresh([data])

    def _create_identity_less_program(self, hours_from_now=2, title="Test Show",
                                      start=None, duration=None):
        """Programme with no season/episode, onscreen id, or sub_title."""
        start = start if start is not None else self.now + timedelta(hours=hours_from_now)
        end = start + (duration or timedelta(hours=1))
        return ProgramData.objects.create(
            epg=self.epg,
            tvg_id="test.channel.1",
            start_time=start,
            end_time=end,
            title=title,
            sub_title="",
        )

    @patch("apps.channels.tasks.acquire_task_lock", return_value=True)
    @patch("apps.channels.tasks.release_task_lock")
    def test_subtitle_identity_dedups_when_start_time_drifts(
            self, mock_release, mock_lock, mock_schedule, mock_artwork):
        """sub_title identity absorbs a start-time nudge. Default fixture has a sub_title."""
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
    def test_subtitle_identity_dedups_when_only_end_time_drifts(
            self, mock_release, mock_lock, mock_schedule, mock_artwork):
        """sub_title identity still matches when only the end boundary moves."""
        from apps.channels.tasks import evaluate_series_rules_impl

        prog = self._create_program(hours_from_now=2)
        self.assertEqual(evaluate_series_rules_impl()["scheduled"], 1)

        self._refresh_with_drift(prog, end_delta=timedelta(minutes=-2))

        result = evaluate_series_rules_impl()
        self.assertEqual(result["scheduled"], 0)
        self.assertEqual(Recording.objects.count(), 1)

    @patch("apps.channels.tasks.acquire_task_lock", return_value=True)
    @patch("apps.channels.tasks.release_task_lock")
    def test_subtitle_identity_dedups_across_repeated_drifting_refreshes(
            self, mock_release, mock_lock, mock_schedule, mock_artwork):
        """sub_title identity must not accumulate recordings as drift compounds."""
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
    def test_episode_identity_dedups_drift_beyond_tolerance(
            self, mock_release, mock_lock, mock_schedule, mock_artwork):
        """season/episode is exact and stable, so it absorbs drift of any size.

        The drift here is deliberately far wider than the start-time tolerance,
        so only the identity guard can catch it.
        """
        from apps.channels.tasks import evaluate_series_rules_impl

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
    def test_tolerance_covers_programme_with_no_identity(
            self, mock_release, mock_lock, mock_schedule, mock_artwork):
        """With no season/episode, onscreen id or sub-title, the window is all there is.

        This is the shape that actually duplicated in the wild: a news bulletin
        carrying no episode identity at all. The original slot is gone after
        the refresh, so the window is allowed to treat the nudged row as the
        same airing.
        """
        from apps.channels.tasks import evaluate_series_rules_impl

        prog = self._create_identity_less_program(hours_from_now=2)
        self.assertEqual(evaluate_series_rules_impl()["scheduled"], 1)

        self._refresh_with_drift(prog, start_delta=timedelta(seconds=45))

        result = evaluate_series_rules_impl()
        self.assertEqual(result["scheduled"], 0)
        self.assertEqual(Recording.objects.count(), 1)

    @patch("apps.channels.tasks.acquire_task_lock", return_value=True)
    @patch("apps.channels.tasks.release_task_lock")
    def test_tolerance_covers_identity_less_end_only_drift(
            self, mock_release, mock_lock, mock_schedule, mock_artwork):
        """End-only drift still misses the exact key. Start is unchanged, so the
        live-EPG check must use start AND end: if it keyed on start alone it
        would think the original slot was still listed and schedule a duplicate.
        """
        from apps.channels.tasks import evaluate_series_rules_impl

        prog = self._create_identity_less_program(hours_from_now=2)
        self.assertEqual(evaluate_series_rules_impl()["scheduled"], 1)

        self._refresh_with_drift(prog, end_delta=timedelta(minutes=-2))

        result = evaluate_series_rules_impl()
        self.assertEqual(result["scheduled"], 0)
        self.assertEqual(Recording.objects.count(), 1)

    @patch("apps.channels.tasks.acquire_task_lock", return_value=True)
    @patch("apps.channels.tasks.release_task_lock")
    def test_identity_less_programmes_inside_window_both_recorded_same_pass(
            self, mock_release, mock_lock, mock_schedule, mock_artwork):
        """Two current EPG listings of the same title, no identity, 10 minutes
        apart, must both be recorded in one evaluation.

        The original slot is still listed, so the time window must not treat
        the later programme as a drifted copy of the first.
        """
        from apps.channels.tasks import evaluate_series_rules_impl

        start = self.now + timedelta(hours=2)
        self._create_identity_less_program(
            start=start, duration=timedelta(minutes=10)
        )
        self._create_identity_less_program(
            start=start + timedelta(minutes=10), duration=timedelta(minutes=10)
        )

        result = evaluate_series_rules_impl()
        self.assertEqual(result["scheduled"], 2)
        self.assertEqual(Recording.objects.count(), 2)

    @patch("apps.channels.tasks.acquire_task_lock", return_value=True)
    @patch("apps.channels.tasks.release_task_lock")
    def test_identity_less_programmes_inside_window_both_recorded_across_evals(
            self, mock_release, mock_lock, mock_schedule, mock_artwork):
        """Same as the same-pass case, but the second listing appears after the
        first is already scheduled. Times did not drift: the original 9:00-9:10
        slot is still in the EPG, so 9:10-9:20 is a different airing.
        """
        from apps.channels.tasks import evaluate_series_rules_impl

        start = self.now + timedelta(hours=2)
        self._create_identity_less_program(
            start=start, duration=timedelta(minutes=10)
        )
        self.assertEqual(evaluate_series_rules_impl()["scheduled"], 1)

        self._create_identity_less_program(
            start=start + timedelta(minutes=10), duration=timedelta(minutes=10)
        )

        result = evaluate_series_rules_impl()
        self.assertEqual(result["scheduled"], 1)
        self.assertEqual(Recording.objects.count(), 2)

    @patch("apps.channels.tasks.acquire_task_lock", return_value=True)
    @patch("apps.channels.tasks.release_task_lock")
    def test_orphaned_recording_does_not_swallow_two_candidates(
            self, mock_release, mock_lock, mock_schedule, mock_artwork):
        """One drifted recording may claim at most one replacement candidate.

        A recording's slot drifts (so it is "orphaned": its original start/end
        is gone from the EPG) at the same time a genuinely separate, unrelated
        same-title programme appears nearby. Both candidates fall inside the
        tolerance window of the one orphaned recording. Only the closer one
        (the true drift replacement) may be absorbed by it; the other is a
        distinct airing and must still get its own recording. Without this
        guard, a single orphaned recording could suppress every nearby
        candidate, silently dropping a recording the rule matched.
        """
        from apps.channels.tasks import evaluate_series_rules_impl

        start = self.now + timedelta(hours=2)
        prog = self._create_identity_less_program(
            start=start, duration=timedelta(minutes=10)
        )
        self.assertEqual(evaluate_series_rules_impl()["scheduled"], 1)
        self.assertEqual(Recording.objects.count(), 1)

        # The original 9:00-9:10 slot drifts to 9:00:45-9:10:45 (its replacement,
        # close to the recording), and a distinct 9:05-9:15 listing also appears
        # (same title, no identity, well within the 15-minute tolerance).
        ProgramData.objects.filter(id=prog.id).delete()
        ProgramData.objects.create(
            epg=self.epg, tvg_id="test.channel.1",
            start_time=start + timedelta(seconds=45),
            end_time=start + timedelta(minutes=10, seconds=45),
            title="Test Show", sub_title="",
        )
        ProgramData.objects.create(
            epg=self.epg, tvg_id="test.channel.1",
            start_time=start + timedelta(minutes=5),
            end_time=start + timedelta(minutes=15),
            title="Test Show", sub_title="",
        )

        result = evaluate_series_rules_impl()
        self.assertEqual(result["scheduled"], 1,
                         "the unrelated nearby listing must still be recorded")
        self.assertEqual(Recording.objects.count(), 2)

    @patch("apps.channels.tasks.acquire_task_lock", return_value=True)
    @patch("apps.channels.tasks.release_task_lock")
    def test_shared_subtitle_different_episode_inside_window(
            self, mock_release, mock_lock, mock_schedule, mock_artwork):
        """A generic sub-title must not let the window swallow a distinct episode.

        Back-to-back programmes can share a boilerplate sub-title while differing
        by season/episode. Identity is authoritative whenever it exists, so the
        second airing is scheduled even though it starts inside the window.
        """
        from apps.channels.tasks import evaluate_series_rules_impl

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
    def test_distinct_episodes_inside_window_not_merged(
            self, mock_release, mock_lock, mock_schedule, mock_artwork):
        """Two different episodes closer together than the tolerance stay distinct.

        These have distinct sub_titles, so identity (not the time window) keeps
        them apart.
        """
        from apps.channels.tasks import evaluate_series_rules_impl

        first = self._create_program(hours_from_now=2, sub_title="Episode 1")
        self.assertEqual(evaluate_series_rules_impl()["scheduled"], 1)

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
    def test_different_titles_at_same_time_not_merged(
            self, mock_release, mock_lock, mock_schedule, mock_artwork):
        """The tolerance is scoped per title, so a different show is unaffected."""
        from apps.channels.tasks import evaluate_series_rules_impl

        self._create_program(hours_from_now=2)
        self.assertEqual(evaluate_series_rules_impl()["scheduled"], 1)

        # A different programme starting inside the tolerance window. It does not
        # match the rule, so it must not be scheduled, and equally must not be
        # confused with the scheduled airing.
        self._create_program(hours_from_now=2, title="Another Show")

        result = evaluate_series_rules_impl()
        self.assertEqual(result["scheduled"], 0)
        self.assertEqual(Recording.objects.count(), 1)
