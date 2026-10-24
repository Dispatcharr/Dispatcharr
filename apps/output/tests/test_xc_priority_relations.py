"""XC catalogue winner selection stays in SQL and avoids unselected artwork."""
from unittest.mock import patch

from django.test import TestCase

from apps.m3u.models import M3UAccount
from apps.output import views
from apps.vod.models import M3UMovieRelation, Movie


class XCPriorityRelationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        # bulk_create avoids account-refresh signals: these tests never contact
        # a provider or dispatch background work.
        cls.low, cls.high = M3UAccount.objects.bulk_create([
            M3UAccount(name='Low', server_url='https://low.example.invalid',
                       account_type=M3UAccount.Types.XC, priority=1, is_active=True),
            M3UAccount(name='High', server_url='https://high.example.invalid',
                       account_type=M3UAccount.Types.XC, priority=2, is_active=True),
        ])
        cls.alpha, cls.beta = Movie.objects.bulk_create([
            Movie(name='Alpha'), Movie(name='beta'),
        ])
        cls.loser, cls.winner, cls.tie, cls.other = M3UMovieRelation.objects.bulk_create([
            M3UMovieRelation(m3u_account=cls.low, movie=cls.alpha, stream_id='1'),
            M3UMovieRelation(m3u_account=cls.high, movie=cls.alpha, stream_id='2'),
            M3UMovieRelation(m3u_account=cls.high, movie=cls.alpha, stream_id='3'),
            M3UMovieRelation(m3u_account=cls.low, movie=cls.beta, stream_id='4'),
        ])

    def fetch(self, fields=('id', 'movie_id', 'movie__name'), **filters):
        return views._xc_fetch_priority_distinct_relations(
            manager=M3UMovieRelation.objects,
            rel_filters={'m3u_account__is_active': True, **filters},
            distinct_field='movie_id', value_fields=fields,
            order_by_name_field='movie__name',
        )

    def test_priority_tie_break_and_name_order_in_one_query(self):
        with self.assertNumQueries(1):
            rows = self.fetch()
        self.assertEqual([r['id'] for r in rows], [self.winner.pk, self.other.pk])

    def test_filters_apply_before_winner_selection(self):
        rows = self.fetch(m3u_account_id=self.low.pk)
        self.assertEqual([r['id'] for r in rows], [self.loser.pk, self.other.pk])
        self.assertEqual(self.fetch(movie_id=-1), [])

    def test_narrow_selection_skips_artwork_annotations(self):
        with patch.object(views, '_xc_annotate_relation_artwork',
                          side_effect=AssertionError('unselected artwork')):
            self.assertEqual(len(self.fetch()), 2)

    def test_artwork_selection_still_annotates(self):
        with patch.object(views, '_xc_annotate_relation_artwork',
                          wraps=views._xc_annotate_relation_artwork) as annotate:
            rows = self.fetch(fields=('id', 'movie_id', 'movie__name', 'rel_movie_image'))
        annotate.assert_called_once()
        self.assertTrue(all('rel_movie_image' in row for row in rows))
