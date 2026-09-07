"""batch_process_episodes must not wipe most of a series' episode relations
from a single short/incomplete provider response.

Real-world trigger: a slow upstream, a transient network hiccup, or a
provider mid-update can return a *valid but truncated* episode list for one
series (a season missing, most episodes absent) without ever producing an
HTTP error -- there is no status code or header that distinguishes "this
provider genuinely removed episodes" from "this fetch came back short". The
un-guarded stale-relation delete (`stale_qs.exclude(stream_id__in=episode_ids)
.delete()`) treated every case the same way: instant, ungraceful removal of
every relation missing from that one response. In practice this reproduces
as a real user watching a series mid-episode, a routine playlist refresh
happens, and the show goes from having a full season list to showing empty
in the client (TiviMate, Dispatcharr's own guide) -- with nothing having
actually changed upstream.
"""

from django.test import TestCase

from apps.m3u.models import M3UAccount
from apps.vod.models import Episode, M3UEpisodeRelation, M3USeriesRelation, Series
from apps.vod.tasks import batch_process_episodes


def _episode(stream_id, title, episode_num, season=1):
    return {
        'id': str(stream_id),
        'title': title,
        'episode_num': episode_num,
        'season': season,
        'container_extension': 'mp4',
        'info': {},
    }


class BatchProcessEpisodesStaleGuardTests(TestCase):
    def setUp(self):
        self.account = M3UAccount.objects.create(
            name='XC Episodes Stale Guard',
            server_url='http://example.com',
            username='user',
            password='pass',
            account_type=M3UAccount.Types.XC,
            is_active=True,
            custom_properties={'enable_vod': True},
        )
        self.series = Series.objects.create(name='Guarded Series', year=2000)
        self.series_relation = M3USeriesRelation.objects.create(
            m3u_account=self.account,
            series=self.series,
            external_series_id='8701',
        )

    def _seed_episodes(self, count):
        """Populates `count` existing episode relations via a normal, full
        batch_process_episodes call -- exercises the same code path the
        guard sits in, rather than constructing rows directly."""
        episodes_data = {'1': [_episode(100 + i, f'Episode {i}', i) for i in range(count)]}
        batch_process_episodes(
            self.account, self.series, episodes_data, series_relation=self.series_relation,
        )
        self.assertEqual(M3UEpisodeRelation.objects.filter(m3u_account=self.account).count(), count)

    def test_short_response_does_not_wipe_majority_of_existing_episodes(self):
        self._seed_episodes(10)

        # A response with only 1 of the original 10 episodes -- 90% would be
        # removed in one pass, well past the guard's threshold.
        short_response = {'1': [_episode(100, 'Episode 0', 0)]}
        batch_process_episodes(
            self.account, self.series, short_response, series_relation=self.series_relation,
        )

        self.assertEqual(
            M3UEpisodeRelation.objects.filter(m3u_account=self.account).count(), 10,
            'a response missing 90% of known episodes must not delete the other 9 -- '
            'looks like a truncated fetch, not a real removal',
        )
        # The one episode actually present in the short response is still
        # processed normally (updated in place), not ignored outright.
        self.assertTrue(Episode.objects.filter(series=self.series, name='Episode 0').exists())

    def test_small_legitimate_removal_still_applies(self):
        self._seed_episodes(10)

        # Removing 2 of 10 (20%) is well under the guard's 50% threshold --
        # a normal "a couple episodes were pulled from the catalog" case.
        response = {'1': [_episode(100 + i, f'Episode {i}', i) for i in range(8)]}
        batch_process_episodes(
            self.account, self.series, response, series_relation=self.series_relation,
        )

        self.assertEqual(M3UEpisodeRelation.objects.filter(m3u_account=self.account).count(), 8)

    def test_guard_does_not_block_cleanup_on_small_series(self):
        # Below EPISODE_STALE_DELETE_MIN_EXISTING (5) -- even a full removal
        # is a small absolute count, so the guard must not block it
        # indefinitely (a genuinely tiny/ended series would never clean up).
        self._seed_episodes(3)

        response = {'1': [_episode(999, 'Only Survivor', 99)]}
        batch_process_episodes(
            self.account, self.series, response, series_relation=self.series_relation,
        )

        remaining = list(M3UEpisodeRelation.objects.filter(m3u_account=self.account))
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0].stream_id, '999')

    def test_fully_empty_response_still_no_ops_without_deleting(self):
        # Existing, separate short-circuit (`if not episodes_data: return`) --
        # confirms the guard's presence doesn't change this already-safe case.
        self._seed_episodes(10)

        batch_process_episodes(
            self.account, self.series, {}, series_relation=self.series_relation,
        )

        self.assertEqual(M3UEpisodeRelation.objects.filter(m3u_account=self.account).count(), 10)

    # ── Boundary conditions ──────────────────────────────────────────────

    def test_exactly_fifty_percent_removal_is_not_guarded(self):
        # 5 of 10 removed is exactly EPISODE_STALE_DELETE_MAX_FRACTION (0.5) --
        # the guard uses a strict `>`, so exactly-half applies normally rather
        # than being ambiguously blocked.
        self._seed_episodes(10)

        response = {'1': [_episode(100 + i, f'Episode {i}', i) for i in range(5)]}
        batch_process_episodes(
            self.account, self.series, response, series_relation=self.series_relation,
        )

        self.assertEqual(M3UEpisodeRelation.objects.filter(m3u_account=self.account).count(), 5)

    def test_just_over_fifty_percent_removal_is_guarded(self):
        # 6 of 10 removed (60%) crosses the threshold -- one episode more
        # than the exactly-half case above, and the guard now applies.
        self._seed_episodes(10)

        response = {'1': [_episode(100 + i, f'Episode {i}', i) for i in range(4)]}
        batch_process_episodes(
            self.account, self.series, response, series_relation=self.series_relation,
        )

        self.assertEqual(M3UEpisodeRelation.objects.filter(m3u_account=self.account).count(), 10)

    def test_min_existing_boundary_at_threshold_is_guarded(self):
        # Exactly EPISODE_STALE_DELETE_MIN_EXISTING (5) existing relations,
        # losing all but one (80%) -- at the boundary, the guard still applies
        # (`>=`), unlike the 3-episode case below the threshold. The 5 old
        # relations are kept (deletion deferred) AND the response's own new
        # stream_id (999) is still created -- the guard only defers deletes,
        # never blocks a genuine create -- so 6 relations exist afterward.
        self._seed_episodes(5)

        response = {'1': [_episode(999, 'Only Survivor', 99)]}
        batch_process_episodes(
            self.account, self.series, response, series_relation=self.series_relation,
        )

        self.assertEqual(M3UEpisodeRelation.objects.filter(m3u_account=self.account).count(), 6)
        self.assertTrue(
            M3UEpisodeRelation.objects.filter(m3u_account=self.account, stream_id='999').exists()
        )

    def test_min_existing_boundary_just_below_threshold_is_not_guarded(self):
        # One fewer than the minimum (4) -- confirms the boundary sits exactly
        # where EPISODE_STALE_DELETE_MIN_EXISTING says it does, not off-by-one.
        self._seed_episodes(4)

        response = {'1': [_episode(999, 'Only Survivor', 99)]}
        batch_process_episodes(
            self.account, self.series, response, series_relation=self.series_relation,
        )

        remaining = list(M3UEpisodeRelation.objects.filter(m3u_account=self.account))
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0].stream_id, '999')

    # ── Realistic growth/shrink scenarios ───────────────────────────────

    def test_new_season_added_never_triggers_guard(self):
        # A real, common case: the show got a new season. Pure growth, zero
        # removals -- must never be affected by a delete-focused guard.
        self._seed_episodes(10)

        response = {
            '1': [_episode(100 + i, f'Episode {i}', i) for i in range(10)],
            '2': [_episode(200 + i, f'S2 Episode {i}', i) for i in range(10)],
        }
        batch_process_episodes(
            self.account, self.series, response, series_relation=self.series_relation,
        )

        self.assertEqual(M3UEpisodeRelation.objects.filter(m3u_account=self.account).count(), 20)

    def test_one_of_three_seasons_removed_is_a_legitimate_small_fraction(self):
        # Removing a whole season is real and intentional, but proportionally
        # small against a big enough series (10 of 30, ~33%) -- must still
        # apply immediately, not be treated as a suspicious short fetch.
        episodes_data = {
            '1': [_episode(100 + i, f'S1E{i}', i) for i in range(10)],
            '2': [_episode(200 + i, f'S2E{i}', i) for i in range(10)],
            '3': [_episode(300 + i, f'S3E{i}', i) for i in range(10)],
        }
        batch_process_episodes(
            self.account, self.series, episodes_data, series_relation=self.series_relation,
        )
        self.assertEqual(M3UEpisodeRelation.objects.filter(m3u_account=self.account).count(), 30)

        # Season 2 pulled entirely.
        response = {
            '1': [_episode(100 + i, f'S1E{i}', i) for i in range(10)],
            '3': [_episode(300 + i, f'S3E{i}', i) for i in range(10)],
        }
        batch_process_episodes(
            self.account, self.series, response, series_relation=self.series_relation,
        )

        # Check the relation table, not Episode: batch_process_episodes only ever
        # deletes M3UEpisodeRelation rows -- the shared Episode metadata rows persist
        # even after their relation to this account is gone (by design; another
        # provider offering the same series keeps its own relations to the same rows).
        remaining_seasons = set(
            M3UEpisodeRelation.objects.filter(m3u_account=self.account)
            .values_list('episode__season_number', flat=True)
        )
        self.assertEqual(remaining_seasons, {1, 3})
        self.assertEqual(M3UEpisodeRelation.objects.filter(m3u_account=self.account).count(), 20)

    # ── Repeated calls / eventual consistency ───────────────────────────

    def test_repeated_short_responses_never_delete(self):
        # The guard must keep blocking on every call, not just the first --
        # a flaky upstream that stays flaky for several consecutive on-demand
        # refreshes (each one a real, separate request in production) must
        # not eventually wear the guard down.
        self._seed_episodes(10)

        short_response = {'1': [_episode(100, 'Episode 0', 0)]}
        for _ in range(5):
            batch_process_episodes(
                self.account, self.series, short_response, series_relation=self.series_relation,
            )

        self.assertEqual(M3UEpisodeRelation.objects.filter(m3u_account=self.account).count(), 10)

    def test_complete_response_after_blocked_short_ones_reconciles_cleanly(self):
        # A later, genuinely complete fetch must still be able to apply a
        # real removal (and must not have accumulated duplicates or corrupted
        # state from the earlier blocked attempts).
        self._seed_episodes(10)

        short_response = {'1': [_episode(100, 'Episode 0', 0)]}
        batch_process_episodes(
            self.account, self.series, short_response, series_relation=self.series_relation,
        )
        batch_process_episodes(
            self.account, self.series, short_response, series_relation=self.series_relation,
        )
        self.assertEqual(M3UEpisodeRelation.objects.filter(m3u_account=self.account).count(), 10)

        # Provider genuinely trimmed to 6 episodes -- 4 removed (40%), under
        # threshold, should apply cleanly now that a complete fetch arrived.
        complete_response = {'1': [_episode(100 + i, f'Episode {i}', i) for i in range(6)]}
        batch_process_episodes(
            self.account, self.series, complete_response, series_relation=self.series_relation,
        )

        relations = list(M3UEpisodeRelation.objects.filter(m3u_account=self.account))
        self.assertEqual(len(relations), 6)
        self.assertEqual(
            {r.stream_id for r in relations}, {str(100 + i) for i in range(6)},
        )
        # No duplicate Episode rows accumulated across the 3 calls -- still exactly
        # the 10 distinct season/episode-number rows ever seen (Episode rows are
        # matched and reused by season/episode number, never deleted by this
        # function even after their relation is removed, so this stays at the
        # original 10, not the current relation count of 6).
        self.assertEqual(Episode.objects.filter(series=self.series).count(), 10)

    # ── Multi-account isolation ──────────────────────────────────────────

    def test_guard_scoping_is_isolated_per_account(self):
        # The same underlying Series carried by two different M3U accounts
        # (a real, supported Dispatcharr setup -- two providers offering the
        # same show) must be scoped independently: a short fetch for account
        # A must not be evaluated against account B's episode count, and must
        # never touch account B's relations.
        other_account = M3UAccount.objects.create(
            name='XC Episodes Stale Guard (other account)',
            server_url='http://example2.com',
            username='user2',
            password='pass2',
            account_type=M3UAccount.Types.XC,
            is_active=True,
            custom_properties={'enable_vod': True},
        )
        other_relation = M3USeriesRelation.objects.create(
            m3u_account=other_account,
            series=self.series,
            external_series_id='9999',
        )

        self._seed_episodes(10)  # account A: 10 episodes
        episodes_data_b = {'1': [_episode(500 + i, f'B Episode {i}', i) for i in range(3)]}
        batch_process_episodes(
            other_account, self.series, episodes_data_b, series_relation=other_relation,
        )
        self.assertEqual(M3UEpisodeRelation.objects.filter(m3u_account=other_account).count(), 3)

        # Account A gets a short response (1 of 10, 90% loss) -- must be
        # blocked using ONLY account A's own existing count (10), not
        # inflated or diluted by account B's unrelated 3 relations.
        short_response = {'1': [_episode(100, 'Episode 0', 0)]}
        batch_process_episodes(
            self.account, self.series, short_response, series_relation=self.series_relation,
        )

        self.assertEqual(
            M3UEpisodeRelation.objects.filter(m3u_account=self.account).count(), 10,
            "account A's relations must be guarded using only account A's own existing count",
        )
        self.assertEqual(
            M3UEpisodeRelation.objects.filter(m3u_account=other_account).count(), 3,
            "account B's relations must be completely untouched by account A's fetch",
        )

    # ── Legacy (series_relation=None) fallback scoping ──────────────────

    def test_guard_applies_on_legacy_series_relation_none_path(self):
        # Pre-migration rows (or any caller that doesn't pass series_relation)
        # fall back to a plain account+series scope -- the guard must still
        # apply there, not just on the series_relation-scoped path.
        episodes_data = {'1': [_episode(100 + i, f'Episode {i}', i) for i in range(10)]}
        batch_process_episodes(self.account, self.series, episodes_data, series_relation=None)
        self.assertEqual(M3UEpisodeRelation.objects.filter(m3u_account=self.account).count(), 10)

        short_response = {'1': [_episode(100, 'Episode 0', 0)]}
        batch_process_episodes(self.account, self.series, short_response, series_relation=None)

        self.assertEqual(M3UEpisodeRelation.objects.filter(m3u_account=self.account).count(), 10)

    # ── Known, documented trade-off ──────────────────────────────────────

    def test_full_stream_id_reissue_is_treated_as_a_mass_removal_then_self_corrects(self):
        # Documented trade-off, not a bug: if a provider re-issues brand new
        # stream_ids for the exact same episodes (a re-encode, a catalog
        # rebuild on the provider's end), every old relation looks "missing"
        # by id even though the real episode count hasn't changed. The guard
        # can only see stream_id overlap, not episode identity, so it can't
        # tell this apart from a truncated fetch -- it favors "never silently
        # mass-delete" over optimizing for this specific, rarer case.
        #
        # The guard only defers the DELETE, not the CREATE: the new stream
        # ids are still linked as real relations to the (existing, matched by
        # season/episode number) Episode rows immediately. So after one pass,
        # both old and new relations coexist -- no data loss, but real
        # duplication until a later pass reconciles it, which happens
        # automatically: once the new relations exist too, the "stale" old
        # ones become a smaller fraction of a larger total (10 of 20 = 50%,
        # AT the threshold, not over it), so the very next identical refresh
        # crosses back under the guard and cleans them up normally.
        self._seed_episodes(10)

        reissued = {'1': [_episode(900 + i, f'Episode {i}', i) for i in range(10)]}
        batch_process_episodes(
            self.account, self.series, reissued, series_relation=self.series_relation,
        )

        all_ids = set(
            M3UEpisodeRelation.objects.filter(m3u_account=self.account).values_list('stream_id', flat=True)
        )
        self.assertEqual(
            all_ids, {str(100 + i) for i in range(10)} | {str(900 + i) for i in range(10)},
            'old relations deferred (not deleted) AND new ones created -- 20 total, no data loss',
        )
        # Same underlying episodes throughout (matched by season/episode
        # number) -- updated in place, never duplicated.
        self.assertEqual(Episode.objects.filter(series=self.series).count(), 10)

        # A second identical response: now 10 of 20 (50%) would be removed --
        # exactly at the threshold, not over it, so this pass reconciles
        # cleanly down to just the reissued ids.
        batch_process_episodes(
            self.account, self.series, reissued, series_relation=self.series_relation,
        )
        self.assertEqual(
            {r.stream_id for r in M3UEpisodeRelation.objects.filter(m3u_account=self.account)},
            {str(900 + i) for i in range(10)},
        )
