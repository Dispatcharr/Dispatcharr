"""Tests for series rule evaluation deduplication.

Unit tests verify the dedup logic in evaluate_series_rules_impl.
Integration tests exercise the full path: EPG refresh → series rule
evaluation → Recording creation → post_save signal chain.
"""
from datetime import timedelta
from unittest.mock import patch, MagicMock

from django.test import TestCase
from django.utils import timezone

from apps.channels.models import Channel, Recording
from apps.epg.models import EPGSource, EPGData, ProgramData
from core.models import CoreSettings


def _set_series_rules(rules):
    """Helper to store series rules in CoreSettings."""
    CoreSettings.set_dvr_series_rules(rules)


def _set_dvr_offsets(pre_min=0, post_min=0):
    """Helper to store DVR pre/post offsets."""
    CoreSettings._update_group("dvr_settings", "DVR Settings", {
        "pre_offset_minutes": pre_min,
        "post_offset_minutes": post_min,
    })


class SeriesRuleDedupBaseTestCase(TestCase):
    """Shared setup for series rule dedup tests."""

    def setUp(self):
        self.now = timezone.now()
        self.epg_source = EPGSource.objects.create(
            name="Test EPG", source_type="xmltv"
        )
        self.epg = EPGData.objects.create(
            tvg_id="test.channel.1",
            name="Test Channel EPG",
            epg_source=self.epg_source,
        )
        self.channel = Channel.objects.create(
            channel_number=1, name="Test Channel", epg_data=self.epg
        )

        _set_series_rules([{
            "tvg_id": "test.channel.1",
            "mode": "all",
            "title": "Test Show",
        }])
        _set_dvr_offsets(pre_min=0, post_min=0)

    def _create_program(self, hours_from_now=1, title="Test Show",
                        sub_title="Episode 1", tvg_id="test.channel.1"):
        """Create a ProgramData at the given offset."""
        start = self.now + timedelta(hours=hours_from_now)
        end = start + timedelta(hours=1)
        return ProgramData.objects.create(
            epg=self.epg,
            tvg_id=tvg_id,
            start_time=start,
            end_time=end,
            title=title,
            sub_title=sub_title,
        )

    def _simulate_epg_refresh(self, programs_data):
        """Delete all ProgramData and recreate with new IDs (simulates EPG refresh)."""
        ProgramData.objects.filter(epg=self.epg).delete()
        new_programs = []
        for data in programs_data:
            prog = ProgramData.objects.create(epg=self.epg, **data)
            new_programs.append(prog)
        return new_programs

    def _program_data_for_refresh(self, prog):
        """Build the dict needed by _simulate_epg_refresh from a ProgramData."""
        return {
            "tvg_id": prog.tvg_id,
            "start_time": prog.start_time,
            "end_time": prog.end_time,
            "title": prog.title,
            "sub_title": prog.sub_title,
        }


# ---------------------------------------------------------------------------
# Unit tests: dedup logic in evaluate_series_rules_impl
# ---------------------------------------------------------------------------

@patch("apps.channels.tasks.prefetch_recording_artwork")
@patch("apps.channels.signals.schedule_recording_task", return_value="mock-task-id")
class ProgramIdStabilityTests(SeriesRuleDedupBaseTestCase):
    """Verify dedup works after EPG refresh changes ProgramData IDs."""

    @patch("apps.channels.tasks.acquire_task_lock", return_value=True)
    @patch("apps.channels.tasks.release_task_lock")
    def test_no_duplicate_after_epg_refresh(self, mock_release, mock_lock,
                                            mock_schedule, mock_artwork):
        """Same program should not be recorded twice after EPG refresh."""
        from apps.channels.tasks import evaluate_series_rules_impl

        prog = self._create_program(hours_from_now=2)
        old_id = prog.id
        result1 = evaluate_series_rules_impl()
        self.assertEqual(result1["scheduled"], 1)
        self.assertEqual(Recording.objects.count(), 1)

        new_programs = self._simulate_epg_refresh(
            [self._program_data_for_refresh(prog)]
        )
        self.assertNotEqual(old_id, new_programs[0].id)

        result2 = evaluate_series_rules_impl()
        self.assertEqual(Recording.objects.count(), 1)
        self.assertEqual(result2["scheduled"], 0)

    @patch("apps.channels.tasks.acquire_task_lock", return_value=True)
    @patch("apps.channels.tasks.release_task_lock")
    def test_no_duplicate_with_offsets_after_refresh(self, mock_release, mock_lock,
                                                     mock_schedule, mock_artwork):
        """Dedup works when DVR offsets shift Recording times away from program times."""
        from apps.channels.tasks import evaluate_series_rules_impl

        _set_dvr_offsets(pre_min=5, post_min=5)
        prog = self._create_program(hours_from_now=2)
        result1 = evaluate_series_rules_impl()
        self.assertEqual(result1["scheduled"], 1)

        rec = Recording.objects.first()
        self.assertEqual(rec.start_time, prog.start_time - timedelta(minutes=5))
        self.assertEqual(rec.end_time, prog.end_time + timedelta(minutes=5))

        self._simulate_epg_refresh([self._program_data_for_refresh(prog)])
        result2 = evaluate_series_rules_impl()
        self.assertEqual(Recording.objects.count(), 1)

    @patch("apps.channels.tasks.acquire_task_lock", return_value=True)
    @patch("apps.channels.tasks.release_task_lock")
    def test_different_episodes_still_recorded(self, mock_release, mock_lock,
                                               mock_schedule, mock_artwork):
        """Different episodes on the same channel should each get a recording."""
        from apps.channels.tasks import evaluate_series_rules_impl

        self._create_program(hours_from_now=2, sub_title="Episode 1")
        self._create_program(hours_from_now=4, sub_title="Episode 2")
        result = evaluate_series_rules_impl()
        self.assertEqual(result["scheduled"], 2)
        self.assertEqual(Recording.objects.count(), 2)

    @patch("apps.channels.tasks.acquire_task_lock", return_value=True)
    @patch("apps.channels.tasks.release_task_lock")
    def test_new_episode_after_refresh_is_recorded(self, mock_release, mock_lock,
                                                   mock_schedule, mock_artwork):
        """A genuinely new episode appearing after EPG refresh should be recorded."""
        from apps.channels.tasks import evaluate_series_rules_impl

        prog = self._create_program(hours_from_now=2, sub_title="Episode 1")
        evaluate_series_rules_impl()
        self.assertEqual(Recording.objects.count(), 1)

        self._simulate_epg_refresh([
            self._program_data_for_refresh(prog),
            {
                "tvg_id": "test.channel.1",
                "start_time": prog.end_time,
                "end_time": prog.end_time + timedelta(hours=1),
                "title": "Test Show",
                "sub_title": "Episode 2",
            },
        ])

        result2 = evaluate_series_rules_impl()
        self.assertEqual(Recording.objects.count(), 2)
        self.assertEqual(result2["scheduled"], 1)

    @patch("apps.channels.tasks.acquire_task_lock", return_value=True)
    @patch("apps.channels.tasks.release_task_lock")
    def test_multiple_epg_refreshes_no_duplicates(self, mock_release, mock_lock,
                                                   mock_schedule, mock_artwork):
        """Multiple consecutive EPG refreshes should not accumulate duplicates."""
        from apps.channels.tasks import evaluate_series_rules_impl

        prog = self._create_program(hours_from_now=2)
        evaluate_series_rules_impl()
        self.assertEqual(Recording.objects.count(), 1)

        for _ in range(5):
            self._simulate_epg_refresh([self._program_data_for_refresh(prog)])
            evaluate_series_rules_impl()

        self.assertEqual(Recording.objects.count(), 1)


@patch("apps.channels.tasks.prefetch_recording_artwork")
@patch("apps.channels.signals.schedule_recording_task", return_value="mock-task-id")
class ConcurrencyGuardTests(SeriesRuleDedupBaseTestCase):
    """Verify the task lock prevents concurrent evaluation."""

    def test_lock_acquired_and_released(self, mock_schedule, mock_artwork):
        """evaluate_series_rules_impl acquires and releases the task lock."""
        from apps.channels.tasks import evaluate_series_rules_impl

        self._create_program(hours_from_now=2)

        with patch("apps.channels.tasks.acquire_task_lock", return_value=True) as mock_lock, \
             patch("apps.channels.tasks.release_task_lock") as mock_release:
            evaluate_series_rules_impl()
            mock_lock.assert_called_once_with('evaluate_series_rules', 'all')
            mock_release.assert_called_once_with('evaluate_series_rules', 'all')

    def test_skips_when_lock_held(self, mock_schedule, mock_artwork):
        """Returns early with skip reason when lock is already held."""
        from apps.channels.tasks import evaluate_series_rules_impl

        self._create_program(hours_from_now=2)

        with patch("apps.channels.tasks.acquire_task_lock", return_value=False):
            result = evaluate_series_rules_impl()
            self.assertEqual(result["scheduled"], 0)
            self.assertTrue(
                any(d.get("reason") == "concurrent evaluation in progress"
                    for d in result["details"]),
            )
            self.assertEqual(Recording.objects.count(), 0)

    @patch("apps.channels.tasks.acquire_task_lock", return_value=True)
    @patch("apps.channels.tasks.release_task_lock")
    def test_lock_released_on_exception(self, mock_release, mock_lock,
                                        mock_schedule, mock_artwork):
        """Lock is released even if the inner implementation raises."""
        from apps.channels.tasks import evaluate_series_rules_impl

        with patch("apps.channels.tasks._evaluate_series_rules_locked",
                   side_effect=RuntimeError("test error")):
            with self.assertRaises(RuntimeError):
                evaluate_series_rules_impl()
            mock_release.assert_called_once_with('evaluate_series_rules', 'all')


@patch("apps.channels.tasks.prefetch_recording_artwork")
@patch("apps.channels.signals.schedule_recording_task", return_value="mock-task-id")
class SecondaryGuardTests(SeriesRuleDedupBaseTestCase):
    """Verify the secondary DB guard uses stable program attributes."""

    @patch("apps.channels.tasks.acquire_task_lock", return_value=True)
    @patch("apps.channels.tasks.release_task_lock")
    def test_secondary_guard_catches_duplicate_with_offsets(self, mock_release, mock_lock,
                                                            mock_schedule, mock_artwork):
        """Secondary guard works with stale program IDs and DVR offsets."""
        from apps.channels.tasks import evaluate_series_rules_impl

        _set_dvr_offsets(pre_min=10, post_min=10)
        prog = self._create_program(hours_from_now=2)

        # Pre-existing recording with a stale program ID (from previous EPG refresh)
        Recording.objects.create(
            channel=self.channel,
            start_time=prog.start_time - timedelta(minutes=10),
            end_time=prog.end_time + timedelta(minutes=10),
            custom_properties={
                "program": {
                    "id": 99999,
                    "tvg_id": prog.tvg_id,
                    "title": prog.title,
                    "start_time": prog.start_time.isoformat(),
                    "end_time": prog.end_time.isoformat(),
                }
            },
        )

        result = evaluate_series_rules_impl()
        self.assertEqual(Recording.objects.count(), 1)
        self.assertEqual(result["scheduled"], 0)


# ---------------------------------------------------------------------------
# Integration tests: full path from EPG refresh through recording creation
# ---------------------------------------------------------------------------

@patch("apps.channels.tasks.prefetch_recording_artwork")
@patch("apps.channels.signals.schedule_recording_task", return_value="mock-task-id")
class IntegrationEPGRefreshTests(SeriesRuleDedupBaseTestCase):
    """End-to-end tests simulating the EPG refresh → evaluate → record flow.

    These exercise the full signal chain: evaluate_series_rules_impl creates
    a Recording, the post_save signal fires schedule_recording_task, and
    subsequent evaluations (after EPG refresh) must not create duplicates.
    """

    @patch("apps.channels.tasks.acquire_task_lock", return_value=True)
    @patch("apps.channels.tasks.release_task_lock")
    def test_full_flow_single_episode_no_duplicates(self, mock_release, mock_lock,
                                                     mock_schedule, mock_artwork):
        """Simulate: create rule → evaluate → EPG refresh → re-evaluate.

        The full recording lifecycle must result in exactly 1 recording.
        """
        from apps.channels.tasks import evaluate_series_rules_impl

        # Initial EPG data
        prog = self._create_program(hours_from_now=2, sub_title="Pilot")

        # First evaluation creates the recording
        result1 = evaluate_series_rules_impl()
        self.assertEqual(result1["scheduled"], 1)
        self.assertEqual(Recording.objects.count(), 1)

        # Verify the recording was created with correct program metadata
        rec = Recording.objects.first()
        self.assertEqual(rec.custom_properties["program"]["tvg_id"], "test.channel.1")
        self.assertEqual(rec.custom_properties["program"]["title"], "Test Show")
        self.assertEqual(
            rec.custom_properties["program"]["start_time"],
            prog.start_time.isoformat()
        )

        # Verify the post_save signal scheduled a task
        mock_schedule.assert_called()
        initial_schedule_count = mock_schedule.call_count

        # Simulate EPG refresh (programs get new DB IDs)
        self._simulate_epg_refresh([self._program_data_for_refresh(prog)])

        # Re-evaluate after refresh (this is what EPG refresh triggers)
        result2 = evaluate_series_rules_impl()
        self.assertEqual(result2["scheduled"], 0)
        self.assertEqual(Recording.objects.count(), 1)

        # No additional task scheduling should have occurred
        self.assertEqual(mock_schedule.call_count, initial_schedule_count)

    @patch("apps.channels.tasks.acquire_task_lock", return_value=True)
    @patch("apps.channels.tasks.release_task_lock")
    def test_full_flow_with_offsets_no_duplicates(self, mock_release, mock_lock,
                                                   mock_schedule, mock_artwork):
        """Full flow with DVR offsets: recording times differ from program times."""
        from apps.channels.tasks import evaluate_series_rules_impl

        _set_dvr_offsets(pre_min=5, post_min=10)
        prog = self._create_program(hours_from_now=3, sub_title="Episode 1")

        result1 = evaluate_series_rules_impl()
        self.assertEqual(result1["scheduled"], 1)

        rec = Recording.objects.first()
        # Verify offset-adjusted recording times
        self.assertEqual(rec.start_time, prog.start_time - timedelta(minutes=5))
        self.assertEqual(rec.end_time, prog.end_time + timedelta(minutes=10))
        # Verify original (unadjusted) program times in custom_properties
        self.assertEqual(
            rec.custom_properties["program"]["start_time"],
            prog.start_time.isoformat()
        )
        self.assertEqual(
            rec.custom_properties["program"]["end_time"],
            prog.end_time.isoformat()
        )

        # EPG refresh + re-evaluate
        self._simulate_epg_refresh([self._program_data_for_refresh(prog)])
        result2 = evaluate_series_rules_impl()
        self.assertEqual(Recording.objects.count(), 1)
        self.assertEqual(result2["scheduled"], 0)

    @patch("apps.channels.tasks.acquire_task_lock", return_value=True)
    @patch("apps.channels.tasks.release_task_lock")
    def test_full_flow_multiple_episodes_across_refreshes(self, mock_release, mock_lock,
                                                           mock_schedule, mock_artwork):
        """New episodes appear across multiple EPG refreshes; each recorded once."""
        from apps.channels.tasks import evaluate_series_rules_impl

        ep1 = self._create_program(hours_from_now=2, sub_title="Episode 1")
        evaluate_series_rules_impl()
        self.assertEqual(Recording.objects.count(), 1)

        # EPG refresh adds episode 2 alongside episode 1
        ep1_data = self._program_data_for_refresh(ep1)
        ep2_start = ep1.end_time
        ep2_data = {
            "tvg_id": "test.channel.1",
            "start_time": ep2_start,
            "end_time": ep2_start + timedelta(hours=1),
            "title": "Test Show",
            "sub_title": "Episode 2",
        }
        self._simulate_epg_refresh([ep1_data, ep2_data])
        evaluate_series_rules_impl()
        self.assertEqual(Recording.objects.count(), 2)

        # Another EPG refresh adds episode 3
        ep3_start = ep2_start + timedelta(hours=1)
        ep3_data = {
            "tvg_id": "test.channel.1",
            "start_time": ep3_start,
            "end_time": ep3_start + timedelta(hours=1),
            "title": "Test Show",
            "sub_title": "Episode 3",
        }
        self._simulate_epg_refresh([ep1_data, ep2_data, ep3_data])
        evaluate_series_rules_impl()
        self.assertEqual(Recording.objects.count(), 3)

        # Final EPG refresh with no new episodes — count must stay at 3
        self._simulate_epg_refresh([ep1_data, ep2_data, ep3_data])
        evaluate_series_rules_impl()
        self.assertEqual(Recording.objects.count(), 3)

    @patch("apps.channels.tasks.acquire_task_lock", return_value=True)
    @patch("apps.channels.tasks.release_task_lock")
    def test_full_flow_multiple_series_rules(self, mock_release, mock_lock,
                                              mock_schedule, mock_artwork):
        """Multiple series rules on different channels, each evaluated correctly."""
        from apps.channels.tasks import evaluate_series_rules_impl

        # Second channel with its own EPG
        epg2 = EPGData.objects.create(
            tvg_id="test.channel.2",
            name="Channel 2 EPG",
            epg_source=self.epg_source,
        )
        channel2 = Channel.objects.create(
            channel_number=2, name="Test Channel 2", epg_data=epg2
        )

        _set_series_rules([
            {"tvg_id": "test.channel.1", "mode": "all", "title": "Show A"},
            {"tvg_id": "test.channel.2", "mode": "all", "title": "Show B"},
        ])

        # Programs on both channels
        start1 = self.now + timedelta(hours=2)
        prog1 = ProgramData.objects.create(
            epg=self.epg, tvg_id="test.channel.1",
            start_time=start1, end_time=start1 + timedelta(hours=1),
            title="Show A", sub_title="Episode 1",
        )
        start2 = self.now + timedelta(hours=3)
        prog2 = ProgramData.objects.create(
            epg=epg2, tvg_id="test.channel.2",
            start_time=start2, end_time=start2 + timedelta(hours=1),
            title="Show B", sub_title="Episode 1",
        )

        evaluate_series_rules_impl()
        self.assertEqual(Recording.objects.count(), 2)
        self.assertEqual(Recording.objects.filter(channel=self.channel).count(), 1)
        self.assertEqual(Recording.objects.filter(channel=channel2).count(), 1)

        # EPG refresh for both channels
        ProgramData.objects.filter(epg=self.epg).delete()
        ProgramData.objects.filter(epg=epg2).delete()
        ProgramData.objects.create(
            epg=self.epg, tvg_id="test.channel.1",
            start_time=start1, end_time=start1 + timedelta(hours=1),
            title="Show A", sub_title="Episode 1",
        )
        ProgramData.objects.create(
            epg=epg2, tvg_id="test.channel.2",
            start_time=start2, end_time=start2 + timedelta(hours=1),
            title="Show B", sub_title="Episode 1",
        )

        evaluate_series_rules_impl()
        self.assertEqual(Recording.objects.count(), 2,
                         "No duplicates across multiple series rules after EPG refresh")

    @patch("apps.channels.tasks.acquire_task_lock", return_value=True)
    @patch("apps.channels.tasks.release_task_lock")
    def test_full_flow_rapid_epg_refreshes_simulate_user_report(
        self, mock_release, mock_lock, mock_schedule, mock_artwork
    ):
        """Reproduce the user-reported scenario: series rule + multiple EPG refreshes
        causing count to balloon from 6 to 25 and 5 simultaneous recordings.

        Simulates 6 episodes with 5 EPG refreshes (each assigning new ProgramData IDs).
        """
        from apps.channels.tasks import evaluate_series_rules_impl

        # Create 6 episodes (the user had "next of 6")
        episodes = []
        for i in range(6):
            start = self.now + timedelta(hours=2 + i * 2)
            episodes.append({
                "tvg_id": "test.channel.1",
                "start_time": start,
                "end_time": start + timedelta(hours=1),
                "title": "Test Show",
                "sub_title": f"Episode {i + 1}",
            })

        # Create initial ProgramData
        for ep in episodes:
            ProgramData.objects.create(epg=self.epg, **ep)

        # First evaluation: should create exactly 6 recordings
        evaluate_series_rules_impl()
        self.assertEqual(Recording.objects.count(), 6)

        # Simulate 5 EPG refreshes (the user saw count balloon to 25)
        for refresh_num in range(5):
            self._simulate_epg_refresh(episodes)
            result = evaluate_series_rules_impl()
            self.assertEqual(
                Recording.objects.count(), 6,
                f"After EPG refresh #{refresh_num + 1}, expected 6 recordings "
                f"but got {Recording.objects.count()}"
            )
            self.assertEqual(result["scheduled"], 0)

    @patch("apps.channels.tasks.acquire_task_lock", return_value=True)
    @patch("apps.channels.tasks.release_task_lock")
    def test_full_flow_recording_survives_program_removal_and_readd(
        self, mock_release, mock_lock, mock_schedule, mock_artwork
    ):
        """Program temporarily disappears from EPG then reappears — no duplicate."""
        from apps.channels.tasks import evaluate_series_rules_impl

        prog = self._create_program(hours_from_now=2, sub_title="Episode 1")
        evaluate_series_rules_impl()
        self.assertEqual(Recording.objects.count(), 1)

        # EPG refresh removes the program entirely
        self._simulate_epg_refresh([])
        evaluate_series_rules_impl()
        self.assertEqual(Recording.objects.count(), 1,
                         "Existing recording preserved when program disappears from EPG")

        # EPG refresh adds the program back (new ID)
        self._simulate_epg_refresh([self._program_data_for_refresh(prog)])
        evaluate_series_rules_impl()
        self.assertEqual(Recording.objects.count(), 1,
                         "No duplicate when program reappears with new ID")

    @patch("apps.channels.tasks.acquire_task_lock", return_value=True)
    @patch("apps.channels.tasks.release_task_lock")
    def test_full_flow_celery_task_wrapper_calls_impl(self, mock_release, mock_lock,
                                                       mock_schedule, mock_artwork):
        """The @shared_task evaluate_series_rules delegates to _impl correctly."""
        from apps.channels.tasks import evaluate_series_rules

        self._create_program(hours_from_now=2)
        result = evaluate_series_rules()
        self.assertEqual(result["scheduled"], 1)
        self.assertEqual(Recording.objects.count(), 1)

        # Call again (simulating a second EPG refresh trigger)
        result2 = evaluate_series_rules()
        self.assertEqual(result2["scheduled"], 0)
        self.assertEqual(Recording.objects.count(), 1)

    @patch("apps.channels.tasks.acquire_task_lock", return_value=True)
    @patch("apps.channels.tasks.release_task_lock")
    def test_full_flow_tvg_id_scoped_evaluation(self, mock_release, mock_lock,
                                                 mock_schedule, mock_artwork):
        """Scoped evaluation (tvg_id parameter) still prevents duplicates."""
        from apps.channels.tasks import evaluate_series_rules_impl

        prog = self._create_program(hours_from_now=2)
        result1 = evaluate_series_rules_impl(tvg_id="test.channel.1")
        self.assertEqual(result1["scheduled"], 1)

        self._simulate_epg_refresh([self._program_data_for_refresh(prog)])
        result2 = evaluate_series_rules_impl(tvg_id="test.channel.1")
        self.assertEqual(result2["scheduled"], 0)
        self.assertEqual(Recording.objects.count(), 1)

    @patch("apps.channels.tasks.acquire_task_lock", return_value=True)
    @patch("apps.channels.tasks.release_task_lock")
    def test_full_flow_offset_change_between_refreshes(self, mock_release, mock_lock,
                                                        mock_schedule, mock_artwork):
        """Changing DVR offsets between EPG refreshes doesn't create duplicates.

        Even though Recording.start_time/end_time change when offsets change,
        the dedup key uses the original program times from custom_properties.
        """
        from apps.channels.tasks import evaluate_series_rules_impl

        _set_dvr_offsets(pre_min=5, post_min=5)
        prog = self._create_program(hours_from_now=2)
        evaluate_series_rules_impl()
        self.assertEqual(Recording.objects.count(), 1)

        rec = Recording.objects.first()
        original_start = rec.start_time
        original_end = rec.end_time

        # Change offsets
        _set_dvr_offsets(pre_min=10, post_min=15)

        # EPG refresh
        self._simulate_epg_refresh([self._program_data_for_refresh(prog)])
        result = evaluate_series_rules_impl()
        self.assertEqual(Recording.objects.count(), 1,
                         "Changing offsets between refreshes should not create duplicates")
        self.assertEqual(result["scheduled"], 0)


# ---------------------------------------------------------------------------
# Edge case tests: Redis unavailability, non-series recordings, robustness
# ---------------------------------------------------------------------------

@patch("apps.channels.tasks.prefetch_recording_artwork")
@patch("apps.channels.signals.schedule_recording_task", return_value="mock-task-id")
class RedisUnavailabilityTests(SeriesRuleDedupBaseTestCase):
    """Verify evaluation works when Redis is unavailable (lock cannot be acquired)."""

    def test_proceeds_when_redis_down(self, mock_schedule, mock_artwork):
        """Evaluation succeeds (with dedup guards) when Redis raises on lock acquire."""
        from apps.channels.tasks import evaluate_series_rules_impl

        self._create_program(hours_from_now=2)

        with patch("apps.channels.tasks.acquire_task_lock",
                   side_effect=ConnectionError("Redis unavailable")):
            result = evaluate_series_rules_impl()
            self.assertEqual(result["scheduled"], 1)
            self.assertEqual(Recording.objects.count(), 1)

    def test_dedup_still_works_without_lock(self, mock_schedule, mock_artwork):
        """Dedup guards prevent duplicates even when the lock is unavailable."""
        from apps.channels.tasks import evaluate_series_rules_impl

        prog = self._create_program(hours_from_now=2)

        # First call: Redis down, proceeds without lock
        with patch("apps.channels.tasks.acquire_task_lock",
                   side_effect=ConnectionError("Redis unavailable")):
            evaluate_series_rules_impl()
            self.assertEqual(Recording.objects.count(), 1)

        # EPG refresh
        self._simulate_epg_refresh([self._program_data_for_refresh(prog)])

        # Second call: Redis still down
        with patch("apps.channels.tasks.acquire_task_lock",
                   side_effect=ConnectionError("Redis unavailable")):
            result = evaluate_series_rules_impl()
            self.assertEqual(Recording.objects.count(), 1,
                             "Dedup guards prevent duplicates even without lock")
            self.assertEqual(result["scheduled"], 0)

    def test_lock_not_released_when_not_acquired(self, mock_schedule, mock_artwork):
        """release_task_lock is not called if acquire raised an exception."""
        from apps.channels.tasks import evaluate_series_rules_impl

        self._create_program(hours_from_now=2)

        with patch("apps.channels.tasks.acquire_task_lock",
                   side_effect=ConnectionError("Redis unavailable")), \
             patch("apps.channels.tasks.release_task_lock") as mock_release:
            evaluate_series_rules_impl()
            mock_release.assert_not_called()


@patch("apps.channels.tasks.prefetch_recording_artwork")
@patch("apps.channels.signals.schedule_recording_task", return_value="mock-task-id")
class NonSeriesRecordingTests(SeriesRuleDedupBaseTestCase):
    """Verify non-series recordings don't interfere with series rule dedup."""

    @patch("apps.channels.tasks.acquire_task_lock", return_value=True)
    @patch("apps.channels.tasks.release_task_lock")
    def test_manual_recording_without_program_data_ignored(self, mock_release, mock_lock,
                                                            mock_schedule, mock_artwork):
        """Recordings without custom_properties.program are skipped by dedup key builder."""
        from apps.channels.tasks import evaluate_series_rules_impl

        # Manual recording with no program metadata
        Recording.objects.create(
            channel=self.channel,
            start_time=self.now + timedelta(hours=2),
            end_time=self.now + timedelta(hours=3),
            custom_properties={},
        )

        prog = self._create_program(hours_from_now=2)
        result = evaluate_series_rules_impl()
        self.assertEqual(result["scheduled"], 1)
        self.assertEqual(Recording.objects.count(), 2)

    @patch("apps.channels.tasks.acquire_task_lock", return_value=True)
    @patch("apps.channels.tasks.release_task_lock")
    def test_recurring_rule_recording_does_not_interfere(self, mock_release, mock_lock,
                                                          mock_schedule, mock_artwork):
        """Recordings from recurring rules (custom_properties.rule) don't block series rules."""
        from apps.channels.tasks import evaluate_series_rules_impl

        Recording.objects.create(
            channel=self.channel,
            start_time=self.now + timedelta(hours=2),
            end_time=self.now + timedelta(hours=3),
            custom_properties={"rule": {"id": 1, "name": "Daily News"}},
        )

        prog = self._create_program(hours_from_now=2)
        result = evaluate_series_rules_impl()
        self.assertEqual(result["scheduled"], 1)
        self.assertEqual(Recording.objects.count(), 2)

    @patch("apps.channels.tasks.acquire_task_lock", return_value=True)
    @patch("apps.channels.tasks.release_task_lock")
    def test_recording_with_null_custom_properties_ignored(self, mock_release, mock_lock,
                                                            mock_schedule, mock_artwork):
        """Recordings with None custom_properties don't crash the dedup key builder."""
        from apps.channels.tasks import evaluate_series_rules_impl

        Recording.objects.create(
            channel=self.channel,
            start_time=self.now + timedelta(hours=2),
            end_time=self.now + timedelta(hours=3),
            custom_properties=None,
        )

        prog = self._create_program(hours_from_now=2)
        result = evaluate_series_rules_impl()
        self.assertEqual(result["scheduled"], 1)
