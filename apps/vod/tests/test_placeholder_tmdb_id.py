"""Placeholder TMDB IDs (e.g. '999999') must not merge unrelated VOD items."""

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from apps.m3u.models import M3UAccount
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
from apps.vod.tasks import (
    batch_process_episodes,
    cleanup_orphaned_vod_content,
    normalize_tmdb_id,
    process_movie_batch,
    process_series_batch,
    refresh_movie_advanced_data,
)


class NormalizeTmdbIdTests(SimpleTestCase):
    def test_rejects_missing_placeholder_and_non_scalar_values(self):
        for value in (
            None,
            "",
            "   ",
            0,
            "0",
            " 0 ",
            999999,
            "999999",
            " 999999 ",
            True,
            False,
            [],
            {},
            12.34,
        ):
            with self.subTest(value=value):
                self.assertIsNone(normalize_tmdb_id(value))

    def test_returns_stripped_string_for_valid_ids(self):
        self.assertEqual(normalize_tmdb_id("12345"), "12345")
        self.assertEqual(normalize_tmdb_id(" 12345 "), "12345")
        self.assertEqual(normalize_tmdb_id(12345), "12345")
        self.assertEqual(normalize_tmdb_id(999998), "999998")
        self.assertEqual(normalize_tmdb_id(1000000), "1000000")


class SeriesPlaceholderTmdbIdTests(TestCase):
    def setUp(self):
        self.account = M3UAccount.objects.create(
            name="Placeholder Series XC",
            server_url="http://example.com",
            username="user",
            password="pass",
            account_type=M3UAccount.Types.XC,
            is_active=True,
            custom_properties={"enable_vod": True},
        )
        self.category_a = VODCategory.objects.create(
            name="Series A", category_type="series",
        )
        self.category_b = VODCategory.objects.create(
            name="Series B", category_type="series",
        )
        self.relations = {
            self.category_a.id: M3UVODCategoryRelation.objects.create(
                category=self.category_a, m3u_account=self.account, enabled=True,
            ),
            self.category_b.id: M3UVODCategoryRelation.objects.create(
                category=self.category_b, m3u_account=self.account, enabled=True,
            ),
        }
        self.categories = {
            "20": self.category_a,
            "21": self.category_b,
            "__uncategorized__": self.category_a,
        }

    def _process(self, rows, scan_start_time=None):
        return process_series_batch(
            self.account,
            rows,
            self.categories,
            self.relations,
            scan_start_time=scan_start_time or timezone.now(),
        )

    def test_unrelated_series_with_placeholder_tmdb_id_do_not_merge(self):
        self._process([
            {"series_id": 101, "name": "Show Alpha", "releaseDate": "2020-01-01", "category_id": "20", "tmdb": "999999"},
            {"series_id": 102, "name": "Show Beta", "releaseDate": "2021-05-10", "category_id": "20", "tmdb": 999999},
            {"series_id": 103, "name": "Show Gamma", "releaseDate": "2022-03-01", "category_id": "21", "tmdb_id": " 999999 "},
        ])

        self.assertEqual(Series.objects.count(), 3)
        for name in ("Show Alpha", "Show Beta", "Show Gamma"):
            series = Series.objects.get(name=name)
            self.assertIsNone(series.tmdb_id)
        self.assertEqual(
            M3USeriesRelation.objects.filter(m3u_account=self.account).count(),
            3,
        )
        self.assertEqual(
            len(set(M3USeriesRelation.objects.values_list("series_id", flat=True))),
            3,
        )

    def test_placeholder_tmdb_id_falls_back_to_imdb_id(self):
        rows = [
            {"series_id": 201, "name": "Show One", "category_id": "20", "tmdb": "999999", "imdb": "tt1111111"},
            {"series_id": 202, "name": "Show Two", "category_id": "20", "tmdb": "999999", "imdb": "tt2222222"},
        ]
        self._process(rows)

        s1 = Series.objects.get(imdb_id="tt1111111")
        s2 = Series.objects.get(imdb_id="tt2222222")
        self.assertNotEqual(s1.id, s2.id)
        self.assertIsNone(s1.tmdb_id)
        self.assertIsNone(s2.tmdb_id)

        # Re-refresh matches the same rows by imdb_id without duplicating them.
        result = self._process(rows)
        self.assertEqual(Series.objects.count(), 2)
        self.assertIn("0 created, 0 updated", result)

    def test_placeholder_tmdb_id_falls_back_to_name_year_and_merges_same_title(self):
        self._process([
            {"series_id": 301, "name": "Same Show", "releaseDate": "2020-01-01", "category_id": "20", "tmdb": "999999"},
            {"series_id": 302, "name": "Same Show", "releaseDate": "2020-01-01", "category_id": "21", "tmdb": 999999},
            {"series_id": 303, "name": "Same Show", "releaseDate": "2022-01-01", "category_id": "20", "tmdb": "999999"},
        ])

        self.assertEqual(Series.objects.count(), 2)
        show_2020 = Series.objects.get(name="Same Show", year=2020)
        show_2022 = Series.objects.get(name="Same Show", year=2022)
        self.assertIsNone(show_2020.tmdb_id)
        self.assertIsNone(show_2022.tmdb_id)
        self.assertEqual(show_2020.m3u_relations.count(), 2)
        self.assertEqual(show_2022.m3u_relations.count(), 1)

    def test_placeholder_tmdb_falls_back_to_valid_tmdb_id_key(self):
        self._process([
            {"series_id": 401, "name": "Mixed Keys Show", "category_id": "20", "tmdb": "999999", "tmdb_id": "12345"},
        ])

        series = Series.objects.get(name="Mixed Keys Show")
        self.assertEqual(series.tmdb_id, "12345")

    def test_rerefresh_unmerges_existing_placeholder_series_and_cleans_up_orphan(self):
        polluted = Series.objects.create(
            name="Show Alpha", year=2020, tmdb_id="999999",
        )
        rel_a = M3USeriesRelation.objects.create(
            m3u_account=self.account,
            series=polluted,
            category=self.category_a,
            external_series_id="501",
            custom_properties={"detailed_fetched": True, "episodes_fetched": True},
        )
        rel_b = M3USeriesRelation.objects.create(
            m3u_account=self.account,
            series=polluted,
            category=self.category_b,
            external_series_id="502",
            custom_properties={"detailed_fetched": True, "episodes_fetched": True},
        )
        old_episode = Episode.objects.create(
            series=polluted, season_number=1, episode_number=1, name="Mixed Ep",
        )
        M3UEpisodeRelation.objects.create(
            m3u_account=self.account,
            episode=old_episode,
            series_relation=rel_a,
            stream_id="ep-501",
        )

        scan_time = timezone.now()
        self._process(
            [
                {"series_id": 501, "name": "Show Alpha", "releaseDate": "2020-01-01", "category_id": "20", "tmdb": "999999"},
                {"series_id": 502, "name": "Show Beta", "releaseDate": "2021-01-01", "category_id": "21", "tmdb": "999999"},
            ],
            scan_start_time=scan_time,
        )
        cleanup_orphaned_vod_content(account_id=self.account.id, scan_start_time=scan_time)

        self.assertFalse(Series.objects.filter(id=polluted.id).exists())
        self.assertFalse(Episode.objects.filter(id=old_episode.id).exists())
        self.assertFalse(M3UEpisodeRelation.objects.filter(stream_id="ep-501").exists())

        show_alpha = Series.objects.get(name="Show Alpha", year=2020)
        show_beta = Series.objects.get(name="Show Beta", year=2021)
        self.assertIsNone(show_alpha.tmdb_id)
        self.assertIsNone(show_beta.tmdb_id)

        rel_a.refresh_from_db()
        rel_b.refresh_from_db()
        self.assertEqual(rel_a.series_id, show_alpha.id)
        self.assertEqual(rel_b.series_id, show_beta.id)
        self.assertFalse(rel_a.custom_properties["detailed_fetched"])
        self.assertFalse(rel_a.custom_properties["episodes_fetched"])
        self.assertFalse(rel_b.custom_properties["detailed_fetched"])
        self.assertFalse(rel_b.custom_properties["episodes_fetched"])

    def test_valid_integer_and_string_tmdb_ids_still_deduplicate(self):
        rows = [
            {"series_id": 601, "name": "Real Show", "category_id": "20", "tmdb": 12345},
            {"series_id": 602, "name": "Real Show", "category_id": "21", "tmdb_id": " 12345 "},
        ]
        self._process(rows)

        self.assertEqual(Series.objects.count(), 1)
        series = Series.objects.get(tmdb_id="12345")
        self.assertEqual(series.m3u_relations.count(), 2)

        result = self._process(rows)
        self.assertIn("0 created, 0 updated", result)


class MoviePlaceholderTmdbIdTests(TestCase):
    def setUp(self):
        self.account = M3UAccount.objects.create(
            name="Placeholder Movie XC",
            server_url="http://example.com",
            username="user",
            password="pass",
            account_type=M3UAccount.Types.XC,
            is_active=True,
            custom_properties={"enable_vod": True},
        )
        self.category_a = VODCategory.objects.create(
            name="Movies A", category_type="movie",
        )
        self.category_b = VODCategory.objects.create(
            name="Movies B", category_type="movie",
        )
        self.relations = {
            self.category_a.id: M3UVODCategoryRelation.objects.create(
                category=self.category_a, m3u_account=self.account, enabled=True,
            ),
            self.category_b.id: M3UVODCategoryRelation.objects.create(
                category=self.category_b, m3u_account=self.account, enabled=True,
            ),
        }
        self.categories = {
            "10": self.category_a,
            "11": self.category_b,
            "__uncategorized__": self.category_a,
        }

    def _process(self, rows, scan_start_time=None):
        return process_movie_batch(
            self.account,
            rows,
            self.categories,
            self.relations,
            scan_start_time=scan_start_time or timezone.now(),
        )

    def test_unrelated_movies_with_placeholder_tmdb_id_do_not_merge(self):
        self._process([
            {"stream_id": 1001, "name": "Movie Alpha", "year": 2020, "category_id": "10", "tmdb_id": "999999"},
            {"stream_id": 1002, "name": "Movie Beta", "year": 2021, "category_id": "10", "tmdb": 999999},
            {"stream_id": 1003, "name": "Movie Gamma", "category_id": "11", "tmdb_id": " 999999 ", "imdb_id": "tt3333333"},
            {"stream_id": 1004, "name": "Movie Delta", "category_id": "11", "tmdb_id": "999999", "imdb_id": "tt4444444"},
        ])

        self.assertEqual(Movie.objects.count(), 4)
        for movie in Movie.objects.all():
            self.assertIsNone(movie.tmdb_id)
        self.assertEqual(Movie.objects.get(imdb_id="tt3333333").name, "Movie Gamma")
        self.assertEqual(Movie.objects.get(imdb_id="tt4444444").name, "Movie Delta")
        self.assertEqual(
            M3UMovieRelation.objects.filter(m3u_account=self.account).count(),
            4,
        )

    def test_rerefresh_unmerges_existing_placeholder_movie_and_cleans_up_orphan(self):
        polluted = Movie.objects.create(
            name="Movie Alpha", year=2020, tmdb_id="999999",
        )
        rel_a = M3UMovieRelation.objects.create(
            m3u_account=self.account,
            movie=polluted,
            category=self.category_a,
            stream_id="2001",
            custom_properties={"detailed_fetched": True},
        )
        rel_b = M3UMovieRelation.objects.create(
            m3u_account=self.account,
            movie=polluted,
            category=self.category_b,
            stream_id="2002",
            custom_properties={"detailed_fetched": True},
        )

        scan_time = timezone.now()
        self._process(
            [
                {"stream_id": 2001, "name": "Movie Alpha", "year": 2020, "category_id": "10", "tmdb_id": "999999"},
                {"stream_id": 2002, "name": "Movie Beta", "year": 2021, "category_id": "11", "tmdb_id": "999999"},
            ],
            scan_start_time=scan_time,
        )
        cleanup_orphaned_vod_content(account_id=self.account.id, scan_start_time=scan_time)

        self.assertFalse(Movie.objects.filter(id=polluted.id).exists())
        movie_alpha = Movie.objects.get(name="Movie Alpha", year=2020)
        movie_beta = Movie.objects.get(name="Movie Beta", year=2021)
        self.assertIsNone(movie_alpha.tmdb_id)
        self.assertIsNone(movie_beta.tmdb_id)

        rel_a.refresh_from_db()
        rel_b.refresh_from_db()
        self.assertEqual(rel_a.movie_id, movie_alpha.id)
        self.assertEqual(rel_b.movie_id, movie_beta.id)
        self.assertFalse(rel_a.custom_properties["detailed_fetched"])
        self.assertFalse(rel_b.custom_properties["detailed_fetched"])

    @patch("core.xtream_codes.Client")
    def test_refresh_movie_advanced_data_ignores_placeholder_tmdb_ids(self, mock_client_cls):
        movie_a = Movie.objects.create(name="Detail Film A", year=2020)
        movie_b = Movie.objects.create(name="Detail Film B", year=2021)
        rel_a = M3UMovieRelation.objects.create(
            m3u_account=self.account,
            movie=movie_a,
            category=self.category_a,
            stream_id="3001",
            custom_properties={"detailed_fetched": False},
        )
        rel_b = M3UMovieRelation.objects.create(
            m3u_account=self.account,
            movie=movie_b,
            category=self.category_b,
            stream_id="3002",
            custom_properties={"detailed_fetched": False},
        )

        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__.return_value = mock_client
        mock_client.get_vod_info.side_effect = [
            {
                "info": {"plot": "Plot A", "tmdb_id": "999999"},
                "movie_data": {"stream_id": 3001, "name": "Detail Film A"},
            },
            {
                "info": {"plot": "Plot B", "tmdb_id": "0"},
                "movie_data": {"stream_id": 3002, "name": "Detail Film B"},
            },
            {
                "info": {"plot": "Plot B updated", "tmdb_id": "999999"},
                "movie_data": {"stream_id": 3002, "name": "Detail Film B"},
            },
        ]

        self.assertEqual(refresh_movie_advanced_data(rel_a.id), "Advanced data refreshed.")
        self.assertEqual(refresh_movie_advanced_data(rel_b.id), "Advanced data refreshed.")
        self.assertEqual(
            refresh_movie_advanced_data(rel_b.id, force_refresh=True),
            "Advanced data refreshed.",
        )

        movie_a.refresh_from_db()
        movie_b.refresh_from_db()
        rel_a.refresh_from_db()
        rel_b.refresh_from_db()
        self.assertEqual(Movie.objects.count(), 2)
        self.assertIsNone(movie_a.tmdb_id)
        self.assertIsNone(movie_b.tmdb_id)
        self.assertEqual(rel_a.movie_id, movie_a.id)
        self.assertEqual(rel_b.movie_id, movie_b.id)
        self.assertTrue(rel_a.custom_properties["detailed_fetched"])
        self.assertTrue(rel_b.custom_properties["detailed_fetched"])


class EpisodePlaceholderTmdbIdTests(TestCase):
    def test_batch_process_episodes_normalizes_placeholder_tmdb_id(self):
        account = M3UAccount.objects.create(
            name="Episode TMDB XC",
            server_url="http://example.com",
            username="user",
            password="pass",
            account_type=M3UAccount.Types.XC,
            is_active=True,
            custom_properties={"enable_vod": True},
        )
        series = Series.objects.create(name="Episode TMDB Series")
        series_rel = M3USeriesRelation.objects.create(
            m3u_account=account, series=series, external_series_id="701",
        )

        batch_process_episodes(
            account,
            series,
            {
                "1": [
                    {
                        "id": "9001",
                        "title": "Ep 1",
                        "episode_num": 1,
                        "container_extension": "mp4",
                        "info": {"tmdb_id": "999999"},
                    },
                    {
                        "id": "9002",
                        "title": "Ep 2",
                        "episode_num": 2,
                        "container_extension": "mp4",
                        "info": {"tmdb_id": "0"},
                    },
                    {
                        "id": "9003",
                        "title": "Ep 3",
                        "episode_num": 3,
                        "container_extension": "mp4",
                        "info": {"tmdb_id": ""},
                    },
                    {
                        "id": "9004",
                        "title": "Ep 4",
                        "episode_num": 4,
                        "container_extension": "mp4",
                        "info": {"tmdb_id": 54321},
                    },
                ]
            },
            series_relation=series_rel,
        )

        by_num = {
            ep.episode_number: ep.tmdb_id
            for ep in Episode.objects.filter(series=series)
        }
        self.assertEqual(
            by_num,
            {1: None, 2: None, 3: None, 4: "54321"},
        )
