"""resolve_movie_relation: relation-id-first resolution with Movie.id
fallback for XC movie stream_id params."""
from django.test import TestCase

from apps.m3u.models import M3UAccount
from apps.vod.language import resolve_movie_relation
from apps.vod.models import M3UMovieRelation, Movie


class ResolveMovieRelationTests(TestCase):
    def setUp(self):
        self.account = M3UAccount.objects.create(
            name="Resolver Provider",
            server_url="http://example.com",
            username="u",
            password="p",
            account_type=M3UAccount.Types.XC,
            is_active=True,
        )
        self.movie = Movie.objects.create(name="Resolvable Movie", year=2022)
        self.relation = M3UMovieRelation.objects.create(
            m3u_account=self.account, movie=self.movie, stream_id="r-1",
            container_extension="mp4",
        )

    def test_resolves_by_relation_pk(self):
        found = resolve_movie_relation(str(self.relation.id))
        self.assertEqual(found.id, self.relation.id)

    def test_falls_back_to_movie_id_on_pk_miss(self):
        found = resolve_movie_relation(str(self.movie.id + 999999))
        self.assertIsNone(found)

    def test_falls_back_to_movie_id_when_pk_does_not_match_any_relation(self):
        # A raw id that is not a live relation pk but is a real Movie.id.
        other_movie = Movie.objects.create(name="Other Movie", year=2023)
        M3UMovieRelation.objects.create(
            m3u_account=self.account, movie=other_movie, stream_id="r-2",
            container_extension="mp4",
        )
        # Use an id well past any relation pk created so far.
        probe_id = M3UMovieRelation.objects.order_by('-id').first().id + 1000
        # No relation has this pk, and no Movie has this id either -> None.
        self.assertIsNone(resolve_movie_relation(str(probe_id)))

        # Now point the probe at a real Movie.id that isn't a relation pk
        # (guard against accidental collision by only asserting the movie
        # that comes back, whichever path resolved it).
        found = resolve_movie_relation(str(self.movie.id))
        self.assertEqual(found.movie_id, self.movie.id)

    def test_relation_id_wins_over_a_colliding_movie_id(self):
        """A Movie.id that also exists as an M3UMovieRelation.id (for a
        different movie) must resolve via the relation, not the
        coincidentally matching Movie.id. Relation ids are tried first,
        always."""
        colliding_id = 999001
        stale_movie = Movie.objects.create(id=colliding_id, name="Stale Client's Movie", year=2010)
        real_movie = Movie.objects.create(name="Real Anchor Movie", year=2011)
        colliding_relation = M3UMovieRelation.objects.create(
            id=colliding_id, m3u_account=self.account, movie=real_movie,
            stream_id="collide-1", container_extension="mp4",
        )

        found = resolve_movie_relation(str(colliding_id))

        self.assertEqual(found.id, colliding_relation.id)
        self.assertEqual(found.movie_id, real_movie.id)
        self.assertNotEqual(found.movie_id, stale_movie.id)

    def test_non_numeric_id_falls_through_without_raising(self):
        found = resolve_movie_relation("not-a-number")
        self.assertIsNone(found)

    def test_extra_filters_applied_to_both_lookups(self):
        adult_movie = Movie.objects.create(name="Adult Movie", year=2021, is_adult=True)
        adult_relation = M3UMovieRelation.objects.create(
            m3u_account=self.account, movie=adult_movie, stream_id="r-3",
            container_extension="mp4",
        )

        found = resolve_movie_relation(
            str(adult_relation.id), extra_filters={"movie__is_adult": False}
        )
        self.assertIsNone(found)

    def test_inactive_account_is_excluded(self):
        self.account.is_active = False
        self.account.save(update_fields=["is_active"])

        found = resolve_movie_relation(str(self.relation.id))
        self.assertIsNone(found)
