"""Category language is part of Movie/Series identity at ingest."""

from django.db import IntegrityError, transaction
from django.test import RequestFactory, SimpleTestCase, TestCase
from django.utils import timezone

from apps.accounts.models import User
from apps.m3u.models import M3UAccount
from apps.output.views import xc_get_series, xc_get_series_info
from apps.vod.language import category_language, validate_category_custom_properties
from apps.vod.models import (
    M3UMovieRelation,
    M3USeriesRelation,
    M3UVODCategoryRelation,
    Movie,
    Series,
    VODCategory,
)
from apps.vod.tasks import (
    handle_movie_id_conflicts,
    process_movie_batch,
    process_series_batch,
)


class ValidateCategoryCustomPropertiesTests(SimpleTestCase):
    def test_lowercases_language_and_keeps_other_keys(self):
        self.assertEqual(
            validate_category_custom_properties({"language": "ES", "other": 1}),
            {"language": "es", "other": 1},
        )

    def test_rejects_invalid_language(self):
        for value in ("spa", "e", 5, "e1"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_category_custom_properties({"language": value})

    def test_rejects_invalid_quality(self):
        with self.assertRaises(ValueError):
            validate_category_custom_properties({"quality": "8K"})

    def test_null_values_are_allowed(self):
        self.assertEqual(
            validate_category_custom_properties({"language": None, "quality": None}),
            {"language": None, "quality": None},
        )

    def test_category_language(self):
        self.assertEqual(category_language(None), "")
        self.assertEqual(
            category_language(M3UVODCategoryRelation(custom_properties=None)), ""
        )
        self.assertEqual(
            category_language(M3UVODCategoryRelation(custom_properties={"language": "ES"})),
            "es",
        )


class LanguageIdentityTestMixin:
    category_type = None

    def setUp(self):
        self.account = M3UAccount.objects.create(
            name="Lang XC",
            server_url="http://example.com",
            username="user",
            password="pass",
            account_type=M3UAccount.Types.XC,
            is_active=True,
            custom_properties={"enable_vod": True},
        )
        self.english = VODCategory.objects.create(name="English", category_type=self.category_type)
        self.spanish = VODCategory.objects.create(name="Spanish", category_type=self.category_type)
        self.english_rel = M3UVODCategoryRelation.objects.create(
            category=self.english, m3u_account=self.account, enabled=True,
        )
        self.spanish_rel = M3UVODCategoryRelation.objects.create(
            category=self.spanish,
            m3u_account=self.account,
            enabled=True,
            custom_properties={"language": "es"},
        )
        self.categories = {
            "1": self.english,
            "2": self.spanish,
            "__uncategorized__": self.english,
        }
        self.relations = {
            self.english.id: self.english_rel,
            self.spanish.id: self.spanish_rel,
        }


class MovieLanguageIdentityTests(LanguageIdentityTestMixin, TestCase):
    category_type = "movie"

    def _ingest(self, rows):
        process_movie_batch(
            self.account, rows, self.categories, self.relations,
            scan_start_time=timezone.now(),
        )

    def _row(self, stream_id, category_id, **extra):
        row = {
            "stream_id": stream_id,
            "name": "Shared Film",
            "category_id": category_id,
            "container_extension": "mkv",
        }
        row.update(extra)
        return row

    def test_same_tmdb_id_in_two_languages_creates_two_movies(self):
        self._ingest([
            self._row(1, "1", tmdb_id="100"),
            self._row(2, "2", tmdb_id="100"),
        ])

        english = Movie.objects.get(tmdb_id="100", language="")
        spanish = Movie.objects.get(tmdb_id="100", language="es")
        self.assertNotEqual(english.id, spanish.id)
        self.assertEqual(
            M3UMovieRelation.objects.get(stream_id="1").movie_id, english.id
        )
        self.assertEqual(
            M3UMovieRelation.objects.get(stream_id="2").movie_id, spanish.id
        )

    def test_repeated_refresh_does_not_duplicate_rows(self):
        rows = [
            self._row(1, "1", tmdb_id="100"),
            self._row(2, "2", tmdb_id="100"),
            self._row(3, "1", name="No Ids", year=2001),
            self._row(4, "2", name="No Ids", year=2001),
            self._row(5, "1", name="Imdb Only", imdb_id="tt5"),
            self._row(6, "2", name="Imdb Only", imdb_id="tt5"),
        ]
        self._ingest(rows)
        first_ids = set(Movie.objects.values_list("id", flat=True))
        self._ingest(rows)

        self.assertEqual(set(Movie.objects.values_list("id", flat=True)), first_ids)
        self.assertEqual(len(first_ids), 6)

    def test_same_language_from_two_streams_shares_one_movie(self):
        self._ingest([
            self._row(1, "2", tmdb_id="100"),
            self._row(2, "2", tmdb_id="100"),
        ])

        movie = Movie.objects.get(tmdb_id="100")
        self.assertEqual(movie.language, "es")
        self.assertEqual(movie.m3u_relations.count(), 2)

    def test_tagging_a_category_moves_its_streams_to_a_new_movie(self):
        self._ingest([
            self._row(1, "1", tmdb_id="100"),
            self._row(2, "1", tmdb_id="100"),
        ])
        original = Movie.objects.get(tmdb_id="100")
        M3UMovieRelation.objects.filter(stream_id="2").update(
            custom_properties={"detailed_fetched": True}
        )

        self.english_rel.custom_properties = {"language": "en"}
        self._ingest([
            self._row(1, "2", tmdb_id="100"),
            self._row(2, "1", tmdb_id="100"),
        ])

        # The untagged-to-tagged move produces a new id; the old id is untouched.
        relation_1 = M3UMovieRelation.objects.get(stream_id="1")
        relation_2 = M3UMovieRelation.objects.get(stream_id="2")
        self.assertEqual(relation_1.movie.language, "es")
        self.assertEqual(relation_2.movie.language, "en")
        self.assertNotEqual(relation_2.movie_id, original.id)
        self.assertTrue(Movie.objects.filter(id=original.id, language="").exists())
        self.assertFalse(relation_2.custom_properties["detailed_fetched"])

    def test_unique_constraints_are_per_language(self):
        Movie.objects.create(name="A", tmdb_id="7", imdb_id="tt7")
        Movie.objects.create(name="A", tmdb_id="7", imdb_id="tt7", language="es")
        Movie.objects.create(name="B", year=2000)
        Movie.objects.create(name="B", year=2000, language="es")
        for kwargs in (
            {"name": "A", "tmdb_id": "7"},
            {"name": "A", "imdb_id": "tt7"},
            {"name": "B", "year": 2000},
        ):
            with self.subTest(**kwargs), self.assertRaises(IntegrityError):
                with transaction.atomic():
                    Movie.objects.create(**kwargs)

    def test_id_conflict_merge_ignores_other_languages(self):
        spanish = Movie.objects.create(name="Film", tmdb_id="9", language="es")
        english = Movie.objects.create(name="Film")

        movie, _ = handle_movie_id_conflicts(english, None, "9", None)

        self.assertEqual(movie.id, english.id)
        self.assertTrue(Movie.objects.filter(id=spanish.id, tmdb_id="9").exists())


class SeriesLanguageIdentityTests(LanguageIdentityTestMixin, TestCase):
    category_type = "series"

    def _ingest(self, rows):
        process_series_batch(
            self.account, rows, self.categories, self.relations,
            scan_start_time=timezone.now(),
        )

    def test_same_tmdb_id_in_two_languages_creates_two_series(self):
        self._ingest([
            {"series_id": 1, "name": "Show", "category_id": "1", "tmdb_id": "200"},
            {"series_id": 2, "name": "Show", "category_id": "2", "tmdb_id": "200"},
        ])

        english = Series.objects.get(tmdb_id="200", language="")
        spanish = Series.objects.get(tmdb_id="200", language="es")
        self.assertEqual(
            M3USeriesRelation.objects.get(external_series_id="1").series_id, english.id
        )
        self.assertEqual(
            M3USeriesRelation.objects.get(external_series_id="2").series_id, spanish.id
        )

    def test_moved_relation_refetches_details_and_episodes(self):
        rows = [{"series_id": 1, "name": "Show", "category_id": "1", "tmdb_id": "200"}]
        self._ingest(rows)
        M3USeriesRelation.objects.filter(external_series_id="1").update(
            custom_properties={"detailed_fetched": True, "episodes_fetched": True}
        )

        self._ingest(rows)
        props = M3USeriesRelation.objects.get(external_series_id="1").custom_properties
        self.assertTrue(props["episodes_fetched"])

        self.english_rel.custom_properties = {"language": "en"}
        self._ingest(rows)
        relation = M3USeriesRelation.objects.get(external_series_id="1")
        self.assertEqual(relation.series.language, "en")
        self.assertFalse(relation.custom_properties["detailed_fetched"])
        self.assertFalse(relation.custom_properties["episodes_fetched"])


class XcSeriesPublishesSeriesIdTests(TestCase):
    def setUp(self):
        self.request = RequestFactory().get("/player_api.php")
        self.user = User.objects.create_user(
            username="xc-series-lang",
            password="pass",
            custom_properties={"xc_password": "xcpass"},
        )
        self.account = M3UAccount.objects.create(
            name="Series XC", server_url="http://example.com", is_active=True,
        )
        # Burn a few relation ids so relation and series ids diverge.
        filler = Series.objects.create(name="Filler")
        for i in range(3):
            M3USeriesRelation.objects.create(
                m3u_account=self.account, series=filler, external_series_id=f"f{i}",
            )
        self.english = Series.objects.create(name="Show", tmdb_id="300")
        self.spanish = Series.objects.create(name="Show", tmdb_id="300", language="es")
        for series, ext in ((self.english, "e"), (self.spanish, "s")):
            M3USeriesRelation.objects.create(
                m3u_account=self.account,
                series=series,
                external_series_id=ext,
                last_episode_refresh=timezone.now(),
                custom_properties={"episodes_fetched": True, "detailed_fetched": True},
            )

    def test_listing_publishes_series_ids(self):
        ids = {
            row["series_id"]
            for row in xc_get_series(self.request, self.user)
            if row["name"] == "Show"
        }
        self.assertEqual(ids, {self.english.id, self.spanish.id})

    def test_series_info_resolves_series_id(self):
        info = xc_get_series_info(self.request, self.user, str(self.spanish.id))
        self.assertEqual(info["info"]["name"], "Show")
        self.assertEqual(info["info"]["tmdb"], "300")

    def test_series_info_unknown_id_is_404(self):
        from django.http import Http404

        for series_id in ("999999", "not-a-number"):
            with self.subTest(series_id=series_id), self.assertRaises(Http404):
                xc_get_series_info(self.request, self.user, series_id)
