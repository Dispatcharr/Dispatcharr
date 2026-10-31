"""Inclusive date ranges share the canonical/provider metadata precedence."""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from apps.vod import library
from apps.vod.models import M3UMovieRelation, M3USeriesRelation, Movie, Series

from . import test_library as fixtures


class LibraryDateRangeTests(TestCase):
    setUp = fixtures.LibraryTests.setUp
    endpoint = fixtures.LibraryTests.endpoint

    def test_year_only_edits_do_not_invent_release_dates_for_movies_or_series(self):
        series = Series.objects.create(name="Year-only series", year=2020)
        M3USeriesRelation.objects.create(
            m3u_account=self.account, series=series, external_series_id="year-only"
        )
        for kind, content in (("movie", self.movie), ("series", series)):
            with self.subTest(kind=kind):
                response = self.client.patch(
                    self.endpoint("content"),
                    {"content_type": kind, "id": content.pk, "year": 2021},
                    format="json",
                )
                self.assertEqual(response.status_code, 200, response.data)
                document = response.data["metadata"]
                self.assertEqual(document["year"], 2021)
                self.assertFalse(document["metadata"].get("release_date"))
                content.refresh_from_db()
                self.assertEqual(content.year, 2020)
                self.assertEqual(
                    content.tmdb_metadata["_manual_overrides"]["year"], 2021
                )
                for view in ("titles", "sources"):
                    result = self.client.get(
                        self.endpoint(),
                        {
                            "view": view,
                            "type": kind,
                            "released_since": "2021-01-01",
                            "released_until": "2021-01-01",
                        },
                    )
                    self.assertEqual(result.status_code, 200, result.data)
                    self.assertEqual(result.data["count"], 0)

    def test_known_release_date_is_kept_and_conflicting_year_is_not_silently_saved(
        self,
    ):
        for location in ("tmdb_metadata", "custom_properties"):
            with self.subTest(location=location):
                Movie.objects.filter(pk=self.movie.pk).update(
                    tmdb_metadata={}, custom_properties={}
                )
                Movie.objects.filter(pk=self.movie.pk).update(
                    **{location: {"release_date": "2020-08-19"}}
                )
                response = self.client.patch(
                    self.endpoint("content"),
                    {"content_type": "movie", "id": self.movie.pk, "year": 2020},
                    format="json",
                )
                self.assertEqual(response.status_code, 200, response.data)
                self.assertEqual(
                    response.data["metadata"]["metadata"]["release_date"],
                    "2020-08-19",
                )
                response = self.client.patch(
                    self.endpoint("content"),
                    {"content_type": "movie", "id": self.movie.pk, "year": 2021},
                    format="json",
                )
                self.assertEqual(response.status_code, 400, response.data)
                self.assertIn("year", response.data)
                self.movie.refresh_from_db()
                self.assertEqual(library.canonical_document(self.movie)["year"], 2020)

    def test_release_date_can_be_cleared_without_losing_the_explicit_year(self):
        self.movie.tmdb_metadata = {"release_date": "2020-08-19"}
        self.movie.save()
        response = self.client.patch(
            self.endpoint("content"),
            {
                "content_type": "movie",
                "id": self.movie.pk,
                "year": 2021,
                "metadata": {"release_date": None},
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["metadata"]["year"], 2021)
        self.assertEqual(response.data["metadata"]["metadata"]["release_date"], "")

    def test_an_explicit_release_date_supersedes_a_previous_year_only_edit(self):
        library.update_content(
            {"content_type": "movie", "id": self.movie.pk, "year": 2021}
        )
        response = self.client.patch(
            self.endpoint("content"),
            {
                "content_type": "movie",
                "id": self.movie.pk,
                "metadata": {"release_date": "2022-08-19"},
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["metadata"]["year"], 2022)
        self.assertEqual(
            response.data["metadata"]["metadata"]["release_date"], "2022-08-19"
        )
        for year, count in ((2022, 1), (2021, 0)):
            results = library.canonical_targets(
                {"content_type": "movie", "query": "Film", "year": year}
            )
            self.assertEqual(len(results), count)

    def test_manual_year_survives_enrichment_and_is_used_in_target_search(self):
        library.update_content(
            {"content_type": "movie", "id": self.movie.pk, "year": 2021}
        )
        self.movie.refresh_from_db()
        library.apply_tmdb(self.movie, {"id": "123", "release_date": "2021-08-19"})
        self.movie.refresh_from_db()
        self.assertEqual(library.canonical_document(self.movie)["year"], 2021)
        for year, count in ((2021, 1), (2020, 0)):
            results = library.canonical_targets(
                {"content_type": "movie", "query": "Film", "year": year}
            )
            self.assertEqual(len(results), count)

    def test_added_dates_use_first_import_and_include_both_boundaries(self):
        day = timezone.localdate()
        Movie.objects.filter(pk=self.movie.pk).update(
            library_added_at=timezone.now() - timedelta(days=3)
        )
        for offset, expected in ((3, 1), (2, 0), (4, 0)):
            date = (day - timedelta(days=offset)).isoformat()
            for view in ("titles", "sources"):
                response = self.client.get(
                    self.endpoint(),
                    {"view": view, "added_since": date, "added_until": date},
                )
                self.assertEqual(response.status_code, 200, response.data)
                self.assertEqual(response.data["count"], expected)

    def test_release_dates_prefer_metadata_and_do_not_invent_a_date_from_year(self):
        cases = [
            ({"release_date": "2020-02-15"}, {"release_date": "1990-01-01"}, 1),
            ({"release_date": "1990-01-01"}, {"release_date": "2020-02-15"}, 0),
            ({}, {"release_date": "2020-02-15"}, 1),
            ({"release_date": ""}, {"release_date": "2020-02-15"}, 0),
            ({"release_date": None}, {"release_date": "2020-02-15"}, 0),
            ({}, {"release_date": "2020"}, 0),
            ({}, {"release_date": "not-a-date"}, 0),
        ]
        for metadata, provider, expected in cases:
            with self.subTest(metadata=metadata, provider=provider):
                Movie.objects.filter(pk=self.movie.pk).update(
                    tmdb_metadata=metadata, custom_properties=provider, year=2020
                )
                for view in ("titles", "sources"):
                    response = self.client.get(
                        self.endpoint(),
                        {
                            "view": view,
                            "released_since": "2020-02-15",
                            "released_until": "2020-02-15",
                        },
                    )
                    self.assertEqual(response.status_code, 200, response.data)
                    self.assertEqual(response.data["count"], expected)

    def test_reversed_ranges_are_validation_errors_for_reads_and_bulk_filters(self):
        for start, end in (
            ("added_since", "added_until"),
            ("released_since", "released_until"),
        ):
            filters = {start: "2026-10-31", end: "2026-10-01"}
            self.assertEqual(self.client.get(self.endpoint(), filters).status_code, 400)
            response = self.client.post(
                self.endpoint("bulk"),
                {"all_matching": True, "filters": filters, "operation": "block"},
                format="json",
            )
            self.assertEqual(response.status_code, 400, response.data)
        self.movie.refresh_from_db()
        self.assertFalse(self.movie.library_blocked)

    def test_filtered_bulk_actions_use_the_same_release_date_range(self):
        self.movie.tmdb_metadata = {"release_date": "2020-01-01"}
        self.movie.save()
        outside = Movie.objects.create(
            name="Outside range", tmdb_metadata={"release_date": "2021-01-01"}
        )
        M3UMovieRelation.objects.create(
            m3u_account=self.account, movie=outside, stream_id="outside"
        )
        response = self.client.post(
            self.endpoint("bulk"),
            {
                "all_matching": True,
                "filters": {
                    "released_since": "2020-01-01",
                    "released_until": "2020-12-31",
                },
                "operation": "block",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["count"], 1)
        self.movie.refresh_from_db()
        outside.refresh_from_db()
        self.assertTrue(self.movie.library_blocked)
        self.assertFalse(outside.library_blocked)
