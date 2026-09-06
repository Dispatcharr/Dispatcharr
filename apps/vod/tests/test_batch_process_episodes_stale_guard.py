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
