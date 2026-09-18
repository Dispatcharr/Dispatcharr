from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from apps.vod.api_views import MovieFilter, SeriesFilter
from apps.vod.models import Episode, Movie, Series


class LibraryAddedAtTests(TestCase):
    def test_library_timestamp_is_stable_when_content_is_updated(self):
        imported_at = timezone.now() - timedelta(days=30)
        movie = Movie.objects.create(
            name="Existing movie",
            library_added_at=imported_at,
        )

        movie.description = "Metadata received by a later refresh"
        movie.save(update_fields=["description", "updated_at"])
        movie.refresh_from_db()

        self.assertEqual(movie.library_added_at, imported_at)

    def test_new_library_rows_receive_their_own_import_timestamp(self):
        before = timezone.now()
        series = Series.objects.create(name="New series")
        episode = Episode.objects.create(name="Pilot", series=series)
        after = timezone.now()

        self.assertLessEqual(before, series.library_added_at)
        self.assertLessEqual(series.library_added_at, after)
        self.assertLessEqual(before, episode.library_added_at)
        self.assertLessEqual(episode.library_added_at, after)

    def test_movie_and_series_filters_support_library_date_ranges(self):
        cutoff = timezone.now() - timedelta(days=7)
        old_movie = Movie.objects.create(
            name="Old movie",
            library_added_at=cutoff - timedelta(days=1),
        )
        new_movie = Movie.objects.create(
            name="New movie",
            library_added_at=cutoff + timedelta(days=1),
        )
        old_series = Series.objects.create(
            name="Old series",
            library_added_at=cutoff - timedelta(days=1),
        )
        new_series = Series.objects.create(
            name="New series",
            library_added_at=cutoff + timedelta(days=1),
        )

        movie_ids = set(
            MovieFilter(
                {"library_added_after": cutoff.isoformat()},
                queryset=Movie.objects.all(),
            ).qs.values_list("id", flat=True)
        )
        series_ids = set(
            SeriesFilter(
                {"library_added_after": cutoff.isoformat()},
                queryset=Series.objects.all(),
            ).qs.values_list("id", flat=True)
        )

        self.assertEqual(movie_ids, {new_movie.id})
        self.assertNotIn(old_movie.id, movie_ids)
        self.assertEqual(series_ids, {new_series.id})
        self.assertNotIn(old_series.id, series_ids)
