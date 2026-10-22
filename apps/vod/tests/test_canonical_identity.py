"""Source languages must never split canonical movie/series identity."""

from django.test import TestCase

from apps.m3u.models import M3UAccount
from apps.vod.identity import handle_identity_conflicts
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
from apps.vod.selection import resolve_content
from apps.vod.tasks import process_movie_batch, process_series_batch


class CanonicalIdentityTests(TestCase):
    def setUp(self):
        self.account = M3UAccount.objects.create(name="Canonical XC", account_type="XC")
        self.movie_category = VODCategory.objects.create(
            name="Movies", category_type="movie"
        )
        self.series_category = VODCategory.objects.create(
            name="Series", category_type="series"
        )
        self.movie_defaults = M3UVODCategoryRelation.objects.create(
            m3u_account=self.account,
            category=self.movie_category,
            enabled=True,
            metadata_defaults={"audio_languages": ["ger", "eng"]},
        )
        self.series_defaults = M3UVODCategoryRelation.objects.create(
            m3u_account=self.account,
            category=self.series_category,
            enabled=True,
            metadata_defaults={"audio_languages": ["ger"]},
        )

    def movies(self, rows):
        return process_movie_batch(
            self.account,
            rows,
            {"1": self.movie_category},
            {self.movie_category.pk: self.movie_defaults},
        )

    def test_multilingual_movie_sources_share_one_identity(self):
        rows = [
            {
                "stream_id": 1,
                "category_id": "1",
                "name": "Film",
                "tmdb_id": "10",
                "audio_languages": ["de"],
            },
            {
                "stream_id": 2,
                "category_id": "1",
                "name": "Film",
                "tmdb_id": "10",
                "audio_languages": ["de", "en"],
            },
        ]
        self.movies(rows)
        movie = Movie.objects.get(tmdb_id="10")
        ids = list(M3UMovieRelation.objects.order_by("pk").values_list("pk", flat=True))
        self.movies(rows)
        self.assertEqual(Movie.objects.get(tmdb_id="10").pk, movie.pk)
        self.assertEqual(
            list(M3UMovieRelation.objects.order_by("pk").values_list("pk", flat=True)),
            ids,
        )
        self.assertEqual(movie.m3u_relations.count(), 2)
        self.assertNotIn("language", {field.name for field in Movie._meta.fields})

    def test_category_retag_never_moves_existing_sources(self):
        row = {"stream_id": 1, "category_id": "1", "name": "Film", "tmdb_id": "10"}
        self.movies([row])
        source = M3UMovieRelation.objects.get(stream_id="1")
        original = source.movie_id, source.pk
        self.movie_defaults.metadata_defaults = {
            "audio_languages": ["fre"],
            "video_features": ["hdr"],
        }
        self.movie_defaults.save()
        self.movies([row])
        source.refresh_from_db()
        self.assertEqual((source.movie_id, source.pk), original)
        self.assertEqual(
            source.effective_metadata()["values"]["audio_languages"], ["fre"]
        )

    def test_unknown_titles_remain_source_bound(self):
        rows = [
            {"stream_id": source_id, "category_id": "1", "name": "Unknown film"}
            for source_id in (1, 2)
        ]
        self.movies(rows)
        self.assertEqual(Movie.objects.count(), 2)
        source_ids = list(
            M3UMovieRelation.objects.order_by("pk").values_list("movie_id", flat=True)
        )
        self.movies(rows)
        self.assertEqual(
            list(
                M3UMovieRelation.objects.order_by("pk").values_list(
                    "movie_id", flat=True
                )
            ),
            source_ids,
        )

    def test_sparse_refresh_does_not_detach_known_source(self):
        self.movies(
            [{"stream_id": 1, "category_id": "1", "name": "Film", "tmdb_id": "10"}]
        )
        source = M3UMovieRelation.objects.get(stream_id="1")
        original = source.movie_id
        self.movies([{"stream_id": 1, "category_id": "1", "name": "Film"}])
        source.refresh_from_db()
        self.assertEqual(source.movie_id, original)
        self.assertEqual(source.movie.tmdb_id, "10")

    def test_series_import_uses_content_identity_not_audio_languages(self):
        rows = [
            {
                "series_id": 1,
                "category_id": "1",
                "name": "Show",
                "imdb_id": "tt10",
                "audio_languages": ["de"],
            },
            {
                "series_id": 2,
                "category_id": "1",
                "name": "Show",
                "imdb_id": "tt10",
                "audio_languages": ["en"],
            },
        ]
        for _ in range(2):
            process_series_batch(
                self.account,
                rows,
                {"1": self.series_category},
                {self.series_category.pk: self.series_defaults},
            )
        self.assertEqual(Series.objects.filter(imdb_id="tt10").count(), 1)
        self.assertEqual(M3USeriesRelation.objects.count(), 2)

    def test_detail_merge_preserves_episode_sources_and_old_urls(self):
        current = Series.objects.create(name="Current series")
        donor = Series.objects.create(name="Provider series", tmdb_id="11")
        current_episode = Episode.objects.create(
            series=current, name="E1", season_number=1, episode_number=1
        )
        donor_episode = Episode.objects.create(
            series=donor, name="E1", season_number=1, episode_number=1
        )
        old_episode_id, old_episode_uuid = donor_episode.pk, donor_episode.uuid
        show_source = M3USeriesRelation.objects.create(
            series=donor, m3u_account=self.account, external_series_id="s1"
        )
        episode_source = M3UEpisodeRelation.objects.create(
            episode=donor_episode,
            series_relation=show_source,
            m3u_account=self.account,
            stream_id="e1",
            manual_metadata={"audio_languages": ["ger"]},
        )
        result, _ = handle_identity_conflicts(current, show_source, "11", None)
        self.assertEqual(result.pk, current.pk)
        episode_source.refresh_from_db()
        show_source.refresh_from_db()
        self.assertEqual(show_source.series_id, current.pk)
        self.assertEqual(episode_source.episode_id, current_episode.pk)
        self.assertEqual(episode_source.manual_metadata, {"audio_languages": ["ger"]})
        self.assertEqual(
            resolve_content("episode", old_episode_id)[0].pk, current_episode.pk
        )
        self.assertEqual(
            resolve_content("episode", old_episode_uuid, by_uuid=True)[0].pk,
            current_episode.pk,
        )

    def test_conflicting_external_ids_are_not_silently_merged(self):
        current = Movie.objects.create(name="A", tmdb_id="10")
        donor = Movie.objects.create(name="B", tmdb_id="20", imdb_id="tt20")
        with self.assertRaises(ValueError):
            handle_identity_conflicts(current, None, "10", "tt20")
        self.assertTrue(Movie.objects.filter(pk=donor.pk).exists())
        self.assertTrue(Movie.objects.filter(pk=current.pk).exists())

    def test_new_tmdb_id_reuses_an_existing_imdb_identity(self):
        current = Movie.objects.create(name="Film", imdb_id="tt123")
        self.movies(
            [
                {
                    "stream_id": 1,
                    "category_id": "1",
                    "name": "Film",
                    "tmdb_id": "123",
                    "imdb_id": "tt123",
                }
            ]
        )
        current.refresh_from_db()
        self.assertEqual(current.tmdb_id, "123")
        self.assertEqual(M3UMovieRelation.objects.get().movie_id, current.pk)

    def test_mixed_identifier_sources_in_one_batch_share_the_same_title(self):
        self.movies(
            [
                {
                    "stream_id": 1,
                    "category_id": "1",
                    "name": "Film",
                    "imdb_id": "tt123",
                },
                {
                    "stream_id": 2,
                    "category_id": "1",
                    "name": "Film",
                    "tmdb_id": "123",
                    "imdb_id": "tt123",
                },
            ]
        )
        self.assertEqual(Movie.objects.count(), 1)
        self.assertEqual(M3UMovieRelation.objects.count(), 2)
        self.assertEqual(Movie.objects.get().tmdb_id, "123")
