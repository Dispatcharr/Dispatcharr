"""One title precedence for Library presentation and XC output."""

from django.db import connection
from django.test import RequestFactory, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.output.views import (
    xc_get_series,
    xc_get_series_info,
    xc_get_vod_info,
    xc_get_vod_streams,
)
from apps.vod import library
from apps.vod.metadata import effective_source_metadata, metadata_suffix
from apps.vod.models import M3UMovieRelation, M3USeriesRelation, Movie, Series
from apps.vod.presentation import canonical_title, canonical_title_expression
from apps.vod.serializers import MovieSerializer, SeriesSerializer

from . import test_library as fixtures


@override_settings(
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
)
class LibraryPresentationTests(TestCase):
    endpoint = fixtures.LibraryTests.endpoint

    def setUp(self):
        fixtures.LibraryTests.setUp(self)
        self.source.last_advanced_refresh = timezone.now()
        self.source.custom_properties = {
            "basic_data": {"name": "Movie source original"},
            "detailed_fetched": True,
            "detailed_info": {"name": "Provider detail must not win"},
        }
        self.source.save()
        self.series = Series.objects.create(name="Series base", year=2020)
        self.series_source = M3USeriesRelation.objects.create(
            m3u_account=self.account,
            series=self.series,
            external_series_id="20",
            last_episode_refresh=timezone.now(),
            custom_properties={
                "basic_data": {"name": "Series source original"},
                "episodes_fetched": True,
                "detailed_fetched": True,
                "detailed_info": {"name": "Provider detail must not win"},
            },
        )
        self.request = RequestFactory().get("/player_api.php")

    def test_precedence_matches_python_sql_serializers_and_xc_for_both_kinds(self):
        languages = ["de-DE", "en-US"]
        library.save_library_settings({"languages": languages})
        for kind, content, source, serializer, catalogue, detail in (
            (
                "movie",
                self.movie,
                self.source,
                MovieSerializer,
                xc_get_vod_streams,
                xc_get_vod_info,
            ),
            (
                "series",
                self.series,
                self.series_source,
                SeriesSerializer,
                xc_get_series,
                xc_get_series_info,
            ),
        ):
            for manual, translations, cleaned, expected in (
                (
                    "Manual title",
                    {"de-DE": {"title": "Deutsch"}},
                    "Clean",
                    "Manual title",
                ),
                (
                    "",
                    {"de-DE": {"title": "Deutsch"}, "en-US": {"title": "English"}},
                    "Clean",
                    "Deutsch",
                ),
                (
                    "",
                    {"de-DE": {"title": " "}, "en-US": {"title": "English"}},
                    "Clean",
                    "English",
                ),
                ("", {"fr-FR": {"title": "Not configured"}}, "Clean", "Clean"),
                (" ", {"de-DE": {"title": ""}}, " ", content.name),
            ):
                with self.subTest(kind=kind, expected=expected):
                    content.display_name = manual
                    content.clean_title = cleaned
                    content.tmdb_metadata = {"localized": translations}
                    content.save()
                    raw_before = type(content).objects.values().get(pk=content.pk)
                    source_before = type(source).objects.values().get(pk=source.pk)
                    self.assertEqual(canonical_title(content, languages), expected)
                    self.assertEqual(
                        type(content)
                        .objects.annotate(
                            presented=canonical_title_expression("", languages)
                        )
                        .get(pk=content.pk)
                        .presented,
                        expected,
                    )
                    self.assertEqual(
                        library.canonical_document(content)["name"], expected
                    )
                    self.assertEqual(serializer(content).data["name"], expected)
                    rows = self.client.get(self.endpoint(), {"type": kind}).json()[
                        "results"
                    ]
                    self.assertEqual(rows[0]["name"], expected)
                    self.assertEqual(rows[0]["provider_name"], content.name)
                    source_rows = self.client.get(
                        self.endpoint(), {"type": kind, "view": "sources"}
                    ).json()["results"]
                    self.assertEqual(
                        source_rows[0]["provider_name"],
                        f"{kind.title()} source original",
                    )
                    output_title = metadata_suffix(
                        expected, effective_source_metadata(source)["values"]
                    )
                    self.assertEqual(
                        catalogue(self.request, self.admin)[0]["name"], output_title
                    )
                    info = detail(self.request, self.admin, str(content.pk))
                    self.assertEqual(info["info"]["name"], output_title)
                    if kind == "movie":
                        self.assertEqual(info["info"]["o_name"], output_title)
                        self.assertEqual(info["movie_data"]["name"], output_title)
                    self.assertEqual(
                        raw_before, type(content).objects.values().get(pk=content.pk)
                    )
                    self.assertEqual(
                        source_before, type(source).objects.values().get(pk=source.pk)
                    )

    def test_language_order_changes_presentation_not_identity_or_stored_metadata(self):
        self.movie.clean_title = "Clean title"
        self.movie.tmdb_metadata = {
            "localized": {
                "de-DE": {"title": "Deutsch"},
                "en-US": {"title": "English"},
            }
        }
        self.movie.save()
        before = Movie.objects.values().get(pk=self.movie.pk)
        output_ids = []
        for languages, expected in (
            (["de-DE", "en-US"], "Deutsch"),
            (["en-US", "de-DE"], "English"),
        ):
            library.save_library_settings({"languages": languages})
            self.assertEqual(
                self.client.get(self.endpoint(), {"type": "movie"}).json()["results"][
                    0
                ]["name"],
                expected,
            )
            stream = xc_get_vod_streams(self.request, self.admin)[0]
            self.assertEqual(stream["name"], f"{expected} [ENG]")
            output_ids.append(stream["stream_id"])
        self.assertEqual(output_ids[0], output_ids[1])
        self.assertEqual(before, Movie.objects.values().get(pk=self.movie.pk))

    def test_localized_titles_are_searchable_and_sorted_in_library_and_xc(self):
        library.save_library_settings({"languages": ["de-DE", "en-US"]})
        self.movie.tmdb_metadata = {"localized": {"de-DE": {"title": "Zulu"}}}
        self.movie.save()
        other = Movie.objects.create(
            name="Zulu raw", tmdb_metadata={"localized": {"de-DE": {"title": "Alpha"}}}
        )
        M3UMovieRelation.objects.create(
            m3u_account=self.account, movie=other, stream_id="11"
        )
        rows = self.client.get(self.endpoint(), {"type": "movie"}).json()["results"]
        self.assertEqual([row["name"] for row in rows], ["Alpha", "Zulu"])
        self.assertEqual(
            [row["name"] for row in xc_get_vod_streams(self.request, self.admin)],
            ["Alpha", "Zulu [ENG]"],
        )
        for view in ("titles", "sources"):
            rows = self.client.get(
                self.endpoint(), {"type": "movie", "view": view, "search": "Alpha"}
            ).json()["results"]
            self.assertEqual([row["content_id"] for row in rows], [other.pk])
        targets = library.canonical_targets({"content_type": "movie", "query": "Alpha"})
        self.assertEqual(
            [(row["id"], row["name"]) for row in targets], [(other.pk, "Alpha")]
        )

    def test_enriched_filter_distinguishes_loaded_metadata_from_ids_and_status(self):
        self.movie.tmdb_id = "123"
        self.movie.tmdb_status = "matched"
        self.movie.save()
        for kind, content in (("movie", self.movie), ("series", self.series)):
            for enriched in (False, True):
                content.tmdb_enriched_at = timezone.now() if enriched else None
                content.tmdb_status = "failed" if enriched else "matched"
                content.save()
                for view in ("titles", "sources"):
                    for status, wanted in (
                        ("enriched", enriched),
                        ("missing_metadata", not enriched),
                    ):
                        response = self.client.get(
                            self.endpoint(),
                            {"type": kind, "view": view, "metadata_status": status},
                        )
                        self.assertEqual(response.status_code, 200, response.data)
                        self.assertEqual(
                            response.json()["count"], int(wanted), (kind, view, status)
                        )

    def test_xc_list_still_deduplicates_before_fetching_lean_display_columns(self):
        if connection.vendor != "postgresql":
            self.skipTest("PostgreSQL query shape")
        self.movie.tmdb_metadata = {"localized": {"en-US": {"title": "Translated"}}}
        self.movie.save()
        with CaptureQueriesContext(connection) as queries:
            xc_get_vod_streams(self.request, self.admin)
        dedupe = [query["sql"] for query in queries if "DISTINCT ON" in query["sql"]]
        self.assertEqual(len(dedupe), 1)
        self.assertNotIn('"vod_movie"', dedupe[0])
        fetch = next(
            query["sql"] for query in queries if 'AS "_library_title"' in query["sql"]
        )
        self.assertIn("tmdb_metadata", fetch)
        self.assertNotIn('"vod_movie"."tmdb_metadata",', fetch)
