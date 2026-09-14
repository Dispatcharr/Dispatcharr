"""xc_get_vod_streams / xc_get_series under the VOD category-language feature.

Covers the zero-config no-op case, movie anchor (min id) nomination vs
series winner (quality then priority) nomination, and the title suffix.
"""
from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from django.utils import timezone

from apps.m3u.models import M3UAccount
from apps.output.views import xc_get_series, xc_get_series_info, xc_get_vod_streams
from apps.vod.language import invalidate_category_metadata_cache
from apps.vod.models import (
    Episode,
    M3UEpisodeRelation,
    M3UMovieRelation,
    M3USeriesRelation,
    M3UVODCategoryRelation,
    Movie,
    Series,
    VODCategory,
)

User = get_user_model()


class _BaseVodLanguageTests(TestCase):
    def setUp(self):
        invalidate_category_metadata_cache()
        self.addCleanup(invalidate_category_metadata_cache)

        self.factory = RequestFactory()
        self.user = User.objects.create_user(username='vodlanguser', password='testpass123')
        self.user.user_level = 10
        self.user.save()

    def _account(self, name, priority=0):
        return M3UAccount.objects.create(
            name=name,
            server_url=f'http://{name.lower()}.example.com',
            username='u',
            password='p',
            account_type=M3UAccount.Types.XC,
            is_active=True,
            priority=priority,
            custom_properties={'enable_vod': True},
        )

    def _category(self, name, category_type, language=None, quality=None):
        category = VODCategory.objects.create(name=name, category_type=category_type)
        props = {}
        if language is not None:
            props['language'] = language
        if quality is not None:
            props['quality'] = quality
        return category, props

    def _cat_relation(self, category, account, props):
        return M3UVODCategoryRelation.objects.create(
            category=category, m3u_account=account, enabled=True, custom_properties=props,
        )

    def _request(self):
        return self.factory.get('/player_api.php')


class MovieLanguageOutputTests(_BaseVodLanguageTests):
    def test_zero_config_is_byte_identical_to_legacy(self):
        account = self._account('Solo')
        movie = Movie.objects.create(name='Legacy Movie', year=2000)
        M3UMovieRelation.objects.create(
            m3u_account=account, movie=movie, stream_id='m-1', container_extension='mp4',
        )

        streams = xc_get_vod_streams(self._request(), self.user)

        self.assertEqual(len(streams), 1)
        self.assertEqual(streams[0]['stream_id'], movie.id)
        self.assertEqual(streams[0]['name'], 'Legacy Movie')

    def test_different_category_languages_produce_two_entries(self):
        account = self._account('Provider')
        movie = Movie.objects.create(name='Shared Movie', tmdb_id='mv-1', year=2001)

        es_category, es_props = self._category('Spanish Movies', 'movie', language='es')
        fr_category, fr_props = self._category('French Movies', 'movie', language='fr')
        self._cat_relation(es_category, account, es_props)
        self._cat_relation(fr_category, account, fr_props)

        rel_es = M3UMovieRelation.objects.create(
            m3u_account=account, movie=movie, category=es_category,
            stream_id='es-1', container_extension='mp4',
        )
        rel_fr = M3UMovieRelation.objects.create(
            m3u_account=account, movie=movie, category=fr_category,
            stream_id='fr-1', container_extension='mp4',
        )

        streams = xc_get_vod_streams(self._request(), self.user)

        self.assertEqual(len(streams), 2)
        by_id = {s['stream_id']: s for s in streams}
        self.assertIn(rel_es.id, by_id)
        self.assertIn(rel_fr.id, by_id)
        self.assertEqual(by_id[rel_es.id]['name'], 'Shared Movie [ES]')
        self.assertEqual(by_id[rel_fr.id]['name'], 'Shared Movie [FR]')

    def test_same_language_group_collapses_to_anchor_min_id(self):
        low_priority = self._account('LowPriority', priority=1)
        high_priority = self._account('HighPriority', priority=10)
        movie = Movie.objects.create(name='Collapsed Movie', tmdb_id='mv-2', year=2002)

        category, props = self._category('Spanish Movies 2', 'movie', language='es')
        self._cat_relation(category, low_priority, props)
        self._cat_relation(category, high_priority, props)

        first_rel = M3UMovieRelation.objects.create(
            m3u_account=low_priority, movie=movie, category=category,
            stream_id='low-1', container_extension='mp4',
        )
        M3UMovieRelation.objects.create(
            m3u_account=high_priority, movie=movie, category=category,
            stream_id='high-1', container_extension='mp4',
        )

        streams = xc_get_vod_streams(self._request(), self.user)

        self.assertEqual(len(streams), 1)
        # Anchor is min(id) in the group, independent of account priority.
        self.assertEqual(streams[0]['stream_id'], first_rel.id)
        self.assertEqual(streams[0]['name'], 'Collapsed Movie [ES]')

    def test_anchor_is_stable_when_a_higher_quality_relation_is_added(self):
        """Anchor selection is stable when a higher-quality relation is
        added to the group later."""
        account_a = self._account('AnchorFirst', priority=1)
        account_b = self._account('AnchorSecond', priority=1)
        movie = Movie.objects.create(name='Stable Anchor Movie', tmdb_id='mv-4', year=2004)

        category, props = self._category('Spanish Movies 4', 'movie', language='es', quality='720p')
        self._cat_relation(category, account_a, props)
        self._cat_relation(category, account_b, props)

        first_rel = M3UMovieRelation.objects.create(
            m3u_account=account_a, movie=movie, category=category,
            stream_id='first-1', container_extension='mp4',
        )
        streams_before = xc_get_vod_streams(self._request(), self.user)
        self.assertEqual(len(streams_before), 1)
        self.assertEqual(streams_before[0]['stream_id'], first_rel.id)

        # A higher-quality relation joins the same (movie, language) group.
        M3UMovieRelation.objects.create(
            m3u_account=account_b, movie=movie, category=category,
            stream_id='second-hq-1', container_extension='mp4',
            custom_properties={'quality': '4K'},
        )

        streams_after = xc_get_vod_streams(self._request(), self.user)
        self.assertEqual(len(streams_after), 1)
        # Anchor (min id) is unchanged even though a better-quality relation
        # now exists in the group.
        self.assertEqual(streams_after[0]['stream_id'], first_rel.id)

    def test_unassigned_category_has_no_suffix_and_groups_as_unknown(self):
        account = self._account('Unassigned')
        # A second, unrelated category *is* language-assigned so the feature
        # is active, but this movie's own category is not.
        other_category, other_props = self._category('Spanish Movies 3', 'movie', language='es')
        other_account = self._account('OtherProvider')
        self._cat_relation(other_category, other_account, other_props)

        movie = Movie.objects.create(name='Unknown Lang Movie', tmdb_id='mv-3', year=2003)
        M3UMovieRelation.objects.create(
            m3u_account=account, movie=movie, stream_id='unk-1', container_extension='mp4',
        )

        streams = xc_get_vod_streams(self._request(), self.user)
        target = next(s for s in streams if s['name'].startswith('Unknown Lang Movie'))
        self.assertEqual(target['name'], 'Unknown Lang Movie')


class SeriesLanguageOutputTests(_BaseVodLanguageTests):
    def test_different_category_languages_produce_two_entries(self):
        account = self._account('Provider')
        series = Series.objects.create(name='Shared Series', tmdb_id='sr-1', year=2001)

        es_category, es_props = self._category('Spanish Series', 'series', language='es')
        fr_category, fr_props = self._category('French Series', 'series', language='fr')
        self._cat_relation(es_category, account, es_props)
        self._cat_relation(fr_category, account, fr_props)

        rel_es = M3USeriesRelation.objects.create(
            m3u_account=account, series=series, category=es_category,
            external_series_id='es-1',
        )
        rel_fr = M3USeriesRelation.objects.create(
            m3u_account=account, series=series, category=fr_category,
            external_series_id='fr-1',
        )

        results = xc_get_series(self._request(), self.user)

        self.assertEqual(len(results), 2)
        by_id = {s['series_id']: s for s in results}
        self.assertIn(rel_es.id, by_id)
        self.assertIn(rel_fr.id, by_id)
        self.assertEqual(by_id[rel_es.id]['name'], 'Shared Series [ES]')
        self.assertEqual(by_id[rel_fr.id]['name'], 'Shared Series [FR]')

    def test_higher_quality_wins_over_higher_priority_within_same_language(self):
        """Higher quality wins even when the lower-quality provider has
        higher account priority."""
        low_quality_high_priority = self._account('LowQualityHighPriority', priority=10)
        high_quality_low_priority = self._account('HighQualityLowPriority', priority=1)
        series = Series.objects.create(name='Ranked Series', tmdb_id='sr-2', year=2002)

        category, props = self._category(
            'Spanish Series 2', 'series', language='es', quality='720p'
        )
        self._cat_relation(category, low_quality_high_priority, props)

        hq_category, hq_props = self._category(
            'Spanish Series 2 HQ', 'series', language='es', quality='1080p'
        )
        self._cat_relation(hq_category, high_quality_low_priority, hq_props)

        M3USeriesRelation.objects.create(
            m3u_account=low_quality_high_priority, series=series, category=category,
            external_series_id='lq-1',
        )
        hq_rel = M3USeriesRelation.objects.create(
            m3u_account=high_quality_low_priority, series=series, category=hq_category,
            external_series_id='hq-1',
        )

        results = xc_get_series(self._request(), self.user)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['series_id'], hq_rel.id)

    def test_zero_config_matches_legacy_winner_by_priority(self):
        low = self._account('Low', priority=1)
        high = self._account('High', priority=10)
        series = Series.objects.create(name='Legacy Series', year=2000)

        M3USeriesRelation.objects.create(
            m3u_account=low, series=series, external_series_id='low-1',
        )
        winning_rel = M3USeriesRelation.objects.create(
            m3u_account=high, series=series, external_series_id='high-1',
        )

        results = xc_get_series(self._request(), self.user)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['series_id'], winning_rel.id)
        self.assertEqual(results[0]['name'], 'Legacy Series')


class SeriesInfoEpisodeLanguageTests(_BaseVodLanguageTests):
    """xc_get_series_info's per-episode relation selection: which provider's
    M3UEpisodeRelation backs an episode depends on the language of the
    specific series_relation (series_id) the client asked for, not just
    whichever provider has the highest account priority overall."""

    def _series_relation(self, account, series, category, external_id):
        return M3USeriesRelation.objects.create(
            m3u_account=account, series=series, category=category,
            external_series_id=external_id,
            # Skip xc_get_series_info's refresh-episodes-from-provider path.
            custom_properties={'episodes_fetched': True, 'detailed_fetched': True},
            last_episode_refresh=timezone.now(),
        )

    def test_picks_the_relation_matching_the_requested_series_language(self):
        es_account = self._account('SeriesInfoSpanish', priority=1)
        en_account = self._account('SeriesInfoEnglish', priority=10)
        series = Series.objects.create(name='Info Series', year=2020)
        episode = Episode.objects.create(series=series, name='Ep 1', season_number=1, episode_number=1)

        es_category, es_props = self._category('Info Spanish', 'series', language='es')
        en_category, en_props = self._category('Info English', 'series', language='en')
        self._cat_relation(es_category, es_account, es_props)
        self._cat_relation(en_category, en_account, en_props)

        es_series_rel = self._series_relation(es_account, series, es_category, 'es-series-1')
        self._series_relation(en_account, series, en_category, 'en-series-1')

        es_ep_rel = M3UEpisodeRelation.objects.create(
            m3u_account=es_account, episode=episode, series_relation=es_series_rel, stream_id='es-ep-1',
        )
        M3UEpisodeRelation.objects.create(
            m3u_account=en_account, episode=episode,
            series_relation=M3USeriesRelation.objects.get(external_series_id='en-series-1'),
            stream_id='en-ep-1',
        )

        # The client asked for the Spanish series listing specifically.
        info = xc_get_series_info(self._request(), self.user, es_series_rel.id)

        episodes = info['episodes'][1]
        self.assertEqual(len(episodes), 1)
        self.assertEqual(episodes[0]['id'], es_ep_rel.id)

    def test_falls_back_to_best_of_rest_when_no_language_match(self):
        """An episode with only an off-language relation still plays rather
        than vanishing from the requested language's listing."""
        es_account = self._account('SeriesInfoSpanishOnly', priority=1)
        en_account = self._account('SeriesInfoEnglishOnly', priority=10)
        series = Series.objects.create(name='Partial Info Series', year=2021)
        episode = Episode.objects.create(series=series, name='Ep 1', season_number=1, episode_number=1)

        es_category, es_props = self._category('Partial Info Spanish', 'series', language='es')
        en_category, en_props = self._category('Partial Info English', 'series', language='en')
        self._cat_relation(es_category, es_account, es_props)
        self._cat_relation(en_category, en_account, en_props)

        es_series_rel = self._series_relation(es_account, series, es_category, 'es-series-2')

        # Only the English provider actually has this episode.
        en_ep_rel = M3UEpisodeRelation.objects.create(
            m3u_account=en_account, episode=episode,
            series_relation=self._series_relation(en_account, series, en_category, 'en-series-2'),
            stream_id='en-ep-2',
        )

        info = xc_get_series_info(self._request(), self.user, es_series_rel.id)

        episodes = info['episodes'][1]
        self.assertEqual(len(episodes), 1)
        self.assertEqual(episodes[0]['id'], en_ep_rel.id)

    def test_quality_beats_priority_within_the_matched_language_group(self):
        hi_priority_lo_quality = self._account('InfoHiPriLoQual', priority=10)
        lo_priority_hi_quality = self._account('InfoLoPriHiQual', priority=1)
        series = Series.objects.create(name='Info Ranked Series', year=2022)
        episode = Episode.objects.create(series=series, name='Ep 1', season_number=1, episode_number=1)

        lo_q_category, lo_q_props = self._category(
            'Info Spanish LQ', 'series', language='es', quality='720p'
        )
        hi_q_category, hi_q_props = self._category(
            'Info Spanish HQ', 'series', language='es', quality='1080p'
        )
        self._cat_relation(lo_q_category, hi_priority_lo_quality, lo_q_props)
        self._cat_relation(hi_q_category, lo_priority_hi_quality, hi_q_props)

        requesting_series_rel = self._series_relation(
            hi_priority_lo_quality, series, lo_q_category, 'lq-series-1'
        )
        hi_q_series_rel = self._series_relation(
            lo_priority_hi_quality, series, hi_q_category, 'hq-series-1'
        )

        M3UEpisodeRelation.objects.create(
            m3u_account=hi_priority_lo_quality, episode=episode,
            series_relation=requesting_series_rel, stream_id='lq-ep-1',
        )
        hi_q_ep_rel = M3UEpisodeRelation.objects.create(
            m3u_account=lo_priority_hi_quality, episode=episode,
            series_relation=hi_q_series_rel, stream_id='hq-ep-1',
        )

        info = xc_get_series_info(self._request(), self.user, requesting_series_rel.id)

        episodes = info['episodes'][1]
        self.assertEqual(len(episodes), 1)
        # Both relations resolve to the 'es' group the request asked for;
        # the higher-quality one wins even though its account has lower
        # priority (matches _order_candidates_by_language's playback rule).
        self.assertEqual(episodes[0]['id'], hi_q_ep_rel.id)

    def test_zero_config_matches_legacy_highest_priority_relation(self):
        low = self._account('InfoLegacyLow', priority=1)
        high = self._account('InfoLegacyHigh', priority=10)
        series = Series.objects.create(name='Legacy Info Series', year=2010)
        episode = Episode.objects.create(series=series, name='Ep 1', season_number=1, episode_number=1)

        low_series_rel = self._series_relation(low, series, None, 'legacy-low-1')
        self._series_relation(high, series, None, 'legacy-high-1')

        M3UEpisodeRelation.objects.create(
            m3u_account=low, episode=episode, series_relation=low_series_rel,
            stream_id='legacy-low-ep-1', container_extension='avi',
        )
        M3UEpisodeRelation.objects.create(
            m3u_account=high, episode=episode,
            series_relation=M3USeriesRelation.objects.get(external_series_id='legacy-high-1'),
            stream_id='legacy-high-ep-1', container_extension='mkv',
        )

        info = xc_get_series_info(self._request(), self.user, low_series_rel.id)

        episodes = info['episodes'][1]
        self.assertEqual(len(episodes), 1)
        # Feature is off: the exposed id stays Episode.id regardless of
        # which series_id was requested.
        self.assertEqual(episodes[0]['id'], episode.id)
        # Which relation's metadata backs the response is still
        # priority-ordered: the highest-priority account's
        # container_extension wins.
        self.assertEqual(episodes[0]['container_extension'], 'mkv')
