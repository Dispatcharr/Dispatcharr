"""Unit tests for join prebuffer and recent-window ingest delivery rate."""

import random
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from apps.proxy.live_proxy.input.ingest_lag import (
    CLUSTER_GAP_SECONDS,
    CLUSTER_MAX_SPAN_SECONDS,
    JOIN_ARM_FALLBACK_SECONDS,
    JOIN_DENSE_SAMPLE_SECONDS,
    JOIN_STABLE_MIN_SECONDS,
    ADOPT_CUSHION_SECONDS,
    CONFIRM_WINDOW_SECONDS,
    CUSHION_CLEAR_FRACTION,
    MIN_CUSHION_TRIP_SECONDS,
    MIN_RATE_SAMPLES,
    STALL_GAP_MAX_SECONDS,
    SILENCE_STALL_SECONDS,
    RATE_RECOVERY_SECONDS,
    SPEED_WINDOW_SECONDS,
    TRIP_CONFIRM_SECONDS,
    IngestLagTracker,
)
from apps.proxy.live_proxy.channel_status import ChannelStatus
from apps.proxy.live_proxy.input.buffer import StreamBuffer
from apps.proxy.live_proxy.input.manager import StreamManager
from apps.proxy.live_proxy.ts_clock import wrap_delta_seconds

PID = 0x100
WALL0 = 1_000_000.0
# Extra wall time after arm so speed windows have span. Not a product setting.
MIN_BUFFER = 4.0
SPEED_THRESHOLD = 1.0
CLIENT_BEHIND = 5.0
TRIP_SECONDS = IngestLagTracker.cushion_trip_seconds(CLIENT_BEHIND)
CLEAR_SECONDS = IngestLagTracker.cushion_clear_seconds(TRIP_SECONDS)


def assert_is_slow(testcase, tracker, now, trip=TRIP_SECONDS):
    """Debt must stay empty for the confirm hold before ``is_slow`` is True."""
    testcase.assertFalse(tracker.is_slow(trip, now=now))
    testcase.assertTrue(
        tracker.is_slow(trip, now=now + TRIP_CONFIRM_SECONDS)
    )


def feed_burst(tracker, wall, media_end, media_start, chunks=8, spread=0.3, pid=PID):
    """One provider burst: ``chunks`` chunks inside ``spread`` seconds of wall time."""
    finished = False
    for i in range(chunks):
        media = media_start + (media_end - media_start) * i / max(chunks - 1, 1)
        finished = tracker.observe(
            wall + spread * i / max(chunks - 1, 1),
            media,
            "pts",
            pid,
        ) or finished
    return finished


def arm_with_burst(tracker, wall=WALL0, media_start=1000.0, media_end=1030.0, spread=0.3):
    """Complete the initial burst and return the settle wall."""
    feed_burst(tracker, wall, media_end, media_start, spread=spread)
    settle_at = wall + spread + CLUSTER_GAP_SECONDS
    tracker.settle(settle_at)
    return settle_at, media_end


def feed_realtime(tracker, start_wall, start_media, duration, step=0.25, rate=1.0):
    """Steady delivery at ``rate`` media seconds per wall second."""
    wall = start_wall
    media = start_media
    end = start_wall + duration
    while wall < end - 1e-9:
        wall = min(wall + step, end)
        media = start_media + (wall - start_wall) * rate
        tracker.observe(wall, media, "pts", PID)
    return wall, media


def bursty_timeline(
    rate_at,
    stall=None,
    period=6.0,
    jitter=1.0,
    spread=0.4,
    seed=1,
    join=20.0,
    horizon=600.0,
    step=0.1,
):
    """(wall offset, media) points for a provider that sends bursts.

    Each burst carries ``rate_at(t)`` media seconds per wall second since the
    previous burst and arrives over ``spread`` seconds. ``stall`` is a
    ``(start, end)`` window with no data at all. The feed opens with a ``join``
    second dump at t=0.
    """
    rnd = random.Random(seed)
    media = 1000.0
    points = []
    n = int(0.3 / step) + 1
    for i in range(n):
        points.append((i * step, media + join * (i + 1) / n))
    media += join
    last_burst = 0.3
    nxt = last_burst + max(1.0, period + rnd.uniform(-jitter, jitter))
    while nxt < horizon:
        if stall and stall[0] <= nxt < stall[1]:
            nxt = stall[1]
            owed = period * rate_at(nxt)
        else:
            owed = (nxt - last_burst) * rate_at(nxt)
        steps = max(1, int(spread / step))
        for i in range(steps):
            points.append((round(nxt + i * step, 3), media + owed * (i + 1) / steps))
        media += owed
        last_burst = nxt
        nxt += max(1.0, period + rnd.uniform(-jitter, jitter))
    return points


def rate_between(normal, slow, start, end):
    return lambda t: slow if start <= t < end else normal


def feed_paced_bursts(tracker, start_wall, start_media, duration, rate=1.0, period=6.0):
    """Feed bursts for ``duration`` seconds. Returns the final (wall, media)."""
    wall, media = start_wall, start_media
    last_burst = start_wall
    burst = start_wall + period
    while burst <= start_wall + duration:
        owed = (burst - last_burst) * rate
        steps = 4
        for i in range(steps):
            tracker.observe(
                burst + i * 0.1, media + owed * (i + 1) / steps, "pts", PID
            )
        media += owed
        wall = burst + (steps - 1) * 0.1
        last_burst = burst
        burst += period
    return wall, media


class IngestLagTrackerTests(SimpleTestCase):
    def test_initial_burst_sets_prebuffer(self):
        tracker = IngestLagTracker()
        # ~30s of media in 0.3s of wall → ~29.7s prebuffer.
        arm_with_burst(tracker, media_start=1000.0, media_end=1030.0, spread=0.3)
        self.assertTrue(tracker.is_armed)
        self.assertAlmostEqual(tracker.prebuffer, 29.7, places=1)
        self.assertTrue(tracker.join_prebuffer_pending)
        tracker.mark_join_prebuffer_persisted()
        self.assertFalse(tracker.join_prebuffer_pending)

    def test_steady_realtime_recent_speed_near_one(self):
        tracker = IngestLagTracker()
        settle, media = arm_with_burst(tracker)
        # Past grace with steady 1.0x.
        wall, _media = feed_realtime(
            tracker, settle + 0.1, media, duration=MIN_BUFFER + SPEED_WINDOW_SECONDS
        )
        speed = tracker.recent_speed(now=wall)
        self.assertIsNotNone(speed)
        self.assertAlmostEqual(speed, 1.0, places=1)
        self.assertFalse(tracker.is_slow(TRIP_SECONDS, now=wall))

    def test_half_speed_builds_cushion_debt_and_trips(self):
        tracker = IngestLagTracker()
        settle, media = arm_with_burst(tracker)
        # At 0.5x, debt grows at 0.5s/s. Need TRIP_SECONDS after grace/anchor.
        wall, media = feed_realtime(
            tracker,
            settle + 0.1,
            media,
            duration=MIN_BUFFER + TRIP_SECONDS / 0.5 + 2.0,
            rate=0.5,
        )
        self.assertTrue(tracker.rate_ready(now=wall))
        # First evaluate seats the debt anchor; confirm hold still applies.
        assert_is_slow(self, tracker, wall)
        trip_at = wall + TRIP_CONFIRM_SECONDS
        self.assertGreaterEqual(tracker.cushion_debt(now=trip_at), TRIP_SECONDS)
        self.assertAlmostEqual(
            tracker.empty_for_seconds(now=trip_at), TRIP_CONFIRM_SECONDS, places=3
        )
        self.assertAlmostEqual(
            tracker.empty_for_seconds(now=trip_at + 0.37),
            TRIP_CONFIRM_SECONDS + 0.37,
            places=3,
        )

    def test_soft_under_delivery_trips_only_after_full_client_behind(self):
        tracker = IngestLagTracker()
        settle, media = arm_with_burst(tracker)
        # 0.9x loses 0.1s/s. Empty after ~behind seconds of debt; not before.
        wall, media = feed_realtime(
            tracker,
            settle + 0.1,
            media,
            duration=MIN_BUFFER + 5.0,
            rate=0.9,
        )
        self.assertFalse(tracker.is_slow(TRIP_SECONDS, now=wall))
        wall, media = feed_realtime(
            tracker,
            wall + 0.1,
            media,
            duration=TRIP_SECONDS / 0.1 + 2.0,
            rate=0.9,
        )
        self.assertGreaterEqual(tracker.cushion_debt(now=wall), TRIP_SECONDS)
        assert_is_slow(self, tracker, wall)

    def test_empty_budget_blip_does_not_fire_before_confirm_hold(self):
        tracker = IngestLagTracker()
        settle, media = arm_with_burst(tracker)
        wall, media = feed_realtime(
            tracker,
            settle + 0.1,
            media,
            duration=MIN_BUFFER + TRIP_SECONDS / 0.5 + 2.0,
            rate=0.5,
        )
        # First sighting of empty starts the confirm clock; not a trip yet.
        self.assertFalse(tracker.is_slow(TRIP_SECONDS, now=wall))
        self.assertGreaterEqual(tracker.cushion_debt(now=wall), TRIP_SECONDS)
        # Brief recovery below empty resets the confirm clock.
        wall, media = feed_realtime(
            tracker, wall + 0.1, media, duration=4.0, rate=3.0
        )
        self.assertLess(tracker.cushion_debt(now=wall), TRIP_SECONDS)
        self.assertFalse(tracker.is_slow(TRIP_SECONDS, now=wall))
        # Empty again: still needs the full confirm hold.
        wall, media = feed_realtime(
            tracker,
            wall + 0.1,
            media,
            duration=TRIP_SECONDS / 0.5 + 2.0,
            rate=0.5,
        )
        self.assertFalse(tracker.is_slow(TRIP_SECONDS, now=wall))
        self.assertTrue(
            tracker.is_slow(TRIP_SECONDS, now=wall + TRIP_CONFIRM_SECONDS)
        )

    def test_silence_drives_speed_toward_zero(self):
        tracker = IngestLagTracker()
        settle, media = arm_with_burst(tracker)
        wall, media = feed_realtime(
            tracker, settle + 0.1, media, duration=MIN_BUFFER + 1.0, rate=1.0
        )
        # Arm debt, then stall past the provider rhythm so credit no longer covers idle.
        self.assertFalse(tracker.is_slow(TRIP_SECONDS, now=wall))
        silent_at = wall + tracker._stall_after()
        tracker.project_silence(silent_at)
        for _ in range(int(SPEED_WINDOW_SECONDS) + 1):
            silent_at += 1.0
            tracker.project_silence(silent_at)
        speed = tracker.recent_speed(now=silent_at)
        self.assertIsNotNone(speed)
        self.assertLess(speed, 0.2)
        # Keep idling until cushion debt hits the trip line.
        trip_at = silent_at
        for _ in range(int(TRIP_SECONDS) + 5):
            trip_at += 1.0
            tracker.project_silence(trip_at)
            if tracker.is_slow(TRIP_SECONDS, now=trip_at):
                break
        self.assertTrue(tracker.is_slow(TRIP_SECONDS, now=trip_at))

    def test_short_provider_gap_does_not_trip(self):
        tracker = IngestLagTracker()
        settle, media = arm_with_burst(tracker)
        wall, media = feed_realtime(
            tracker,
            settle + 0.1,
            media,
            duration=MIN_BUFFER + SPEED_WINDOW_SECONDS,
            rate=1.0,
        )
        before = tracker.recent_speed(now=wall)
        # Normal inter-burst quiet must hold near realtime, not invent under-1x.
        gap_at = wall + 5.0
        after = tracker.recent_speed(now=gap_at)
        self.assertIsNotNone(before)
        self.assertIsNotNone(after)
        self.assertAlmostEqual(after, before, delta=0.05)
        self.assertGreaterEqual(after, SPEED_THRESHOLD - 0.05)
        self.assertFalse(tracker.is_slow(TRIP_SECONDS, now=gap_at))

    def test_silence_projection_does_not_zero_cushion_on_healthy_gap(self):
        # project_silence used to stamp a frozen sample at ``now``, which made
        # idle credit look like 0 and dropped the budget to empty on the first
        # stall-threshold tick of a normal provider gap.
        tracker = IngestLagTracker()
        settle, media = arm_with_burst(tracker)
        wall, media = feed_paced_bursts(
            tracker,
            settle + 0.1,
            media,
            duration=MIN_BUFFER + 40.0,
            rate=1.0,
            period=6.2,
        )
        self.assertFalse(tracker.is_slow(TRIP_SECONDS, now=wall))
        # Seat at the last complete burst so we only score this gap.
        tracker._debt_anchor_wall = tracker._rate_wall
        tracker._debt_anchor_media = tracker._rate_media
        tracker._debt = 0.0
        stall_at = wall + tracker._stall_after()
        tracker.project_silence(stall_at)
        debt = tracker.cushion_debt(now=stall_at)
        self.assertLess(
            debt,
            0.5,
            f"silence projection spent cushion on a healthy gap: debt={debt}",
        )
        self.assertFalse(tracker.is_slow(TRIP_SECONDS, now=stall_at))
        # A real stall past the rhythm still trips.
        trip_at = stall_at
        for _ in range(int(TRIP_SECONDS) + 5):
            trip_at += 1.0
            tracker.project_silence(trip_at)
            if tracker.is_slow(TRIP_SECONDS, now=trip_at):
                break
        self.assertTrue(tracker.is_slow(TRIP_SECONDS, now=trip_at))

    def test_trailing_idle_cools_catch_up_toward_one_not_below(self):
        tracker = IngestLagTracker()
        settle, media = arm_with_burst(tracker)
        # Short post-join baseline so a 10s dump still lifts the long window.
        wall, media = feed_realtime(
            tracker,
            settle + 0.1,
            media,
            duration=MIN_BUFFER + 20.0,
            rate=1.0,
        )
        # Catch-up dump pushes raw above 1.
        dump_at = wall + 0.1
        feed_burst(
            tracker,
            dump_at,
            media_end=media + 10.0,
            media_start=media,
            chunks=8,
            spread=0.3,
        )
        high = tracker.recent_speed(now=dump_at + 0.3)
        self.assertGreater(high, 1.15)
        # Quiet may cool catch-up toward 1.0x but must not push under threshold.
        later = dump_at + 0.3 + 5.0
        cooled = tracker.recent_speed(now=later)
        self.assertLess(cooled, high)
        self.assertLessEqual(cooled, high - 0.05)
        self.assertGreaterEqual(cooled, SPEED_THRESHOLD)

    def test_bursty_window_speed_is_not_biased_high(self):
        # A window that starts on the first packet of a burst skips the media
        # that packet already carries and reads a 0.9x provider as ~1.0x.
        tracker = IngestLagTracker()
        settle, media = arm_with_burst(tracker)
        # 6.2s does not divide the speed window, so the window start lands inside
        # a burst. A period that divided evenly would hide the bias.
        wall, _media = feed_paced_bursts(
            tracker, settle + 0.1, media, duration=120.0, rate=0.9, period=6.2
        )
        self.assertAlmostEqual(tracker.recent_speed(now=wall), 0.9, delta=0.05)
        healthy = IngestLagTracker()
        settle, media = arm_with_burst(healthy)
        wall, _media = feed_paced_bursts(
            healthy, settle + 0.1, media, duration=120.0, rate=1.0, period=6.2
        )
        self.assertAlmostEqual(healthy.recent_speed(now=wall), 1.0, delta=0.05)

    def test_healthy_bursty_feed_keeps_zero_cushion_debt(self):
        tracker = IngestLagTracker()
        settle, media = arm_with_burst(tracker)
        wall, media = feed_paced_bursts(
            tracker, settle + 0.1, media, duration=MIN_BUFFER + 90.0, rate=1.0, period=6.2
        )
        # Seat debt at the last complete burst so the harness gap before the
        # first paced burst is not scored. Mid-gap credit is what we test.
        self.assertTrue(
            tracker.is_slow(TRIP_SECONDS, now=wall) is not None
        )
        tracker._debt_anchor_wall = tracker._rate_wall
        tracker._debt_anchor_media = tracker._rate_media
        tracker._debt = 0.0
        mid_gap = wall + 3.0
        self.assertFalse(tracker.is_slow(TRIP_SECONDS, now=mid_gap))
        self.assertLess(tracker.cushion_debt(now=mid_gap), 0.5)

    def test_stall_threshold_follows_the_providers_own_gap(self):
        tracker = IngestLagTracker()
        # Unknown rhythm: only extreme silence freezes until a real gap is seen.
        self.assertEqual(tracker._stall_after(), STALL_GAP_MAX_SECONDS)
        settle, media = arm_with_burst(tracker)
        wall, media = feed_paced_bursts(
            tracker, settle + 0.1, media, duration=60.0, rate=1.0, period=6.2
        )
        stall_after = tracker._stall_after()
        self.assertGreater(stall_after, SILENCE_STALL_SECONDS)
        # Idle time inside the provider's normal gap must not invent a stall.
        tracker.project_silence(wall + 6.5)
        self.assertEqual(tracker._rate_wall, wall)
        # Idle beyond the provider's rhythm is a real stall: media freezes
        # while wall keeps moving.
        stalled_at = wall + stall_after + 0.5
        tracker.project_silence(stalled_at)
        self.assertEqual(tracker._rate_wall, stalled_at)
        self.assertEqual(tracker._rate_media, media)

    def test_stall_threshold_is_capped_after_a_long_outage(self):
        tracker = IngestLagTracker()
        settle, media = arm_with_burst(tracker)
        tracker.observe(settle + 0.1, media + 1.0, "pts", PID)
        tracker.observe(settle + 40.0, media + 2.0, "pts", PID)
        self.assertEqual(tracker._stall_after(), STALL_GAP_MAX_SECONDS)

    def test_recovery_clears_when_debt_falls_under_clear_line(self):
        tracker = IngestLagTracker()
        settle, media = arm_with_burst(tracker)
        wall, media = feed_realtime(
            tracker,
            settle + 0.1,
            media,
            duration=MIN_BUFFER + TRIP_SECONDS / 0.5 + 2.0,
            rate=0.5,
        )
        assert_is_slow(self, tracker, wall)
        # Catch up faster than realtime to pay the debt down.
        wall, media = feed_realtime(
            tracker,
            wall + TRIP_CONFIRM_SECONDS + 0.1,
            media,
            duration=TRIP_SECONDS / 0.5 + 5.0,
            rate=2.0,
        )
        self.assertLessEqual(tracker.cushion_debt(now=wall), CLEAR_SECONDS)
        recovered = False
        for _ in range(int(RATE_RECOVERY_SECONDS / 0.25) + 4):
            wall += 0.25
            media += 0.25
            tracker.observe(wall, media, "pts", PID)
            recovered = tracker.is_recovered(TRIP_SECONDS, now=wall)
            if recovered:
                break
        self.assertTrue(recovered)
        self.assertIsNone(tracker._rate_ok_since)

    def test_idle_cools_catch_up_toward_one_without_crossing_under(self):
        tracker = IngestLagTracker()
        settle, media = arm_with_burst(tracker)
        wall, _media = feed_realtime(
            tracker,
            settle + 0.1,
            media,
            duration=SPEED_WINDOW_SECONDS,
            rate=1.2,
        )
        base = tracker.recent_speed(now=wall)
        self.assertGreater(base, 1.05)
        # Quiet cools that same pair toward 1x and stops there.
        later = tracker.recent_speed(now=wall + 10.0)
        self.assertGreaterEqual(later, 1.0)
        self.assertLess(later, base)

    def test_bursty_dumps_across_gaps_average_near_one(self):
        tracker = IngestLagTracker()
        settle, media = arm_with_burst(tracker)
        wall = settle + 0.1
        # Realtime-worth dumps separated by quiet wall; next dump spans the gap.
        for _ in range(6):
            feed_burst(
                tracker,
                wall,
                media_end=media + 5.0,
                media_start=media,
                chunks=6,
                spread=0.4,
            )
            media += 5.0
            wall += 0.4 + 5.0
        feed_burst(
            tracker,
            wall,
            media_end=media + 5.0,
            media_start=media,
            chunks=6,
            spread=0.4,
        )
        wall += 0.4
        speed = tracker.recent_speed(now=wall)
        self.assertIsNotNone(speed)
        self.assertAlmostEqual(speed, 1.0, delta=0.25)
        self.assertFalse(tracker.is_slow(TRIP_SECONDS, now=wall))

    def test_brief_dip_does_not_reach_cushion_trip(self):
        tracker = IngestLagTracker()
        settle, media = arm_with_burst(tracker)
        wall, media = feed_realtime(
            tracker,
            settle + 0.1,
            media,
            duration=MIN_BUFFER + SPEED_WINDOW_SECONDS,
            rate=1.0,
        )
        self.assertFalse(tracker.is_slow(TRIP_SECONDS, now=wall))
        # One second at half speed is only ~0.5s of debt.
        wall, media = feed_realtime(
            tracker, wall + 0.1, media, duration=1.0, rate=0.5
        )
        wall, media = feed_realtime(
            tracker,
            wall + 0.1,
            media,
            duration=CONFIRM_WINDOW_SECONDS + 1.0,
            rate=1.0,
        )
        self.assertLess(tracker.cushion_debt(now=wall), TRIP_SECONDS)
        self.assertFalse(tracker.is_slow(TRIP_SECONDS, now=wall))

    def test_catch_up_after_starve_clears_buffering_debt(self):
        tracker = IngestLagTracker()
        settle, media = arm_with_burst(tracker)
        wall, media = feed_realtime(
            tracker,
            settle + 0.1,
            media,
            duration=MIN_BUFFER + TRIP_SECONDS / 0.5 + 2.0,
            rate=0.5,
        )
        assert_is_slow(self, tracker, wall)
        wall, media = feed_realtime(
            tracker,
            wall + TRIP_CONFIRM_SECONDS + 0.1,
            media,
            duration=TRIP_SECONDS / 0.5 + 5.0,
            rate=2.0,
        )
        self.assertFalse(tracker.is_slow(TRIP_SECONDS, now=wall))
        self.assertLessEqual(tracker.cushion_debt(now=wall), CLEAR_SECONDS)

    def test_short_slow_interval_does_not_trip(self):
        tracker = IngestLagTracker()
        settle, media = arm_with_burst(tracker)
        tracker.observe(settle + 0.5, media + 0.1, "pts", PID)
        tracker.observe(settle + 1.0, media + 0.2, "pts", PID)
        self.assertTrue(tracker.rate_ready(now=settle + 1.0))
        self.assertFalse(tracker.is_slow(TRIP_SECONDS, now=settle + 1.0))

    def test_debt_anchor_is_the_live_pts(self):
        tracker = IngestLagTracker()
        _settle, media = arm_with_burst(tracker)
        armed = tracker._armed_wall
        # Half speed from the live PTS. 4.5s at 0.5x is about 2.25s of debt.
        wall, _media = feed_realtime(
            tracker,
            armed + 0.05,
            media,
            duration=MIN_BUFFER + 0.5,
            rate=0.5,
        )
        self.assertFalse(tracker.is_slow(TRIP_SECONDS, now=wall))
        self.assertAlmostEqual(tracker._debt_anchor_wall, armed, delta=0.05)
        self.assertGreater(tracker.cushion_debt(now=wall), 1.5)

    def test_join_catch_up_shows_high_speed_before_arm(self):
        tracker = IngestLagTracker()
        # ~20s media in 0.4s wall during the initial dump.
        feed_burst(
            tracker,
            WALL0,
            media_end=1020.0,
            media_start=1000.0,
            chunks=8,
            spread=0.4,
        )
        speed = tracker.recent_speed(now=WALL0 + 0.4)
        self.assertFalse(tracker.is_armed)
        self.assertIsNotNone(speed)
        self.assertGreater(speed, 5.0)

    def test_modest_join_dump_stays_high_until_arm(self):
        tracker = IngestLagTracker()
        # Typical join cushion is a few seconds of media, not a huge dump.
        feed_burst(
            tracker,
            WALL0,
            media_end=1004.0,
            media_start=1000.0,
            chunks=8,
            spread=0.3,
        )
        during = tracker.recent_speed(now=WALL0 + 0.3)
        self.assertFalse(tracker.is_armed)
        self.assertIsNotNone(during)
        self.assertGreater(during, 5.0)
        # Trailing cluster quiet before arm must not dilute into a fake under-1x.
        quiet = WALL0 + 0.3 + CLUSTER_GAP_SECONDS
        before_arm = tracker.recent_speed(now=quiet)
        self.assertGreater(before_arm, 5.0)
        self.assertAlmostEqual(before_arm, during, delta=0.5)
        tracker.settle(quiet)
        # Once armed, the join dump is no longer the badge; quiet alone must
        # not invent a soft under-1x reading.
        after_arm = tracker.recent_speed(now=quiet + 5.0)
        if after_arm is not None:
            self.assertGreaterEqual(after_arm, 1.0)

    def test_catch_up_then_realtime_decays_toward_one(self):
        tracker = IngestLagTracker()
        settle, media = arm_with_burst(
            tracker, media_start=1000.0, media_end=1030.0, spread=0.3
        )
        # Join dump already left a high mean; feed realtime until the window ages.
        wall, media = feed_realtime(
            tracker,
            settle + 0.1,
            media,
            duration=SPEED_WINDOW_SECONDS + 1.0,
            rate=1.0,
        )
        speed = tracker.recent_speed(now=wall)
        self.assertIsNotNone(speed)
        self.assertAlmostEqual(speed, 1.0, delta=0.2)

    def test_silence_poll_ignored_while_samples_are_fresh(self):
        tracker = IngestLagTracker()
        settle, media = arm_with_burst(tracker)
        wall, media = feed_realtime(
            tracker, settle + 0.1, media, duration=MIN_BUFFER + 2.0, rate=1.0
        )
        # Gap poll shortly after a real sample must not invent stall samples.
        # Trailing idle in recent_speed(now=...) is expected; project_silence
        # itself must not change the ring.
        at = wall + 0.2
        before = tracker.recent_speed(now=at)
        tracker.project_silence(at)
        after = tracker.recent_speed(now=at)
        self.assertAlmostEqual(before, after, places=2)

    def test_arm_keeps_catch_up_speed_history(self):
        tracker = IngestLagTracker()
        feed_burst(
            tracker,
            WALL0,
            media_end=1020.0,
            media_start=1000.0,
            chunks=8,
            spread=0.4,
        )
        before = tracker.recent_speed(now=WALL0 + 0.4)
        tracker.settle(WALL0 + 0.4 + CLUSTER_GAP_SECONDS)
        self.assertTrue(tracker.is_armed)
        after = tracker.recent_speed(now=WALL0 + 0.4 + CLUSTER_GAP_SECONDS)
        self.assertIsNotNone(before)
        self.assertIsNotNone(after)
        self.assertGreater(after, 5.0)

    def test_rate_recovery_requires_sustained_clear_debt(self):
        tracker = IngestLagTracker()
        settle, media = arm_with_burst(tracker)
        wall, media = feed_realtime(
            tracker,
            settle + 0.1,
            media,
            duration=MIN_BUFFER + TRIP_SECONDS / 0.5 + 2.0,
            rate=0.4,
        )
        assert_is_slow(self, tracker, wall)
        wall, media = feed_realtime(
            tracker,
            wall + TRIP_CONFIRM_SECONDS + 0.1,
            media,
            duration=TRIP_SECONDS / 0.6 + 5.0,
            rate=2.0,
        )
        self.assertLessEqual(tracker.cushion_debt(now=wall), CLEAR_SECONDS)
        self.assertFalse(tracker.is_recovered(TRIP_SECONDS, now=wall))
        catch = wall + RATE_RECOVERY_SECONDS
        media += RATE_RECOVERY_SECONDS
        tracker.observe(catch, media, "pts", PID)
        # Hold under clear line for the recovery window.
        self.assertFalse(tracker.is_recovered(TRIP_SECONDS, now=wall))
        self.assertTrue(tracker.is_recovered(TRIP_SECONDS, now=catch))

    def test_brief_healthy_blip_does_not_clear_high_debt(self):
        # Deep-debt clear needs a full confirm window of >=1.0x, not the short
        # paid-down timer. A one-second healthy blip must not re-anchor.
        tracker = IngestLagTracker()
        settle, media = arm_with_burst(tracker)
        wall, media = feed_realtime(
            tracker,
            settle + 0.1,
            media,
            duration=MIN_BUFFER + TRIP_SECONDS / 0.5 + 2.0,
            rate=0.4,
        )
        assert_is_slow(self, tracker, wall)
        self.assertGreater(tracker.cushion_debt(now=wall), CLEAR_SECONDS)
        burst_end = wall + CONFIRM_WINDOW_SECONDS
        media += CONFIRM_WINDOW_SECONDS * 1.2
        tracker.observe(burst_end, media, "pts", PID)
        self.assertGreater(tracker.cushion_debt(now=burst_end), CLEAR_SECONDS)
        raw = tracker.confirm_speed(now=burst_end)
        self.assertIsNotNone(raw)
        self.assertGreaterEqual(round(float(raw), 3), 1.0)
        hold = burst_end + RATE_RECOVERY_SECONDS
        media += RATE_RECOVERY_SECONDS
        tracker.observe(hold, media, "pts", PID)
        self.assertFalse(tracker.is_recovered(TRIP_SECONDS, now=hold))
        self.assertGreater(tracker.cushion_debt(now=hold), CLEAR_SECONDS)

    def test_sustained_healthy_delivery_clears_deep_debt(self):
        # After a stall, absolute debt cannot be paid at 1.0x. Holding realtime
        # for a full confirm window re-seats the cushion.
        tracker = IngestLagTracker()
        settle, media = arm_with_burst(tracker)
        wall, media = feed_realtime(
            tracker,
            settle + 0.1,
            media,
            duration=MIN_BUFFER + TRIP_SECONDS / 0.5 + 2.0,
            rate=0.4,
        )
        assert_is_slow(self, tracker, wall)
        self.assertGreater(tracker.cushion_debt(now=wall), CLEAR_SECONDS)
        recovered = False
        # Confirm window must fill with realtime before deep-recovery arms, then
        # hold for another confirm window. Allow a little slack for the edge.
        for _ in range(int(2 * CONFIRM_WINDOW_SECONDS / 0.25) + 8):
            wall += 0.25
            media += 0.25
            tracker.observe(wall, media, "pts", PID)
            if tracker.cushion_debt(now=wall) <= CLEAR_SECONDS:
                # Paid-down path; not what this test is covering.
                break
            recovered = tracker.is_recovered(TRIP_SECONDS, now=wall)
            if recovered:
                break
        self.assertTrue(recovered)
        self.assertEqual(tracker.cushion_debt(now=wall), 0.0)

    def test_oscillation_mean_stays_near_midpoint(self):
        tracker = IngestLagTracker()
        settle, media = arm_with_burst(tracker)
        wall = settle + 0.1
        # Alternate slow/fast half-second intervals past grace.
        end = wall + MIN_BUFFER + SPEED_WINDOW_SECONDS
        toggle = False
        while wall < end:
            toggle = not toggle
            rate = 0.2 if toggle else 1.5
            next_wall = min(wall + 0.5, end)
            media = media + (next_wall - wall) * rate
            # Two samples so the open cluster is trusted for rate emit.
            mid = wall + (next_wall - wall) / 2
            mid_media = media - (next_wall - mid) * rate
            tracker.observe(mid, mid_media, "pts", PID)
            tracker.observe(next_wall, media, "pts", PID)
            wall = next_wall
        speed = tracker.recent_speed(now=wall)
        self.assertIsNotNone(speed)
        # Calendar-window Δmedia/Δwall of 0.2/1.5 duty cycle is ~0.85.
        self.assertGreater(speed, 0.5)
        self.assertLess(speed, 1.2)
        self.assertLess(speed, 1.0)

    def test_recent_speed_reads_realtime_then_reflects_a_dump(self):
        tracker = IngestLagTracker()
        settle, media = arm_with_burst(tracker)
        wall, media = feed_realtime(
            tracker,
            settle + 0.1,
            media,
            duration=MIN_BUFFER + 30.0,
            rate=1.0,
        )
        self.assertAlmostEqual(tracker.recent_speed(now=wall), 1.0, delta=0.1)
        dump_wall = wall + 0.1
        feed_burst(
            tracker,
            dump_wall,
            media_end=media + 20.0,
            media_start=media,
            chunks=8,
            spread=0.3,
        )
        spike_at = dump_wall + 0.3
        self.assertGreater(tracker.recent_speed(now=spike_at), 1.0)

    def test_healthy_bursty_badge_stays_near_realtime(self):
        # Dump/gap feeds used to look soft forever under the old asymmetric EMA.
        tracker = IngestLagTracker()
        settle, media = arm_with_burst(tracker)
        wall, _media = feed_paced_bursts(
            tracker,
            settle + 0.1,
            media,
            duration=SPEED_WINDOW_SECONDS,
            rate=1.0,
            period=6.2,
        )
        # Mid-gap and at burst end should both read ~1x on the long window.
        self.assertAlmostEqual(tracker.recent_speed(now=wall), 1.0, delta=0.05)
        mid_gap = wall + 3.0
        self.assertAlmostEqual(
            tracker.recent_speed(now=mid_gap), 1.0, delta=0.05
        )

    def test_true_soft_delivery_still_shows_below_one(self):
        tracker = IngestLagTracker()
        settle, media = arm_with_burst(tracker)
        wall, _media = feed_paced_bursts(
            tracker,
            settle + 0.1,
            media,
            duration=SPEED_WINDOW_SECONDS,
            rate=0.9,
            period=6.2,
        )
        self.assertAlmostEqual(tracker.recent_speed(now=wall), 0.9, delta=0.05)

    def test_reset_clears_recent_speed(self):
        tracker = IngestLagTracker()
        settle, media = arm_with_burst(tracker)
        wall, _media = feed_realtime(
            tracker, settle + 0.1, media, duration=MIN_BUFFER + 2.0, rate=1.0
        )
        self.assertIsNotNone(tracker.recent_speed(now=wall))
        tracker.reset()
        self.assertIsNone(tracker.recent_speed())
        self.assertIsNone(tracker.recent_speed())

    def test_reset_clears_arm_and_prebuffer(self):
        tracker = IngestLagTracker()
        arm_with_burst(tracker)
        tracker.reset()
        self.assertFalse(tracker.is_armed)
        self.assertIsNone(tracker.prebuffer)
        self.assertIsNone(tracker.recent_speed())

    def test_pts_discontinuity_rearms_from_new_bitstream(self):
        tracker = IngestLagTracker()
        arm_with_burst(tracker)
        tracker.observe(WALL0 + 60.0, 10.0, "pts", PID)
        self.assertFalse(tracker.is_armed)
        feed_burst(tracker, WALL0 + 60.0, 40.0, 10.0)
        tracker.settle(WALL0 + 60.3 + CLUSTER_GAP_SECONDS)
        self.assertTrue(tracker.is_armed)
        self.assertGreater(tracker.prebuffer, 20.0)

    def test_single_sample_waits_extra_quiet_before_initial_settle(self):
        tracker = IngestLagTracker()
        tracker.observe(WALL0, 1000.0, "pts", PID)
        self.assertFalse(tracker.settle(WALL0 + CLUSTER_GAP_SECONDS))
        self.assertTrue(tracker.settle(WALL0 + 2 * CLUSTER_GAP_SECONDS))
        self.assertTrue(tracker.is_armed)

    def test_continuous_span_limit_arms_then_tracks(self):
        tracker = IngestLagTracker()
        wall = WALL0
        media = 1000.0
        while wall - WALL0 < CLUSTER_MAX_SPAN_SECONDS + 0.5:
            wall += 0.25
            media += 0.25
            tracker.observe(wall, media, "pts", PID)
        self.assertTrue(tracker.is_armed)
        self.assertLess(tracker.prebuffer, MIN_BUFFER)
        start = wall
        while wall - start < CLUSTER_MAX_SPAN_SECONDS + 0.5:
            wall += 0.25
            media += 0.25
            tracker.observe(wall, media, "pts", PID)
        tracker.settle(wall + 2 * CLUSTER_GAP_SECONDS)
        speed = tracker.recent_speed(now=wall)
        self.assertIsNotNone(speed)
        self.assertAlmostEqual(speed, 1.0, delta=0.15)

    def test_gapless_live_join_arms_once_the_ratio_is_realtime(self):
        tracker = IngestLagTracker()
        wall, media = feed_realtime(tracker, WALL0, 1000.0, duration=1.5, rate=1.0)
        self.assertFalse(tracker.is_armed)
        wall, _media = feed_realtime(tracker, wall, media, duration=1.0, rate=1.0)
        self.assertTrue(tracker.is_armed)
        self.assertLess(wall - WALL0, CLUSTER_MAX_SPAN_SECONDS)
        self.assertGreaterEqual(wall - WALL0, JOIN_STABLE_MIN_SECONDS)
        self.assertLess(tracker.prebuffer, 0.5)

    def test_gapless_catch_up_waits_out_the_span_cap(self):
        tracker = IngestLagTracker()
        feed_realtime(
            tracker,
            WALL0,
            1000.0,
            duration=CLUSTER_MAX_SPAN_SECONDS + 3.0,
            rate=2.0,
        )
        self.assertFalse(tracker.is_armed)
        self.assertIsNone(tracker.prebuffer)

    def test_gapless_catch_up_arms_after_delivery_settles(self):
        tracker = IngestLagTracker()
        wall, media = feed_realtime(tracker, WALL0, 1000.0, duration=12.0, rate=2.0)
        self.assertFalse(tracker.is_armed)
        feed_realtime(tracker, wall, media, duration=2.5, rate=1.0)
        self.assertTrue(tracker.is_armed)
        self.assertGreater(tracker.prebuffer, 5.0)

    def test_gapless_join_arms_at_the_fallback_if_it_never_settles(self):
        tracker = IngestLagTracker()
        wall, media = feed_realtime(
            tracker,
            WALL0,
            1000.0,
            duration=JOIN_ARM_FALLBACK_SECONDS - 1.0,
            rate=2.0,
            step=1.0,
        )
        self.assertFalse(tracker.is_armed)
        feed_realtime(tracker, wall, media, duration=3.0, rate=2.0, step=1.0)
        self.assertTrue(tracker.is_armed)
        self.assertGreaterEqual(
            tracker.join_wall_elapsed(tracker._armed_wall),
            JOIN_ARM_FALLBACK_SECONDS,
        )

    def test_later_dump_replaces_trickle_budget(self):
        tracker = IngestLagTracker()
        _settle, media = arm_with_burst(
            tracker, media_start=1000.0, media_end=1001.0, spread=0.3
        )
        self.assertLess(tracker.prebuffer, ADOPT_CUSHION_SECONDS)
        dump_wall = tracker._armed_wall + 1.0
        feed_burst(tracker, dump_wall, media + 30.0, media, spread=0.3)
        tracker.settle(dump_wall + 0.3 + CLUSTER_GAP_SECONDS)
        self.assertGreater(tracker.prebuffer, 20.0)
        self.assertTrue(tracker.join_prebuffer_pending)

    def test_adopt_floor_tracks_configured_minimum(self):
        strict = IngestLagTracker(adopt_floor=10)
        _settle, media = arm_with_burst(
            strict, media_start=1000.0, media_end=1001.0, spread=0.3
        )
        wall = strict._armed_wall + 1.0
        # ~5.7s of cushion. Clears the default floor of 4, not a floor of 10.
        feed_burst(strict, wall, media + 6.0, media, spread=0.3)
        strict.settle(wall + 0.3 + CLUSTER_GAP_SECONDS)
        self.assertLess(strict.prebuffer, 2.0)

        loose = IngestLagTracker(adopt_floor=2)
        _settle, media = arm_with_burst(
            loose, media_start=1000.0, media_end=1001.0, spread=0.3
        )
        wall = loose._armed_wall + 1.0
        feed_burst(loose, wall, media + 3.0, media, spread=0.2)
        loose.settle(wall + 0.2 + CLUSTER_GAP_SECONDS)
        self.assertGreater(loose.prebuffer, 2.0)

    def test_small_jitter_does_not_replace_budget(self):
        tracker = IngestLagTracker()
        _settle, media = arm_with_burst(
            tracker, media_start=1000.0, media_end=1001.0, spread=0.3
        )
        before = tracker.prebuffer
        jitter_wall = tracker._armed_wall + 1.0
        feed_burst(tracker, jitter_wall, media + 1.2, media, spread=0.2)
        tracker.settle(jitter_wall + 0.2 + CLUSTER_GAP_SECONDS)
        self.assertAlmostEqual(tracker.prebuffer, before, places=2)

    def test_min_rate_samples_constant(self):
        self.assertGreaterEqual(MIN_RATE_SAMPLES, 2)

    def test_has_debt_anchor_follows_the_anchor(self):
        tracker = IngestLagTracker()
        self.assertFalse(tracker.has_debt_anchor)
        arm_with_burst(tracker)
        # Seated on the live PTS when the join arms, not on the first trip.
        self.assertTrue(tracker.has_debt_anchor)
        tracker.reset()
        self.assertFalse(tracker.has_debt_anchor)

    def test_single_sample_quiet_arm_seats_debt_immediately(self):
        tracker = IngestLagTracker()
        tracker.observe(WALL0, 1000.0, "pts", PID)
        self.assertTrue(tracker.settle(WALL0 + 2 * CLUSTER_GAP_SECONDS))
        self.assertTrue(tracker.is_armed)
        self.assertTrue(tracker.has_debt_anchor)
        settle = WALL0 + 2 * CLUSTER_GAP_SECONDS
        self.assertTrue(tracker.rate_ready(now=settle))
        # Healthy silence is gap-credited; a real stall past the rhythm spends
        # the cushion from the live PTS even with only one sample.
        quiet = settle + 2.0
        self.assertLess(tracker.cushion_debt(now=quiet), 0.5)
        stall_at = settle + tracker._stall_after() + 2.0
        self.assertGreater(tracker.cushion_debt(now=stall_at), 1.0)

    def test_window_count_matches_the_plain_list_definition(self):
        # _window_count replaced a list rebuild with bisect. Hold it to the
        # original definition across bursty, steady and stalled shapes.
        rnd = random.Random(11)
        for trial in range(80):
            tracker = IngestLagTracker()
            wall, media = WALL0, 1000.0
            for _ in range(300):
                wall += rnd.choice([0.02, 0.1, 0.1, 0.5, 2.5])
                media += rnd.choice([0.0, 0.02, 0.1, 0.5, 3.0])
                tracker.observe(wall, media, "pts", PID)
                if rnd.random() < 0.05:
                    tracker.settle(wall + CLUSTER_GAP_SECONDS)
                self.assertEqual(
                    tracker._window_count(),
                    reference_window_count(tracker),
                    f"trial {trial}",
                )


def reference_window_count(tracker):
    """The pre-bisect definition: filter a list, then count what survives."""
    samples = list(tracker._samples)
    if tracker._open is None or len(samples) < 2:
        return len(samples)
    open_start = tracker._open[0]
    pre = [s for s in samples if s[0] < open_start]
    if len(pre) < 2:
        return len(samples)
    gained = wrap_delta_seconds(tracker._open[2], pre[-1][1])
    if gained < 0:
        return len(pre)
    gap_wall = open_start - pre[-1][0]
    if gap_wall > 0 and gained < gap_wall:
        return len(pre)
    return len(samples)


def make_manager():
    """A StreamManager wired for ingest detection with no I/O or timers."""
    manager = StreamManager.__new__(StreamManager)
    manager.stopping = False
    manager.running = True
    manager.buffering = False
    manager.channel_id = "gate"
    manager.current_stream_id = None
    manager.buffering_speed = SPEED_THRESHOLD
    manager.new_client_behind_seconds = CLIENT_BEHIND
    manager.cushion_trip_seconds = TRIP_SECONDS
    manager.experimental_ingest_buffer = True
    manager.buffer = MagicMock()
    manager.buffer.redis_client = None
    manager._update_ffmpeg_stats_in_redis = MagicMock()
    manager._update_buffering_state = MagicMock()
    manager._init_ingest_lag_state()
    # Timers belong to the live loop. Tests drive the same entry points by hand.
    manager._arm_ingest_quiet_timer = MagicMock()
    manager._arm_ingest_gap_timer = MagicMock()
    return manager


def replay(timeline, horizon=600.0, step=0.1):
    """Run a provider timeline through the real manager decision path.

    Drives ``observe``, the settle timer, the gap poll cadence and
    ``_evaluate_ingest_lag`` exactly as the live hooks do, with time injected.
    Returns the trip and clear times as offsets from the start of the timeline.
    """
    manager = make_manager()
    tracker = manager.ingest_lag
    clock = {"now": WALL0}
    events = []

    def apply(is_buffering, speed=None, empty_for=None, failover_async=False):
        if is_buffering and not manager.buffering:
            manager.buffering = True
            events.append(("trip", clock["now"] - WALL0))
        elif not is_buffering and manager.buffering:
            manager.buffering = False
            events.append(("clear", clock["now"] - WALL0))

    manager._update_buffering_state = MagicMock(side_effect=apply)
    index = 0
    next_poll = None
    offset = 0.0
    while offset <= horizon:
        now = WALL0 + offset
        clock["now"] = now
        while index < len(timeline) and timeline[index][0] <= offset + 1e-9:
            wall = WALL0 + timeline[index][0]
            clock["now"] = wall
            finished = tracker.observe(wall, timeline[index][1], "pts", PID)
            manager._evaluate_after_sample(tracker, wall, force=finished)
            index += 1
        clock["now"] = now
        deadline = tracker.quiet_deadline
        if deadline is not None and now >= deadline and tracker.settle(now):
            manager._evaluate_ingest_lag(now=now)
        if tracker.is_armed or tracker.has_rate:
            if next_poll is None:
                next_poll = now + manager._ingest_gap_poll_delay(tracker, now=now)
            if now >= next_poll:
                tracker.project_silence(now)
                manager._evaluate_ingest_lag(now=now)
                next_poll = now + manager._ingest_gap_poll_delay(tracker, now=now)
        offset += step
    return events


def trips(events):
    return [t for kind, t in events if kind == "trip"]


class IngestSampleGateTests(SimpleTestCase):
    def _manager(self):
        return make_manager()

    def test_unarmed_reads_are_always_due(self):
        manager = self._manager()
        manager._ingest_last_sample_wall = 1.0
        self.assertFalse(manager.ingest_lag.is_armed)
        self.assertTrue(manager._ingest_sample_due(manager.ingest_lag, 1.02))

    def test_long_unarmed_catch_up_backs_off_sampling(self):
        manager = self._manager()
        tracker = manager.ingest_lag
        wall, _media = feed_realtime(
            tracker, WALL0, 1000.0, duration=JOIN_DENSE_SAMPLE_SECONDS + 1.0, rate=2.0
        )
        self.assertFalse(tracker.is_armed)
        manager._ingest_last_sample_wall = wall
        manager._ingest_sample_interval = 0.0
        for _ in range(40):
            manager._adapt_ingest_sample_interval(tracker, after_gap=False)
        self.assertAlmostEqual(
            manager._ingest_sample_interval,
            manager._INGEST_JOIN_SAMPLE_TARGET,
            delta=0.02,
        )
        self.assertFalse(manager._ingest_sample_due(tracker, wall + 0.02))

    def test_armed_steady_reads_wait_but_a_gap_does_not(self):
        manager = self._manager()
        arm_with_burst(manager.ingest_lag)
        # Steady-state cadence after the join backoff has settled.
        manager._ingest_sample_interval = manager._INGEST_SAMPLE_TARGET
        manager._ingest_last_sample_wall = 2_000.0
        self.assertFalse(manager._ingest_sample_due(manager.ingest_lag, 2_000.05))
        self.assertTrue(
            manager._ingest_sample_due(
                manager.ingest_lag,
                2_000.0 + manager._INGEST_SAMPLE_TARGET + 0.001,
            )
        )
        self.assertTrue(
            manager._ingest_sample_due(
                manager.ingest_lag, 2_000.0 + CLUSTER_GAP_SECONDS
            )
        )

    def test_sample_interval_backs_off_toward_target_and_resets_on_gap(self):
        manager = self._manager()
        arm_with_burst(manager.ingest_lag)
        manager._ingest_sample_interval = 0.0
        for _ in range(40):
            manager._adapt_ingest_sample_interval(manager.ingest_lag, after_gap=False)
        self.assertAlmostEqual(
            manager._ingest_sample_interval, manager._INGEST_SAMPLE_TARGET, delta=0.02
        )
        self.assertLessEqual(
            manager._ingest_sample_interval, manager._INGEST_SAMPLE_MAX
        )
        manager._adapt_ingest_sample_interval(manager.ingest_lag, after_gap=True)
        self.assertEqual(manager._ingest_sample_interval, 0.0)

    def test_gap_poll_speeds_up_when_under_threshold(self):
        manager = self._manager()
        settle, media = arm_with_burst(manager.ingest_lag)
        wall, _media = feed_realtime(
            manager.ingest_lag,
            settle + 0.1,
            media,
            duration=MIN_BUFFER + SPEED_WINDOW_SECONDS,
            rate=1.0,
        )
        # Re-seat past join-settle quiet so this checks poll cadence vs debt.
        tracker = manager.ingest_lag
        tracker._debt_anchor_wall = tracker._rate_wall
        tracker._debt_anchor_media = tracker._rate_media
        tracker._debt = 0.0
        delay = manager._ingest_gap_poll_delay(tracker, now=wall)
        self.assertEqual(delay, manager._INGEST_GAP_POLL_SECONDS)
        wall, _media = feed_realtime(
            manager.ingest_lag,
            wall + 0.1,
            _media,
            duration=CLEAR_SECONDS / 0.6 + 2.0,
            rate=0.4,
        )
        delay = manager._ingest_gap_poll_delay(manager.ingest_lag, now=wall)
        self.assertEqual(delay, manager._INGEST_GAP_POLL_FAST_SECONDS)
        manager.buffering = True
        delay = manager._ingest_gap_poll_delay(manager.ingest_lag, now=wall)
        self.assertEqual(delay, manager._INGEST_GAP_POLL_FAST_SECONDS)

    def test_unchanged_speed_is_not_rewritten_to_redis(self):
        manager = self._manager()
        settle, media = arm_with_burst(manager.ingest_lag)
        wall, _media = feed_realtime(
            manager.ingest_lag,
            settle + 0.1,
            media,
            duration=MIN_BUFFER + 8.0,
            rate=1.0,
        )
        manager._evaluate_ingest_lag(now=wall)
        manager._evaluate_ingest_lag(now=wall + 0.1)
        self.assertEqual(manager._update_ffmpeg_stats_in_redis.call_count, 1)
        # A different rounded speed inside the publish interval still waits.
        manager._last_published_ingest_speed = 0.5
        manager._evaluate_ingest_lag(now=wall + 0.2)
        self.assertEqual(manager._update_ffmpeg_stats_in_redis.call_count, 1)
        # Once the interval has passed, the changed value goes out.
        manager._evaluate_ingest_lag(
            now=wall + manager._INGEST_SPEED_PUBLISH_MIN_SECONDS + 0.1
        )
        self.assertEqual(manager._update_ffmpeg_stats_in_redis.call_count, 2)

    def test_clockless_read_does_not_consume_the_sample_slot(self):
        manager = self._manager()
        arm_with_burst(manager.ingest_lag)
        manager._ingest_last_sample_wall = None
        with patch(
            "apps.proxy.live_proxy.input.manager.last_clock_on_pid",
            return_value=None,
        ):
            manager._on_packets_received(b"\x47" * 188, wall=3_000.0)
        self.assertIsNone(manager._ingest_last_sample_wall)
        self.assertTrue(manager._ingest_sample_due(manager.ingest_lag, 3_000.01))

    def test_a_clock_sample_starts_the_throttle(self):
        manager = self._manager()
        _settle, media = arm_with_burst(manager.ingest_lag)
        with patch(
            "apps.proxy.live_proxy.input.manager.last_clock_on_pid",
            return_value=media + 1.0,
        ):
            manager._on_packets_received(b"\x47" * 188, wall=4_000.0)
        self.assertEqual(manager._ingest_last_sample_wall, 4_000.0)
        self.assertGreater(manager._ingest_sample_interval, 0.0)
        self.assertFalse(
            manager._ingest_sample_due(
                manager.ingest_lag,
                4_000.0 + manager._ingest_sample_interval * 0.5,
            )
        )

    def test_reset_does_not_allocate_when_experimental_off(self):
        manager = StreamManager.__new__(StreamManager)
        manager.experimental_ingest_buffer = False
        manager.ingest_lag = None
        manager._ingest_timer = None
        manager._ingest_gap_timer = None
        manager._ingest_last_sample_wall = None
        manager.channel_id = "off"
        manager.buffer = MagicMock()
        manager.buffer.redis_client = None
        manager._reset_ingest_lag()
        self.assertIsNone(manager.ingest_lag)

    def test_evaluate_persists_join_prebuffer_once(self):
        manager = self._manager()
        manager.stopping = False
        manager.running = True
        manager.buffering = False
        manager.current_stream_id = 42
        manager.buffer = MagicMock()
        manager.buffer.redis_client = MagicMock()
        arm_with_burst(manager.ingest_lag)
        self.assertTrue(manager.ingest_lag.join_prebuffer_pending)
        # The write runs in its own greenlet. Run it inline here.
        inline_spawn = lambda fn, *a, **k: fn(*a, **k)  # noqa: E731
        with patch(
            "apps.proxy.live_proxy.input.manager.gevent.spawn", side_effect=inline_spawn
        ), patch(
            "apps.proxy.live_proxy.services.channel_service.ChannelService._update_stream_stats_in_db"
        ) as persist:
            manager._evaluate_ingest_lag(now=manager.ingest_lag._armed_wall + 0.1)
            persist.assert_called_once()
            args, kwargs = persist.call_args
            self.assertEqual(args, (42,))
            self.assertIn("join_prebuffer_seconds", kwargs)
            self.assertAlmostEqual(kwargs["join_prebuffer_seconds"], 29.7, places=1)
        self.assertFalse(manager.ingest_lag.join_prebuffer_pending)
        with patch(
            "apps.proxy.live_proxy.input.manager.gevent.spawn", side_effect=inline_spawn
        ), patch(
            "apps.proxy.live_proxy.services.channel_service.ChannelService._update_stream_stats_in_db"
        ) as persist_again:
            manager._evaluate_ingest_lag(now=manager.ingest_lag._armed_wall + 0.2)
            persist_again.assert_not_called()

    def test_join_prebuffer_waits_for_a_stream_id_and_never_blocks_the_reader(self):
        manager = self._manager()
        manager.current_stream_id = None
        arm_with_burst(manager.ingest_lag)
        with patch("apps.proxy.live_proxy.input.manager.gevent.spawn") as spawn:
            manager._evaluate_ingest_lag(now=manager.ingest_lag._armed_wall + 0.1)
            spawn.assert_not_called()
        self.assertTrue(manager.ingest_lag.join_prebuffer_pending)
        manager.current_stream_id = 7
        with patch("apps.proxy.live_proxy.input.manager.gevent.spawn") as spawn:
            manager._evaluate_ingest_lag(now=manager.ingest_lag._armed_wall + 0.2)
            spawn.assert_called_once()
            # Marked persisted before the greenlet runs, so a slow database
            # cannot cause a second spawn on the next evaluate.
            self.assertFalse(manager.ingest_lag.join_prebuffer_pending)

    def test_reconnect_resets_armed_ingest_budget(self):
        manager = self._manager()
        manager.stopping = False
        manager.running = True
        manager.reconnecting = False
        manager.url_switching = False
        manager.transcode = False
        manager.socket = None
        manager.connected = True
        manager.channel_name = "gate"
        manager.current_stream_id = 1
        manager.buffer = MagicMock()
        manager.buffer.redis_client = None
        arm_with_burst(manager.ingest_lag)
        self.assertTrue(manager.ingest_lag.is_armed)
        self.assertIsNotNone(manager.ingest_lag.locked_pid)

        with patch.object(manager, "_close_connection"), patch.object(
            manager, "_wait_for_existing_processes_to_close", return_value=True
        ), patch.object(
            manager, "_establish_http_connection", return_value=True
        ), patch(
            "apps.proxy.live_proxy.input.manager.log_system_event"
        ):
            self.assertTrue(manager._attempt_reconnect())

        self.assertFalse(manager.ingest_lag.is_armed)
        self.assertIsNone(manager.ingest_lag.locked_pid)
        self.assertIsNone(manager.ingest_lag.prebuffer)

    def test_gap_poll_stays_slow_when_cushion_debt_is_near_zero(self):
        manager = self._manager()
        settle, media = arm_with_burst(manager.ingest_lag)
        wall, _media = feed_realtime(
            manager.ingest_lag,
            settle + 0.1,
            media,
            duration=MIN_BUFFER + SPEED_WINDOW_SECONDS,
            rate=1.0,
        )
        tracker = manager.ingest_lag
        tracker._debt_anchor_wall = tracker._rate_wall
        tracker._debt_anchor_media = tracker._rate_media
        tracker._debt = 0.0
        self.assertEqual(
            manager._ingest_gap_poll_delay(tracker, now=wall),
            manager._INGEST_GAP_POLL_SECONDS,
        )

    def test_gap_poll_speeds_up_when_cushion_debt_rises(self):
        manager = self._manager()
        settle, media = arm_with_burst(manager.ingest_lag)
        wall, media = feed_realtime(
            manager.ingest_lag,
            settle + 0.1,
            media,
            duration=MIN_BUFFER + 1.0,
            rate=1.0,
        )
        tracker = manager.ingest_lag
        tracker._debt_anchor_wall = tracker._rate_wall
        tracker._debt_anchor_media = tracker._rate_media
        tracker._debt = 0.0
        wall, _media = feed_realtime(
            manager.ingest_lag,
            wall + 0.1,
            media,
            duration=CLEAR_SECONDS / 0.05 + 2.0,
            rate=0.95,
        )
        self.assertEqual(
            manager._ingest_gap_poll_delay(manager.ingest_lag, now=wall),
            manager._INGEST_GAP_POLL_FAST_SECONDS,
        )

    def test_failover_does_not_reset_the_tracker_a_second_time(self):
        # update_url already reset it for the new stream. A second reset could
        # wipe a join measurement the new connection has already started.
        manager = self._manager()
        manager.buffering = True
        manager.buffering_start_time = 1.0
        manager.channel_name = "gate"
        manager.current_stream_id = 2
        manager.buffer = MagicMock()
        manager.buffer.redis_client = MagicMock()
        arm_with_burst(manager.ingest_lag)
        with patch("apps.proxy.live_proxy.input.manager.log_system_event"):
            manager._after_buffering_failover(15.0, 1, {})
        self.assertFalse(manager.buffering)
        self.assertTrue(manager.ingest_lag.is_armed)
        manager.buffer.redis_client.hdel.assert_not_called()

    def test_reset_skips_redis_entirely_when_the_feature_is_off(self):
        manager = StreamManager.__new__(StreamManager)
        manager.ingest_lag = None
        manager.channel_id = "off"
        manager.buffer = MagicMock()
        manager.buffer.redis_client = MagicMock()
        manager._reset_ingest_lag()
        manager.buffer.redis_client.hdel.assert_not_called()

    def test_evaluate_passes_speed_and_empty_for_on_trip(self):
        manager = self._manager()
        manager.buffering = False
        settle, media = arm_with_burst(manager.ingest_lag)
        wall, media = feed_realtime(
            manager.ingest_lag,
            settle + 0.1,
            media,
            duration=MIN_BUFFER + TRIP_SECONDS / 0.5 + 2.0,
            rate=0.5,
        )
        # Seat the debt and start the empty hold without tripping yet.
        self.assertFalse(
            manager.ingest_lag.is_slow(TRIP_SECONDS, now=wall)
        )
        trip_at = wall + TRIP_CONFIRM_SECONDS + 0.2
        manager._evaluate_ingest_lag(now=trip_at)
        manager._update_buffering_state.assert_called()
        kwargs = manager._update_buffering_state.call_args.kwargs
        self.assertTrue(manager._update_buffering_state.call_args.args[0])
        self.assertIsNotNone(kwargs.get("speed"))
        self.assertGreaterEqual(kwargs["empty_for"], TRIP_CONFIRM_SECONDS)

    def test_latched_buffering_without_anchor_still_hits_timeout_path(self):
        manager = self._manager()
        manager.buffering = True
        manager.buffering_start_time = 1_000.0
        manager.buffering_timeout = 5.0
        manager.buffering_timeout_error_stream_id = None
        manager._buffering_failover_running = False
        manager.ingest_lag._clear_debt_anchor()
        with patch.object(
            manager, "_update_buffering_state", wraps=manager._update_buffering_state
        ) as update:
            with patch("apps.proxy.live_proxy.input.manager.time") as t:
                t.time.return_value = 1_010.0
                manager._evaluate_ingest_lag(now=1_010.0)
        update.assert_called_once()
        self.assertTrue(update.call_args.args[0])

    def test_reset_ingest_lag_clears_buffering_latch(self):
        manager = self._manager()
        manager.buffering = True
        manager.buffering_start_time = 1_000.0
        manager.channel_name = "gate"
        manager.buffer = MagicMock()
        manager.buffer.redis_client = MagicMock()
        manager.buffering_timeout_error_stream_id = (
            StreamManager._NO_BUFFERING_TIMEOUT_ERROR
        )
        manager._update_buffering_state = StreamManager._update_buffering_state.__get__(
            manager, StreamManager
        )
        manager._reset_ingest_lag()
        self.assertFalse(manager.buffering)
        self.assertIsNone(manager.buffering_start_time)

    def test_recovery_hold_restarts_when_clear_path_changes(self):
        tracker = IngestLagTracker()
        settle, media = arm_with_burst(tracker)
        wall, media = feed_realtime(
            tracker,
            settle + 0.1,
            media,
            duration=MIN_BUFFER + TRIP_SECONDS / 0.5 + 2.0,
            rate=0.4,
        )
        assert_is_slow(self, tracker, wall)
        wall, media = feed_realtime(
            tracker,
            wall + 0.1,
            media,
            duration=CONFIRM_WINDOW_SECONDS,
            rate=1.2,
        )
        self.assertGreater(tracker.cushion_debt(now=wall), CLEAR_SECONDS)
        tracker.is_recovered(TRIP_SECONDS, now=wall)
        self.assertEqual(tracker._recovery_mode, "deep")
        self.assertIsNotNone(tracker._rate_ok_since)
        ok_since = tracker._rate_ok_since
        wall, media = feed_realtime(
            tracker,
            wall + 0.1,
            media,
            duration=TRIP_SECONDS / 0.6 + 5.0,
            rate=2.0,
        )
        self.assertLessEqual(tracker.cushion_debt(now=wall), CLEAR_SECONDS)
        tracker.is_recovered(TRIP_SECONDS, now=wall)
        self.assertEqual(tracker._recovery_mode, "shallow")
        self.assertNotEqual(tracker._rate_ok_since, ok_since)

    def test_pts_discontinuity_clears_buffering_and_stale_cushion(self):
        # Same-URL hard backward PTS jump disarms without _reset_ingest_lag.
        # Must unlatch buffering and drop Redis cushion so the card cannot
        # keep the old budget until buffering timeout.
        manager = self._manager()
        manager.stopping = False
        manager.running = True
        manager.buffering = True
        manager.buffering_start_time = 1_000.0
        manager.channel_name = "gate"
        manager.buffer = MagicMock()
        manager.buffer.redis_client = MagicMock()
        manager.buffering_timeout_error_stream_id = (
            StreamManager._NO_BUFFERING_TIMEOUT_ERROR
        )
        manager._update_buffering_state = StreamManager._update_buffering_state.__get__(
            manager, StreamManager
        )
        settle, media = arm_with_burst(manager.ingest_lag)
        manager._last_published_cushion_remaining = 1.2
        with patch(
            "apps.proxy.live_proxy.input.manager.last_clock_on_pid",
            return_value=media - 30.0,
        ):
            manager._on_packets_received(b"\x47" * 188, wall=settle + 1.0)
        self.assertFalse(manager.ingest_lag.is_armed)
        self.assertFalse(manager.buffering)
        self.assertIsNone(manager._last_published_cushion_remaining)
        manager.buffer.redis_client.hdel.assert_called()

    def test_publish_yield_discontinuity_does_not_reopen_buffering(self):
        # Gap poll used to decide "still buffering", yield on Redis, then apply
        # that decision after a discontinuity had already cleared the latch.
        manager = self._manager()
        manager.stopping = False
        manager.running = True
        manager.channel_name = "gate"
        manager.buffer = MagicMock()
        manager.buffer.redis_client = MagicMock()
        manager.buffering_timeout_error_stream_id = (
            StreamManager._NO_BUFFERING_TIMEOUT_ERROR
        )
        manager._update_buffering_state = (
            StreamManager._update_buffering_state.__get__(manager, StreamManager)
        )
        settle, media = arm_with_burst(manager.ingest_lag)
        wall, media = feed_realtime(
            manager.ingest_lag,
            settle + 0.1,
            media,
            duration=MIN_BUFFER + 2.0,
            rate=1.0,
        )
        manager.buffering = True
        manager.buffering_start_time = wall

        def discontinuity_during_publish(tracker, now=None):
            manager.buffering = False
            tracker._armed = False
            tracker._clear_debt_anchor()

        manager._publish_cushion_remaining = discontinuity_during_publish
        manager._evaluate_ingest_lag(now=wall)
        self.assertFalse(manager.buffering)

    def test_state_write_skipped_when_latch_clears_during_log(self):
        manager = self._manager()
        manager.buffering = False
        manager.channel_name = "gate"
        manager.current_stream_id = 1
        manager.buffer = MagicMock()
        manager.buffer.redis_client = MagicMock()
        manager.buffering_timeout_error_stream_id = (
            StreamManager._NO_BUFFERING_TIMEOUT_ERROR
        )
        manager._update_buffering_state = (
            StreamManager._update_buffering_state.__get__(manager, StreamManager)
        )

        def clear_latch(*args, **kwargs):
            manager.buffering = False

        with patch(
            "apps.proxy.live_proxy.input.manager.log_system_event",
            side_effect=clear_latch,
        ):
            manager._update_buffering_state(True, speed=0.4)
        self.assertFalse(manager.buffering)
        manager.buffer.redis_client.hset.assert_not_called()

    def test_loose_clock_resumes_former_pts_when_last_clock_misses(self):
        manager = self._manager()
        manager.stopping = False
        manager.running = True
        settle, media = arm_with_burst(manager.ingest_lag)
        old_pid = manager.ingest_lag.locked_pid
        manager.ingest_lag.observe(settle + 1.0, media - 30.0, "pts", old_pid)
        self.assertTrue(manager.ingest_lag.clock_loose)
        resumed = media + 50.0
        with patch(
            "apps.proxy.live_proxy.input.manager.last_clock_on_pid",
            return_value=None,
        ), patch(
            "apps.proxy.live_proxy.input.manager.sample_media_clock_for_relock",
            return_value=(resumed, "pts", old_pid),
        ):
            manager._on_packets_received(b"\x47" * 188, wall=settle + 2.0)
        self.assertFalse(manager.ingest_lag.clock_loose)
        self.assertEqual(manager.ingest_lag.locked_pid, old_pid)

    def test_loose_clock_relocks_when_old_pid_is_absent(self):
        manager = self._manager()
        manager.stopping = False
        manager.running = True
        manager.buffer = MagicMock()
        manager.buffer.redis_client = None
        settle, media = arm_with_burst(manager.ingest_lag)
        old_pid = manager.ingest_lag.locked_pid
        manager.ingest_lag.observe(settle + 1.0, media - 30.0, "pts", old_pid)
        self.assertTrue(manager.ingest_lag.clock_loose)
        self.assertEqual(manager.ingest_lag.locked_pid, old_pid)
        new_pid = old_pid + 1
        with patch(
            "apps.proxy.live_proxy.input.manager.last_clock_on_pid",
            return_value=None,
        ), patch(
            "apps.proxy.live_proxy.input.manager.sample_media_clock_for_relock",
            return_value=(2000.0, "pts", new_pid),
        ):
            manager._on_packets_received(b"\x47" * 188, wall=settle + 2.0)
        self.assertEqual(manager.ingest_lag.locked_pid, new_pid)
        self.assertFalse(manager.ingest_lag.clock_loose)

    def test_pid_relock_clears_buffering_when_already_disarmed(self):
        # Discontinuity disarms before the next packet. Relock must still drop
        # the latch without waiting for buffering timeout.
        manager = self._manager()
        manager.stopping = False
        manager.running = True
        manager.buffering = True
        manager.buffering_start_time = 1_000.0
        manager.channel_name = "gate"
        manager.buffer = MagicMock()
        manager.buffer.redis_client = MagicMock()
        manager.buffering_timeout_error_stream_id = (
            StreamManager._NO_BUFFERING_TIMEOUT_ERROR
        )
        manager._update_buffering_state = StreamManager._update_buffering_state.__get__(
            manager, StreamManager
        )
        settle, media = arm_with_burst(manager.ingest_lag)
        old_pid = manager.ingest_lag.locked_pid
        manager.ingest_lag.observe(settle + 1.0, media - 30.0, "pts", old_pid)
        self.assertFalse(manager.ingest_lag.is_armed)
        self.assertTrue(manager.ingest_lag.clock_loose)
        manager._last_published_cushion_remaining = 1.2
        new_pid = old_pid + 1
        with patch(
            "apps.proxy.live_proxy.input.manager.last_clock_on_pid",
            return_value=None,
        ), patch(
            "apps.proxy.live_proxy.input.manager.sample_media_clock_for_relock",
            return_value=(2000.0, "pts", new_pid),
        ):
            manager._on_packets_received(b"\x47" * 188, wall=settle + 2.0)
        self.assertFalse(manager.buffering)
        self.assertIsNone(manager._last_published_cushion_remaining)
        manager.buffer.redis_client.hdel.assert_called()


class IngestStopSafetyTests(SimpleTestCase):
    """stop_channel deletes the Redis metadata before it stops the manager."""

    def _latched_manager(self, redis):
        manager = make_manager()
        manager.channel_name = "gate"
        manager.buffering = True
        manager.buffering_start_time = 1_000.0
        manager.buffering_timeout = 15
        manager.current_stream_id = 1
        manager.buffer = MagicMock()
        manager.buffer.redis_client = redis
        manager.buffering_timeout_error_stream_id = (
            StreamManager._NO_BUFFERING_TIMEOUT_ERROR
        )
        manager._update_buffering_state = (
            StreamManager._update_buffering_state.__get__(manager, StreamManager)
        )
        return manager

    def test_stop_writes_nothing_to_redis_while_latched_buffering(self):
        # A write here would recreate the deleted metadata hash as a stateless
        # orphan (state=active), or overwrite STOPPING.
        redis = MagicMock()
        manager = self._latched_manager(redis)
        manager._close_socket = MagicMock()
        manager._buffer_check_timers = []
        manager.current_response = None
        manager.current_session = None
        manager._smoothed_output_bitrate = None
        arm_with_burst(manager.ingest_lag)

        StreamManager.stop(manager)

        self.assertEqual(redis.method_calls, [])
        self.assertTrue(manager.stopping)
        self.assertFalse(manager.buffering)
        self.assertFalse(manager.ingest_lag.is_armed)

    def test_stop_style_reset_drops_timers_and_local_state_only(self):
        redis = MagicMock()
        manager = self._latched_manager(redis)
        timer = MagicMock()
        manager._ingest_timer = timer
        manager._ingest_gap_timer = MagicMock()
        arm_with_burst(manager.ingest_lag)

        manager._reset_ingest_lag(publish=False)

        timer.kill.assert_called_once()
        self.assertIsNone(manager._ingest_timer)
        self.assertIsNone(manager._ingest_gap_timer)
        self.assertEqual(redis.method_calls, [])

    def test_a_reconnect_reset_still_publishes_the_clear(self):
        redis = MagicMock()
        manager = self._latched_manager(redis)
        with patch("apps.proxy.live_proxy.input.manager.log_system_event"):
            manager._reset_ingest_lag()
        self.assertFalse(manager.buffering)
        states = [
            c.args[2] for c in redis.hset.call_args_list if len(c.args) >= 3
        ]
        self.assertIn("active", states)

    def test_late_state_writes_are_dropped_once_stopping(self):
        redis = MagicMock()
        manager = self._latched_manager(redis)
        manager.stopping = True
        with patch("apps.proxy.live_proxy.input.manager.log_system_event"):
            manager._update_buffering_state(False)
            self.assertFalse(manager.buffering)
            manager._update_buffering_state(True)
            self.assertTrue(manager.buffering)
            manager._after_buffering_failover(1.0, 1, {})
        redis.hset.assert_not_called()

    def test_evaluate_is_inert_once_stopping(self):
        manager = make_manager()
        manager.stopping = True
        manager._publish_cushion_remaining = MagicMock()
        manager._evaluate_ingest_lag(now=WALL0)
        manager._publish_cushion_remaining.assert_not_called()
        manager._update_buffering_state.assert_not_called()
        manager._update_ffmpeg_stats_in_redis.assert_not_called()

    def test_stop_during_the_publish_yield_skips_the_decision(self):
        # The cushion write yields to the hub. A channel stop that begins
        # there must not go on to latch buffering or fail over.
        manager = make_manager()
        manager.buffering = True

        def stop_during_publish(tracker, now=None):
            manager.stopping = True

        manager._publish_cushion_remaining = stop_during_publish
        manager._evaluate_ingest_lag(now=WALL0)
        manager._update_buffering_state.assert_not_called()

    def test_cushion_publish_is_skipped_once_stopping(self):
        redis = MagicMock()
        manager = make_manager()
        manager.buffer.redis_client = redis
        arm_with_burst(manager.ingest_lag)
        tracker = manager.ingest_lag
        wall, _media = feed_realtime(
            tracker, WALL0 + 3.0, 1030.0, duration=MIN_BUFFER + 2.0, rate=1.0
        )
        tracker.is_slow(TRIP_SECONDS, now=wall)
        self.assertTrue(tracker.has_debt_anchor)
        manager.stopping = True
        manager._publish_cushion_remaining(tracker, now=wall)
        redis.hset.assert_not_called()


class IngestFailoverThrottleTests(SimpleTestCase):
    def _manager(self):
        manager = make_manager()
        manager.channel_name = "single-stream"
        manager.buffering = True
        manager.buffering_start_time = 1_000.0
        manager.buffering_timeout = 15
        manager.current_stream_id = 1
        manager.buffering_timeout_error_stream_id = (
            StreamManager._NO_BUFFERING_TIMEOUT_ERROR
        )
        for name in (
            "_update_buffering_state",
            "_buffering_timeout_failover",
            "_buffering_timeout_no_stream",
        ):
            setattr(manager, name, getattr(StreamManager, name).__get__(manager))
        manager._try_next_stream = MagicMock(return_value=False)
        return manager

    def test_failover_retries_are_spaced_once_past_the_timeout(self):
        # A single-stream channel has no alternate. Evaluation runs several
        # times a second, and each attempt reads the alternates from the
        # database, so attempts have to be spaced.
        manager = self._manager()
        clock = [2_000.0]
        inline_spawn = lambda fn, *a, **k: fn(*a, **k)  # noqa: E731
        with patch(
            "apps.proxy.live_proxy.input.manager.time"
        ) as mock_time, patch(
            "apps.proxy.live_proxy.input.manager.gevent.spawn",
            side_effect=inline_spawn,
        ), patch("apps.proxy.live_proxy.input.manager.log_system_event"):
            mock_time.time.side_effect = lambda: clock[0]
            for _ in range(80):
                manager._update_buffering_state(True, failover_async=True)
                clock[0] += 0.125
        # Ten seconds of evaluations, one attempt a second.
        self.assertGreaterEqual(manager._try_next_stream.call_count, 9)
        self.assertLessEqual(manager._try_next_stream.call_count, 11)
        self.assertTrue(manager.buffering)

    def test_a_pending_failover_blocks_another_spawn(self):
        manager = self._manager()
        clock = [2_000.0]
        with patch(
            "apps.proxy.live_proxy.input.manager.time"
        ) as mock_time, patch(
            "apps.proxy.live_proxy.input.manager.gevent.spawn"
        ) as spawn, patch("apps.proxy.live_proxy.input.manager.log_system_event"):
            mock_time.time.side_effect = lambda: clock[0]
            for _ in range(3):
                manager._update_buffering_state(True, failover_async=True)
                clock[0] += 5.0
        spawn.assert_called_once()


class IngestEvaluateCapTests(SimpleTestCase):
    def test_sample_driven_evaluation_is_capped_but_a_finished_burst_is_not(self):
        manager = make_manager()
        manager._evaluate_ingest_lag = MagicMock()
        tracker = manager.ingest_lag
        settle, media = arm_with_burst(tracker)
        feed_realtime(tracker, settle + 0.1, media, duration=3.0)
        self.assertTrue(tracker.has_rate)
        base = 5_000.0
        manager._evaluate_after_sample(tracker, base)
        manager._evaluate_after_sample(tracker, base + 0.1)
        manager._evaluate_after_sample(tracker, base + 0.2)
        self.assertEqual(manager._evaluate_ingest_lag.call_count, 1)
        manager._evaluate_after_sample(
            tracker, base + manager._INGEST_EVAL_MIN_SECONDS
        )
        self.assertEqual(manager._evaluate_ingest_lag.call_count, 2)
        manager._evaluate_after_sample(tracker, base + 0.26, force=True)
        self.assertEqual(manager._evaluate_ingest_lag.call_count, 3)

    def test_sample_driven_evaluation_waits_for_a_rate_unless_forced(self):
        manager = make_manager()
        manager._evaluate_ingest_lag = MagicMock()
        tracker = manager.ingest_lag
        self.assertFalse(tracker.has_rate)
        manager._evaluate_after_sample(tracker, 1.0)
        manager._evaluate_ingest_lag.assert_not_called()
        manager._evaluate_after_sample(tracker, 1.0, force=True)
        manager._evaluate_ingest_lag.assert_called_once()

    def test_reset_reopens_the_evaluate_cap(self):
        manager = make_manager()
        manager._ingest_last_eval_wall = 99.0
        manager._reset_ingest_lag(publish=False)
        self.assertIsNone(manager._ingest_last_eval_wall)


class StreamBufferHookTests(SimpleTestCase):
    def _buffer(self):
        with patch("apps.proxy.live_proxy.input.buffer.ConfigHelper") as cfg:
            cfg.redis_chunk_ttl.return_value = 60
            cfg.get.return_value = 188 * 5644
            return StreamBuffer(channel_id="hook", redis_client=None)

    PACKET = b"\x47" + b"\x00" * 187

    def test_hook_gets_the_complete_packets_and_the_arrival_wall(self):
        buf = self._buffer()
        buf.on_packets_received = MagicMock()
        before = time_now()
        buf.add_chunk(self.PACKET + self.PACKET[:50])
        hook = buf.on_packets_received
        hook.assert_called_once()
        self.assertEqual(hook.call_args.args[0], self.PACKET)
        self.assertGreaterEqual(hook.call_args.kwargs["wall"], before)

    def test_a_failing_hook_warns_once_and_never_stalls_ingest(self):
        buf = self._buffer()
        hook = MagicMock(side_effect=RuntimeError("boom"))
        buf.on_packets_received = hook
        with patch("apps.proxy.live_proxy.input.buffer.logger") as log:
            self.assertTrue(buf.add_chunk(self.PACKET))
            self.assertTrue(buf.add_chunk(self.PACKET))
            self.assertTrue(buf.add_chunk(self.PACKET))
        self.assertEqual(log.warning.call_count, 1)
        self.assertEqual(hook.call_count, 1)
        self.assertIsNone(buf.on_packets_received)


def time_now():
    import time

    return time.time()


class CushionRemainingParseTests(SimpleTestCase):
    def test_parses_numbers_including_a_real_zero(self):
        parse = ChannelStatus._parse_cushion_remaining
        key = "cushion_remaining"
        self.assertEqual(parse({key: "2.5"}), 2.5)
        self.assertEqual(parse({key: "0.0"}), 0.0)
        self.assertEqual(parse({key: "0"}), 0.0)

    def test_missing_blank_or_garbage_is_none(self):
        parse = ChannelStatus._parse_cushion_remaining
        key = "cushion_remaining"
        self.assertIsNone(parse({}))
        self.assertIsNone(parse({key: ""}))
        self.assertIsNone(parse({key: "abc"}))
        self.assertIsNone(parse({key: None}))


class IngestReplayTests(SimpleTestCase):
    """Whole provider timelines through the real manager decision path."""

    def test_healthy_bursty_providers_never_report_buffering(self):
        cases = {
            "6s burst, 1s jitter": bursty_timeline(lambda t: 1.0, seed=3),
            "6.2s burst, small jitter": bursty_timeline(
                lambda t: 1.0, period=6.2, jitter=0.3, seed=3
            ),
            "5s burst": bursty_timeline(
                lambda t: 1.0, period=5.0, jitter=0.5, seed=3
            ),
            # The gap here is longer than the fixed stall floor, so only a
            # provider-relative stall threshold keeps it quiet.
            "12s burst, 2s jitter": bursty_timeline(
                lambda t: 1.0, period=12.0, jitter=2.0, seed=6
            ),
            "1% over realtime": bursty_timeline(lambda t: 1.01, seed=11),
        }
        for name, timeline in cases.items():
            with self.subTest(name):
                self.assertEqual(trips(replay(timeline)), [])

    def test_a_real_stall_trips_once_and_does_not_retrip_after_recovery(self):
        for name, period, jitter in (
            ("6s burst", 6.0, 1.0),
            ("6.2s burst", 6.2, 0.3),
        ):
            with self.subTest(name):
                timeline = bursty_timeline(
                    lambda t: 1.0,
                    stall=(120, 135),
                    period=period,
                    jitter=jitter,
                    seed=8,
                )
                events = replay(timeline)
                self.assertEqual(len(trips(events)), 1, events)
                self.assertGreaterEqual(trips(events)[0], 120)
                self.assertLessEqual(trips(events)[0], 120 + 30)
                self.assertEqual(events[-1][0], "clear", events)

    def test_sustained_slowdowns_are_detected(self):
        # Cushion trip is a full empty New Client Buffer, plus the confirm
        # hold. Time to empty at rate R is behind / (1-R). Allow slack.
        for rate in (0.95, 0.9, 0.8, 0.5):
            with self.subTest(rate=rate):
                timeline = bursty_timeline(
                    rate_between(1.0, rate, 120, 360), seed=7
                )
                found = [t for t in trips(replay(timeline)) if t >= 120]
                self.assertTrue(found, f"no trip at {rate}x")
                expect_by = (
                    120
                    + TRIP_SECONDS / max(0.01, 1.0 - rate)
                    + TRIP_CONFIRM_SECONDS
                    + 30.0
                )
                self.assertLessEqual(found[0], expect_by)

    def test_a_slowdown_that_ends_clears_without_retripping(self):
        timeline = bursty_timeline(rate_between(1.0, 0.5, 120, 180), seed=7)
        events = replay(timeline)
        self.assertEqual(len(trips(events)), 1, events)
        self.assertEqual(events[-1][0], "clear", events)
