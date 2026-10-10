"""Category language is part of Movie/Series identity at ingest."""

from datetime import timedelta
from unittest.mock import patch

from django.db import IntegrityError, connection, transaction
from django.test import RequestFactory, SimpleTestCase, TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.accounts.models import User
from apps.m3u.models import M3UAccount
from apps.output.views import xc_get_series, xc_get_series_info
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
from apps.vod import tasks as vod_tasks
from apps.vod.tasks import (
    _language_reconcile_candidate_ids,
    _language_skip_note,
    handle_movie_id_conflicts,
    process_movie_batch,
    process_series_batch,
    reconcile_movie_language_identity,
    reconcile_series_language_identity,
)
from apps.vod.utils import category_language, validate_category_custom_properties, xc_language_suffix


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

    def test_rejects_non_object_custom_properties(self):
        for value in ('{"language": "es"}', 5, ["es"]):
            with self.subTest(value=value), self.assertRaises(ValueError) as ctx:
                validate_category_custom_properties(value)
            self.assertIn("must be an object", str(ctx.exception))

    def test_null_values_are_allowed(self):
        self.assertEqual(
            validate_category_custom_properties({"language": None, "quality": None}),
            {"language": None, "quality": None},
        )
        self.assertEqual(validate_category_custom_properties(None), {})

    def test_xc_language_suffix(self):
        self.assertEqual(xc_language_suffix("Show", ""), "Show")
        self.assertEqual(xc_language_suffix("Show", "es"), "Show [ES]")
        self.assertEqual(xc_language_suffix("Show [ES]", "es"), "Show [ES]")

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

    def _ingest(self, rows, scan_start_time=None):
        scan_start_time = scan_start_time or timezone.now()
        process_movie_batch(
            self.account, rows, self.categories, self.relations,
            scan_start_time=scan_start_time,
        )
        return scan_start_time

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

    def test_tagging_a_category_stays_pinned_until_reconciled(self):
        self._ingest([
            self._row(1, "1", tmdb_id="100"),
            self._row(2, "1", tmdb_id="100"),
        ])
        original = Movie.objects.get(tmdb_id="100")
        M3UMovieRelation.objects.filter(stream_id="2").update(
            custom_properties={"detailed_fetched": True}
        )

        self.english_rel.custom_properties = {"language": "en"}
        self.english_rel.save()
        scan_time = self._ingest([
            self._row(1, "2", tmdb_id="100"),
            self._row(2, "1", tmdb_id="100"),
        ])

        # No fork mid-batch: both relations stay pinned to the original,
        # still-untagged movie even though stream 1's category changed and
        # stream 2's category was retagged.
        relation_1 = M3UMovieRelation.objects.get(stream_id="1")
        relation_2 = M3UMovieRelation.objects.get(stream_id="2")
        self.assertEqual(relation_1.movie_id, original.id)
        self.assertEqual(relation_2.movie_id, original.id)
        self.assertTrue(relation_2.custom_properties["detailed_fetched"])

        reconcile_movie_language_identity(self.account, scan_start_time=scan_time)

        relation_1.refresh_from_db()
        relation_2.refresh_from_db()
        original.refresh_from_db()
        # Tie on group size keeps 'es' (later language code) on the original id.
        self.assertEqual(original.language, "es")
        self.assertEqual(relation_1.movie_id, original.id)
        self.assertEqual(relation_2.movie.language, "en")
        self.assertNotEqual(relation_2.movie_id, original.id)
        self.assertFalse(relation_2.custom_properties["detailed_fetched"])

    def test_reconcile_updates_language_in_place_when_no_target_exists(self):
        self._ingest([self._row(1, "1", tmdb_id="100")])
        original = Movie.objects.get(tmdb_id="100")

        self.english_rel.custom_properties = {"language": "en"}
        self.english_rel.save()
        scan_time = self._ingest([self._row(1, "1", tmdb_id="100")])

        reconcile_movie_language_identity(self.account, scan_start_time=scan_time)

        original.refresh_from_db()
        self.assertEqual(original.language, "en")
        self.assertEqual(M3UMovieRelation.objects.get(stream_id="1").movie_id, original.id)

    def test_reconcile_keeps_original_id_when_language_row_exists(self):
        existing_target = Movie.objects.create(
            name="Shared Film", tmdb_id="100", language="en", description="from the newer row",
        )
        self._ingest([self._row(1, "1", tmdb_id="100")])
        original = Movie.objects.get(tmdb_id="100", language="")

        self.english_rel.custom_properties = {"language": "en"}
        self.english_rel.save()
        scan_time = self._ingest([self._row(1, "1", tmdb_id="100")])

        reconcile_movie_language_identity(self.account, scan_start_time=scan_time)

        original.refresh_from_db()
        relation = M3UMovieRelation.objects.get(stream_id="1")
        self.assertEqual(relation.movie_id, original.id)
        self.assertEqual(original.language, "en")
        self.assertEqual(original.description, "from the newer row")
        self.assertFalse(Movie.objects.filter(id=existing_target.id).exists())

    def test_new_stream_joins_untagged_movie(self):
        self._ingest([self._row(1, "1", tmdb_id="100")])
        original = Movie.objects.get(tmdb_id="100")
        self.english_rel.custom_properties = {"language": "en"}
        self.english_rel.save()

        self._ingest([
            self._row(1, "1", tmdb_id="100"),
            self._row(2, "1", tmdb_id="100"),
        ])

        self.assertEqual(Movie.objects.filter(tmdb_id="100").count(), 1)
        self.assertEqual(M3UMovieRelation.objects.get(stream_id="2").movie_id, original.id)

    def test_reconcile_leaves_untagged_group_on_source(self):
        french = VODCategory.objects.create(name="French", category_type="movie")
        french_rel = M3UVODCategoryRelation.objects.create(
            category=french, m3u_account=self.account, enabled=True,
        )
        self.categories["3"] = french
        self.relations[french.id] = french_rel

        self._ingest([
            self._row(1, "1", tmdb_id="100"),
            self._row(2, "3", tmdb_id="100"),
        ])
        original = Movie.objects.get(tmdb_id="100")

        self.english_rel.custom_properties = {"language": "en"}
        self.english_rel.save()
        scan_time = self._ingest([
            self._row(1, "1", tmdb_id="100"),
            self._row(2, "3", tmdb_id="100"),
        ])

        reconcile_movie_language_identity(self.account, scan_start_time=scan_time)

        relation_1 = M3UMovieRelation.objects.get(stream_id="1")
        relation_2 = M3UMovieRelation.objects.get(stream_id="2")
        self.assertEqual(relation_1.movie.language, "en")
        self.assertNotEqual(relation_1.movie_id, original.id)
        self.assertEqual(relation_2.movie_id, original.id)
        self.assertTrue(Movie.objects.filter(id=original.id, language="").exists())

    def test_reconcile_considers_other_accounts_relations(self):
        other_account = M3UAccount.objects.create(
            name="Other XC", server_url="http://example.com", username="u2", password="p2",
            account_type=M3UAccount.Types.XC, is_active=True,
        )
        other_category = VODCategory.objects.create(name="Other English", category_type="movie")
        M3UVODCategoryRelation.objects.create(
            category=other_category, m3u_account=other_account, enabled=True,
            custom_properties={"language": "en"},
        )

        self._ingest([self._row(1, "1", tmdb_id="100")])
        original = Movie.objects.get(tmdb_id="100")

        M3UMovieRelation.objects.create(
            m3u_account=other_account, movie=original, category=other_category,
            stream_id="other-1", last_seen=timezone.now() - timedelta(days=1),
        )

        self.english_rel.custom_properties = {"language": "en"}
        self.english_rel.save()
        scan_time = self._ingest([self._row(1, "1", tmdb_id="100")])

        reconcile_movie_language_identity(self.account, scan_start_time=scan_time)

        original.refresh_from_db()
        self.assertEqual(original.language, "en")
        self.assertTrue(
            M3UMovieRelation.objects.filter(stream_id="other-1", movie=original).exists()
        )

    def test_reconcile_retags_already_tagged_movies(self):
        self._ingest([self._row(1, "2", tmdb_id="100")])
        spanish_movie = Movie.objects.get(tmdb_id="100", language="es")

        self.spanish_rel.custom_properties = {"language": "fr"}
        self.spanish_rel.save()
        scan_time = self._ingest([self._row(1, "2", tmdb_id="100")])

        reconcile_movie_language_identity(self.account, scan_start_time=scan_time)

        spanish_movie.refresh_from_db()
        self.assertEqual(spanish_movie.language, "fr")
        self.assertEqual(
            M3UMovieRelation.objects.get(stream_id="1").movie_id, spanish_movie.id
        )

    def test_reconcile_absorb_does_not_keep_retagged_relations(self):
        other = M3UAccount.objects.create(
            name="Other XC", server_url="http://example.com", username="u2", password="p2",
            account_type=M3UAccount.Types.XC, is_active=True,
        )
        newly = VODCategory.objects.create(name="Newly ES", category_type="movie")
        retagged = VODCategory.objects.create(name="Now FR", category_type="movie")
        still = VODCategory.objects.create(name="Still ES", category_type="movie")
        M3UVODCategoryRelation.objects.create(
            category=newly, m3u_account=self.account, enabled=True,
            custom_properties={"language": "es"},
        )
        M3UVODCategoryRelation.objects.create(
            category=retagged, m3u_account=self.account, enabled=True,
            custom_properties={"language": "fr"},
        )
        M3UVODCategoryRelation.objects.create(
            category=still, m3u_account=other, enabled=True,
            custom_properties={"language": "es"},
        )
        untagged = Movie.objects.create(name="Shared Film", tmdb_id="100", language="")
        spanish = Movie.objects.create(name="Shared Film", tmdb_id="100", language="es")
        now = timezone.now()
        M3UMovieRelation.objects.create(
            m3u_account=self.account, movie=untagged, category=newly,
            stream_id="new-es", last_seen=now,
        )
        M3UMovieRelation.objects.create(
            m3u_account=self.account, movie=spanish, category=retagged,
            stream_id="now-fr", last_seen=now,
        )
        M3UMovieRelation.objects.create(
            m3u_account=other, movie=spanish, category=still,
            stream_id="still-es", last_seen=now,
        )

        reconcile_movie_language_identity(self.account, scan_start_time=now)

        untagged.refresh_from_db()
        self.assertEqual(untagged.language, "es")
        self.assertFalse(Movie.objects.filter(id=spanish.id).exists())
        self.assertEqual(
            M3UMovieRelation.objects.get(stream_id="new-es").movie_id, untagged.id
        )
        self.assertEqual(
            M3UMovieRelation.objects.get(stream_id="still-es").movie_id, untagged.id
        )
        french_rel = M3UMovieRelation.objects.get(stream_id="now-fr")
        self.assertEqual(french_rel.movie.language, "fr")
        self.assertNotEqual(french_rel.movie_id, untagged.id)
        self.assertEqual(M3UMovieRelation.objects.count(), 3)

    def test_reconcile_detaches_cleared_category_language(self):
        self._ingest([
            self._row(1, "2", tmdb_id="100"),
            self._row(2, "2", tmdb_id="100"),
        ])
        original = Movie.objects.get(tmdb_id="100", language="es")
        cleared = VODCategory.objects.create(name="Cleared", category_type="movie")
        M3UVODCategoryRelation.objects.create(
            category=cleared, m3u_account=self.account, enabled=True,
        )
        M3UMovieRelation.objects.filter(stream_id="2").update(category=cleared)
        scan_time = timezone.now()
        M3UMovieRelation.objects.filter(m3u_account=self.account).update(last_seen=scan_time)

        reconcile_movie_language_identity(self.account, scan_start_time=scan_time)

        original.refresh_from_db()
        self.assertEqual(original.language, "es")
        self.assertEqual(
            M3UMovieRelation.objects.get(stream_id="1").movie_id, original.id
        )
        detached = M3UMovieRelation.objects.get(stream_id="2")
        self.assertNotEqual(detached.movie_id, original.id)
        self.assertEqual(detached.movie.language, "")

    def test_reconcile_clear_absorbs_existing_untagged_row(self):
        other = M3UAccount.objects.create(
            name="Other XC", server_url="http://example.com", username="u2", password="p2",
            account_type=M3UAccount.Types.XC, is_active=True,
        )
        plain = VODCategory.objects.create(name="Plain", category_type="movie")
        M3UVODCategoryRelation.objects.create(
            category=plain, m3u_account=other, enabled=True,
        )
        spanish = Movie.objects.create(name="Shared Film", tmdb_id="100", language="es")
        untagged = Movie.objects.create(
            name="Shared Film", tmdb_id="100", language="", description="kept",
        )
        now = timezone.now()
        M3UMovieRelation.objects.create(
            m3u_account=self.account, movie=spanish, category=self.spanish,
            stream_id="was-es", last_seen=now,
        )
        M3UMovieRelation.objects.create(
            m3u_account=other, movie=untagged, category=plain,
            stream_id="plain", last_seen=now,
        )
        self.spanish_rel.custom_properties = {}
        self.spanish_rel.save()

        reconcile_movie_language_identity(self.account, scan_start_time=now)

        spanish.refresh_from_db()
        self.assertEqual(spanish.language, "")
        self.assertEqual(spanish.description, "kept")
        self.assertFalse(Movie.objects.filter(id=untagged.id).exists())
        self.assertEqual(
            M3UMovieRelation.objects.get(stream_id="was-es").movie_id, spanish.id
        )
        self.assertEqual(
            M3UMovieRelation.objects.get(stream_id="plain").movie_id, spanish.id
        )

    def test_candidate_scan_matches_category_language_in_sql(self):
        matching = Movie.objects.create(name="Match", tmdb_id="100", language="es")
        mismatched = Movie.objects.create(name="Mismatch", tmdb_id="200", language="es")
        stale = Movie.objects.create(name="Stale", tmdb_id="300", language="es")
        untagged_plain = Movie.objects.create(name="Plain", tmdb_id="400", language="")
        untagged_tagged_cat = Movie.objects.create(name="Join", tmdb_id="500", language="")
        now = timezone.now()
        self.spanish_rel.custom_properties = {"language": "ES"}
        self.spanish_rel.save()
        french = VODCategory.objects.create(name="French SQL", category_type="movie")
        M3UVODCategoryRelation.objects.create(
            category=french, m3u_account=self.account, enabled=True,
            custom_properties={"language": "fr"},
        )
        M3UMovieRelation.objects.create(
            m3u_account=self.account, movie=matching, category=self.spanish,
            stream_id="match", last_seen=now,
        )
        M3UMovieRelation.objects.create(
            m3u_account=self.account, movie=mismatched, category=french,
            stream_id="mismatch", last_seen=now,
        )
        M3UMovieRelation.objects.create(
            m3u_account=self.account, movie=stale, category=french,
            stream_id="stale", last_seen=now - timedelta(days=2),
        )
        M3UMovieRelation.objects.create(
            m3u_account=self.account, movie=untagged_plain, category=self.english,
            stream_id="plain", last_seen=now,
        )
        M3UMovieRelation.objects.create(
            m3u_account=self.account, movie=untagged_tagged_cat, category=french,
            stream_id="join", last_seen=now,
        )

        ids = _language_reconcile_candidate_ids(
            self.account, now, relation_model=M3UMovieRelation, fk_name="movie",
        )

        self.assertEqual(ids, {mismatched.id, untagged_tagged_cat.id})

    def test_reconcile_is_cheap_when_no_language_work(self):
        now = timezone.now()
        movies = Movie.objects.bulk_create([
            Movie(name=f"Film {i}", tmdb_id=str(1000 + i)) for i in range(50)
        ])
        M3UMovieRelation.objects.bulk_create([
            M3UMovieRelation(
                m3u_account=self.account,
                movie=movie,
                category=self.english,
                stream_id=f"cheap-{i}",
                last_seen=now,
            )
            for i, movie in enumerate(movies)
        ])

        with CaptureQueriesContext(connection) as ctx:
            result = reconcile_movie_language_identity(self.account, scan_start_time=now)

        self.assertIn("No movies needed language reconcile this refresh", result)
        # One candidate-id scan, nothing else. Must stay O(1) in catalog size.
        self.assertLessEqual(len(ctx), 3)

    def test_mass_retag_stays_a_bulk_update(self):
        self.english_rel.custom_properties = {"language": "es"}
        self.english_rel.save()
        now = timezone.now()
        movies = Movie.objects.bulk_create([
            Movie(name=f"Bulk {i}", tmdb_id=str(3000 + i)) for i in range(50)
        ])
        M3UMovieRelation.objects.bulk_create([
            M3UMovieRelation(
                m3u_account=self.account,
                movie=movie,
                category=self.english,
                stream_id=f"bulk-{i}",
                last_seen=now,
            )
            for i, movie in enumerate(movies)
        ])

        with CaptureQueriesContext(connection) as ctx:
            result = reconcile_movie_language_identity(self.account, scan_start_time=now)

        self.assertIn("50 updated in place", result)
        self.assertEqual(Movie.objects.filter(language="es").count(), 50)
        # Candidate scan, one relation load, one category load, one identity
        # load, one bulk_update. Must not grow a query per title.
        self.assertLess(len(ctx), 20)

    def test_retag_keeps_both_ids_when_untagged_row_is_tagged(self):
        # The untagged row is created first, then the es row. Both orders
        # must keep both ids: the es row's streams now want fr, so it is not
        # a duplicate es row to absorb.
        for untagged_first in (True, False):
            with self.subTest(untagged_first=untagged_first):
                self._assert_retag_keeps_both_ids(untagged_first=untagged_first)

    def _assert_retag_keeps_both_ids(self, *, untagged_first):
        newly = VODCategory.objects.create(name=f"Newly {untagged_first}", category_type="movie")
        now_fr = VODCategory.objects.create(name=f"Now FR {untagged_first}", category_type="movie")
        M3UVODCategoryRelation.objects.create(
            category=newly, m3u_account=self.account, enabled=True,
            custom_properties={"language": "es"},
        )
        M3UVODCategoryRelation.objects.create(
            category=now_fr, m3u_account=self.account, enabled=True,
            custom_properties={"language": "fr"},
        )
        tmdb_id = "untagged-first" if untagged_first else "tagged-first"
        first = Movie.objects.create(name="Shared Film", tmdb_id=tmdb_id, language="" if untagged_first else "es")
        second = Movie.objects.create(name="Shared Film", tmdb_id=tmdb_id, language="es" if untagged_first else "")
        untagged = first if untagged_first else second
        spanish = second if untagged_first else first
        now = timezone.now()
        M3UMovieRelation.objects.create(
            m3u_account=self.account, movie=untagged, category=newly,
            stream_id=f"new-es-{untagged_first}", last_seen=now,
        )
        M3UMovieRelation.objects.create(
            m3u_account=self.account, movie=spanish, category=now_fr,
            stream_id=f"now-fr-{untagged_first}", last_seen=now,
        )

        reconcile_movie_language_identity(self.account, scan_start_time=now)

        untagged.refresh_from_db()
        spanish.refresh_from_db()
        self.assertEqual(untagged.language, "es")
        self.assertEqual(spanish.language, "fr")
        self.assertEqual(M3UMovieRelation.objects.get(stream_id=f"new-es-{untagged_first}").movie_id, untagged.id)
        self.assertEqual(M3UMovieRelation.objects.get(stream_id=f"now-fr-{untagged_first}").movie_id, spanish.id)

    def test_swapped_languages_keep_both_ids(self):
        cleared = VODCategory.objects.create(name="Cleared swap", category_type="movie")
        M3UVODCategoryRelation.objects.create(
            category=cleared, m3u_account=self.account, enabled=True,
        )
        spanish = Movie.objects.create(name="Shared Film", tmdb_id="swap", language="es")
        untagged = Movie.objects.create(name="Shared Film", tmdb_id="swap", language="")
        now = timezone.now()
        M3UMovieRelation.objects.create(
            m3u_account=self.account, movie=spanish, category=cleared,
            stream_id="swap-clear", last_seen=now,
        )
        M3UMovieRelation.objects.create(
            m3u_account=self.account, movie=untagged, category=self.spanish,
            stream_id="swap-es", last_seen=now,
        )

        reconcile_movie_language_identity(self.account, scan_start_time=now)

        spanish.refresh_from_db()
        untagged.refresh_from_db()
        self.assertEqual(spanish.language, "")
        self.assertEqual(untagged.language, "es")
        self.assertEqual(M3UMovieRelation.objects.get(stream_id="swap-clear").movie_id, spanish.id)
        self.assertEqual(M3UMovieRelation.objects.get(stream_id="swap-es").movie_id, untagged.id)

    def test_leaving_language_runs_before_arriving_without_parking(self):
        # One row leaves es for fr. Another arrives at es from untagged. The
        # leaver frees the slot, so neither creation order needs a spare code.
        for leaving_first in (True, False):
            with self.subTest(leaving_first=leaving_first):
                french = VODCategory.objects.create(
                    name=f"FR leave {leaving_first}", category_type="movie",
                )
                M3UVODCategoryRelation.objects.create(
                    category=french, m3u_account=self.account, enabled=True,
                    custom_properties={"language": "fr"},
                )
                tmdb_id = f"leave-{leaving_first}"
                if leaving_first:
                    leaving = Movie.objects.create(name="Amelie", tmdb_id=tmdb_id, language="es")
                    arriving = Movie.objects.create(name="Amelie", tmdb_id=tmdb_id, language="")
                else:
                    arriving = Movie.objects.create(name="Amelie", tmdb_id=tmdb_id, language="")
                    leaving = Movie.objects.create(name="Amelie", tmdb_id=tmdb_id, language="es")
                now = timezone.now()
                M3UMovieRelation.objects.create(
                    m3u_account=self.account, movie=leaving, category=french,
                    stream_id=f"leave-{leaving_first}", last_seen=now,
                )
                M3UMovieRelation.objects.create(
                    m3u_account=self.account, movie=arriving, category=self.spanish,
                    stream_id=f"arrive-{leaving_first}", last_seen=now,
                )
                parks = []
                real_park = vod_tasks._park_language

                def watch_park(*args, **kwargs):
                    parks.append(1)
                    return real_park(*args, **kwargs)

                with patch("apps.vod.tasks._park_language", watch_park):
                    reconcile_movie_language_identity(self.account, scan_start_time=now)

                leaving.refresh_from_db()
                arriving.refresh_from_db()
                self.assertEqual(leaving.language, "fr")
                self.assertEqual(arriving.language, "es")
                self.assertEqual(parks, [])

    def test_partial_overlap_hands_off_only_languages_with_a_home(self):
        french = VODCategory.objects.create(name="French Partial", category_type="movie")
        M3UVODCategoryRelation.objects.create(
            category=french, m3u_account=self.account, enabled=True,
            custom_properties={"language": "fr"},
        )
        home_es = Movie.objects.create(name="Partial", tmdb_id="partial", language="es")
        src = Movie.objects.create(name="Partial", tmdb_id="partial", language="")
        now = timezone.now()
        M3UMovieRelation.objects.create(
            m3u_account=self.account, movie=home_es, category=self.spanish,
            stream_id="home-es", last_seen=now - timedelta(days=1),
        )
        for stream_id in ("src-es-1", "src-es-2"):
            M3UMovieRelation.objects.create(
                m3u_account=self.account, movie=src, category=self.spanish,
                stream_id=stream_id, last_seen=now,
            )
        M3UMovieRelation.objects.create(
            m3u_account=self.account, movie=src, category=french,
            stream_id="src-fr", last_seen=now,
        )

        reconcile_movie_language_identity(self.account, scan_start_time=now)

        src.refresh_from_db()
        home_es.refresh_from_db()
        self.assertEqual(src.language, "fr")
        self.assertEqual(home_es.language, "es")
        self.assertEqual(
            set(M3UMovieRelation.objects.filter(movie=home_es).values_list("stream_id", flat=True)),
            {"home-es", "src-es-1", "src-es-2"},
        )
        self.assertEqual(
            M3UMovieRelation.objects.get(stream_id="src-fr").movie_id, src.id
        )
        again = reconcile_movie_language_identity(self.account, scan_start_time=now)
        self.assertIn("No movies needed language reconcile this refresh", again)

    def test_one_title_failing_does_not_skip_the_rest(self):
        from apps.vod import tasks as vod_tasks

        self.english_rel.custom_properties = {"language": "en"}
        self.english_rel.save()
        now = timezone.now()
        good = Movie.objects.create(name="Good Film", tmdb_id="good")
        bad = Movie.objects.create(name="Bad Film", tmdb_id="bad")
        for movie, stream_id in ((good, "good-en"), (bad, "bad-en")):
            M3UMovieRelation.objects.create(
                m3u_account=self.account, movie=movie, category=self.english,
                stream_id=stream_id, last_seen=now,
            )
            M3UMovieRelation.objects.create(
                m3u_account=self.account, movie=movie, category=self.spanish,
                stream_id=stream_id.replace("en", "es"), last_seen=now,
            )
        real = vod_tasks._reconcile_one

        def wrapped(ctx, source, run):
            if source.tmdb_id == "bad":
                raise RuntimeError("boom")
            return real(ctx, source, run)

        with patch("apps.vod.tasks._reconcile_one", wrapped):
            result = reconcile_movie_language_identity(self.account, scan_start_time=now)

        self.assertIn("1 title skipped", result)
        good.refresh_from_db()
        bad.refresh_from_db()
        self.assertEqual(good.language, "es")
        self.assertEqual(bad.language, "")

    def test_mixed_row_does_not_absorb_clean_language_row(self):
        french = VODCategory.objects.create(name="French Mixed", category_type="movie")
        M3UVODCategoryRelation.objects.create(
            category=french, m3u_account=self.account, enabled=True,
            custom_properties={"language": "fr"},
        )
        mono = Movie.objects.create(name="Shared Film", tmdb_id="mix", language="")
        mixed = Movie.objects.create(name="Shared Film", tmdb_id="mix", language="de")
        now = timezone.now()
        M3UMovieRelation.objects.create(
            m3u_account=self.account, movie=mono, category=self.spanish,
            stream_id="mono-es", last_seen=now,
        )
        for stream_id in ("mixed-es-1", "mixed-es-2"):
            M3UMovieRelation.objects.create(
                m3u_account=self.account, movie=mixed, category=self.spanish,
                stream_id=stream_id, last_seen=now,
            )
        M3UMovieRelation.objects.create(
            m3u_account=self.account, movie=mixed, category=french,
            stream_id="mixed-fr", last_seen=now,
        )

        reconcile_movie_language_identity(self.account, scan_start_time=now)

        mono.refresh_from_db()
        mixed.refresh_from_db()
        self.assertEqual(mono.language, "es")
        self.assertEqual(mixed.language, "fr")
        self.assertEqual(
            set(M3UMovieRelation.objects.filter(movie=mono).values_list("stream_id", flat=True)),
            {"mono-es", "mixed-es-1", "mixed-es-2"},
        )
        self.assertEqual(
            M3UMovieRelation.objects.get(stream_id="mixed-fr").movie_id, mixed.id
        )

    def test_hand_off_finishes_past_six_languages(self):
        codes = ("de", "en", "es", "fr", "it", "pt")
        categories = {}
        homes = {}
        for code in codes:
            category = VODCategory.objects.create(name=f"Lang {code}", category_type="movie")
            M3UVODCategoryRelation.objects.create(
                category=category, m3u_account=self.account, enabled=True,
                custom_properties={"language": code},
            )
            categories[code] = category
            homes[code] = Movie.objects.create(name="Wide Film", tmdb_id="wide", language=code)
        mixed = Movie.objects.create(name="Wide Film", tmdb_id="wide", language="xx")
        now = timezone.now()
        for code in codes:
            M3UMovieRelation.objects.create(
                m3u_account=self.account, movie=homes[code], category=categories[code],
                stream_id=f"home-{code}", last_seen=now - timedelta(days=1),
            )
            M3UMovieRelation.objects.create(
                m3u_account=self.account, movie=mixed, category=categories[code],
                stream_id=f"mixed-{code}", last_seen=now,
            )

        result = reconcile_movie_language_identity(self.account, scan_start_time=now)

        mixed.refresh_from_db()
        self.assertNotIn("skipped", result)
        # Every group is the same size, so the latest code stays on this id
        # and that code's existing row is the duplicate that gets absorbed.
        self.assertEqual(mixed.language, "pt")
        self.assertFalse(Movie.objects.filter(id=homes["pt"].id).exists())
        for code in codes:
            relation = M3UMovieRelation.objects.get(stream_id=f"mixed-{code}")
            if code == "pt":
                self.assertEqual(relation.movie_id, mixed.id)
            else:
                self.assertEqual(relation.movie_id, homes[code].id)
                self.assertTrue(Movie.objects.filter(id=homes[code].id, language=code).exists())

        again = reconcile_movie_language_identity(self.account, scan_start_time=now)
        self.assertIn("No movies needed language reconcile this refresh", again)

    def test_imdb_collision_is_absorbed_instead_of_skipped(self):
        holder = Movie.objects.create(
            name="Other Cut", tmdb_id="2", imdb_id="tt-share", language="es",
        )
        incoming = Movie.objects.create(
            name="This Cut", tmdb_id="1", imdb_id="tt-share", language="",
        )
        now = timezone.now()
        M3UMovieRelation.objects.create(
            m3u_account=self.account, movie=holder, category=self.spanish,
            stream_id="holder-es", last_seen=now - timedelta(days=1),
        )
        M3UMovieRelation.objects.create(
            m3u_account=self.account, movie=incoming, category=self.spanish,
            stream_id="incoming-es", last_seen=now,
        )

        result = reconcile_movie_language_identity(self.account, scan_start_time=now)

        incoming.refresh_from_db()
        self.assertNotIn("skipped", result)
        self.assertEqual(incoming.language, "es")
        self.assertFalse(Movie.objects.filter(id=holder.id).exists())
        self.assertEqual(
            set(M3UMovieRelation.objects.values_list("movie_id", flat=True)),
            {incoming.id},
        )

    def test_reconcile_retags_absorbs_existing_language_row(self):
        self._ingest([self._row(1, "2", tmdb_id="100")])
        spanish_movie = Movie.objects.get(tmdb_id="100", language="es")
        french_movie = Movie.objects.create(
            name="Shared Film", tmdb_id="100", language="fr", description="kept",
        )

        self.spanish_rel.custom_properties = {"language": "fr"}
        self.spanish_rel.save()
        scan_time = self._ingest([self._row(1, "2", tmdb_id="100")])

        reconcile_movie_language_identity(self.account, scan_start_time=scan_time)

        spanish_movie.refresh_from_db()
        self.assertEqual(spanish_movie.language, "fr")
        self.assertEqual(spanish_movie.description, "kept")
        self.assertEqual(
            M3UMovieRelation.objects.get(stream_id="1").movie_id, spanish_movie.id
        )
        self.assertFalse(Movie.objects.filter(id=french_movie.id).exists())

    def test_new_name_year_stream_joins_untagged_movie(self):
        self._ingest([self._row(1, "1", name="No Ids", year=2001)])
        original = Movie.objects.get(name="No Ids", year=2001)
        self.english_rel.custom_properties = {"language": "en"}
        self.english_rel.save()

        self._ingest([
            self._row(1, "1", name="No Ids", year=2001),
            self._row(2, "1", name="No Ids", year=2001),
        ])

        self.assertEqual(Movie.objects.filter(name="No Ids", year=2001).count(), 1)
        self.assertEqual(
            M3UMovieRelation.objects.get(stream_id="2").movie_id, original.id
        )

    def test_reconcile_is_idempotent(self):
        self._ingest([
            self._row(1, "1", tmdb_id="100"),
            self._row(2, "1", tmdb_id="100"),
        ])
        self.english_rel.custom_properties = {"language": "en"}
        self.english_rel.save()
        scan_time = self._ingest([
            self._row(1, "1", tmdb_id="100"),
            self._row(2, "1", tmdb_id="100"),
        ])

        reconcile_movie_language_identity(self.account, scan_start_time=scan_time)
        state_after_first = list(
            M3UMovieRelation.objects.order_by("stream_id").values("stream_id", "movie_id")
        )

        result = reconcile_movie_language_identity(self.account, scan_start_time=scan_time)

        self.assertEqual(
            list(M3UMovieRelation.objects.order_by("stream_id").values("stream_id", "movie_id")),
            state_after_first,
        )
        self.assertIn("No movies needed language reconcile this refresh", result)

    def test_reconcile_skips_movies_not_touched_this_scan(self):
        self._ingest([self._row(1, "1", tmdb_id="100")])
        original = Movie.objects.get(tmdb_id="100")

        self.english_rel.custom_properties = {"language": "en"}
        self.english_rel.save()
        scan_time = timezone.now()

        reconcile_movie_language_identity(self.account, scan_start_time=scan_time)

        original.refresh_from_db()
        self.assertEqual(original.language, "")

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


class LanguageSkipNoteTests(SimpleTestCase):
    def test_names_kind_and_count(self):
        movie = (
            "Movie language reconcile: 0 updated in place, 0 relations moved, "
            "0 existing language rows absorbed, 1 title skipped"
        )
        series = (
            "Series language reconcile: 1 updated in place, 0 relations moved, "
            "0 existing language rows absorbed, 2 titles skipped"
        )
        self.assertEqual(
            _language_skip_note(movie, "No series needed language reconcile this refresh."),
            ". 1 movie title skipped during language reconcile",
        )
        self.assertEqual(
            _language_skip_note("No movies needed language reconcile this refresh.", series),
            ". 2 series titles skipped during language reconcile",
        )
        self.assertEqual(
            _language_skip_note(movie, series),
            ". 1 movie title skipped during language reconcile. "
            "2 series titles skipped during language reconcile",
        )
        self.assertEqual(
            _language_skip_note(
                "No movies needed language reconcile this refresh.",
                "No series needed language reconcile this refresh.",
            ),
            "",
        )


class SeriesLanguageIdentityTests(LanguageIdentityTestMixin, TestCase):
    category_type = "series"

    def _ingest(self, rows, scan_start_time=None):
        scan_start_time = scan_start_time or timezone.now()
        process_series_batch(
            self.account, rows, self.categories, self.relations,
            scan_start_time=scan_start_time,
        )
        return scan_start_time

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

    def test_retagged_category_stays_pinned_until_reconciled(self):
        rows = [{"series_id": 1, "name": "Show", "category_id": "1", "tmdb_id": "200"}]
        self._ingest(rows)
        original = Series.objects.get(tmdb_id="200")
        M3USeriesRelation.objects.filter(external_series_id="1").update(
            custom_properties={"detailed_fetched": True, "episodes_fetched": True}
        )

        self._ingest(rows)
        props = M3USeriesRelation.objects.get(external_series_id="1").custom_properties
        self.assertTrue(props["episodes_fetched"])

        self.english_rel.custom_properties = {"language": "en"}
        self.english_rel.save()
        scan_time = self._ingest(rows)

        # No fork mid-batch: the relation stays pinned to the original,
        # still-untagged series, and its fetched flags are untouched.
        relation = M3USeriesRelation.objects.get(external_series_id="1")
        self.assertEqual(relation.series_id, original.id)
        self.assertTrue(relation.custom_properties["detailed_fetched"])
        self.assertTrue(relation.custom_properties["episodes_fetched"])

        reconcile_series_language_identity(self.account, scan_start_time=scan_time)

        # Single group, no pre-existing 'en' row: rename in place. Id is
        # unchanged and nothing moved, so the fetched flags are preserved -
        # the opposite outcome from the movie disagreement case above.
        relation.refresh_from_db()
        self.assertEqual(relation.series_id, original.id)
        self.assertEqual(relation.series.language, "en")
        self.assertTrue(relation.custom_properties["detailed_fetched"])
        self.assertTrue(relation.custom_properties["episodes_fetched"])

    def test_reconcile_retags_already_tagged_series(self):
        rows = [{"series_id": 1, "name": "Show", "category_id": "2", "tmdb_id": "200"}]
        self._ingest(rows)
        spanish = Series.objects.get(tmdb_id="200", language="es")

        self.spanish_rel.custom_properties = {"language": "fr"}
        self.spanish_rel.save()
        scan_time = self._ingest(rows)

        reconcile_series_language_identity(self.account, scan_start_time=scan_time)

        spanish.refresh_from_db()
        self.assertEqual(spanish.language, "fr")
        self.assertEqual(
            M3USeriesRelation.objects.get(external_series_id="1").series_id, spanish.id
        )

    def test_reconcile_moves_episodes_without_collision(self):
        existing_target = Series.objects.create(name="Show", tmdb_id="200", language="en")

        rows = [{"series_id": 1, "name": "Show", "category_id": "1", "tmdb_id": "200"}]
        self._ingest(rows)
        original = Series.objects.get(tmdb_id="200", language="")
        episode = Episode.objects.create(
            series=original, season_number=1, episode_number=1, name="Pilot"
        )
        episode_relation = M3UEpisodeRelation.objects.create(
            m3u_account=self.account, episode=episode, stream_id="ep-1",
        )

        self.english_rel.custom_properties = {"language": "en"}
        self.english_rel.save()
        scan_time = self._ingest(rows)

        reconcile_series_language_identity(self.account, scan_start_time=scan_time)

        original.refresh_from_db()
        episode.refresh_from_db()
        episode_relation.refresh_from_db()
        self.assertEqual(original.language, "en")
        self.assertEqual(episode.series_id, original.id)
        self.assertEqual(episode_relation.episode_id, episode.id)
        self.assertFalse(Series.objects.filter(id=existing_target.id).exists())

    def test_reconcile_merges_colliding_episodes(self):
        existing_target = Series.objects.create(name="Show", tmdb_id="200", language="en")
        target_episode = Episode.objects.create(
            series=existing_target, season_number=1, episode_number=1, name="Pilot (EN)"
        )

        rows = [{"series_id": 1, "name": "Show", "category_id": "1", "tmdb_id": "200"}]
        self._ingest(rows)
        original = Series.objects.get(tmdb_id="200", language="")
        source_episode = Episode.objects.create(
            series=original, season_number=1, episode_number=1, name="Pilot"
        )
        episode_relation = M3UEpisodeRelation.objects.create(
            m3u_account=self.account, episode=source_episode, stream_id="ep-1",
        )

        self.english_rel.custom_properties = {"language": "en"}
        self.english_rel.save()
        scan_time = self._ingest(rows)

        reconcile_series_language_identity(self.account, scan_start_time=scan_time)

        original.refresh_from_db()
        episode_relation.refresh_from_db()
        self.assertEqual(original.language, "en")
        self.assertEqual(episode_relation.episode_id, source_episode.id)
        self.assertFalse(Episode.objects.filter(id=target_episode.id).exists())
        self.assertFalse(Series.objects.filter(id=existing_target.id).exists())

    def test_reconcile_full_split_gives_episodes_to_majority_target(self):
        french = VODCategory.objects.create(name="French", category_type="series")
        french_rel = M3UVODCategoryRelation.objects.create(
            category=french, m3u_account=self.account, enabled=True,
        )
        self.categories["3"] = french
        self.relations[french.id] = french_rel

        rows = [
            {"series_id": 1, "name": "Show", "category_id": "1", "tmdb_id": "200"},
            {"series_id": 2, "name": "Show", "category_id": "1", "tmdb_id": "200"},
            {"series_id": 3, "name": "Show", "category_id": "3", "tmdb_id": "200"},
        ]
        self._ingest(rows)
        original = Series.objects.get(tmdb_id="200")
        en_relation = M3USeriesRelation.objects.get(external_series_id="1")
        other_en_relation = M3USeriesRelation.objects.get(external_series_id="2")
        episode = Episode.objects.create(
            series=original, season_number=1, episode_number=1, name="Pilot"
        )
        for series_rel, stream_id in (
            (en_relation, "ep-en"),
            (other_en_relation, "ep-en-2"),
        ):
            M3UEpisodeRelation.objects.create(
                m3u_account=self.account, episode=episode, series_relation=series_rel,
                stream_id=stream_id,
            )

        self.english_rel.custom_properties = {"language": "en"}
        self.english_rel.save()
        french_rel.custom_properties = {"language": "fr"}
        french_rel.save()
        scan_time = self._ingest(rows)

        reconcile_series_language_identity(self.account, scan_start_time=scan_time)

        original.refresh_from_db()
        episode.refresh_from_db()
        fr_target = Series.objects.get(tmdb_id="200", language="fr")
        self.assertEqual(original.language, "en")
        self.assertEqual(episode.series_id, original.id)
        self.assertEqual(fr_target.episodes.count(), 0)

    def test_reconcile_splits_episode_relations_by_series_relation(self):
        french = VODCategory.objects.create(name="French Split", category_type="series")
        french_rel = M3UVODCategoryRelation.objects.create(
            category=french, m3u_account=self.account, enabled=True,
        )
        self.categories["3"] = french
        self.relations[french.id] = french_rel

        rows = [
            {"series_id": 1, "name": "Show", "category_id": "1", "tmdb_id": "200"},
            {"series_id": 2, "name": "Show", "category_id": "1", "tmdb_id": "200"},
            {"series_id": 3, "name": "Show", "category_id": "3", "tmdb_id": "200"},
        ]
        self._ingest(rows)
        original = Series.objects.get(tmdb_id="200")
        en_relation = M3USeriesRelation.objects.get(external_series_id="1")
        other_en_relation = M3USeriesRelation.objects.get(external_series_id="2")
        fr_relation = M3USeriesRelation.objects.get(external_series_id="3")
        episode = Episode.objects.create(
            series=original, season_number=1, episode_number=1, name="Pilot"
        )
        en_episode_rel = M3UEpisodeRelation.objects.create(
            m3u_account=self.account, episode=episode, series_relation=en_relation, stream_id="ep-en",
        )
        other_en_episode_rel = M3UEpisodeRelation.objects.create(
            m3u_account=self.account, episode=episode, series_relation=other_en_relation,
            stream_id="ep-en-2",
        )
        fr_episode_rel = M3UEpisodeRelation.objects.create(
            m3u_account=self.account, episode=episode, series_relation=fr_relation, stream_id="ep-fr",
        )

        self.english_rel.custom_properties = {"language": "en"}
        self.english_rel.save()
        french_rel.custom_properties = {"language": "fr"}
        french_rel.save()
        scan_time = self._ingest(rows)

        reconcile_series_language_identity(self.account, scan_start_time=scan_time)

        episode.refresh_from_db()
        en_episode_rel.refresh_from_db()
        other_en_episode_rel.refresh_from_db()
        fr_episode_rel.refresh_from_db()
        self.assertEqual(episode.series_id, original.id)
        self.assertEqual(en_episode_rel.episode_id, episode.id)
        self.assertEqual(other_en_episode_rel.episode_id, episode.id)
        self.assertNotEqual(fr_episode_rel.episode_id, episode.id)
        self.assertEqual(fr_episode_rel.episode.series.language, "fr")
        self.assertEqual(fr_episode_rel.episode.episode_number, 1)

    def test_hand_off_moves_episode_streams_to_clean_home(self):
        french = VODCategory.objects.create(name="French HandOff", category_type="series")
        M3UVODCategoryRelation.objects.create(
            category=french, m3u_account=self.account, enabled=True,
            custom_properties={"language": "fr"},
        )
        now = timezone.now()
        home_es = Series.objects.create(name="Show", tmdb_id="handoff", language="es")
        home_series_rel = M3USeriesRelation.objects.create(
            m3u_account=self.account, series=home_es, category=self.spanish,
            external_series_id="home-es", last_seen=now - timedelta(days=1),
        )
        home_ep = Episode.objects.create(
            series=home_es, season_number=1, episode_number=1, name="Pilot ES",
        )
        M3UEpisodeRelation.objects.create(
            m3u_account=self.account, episode=home_ep, series_relation=home_series_rel,
            stream_id="ep-home-es",
        )
        src = Series.objects.create(name="Show", tmdb_id="handoff", language="")
        src_es_rel = M3USeriesRelation.objects.create(
            m3u_account=self.account, series=src, category=self.spanish,
            external_series_id="src-es", last_seen=now,
        )
        src_fr_rel = M3USeriesRelation.objects.create(
            m3u_account=self.account, series=src, category=french,
            external_series_id="src-fr", last_seen=now,
        )
        episode = Episode.objects.create(
            series=src, season_number=1, episode_number=1, name="Pilot",
        )
        es_ep_rel = M3UEpisodeRelation.objects.create(
            m3u_account=self.account, episode=episode, series_relation=src_es_rel,
            stream_id="ep-src-es",
        )
        fr_ep_rel = M3UEpisodeRelation.objects.create(
            m3u_account=self.account, episode=episode, series_relation=src_fr_rel,
            stream_id="ep-src-fr",
        )

        reconcile_series_language_identity(self.account, scan_start_time=now)

        src.refresh_from_db()
        home_es.refresh_from_db()
        es_ep_rel.refresh_from_db()
        fr_ep_rel.refresh_from_db()
        self.assertEqual(src.language, "fr")
        self.assertEqual(home_es.language, "es")
        self.assertEqual(
            M3USeriesRelation.objects.get(external_series_id="src-es").series_id, home_es.id
        )
        self.assertEqual(
            M3USeriesRelation.objects.get(external_series_id="src-fr").series_id, src.id
        )
        self.assertEqual(es_ep_rel.episode.series_id, home_es.id)
        self.assertEqual(es_ep_rel.episode.episode_number, 1)
        self.assertEqual(fr_ep_rel.episode.series_id, src.id)
        self.assertEqual(fr_ep_rel.episode_id, episode.id)

    def test_split_deletes_episode_when_every_stream_hits_a_collision(self):
        french = VODCategory.objects.create(name="French Empty Ep", category_type="series")
        M3UVODCategoryRelation.objects.create(
            category=french, m3u_account=self.account, enabled=True,
            custom_properties={"language": "fr"},
        )
        now = timezone.now()
        home_es = Series.objects.create(name="Show", tmdb_id="empty-ep", language="es")
        home_series_rel = M3USeriesRelation.objects.create(
            m3u_account=self.account, series=home_es, category=self.spanish,
            external_series_id="home-es", last_seen=now - timedelta(days=1),
        )
        home_ep = Episode.objects.create(
            series=home_es, season_number=1, episode_number=1, name="Pilot ES",
        )
        M3UEpisodeRelation.objects.create(
            m3u_account=self.account, episode=home_ep, series_relation=home_series_rel,
            stream_id="ep-home-es",
        )
        src = Series.objects.create(name="Show", tmdb_id="empty-ep", language="")
        src_es_rel = M3USeriesRelation.objects.create(
            m3u_account=self.account, series=src, category=self.spanish,
            external_series_id="src-es", last_seen=now,
        )
        M3USeriesRelation.objects.create(
            m3u_account=self.account, series=src, category=french,
            external_series_id="src-fr", last_seen=now,
        )
        episode = Episode.objects.create(
            series=src, season_number=1, episode_number=1, name="Pilot",
        )
        es_ep_rel = M3UEpisodeRelation.objects.create(
            m3u_account=self.account, episode=episode, series_relation=src_es_rel,
            stream_id="ep-src-es",
        )

        reconcile_series_language_identity(self.account, scan_start_time=now)

        src.refresh_from_db()
        es_ep_rel.refresh_from_db()
        self.assertEqual(src.language, "fr")
        self.assertFalse(Episode.objects.filter(id=episode.id).exists())
        self.assertEqual(es_ep_rel.episode_id, home_ep.id)
        self.assertEqual(Episode.objects.filter(series=src).count(), 0)
        self.assertEqual(Episode.objects.filter(series=home_es).count(), 1)

    def test_split_keeps_episode_when_a_stream_stays_after_collision(self):
        french = VODCategory.objects.create(name="French Keep Ep", category_type="series")
        M3UVODCategoryRelation.objects.create(
            category=french, m3u_account=self.account, enabled=True,
            custom_properties={"language": "fr"},
        )
        now = timezone.now()
        src = Series.objects.create(name="Show", tmdb_id="keep-ep", language="")
        src_es_rel = M3USeriesRelation.objects.create(
            m3u_account=self.account, series=src, category=self.spanish,
            external_series_id="src-es", last_seen=now,
        )
        src_fr_rel = M3USeriesRelation.objects.create(
            m3u_account=self.account, series=src, category=french,
            external_series_id="src-fr", last_seen=now,
        )
        home_es = Series.objects.create(name="Show", tmdb_id="keep-ep", language="es")
        home_series_rel = M3USeriesRelation.objects.create(
            m3u_account=self.account, series=home_es, category=self.spanish,
            external_series_id="home-es", last_seen=now - timedelta(days=1),
        )
        home_ep = Episode.objects.create(
            series=home_es, season_number=1, episode_number=1, name="Pilot ES",
        )
        episode = Episode.objects.create(
            series=src, season_number=1, episode_number=1, name="Pilot",
        )
        es_rels = []
        for stream_id, series_rel in (("ep-src-es-1", src_es_rel), ("ep-src-es-2", src_es_rel)):
            es_rels.append(M3UEpisodeRelation.objects.create(
                m3u_account=self.account, episode=episode, series_relation=series_rel,
                stream_id=stream_id,
            ))
        fr_ep_rel = M3UEpisodeRelation.objects.create(
            m3u_account=self.account, episode=episode, series_relation=src_fr_rel,
            stream_id="ep-src-fr",
        )
        M3UEpisodeRelation.objects.create(
            m3u_account=self.account, episode=home_ep, series_relation=home_series_rel,
            stream_id="ep-home-es",
        )

        reconcile_series_language_identity(self.account, scan_start_time=now)

        episode.refresh_from_db()
        fr_ep_rel.refresh_from_db()
        for rel in es_rels:
            rel.refresh_from_db()
        self.assertEqual(episode.series_id, src.id)
        self.assertEqual(fr_ep_rel.episode_id, episode.id)
        self.assertEqual(
            {rel.episode_id for rel in es_rels},
            {home_ep.id},
        )

    def test_split_deletes_already_empty_episodes(self):
        now = timezone.now()
        src = Series.objects.create(name="Show", tmdb_id="orphan-ep", language="")
        M3USeriesRelation.objects.create(
            m3u_account=self.account, series=src, category=self.spanish,
            external_series_id="src-es", last_seen=now,
        )
        orphan = Episode.objects.create(
            series=src, season_number=1, episode_number=1, name="Orphan",
        )
        kept = Episode.objects.create(
            series=src, season_number=1, episode_number=2, name="Kept",
        )
        series_rel = M3USeriesRelation.objects.get(external_series_id="src-es")
        M3UEpisodeRelation.objects.create(
            m3u_account=self.account, episode=kept, series_relation=series_rel,
            stream_id="ep-kept",
        )

        reconcile_series_language_identity(self.account, scan_start_time=now)

        src.refresh_from_db()
        self.assertEqual(src.language, "es")
        self.assertFalse(Episode.objects.filter(id=orphan.id).exists())
        self.assertTrue(Episode.objects.filter(id=kept.id, series=src).exists())


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
        rows = {
            row["series_id"]: row["name"]
            for row in xc_get_series(self.request, self.user)
            if row["name"].startswith("Show")
        }
        self.assertEqual(
            rows,
            {self.english.id: "Show", self.spanish.id: "Show [ES]"},
        )

    def test_series_info_resolves_series_id(self):
        info = xc_get_series_info(self.request, self.user, str(self.spanish.id))
        self.assertEqual(info["info"]["name"], "Show [ES]")
        self.assertEqual(info["info"]["tmdb"], "300")

    def test_series_info_unknown_id_is_404(self):
        from django.http import Http404

        for series_id in ("999999", "not-a-number"):
            with self.subTest(series_id=series_id), self.assertRaises(Http404):
                xc_get_series_info(self.request, self.user, series_id)
