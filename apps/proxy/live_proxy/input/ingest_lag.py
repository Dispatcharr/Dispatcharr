"""Ingest join cushion, delivery-rate badge, and client-cushion debt trips.

At bitstream start (channel init, reconnect, or failover) the provider usually
dumps a burst of media. That burst defines a join prebuffer cushion (saved as a
stream stat, not used for the live badge):

    prebuffer = (last_pts - first_pts) - (last_wall - first_wall)

The card's Current Speed is a recent media/wall ratio over a long window
(several provider dump/gap cycles). Display only: no asymmetric smoother, so a
healthy bursty feed that really delivers ~1x does not sit soft forever. Hard
buffering asks a different question: has ingest emptied the worst client's
runway and held it empty long enough to count?

New clients start ``new_client_behind_seconds`` behind the live PTS at the
moment the join arms (default 5). That PTS is the debt zero for the session:

    debt = max(0, wall_since_live - media_since_live - gap_credit)

``gap_credit`` forgives the current idle up to the provider's own stall
rhythm, so a healthy burst gap
does not spend the cushion. Soft under-delivery and real stalls grow debt.
Forward catch-up pays it down. A hard backward PTS jump, stream switch, or
reconnect wipes the anchor and starts again.

Buffering starts when debt has kept the budget at empty (full New Client
Buffer spent, floored so a 0-second behind setting still trips on a real
stall) for a short confirm hold. Brief empty blips are ignored. It clears
once debt has stayed at or under a quarter of that trip line for one
second, or after a stall that realtime delivery cannot pay down, once
delivery has held at realtime for five seconds. Buffering Timeout still
owns failover while buffering is latched.

Mid-burst single samples (first 8KB after a gap) do not invent speed spikes.
Large forward jumps are join/catch-up. A later burst that is a real join dump
can replace a trickle prebuffer for the stream stat.

A gapless join does not arm when the open cluster hits five seconds. That
roll only keeps the rate window bounded. The join ends on a real quiet, or
once a two-second ratio sits near realtime (the provider has finished
catching up), or at a two-minute fallback if the ratio never settles.
"""

from bisect import bisect_left, bisect_right
from collections import deque

from ..ts_clock import wrap_delta_seconds

# No further socket data for this long means the burst is finished.
CLUSTER_GAP_SECONDS = 2.0
# Continuous feeds never go quiet. Roll the open cluster this often so the
# rate window stays bounded. A roll does not end the join.
CLUSTER_MAX_SPAN_SECONDS = 5.0
# Gapless join: do not arm before this much wall time, so one fast read
# cannot look like "already live".
JOIN_STABLE_MIN_SECONDS = 2.0
# Dense PTS samples for this long at join start. A large head-start catch-up
# can run many wall seconds above realtime before the join ratio settles, so
# this window is longer than the minimum arm delay. After it, until arm or
# the 120s fallback, the reader uses the join cadence (~50ms).
JOIN_DENSE_SAMPLE_SECONDS = 10.0
# Recent media/wall ratio used to decide a gapless join has caught up.
JOIN_STABLE_WINDOW_SECONDS = 2.0
# Inside this band the join is delivering about realtime, not still dumping
# a head-start buffer and not stalled.
JOIN_STABLE_SPEED_MIN = 0.95
JOIN_STABLE_SPEED_MAX = 1.10
# If a gapless join never settles (slow link, odd clock), arm anyway so
# debt can run. Long enough for a multi-tens-of-seconds catch-up.
JOIN_ARM_FALLBACK_SECONDS = 120.0
# Single-sample clusters wait this many gaps before settling (first 8KB guard).
SINGLE_SAMPLE_GAP_MULTIPLIER = 2
# Smaller backward steps are PTS reordering; larger ones are a timeline break.
RESET_BACKWARD_SECONDS = 1.0
# Badge speed is Δmedia/Δwall across samples inside this many wall seconds.
# Long enough for many dump/gap cycles (~6-10s) so one burst cannot own the
# ratio. Buffering decisions do not use this window.
SPEED_WINDOW_SECONDS = 120.0
# Published/badge ceiling so a wild PTS glitch cannot show a million-x.
MAX_REPORT_SPEED = 99.0
# Floor for the stall freeze (pull speed toward 0). The effective threshold also
# scales with the provider's own gaps, see ``IngestLagTracker._stall_after``.
SILENCE_STALL_SECONDS = 6.0
# Stall threshold is this multiple of the longest recent arrival gap...
STALL_GAP_MULTIPLIER = 1.5
# ...capped here so one real outage cannot make later stalls undetectable.
STALL_GAP_MAX_SECONDS = 15.0
# Only gaps at least this long count as the provider's rhythm (not chunk jitter).
MIN_TRACKED_GAP_SECONDS = 1.0
# Clear buffering once debt is at or under this fraction of the trip line.
CUSHION_CLEAR_FRACTION = 0.25
# Floor so behind=0 (start at live) still trips on a real stall.
MIN_CUSHION_TRIP_SECONDS = 0.5
# Budget must stay empty this long before buffering starts (ignores blips).
TRIP_CONFIRM_SECONDS = 1.0
# Leave buffering once debt has stayed under the clear line this long.
RATE_RECOVERY_SECONDS = 1.0
# Short window used for recovery's "recently healthy" check, not the badge.
CONFIRM_WINDOW_SECONDS = 5.0
# A later burst at least this far above realtime replaces a trickle/realtime
# first cluster that never measured the real join dump. Smaller wobble does
# not move the anchor.
ADOPT_CUSHION_SECONDS = 4.0
# Need at least this many samples in the window before rate can trip.
MIN_RATE_SAMPLES = 2


def _sample_wall(sample):
    """Bisect key: samples are (wall, media) and wall never decreases."""
    return sample[0]


class IngestLagTracker:
    """Join prebuffer plus recent-window ingest delivery rate for one channel."""

    __slots__ = (
        "_open",
        "_open_samples",
        "_clock_kind",
        "_pid",
        "_first_wall",
        "_first_media",
        "_settled_media",
        "_prebuffer",
        "_armed",
        "_armed_wall",
        "_budget_locked",
        "_adopt_floor",
        "_join_prebuffer_pending",
        "_rate_wall",
        "_rate_media",
        "_samples",
        "_last_advance_wall",
        "_gaps",
        "_longest_gap_seen",
        "_last_speed",
        "_debt_anchor_wall",
        "_debt_anchor_media",
        "_debt",
        "_trip_since",
        "_rate_ok_since",
        "_recovery_mode",
        "_clock_loose",
    )

    def __init__(self, adopt_floor=ADOPT_CUSHION_SECONDS):
        # [first_wall, last_wall, last_media, first_media] of the open cluster.
        # adopt_floor gates replacing a trickle join cushion with a later dump.
        self._open = None
        self._open_samples = 0
        self._clock_kind = None
        self._pid = None
        self._first_wall = None
        self._first_media = None
        self._settled_media = None
        self._prebuffer = None
        self._armed = False
        self._armed_wall = None
        self._budget_locked = False
        self._adopt_floor = float(adopt_floor)
        self._join_prebuffer_pending = False
        self._rate_wall = None
        self._rate_media = None
        # (wall, media) samples: those inside SPEED_WINDOW_SECONDS plus the
        # newest one at or before the window start (the speed origin).
        self._samples = deque()
        # Wall of the last sample that advanced media, and recent
        # (wall, gap) arrival gaps. These set the provider-relative stall time.
        self._last_advance_wall = None
        self._gaps = deque()
        # Sticky longest gap so a long stall cannot age the rhythm out of the
        # window and raise the freeze threshold mid-outage.
        self._longest_gap_seen = 0.0
        # Last computed window speed so the badge does not blank when empty.
        self._last_speed = None
        # Client-cushion debt anchor. Seated on the live PTS when the join arms.
        self._debt_anchor_wall = None
        self._debt_anchor_media = None
        self._debt = 0.0
        self._trip_since = None
        self._rate_ok_since = None
        self._recovery_mode = None
        # After a hard PTS jump, the next batch may carry a new PID. Until a
        # sample lands on the locked clock, a different PID in the batch may
        # take over.
        self._clock_loose = False

    @property
    def locked_pid(self):
        return self._pid

    @property
    def locked_kind(self):
        return self._clock_kind

    @property
    def clock_loose(self):
        """True after a PTS discontinuity until the locked clock is seen again."""
        return self._clock_loose

    @property
    def has_debt_anchor(self):
        """True once the live PTS has been seated as the cushion-debt anchor."""
        return self._debt_anchor_wall is not None

    @property
    def is_armed(self):
        """True once the initial burst has defined the join prebuffer."""
        return self._armed

    @property
    def prebuffer(self):
        """Seconds of media-above-realtime from the join burst, or None."""
        return self._prebuffer

    @property
    def join_prebuffer_pending(self):
        """True when join prebuffer changed and has not been persisted yet."""
        return self._join_prebuffer_pending

    def mark_join_prebuffer_persisted(self):
        self._join_prebuffer_pending = False

    @property
    def quiet_deadline(self):
        """Wall time at which the open cluster counts as finished, or None."""
        if self._open is None:
            return None
        gap = CLUSTER_GAP_SECONDS
        if self._open_samples < 2:
            gap = SINGLE_SAMPLE_GAP_MULTIPLIER * CLUSTER_GAP_SECONDS
        return self._open[1] + gap

    @property
    def has_rate(self):
        """True once at least two rate samples exist (badge/evaluate may run)."""
        return len(self._samples) >= 2 or self._last_speed is not None

    def reset(self):
        """Forget everything and unlock the clock PID.

        Used for a stream switch or reconnect, and when a post-discontinuity
        batch carries a different clock PID that has to be bound from scratch.
        A plain hard PTS jump on the same PID goes through ``_reset_timeline``.
        """
        self._open = None
        self._open_samples = 0
        self._clock_kind = None
        self._pid = None
        self._first_wall = None
        self._first_media = None
        self._settled_media = None
        self._prebuffer = None
        self._armed = False
        self._armed_wall = None
        self._budget_locked = False
        self._join_prebuffer_pending = False
        self._clock_loose = False
        self._wipe_rate()

    def _wipe_rate(self):
        """Drop delivery-rate memory. Join cluster state stays put."""
        self._rate_wall = None
        self._rate_media = None
        self._samples.clear()
        self._last_advance_wall = None
        self._gaps.clear()
        self._longest_gap_seen = 0.0
        self._last_speed = None
        self._clear_debt_anchor()
        self._rate_ok_since = None
        self._recovery_mode = None

    def observe(self, wall, media, clock_kind, pid):
        """Record media clock for packets that just arrived from the socket.

        Returns True when this arrival finalized the previous cluster.
        """
        if media is None or clock_kind is None:
            return False
        if self._pid is None:
            self._pid = pid
            self._clock_kind = clock_kind
            self._clock_loose = False
        elif pid != self._pid or clock_kind != self._clock_kind:
            return False
        else:
            self._clock_loose = False

        newest = self._open[2] if self._open is not None else self._settled_media
        if newest is not None:
            step = wrap_delta_seconds(media, newest)
            # Only a hard backward jump is a new bitstream. Large forward steps
            # are normal join/catch-up dumps and must not wipe the budget.
            if step < -RESET_BACKWARD_SECONDS:
                self._reset_timeline(wall, media)
                return False
            if step < 0:
                return False

        if self._open is None:
            self._open = [wall, wall, media, media]
            self._open_samples = 1
            if self._first_media is None:
                self._first_wall = wall
                self._first_media = media
            # First point of a burst seeds the rate window immediately.
            self._record_sample(wall, media)
            return False

        gap = wall - self._open[1]
        span = wall - self._open[0]
        if gap >= CLUSTER_GAP_SECONDS:
            self._close_open()
            self._open = [wall, wall, media, media]
            self._open_samples = 1
            # Keep calendar continuity: record the new media at this wall so the
            # idle stretch already held via gap polls is not discarded.
            self._record_sample(wall, media)
            return True

        self._open[1] = wall
        self._open_samples += 1
        if wrap_delta_seconds(media, self._open[2]) > 0:
            self._open[2] = media
        # Emit rate from the second sample of a burst, including the join dump.
        if self._open_samples >= 2:
            self._record_sample(wall, media)
        # Live or finished catch-up: arm before the span cap. Still-fast
        # catch-up stays unarmed so debt does not start mid-download.
        if not self._armed and self._try_arm_join(wall):
            return True
        if span >= CLUSTER_MAX_SPAN_SECONDS:
            if self._armed:
                self._close_open()
                self._open = [wall, wall, media, media]
                self._open_samples = 1
            else:
                # Keep measuring the join. The next samples start a new
                # open cluster so one endless read cannot pin the window.
                self._settled_media = self._open[2]
                self._open = [wall, wall, media, media]
                self._open_samples = 1
            return True
        return False

    def join_wall_elapsed(self, wall):
        """Seconds since the first join sample, or None before any sample."""
        if self._first_wall is None or wall is None:
            return None
        return max(0.0, float(wall) - self._first_wall)

    def _recent_join_ratio(self):
        """Raw Δmedia/Δwall over the recent join window, or None.

        Ignores the badge window's idle stretch toward 1.0x. A catch-up dump
        has to stay visibly fast until it is actually over.
        """
        samples = self._samples
        count = len(samples)
        if count < 2:
            return None
        last_wall, last_media = samples[count - 1]
        cutoff = last_wall - JOIN_STABLE_WINDOW_SECONDS
        first_index = bisect_right(samples, cutoff, hi=count, key=_sample_wall) - 1
        if first_index < 0:
            first_index = 0
        first_wall, first_media = samples[first_index]
        wall_delta = last_wall - first_wall
        if wall_delta < 1.0:
            return None
        media_delta = wrap_delta_seconds(last_media, first_media)
        if media_delta < 0:
            return None
        return media_delta / wall_delta

    def _try_arm_join(self, wall):
        """Arm a gapless join once it looks live, or at the fallback cutoff.

        Quiet joins still arm through ``_close_open`` (gap or settle). This
        path is for a socket that never goes quiet: wait out the head-start
        download, then arm when the recent ratio is near realtime.
        """
        if self._armed or self._open is None or self._first_wall is None:
            return False
        elapsed = wall - self._first_wall
        if elapsed >= JOIN_ARM_FALLBACK_SECONDS:
            self._close_open()
            return self._armed
        if elapsed < JOIN_STABLE_MIN_SECONDS:
            return False
        ratio = self._recent_join_ratio()
        if ratio is None:
            return False
        if ratio < JOIN_STABLE_SPEED_MIN or ratio > JOIN_STABLE_SPEED_MAX:
            return False
        self._close_open()
        return self._armed

    def settle(self, now):
        """Close the open cluster once it has been quiet long enough."""
        deadline = self.quiet_deadline
        if deadline is None or now < deadline:
            return False
        self._close_open()
        return True

    def _stall_after(self):
        """Idle seconds after which silence counts as a stall.

        Relative to this provider's own rhythm: a feed that normally pauses
        ~6s between bursts needs longer than that before it is called stalled.
        Before any gap is known, only extreme silence counts so the first
        real inter-burst pause is not frozen into the speed window. While
        gaps remain in the speed window, the longest of those sets the rhythm;
        when the window is empty during a stall, the last seen longest gap
        still applies so mid-outage silence does not shrink the threshold.
        """
        longest = max(
            self._longest_gap_seen,
            max((gap for _wall, gap in self._gaps), default=0.0),
        )
        if longest <= 0.0:
            return STALL_GAP_MAX_SECONDS
        return max(
            SILENCE_STALL_SECONDS,
            min(STALL_GAP_MAX_SECONDS, STALL_GAP_MULTIPLIER * longest),
        )

    def project_silence(self, now):
        """Freeze media only after a real stall, not normal inter-burst quiet.

        Short empty polls leave the raw window alone so smoothed speed holds.
        After ``_stall_after()`` seconds with no media advance, wall keeps moving
        with the last media clock so speed falls toward 0 for true stalls.
        """
        if self._rate_wall is None or self._rate_media is None:
            return
        if now - self._rate_wall < self._stall_after():
            return
        # Do not invent samples while an untrusted single packet is open.
        if self._open is not None and self._open_samples < 2:
            return
        self._record_sample(now, self._rate_media)

    def _window_count(self):
        """How many leading samples count for Δmedia/Δwall and debt.

        Skips an incomplete open burst. The first packets of a realtime burst
        only carry a slice of the media owed for the preceding gap. Ending the
        window there reads a healthy feed as ~0.25x and was what the old hidden
        0.98 floor was papering over. Wait until this burst has caught up to
        that gap (join/catch-up dumps pass immediately) before using its
        samples.

        Media gained is measured from the previous sample (not open-first to
        open-last): the first packet of the burst already carries part of the
        owed media, so ignoring it kept healthy bursts "incomplete" forever.

        Returns a prefix length of ``self._samples`` (bisect, not a list copy:
        this runs several times per evaluate over up to ~1000 samples).
        """
        samples = self._samples
        total = len(samples)
        if self._open is None or total < 2:
            return total
        open_start = self._open[0]
        pre = bisect_left(samples, open_start, key=_sample_wall)
        if pre < 2:
            return total
        prev_wall, prev_media = samples[pre - 1]
        # Open layout: [first_wall, last_wall, last_media, first_media].
        gained = wrap_delta_seconds(self._open[2], prev_media)
        if gained < 0:
            return pre
        gap_wall = open_start - prev_wall
        if gap_wall > 0 and gained < gap_wall:
            return pre
        return total

    def _window_speed(self, now, window_seconds):
        """Δmedia/Δwall over ``window_seconds``, with catch-up-only trailing idle.

        Post-join only: the initial dump is not delivery rate. Idle extends wall
        on the same sample pair and stops at 1.0x. It does not drop the older
        samples (that re-pick was reading the slow tail as if the fast prefix
        had aged out). Short spans without enough length stay undiluted.
        """
        if now is not None:
            self._prune_samples(now)
        samples = self._samples
        end = self._window_count()
        start = 0
        if self._armed_wall is not None:
            start = bisect_left(samples, self._armed_wall, hi=end, key=_sample_wall)
        if end - start < 2:
            return None
        last_wall, last_media = samples[end - 1]
        cutoff = last_wall - float(window_seconds)
        # Origin is the newest sample at or before the window start, else the
        # oldest usable one.
        first_index = (
            bisect_right(samples, cutoff, lo=start, hi=end, key=_sample_wall) - 1
        )
        first_wall, first_media = samples[max(first_index, start)]
        sample_span = last_wall - first_wall
        if sample_span <= 0:
            return None
        media_delta = wrap_delta_seconds(last_media, first_media)
        if media_delta < 0:
            return None
        end_wall = last_wall
        min_span_for_idle = min(CONFIRM_WINDOW_SECONDS, float(window_seconds) * 0.5)
        if (
            now is not None
            and now > last_wall
            and sample_span >= min_span_for_idle
            and media_delta > sample_span
        ):
            # Same media pair. Extra wall stops once the ratio would hit 1.0x.
            end_wall = min(now, first_wall + media_delta)
        wall_delta = end_wall - first_wall
        # Short confirm needs a real span so one packet cannot invent a rate.
        if (
            window_seconds < SPEED_WINDOW_SECONDS
            and wall_delta < min(1.0, window_seconds * 0.4)
        ):
            return None
        return min(MAX_REPORT_SPEED, max(0.0, media_delta / wall_delta))

    def recent_speed(self, now=None):
        """Long-window Δmedia/Δwall for the Current Speed badge."""
        speed = self._window_speed(now, SPEED_WINDOW_SECONDS)
        if speed is not None:
            self._last_speed = speed
            return speed
        return self._last_speed

    def confirm_speed(self, now=None):
        """Short-window speed for recovery's recently-healthy check."""
        return self._window_speed(now, CONFIRM_WINDOW_SECONDS)

    def rate_ready(self, now=None):
        """True once the join is armed and a rate cursor exists.

        Debt needs the live PTS and wall time, not a two-sample speed window.
        A quiet single-sample arm is enough to start the budget.
        """
        if not self._armed or self._armed_wall is None:
            return False
        if now is None:
            now = self._rate_wall
        if now is None or self._rate_media is None:
            return False
        self._prune_samples(now)
        return True

    def _clear_debt_anchor(self):
        self._debt_anchor_wall = None
        self._debt_anchor_media = None
        self._debt = 0.0
        self._trip_since = None
        self._rate_ok_since = None
        self._recovery_mode = None

    @staticmethod
    def cushion_trip_seconds(behind_seconds):
        """Debt seconds that start a buffering event for ``behind_seconds``."""
        return max(MIN_CUSHION_TRIP_SECONDS, float(behind_seconds))

    @staticmethod
    def cushion_clear_seconds(trip_seconds):
        """Debt seconds at or under which buffering may clear."""
        return max(0.0, float(trip_seconds) * CUSHION_CLEAR_FRACTION)

    def ensure_debt_anchor(self):
        """Seat debt on the live PTS if the join is armed and no anchor yet."""
        if self._debt_anchor_wall is not None:
            return True
        return self._arm_debt_anchor()

    def _arm_debt_anchor(self):
        """Seat debt on the live PTS, the sample where the join armed.

        New clients start ``new_client_behind`` behind that PTS, so the
        budget is wall-ahead-of-media since then. Called when the join arms
        so the budget badge and trip clock start on that same sample.
        """
        if self._armed_wall is None:
            return False
        if self._rate_wall is None or self._rate_media is None:
            return False
        target = self._armed_wall
        anchor_wall = self._rate_wall
        anchor_media = self._rate_media
        newest_before = bisect_right(self._samples, target, key=_sample_wall) - 1
        if newest_before >= 0:
            anchor_wall, anchor_media = self._samples[newest_before]
        self._debt_anchor_wall = anchor_wall
        self._debt_anchor_media = anchor_media
        self._debt = 0.0
        self._trip_since = None
        self._rate_ok_since = None
        self._recovery_mode = None
        return True

    def cushion_debt(self, now=None):
        """Seconds of client cushion eaten since the debt anchor.

        Forgives the current inter-burst idle up to ``_stall_after()`` so a
        healthy provider gap does not look like lost runway. Soft under-delivery
        and stalls past that rhythm grow debt. Catch-up media pays it down.

        While an open burst is still filling the preceding gap, debt is scored
        against the last complete sample (same exclusion as the speed windows)
        so the first packets of a dump cannot spend the cushion.

        ``project_silence`` appends frozen media samples so the speed badge
        falls during a stall. Those samples must not be the debt idle cursor:
        ``idle = now - silence_wall`` is ~0, which zeroes gap credit and drops
        the budget to empty on the first stall-threshold tick of a healthy gap.
        Clamp the effective wall back to the last real media advance when the
        sample tail is silence-only.
        """
        if self._debt_anchor_wall is None or self._debt_anchor_media is None:
            return 0.0
        if now is None:
            now = self._rate_wall
        if now is None:
            return self._debt
        usable = self._window_count()
        if usable:
            eff_wall, eff_media = self._samples[usable - 1]
        elif self._rate_media is not None and self._rate_wall is not None:
            eff_wall, eff_media = self._rate_wall, self._rate_media
        else:
            return self._debt
        # Silence projections share media with the last advance but sit later
        # on the wall. Keep media; rewind wall so credit still sees the gap.
        if (
            self._last_advance_wall is not None
            and eff_wall > self._last_advance_wall
        ):
            eff_wall = self._last_advance_wall
        wall_elapsed = max(0.0, now - self._debt_anchor_wall)
        media_elapsed = wrap_delta_seconds(eff_media, self._debt_anchor_media)
        if media_elapsed < 0:
            media_elapsed = 0.0
        idle = max(0.0, now - eff_wall)
        credit = min(idle, self._stall_after())
        self._debt = max(0.0, wall_elapsed - media_elapsed - credit)
        return self._debt

    def is_slow(self, trip_seconds, now=None):
        """True when the client cushion has stayed empty long enough to count.

        ``trip_seconds`` is ``cushion_trip_seconds(new_client_behind)`` (full
        New Client Buffer measured from the live PTS). Speed is not consulted.
        Returns None until the join is armed. Debt must stay at or above the
        trip line for ``TRIP_CONFIRM_SECONDS`` before this returns True so a
        brief empty blip does not fire buffering.
        """
        if not self.rate_ready(now=now):
            # Discontinuity / reset already wipe the anchor. Do not clear it
            # here: a brief unreadiness would forget the live PTS.
            return None
        if now is None:
            now = self._rate_wall
        if now is None or self._rate_media is None:
            return None
        if not self.ensure_debt_anchor():
            return None
        debt = self.cushion_debt(now=now)
        if debt < float(trip_seconds):
            self._trip_since = None
            return False
        self._rate_ok_since = None
        if self._trip_since is None:
            self._trip_since = now
            return False
        if (now - self._trip_since) < TRIP_CONFIRM_SECONDS:
            return False
        return True

    def empty_for_seconds(self, now=None):
        """Seconds the cushion has been at or past the trip line, or None.

        Set while debt is empty; used for the buffering event's ``empty_for``.
        At trip this is at least ``TRIP_CONFIRM_SECONDS``, and a bit more when
        the next evaluate lands after the confirm hold.
        """
        if self._trip_since is None:
            return None
        if now is None:
            now = self._rate_wall
        if now is None:
            return None
        return max(0.0, now - self._trip_since)

    def is_recovered(self, trip_seconds, now=None):
        """True when the cushion-risk episode has ended.

        Two clear paths:

        * Debt at or under the clear line for ``RATE_RECOVERY_SECONDS``
          (paid-down catch-up).
        * Still deep underwater, but recent delivery has held at realtime
          (``confirm_speed`` >= 1.0) for a full ``CONFIRM_WINDOW_SECONDS``.
          After a real stall absolute debt cannot be paid at 1.0x, so this
          re-seats the cushion once the feed is stably back. A one-burst
          blip on the short recovery timer is not enough (that was the flap).

        On clear, re-anchor so the next shortfall starts from a full client
        cushion instead of keeping the channel latched until timeout.
        """
        if now is None:
            return None
        if self._debt_anchor_wall is None:
            return None
        clear_at = self.cushion_clear_seconds(trip_seconds)
        debt = self.cushion_debt(now=now)
        if debt <= clear_at:
            need = RATE_RECOVERY_SECONDS
            mode = "shallow"
        else:
            # Short window: a long badge average would stay soft after a stall
            # even while the feed is already back to realtime.
            raw = self.confirm_speed(now=now)
            if raw is None or round(float(raw), 3) < 1.0:
                self._rate_ok_since = None
                self._recovery_mode = None
                return False
            need = CONFIRM_WINDOW_SECONDS
            mode = "deep"
        if mode != self._recovery_mode:
            self._recovery_mode = mode
            self._rate_ok_since = None
        if self._rate_ok_since is None:
            self._rate_ok_since = now
            return False
        if (now - self._rate_ok_since) < need:
            return False
        # Re-seat at now: the finished episode should not keep the next one
        # starting already half-spent.
        self._debt_anchor_wall = self._rate_wall
        self._debt_anchor_media = self._rate_media
        self._debt = 0.0
        self._trip_since = None
        self._rate_ok_since = None
        self._recovery_mode = None
        return True

    def _record_sample(self, wall, media):
        if self._rate_wall is not None and wall < self._rate_wall:
            return
        if self._rate_media is not None:
            media_delta = wrap_delta_seconds(media, self._rate_media)
            if media_delta < -RESET_BACKWARD_SECONDS:
                self._wipe_rate()
            elif media_delta < 0:
                # Reorder: ignore this point for rate.
                return
        # Frozen stall samples do not advance media, so they are not arrivals.
        advanced = self._rate_media is None or media > self._rate_media
        if advanced:
            if self._last_advance_wall is not None:
                gap = wall - self._last_advance_wall
                if gap >= MIN_TRACKED_GAP_SECONDS:
                    self._gaps.append((wall, gap))
                    if gap > self._longest_gap_seen:
                        self._longest_gap_seen = gap
            self._last_advance_wall = wall
        self._samples.append((wall, media))
        self._rate_wall = wall
        self._rate_media = media
        self._prune_samples(wall)

    def _prune_samples(self, now):
        cutoff = now - SPEED_WINDOW_SECONDS
        # Keep the newest sample at or before the window start. It is the
        # origin for the speed ratio; dropping it would start the window on a
        # packet that already carries part of a burst and read the feed too fast.
        while len(self._samples) > 1 and self._samples[1][0] <= cutoff:
            self._samples.popleft()
        while self._gaps and self._gaps[0][0] < cutoff:
            self._gaps.popleft()
        if self._gaps:
            self._longest_gap_seen = max(gap for _wall, gap in self._gaps)

    def _reset_timeline(self, wall, media):
        """PTS discontinuity (large backward jump): new bitstream."""
        self._open = [wall, wall, media, media]
        self._open_samples = 1
        self._first_wall = wall
        self._first_media = media
        self._settled_media = None
        self._prebuffer = None
        self._armed = False
        self._armed_wall = None
        self._budget_locked = False
        self._join_prebuffer_pending = False
        self._wipe_rate()
        self._record_sample(wall, media)
        self._clock_loose = True

    def _cluster_cushion(self, first_wall, last_wall, first_media, last_media):
        wall_span = max(0.0, last_wall - first_wall)
        media_span = max(0.0, wrap_delta_seconds(last_media, first_media))
        return max(0.0, media_span - wall_span)

    def _adopt_budget(self, cushion, last_wall, last_media):
        """Replace a trickle join cushion when this burst is a real dump."""
        if self._budget_locked:
            return
        if cushion < self._adopt_floor:
            return
        if cushion <= (self._prebuffer or 0):
            return
        self._prebuffer = cushion
        self._budget_locked = True
        self._join_prebuffer_pending = True

    def _close_open(self):
        first_wall, last_wall, last_media, first_media = self._open
        self._open = None
        self._open_samples = 0

        if not self._armed:
            # Initial burst end: define join prebuffer and the post-burst rate origin.
            if self._first_media is None:
                self._first_wall = last_wall
                self._first_media = last_media
            wall_span = max(0.0, last_wall - self._first_wall)
            media_span = wrap_delta_seconds(last_media, self._first_media)
            self._prebuffer = max(0.0, media_span - wall_span)
            self._settled_media = last_media
            self._armed = True
            self._armed_wall = last_wall
            self._budget_locked = self._prebuffer >= self._adopt_floor
            self._join_prebuffer_pending = True
            # Keep catch-up samples already collected during the burst so the
            # badge does not go blank at arm. Advance the rate cursor.
            self._record_sample(last_wall, last_media)
            # Seat debt on this live PTS now so the budget badge and trip
            # clock do not wait for a later evaluate.
            self._arm_debt_anchor()
            return

        self._record_sample(last_wall, last_media)
        self._settled_media = last_media
        self._adopt_budget(
            self._cluster_cushion(first_wall, last_wall, first_media, last_media),
            last_wall,
            last_media,
        )
