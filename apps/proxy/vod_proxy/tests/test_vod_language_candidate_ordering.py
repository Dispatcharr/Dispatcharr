"""_order_candidates_by_language: playback candidate ranking within (and
falling back beyond) a resolved language group.

The anchor that got picked for display is never privileged here. The whole
candidate set is re-ranked by (language match, quality, priority, id), and a
language group with no playable relation still falls back to the full set
rather than failing.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.m3u.models import M3UAccount
from apps.proxy.vod_proxy.views import _order_candidates_by_language
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


class OrderCandidatesByLanguageTests(TestCase):
    def setUp(self):
        invalidate_category_metadata_cache()
        self.addCleanup(invalidate_category_metadata_cache)
        self.movie = Movie.objects.create(name='Ranked Movie', year=2020)

    def _account(self, name, priority):
        return M3UAccount.objects.create(
            name=name, server_url=f'http://{name.lower()}.example.com',
            username='u', password='p', account_type=M3UAccount.Types.XC,
            is_active=True, priority=priority,
        )

    def _category(self, name, language=None, quality=None):
        category = VODCategory.objects.create(name=name, category_type='movie')
        props = {}
        if language is not None:
            props['language'] = language
        if quality is not None:
            props['quality'] = quality
        return category, props

    def _relation(self, account, category, cat_props, stream_id, rel_language=None):
        if category is not None:
            M3UVODCategoryRelation.objects.create(
                category=category, m3u_account=account, enabled=True, custom_properties=cat_props,
            )
        custom_properties = {}
        if rel_language:
            custom_properties['language'] = rel_language
        return M3UMovieRelation.objects.create(
            m3u_account=account, movie=self.movie, category=category,
            stream_id=stream_id, container_extension='mp4',
            custom_properties=custom_properties,
        )

    def test_matching_language_ranked_ahead_of_non_matching(self):
        es_account = self._account('Spanish', priority=1)
        en_account = self._account('English', priority=10)
        es_category, es_props = self._category('Spanish Movies', language='es')
        en_category, en_props = self._category('English Movies', language='en')

        es_rel = self._relation(es_account, es_category, es_props, 'es-1')
        en_rel = self._relation(en_account, en_category, en_props, 'en-1')

        ordered = _order_candidates_by_language([en_rel, es_rel], self.movie, 'es')

        self.assertEqual(ordered[0].id, es_rel.id)
        self.assertEqual(ordered[1].id, en_rel.id)

    def test_within_language_group_quality_beats_priority(self):
        hi_priority_lo_quality = self._account('HiPriorityLoQuality', priority=10)
        lo_priority_hi_quality = self._account('LoPriorityHiQuality', priority=1)
        lo_q_category, lo_q_props = self._category('Spanish 720p', language='es', quality='720p')
        hi_q_category, hi_q_props = self._category('Spanish 1080p', language='es', quality='1080p')

        lo_q_rel = self._relation(hi_priority_lo_quality, lo_q_category, lo_q_props, 'lo-1')
        hi_q_rel = self._relation(lo_priority_hi_quality, hi_q_category, hi_q_props, 'hi-1')

        ordered = _order_candidates_by_language([lo_q_rel, hi_q_rel], self.movie, 'es')

        self.assertEqual(ordered[0].id, hi_q_rel.id)
        self.assertEqual(ordered[1].id, lo_q_rel.id)

    def test_no_matching_relation_falls_back_to_full_set_not_empty(self):
        en_account = self._account('OnlyEnglish', priority=5)
        en_category, en_props = self._category('English Only', language='en')
        en_rel = self._relation(en_account, en_category, en_props, 'en-only-1')

        ordered = _order_candidates_by_language([en_rel], self.movie, 'es')

        # No relation in the requested 'es' group, but the candidate is still
        # present (never filtered out) so playback has something to try.
        self.assertEqual(len(ordered), 1)
        self.assertEqual(ordered[0].id, en_rel.id)

    def test_priority_breaks_ties_within_same_quality(self):
        low = self._account('LowPriority', priority=1)
        high = self._account('HighPriority', priority=9)
        category, props = self._category('Spanish Same Quality', language='es', quality='1080p')

        low_rel = self._relation(low, category, props, 'low-1')
        high_rel = self._relation(high, category, props, 'high-1')

        ordered = _order_candidates_by_language([low_rel, high_rel], self.movie, 'es')

        self.assertEqual(ordered[0].id, high_rel.id)
        self.assertEqual(ordered[1].id, low_rel.id)


class OrderCandidatesByLanguageEpisodeTests(TestCase):
    """Same ranking, but for M3UEpisodeRelation. Category lives on the
    parent series_relation rather than on the relation itself, which is
    exactly the indirection category_id_for_relation exists to hide."""

    def setUp(self):
        invalidate_category_metadata_cache()
        self.addCleanup(invalidate_category_metadata_cache)
        self.series = Series.objects.create(name='Ranked Series', year=2020)
        self.episode = Episode.objects.create(series=self.series, name='Ranked Episode')

    def _account(self, name, priority):
        return M3UAccount.objects.create(
            name=name, server_url=f'http://{name.lower()}.example.com',
            username='u', password='p', account_type=M3UAccount.Types.XC,
            is_active=True, priority=priority,
        )

    def _episode_relation(self, account, language=None, quality=None, stream_id='e-1'):
        category = VODCategory.objects.create(name=f'{account.name} Cat', category_type='series')
        props = {}
        if language is not None:
            props['language'] = language
        if quality is not None:
            props['quality'] = quality
        M3UVODCategoryRelation.objects.create(
            category=category, m3u_account=account, enabled=True, custom_properties=props,
        )
        series_relation = M3USeriesRelation.objects.create(
            m3u_account=account, series=self.series, category=category,
            external_series_id=f'ext-{stream_id}',
        )
        return M3UEpisodeRelation.objects.create(
            m3u_account=account, episode=self.episode, series_relation=series_relation,
            stream_id=stream_id,
        )

    def test_matching_language_ranked_ahead_of_non_matching(self):
        es_account = self._account('SpanishEp', priority=1)
        en_account = self._account('EnglishEp', priority=10)
        es_rel = self._episode_relation(es_account, language='es', stream_id='es-1')
        en_rel = self._episode_relation(en_account, language='en', stream_id='en-1')

        ordered = _order_candidates_by_language([en_rel, es_rel], self.episode, 'es')

        self.assertEqual(ordered[0].id, es_rel.id)
        self.assertEqual(ordered[1].id, en_rel.id)

    def test_within_language_group_quality_beats_priority(self):
        hi_priority_lo_quality = self._account('HiPriLoQualEp', priority=10)
        lo_priority_hi_quality = self._account('LoPriHiQualEp', priority=1)
        lo_q_rel = self._episode_relation(
            hi_priority_lo_quality, language='es', quality='720p', stream_id='lo-1'
        )
        hi_q_rel = self._episode_relation(
            lo_priority_hi_quality, language='es', quality='1080p', stream_id='hi-1'
        )

        ordered = _order_candidates_by_language([lo_q_rel, hi_q_rel], self.episode, 'es')

        self.assertEqual(ordered[0].id, hi_q_rel.id)
        self.assertEqual(ordered[1].id, lo_q_rel.id)

    def test_no_matching_relation_falls_back_to_full_set_not_empty(self):
        en_account = self._account('OnlyEnglishEp', priority=5)
        en_rel = self._episode_relation(en_account, language='en', stream_id='en-only-1')

        ordered = _order_candidates_by_language([en_rel], self.episode, 'es')

        self.assertEqual(len(ordered), 1)
        self.assertEqual(ordered[0].id, en_rel.id)
