"""REST VOD endpoints respect per-user movie/series access flags."""

from uuid import uuid4

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.m3u.models import M3UAccount
from apps.vod.models import (
    Episode,
    M3UEpisodeRelation,
    M3UMovieRelation,
    M3USeriesRelation,
    Movie,
    Series,
    VODCategory,
)

User = get_user_model()


class VodRestAccessFlagTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.account = M3UAccount.objects.create(
            name=f"rest-vod-{uuid4().hex[:6]}",
            server_url="http://example.com",
            priority=1,
            is_active=True,
        )
        self.movie_category = VODCategory.objects.create(
            name=f"Movies {uuid4().hex[:6]}", category_type="movie"
        )
        self.series_category = VODCategory.objects.create(
            name=f"Series {uuid4().hex[:6]}", category_type="series"
        )
        self.movie = Movie.objects.create(name="REST Gated Movie")
        M3UMovieRelation.objects.create(
            m3u_account=self.account,
            movie=self.movie,
            category=self.movie_category,
            stream_id="movie-1",
        )
        self.series = Series.objects.create(name="REST Gated Series")
        series_relation = M3USeriesRelation.objects.create(
            m3u_account=self.account,
            series=self.series,
            category=self.series_category,
            external_series_id="series-1",
        )
        self.episode = Episode.objects.create(
            series=self.series,
            name="Pilot",
            season_number=1,
            episode_number=1,
        )
        M3UEpisodeRelation.objects.create(
            m3u_account=self.account,
            episode=self.episode,
            series_relation=series_relation,
            stream_id="episode-1",
        )

    def _user(self, **custom_properties):
        return User.objects.create_user(
            username=f"rest-vod-{uuid4().hex[:8]}",
            password="pass",
            user_level=User.UserLevel.STANDARD,
            custom_properties=custom_properties,
        )

    def _results(self, path):
        response = self.client.get(path)
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        if isinstance(payload, dict) and "results" in payload:
            return payload["results"]
        return payload

    def test_absent_flags_keep_rest_access(self):
        self.client.force_authenticate(user=self._user())
        movie_names = {row["name"] for row in self._results("/api/vod/movies/")}
        series_names = {row["name"] for row in self._results("/api/vod/series/")}
        episode_names = {row["name"] for row in self._results("/api/vod/episodes/")}
        self.assertIn("REST Gated Movie", movie_names)
        self.assertIn("REST Gated Series", series_names)
        self.assertIn("Pilot", episode_names)

    def test_movies_flag_hides_movies_but_not_series(self):
        self.client.force_authenticate(user=self._user(vod_movies_enabled=False))
        self.assertEqual(self._results("/api/vod/movies/"), [])
        self.assertEqual(
            self.client.get(f"/api/vod/movies/{self.movie.id}/").status_code, 404
        )
        series_names = {row["name"] for row in self._results("/api/vod/series/")}
        self.assertIn("REST Gated Series", series_names)

    def test_series_flag_hides_series_and_episodes(self):
        self.client.force_authenticate(user=self._user(vod_series_enabled=False))
        self.assertEqual(self._results("/api/vod/series/"), [])
        self.assertEqual(self._results("/api/vod/episodes/"), [])
        self.assertEqual(
            self.client.get(f"/api/vod/series/{self.series.id}/").status_code, 404
        )
        self.assertEqual(
            self.client.get(f"/api/vod/episodes/{self.episode.id}/").status_code, 404
        )
        movie_names = {row["name"] for row in self._results("/api/vod/movies/")}
        self.assertIn("REST Gated Movie", movie_names)

    def test_unified_all_endpoint_respects_each_flag(self):
        no_movies = self._user(vod_movies_enabled=False)
        self.client.force_authenticate(user=no_movies)
        types = {row["content_type"] for row in self._results("/api/vod/all/")}
        self.assertNotIn("movie", types)
        self.assertIn("series", types)

        no_series = self._user(vod_series_enabled=False)
        self.client.force_authenticate(user=no_series)
        types = {row["content_type"] for row in self._results("/api/vod/all/")}
        self.assertIn("movie", types)
        self.assertNotIn("series", types)

        both_off = self._user(vod_movies_enabled=False, vod_series_enabled=False)
        self.client.force_authenticate(user=both_off)
        self.assertEqual(self._results("/api/vod/all/"), [])

    def test_categories_are_filtered_by_kind(self):
        self.client.force_authenticate(user=self._user(vod_movies_enabled=False))
        types = {
            row["category_type"] for row in self._results("/api/vod/categories/")
        }
        self.assertNotIn("movie", types)
        self.assertIn("series", types)

    def test_anonymous_requests_are_not_gated_by_flags(self):
        """No authenticated user means nothing to tie a flag to, so content stays visible."""
        from django.contrib.auth.models import AnonymousUser
        from rest_framework.test import APIRequestFactory

        from apps.vod.api_views import MovieViewSet, SeriesViewSet

        factory = APIRequestFactory()
        request = factory.get("/api/vod/movies/")
        request.user = AnonymousUser()

        movie_view = MovieViewSet()
        movie_view.request = request
        movie_view.format_kwarg = None
        self.assertTrue(
            movie_view.get_queryset().filter(pk=self.movie.pk).exists()
        )

        series_view = SeriesViewSet()
        series_view.request = request
        series_view.format_kwarg = None
        self.assertTrue(
            series_view.get_queryset().filter(pk=self.series.pk).exists()
        )

    def test_authenticated_disabled_user_cannot_retrieve_movie_image(self):
        self.client.force_authenticate(user=self._user(vod_movies_enabled=False))
        response = self.client.get(
            f"/api/vod/movies/{self.movie.id}/image/?kind=movie_image"
        )
        self.assertEqual(response.status_code, 404)
